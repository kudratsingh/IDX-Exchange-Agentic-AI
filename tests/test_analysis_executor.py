"""WO-017 container executor without Docker: argv, config, pins and cleanup paths.

A fake Popen with real pipes stands in for the docker client, so the read loop,
caps, deadline and cleanup run for real while nothing is executed.
"""

import os
import re
import subprocess
import threading
import tomllib
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from idx_agent.analysis import executor
from idx_agent.analysis.executor import build_command, run_analysis, run_worker
from idx_agent.domain.analysis import make_analysis_sample
from idx_agent.domain.analysis_worker import (
    ANALYSIS_STDOUT_CAP,
    RENDER_STDOUT_CAP,
    STDERR_CAP,
    WALL_CLOCK_S,
    AnalysisRun,
    ExecutorConfig,
    WorkerRun,
)
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import MarketStatsRequest, SoldComp, StatsWindow

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "docker" / "analysis-worker"
# The python:3.11-slim digest the worker is built from (ADR-0013 base, WO-017 step 4).
BASE_DIGEST = "sha256:ae952e0a57138a4317b9b61caaa19a8217c2f356803f8d7e63aad08769950937"
IMAGE = "sha256:" + "ab" * 32
DOCKER = "/usr/bin/docker"


def config(**changes) -> ExecutorConfig:
    return ExecutorConfig(**({"image": IMAGE, "docker": DOCKER} | changes))


def sample():
    dates = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
    scope = MarketStatsRequest(city="Pasadena", property_subtype="Condominium")
    window = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
    rows = [
        SoldComp(
            listing_key=key,
            city="Pasadena",
            close_date=date(2026, 9, 1),
            close_price=700_000 + 10_000 * key,
            list_price=720_000,
            days_on_market=key,
            property_subtype="Condominium",
        )
        for key in range(1, 6)
    ]
    return make_analysis_sample(rows, scope, window, dates)


# --- argv -------------------------------------------------------------------


def test_build_command_is_pinned_exactly():
    argv = build_command(config(), "idx-analysis-0123abcd", "/tmp/in", "bootstrap.py")
    assert argv == [
        DOCKER,
        "run",
        "--rm",
        "--name",
        "idx-analysis-0123abcd",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--pids-limit",
        "64",
        "--cpus",
        "1",
        "--ipc",
        "none",
        "--log-driver",
        "none",
        "--mount",
        "type=bind,src=/tmp/in,dst=/input,readonly",
        "--stop-timeout",
        "1",
        IMAGE,
        "python",
        "-I",
        "/opt/worker/bootstrap.py",
    ]


def test_render_script_is_the_only_other_entry():
    argv = build_command(config(), "idx-analysis-00", "/tmp/in", "render.py")
    assert argv[-1] == "/opt/worker/render.py"
    with pytest.raises(ValueError):
        build_command(config(), "idx-analysis-00", "/tmp/in", "other.py")


FORBIDDEN = {
    "-e",
    "--env",
    "--env-file",
    "-p",
    "--publish",
    "-P",
    "--publish-all",
    "-v",
    "--volume",
    "--volumes-from",
    "--privileged",
    "--cap-add",
    "--device",
    "--pid",
    "--userns",
    "--entrypoint",
    "--add-host",
    "--dns",
    "-i",
    "-t",
    "--interactive",
    "--tty",
    "--gpus",
}


@pytest.mark.parametrize("script", ["bootstrap.py", "render.py"])
def test_no_forbidden_flags_and_one_mount(script):
    argv = build_command(config(), "idx-analysis-ff", "/srv/in", script)
    assert not FORBIDDEN & set(argv)
    assert not any(a.startswith(("--env", "--volume", "--publish")) for a in argv)
    assert argv.count("--mount") == 1
    assert argv.count("--tmpfs") == 1
    assert "host" not in argv  # never --network host / --ipc host


