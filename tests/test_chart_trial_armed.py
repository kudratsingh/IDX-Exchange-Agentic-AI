"""WO-030, D5 trial: the rollback is armed before activation and fires by itself.

The real wrapper and rollback run as copies in a throwaway repo (temp HOME, state dir,
consent dir and record dir; stub openclaw, node and launchctl), as in
tests/test_chart_trial_rollback.py. No input is ever given to any process.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tests.test_chart_trial_rollback import ON, ROOT, _calls, _trial_state
from tests.test_openclaw_merge_config import IMAGE, OWNER

pytestmark = pytest.mark.skipif(os.name != "posix", reason="bash scripts, fcntl")

COPIED = (
    "scripts/chart_trial_armed.py",
    "scripts/chart_trial_armed.sh",
    "scripts/guards/consent_token.py",
)
OFF = [
    f"IDX_OWNER_E164={OWNER}",
    "IDX_ANALYSIS_TOOL=0",
    f"IDX_ANALYSIS_IMAGE={IMAGE}",
    "IDX_CHART_DELIVERY=0",
]


def _module():
    spec = importlib.util.spec_from_file_location(
        "chart_trial_armed", ROOT / "scripts" / "chart_trial_armed.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _delivery_line(status: str) -> str:
    """A chart_delivery line as log_event writes it (sorted keys, no content)."""
    record = {
        "event": "chart_delivery",
        "reason": None if status == "ready" else "dir_full",
        "status": status,
        "trace_id": "a" * 32,
        "ts": "2026-11-04T12:00:00.000+00:00",
    }
    return json.dumps(record, sort_keys=True) + "\n"


class Trial:
    """The Mac as the trial leaves it, plus the armed-run pieces: a delete grant in
    the repo's own consent dir, a 700 record dir and the idx server log."""

    def __init__(self, tmp_path: Path, grant_minutes: float | None = 60) -> None:
        self.tmp = tmp_path
        self.repo = _trial_state(tmp_path, ON, job=True)
        for rel in COPIED:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, self.repo / rel)
        if grant_minutes is not None:
            consent = self.repo / ".local" / "consent"
            consent.mkdir(parents=True)
            (consent / "delete").write_text(f"{time.time() + grant_minutes * 60:.0f}\n")
        self.records = tmp_path / "records"
        self.records.mkdir(mode=0o700)
        self.log = tmp_path / "idx-agent.log"
        self.log.write_text('{"event": "server_start", "trace_id": ""}\n')
        self.env = {
            "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "IDX_PYTHON": sys.executable,
            "OPENCLAW_STATE_DIR": str(tmp_path / "state"),
            "PYTHONPATH": str(ROOT / "src"),
            "MYSQL_HOST": "",
        }

    def argv(self, *args: str) -> list[str]:
        return ["bash", str(self.repo / "scripts" / "chart_trial_armed.sh"), *args]

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.argv(*args),
            cwd=self.tmp,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def arm(self, *extra: str) -> Path:
        done = self.run("arm", "--record-dir", str(self.records), *extra)
        assert done.returncode == 0, done.stdout + done.stderr
        first = done.stdout.splitlines()[0]
        assert first.startswith("ARMED: ")
        self.output = done.stdout
        return Path(first.removeprefix("ARMED: "))

    def runs(self) -> list[Path]:
        return sorted(p for p in self.records.iterdir() if p.is_dir())

    def record(self, run: Path, within: float) -> str:
        """Wait (no input given) for the watchdog's record; fail after `within` s."""
        deadline = time.monotonic() + within
        while time.monotonic() < deadline:
            if (run / "record.txt").exists():
                return (run / "record.txt").read_text()
            time.sleep(0.1)
        path = run / "watchdog.log"
        log = path.read_text() if path.exists() else ""
        raise AssertionError(f"no record within {within} s; watchdog log: {log!r}")

    def restarts(self) -> int:
        calls = _calls(self.tmp) if (self.tmp / "calls").exists() else []
        return calls.count("openclaw gateway restart")

    def env_switches(self) -> list[str]:
        return (self.repo / ".env").read_text().splitlines()


