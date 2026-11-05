"""WO-030, D5: arm the chart-trial rollback BEFORE activation (CHART_DELIVERY.md 7).

The watchdog rolls back once, awaiting no reply; a pass needs the server's line signed
with this trial's key; afterwards a tombstone and a re-enable watch keep things off.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX only, like the rollback script
    fcntl = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[1]
ROLLBACK = REPO / "scripts" / "chart_trial_rollback.sh"
ENV_FILE = REPO / ".env"
LOCK_NAME = "chart-trial.lock"  # in the record dir: one watchdog at a time
STATE_LOCK = "state.lock"  # in the run dir: enable/activated/sent vs the claim
TRIAL_FILE = "trial.key"  # {"trial_id", "key"}, mode 600; the key is never printed
TOMBSTONE = "tombstone"  # written with the claim; never removed
REJECTED = "rejected.jsonl"
# Bounds in seconds: (default, lowest, highest).
ACTIVATION_LIMIT = (600, 1, 1800)  # arm -> `activated`; else rollback `aborted`
TIMEOUT = (600, 1, 1800)  # `activated` -> hard deadline; else rollback `fail`
SETTLE = (120, 0, 300)  # authenticated line seen -> rollback (the reply is sent first)
REPLY_WAIT = (120, 1, 600)  # `sent` -> no authenticated line -> rollback `fail`
WATCH_AFTER_MAX = 240 * 60  # the post-rollback watch; also capped by the grant
ROLLBACK_LIMIT = 600  # the rollback itself; the delete grant covers it too
GRANT_SLACK = 60
MAX_RERUNS = 3  # re-enables rolled back again before the watch gives up (by hand)
CLOCK_SKEW_MS = 2000
MAX_REJECT_NOTES = 10
POLL = 0.25
START_WAIT = 10.0  # how long `arm` waits for the watchdog to report itself
SWITCHES = ("IDX_ANALYSIS_TOOL", "IDX_CHART_DELIVERY")
TRIAL_SETTING = "IDX_CHART_TRIAL_FILE"  # idx_agent.analysis.delivery.TRIAL_SETTING
MAC_CONTEXT = "idx-chart-trial-v1"  # as delivery.trial_message
SAFE_PATH = re.compile(r"/[^\s\"'`\\#$]+")
# The server's chart_delivery log line (sorted-key JSON, maybe escaped once inside a
# gateway log line). Only these fields are read; nothing from a line is printed.
_Q = r'\\?"'
EVENT_RE = re.compile(_Q + "event" + _Q + r"\s*:\s*" + _Q + "chart_delivery" + _Q)


def _field(name: str, value: str) -> re.Pattern[str]:
    return re.compile(_Q + name + _Q + r"\s*:\s*" + value)


FIELDS = {
    "status": _field("status", _Q + r"([a-z_]{1,16})" + _Q),
    "trace_id": _field("trace_id", _Q + r"([0-9A-Za-z_-]{0,64})" + _Q),
    "trial_id": _field("trial_id", _Q + r"([0-9a-f]{32})" + _Q),
    "trial_t": _field("trial_t", r"([0-9]{1,16})\b"),
    "trial_mac": _field("trial_mac", _Q + r"([0-9a-f]{64})" + _Q),
}
STATUS_WORD = {"ready": "pass", "failed": "fail"}


def utc(t: float) -> str:
    """Unix time as `YYYY-MM-DDTHH:MM:SSZ`."""
    stamp = dt.datetime.fromtimestamp(t, dt.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def grant_expiry() -> float | None:
    """The delete grant's expiry if one is valid now, else None. Read only; the env
    overrides are ignored (as the commit gate does), so the grant is the human's."""
    guards = str(REPO / "scripts" / "guards")
    if guards not in sys.path:
        sys.path.insert(0, guards)
    import consent_token as ct

    if not ct.is_valid("delete", ignore_env=True):
        return None
    return ct.expiry("delete", ignore_env=True)


def required_grant_seconds(activation_limit: int, timeout: int) -> int:
    """Arm -> latest possible end of the rollback, plus slack."""
    return activation_limit + timeout + ROLLBACK_LIMIT + GRANT_SLACK


def mac_message(trial_id: str, trace_id: str, status: str, t_ms: int) -> bytes:
    """The bytes the server's HMAC covers (delivery.trial_message, pinned by a test)."""
    return "\n".join((MAC_CONTEXT, trial_id, trace_id, status, str(t_ms))).encode()


