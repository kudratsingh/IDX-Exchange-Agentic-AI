"""WO-030, D5 trial: the armed rollback, in a throwaway repo with stub commands.

No process is given input. The pass cases run a real `bounded_analysis` call through
the MCP server in this process (fake docker worker), which signs the watched log line.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from tests.test_analysis_executor import fake_docker  # noqa: F401 - fixture
from tests.test_analysis_integration import (  # noqa: F401 - fixtures
    CODE,
    SCATTER,
    reader,
    session_call,
    switch_on,
    worker,
    worker_json,
)
from tests.test_analysis_service import PNG
from tests.test_chart_delivery import _payload, charts_in_dotenv
from tests.test_chart_trial_rollback import ROOT, _calls, _trial_state
from tests.test_openclaw_merge_config import IMAGE, OWNER

from idx_agent.analysis import delivery
from idx_agent.mcp_server import server
from idx_agent.observability import logging as obs_logging

pytestmark = pytest.mark.skipif(os.name != "posix", reason="bash scripts, fcntl")

# No consent-token code is copied: arming, the watchdog and the rollback never read one.
COPIED = ("scripts/chart_trial_armed.py", "scripts/chart_trial_armed.sh")
SWITCHES = ("IDX_ANALYSIS_TOOL", "IDX_CHART_DELIVERY")
APPROVAL = "owner trial approval, PR 166 comment (test)"


def _module():
    spec = importlib.util.spec_from_file_location(
        "chart_trial_armed", ROOT / "scripts" / "chart_trial_armed.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARMED = _module()


def _line(status: str, trace: str = "b" * 16, **fields) -> str:
    """A chart_delivery line as log_event writes it (sorted keys, no content)."""
    record = {
        "event": "chart_delivery",
        "reason": None if status == "ready" else "dir_full",
        "status": status,
        "trace_id": trace,
        "ts": "2026-11-04T12:00:00.000+00:00",
        **fields,
    }
    return json.dumps(record, sort_keys=True) + "\n"


def _signed(trial: dict, status: str, t: float, trace: str = "b" * 16) -> str:
    """The line the server writes for `trial` (its own signer, not a copy)."""
    signer = delivery.TrialSigner(trial["trial_id"], bytes.fromhex(trial["key"]))
    return _line(status, trace, **signer.fields(trace, status, now=t))


class Trial:
    """The Mac with Phase 1 on and charts off, plus the armed-run pieces: a 700 record
    dir and the idx server log. No consent token unless `grant_minutes` is given (a
    negative value writes an already expired `delete` grant)."""

    def __init__(self, tmp_path: Path, grant_minutes: float | None = None) -> None:
        self.tmp = tmp_path
        self.charts = tmp_path / ".openclaw" / "workspace-idx" / "idx-charts"
        self.repo = _trial_state(
            tmp_path,
            [
                f"IDX_OWNER_E164={OWNER}",
                "IDX_ANALYSIS_TOOL=1",
                f"IDX_ANALYSIS_IMAGE={IMAGE}",
                "IDX_CHART_DELIVERY=0",
                f"IDX_CHART_DIR={self.charts}",
            ],
            job=True,
        )
        for rel in COPIED:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, self.repo / rel)
        # An installed OpenClaw config, plain JSON as on the Mac, so every install.sh
        # run merges into it (a missing one is installed as the JSON5 render, which a
        # second run cannot merge into: a second rollback would end INCOMPLETE).
        config = tmp_path / "state" / "openclaw.json"
        config.write_text("{}\n")
        config.chmod(0o600)
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

    def grant_file(self) -> Path:
        return self.repo / ".local" / "consent" / "delete"

    def arm(self, *extra: str) -> Path:
        if "--approval" not in extra:
            extra = ("--approval", APPROVAL, *extra)
        done = self.run("arm", "--record-dir", str(self.records), *extra)
        assert done.returncode == 0, done.stdout + done.stderr
        first = done.stdout.splitlines()[0]
        assert first.startswith("ARMED: ")
        self.output = done.stdout
        return Path(first.removeprefix("ARMED: "))

    def activate(self, run: Path) -> float:
        """Step 1 through the helper, then `activated`; the activation time."""
        enabled = self.run("enable", str(run))
        assert enabled.returncode == 0, enabled.stderr
        done = self.run("activated", str(run))
        assert done.returncode == 0, done.stderr
        return json.loads((run / "activated").read_text())["t"]

    def runs(self) -> list[Path]:
        return sorted(p for p in self.records.iterdir() if p.is_dir())

    def record(self, run: Path, within: float, containing: str = "") -> str:
        """Wait (no input given) for the watchdog's record; fail after `within` s."""
        deadline = time.monotonic() + within
        while time.monotonic() < deadline:
            path = run / "record.txt"
            if path.exists() and containing in (text := path.read_text()):
                return text
            time.sleep(0.1)
        path = run / "watchdog.log"
        log = path.read_text() if path.exists() else ""
        raise AssertionError(f"no record within {within} s; watchdog log: {log!r}")

    def restarts(self) -> int:
        calls = _calls(self.tmp) if (self.tmp / "calls").exists() else []
        return calls.count("openclaw gateway restart")

    def switches(self) -> list[str]:
        """Every IDX_ANALYSIS_TOOL / IDX_CHART_DELIVERY line of `.env`."""
        lines = (self.repo / ".env").read_text().splitlines()
        return [line for line in lines if line.split("=")[0] in SWITCHES]

    def edit_env(self, **values: str) -> None:
        ARMED.set_env(self.repo / ".env", values)