@pytest.fixture
def trial(tmp_path):
    made: list[Trial] = []

    def make(**kwargs) -> Trial:
        made.append(Trial(tmp_path, **kwargs))
        return made[-1]

    yield make
    for t in made:  # never leave a watchdog behind a failed test
        for run in t.runs():
            pid = _module()._watchdog_pid(run)
            finished = (run / "record.txt").exists()
            if pid is not None and _module()._alive(pid) and not finished:
                os.kill(pid, signal.SIGKILL)


def _fired(run: Path) -> dict:
    return json.loads((run / "fired").read_text())


def _alive(pid: int) -> bool:
    return _module()._alive(pid)


def test_completion_signal_rolls_back_within_seconds_without_any_input(trial):
    """(1) Arm, activate, the server logs chart_delivery ready: after the settle the
    rollback runs by itself (pass), ROLLBACK DONE, both switches off, one restart."""
    t = trial()
    run = t.arm("--log", str(t.log), "--settle", "1", "--timeout", "120")
    assert "time-bound, it covers every agent delete until then" in t.output
    assert t.run("status", str(run)).returncode == 0  # the check before each step
    assert (t.run("activated", str(run))).returncode == 0
    assert t.restarts() == 0  # armed and activated, nothing rolled back yet
    with t.log.open("a") as out:
        out.write(_delivery_line("ready"))
    seen = time.time()
    record = t.record(run, within=20)
    assert "  rollback: pass (chart_delivery line);" in record
    assert "no reply was awaited" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert "  trial result: pass" in record
    assert _fired(run)["t"] - seen < 1 + 5  # settle, plus polling and load slack
    assert t.env_switches() == OFF
    assert t.restarts() == 1


def test_no_signal_rolls_back_at_the_timeout(trial):
    """(2) Arm, activate, nothing is logged and nobody answers: the rollback fires
    at the timeout (fail), not before it."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "2")
    assert t.run("activated", str(run)).returncode == 0
    activated = json.loads((run / "activated").read_text())["t"]
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert 2 <= _fired(run)["t"] - activated < 2 + 5
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.env_switches() == OFF
    assert t.restarts() == 1


def test_a_failed_activation_rolls_back_aborted_at_once(trial):
    """(3) Arm, an activation step fails, the operator signals abort: aborted."""
    t = trial()
    run = t.arm("--timeout", "120")
    signalled = t.run("abort", str(run))
    assert signalled.returncode == 0, signalled.stderr
    record = t.record(run, within=20)
    assert "  rollback: aborted (activation failed);" in record
    assert "  trial result: aborted" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.env_switches() == OFF


def test_activation_never_confirmed_rolls_back_aborted_at_the_limit(trial):
    """(3) The operator never reports activation (the agent died mid-step): aborted
    at the activation limit, with nobody's help."""
    t = trial()
    run = t.arm("--activation-limit", "2")
    record = t.record(run, within=20)
    assert "  rollback: aborted (activation not confirmed);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    # Too late: the operator is told to stop and to run the rollback again.
    late = t.run("activated", str(run))
    assert late.returncode == 1
    assert "NOT ARMED: the rollback has already fired" in late.stderr
    assert "scripts/chart_trial_rollback.sh aborted again, now" in late.stderr
    assert t.run("status", str(run)).returncode == 1