def authenticate(
    line: bytes, trial_id: str, key: bytes, after_ms: int, until_ms: int, now_ms: int
) -> tuple[str | None, str | None, str]:
    """Judge one log line. (`pass`|`fail`, None, trace id) for a chart_delivery line
    this trial's server signed after `after_ms` and by `until_ms`; (None, reason, "")
    for any other chart_delivery line; (None, None, "") for any other line."""
    text = line.decode("utf-8", "replace")
    if not EVENT_RE.search(text):
        return None, None, ""
    found: dict[str, str] = {}
    for name, pattern in FIELDS.items():
        values = pattern.findall(text)
        if len(values) != 1:
            return None, f"{name} missing, malformed or repeated (unsigned line)", ""
        found[name] = values[0]
    if found["status"] not in STATUS_WORD:
        return None, "status is not ready or failed", ""
    if found["trial_id"] != trial_id:
        return None, "another trial's id (replayed or another run)", ""
    t_ms = int(found["trial_t"])
    expected = hmac.new(
        key,
        mac_message(found["trial_id"], found["trace_id"], found["status"], t_ms),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, found["trial_mac"]):
        return None, "HMAC does not verify (not signed by this trial's server)", ""
    if t_ms <= after_ms:
        return None, "signed before `activated`", ""
    if t_ms > until_ms or t_ms > now_ms + CLOCK_SKEW_MS:
        return None, "signed outside the trial window", ""
    return STATUS_WORD[found["status"]], None, found["trace_id"]


def refuse(reason: str) -> int:
    print(f"REFUSED: {reason}. Nothing was armed; do not activate.", file=sys.stderr)
    return 1


def _bounded(value: int, bounds: tuple[int, int, int], name: str) -> int:
    if not bounds[1] <= value <= bounds[2]:
        raise SystemExit(refuse(f"{name} must be {bounds[1]}..{bounds[2]} s"))
    return value


def _private_dir(path: Path) -> str | None:
    """Why `path` cannot hold the record, or None."""
    if not path.is_dir() or path.is_symlink():
        return f"record directory {path} is not an existing directory"
    info = path.stat()
    if info.st_uid != os.getuid():
        return f"record directory {path} is not owned by this user"
    if info.st_mode & 0o077:
        return f"record directory {path} is mode {info.st_mode & 0o777:o}, not 700"
    if not os.access(path, os.W_OK | os.X_OK):
        return f"record directory {path} is not writable"
    return None


def _lock(record_dir: Path):
    """The record directory's lock, held exclusively, or None if another watchdog
    holds it (one armed trial at a time)."""
    handle = open(record_dir / LOCK_NAME, "a")  # noqa: SIM115 - held for the run
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


@contextmanager
def _state_lock(run: Path) -> Iterator[None]:
    """The run's state lock: `enable`, `activated` and `sent` check the tombstone and
    act under it, and the watchdog claims under it, so an activation step either
    lands before the claim (the rollback undoes it) or is refused. A lock that
    cannot be taken never stops the claim (fail-safe); the commands then refuse."""
    try:
        handle = open(run / STATE_LOCK, "a")  # noqa: SIM115 - closed below
    except OSError:
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _write_new(path: Path, text: str) -> bool:
    """Create `path` with `text` (mode 600); False if it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    return True


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watchdog_pid(run: Path) -> int | None:
    try:
        return int((run / "watchdog.pid").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_word(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


# --- .env: the same line rules as idx_agent.db.pool.dotenv_values ---


def _env_key(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    return text.partition("=")[0].strip().removeprefix("export ").strip()


def _env_value(line: str) -> str:
    return line.strip().partition("=")[2].strip().strip("\"'")


def dotenv_first(path: Path) -> dict[str, str]:
    """Each key's first value (the server's rule), {} without a readable file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    values: dict[str, str] = {}
    for line in lines:
        key = _env_key(line)
        if key is not None:
            values.setdefault(key, _env_value(line))
    return values