@pytest.mark.parametrize(
    "directory", ["relative/dir", "/tmp/a,dst=/etc", "/tmp/a=b", "/tmp/a\nb"]
)
def test_input_dir_must_be_absolute_and_mount_safe(directory):
    with pytest.raises(ValueError):
        build_command(config(), "idx-analysis-ab", directory, "bootstrap.py")


@pytest.mark.parametrize("name", ["other", "idx-analysis-a b", "idx-analysis-,x"])
def test_container_name_must_be_generated(name):
    with pytest.raises(ValueError):
        build_command(config(), name, "/tmp/in", "bootstrap.py")


def test_generated_names_are_unique_and_prefixed():
    names = {executor.new_name() for _ in range(50)}
    assert len(names) == 50
    assert all(re.fullmatch(r"idx-analysis-[0-9a-f]{16}", n) for n in names)


# --- config -----------------------------------------------------------------


@pytest.mark.parametrize(
    "image",
    [
        "python:3.11-slim",
        "idx-analysis-worker:local",
        "idx-analysis-worker",
        "sha256:" + "AB" * 32,
        "sha256:" + "ab" * 31,
        "sha256:" + "ab" * 33,
        "Repo@sha256:" + "ab" * 32,
        "repo:tag@sha256:" + "ab" * 32,
        "repo@sha256:" + "ab" * 16,
        "ab" * 32,
        "",
    ],
)
def test_image_must_be_pinned_by_digest(image):
    with pytest.raises(ValidationError):
        config(image=image)


@pytest.mark.parametrize(
    "image",
    [IMAGE, "ghcr.io/owner/idx-analysis-worker@sha256:" + "0f" * 32],
)
def test_pinned_image_refs_accepted(image):
    assert config(image=image).image == image


def test_limits_can_be_lowered_never_raised():
    low = config(
        wall_clock_s=3,
        analysis_stdout_cap=100,
        render_stdout_cap=200,
        stderr_cap=10,
    )
    assert (low.wall_clock_s, low.stdout_cap("bootstrap.py")) == (3, 100)
    assert low.stdout_cap("render.py") == 200
    for field, value in [
        ("wall_clock_s", WALL_CLOCK_S + 0.5),
        ("wall_clock_s", 0),
        ("analysis_stdout_cap", ANALYSIS_STDOUT_CAP + 1),
        ("render_stdout_cap", RENDER_STDOUT_CAP + 1),
        ("stderr_cap", STDERR_CAP + 1),
        ("stderr_cap", 0),
    ]:
        with pytest.raises(ValidationError):
            config(**{field: value})


def test_config_is_frozen_and_closed():
    value = config()
    with pytest.raises(ValidationError):
        value.image = "sha256:" + "cd" * 32
    with pytest.raises(ValidationError):
        config(extra_flag="--privileged")


def test_docker_path_must_be_absolute():
    with pytest.raises(ValidationError):
        config(docker="docker")
    assert config(docker=None).docker is None


def test_from_env_reads_only_the_image(monkeypatch):
    monkeypatch.setattr(executor.shutil, "which", lambda _: DOCKER)
    assert ExecutorConfig.from_env({}) is None
    assert ExecutorConfig.from_env({"IDX_ANALYSIS_IMAGE": "  "}) is None
    value = ExecutorConfig.from_env(
        {"IDX_ANALYSIS_IMAGE": IMAGE, "IDX_ANALYSIS_TIMEOUT": "999"}
    )
    assert value == ExecutorConfig(image=IMAGE, docker=DOCKER)
    with pytest.raises(ValidationError):
        ExecutorConfig.from_env({"IDX_ANALYSIS_IMAGE": "worker:latest"})


def test_result_models_keep_stdout_and_output_only_when_ok():
    with pytest.raises(ValidationError):
        WorkerRun(status="failed", stdout=b"x", duration_s=0)
    with pytest.raises(ValidationError):
        WorkerRun(status="ok", duration_s=0)
    with pytest.raises(ValidationError):
        AnalysisRun(status="ok")
    assert "stdout" not in AnalysisRun.model_fields