OFF = ["IDX_ANALYSIS_TOOL=0", "IDX_CHART_DELIVERY=0"]


@pytest.fixture
def trial(tmp_path):
    made: list[Trial] = []

    def make(**kwargs) -> Trial:
        made.append(Trial(tmp_path, **kwargs))
        return made[-1]

    yield make
    for t in made:  # never leave a watchdog behind
        for run in t.runs():
            pid = ARMED._watchdog_pid(run)
            if pid is not None and ARMED._alive(pid):
                os.kill(pid, signal.SIGKILL)


def _fired(run: Path) -> dict:
    return json.loads((run / "fired").read_text())


def _key(run: Path) -> dict:
    return json.loads((run / "trial.key").read_text())


def _gone(pid: int | None, within: float = 20) -> None:
    deadline = time.monotonic() + within
    while pid is not None and ARMED._alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert pid is None or not ARMED._alive(pid)


def _server_turn(request, monkeypatch, t: Trial) -> dict:
    """One real `bounded_analysis` call over an in-process MCP session, the server
    started (as OpenClaw would) on the temp repo's `.env` that `enable` wrote, with
    IDX_LOG_FILE the watched log; the fake docker worker draws the scatter chart.
    fake_docker patches subprocess globally, so the real functions are put back."""
    real_run, real_popen = subprocess.run, subprocess.Popen
    request.getfixturevalue("reader")
    work = request.getfixturevalue("worker")
    try:
        monkeypatch.chdir(t.repo)
        monkeypatch.setenv("IDX_LOG_FILE", str(t.log))
        obs_logging.reset_log_file_settings_for_tests()
        delivery.reset_store_for_tests()
        assert server.configure_chart_delivery() is True
        work["set"](worker_json(chart=SCATTER))
        payload, images = session_call(city="Pasadena", code=CODE)
    finally:
        monkeypatch.setattr(subprocess, "run", real_run)
        monkeypatch.setattr(subprocess, "Popen", real_popen)
        delivery.reset_store_for_tests()
    assert images == []
    assert payload["data"]["chart"]["delivery"]["status"] == "ready"
    return payload


def _delivery_lines(log: Path) -> list[str]:
    return [line for line in log.read_text().splitlines() if "chart_delivery" in line]


# --- (a) the authorized trial's own server line is the only pass ---


def test_the_line_the_server_signs_during_the_trial_rolls_back_pass(
    trial, request, monkeypatch
):
    """(a) Arm, enable (writes the trial file into .env), activate; the server
    answers one real bounded_analysis call and logs chart_delivery ready, signed:
    the watchdog verifies it and rolls back (pass) one settle later, by itself."""
    t = trial()
    run = t.arm(
        "--log", str(t.log), "--settle", "1", "--timeout", "120", "--watch-after", "0"
    )
    key = _key(run)
    assert key["trial_id"] in t.output and key["key"] not in t.output
    assert f"trial approval: {APPROVAL} (recorded in arm.json)" in t.output
    assert "the rollback reads and needs no consent token" in t.output
    assert "grant" not in t.output
    assert "deadline check (agent): by " in t.output
    assert t.run("status", str(run)).returncode == 0  # the check before each step
    t.activate(run)
    env = (t.repo / ".env").read_text()
    assert "IDX_CHART_DELIVERY=1\n" in env
    assert f"IDX_CHART_TRIAL_FILE={run / 'trial.key'}\n" in env
    assert t.restarts() == 0  # armed and activated, nothing rolled back yet
    payload = _server_turn(request, monkeypatch, t)
    seen = time.time()
    [line] = _delivery_lines(t.log)
    logged = json.loads(line)
    assert logged["trial_id"] == key["trial_id"]
    assert logged["trace_id"] == payload["provenance"]["trace_id"]
    record = t.record(run, within=30)
    assert "  rollback: pass (authenticated chart_delivery line);" in record
    assert f"trace {payload['provenance']['trace_id']}) seen" in record
    assert "(any call, not only the trial turn); the trial result is" in record
    assert "rejected lines: 0" in record
    assert "no reply was awaited" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert "  trial result: pass" in record
    assert _fired(run)["t"] - seen < 1 + 5  # settle, plus polling and load slack
    assert t.switches() == OFF
    assert t.restarts() == 1
    # The key is in the trial file only: not in the log, the record or any output.
    for path in (t.log, run / "record.txt", run / "watchdog.log", run / "arm.json"):
        assert key["key"] not in path.read_text(), path
    assert key["key"] not in json.dumps(payload)


