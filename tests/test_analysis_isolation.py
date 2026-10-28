"""WO-017 hostile-code tests against a real Docker engine and the pinned worker image.

No mocks. Skips without IDX_ANALYSIS_IMAGE, fails instead under IDX_REQUIRE_CONTAINER=1.
Probes report through `other` figures (1.0 = the forbidden thing worked, 0.0 = it
was refused), so a broken boundary gives a distinguishable answer, not a failure.
"""

import json
import os
import shutil
import statistics
import subprocess
import threading
import time
from datetime import date

import pytest

from idx_agent.analysis import executor
from idx_agent.analysis.executor import run_analysis, run_worker
from idx_agent.analysis.verify import verify_figures
from idx_agent.domain.analysis import make_analysis_sample
from idx_agent.domain.analysis_worker import ExecutorConfig
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

pytestmark = pytest.mark.container

SENTINEL = "IDX_ISOLATION_SENTINEL"

PRELUDE = """
def _out(**flags):
    return {
        "version": 1,
        "figures": [
            {"label": k, "kind": "other", "x": None, "y": None, "value": float(v)}
            for k, v in flags.items()
        ],
        "chart": None,
    }
"""


def _sample():
    dates = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
    scope = MarketStatsRequest(city="Pasadena", property_subtype="Condominium")
    window = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
    rows = [
        SoldComp(
            listing_key=key,
            address=f"{key} Invented Way",
            city="Pasadena",
            postal_code="91101",
            close_date=date(2026, 9, 1),
            close_price=600_000 + 25_000 * key,
            list_price=620_000 + 20_000 * key,
            living_area=900 + 50 * key,
            days_on_market=3 * key,
            property_subtype="Condominium",
        )
        for key in range(1, 13)
    ]
    return make_analysis_sample(rows, scope, window, dates)


SAMPLE = _sample()


@pytest.fixture(scope="module")
def worker() -> ExecutorConfig:
    required = os.environ.get("IDX_REQUIRE_CONTAINER") == "1"
    reason = None
    config = None
    try:
        config = ExecutorConfig.from_env(os.environ)
    except ValueError:
        reason = "IDX_ANALYSIS_IMAGE is not pinned by digest"
    if config is None and reason is None:
        reason = "IDX_ANALYSIS_IMAGE is unset"
    elif config is not None and not executor.available(config):
        reason = "the pinned analysis image or the docker engine is unavailable"
    if reason is not None:
        if required:
            pytest.fail(f"IDX_REQUIRE_CONTAINER=1 but {reason}")
        pytest.skip(reason)
    return config