def test_the_watchdog_outlives_the_shell_that_armed_it(trial):
    """(4) The arming shell's whole process group is hung up and killed right after
    arming; the watchdog (its own session) is still alive and fires at the timeout."""
    t = trial()
    out = t.tmp / "arm.out"
    command = " ".join(t.argv("arm", "--record-dir", str(t.records), "--timeout", "2"))
    shell = subprocess.Popen(
        ["bash", "-c", f"{command} > {out}; sleep 60"],
        env=t.env,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and "ARMED" not in (
        out.read_text() if out.exists() else ""
    ):
        time.sleep(0.1)
    run = Path(out.read_text().splitlines()[0].removeprefix("ARMED: "))
    os.killpg(shell.pid, signal.SIGHUP)
    os.killpg(shell.pid, signal.SIGKILL)
    shell.wait(timeout=10)
    pid = _module()._watchdog_pid(run)
    assert pid is not None and pid != shell.pid
    time.sleep(0.5)
    assert _alive(pid)
    assert t.run("activated", str(run)).returncode == 0
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")


def test_signal_and_timeout_racing_roll_back_exactly_once(trial):
    """(5) The log line, the operator's done and the timeout land together, and a
    second watchdog is started on the same run, during and after: one rollback."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "1", "--settle", "0")
    assert t.run("activated", str(run)).returncode == 0
    activated = json.loads((run / "activated").read_text())["t"]
    time.sleep(max(0.0, activated + 1 - time.time()))
    with t.log.open("a") as out:
        out.write(_delivery_line("failed"))
    (run / "done").write_text("pass\n")
    second = t.run("_watch", str(run))
    assert second.returncode != 0 or (run / "fired").exists()
    record = t.record(run, within=20)
    after = t.run("_watch", str(run))
    assert after.returncode == 0
    assert record.count("ROLLBACK DONE") == 1
    assert _fired(run)["result"] in ("pass", "fail")
    assert t.restarts() == 1
    assert (run / "record.txt").read_text() == record


def test_a_terminated_watchdog_rolls_back_aborted(trial):
    """SIGTERM to the watchdog is not a way to skip the rollback: it fires aborted."""
    t = trial()
    run = t.arm("--timeout", "120")
    os.kill(_module()._watchdog_pid(run), signal.SIGTERM)
    record = t.record(run, within=20)
    assert "  rollback: aborted (watchdog terminated);" in record
    assert t.restarts() == 1


@pytest.mark.parametrize(
    "case",
    [
        "no grant",
        "grant too short",
        "no record dir",
        "record dir not private",
        "no rollback script",
        "no log file",
        "timeout out of bounds",
    ],
)
def test_arming_refuses_and_nothing_starts(trial, case):
    """(6) Each missing precondition: exit 1, REFUSED, no run dir, no watchdog, no
    command run and `.env` untouched; so the operator does not activate."""
    t = trial(grant_minutes={"no grant": None, "grant too short": 10}.get(case, 60))
    records, extra = str(t.records), []
    if case == "no record dir":
        records = str(t.tmp / "missing")
    elif case == "record dir not private":
        t.records.chmod(0o755)
    elif case == "no rollback script":
        (t.repo / "scripts" / "chart_trial_rollback.sh").unlink()
    elif case == "no log file":
        extra = ["--log", str(t.tmp / "missing.log")]
    elif case == "timeout out of bounds":
        extra = ["--timeout", "7200"]
    before = (t.repo / ".env").read_text()
    done = t.run("arm", "--record-dir", records, *extra)
    assert done.returncode == 1
    assert "REFUSED: " in done.stderr and "do not activate" in done.stderr
    assert "ARMED" not in done.stdout
    assert t.runs() == []
    assert not (t.tmp / "calls").exists()
    assert (t.repo / ".env").read_text() == before
    if case == "grant too short":
        assert "it needs at least 31 minutes from now" in done.stderr


def test_activated_without_a_live_watchdog_is_refused(trial):
    """`activated` on a run whose watchdog is gone says so and names the rollback."""
    t = trial()
    run = t.records / "chart-trial-x"
    run.mkdir()
    (run / "arm.json").write_text("{}\n")
    done = t.run("activated", str(run))
    assert done.returncode == 1
    assert "NOT ARMED: no live watchdog" in done.stderr
    assert "scripts/chart_trial_rollback.sh aborted" in done.stderr


@pytest.mark.parametrize(
    ("line", "word"),
    [
        (_delivery_line("ready"), "pass"),
        (_delivery_line("failed"), "fail"),
        # The same line as a gateway might wrap a child's stderr: escaped once.
        ("[idx stderr] " + json.dumps(_delivery_line("ready")), "pass"),
        ('{"event": "tool_call", "status": "ready", "trace_id": ""}', None),
        ('{"event": "chart_delivery", "trace_id": ""}', None),
    ],
)
def test_the_completion_signal_is_the_chart_delivery_line(line, word):
    assert _module().completion(line.encode()) == word


def test_required_grant_covers_the_whole_armed_window():
    """Defaults: 600 s activation + 600 s timeout + 600 s rollback + 60 s = 31 min."""
    module = _module()
    assert module.required_grant_seconds(600, 600) == 1860
    assert module.required_grant_seconds(1800, 1800) / 60 <= 240  # the grant maximum