# --- pins in the image files ------------------------------------------------


def _requirements() -> list[str]:
    text = (WORKER_DIR / "requirements.txt").read_text()
    joined = re.sub(r"\\\n\s*", " ", text)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_every_requirement_is_pinned_with_a_hash():
    lines = _requirements()
    assert len(lines) == 12
    for line in lines:
        assert re.match(r"^[a-z0-9-]+==[0-9][0-9a-z.]* ", line)
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", line)


def test_analysis_extra_matches_the_worker_pin():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    extra = project["optional-dependencies"]["analysis"]
    pinned = [line.split()[0] for line in _requirements()]
    assert extra == ["matplotlib==3.11.2"]
    assert extra[0] in pinned
    assert not any("matplotlib" in d for d in project["dependencies"])
    assert not any("matplotlib" in d for d in project["optional-dependencies"]["dev"])


def test_dockerfile_pins_the_adr_base_and_runs_as_nobody():
    text = (WORKER_DIR / "Dockerfile").read_text()
    froms = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert froms == [f"FROM python:3.11-slim@{BASE_DIGEST}"]
    assert "--require-hashes" in text and "--no-deps" in text
    assert "--only-binary=:all:" in text
    assert "USER 65534:65534" in text
    assert "ENTRYPOINT" not in text and "CMD" not in text


def test_bootstrap_does_not_import_the_host_package():
    text = (WORKER_DIR / "bootstrap.py").read_text()
    assert "from idx_agent" not in text and "import idx_agent" not in text


# --- code validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "code, reason",
    [
        (b"result = {}", "code_not_text"),
        (None, "code_not_text"),
        ("x = 1\n" * 5000, "code_too_long"),
        ("result = {}\x00", "code_has_nul"),
        ("result = '\ud800'", "code_not_utf8"),
    ],
)
def test_invalid_code_never_starts_a_run(monkeypatch, code, reason):
    monkeypatch.setattr(executor, "run_worker", _never)
    run = run_analysis(config(), sample(), code)
    assert (run.status, run.reason, run.output) == ("invalid_code", reason, None)


def test_code_at_the_limit_is_accepted(monkeypatch):
    seen = {}

    def fake(cfg, script, files, cap):
        seen.update(files)
        return WorkerRun(status="failed", exit_code=3, duration_s=0)

    monkeypatch.setattr(executor, "run_worker", fake)
    code = "#" * executor.MAX_CODE_CHARS
    assert run_analysis(config(), sample(), code).status == "failed"
    assert set(seen) == {"sample.json", "analysis.py"}
    assert b"Pasadena" not in seen["sample.json"]


def _never(*args, **kwargs):
    raise AssertionError("must not be called")


# --- run_worker with a fake docker client -------------------------------------


class Calls:
    def __init__(self):
        self.run: list[list[str]] = []
        self.popen: list[list[str]] = []
        self.dirs: list[str] = []


class FakeProcess:
    """Real pipes, no process. `hang` keeps them open until kill()."""

    def __init__(self, out=b"", err=b"", code=0, hang=False):
        self._out_r, self._out_w = os.pipe()
        self._err_r, self._err_w = os.pipe()
        self.stdout = os.fdopen(self._out_r, "rb", buffering=0)
        self.stderr = os.fdopen(self._err_r, "rb", buffering=0)
        os.write(self._out_w, out)
        os.write(self._err_w, err)
        self.returncode = None
        self.killed = False
        self._final = code
        self._open = True
        if not hang:
            self._finish(code)

    def _finish(self, code):
        if self._open:
            os.close(self._out_w)
            os.close(self._err_w)
            self._open = False
        self.returncode = code

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self._finish(-9)

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("docker", timeout)
        return self.returncode