def set_env(path: Path, values: dict[str, str]) -> None:
    """Edit every line of each key in place to `KEY=value` (append it if absent);
    other lines and the file mode are kept; atomic replace."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    seen = set()
    for i, line in enumerate(lines):
        key = _env_key(line)
        if key in values:
            seen.add(key)
            lines[i] = f"{key}={values[key]}" + ("\n" if line.endswith("\n") else "")
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.extend(f"{key}={value}\n" for key, value in values.items() if key not in seen)
    mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write("".join(lines))
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def state_dir() -> Path:
    return Path(os.environ.get("OPENCLAW_STATE_DIR") or Path.home() / ".openclaw")


def reenabled() -> list[str]:
    """What is on again after the rollback: a switch line in `.env` that is not 0 or
    empty (any line, not only the first: stricter than the server), or install.sh's
    analysis fragment in the OpenClaw state dir. [] when everything is off."""
    found = set()
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for line in lines:
        key = _env_key(line)
        if key in SWITCHES and _env_value(line) not in ("", "0"):
            found.add(f".env {key} on")
    if (state_dir() / "openclaw.analysis.json5").exists():
        found.add("install state: openclaw.analysis.json5 present")
    return sorted(found)


# --- the commands ---


def cmd_arm(args: argparse.Namespace) -> int:
    """Refuse unless everything the rollback needs is there; else create the trial's
    id and key, start the watchdog and wait until it reports itself armed."""
    limit = _bounded(args.activation_limit, ACTIVATION_LIMIT, "--activation-limit")
    timeout = _bounded(args.timeout, TIMEOUT, "--timeout")
    settle = _bounded(args.settle, SETTLE, "--settle")
    reply_wait = _bounded(args.reply_wait, REPLY_WAIT, "--reply-wait")
    watch_after = args.watch_after
    if watch_after is not None:
        _bounded(watch_after, (0, 0, WATCH_AFTER_MAX), "--watch-after")
    if fcntl is None:
        return refuse("no fcntl on this platform")
    if not ROLLBACK.is_file():
        return refuse(f"the rollback script {ROLLBACK} is missing")
    record_dir = Path(args.record_dir).expanduser()
    problem = _private_dir(record_dir)
    if problem:
        return refuse(problem)
    log = Path(args.log).expanduser().resolve() if args.log else None
    if log is not None and not log.is_file():
        return refuse(f"the log file {log} does not exist")
    now = time.time()
    need = required_grant_seconds(limit, timeout)
    expiry = grant_expiry()
    if expiry is None:
        return refuse(
            "no valid delete grant; the owner issues one before arming, at least"
            f" {-(-need // 60)} minutes: ! scripts/guards/consent.sh delete <minutes>"
        )
    if expiry < now + need:
        return refuse(
            f"the delete grant expires {utc(expiry)}, before the latest rollback end"
            f" {utc(now + need)} (arm + {limit} s activation + {timeout} s timeout +"
            f" {ROLLBACK_LIMIT} s rollback + {GRANT_SLACK} s); it needs at least"
            f" {-(-need // 60)} minutes from now"
        )
    probe = _lock(record_dir)
    if probe is None:
        return refuse(f"another armed trial's watchdog holds {record_dir / LOCK_NAME}")
    probe.close()
    run = record_dir / f"chart-trial-{utc(now).replace(':', '')}-{os.getpid()}"
    run.mkdir(mode=0o700)
    trial_id = secrets.token_hex(16)
    _write_new(
        run / TRIAL_FILE,
        json.dumps({"trial_id": trial_id, "key": secrets.token_hex(32)}) + "\n",
    )
    config = {
        "armed": now,
        "activation_limit": limit,
        "timeout": timeout,
        "settle": settle,
        "reply_wait": reply_wait,
        "watch_after": watch_after,
        "log": str(log) if log else None,
        "grant_expiry": expiry,
        "trial_id": trial_id,
    }
    _write_new(run / "arm.json", json.dumps(config, sort_keys=True) + "\n")
    with open(run / "watchdog.log", "ab") as out:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()), "_watch", str(run)],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.monotonic() + START_WAIT
    while time.monotonic() < deadline:
        if _watchdog_pid(run) == proc.pid:
            break
        if proc.poll() is not None:
            return refuse(f"the watchdog exited at start; see {run / 'watchdog.log'}")
        time.sleep(0.05)
    else:
        proc.kill()
        return refuse("the watchdog did not report itself armed within 10 s")
    print(f"ARMED: {run}")
    print(f"  watchdog pid {proc.pid}, own session: it outlives this shell")
    print(
        f"  trial id {trial_id}; its key stays in {run / TRIAL_FILE} (mode 600),"
        " never printed; only chart_delivery lines signed with it count"
    )
    print(
        f"  delete grant: valid until {utc(expiry)} ({(expiry - now) / 60:.0f} min"
        f" left; needs >= {-(-need // 60)} min); time-bound, it covers every agent"
        " delete until then"
    )
    print(f"  step 1: scripts/chart_trial_armed.sh enable {run}")
    print(
        f"  confirm activation by {utc(now + limit)}:"
        f" scripts/chart_trial_armed.sh activated {run}"
        " (else the rollback runs, aborted)"
    )
    print(
        f"  rollback, without waiting for any reply: at most {timeout} s after"
        f" activation (fail); {reply_wait} s after `sent` without a signed line"
        " (fail); "
        + (
            f"{settle} s after a chart_delivery line in {log} signed for this trial"
            " (ready: pass, failed: fail)"
            if log
            else "no --log: no signed line can be seen, so this trial cannot pass"
        )
    )
    print(
        "  after the rollback: a tombstone (this trial cannot be activated again);"
        " a re-enable is rolled back again "
        + (
            f"until the delete grant's expiry {utc(expiry)}"
            if watch_after is None
            else f"for {watch_after} s after the rollback (never past {utc(expiry)})"
        )
    )
    print(f"  activation failed: scripts/chart_trial_armed.sh abort {run}")
    print(
        f"  deadline check (agent): by {utc(now + need)} run"
        f' scripts/chart_trial_armed.sh status {run}; "NOT RUNNING and no record"'
        " (SIGKILL, logout, reboot: not covered by the watchdog) means: run"
        " scripts/chart_trial_rollback.sh aborted now"
    )
    return 0


def _closed(run: Path) -> str | None:
    """Why the trial is closed (its rollback has fired: tombstone), or None."""
    for name in (TOMBSTONE, "fired"):
        claim = _read_json(run / name)
        if claim is not None or (run / name).exists():
            when = utc(claim["t"]) if claim and "t" in claim else "?"
            word = (claim or {}).get("result", "?")
            return f"the rollback has already fired ({word}, {when}; {TOMBSTONE})"
    return None


def _live_run(run: Path) -> str | None:
    """Why `run` has no live watchdog to signal, or None."""
    closed = _closed(run)
    if closed:
        return closed
    pid = _watchdog_pid(run)
    if pid is None or not _alive(pid):
        return "no live watchdog for this run"
    return None


def _not_armed(problem: str) -> int:
    print(
        f"NOT ARMED: {problem}. This trial cannot be activated again; nothing was"
        " changed. Any activation step run since then is undone only by running"
        " scripts/chart_trial_rollback.sh aborted again, now.",
        file=sys.stderr,
    )
    return 1


def cmd_enable(args: argparse.Namespace) -> int:
    """Step 1, `.env` only: IDX_CHART_DELIVERY=1 and IDX_CHART_TRIAL_FILE naming this
    run's trial file. Refused once the trial is closed (tombstone)."""
    run = Path(args.run)
    with _state_lock(run):
        problem = _live_run(run)
        if problem:
            return _not_armed(problem)
        if (run / "activated").exists():
            print("REFUSED: already activated; enable comes before it", file=sys.stderr)
            return 1
        trial = run / TRIAL_FILE
        if _read_json(trial) is None or not SAFE_PATH.fullmatch(str(trial)):
            print(
                f"REFUSED: {trial} is missing or its path has spaces, quotes or `#`;"
                " nothing was changed",
                file=sys.stderr,
            )
            return 1
        if not ENV_FILE.is_file():
            print(f"REFUSED: no {ENV_FILE}; nothing was changed", file=sys.stderr)
            return 1
        if dotenv_first(ENV_FILE).get("IDX_ANALYSIS_TOOL") != "1":
            print(
                "REFUSED: IDX_ANALYSIS_TOOL is not 1 in .env (Phase 1 is not on);"
                " nothing was changed",
                file=sys.stderr,
            )
            return 1
        set_env(ENV_FILE, {"IDX_CHART_DELIVERY": "1", TRIAL_SETTING: str(trial)})
        _write_new(run / "enabled", json.dumps({"t": time.time()}) + "\n")
    print(
        f"ENABLED: .env IDX_CHART_DELIVERY=1, {TRIAL_SETTING}={trial}"
        " (the server signs its chart_delivery lines for this trial);"
        " next: scripts/install.sh"
    )
    return 0