# --- (b) a hand-appended line, however well formed, is not the trial's ---


def test_appended_lines_without_the_trials_signature_are_rejected_and_it_fails(trial):
    """(b) Lines in the right format appended to the log after activation: unsigned,
    the right trial id with a made-up HMAC, and one signed with another key. All
    are rejected and recorded; the run ends at the timeout, fail, never pass."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "4", "--watch-after", "0")
    activated = t.activate(run)
    trial_id = _key(run)["trial_id"]
    with t.log.open("a") as out:
        out.write(_line("ready"))
        out.write(
            _line(
                "ready",
                trial_id=trial_id,
                trial_t=int(time.time() * 1000),
                trial_mac="0" * 64,
            )
        )
        other_key = {"trial_id": trial_id, "key": "1" * 64}
        out.write(_signed(other_key, "ready", time.time()))
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert 4 <= _fired(run)["t"] - activated < 4 + 5
    assert "rejected lines: 3" in record
    assert record.count("signal: rejected a line") == 3
    assert "unsigned line" in record
    assert record.count("HMAC does not verify") == 2
    reasons = [
        json.loads(line)["reason"]
        for line in (run / "rejected.jsonl").read_text().splitlines()
    ]
    assert len(reasons) == 3
    assert _fired(run)["result"] == "fail"
    assert t.switches() == OFF and t.restarts() == 1


# --- (c) a valid line from an earlier trial is a replay ---


def test_a_valid_line_replayed_from_an_earlier_trial_is_rejected(
    trial, request, monkeypatch
):
    """(c) Trial 1 passes on its own server line. Trial 2 is armed in the same
    record dir; that exact line, and the same line relabelled with trial 2's id,
    are appended after trial 2's activation: both rejected, trial 2 fails."""
    t = trial()
    first = t.arm(
        "--log", str(t.log), "--settle", "0", "--timeout", "60", "--watch-after", "0"
    )
    t.activate(first)
    _server_turn(request, monkeypatch, t)
    assert "rollback: pass (authenticated" in t.record(first, within=30)
    _gone(ARMED._watchdog_pid(first))
    [old] = _delivery_lines(t.log)
    t.edit_env(IDX_ANALYSIS_TOOL="1")  # Phase 1 on again, as a new trial needs
    second = t.arm("--log", str(t.log), "--timeout", "3", "--watch-after", "0")
    assert _key(second)["trial_id"] != _key(first)["trial_id"]
    t.activate(second)
    relabelled = old.replace(_key(first)["trial_id"], _key(second)["trial_id"])
    with t.log.open("a") as out:
        out.write(old + "\n")
        out.write(relabelled + "\n")
    record = t.record(second, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert "rejected lines: 2" in record
    assert "another trial's id (replayed or another run)" in record
    assert "HMAC does not verify" in record
    assert t.switches() == OFF and t.restarts() == 2  # one per trial


# --- (d) no manual pass ---


def test_done_pass_is_refused_and_a_hand_written_pass_is_ignored(trial):
    """(d) `done RUN pass` is refused and signals nothing; a `done` file holding
    `pass`, written by hand, is recorded as rejected; the run fails at the timeout."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "3", "--watch-after", "0")
    t.activate(run)
    refused = t.run("done", str(run), "pass")
    assert refused.returncode == 2
    assert "REFUSED: a manual pass is not accepted" in refused.stderr
    assert not (run / "done").exists()
    (run / "done").write_text("pass\n")
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert "operator `done` file is not `fail` (no manual pass)" in record
    assert t.switches() == OFF


def test_done_fail_rolls_back_fail_at_once(trial):
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    t.activate(run)
    signalled = t.run("done", str(run), "fail")
    assert signalled.returncode == 0, signalled.stderr
    record = t.record(run, within=20)
    assert "  rollback: fail (operator done fail);" in record
    assert t.switches() == OFF and t.restarts() == 1


# --- (e) nothing comes back on after the rollback ---


def test_late_activation_after_the_timeout_rollback_is_refused_and_rolled_back(trial):
    """(e) The timeout fires; while its rollback runs and after it, `enable`,
    `activated` and `sent` are refused (tombstone). A re-enable forced by editing
    .env is seen by the post-rollback watch and rolled back again."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "1", "--watch-after", "60")
    t.activate(run)
    deadline = time.monotonic() + 20
    # `fired` and `tombstone` are written together under the run's state lock, which
    # the activation commands take; the test reads without it, so waits for both.
    while not (run / "tombstone").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (run / "fired").exists() and (run / "tombstone").exists()
    for args in (("enable", str(run)), ("activated", str(run)), ("sent", str(run))):
        late = t.run(*args)
        assert late.returncode == 1, args
        assert "NOT ARMED: the rollback has already fired (fail" in late.stderr
        assert "cannot be activated again" in late.stderr
    record = t.record(run, within=20, containing="post-rollback watch: until")
    assert "  rollback: fail (trial timeout);" in record
    assert t.switches() == OFF and t.restarts() == 1
    assert t.run("enable", str(run)).returncode == 1  # still refused afterwards
    assert t.switches() == OFF
    # Forced, by hand, past the helper:
    t.edit_env(IDX_CHART_DELIVERY="1", IDX_ANALYSIS_TOOL="1")
    record = t.record(run, within=20, containing="re-enable blocked")
    assert "re-enable blocked" in record and "rollback fail run again" in record
    assert "(rollback-2.log): exit 0, ROLLBACK DONE: analysis off" in record
    assert ".env IDX_ANALYSIS_TOOL on, .env IDX_CHART_DELIVERY on" in record
    deadline = time.monotonic() + 20
    while t.restarts() < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert t.switches() == OFF and t.restarts() == 2
    status = t.run("status", str(run))
    assert status.returncode == 1 and "post-rollback watch running" in status.stdout
    pid = ARMED._watchdog_pid(run)
    os.kill(pid, signal.SIGTERM)  # ends the watch; nothing is turned on by it
    record = t.record(run, within=20, containing="(SIGTERM)")
    _gone(pid)
    assert t.switches() == OFF and t.restarts() == 2


def test_enable_racing_the_activation_limit_never_leaves_anything_on(trial):
    """(e) `enable` is retried in a tight loop across the activation-limit rollback.
    Each attempt either lands before the claim (the rollback undoes it) or is
    refused; every attempt started after the tombstone is refused; one rollback."""
    t = trial()
    run = t.arm("--activation-limit", "2", "--watch-after", "5")
    attempts: list[tuple[float, int]] = []
    stop = threading.Event()

    def hammer() -> None:
        while not stop.is_set():
            began = time.time()
            attempts.append((began, t.run("enable", str(run)).returncode))

    time.sleep(1.2)
    worker_thread = threading.Thread(target=hammer)
    worker_thread.start()
    try:
        t.record(run, within=20)
        time.sleep(0.5)
    finally:
        stop.set()
        worker_thread.join(timeout=30)
    claimed = _fired(run)["t"]
    late = [code for began, code in attempts if began > claimed]
    assert late and all(code == 1 for code in late)
    record = t.record(run, within=20, containing="post-rollback watch: ended")
    assert "  rollback: aborted (activation not confirmed);" in record
    assert "re-enable blocked" not in record
    assert t.switches() == OFF and t.restarts() == 1


# --- (f) the fail-safe ---


def test_an_unexpected_error_in_the_watchdog_rolls_back_aborted(trial):
    """(f) A corrupt `activated` file (written by hand, not by the helper) makes the
    watchdog's loop raise TypeError: the catch-all runs the rollback, aborted, and
    records the exception class."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    assert t.run("enable", str(run)).returncode == 0
    (run / "activated").write_text('{"t": "corrupt", "offset": 0}\n')
    record = t.record(run, within=20)
    assert "watchdog: unexpected TypeError at " in record
    assert "  rollback: aborted (fail-safe, TypeError);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.switches() == OFF and t.restarts() == 1


@pytest.mark.parametrize("claim", ["fired", "tombstone"])
def test_a_claim_the_watchdog_did_not_write_rolls_back_at_once(trial, claim):
    """(f) Only the watchdog writes `fired` and `tombstone`. One written by hand
    into the run directory (here after `enable`) does not suppress the rollback:
    the watchdog rolls back aborted at once, writes the tombstone and the record."""
    t = trial()
    run = t.arm("--timeout", "120", "--activation-limit", "120", "--watch-after", "0")
    assert t.run("enable", str(run)).returncode == 0
    assert t.switches() == ["IDX_ANALYSIS_TOOL=1", "IDX_CHART_DELIVERY=1"]
    (run / claim).write_text("x\n")
    record = t.record(run, within=20)
    assert "watchdog: a claim it did not write appeared " in record
    assert "  rollback: aborted (claim written by another process);" in record
    pre_existed = "watchdog: claim pre-existed (tampered); rolling back anyway"
    assert (pre_existed in record) is (claim == "fired")
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert (run / "fired").exists() and (run / "tombstone").exists()
    assert t.switches() == OFF and t.restarts() == 1


# --- (g) races: one rollback ---


def test_signal_timeout_and_abort_racing_roll_back_exactly_once(trial):
    """(g) A signed line (the server's own signer with the trial's key), `done
    fail`, `abort` and the timeout land together, and a second watchdog is started
    on the same run during and after: one rollback, one restart."""
    t = trial()
    run = t.arm(
        "--log", str(t.log), "--timeout", "1", "--settle", "0", "--watch-after", "0"
    )
    activated = t.activate(run)
    time.sleep(max(0.0, activated + 1 - time.time()))
    with t.log.open("a") as out:
        out.write(_signed(_key(run), "failed", activated + 0.5))
    (run / "done").write_text("fail\n")
    (run / "abort").write_text("aborted\n")
    second = t.run("_watch", str(run))
    assert second.returncode != 0 or (run / "fired").exists()
    record = t.record(run, within=20)
    _gone(ARMED._watchdog_pid(run))
    after = t.run("_watch", str(run))
    assert after.returncode == 0
    assert record.count("ROLLBACK DONE") == 1
    assert _fired(run)["result"] in ("fail", "aborted")
    assert t.restarts() == 1
    assert (run / "record.txt").read_text() == record


# --- the sent countdown, the timeout, abort, the limits ---


def test_no_signed_line_within_the_reply_wait_after_sent_fails(trial):
    """The documented "no reply within 2 minutes of sending": `sent` starts the
    countdown (1 s here); no signed line by then -> fail, before the timeout."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "120", "--reply-wait", "1")
    early = t.run("sent", str(run))
    assert early.returncode == 1 and "not activated yet" in early.stderr
    t.activate(run)
    assert t.run("sent", str(run)).returncode == 0
    sent = json.loads((run / "sent").read_text())["t"]
    record = t.record(run, within=20)
    assert "  rollback: fail (no reply after sent);" in record
    assert 1 <= _fired(run)["t"] - sent < 1 + 5
    assert t.switches() == OFF


def test_no_signal_rolls_back_at_the_timeout(trial):
    """Arm, activate, nothing is logged and nobody answers: the rollback fires at the
    timeout (fail), not before it."""
    t = trial()
    run = t.arm("--log", str(t.log), "--timeout", "2", "--watch-after", "0")
    activated = t.activate(run)
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert 2 <= _fired(run)["t"] - activated < 2 + 5
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.switches() == OFF
    assert t.restarts() == 1


def test_a_failed_activation_rolls_back_aborted_at_once(trial):
    """Arm, an activation step fails, the operator signals abort: aborted."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    signalled = t.run("abort", str(run))
    assert signalled.returncode == 0, signalled.stderr
    record = t.record(run, within=20)
    assert "  rollback: aborted (activation failed);" in record
    assert "  trial result: aborted" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.switches() == OFF


def test_activation_never_confirmed_rolls_back_aborted_at_the_limit(trial):
    """The operator never reports activation (the agent died mid-step): aborted at
    the activation limit, with nobody's help; a late activation is refused."""
    t = trial()
    run = t.arm("--activation-limit", "2", "--watch-after", "0")
    record = t.record(run, within=20)
    assert "  rollback: aborted (activation not confirmed);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    for step in ("enable", "activated"):
        late = t.run(step, str(run))
        assert late.returncode == 1
        assert "NOT ARMED: the rollback has already fired" in late.stderr
        assert "scripts/chart_trial_rollback.sh aborted again, now" in late.stderr
    assert t.switches() == OFF
    assert t.run("status", str(run)).returncode == 1


def test_the_watchdog_outlives_the_shell_that_armed_it(trial):
    """The arming shell's whole process group is hung up and killed right after
    arming; the watchdog (its own session) is still alive and fires at the timeout."""
    t = trial()
    out = t.tmp / "arm.out"
    arm = ("arm", "--record-dir", str(t.records), "--timeout", "2")
    command = shlex.join(t.argv(*arm, "--approval", APPROVAL, "--watch-after", "0"))
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
    pid = ARMED._watchdog_pid(run)
    assert pid is not None and pid != shell.pid
    time.sleep(0.5)
    assert ARMED._alive(pid)
    t.activate(run)
    record = t.record(run, within=20)
    assert "  rollback: fail (trial timeout);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")