def _leftovers(config: ExecutorConfig) -> str:
    done = subprocess.run(
        [config.docker, "ps", "-a", "-q", "--filter", "name=idx-analysis-"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def no_container_left(worker):
    assert _leftovers(worker) == ""
    yield
    assert _leftovers(worker) == ""


def faster(config: ExecutorConfig, seconds: float) -> ExecutorConfig:
    return config.model_copy(update={"wall_clock_s": seconds})


def probe(config: ExecutorConfig, body: str) -> dict[str, float]:
    run = run_analysis(config, SAMPLE, PRELUDE + body)
    assert run.status == "ok", run.status
    return {f.label: f.value for f in run.output.figures}


# --- the happy path -----------------------------------------------------------


def test_mean_is_computed_and_verified(worker):
    code = """
prices = [r["close_price"] for r in rows]
result = {
    "version": 1,
    "figures": [
        {"label": "mean_price", "kind": "mean", "x": "close_price", "y": None,
         "value": sum(prices) / len(prices)},
        {"label": "n", "kind": "count", "x": "close_price", "y": None,
         "value": float(len(prices))},
    ],
    "chart": {"kind": "scatter", "x": "days_on_market", "y": "close_price"},
}
"""
    run = run_analysis(worker, SAMPLE, code)
    assert run.status == "ok"
    assert run.duration_s < 10
    trusted = statistics.mean(r.close_price for r in SAMPLE.rows)
    assert run.output.figures[0].value == pytest.approx(trusted)
    checks = verify_figures(SAMPLE, run.output)
    assert [c.status for c in checks] == ["verified", "verified"]
    assert run.output.chart.kind == "scatter"


def test_worker_sees_only_numeric_rows(worker):
    flags = probe(
        worker,
        """
import json
text = open("/input/sample.json").read()
keys = set().union(*[set(r) for r in rows])
allowed = {"close_price", "list_price", "original_list_price", "living_area",
           "days_on_market"}
result = _out(rows=len(rows), extra_keys=len(keys - allowed),
              place="Pasadena" in text or "Invented" in text,
              inputs=len(__import__("os").listdir("/input")))
""",
    )
    assert flags == {"rows": 12.0, "extra_keys": 0.0, "place": 0.0, "inputs": 2.0}


# --- filesystem, network, identity ----------------------------------------------


def test_outbound_network_is_refused(worker):
    flags = probe(
        worker,
        """
import socket
def tcp():
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        return 1
    except OSError:
        return 0
def dns():
    try:
        socket.getaddrinfo("pypi.org", 443)
        return 1
    except OSError:
        return 0
def udp():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.sendto(b"x", ("8.8.8.8", 53))
        return 1
    except OSError:
        return 0
ifaces = [name for _, name in socket.if_nameindex()]
result = _out(tcp=tcp(), dns=dns(), udp=udp(), non_loopback=len(
    [i for i in ifaces if i != "lo"]))
""",
    )
    assert flags == {"tcp": 0.0, "dns": 0.0, "udp": 0.0, "non_loopback": 0.0}


def test_root_and_input_are_read_only(worker):
    flags = probe(
        worker,
        """
def can_write(path):
    try:
        with open(path, "w") as handle:
            handle.write("x")
        return 1
    except OSError:
        return 0
result = _out(
    root=can_write("/evil"),
    etc=can_write("/etc/evil"),
    worker=can_write("/opt/worker/bootstrap.py"),
    input_new=can_write("/input/new.txt"),
    input_code=can_write("/input/analysis.py"),
    tmp=can_write("/tmp/fine.txt"),
)
""",
    )
    assert flags == {
        "root": 0.0,
        "etc": 0.0,
        "worker": 0.0,
        "input_new": 0.0,
        "input_code": 0.0,
        "tmp": 1.0,
    }


def test_tmp_is_bounded_at_16_mb(worker):
    flags = probe(
        worker,
        """
def fill(path, megabytes):
    try:
        with open(path, "wb") as handle:
            for _ in range(megabytes):
                handle.write(b"x" * (1 << 20))
        return 1
    except OSError:
        return 0
small = fill("/tmp/small.bin", 1)
__import__("os").remove("/tmp/small.bin")
result = _out(small=small, big=fill("/tmp/big.bin", 20))
""",
    )
    assert flags == {"small": 1.0, "big": 0.0}


def test_files_in_tmp_cannot_be_executed(worker):
    flags = probe(
        worker,
        """
import os, shutil, subprocess, sys
def runs(path):
    try:
        return int(subprocess.run([path], timeout=5).returncode == 0)
    except OSError:
        return 0
with open("/tmp/x.sh", "w") as handle:
    handle.write("#!/bin/sh\\nexit 0\\n")
os.chmod("/tmp/x.sh", 0o755)
shutil.copy(sys.executable, "/tmp/py")
os.chmod("/tmp/py", 0o755)
result = _out(script=runs("/tmp/x.sh"), binary=runs("/tmp/py"))
""",
    )
    assert flags == {"script": 0.0, "binary": 0.0}


def test_host_environment_is_absent(worker, monkeypatch):
    monkeypatch.setenv(SENTINEL, "host-only-value")
    image_env = subprocess.run(
        [
            worker.docker,
            "image",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            worker.image,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    names = {item.split("=", 1)[0] for item in json.loads(image_env.stdout)}
    names |= {"HOSTNAME", "HOME"}  # set by the engine for every container
    flags = probe(
        worker,
        f"""
import os
allowed = {sorted(names)!r}
result = _out(
    sentinel=int({SENTINEL!r} in os.environ),
    value=int(any("host-only-value" in v for v in os.environ.values())),
    unexpected=len(set(os.environ) - set(allowed)),
)
""",
    )
    assert flags == {"sentinel": 0.0, "value": 0.0, "unexpected": 0.0}


def test_no_docker_socket_and_nobody_user(worker):
    flags = probe(
        worker,
        """
import os
caps = [l for l in open("/proc/self/status") if l.startswith("CapEff")][0]
nnp = [l for l in open("/proc/self/status") if l.startswith("NoNewPrivs")][0]
result = _out(
    sock=os.path.exists("/var/run/docker.sock") or os.path.exists("/run/docker.sock"),
    uid=os.getuid(), gid=os.getgid(), euid=os.geteuid(),
    caps=int(caps.split()[1], 16), nnp=int(nnp.split()[1]),
)
""",
    )
    assert flags == {
        "sock": 0.0,
        "uid": 65534.0,
        "gid": 65534.0,
        "euid": 65534.0,
        "caps": 0.0,
        "nnp": 1.0,
    }


# --- resource exhaustion ----------------------------------------------------------


def test_process_count_is_bounded(worker):
    flags = probe(
        worker,
        """
import os, time
count = 0
try:
    while count < 500:
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        count += 1
except OSError:
    pass
result = _out(children=count)
""",
    )
    assert 0 < flags["children"] < 64


def test_fork_bomb_ends_within_the_deadline(worker):
    started = time.monotonic()
    run = run_analysis(
        faster(worker, 5),
        SAMPLE,
        """
import os
while True:
    try:
        os.fork()
    except OSError:
        pass
""",
    )
    assert run.status in ("timeout", "failed")
    assert time.monotonic() - started < 5 + 10
    assert executor.available(worker)  # the engine still answers


def test_memory_is_capped(worker):
    started = time.monotonic()
    run = run_worker(
        worker,
        "bootstrap.py",
        {
            "sample.json": b"[]",
            "analysis.py": b"block = b'x' * (600 * 1024 * 1024)\nresult = {}",
        },
    )
    assert run.status == "failed"
    assert run.exit_code in (137, 3)  # OOM kill, or MemoryError caught by bootstrap
    assert time.monotonic() - started < 30


def test_busy_loop_times_out_and_is_removed(worker):
    started = time.monotonic()
    run = run_analysis(faster(worker, 3), SAMPLE, "while True:\n    pass\n")
    elapsed = time.monotonic() - started
    assert run.status == "timeout"
    assert 3 <= elapsed < 3 + 5


def test_stdout_flood_is_cut_off(worker):
    started = time.monotonic()
    run = run_analysis(
        worker,
        SAMPLE,
        "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n",
    )
    assert run.status == "output_too_large"
    assert time.monotonic() - started < 10


def test_stderr_flood_does_not_hang(worker):
    started = time.monotonic()
    run = run_analysis(
        worker,
        SAMPLE,
        "import sys\nwhile True:\n    sys.stderr.write('e' * 65536)\n",
    )
    assert run.status == "output_too_large"
    assert time.monotonic() - started < 10


# --- hostile output ------------------------------------------------------------------


def test_extra_printed_text_is_invalid_output(worker):
    code = PRELUDE + "print('hello')\nresult = _out(a=1)\n"
    run = run_analysis(worker, SAMPLE, code)
    assert (run.status, run.output) == ("invalid_output", None)


def test_deeply_nested_result_is_invalid_output(worker):
    code = PRELUDE + "result = _out(a=1)\nresult['x'] = [[[[[[[[[[1]]]]]]]]]]\n"
    run = run_analysis(worker, SAMPLE, code)
    assert run.status == "invalid_output"


def test_self_printed_nan_is_invalid_output(worker):
    code = (
        "import os, sys\n"
        'sys.stdout.write(\'{"version":1,"figures":[{"label":"a","kind":'
        '"other","x":null,"y":null,"value":NaN}],"chart":null}\\n\')\n'
        "sys.stdout.flush()\nos._exit(0)\n"
    )
    run = run_analysis(worker, SAMPLE, code)
    assert run.status == "invalid_output"


@pytest.mark.parametrize(
    "body",
    [
        "result = _out(a=float('nan'))",  # bootstrap refuses non-finite JSON
        "result = [1, 2]",  # not a dict
        "x = 1",  # no result bound
        "result = {'a': object()}",  # not serialisable
        "raise SystemExit(0)",
        "import sys\nr = []\nfor _ in range(100000):\n    r = [r]\nresult = {'r': r}",
    ],
)
def test_bad_results_fail_in_the_bootstrap(worker, body):
    run = run_worker(
        worker,
        "bootstrap.py",
        {"sample.json": b"[]", "analysis.py": (PRELUDE + body).encode()},
    )
    assert (run.status, run.exit_code, run.stdout) == ("failed", 3, None)


# --- concurrency and availability ---------------------------------------------------


def test_parallel_runs_do_not_share_tmp(worker):
    def code(mine: str, theirs: str) -> str:
        return PRELUDE + (
            "import os, time\n"
            f"open('/tmp/{mine}', 'w').write('x')\n"
            "time.sleep(2)\n"
            f"result = _out(theirs=os.path.exists('/tmp/{theirs}'),"
            f" mine=os.path.exists('/tmp/{mine}'))\n"
        )

    results = {}

    def go(key, mine, theirs):
        results[key] = run_analysis(worker, SAMPLE, code(mine, theirs))

    threads = [
        threading.Thread(target=go, args=("a", "marker_a", "marker_b")),
        threading.Thread(target=go, args=("b", "marker_b", "marker_a")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    for key in ("a", "b"):
        assert results[key].status == "ok"
        flags = {f.label: f.value for f in results[key].output.figures}
        assert flags == {"theirs": 0.0, "mine": 1.0}


def test_third_concurrent_run_is_busy(worker):
    statuses = []
    lock = threading.Lock()

    def go():
        run = run_analysis(
            worker, SAMPLE, PRELUDE + "import time\ntime.sleep(5)\nresult = _out(a=1)\n"
        )
        with lock:
            statuses.append(run.status)

    threads = [threading.Thread(target=go) for _ in range(3)]
    for thread in threads:
        thread.start()
        time.sleep(0.2)
    for thread in threads:
        thread.join(timeout=40)
    assert sorted(statuses) == ["busy", "ok", "ok"]


def test_unknown_image_is_unavailable_and_starts_nothing(worker):
    missing = worker.model_copy(update={"image": "sha256:" + "0" * 64})
    started = time.monotonic()
    run = run_analysis(missing, SAMPLE, "result = {}")
    assert run.status == "unavailable"
    assert time.monotonic() - started < 6


def test_missing_client_is_unavailable(worker):
    assert shutil.which("docker")
    run = run_analysis(
        worker.model_copy(update={"docker": None}), SAMPLE, "result = {}"
    )
    assert run.status == "unavailable"