def cmd_activated(args: argparse.Namespace) -> int:
    """Steps 1-3 done: start the trial timeout and the completion-signal watch."""
    run = Path(args.run)
    with _state_lock(run):
        problem = _live_run(run)
        if problem:
            return _not_armed(problem)
        if not (run / "enabled").exists():
            print(
                f"NOT ENABLED: run scripts/chart_trial_armed.sh enable {run} first"
                " (step 1); without it no line is signed and the trial cannot pass",
                file=sys.stderr,
            )
            return 1
        log = json.loads((run / "arm.json").read_text()).get("log")
        offset = Path(log).stat().st_size if log and Path(log).is_file() else 0
        mark = {"t": time.time(), "offset": offset}
        if not _write_new(run / "activated", json.dumps(mark) + "\n"):
            print("already marked activated", file=sys.stderr)
            return 1
    print(f"ACTIVATED {utc(mark['t'])}: the watchdog's trial timeout has started")
    return 0


def cmd_sent(args: argparse.Namespace) -> int:
    """Step 4, the trial message was sent: starts the no-reply countdown."""
    run = Path(args.run)
    with _state_lock(run):
        problem = _live_run(run)
        if problem:
            return _not_armed(problem)
        config = _read_json(run / "arm.json") or {}
        if not (run / "activated").exists():
            print("REFUSED: not activated yet; nothing was marked", file=sys.stderr)
            return 1
        mark = {"t": time.time()}
        if not _write_new(run / "sent", json.dumps(mark) + "\n"):
            print("already marked sent", file=sys.stderr)
            return 1
    wait = config.get("reply_wait", REPLY_WAIT[0])
    print(
        f"SENT {utc(mark['t'])}: no signed chart_delivery line by"
        f" {utc(mark['t'] + wait)} -> rollback fail"
    )
    return 0