def test_sighup_and_sigint_are_ignored_by_the_watchdog(trial):
    """SIGHUP and SIGINT are ignored (the watchdog keeps watching); the only handled
    terminating signal is SIGTERM, below."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    pid = ARMED._watchdog_pid(run)
    os.kill(pid, signal.SIGHUP)
    os.kill(pid, signal.SIGINT)
    time.sleep(0.5)
    assert ARMED._alive(pid) and not (run / "fired").exists()
    assert t.run("abort", str(run)).returncode == 0
    assert "  rollback: aborted (activation failed);" in t.record(run, within=20)


def test_a_terminated_watchdog_rolls_back_aborted(trial):
    """SIGTERM to the watchdog is not a way to skip the rollback: it fires aborted."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    os.kill(ARMED._watchdog_pid(run), signal.SIGTERM)
    record = t.record(run, within=20)
    assert "  rollback: aborted (watchdog terminated);" in record
    assert t.restarts() == 1


@pytest.mark.parametrize(
    "signum",
    [signal.SIGKILL, signal.SIGUSR1, signal.SIGALRM],
    ids=["SIGKILL", "SIGUSR1", "SIGALRM"],
)
def test_a_killed_watchdog_is_reported_by_status_not_covered(trial, signum):
    """SIGKILL (and so logout or reboot), and any other terminating signal the
    watchdog does not handle (here SIGUSR1, SIGALRM): no rollback runs. The agent's
    deadline check, `status`, says so and names the by-hand rollback."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    pid = ARMED._watchdog_pid(run)
    os.kill(pid, signum)
    _gone(pid)
    status = t.run("status", str(run))
    assert status.returncode == 3
    assert "NOT RUNNING and no record" in status.stdout
    assert "Run scripts/chart_trial_rollback.sh aborted now" in status.stdout
    assert not (run / "record.txt").exists() and t.restarts() == 0


@pytest.mark.parametrize(
    "case",
    [
        "no approval",
        "blank approval",
        "approval with a line break",
        "no record dir",
        "record dir not private",
        "no rollback script",
        "no log file",
        "timeout out of bounds",
    ],
)
def test_arming_refuses_and_nothing_starts(trial, case):
    """Each missing precondition: exit 1, REFUSED, no run dir, no watchdog, no
    command run and `.env` untouched; so the operator does not activate."""
    t = trial(grant_minutes=60)  # a valid grant changes nothing: it is never read
    records, extra = str(t.records), ["--approval", APPROVAL]
    if case == "no approval":
        extra = []
    elif case == "blank approval":
        extra = ["--approval", "  "]
    elif case == "approval with a line break":
        extra = ["--approval", "approved\nby nobody"]
    elif case == "no record dir":
        records = str(t.tmp / "missing")
    elif case == "record dir not private":
        t.records.chmod(0o755)
    elif case == "no rollback script":
        (t.repo / "scripts" / "chart_trial_rollback.sh").unlink()
    elif case == "no log file":
        extra += ["--log", str(t.tmp / "missing.log")]
    elif case == "timeout out of bounds":
        extra += ["--timeout", "7200"]
    before = (t.repo / ".env").read_text()
    done = t.run("arm", "--record-dir", records, *extra)
    assert done.returncode == 1
    assert "REFUSED: " in done.stderr and "do not activate" in done.stderr
    assert "ARMED" not in done.stdout
    assert t.runs() == []
    assert not (t.tmp / "calls").exists()
    assert (t.repo / ".env").read_text() == before
    if case == "no approval":
        assert "no --approval; give the owner's recorded trial approval" in done.stderr


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


def test_activated_needs_enable_and_enable_needs_phase_1(trial):
    """Without `enable` no line is signed, so `activated` is refused; `enable`
    with IDX_ANALYSIS_TOOL not 1 in .env changes nothing."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    done = t.run("activated", str(run))
    assert done.returncode == 1 and "NOT ENABLED" in done.stderr
    t.edit_env(IDX_ANALYSIS_TOOL="0")
    before = (t.repo / ".env").read_text()
    refused = t.run("enable", str(run))
    assert refused.returncode == 1 and "Phase 1 is not on" in refused.stderr
    assert (t.repo / ".env").read_text() == before
    assert t.run("abort", str(run)).returncode == 0
    t.record(run, within=20)