@pytest.fixture
def fake_docker(monkeypatch, tmp_path):
    calls = Calls()
    state = {"available": True, "process": None}

    def fake_run(argv, **kwargs):
        calls.run.append(list(argv))
        assert kwargs.get("env", {}).keys() <= {
            "PATH",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
        }
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0 if state["available"] else 1)
        if argv[1:3] == ["container", "inspect"]:
            return subprocess.CompletedProcess(argv, 1)  # already gone
        return subprocess.CompletedProcess(argv, 0)

    def fake_popen(argv, **kwargs):
        calls.popen.append(list(argv))
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["close_fds"] is True
        assert set(kwargs["env"]) <= {
            "PATH",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
        }
        process = state["factory"]()
        state["process"] = process
        return process

    real_mkdtemp = executor.tempfile.mkdtemp

    def fake_mkdtemp(**kwargs):
        path = real_mkdtemp(dir=tmp_path, **kwargs)
        calls.dirs.append(path)
        return path

    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(executor.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setenv("SECRET_SENTINEL", "must-not-pass")
    state["calls"] = calls
    return state


FILES = {"sample.json": b"[]", "analysis.py": b"result = {}"}


def _removed(calls: Calls) -> bool:
    name = calls.popen[0][calls.popen[0].index("--name") + 1]
    return [DOCKER, "rm", "-f", name] in calls.run


def _assert_clean(state):
    calls = state["calls"]
    assert _removed(calls)
    assert calls.dirs and not any(os.path.exists(d) for d in calls.dirs)
    # Both slots are free again.
    assert executor._slots.acquire(timeout=0)
    assert executor._slots.acquire(timeout=0)
    executor._slots.release()
    executor._slots.release()


def test_ok_run_returns_stdout_and_cleans_up(fake_docker):
    seen = {}

    def factory():
        directory = fake_docker["calls"].dirs[0]
        seen["files"] = sorted(os.listdir(directory))
        seen["mode"] = oct(os.stat(directory).st_mode & 0o777)
        seen["file_mode"] = oct(os.stat(Path(directory, "analysis.py")).st_mode & 0o777)
        return FakeProcess(out=b'{"a":1}\n', err=b"noise")

    fake_docker["factory"] = factory
    run = run_worker(config(), "bootstrap.py", FILES)
    assert (run.status, run.stdout, run.exit_code) == ("ok", b'{"a":1}\n', 0)
    assert seen == {
        "files": ["analysis.py", "sample.json"],
        "mode": "0o755",
        "file_mode": "0o644",
    }
    argv = fake_docker["calls"].popen[0]
    assert argv[argv.index("--mount") + 1] == (
        f"type=bind,src={fake_docker['calls'].dirs[0]},dst=/input,readonly"
    )
    _assert_clean(fake_docker)


def test_nonzero_exit_is_failed_without_stdout(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(out=b"partial", code=3)
    run = run_worker(config(), "bootstrap.py", FILES)
    assert (run.status, run.stdout, run.exit_code) == ("failed", None, 3)
    _assert_clean(fake_docker)


def test_timeout_kills_client_removes_container_and_dir(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(hang=True)
    run = run_worker(config(wall_clock_s=0.3), "bootstrap.py", FILES)
    assert run.status == "timeout"
    assert run.stdout is None
    assert 0.3 <= run.duration_s < 3
    assert fake_docker["process"].killed
    _assert_clean(fake_docker)


def test_stdout_cap_kills_and_cleans_up(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(out=b"x" * 101, hang=True)
    run = run_worker(config(analysis_stdout_cap=100), "bootstrap.py", FILES)
    assert run.status == "output_too_large"
    assert fake_docker["process"].killed
    _assert_clean(fake_docker)


def test_explicit_cap_only_lowers(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(out=b"x" * 60, hang=True)
    run = run_worker(config(), "bootstrap.py", FILES, stdout_cap=50)
    assert run.status == "output_too_large"
    fake_docker["calls"].popen.clear()
    fake_docker["factory"] = lambda: FakeProcess(out=b"x" * 60)
    run = run_worker(config(analysis_stdout_cap=50), "bootstrap.py", FILES, 10**9)
    assert run.status == "output_too_large"


def test_stderr_cap_kills_and_cleans_up(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(err=b"e" * 11, hang=True)
    run = run_worker(config(stderr_cap=10), "bootstrap.py", FILES)
    assert run.status == "output_too_large"
    _assert_clean(fake_docker)


def test_unavailable_never_starts_anything(fake_docker):
    fake_docker["available"] = False
    fake_docker["factory"] = _never
    run = run_worker(config(), "bootstrap.py", FILES)
    assert run.status == "unavailable"
    assert fake_docker["calls"].popen == []
    assert fake_docker["calls"].dirs == []


def test_missing_client_is_unavailable(fake_docker):
    fake_docker["factory"] = _never
    run = run_worker(config(docker=None), "bootstrap.py", FILES)
    assert run.status == "unavailable"
    assert fake_docker["calls"].run == [] and fake_docker["calls"].popen == []


def test_busy_when_both_slots_are_taken(fake_docker, monkeypatch):
    monkeypatch.setattr(executor, "SLOT_WAIT_S", 0.05)
    fake_docker["factory"] = _never
    assert executor._slots.acquire(timeout=0)
    assert executor._slots.acquire(timeout=0)
    try:
        run = run_worker(config(), "bootstrap.py", FILES)
    finally:
        executor._slots.release()
        executor._slots.release()
    assert run.status == "busy"
    assert fake_docker["calls"].popen == [] and fake_docker["calls"].dirs == []


def test_exception_in_read_loop_still_cleans_up(fake_docker, monkeypatch):
    fake_docker["factory"] = lambda: FakeProcess(hang=True)

    def boom(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(executor, "_collect", boom)
    with pytest.raises(KeyboardInterrupt):
        run_worker(config(), "bootstrap.py", FILES)
    assert fake_docker["process"].killed
    _assert_clean(fake_docker)


@pytest.mark.parametrize(
    "files",
    [
        {},
        {"../escape": b""},
        {"sample.json": "text"},
        {"run.sh": b"#!/bin/sh"},
    ],
)
def test_only_named_byte_files_are_written(fake_docker, files):
    fake_docker["factory"] = _never
    with pytest.raises(ValueError):
        run_worker(config(), "bootstrap.py", files)
    assert fake_docker["calls"].dirs == []


def test_analysis_maps_parse_failure_to_invalid_output(fake_docker):
    fake_docker["factory"] = lambda: FakeProcess(out=b'{"version": 1}\n')
    run = run_analysis(config(), sample(), "result = {}")
    assert (run.status, run.reason, run.output) == (
        "invalid_output",
        "output_refused",
        None,
    )
    fake_docker["factory"] = lambda: FakeProcess(
        out=b'{"version":1,"figures":[],"chart":null}\n'
    )
    run = run_analysis(config(), sample(), "result = {}")
    assert run.status == "ok" and run.output is not None
    assert run.output.figures == ()


def test_concurrent_runs_hold_at_most_two_slots(fake_docker, monkeypatch):
    monkeypatch.setattr(executor, "SLOT_WAIT_S", 0.05)
    release = threading.Event()
    started = threading.Barrier(3)

    def factory():
        process = FakeProcess(hang=True)
        started.wait(timeout=5)
        release.wait(timeout=5)
        process._finish(0)
        return process

    fake_docker["factory"] = factory
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(run_worker(config(), "bootstrap.py", FILES))
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    started.wait(timeout=5)
    third = run_worker(config(), "bootstrap.py", FILES)
    release.set()
    for thread in threads:
        thread.join(timeout=5)
    assert third.status == "busy"
    assert sorted(r.status for r in results) == ["ok", "ok"]