def cmd_signal(args: argparse.Namespace) -> int:
    """`abort` (activation failed) or `done fail` (the trial visibly failed): the
    watchdog runs the rollback within a second. `done pass` is refused: a pass comes
    only from the server's signed chart_delivery line."""
    run = Path(args.run)
    if args.cmd == "done" and args.word != "fail":
        print(
            "REFUSED: a manual pass is not accepted; a pass comes only from the"
            " server's chart_delivery line signed for this trial. Use `done RUN fail`"
            " or `abort RUN` to roll back early; nothing was signalled.",
            file=sys.stderr,
        )
        return 2
    name, text = ("abort", "aborted") if args.cmd == "abort" else ("done", "fail")
    problem = _live_run(run)
    if problem and not _closed(run):
        print(
            f"NOT ARMED: {problem}. Run scripts/chart_trial_rollback.sh {text} now.",
            file=sys.stderr,
        )
        return 1
    if problem:
        print(problem)
        return 0
    _write_new(run / name, text + "\n")
    print(f"signalled {name}; the record will be {run / 'record.txt'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Exit 0 only while armed and not fired: the check before each activation step.
    Also the agent's deadline check: a dead watchdog with no record is said plainly."""
    run = Path(args.run)
    record = run / "record.txt"
    pid = _watchdog_pid(run)
    alive = pid is not None and _alive(pid)
    if record.is_file():
        print(record.read_text(), end="")
        if alive:
            print(f"post-rollback watch running; watchdog pid {pid}")
        return 1
    if not alive:
        print(
            f"NOT RUNNING and no record: watchdog pid {pid} ended without a rollback"
            " record (SIGKILL, logout or reboot). Run scripts/chart_trial_rollback.sh"
            " aborted now."
        )
        return 3
    state = "fired, rollback running" if _closed(run) else "armed"
    if (run / "activated").exists() and state == "armed":
        state = "armed, activated"
    print(f"{state}; watchdog pid {pid} alive")
    return 0 if not _closed(run) else 1


class _LogTail:
    """New lines of the log since an offset; follows a rename-rotation to the new
    file. Lines are matched, never kept or printed."""

    def __init__(self, path: str, offset: int) -> None:
        self.path, self.handle, self.inode, self.buffer = path, None, None, b""
        self._open(offset)

    def _open(self, offset: int) -> None:
        try:
            self.handle = open(self.path, "rb")  # noqa: SIM115 - kept open to follow
        except OSError:
            self.handle = None
            return
        self.inode = os.fstat(self.handle.fileno()).st_ino
        self.handle.seek(min(offset, os.fstat(self.handle.fileno()).st_size))

    def lines(self) -> list[bytes]:
        out: list[bytes] = []
        if self.handle is not None:
            self.buffer += self.handle.read()
        try:
            rotated = os.stat(self.path).st_ino != self.inode
        except OSError:
            rotated = False
        if rotated or self.handle is None:
            if self.handle is not None:
                self.handle.close()
            self._open(0)
            if self.handle is not None:
                self.buffer += self.handle.read()
        *done, self.buffer = self.buffer.split(b"\n")
        out.extend(done)
        return out


class Watchdog:
    """One armed run: decide, roll back once, then block a re-enable for a while."""

    def __init__(self, run: Path, config: dict) -> None:
        self.run, self.config = run, config
        self.notes: list[str] = []
        self.after: list[str] = []
        self.terminated: list[int] = []
        self.rejected = 0
        self.trial_id: str | None = config.get("trial_id")
        self.started = False
        self.result, self.reason, self.code = "aborted", "", 1
        self.fired_t = self.finished = 0.0
        self.at_fire = "?"
        self.output = ""

    # -- deciding --

    def reject(self, now: float, reason: str) -> None:
        self.rejected += 1
        with open(self.run / REJECTED, "a", encoding="utf-8") as out:
            out.write(json.dumps({"t": now, "reason": reason}) + "\n")
        if self.rejected <= MAX_REJECT_NOTES:
            self.notes.append(f"signal: rejected a line {utc(now)}: {reason}")

    def watch(self) -> tuple[str, str]:
        """The decision loop; returns the rollback's (result word, reason)."""
        run, cfg = self.run, self.config
        trial = _read_json(run / TRIAL_FILE)
        if trial is None:
            raise RuntimeError("the trial file is missing or unreadable")
        self.trial_id, key = trial["trial_id"], bytes.fromhex(trial["key"])
        armed, limit = cfg["armed"], cfg["activation_limit"]
        reply_wait = cfg.get("reply_wait", REPLY_WAIT[0])
        tail: _LogTail | None = None
        pending: tuple[str, str, float] | None = None
        activated: dict | None = None
        sent: dict | None = None
        done_seen: str | None = None
        while True:
            now = time.time()
            if self.terminated:
                self.notes.append(f"watchdog: SIGTERM at {utc(now)}")
                return "aborted", "watchdog terminated"
            if (run / "fired").exists() or (run / TOMBSTONE).exists():
                # Only this watchdog writes them, and it has not yet: tampering.
                self.notes.append(
                    f"watchdog: a claim it did not write appeared {utc(now)}"
                    " (tampered); rolling back"
                )
                return "aborted", "claim written by another process"
            if (run / "abort").exists():
                self.notes.append(f"activation: abort requested {utc(now)}")
                return "aborted", "activation failed"
            done = _read_word(run / "done")
            if done == "fail":
                self.notes.append(f"signal: operator done fail {utc(now)}")
                return "fail", "operator done fail"
            if done is not None and done != done_seen:
                done_seen = done
                self.reject(now, "operator `done` file is not `fail` (no manual pass)")
            if activated is None:
                activated = _read_json(run / "activated")
                if activated is not None:
                    self.notes.append(f"activation: confirmed {utc(activated['t'])}")
                    if cfg.get("log"):
                        tail = _LogTail(cfg["log"], int(activated.get("offset", 0)))
            if activated is None:
                if now >= armed + limit:
                    self.notes.append(
                        f"activation: not confirmed by {utc(armed + limit)}"
                    )
                    return "aborted", "activation not confirmed"
                time.sleep(POLL)
                continue
            deadline = activated["t"] + cfg["timeout"]
            if sent is None:
                sent = _read_json(run / "sent")
                if sent is not None:
                    self.notes.append(
                        f"sent: trial message sent {utc(sent['t'])}; no signed line"
                        f" by {utc(sent['t'] + reply_wait)} -> fail"
                    )
            for line in tail.lines() if tail is not None and pending is None else []:
                word, reason, trace = authenticate(
                    line,
                    self.trial_id,
                    key,
                    int(activated["t"] * 1000),
                    int(deadline * 1000),
                    int(now * 1000),
                )
                if reason is not None:
                    self.reject(now, reason)
                elif word is not None:
                    self.notes.append(
                        f"signal: chart_delivery line signed for this trial"
                        f" ({'ready' if word == 'pass' else 'failed'}, trace {trace})"
                        f" seen {utc(now)}"
                    )
                    self.notes.append(
                        "signal: proves only that a tool server on this .env signed it"
                        " in the window (any call, not only the trial turn); the trial"
                        " result is the step 5 observation on the phone"
                    )
                    settle_end = now + cfg["settle"]
                    pending = (word, "authenticated chart_delivery line", settle_end)
                    break
            if pending is not None and now >= min(pending[2], deadline):
                return pending[0], pending[1]
            if pending is None and sent is not None and now >= sent["t"] + reply_wait:
                self.notes.append(
                    f"signal: no signed chart_delivery line within {reply_wait} s of"
                    f" sent ({utc(sent['t'] + reply_wait)})"
                )
                return "fail", "no reply after sent"
            if now >= deadline:
                self.notes.append(f"signal: none by the timeout {utc(deadline)}")
                return "fail", "trial timeout"
            time.sleep(POLL)

    # -- rolling back --

    def rollback(self, result: str, log_name: str) -> int:
        """Run the rollback script once; its output goes to `<run>/<log_name>`."""
        with open(self.run / log_name, "wb") as out:
            try:
                return subprocess.run(
                    ["bash", str(ROLLBACK), result],
                    cwd=REPO,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=ROLLBACK_LIMIT,
                    check=False,
                ).returncode
            except subprocess.TimeoutExpired:
                out.write(b"ROLLBACK INCOMPLETE: the rollback ran past its limit\n")
                return -1
            except OSError as exc:
                out.write(f"ROLLBACK INCOMPLETE: {type(exc).__name__}\n".encode())
                return -1

    def fire(self, result: str, reason: str) -> int:
        """Claim the run (`fired` and the tombstone, under the state lock), run the
        rollback once and write the record. This process holds the record-dir lock,
        so it is the run's only watchdog: a claim it cannot write, or one that is
        already there (not written by it: cmd_watch checks under the lock), never
        stops it."""
        if self.started:
            return self.code
        self.fired_t = time.time()
        claim = json.dumps({"result": result, "reason": reason, "t": self.fired_t})
        try:
            with _state_lock(self.run):
                if not _write_new(self.run / "fired", claim + "\n"):
                    self.notes.append(
                        "watchdog: claim pre-existed (tampered); rolling back anyway"
                    )
                _write_new(self.run / TOMBSTONE, claim + "\n")
        except OSError as exc:
            self.notes.append(f"watchdog: claim not written ({type(exc).__name__})")
        self.started = True
        self.result, self.reason = result, reason
        try:
            expiry = grant_expiry()
        except Exception:  # noqa: BLE001 - the record says so; the rollback runs
            expiry = None
        self.at_fire = (
            f"valid until {utc(expiry)}" if expiry else "NOT VALID (revoked/expired)"
        )
        self.code = self.rollback(result, "rollback.log")
        self.finished = time.time()
        try:
            self.output = (self.run / "rollback.log").read_text(errors="replace")
        except OSError:
            self.output = ""
        lines = self.write_record()
        print("\n".join(lines[:7]), flush=True)
        return self.code

    def write_record(self) -> list[str]:
        cfg = self.config
        grant = cfg.get("grant_expiry")
        shown = self.notes
        if self.rejected > MAX_REJECT_NOTES:
            more = self.rejected - MAX_REJECT_NOTES
            shown = [*shown, f"signal: {more} more rejected line(s) in {REJECTED}"]
        lines = [
            "chart trial armed-rollback record (WO-030, D5)",
            f"  run: {self.run.name}",
            f"  trial: {self.trial_id}; only chart_delivery lines signed with its key"
            f" count; rejected lines: {self.rejected}",
            f"  armed: {utc(cfg['armed']) if 'armed' in cfg else '?'};"
            f" watchdog pid {os.getpid()}",
            f"  delete grant: valid until {utc(grant) if grant else '?'} at arm;"
            f" {self.at_fire} at rollback",
            *[f"  {note}" for note in shown],
            f"  rollback: {self.result} ({self.reason}); fired {utc(self.fired_t)},"
            f" finished {utc(self.finished)}, exit {self.code}; no reply was awaited",
            *[f"  {line}" for line in self.after],
            "",
            self.output.rstrip("\n"),
        ]
        tmp = self.run / ".record.tmp"
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.run / "record.txt")
        return lines

    # -- after the rollback --

    def post_watch(self) -> None:
        """Until the delete grant's expiry (or --watch-after), roll back again when a
        switch or the analysis fragment is back on; at most MAX_RERUNS times."""
        watch_after = self.config.get("watch_after")
        end, why = float(self.config.get("grant_expiry") or 0), "the grant's expiry"
        if watch_after is not None and self.finished + watch_after < end:
            end, why = self.finished + watch_after, f"--watch-after {watch_after} s"
        if end <= time.time():
            self.after.append(f"post-rollback watch: none ({why} has passed)")
            self.write_record()
            return
        self.after.append(
            f"post-rollback watch: until {utc(end)} ({why}); a re-enable is rolled"
            " back again"
        )
        self.write_record()
        reruns, ended = 0, why
        while True:
            now = time.time()
            if self.terminated:
                ended = "SIGTERM"
                break
            if now >= end:
                break
            found = reenabled()
            if found:
                if reruns >= MAX_RERUNS:
                    what = ", ".join(found)
                    self.after.append(
                        f"re-enable still on after {reruns} reruns ({what}):"
                        " roll back by hand, now"
                    )
                    ended = "rerun limit"
                    break
                reruns += 1
                self.rerun(f"re-enable blocked {utc(now)}: {', '.join(found)}", reruns)
            time.sleep(POLL)
        self.after.append(f"post-rollback watch: ended {utc(time.time())} ({ended})")
        self.write_record()

    def rerun(self, why: str, n: int) -> None:
        name = f"rollback-{n + 1}.log"
        code = self.rollback(self.result, name)
        try:
            last = (self.run / name).read_text(errors="replace").rstrip().splitlines()
        except OSError:
            last = []
        self.after.append(
            f"{why}; rollback {self.result} run again ({name}): exit {code},"
            f" {last[-1] if last else 'no output'}"
        )
        self.write_record()

    def run_safely(self) -> int:
        """watch -> fire -> post_watch; any unexpected exception rolls back."""
        try:
            result, reason = self.watch()
        except Exception as exc:  # noqa: BLE001 - the fail-safe is the point
            self.notes.append(
                f"watchdog: unexpected {type(exc).__name__} at {utc(time.time())};"
                " fail-safe rollback"
            )
            result, reason = "aborted", f"fail-safe, {type(exc).__name__}"
        try:
            code = self.fire(result, reason)
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"watchdog: {type(exc).__name__} while rolling back")
            if not self.started:
                self.started = True
                self.result, self.reason = "aborted", f"fail-safe, {type(exc).__name__}"
                self.code = self.rollback("aborted", "rollback.log")
            code = self.code
            try:
                self.write_record()
            except Exception:  # noqa: BLE001, S110 - the rollback has run
                pass
        if not self.started:
            return code  # another process claimed the run before this one started
        try:
            self.post_watch()
        except Exception as exc:  # noqa: BLE001
            self.rerun(
                f"post-rollback watch: unexpected {type(exc).__name__}; fail-safe",
                MAX_RERUNS + 1,
            )
        return code