# --- no consent token: the owner's trial approval covers arming and the rollback ---


@pytest.mark.parametrize("grant", ["none at all", "expired", "revoked mid-trial"])
def test_arming_needs_only_the_approval_and_the_rollback_needs_no_token(trial, grant):
    """Arming takes the owner's trial-approval reference and no consent token; the
    rollback runs with no token present at all, with an expired `delete` grant, and
    with one revoked (its file removed, as consent.sh revoke does) after arming. The
    temp repo has no scripts/guards: nothing reads a token."""
    t = trial(grant_minutes={"expired": -5, "revoked mid-trial": 60}.get(grant))
    assert not (t.repo / "scripts" / "guards").exists()
    assert t.grant_file().exists() is (grant != "none at all")
    run = t.arm("--timeout", "120", "--watch-after", "0")
    config = json.loads((run / "arm.json").read_text())
    assert config["approval"] == APPROVAL
    assert not any("grant" in name for name in config)
    t.activate(run)
    assert t.switches() == ["IDX_ANALYSIS_TOOL=1", "IDX_CHART_DELIVERY=1"]
    if grant == "revoked mid-trial":
        t.grant_file().unlink()
    assert t.run("done", str(run), "fail").returncode == 0
    record = t.record(run, within=20)
    assert f"  approval: {APPROVAL}; it authorizes arming and this rollback" in record
    assert "no consent token is read" in record
    assert "grant" not in record.split("\n\n")[0]  # the watchdog's own lines
    assert "  rollback: fail (operator done fail);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert t.switches() == OFF and t.restarts() == 1


def _utc(text: str) -> float:
    return (
        dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=dt.UTC)
        .timestamp()
    )


@pytest.mark.parametrize("grant_minutes", [None, 2])
def test_the_post_rollback_watch_has_a_default_window_no_grant_sets(
    trial, grant_minutes
):
    """No --watch-after: the watch lasts the documented default (3600 s) after the
    rollback, with no grant at all and with a delete grant that expires in 2 minutes
    (neither shortens nor extends it)."""
    t = trial(grant_minutes=grant_minutes)
    run = t.arm("--timeout", "120")
    assert "rolled back again for 3600 s after the rollback" in t.output
    assert t.run("abort", str(run)).returncode == 0
    record = t.record(run, within=20, containing="post-rollback watch: until")
    finished = re.search(r"finished (\S+Z), exit 0;", record).group(1)
    until = re.search(r"post-rollback watch: until (\S+Z) \(([^)]*)\)", record)
    assert until.group(2) == "--watch-after 3600 s"
    assert abs(_utc(until.group(1)) - _utc(finished) - 3600) <= 1
    status = t.run("status", str(run))
    assert status.returncode == 1 and "post-rollback watch running" in status.stdout


# --- the run's state lock is bounded ---


def test_a_held_state_lock_never_stops_the_rollback(trial):
    """Another process holds the run's state lock: `activated` refuses after the
    bounded wait, changing nothing; `done fail` still rolls back, `aborted`, with the
    claim and the tombstone written without the lock."""
    t = trial()
    run = t.arm("--timeout", "120", "--watch-after", "0")
    assert t.run("enable", str(run)).returncode == 0
    with open(run / "state.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        began = time.monotonic()
        busy = t.run("activated", str(run))
        assert busy.returncode == 1
        assert "REFUSED: the run's state lock" in busy.stderr
        assert "could not be taken within 5 s; nothing was changed" in busy.stderr
        assert 5 <= time.monotonic() - began < 5 + 10
        assert not (run / "activated").exists()
        assert t.run("done", str(run), "fail").returncode == 0
        record = t.record(run, within=30)
    assert (
        "watchdog: state lock not taken within 5 s (fail, operator done fail);"
        " claimed without it, rollback aborted"
    ) in record
    assert "  rollback: aborted (state lock not taken in time);" in record
    assert record.rstrip().endswith("ROLLBACK DONE: analysis off, chart delivery off")
    assert (run / "fired").exists() and (run / "tombstone").exists()
    assert t.switches() == OFF and t.restarts() == 1


# --- the signature: watchdog side ---


NOW = 1_800_000_000.0
TRIAL = {"trial_id": "c" * 32, "key": "d" * 64}


def _ok(t: float = NOW + 1, status: str = "ready") -> str:
    return _signed(TRIAL, status, t)


# Each case builds its line when it runs (lambda), so collection needs no signer.
LINES = {
    "ready": (lambda: _ok(), "pass", None),
    "failed": (lambda: _ok(status="failed"), "fail", None),
    # As a gateway might wrap a child's stderr: escaped once.
    "escaped once": (lambda: "[idx stderr] " + json.dumps(_ok()), "pass", None),
    "unsigned": (lambda: _line("ready"), None, "unsigned line"),
    "other trial": (
        lambda: _signed({**TRIAL, "trial_id": "e" * 32}, "ready", NOW + 1),
        None,
        "another",
    ),
    "other key": (
        lambda: _signed({**TRIAL, "key": "f" * 64}, "ready", NOW + 1),
        None,
        "HMAC",
    ),
    "status edited": (
        lambda: _ok(status="failed").replace("failed", "ready"),
        None,
        "HMAC",
    ),
    "trace edited": (lambda: _ok().replace("b" * 16, "a" * 16), None, "HMAC"),
    "before activated": (lambda: _ok(NOW - 1), None, "before `activated`"),
    "after the window": (lambda: _ok(NOW + 100), None, "outside the trial window"),
    "in the future": (lambda: _ok(NOW + 9), None, "outside the trial window"),
    "repeated fields": (lambda: _ok() + _line("ready"), None, "repeated"),
    "other event": (
        lambda: '{"event": "tool_call", "status": "ready", "trace_id": ""}',
        None,
        None,
    ),
}


@pytest.mark.parametrize("case", list(LINES))
def test_only_this_trials_signed_line_in_its_window_counts(case):
    """Activated at NOW, window 60 s, judged at NOW + 5 (2 s clock skew allowed)."""
    make, word, reason = LINES[case]
    got = ARMED.authenticate(
        make().encode(),
        TRIAL["trial_id"],
        bytes.fromhex(TRIAL["key"]),
        int(NOW * 1000),
        int((NOW + 60) * 1000),
        int((NOW + 5) * 1000),
    )
    assert got[0] == word
    assert (got[1] is None) if reason is None else (reason in got[1])


def test_the_watchdog_and_the_server_sign_the_same_bytes():
    args = ("c" * 32, "0123456789abcdef", "ready", 1_800_000_000_123)
    assert ARMED.mac_message(*args) == delivery.trial_message(*args)


def test_the_deadline_check_covers_the_whole_armed_window():
    """Defaults: 600 s activation + 600 s timeout + 600 s rollback + 60 s = 31 min."""
    assert ARMED.latest_end_seconds(600, 600) == 1860
    assert ARMED.latest_end_seconds(1800, 1800) == 4260


# --- the signature: server side ---


def _trial_file(tmp_path: Path, mode: int = 0o600, text: str | None = None) -> Path:
    path = tmp_path / "trial.key"
    path.write_text(json.dumps(TRIAL) if text is None else text)
    path.chmod(mode)
    return path


def test_no_trial_setting_gives_no_signer_and_no_problem():
    assert delivery.trial_signer(lambda _: None) == (None, None)


def test_a_valid_trial_file_gives_a_signer_whose_key_never_shows(tmp_path):
    path = _trial_file(tmp_path)
    signer, problem = delivery.trial_signer({delivery.TRIAL_SETTING: str(path)}.get)
    assert problem is None and signer.trial_id == TRIAL["trial_id"]
    assert TRIAL["key"] not in repr(signer)
    fields = signer.fields("t-1", "ready", now=NOW)
    assert set(fields) == {"trial_id", "trial_t", "trial_mac"}
    assert TRIAL["key"] not in json.dumps(fields)


@pytest.mark.parametrize(
    "case",
    ["relative", "missing", "symlink", "group readable", "not json", "bad id", "dir"],
)
def test_an_unusable_trial_file_gives_no_signer_and_a_problem(tmp_path, case):
    path = _trial_file(tmp_path)
    value = str(path)
    if case == "relative":
        value = "trial.key"
    elif case == "missing":
        value = str(tmp_path / "nope.key")
    elif case == "symlink":
        (tmp_path / "link.key").symlink_to(path)
        value = str(tmp_path / "link.key")
    elif case == "group readable":
        path.chmod(0o640)
    elif case == "not json":
        _trial_file(tmp_path, text="trial")
    elif case == "bad id":
        _trial_file(tmp_path, text=json.dumps({**TRIAL, "trial_id": "x"}))
    elif case == "dir":
        value = str(tmp_path)
    got = delivery.trial_signer({delivery.TRIAL_SETTING: value}.get)
    assert got == (None, delivery.TRIAL_UNUSABLE)


def test_a_fifo_trial_file_is_refused_without_blocking(tmp_path):
    """The server checks the path before opening it: a FIFO (mode 600, this user) is
    refused at once. Opened first, it would block the server's start for good."""
    path = tmp_path / "trial.fifo"
    os.mkfifo(path, 0o600)
    got: list = []
    reader_thread = threading.Thread(
        target=lambda: got.append(
            delivery.trial_signer({delivery.TRIAL_SETTING: str(path)}.get)
        ),
        daemon=True,
    )
    reader_thread.start()
    reader_thread.join(timeout=5)
    if reader_thread.is_alive():  # blocked in open(): unblock it, then fail
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        reader_thread.join(timeout=5)
        pytest.fail("the trial file was opened before it was checked (blocked)")
    assert got == [(None, delivery.TRIAL_UNUSABLE)]


def test_the_server_reads_the_trial_only_with_chart_delivery_on(
    tmp_path,
    monkeypatch,
    switch_on,  # noqa: F811 - the imported fixture
):
    """Off, the setting is not even read (an unusable path gives no problem); on,
    the start line names the trial id, never the key."""
    path = _trial_file(tmp_path)
    assert not charts_in_dotenv(monkeypatch, IDX_CHART_TRIAL_FILE="relative.key")
    assert server._chart_trial is None and server._chart_trial_problem is None
    charts = tmp_path / "workspace-idx" / "idx-charts"
    (tmp_path / "workspace-idx").mkdir()
    assert charts_in_dotenv(
        monkeypatch,
        IDX_CHART_DELIVERY="1",
        IDX_CHART_DIR=str(charts),
        IDX_CHART_TRIAL_FILE=str(path),
    )
    try:
        assert server._chart_trial.trial_id == TRIAL["trial_id"]
        started = server.log_start()
        assert started["chart_trial"] == TRIAL["trial_id"]
        assert TRIAL["key"] not in json.dumps(started)
    finally:
        delivery.reset_store_for_tests()
        server.reset_analysis_tool_for_tests()
    assert server._chart_trial is None


def test_content_blocks_signs_the_line_and_the_watchdog_accepts_it(tmp_path):
    """The delivery code's line, as log_event would write it, verifies."""
    workspace = tmp_path / "workspace-idx"
    workspace.mkdir()
    events = []
    signer = delivery.TrialSigner(TRIAL["trial_id"], bytes.fromhex(TRIAL["key"]))
    before = time.time()
    blocks = delivery.content_blocks(
        _payload(),
        PNG,
        delivery.ChartStore(workspace / "idx-charts"),
        lambda event, trace, **fields: events.append(
            {"event": event, "trace_id": trace, **fields}
        ),
        trial=signer,
    )
    [event] = events
    assert TRIAL["key"] not in json.dumps(event) + blocks[0].text
    word, reason, trace = ARMED.authenticate(
        json.dumps(event, sort_keys=True).encode(),
        TRIAL["trial_id"],
        bytes.fromhex(TRIAL["key"]),
        int(before * 1000) - 1,
        int(time.time() * 1000) + 1000,
        int(time.time() * 1000),
    )
    assert (word, reason, trace) == ("pass", None, "t-1")