def cmd_watch(args: argparse.Namespace) -> int:
    """The watchdog: one decision per poll, so a signal and a timeout that race still
    fire once; the `fired` claim and the lock make that hold across processes."""
    run = Path(args.run)
    config = _read_json(run / "arm.json")
    if config is None:
        print("watchdog: no arm.json", flush=True)
        return 1
    if (run / "fired").exists():
        print("watchdog: the rollback has already fired; not watching", flush=True)
        return 0
    lock = _lock(run.parent)
    if lock is None:
        print("watchdog: another watchdog holds the lock; not watching", flush=True)
        return 1
    if (run / "fired").exists():  # claimed by one that has since let go of the lock
        print("watchdog: the rollback has already fired; not watching", flush=True)
        return 0
    dog = Watchdog(run, config)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda signum, _frame: dog.terminated.append(signum))
    (run / "watchdog.pid").write_text(f"{os.getpid()}\n")
    print(f"watchdog armed {utc(time.time())}, pid {os.getpid()}", flush=True)
    return dog.run_safely()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/chart_trial_armed.sh")
    sub = parser.add_subparsers(dest="cmd", required=True)
    arm = sub.add_parser("arm", help="start the watchdog; before step 1")
    arm.add_argument("--record-dir", required=True, help="existing, mode 700")
    arm.add_argument("--log", help="the idx server log (IDX_LOG_FILE) to watch")
    arm.add_argument("--activation-limit", type=int, default=ACTIVATION_LIMIT[0])
    arm.add_argument("--timeout", type=int, default=TIMEOUT[0])
    arm.add_argument("--settle", type=int, default=SETTLE[0])
    arm.add_argument("--reply-wait", type=int, default=REPLY_WAIT[0])
    arm.add_argument(
        "--watch-after", type=int, default=None, help="default: the grant's expiry"
    )
    for name in ("enable", "activated", "sent", "abort", "status", "_watch"):
        sub.add_parser(name).add_argument("run")
    done = sub.add_parser("done")
    done.add_argument("run")
    done.add_argument("word")
    args = parser.parse_args(argv)
    # Paths are taken from the caller's directory; then the repo is the working
    # directory, so the consent dir resolves from this checkout and nowhere else.
    for name in ("record_dir", "log", "run"):
        value = getattr(args, name, None)
        if value:
            setattr(args, name, os.path.abspath(os.path.expanduser(value)))
    os.chdir(REPO)
    handlers = {
        "arm": cmd_arm,
        "enable": cmd_enable,
        "activated": cmd_activated,
        "sent": cmd_sent,
        "abort": cmd_signal,
        "done": cmd_signal,
        "status": cmd_status,
        "_watch": cmd_watch,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
