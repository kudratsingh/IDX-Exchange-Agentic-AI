"""WO-030, D5: arm the chart-trial rollback BEFORE activation (CHART_DELIVERY.md 7).

`arm` checks the rollback script, the record dir and the delete grant, then starts a
watchdog in its own session that runs `chart_trial_rollback.sh` exactly once, awaiting
no reply, on the first of: abort, done, chart_delivery line (+settle), or a timeout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX only, like the rollback script
    fcntl = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[1]
ROLLBACK = REPO / "scripts" / "chart_trial_rollback.sh"
LOCK_NAME = "chart-trial.lock"
# Bounds in seconds: (default, lowest, highest).
ACTIVATION_LIMIT = (600, 1, 1800)  # arm -> `activated`; else rollback `aborted`
TIMEOUT = (600, 1, 1800)  # `activated` -> hard deadline; else rollback `fail`
SETTLE = (120, 0, 300)  # chart_delivery seen -> rollback (the reply is sent first)
ROLLBACK_LIMIT = 600  # the rollback itself; the delete grant covers it too
GRANT_SLACK = 60
POLL = 0.25
START_WAIT = 10.0  # how long `arm` waits for the watchdog to report itself
# The server's chart_delivery log line (sorted-key JSON, maybe escaped once inside a
# gateway log line). Only the event name and the status are read; nothing is printed.
EVENT_RE = re.compile(r'\\?"event\\?"\s*:\s*\\?"chart_delivery\\?"')
STATUS_RE = re.compile(r'\\?"status\\?"\s*:\s*\\?"(ready|failed)\\?"')
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


def cmd_arm(args: argparse.Namespace) -> int:
    """Refuse unless everything the rollback needs is there; else start the watchdog
    and wait until it reports itself armed."""
    limit = _bounded(args.activation_limit, ACTIVATION_LIMIT, "--activation-limit")
    timeout = _bounded(args.timeout, TIMEOUT, "--timeout")
    settle = _bounded(args.settle, SETTLE, "--settle")
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
    config = {
        "armed": now,
        "activation_limit": limit,
        "timeout": timeout,
        "settle": settle,
        "log": str(log) if log else None,
        "grant_expiry": expiry,
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
        f"  delete grant: valid until {utc(expiry)} ({(expiry - now) / 60:.0f} min"
        f" left; needs >= {-(-need // 60)} min); time-bound, it covers every agent"
        " delete until then"
    )
    print(
        f"  confirm activation by {utc(now + limit)}:"
        f" scripts/chart_trial_armed.sh activated {run}"
        " (else the rollback runs, aborted)"
    )
    print(
        f"  rollback, without waiting for any reply: at most {timeout} s after"
        " activation (fail); "
        + (
            f"{settle} s after a chart_delivery line in {log}"
            " (ready: pass, failed: fail)"
            if log
            else "no completion signal configured (no --log)"
        )
    )
    print(f"  activation failed: scripts/chart_trial_armed.sh abort {run}")
    return 0


def _live_run(run: Path) -> str | None:
    """Why `run` has no live watchdog to signal, or None."""
    if (run / "fired").exists():
        return f"the rollback has already fired: {(run / 'fired').read_text().strip()}"
    pid = _watchdog_pid(run)
    if pid is None or not _alive(pid):
        return "no live watchdog for this run"
    return None


def cmd_activated(args: argparse.Namespace) -> int:
    """Steps 1-3 done: start the trial timeout and the completion-signal watch."""
    run = Path(args.run)
    problem = _live_run(run)
    if problem:
        print(
            f"NOT ARMED: {problem}. Any activation step run since then is undone"
            " only by running scripts/chart_trial_rollback.sh aborted again, now.",
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


def cmd_signal(args: argparse.Namespace) -> int:
    """`abort` (activation failed) or `done pass|fail` (the reply was seen): the
    watchdog runs the rollback within a second."""
    run = Path(args.run)
    name, text = ("abort", "aborted\n") if args.cmd == "abort" else ("done", args.word)
    problem = _live_run(run)
    if problem and not (run / "fired").exists():
        print(
            f"NOT ARMED: {problem}. Run scripts/chart_trial_rollback.sh "
            f"{text.strip()} now.",
            file=sys.stderr,
        )
        return 1
    if problem:
        print(problem)
        return 0
    _write_new(run / name, text.strip() + "\n")
    print(f"signalled {name}; the record will be {run / 'record.txt'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Exit 0 only while armed and not fired: the check before each activation step."""
    run = Path(args.run)
    record = run / "record.txt"
    if record.is_file():
        print(record.read_text(), end="")
        return 1
    pid = _watchdog_pid(run)
    state = "fired, rollback running" if (run / "fired").exists() else "armed"
    if (run / "activated").exists() and state == "armed":
        state = "armed, activated"
    alive = pid is not None and _alive(pid)
    print(f"{state}; watchdog pid {pid} {'alive' if alive else 'NOT RUNNING'}")
    return 0 if alive and not (run / "fired").exists() else 1


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


def completion(line: bytes) -> str | None:
    """`pass` or `fail` for a chart_delivery line (status ready / failed), else None."""
    text = line.decode("utf-8", "replace")
    if not EVENT_RE.search(text):
        return None
    found = STATUS_RE.search(text)
    return STATUS_WORD[found.group(1)] if found else None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def fire(run: Path, config: dict, result: str, reason: str, notes: list[str]) -> int:
    """Run the rollback once (the `fired` file is the claim) and write the record."""
    started = time.time()
    claim = json.dumps({"result": result, "reason": reason, "t": started})
    if not _write_new(run / "fired", claim + "\n"):
        return 0
    expiry = grant_expiry()
    at_fire = f"valid until {utc(expiry)}" if expiry else "NOT VALID (revoked/expired)"
    with open(run / "rollback.log", "wb") as out:
        try:
            code = subprocess.run(
                ["bash", str(ROLLBACK), result],
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=ROLLBACK_LIMIT,
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            code = -1
            out.write(b"ROLLBACK INCOMPLETE: the rollback ran past its limit\n")
    finished = time.time()
    output = (run / "rollback.log").read_text(encoding="utf-8", errors="replace")
    lines = [
        "chart trial armed-rollback record (WO-030, D5)",
        f"  run: {run.name}",
        f"  armed: {utc(config['armed'])}; watchdog pid {os.getpid()}",
        f"  delete grant: valid until {utc(config['grant_expiry'])} at arm;"
        f" {at_fire} at rollback",
        *[f"  {note}" for note in notes],
        f"  rollback: {result} ({reason}); fired {utc(started)}, finished"
        f" {utc(finished)}, exit {code}; no reply was awaited",
        "",
        output.rstrip("\n"),
    ]
    tmp = run / ".record.tmp"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, run / "record.txt")
    print("\n".join(lines[:6]), flush=True)
    return code


def cmd_watch(args: argparse.Namespace) -> int:
    """The watchdog loop: one decision per poll, so a signal and a timeout that race
    still fire once; the `fired` claim and the lock make that hold across processes."""
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
    terminated: list[int] = []
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda signum, _frame: terminated.append(signum))
    (run / "watchdog.pid").write_text(f"{os.getpid()}\n")
    print(f"watchdog armed {utc(time.time())}, pid {os.getpid()}", flush=True)
    armed, limit = config["armed"], config["activation_limit"]
    notes: list[str] = []
    tail: _LogTail | None = None
    pending: tuple[str, str, float] | None = None
    activated: dict | None = None
    while True:
        now = time.time()
        if terminated:
            notes.append(f"watchdog: SIGTERM at {utc(now)}")
            return fire(run, config, "aborted", "watchdog terminated", notes)
        if (run / "abort").exists():
            notes.append(f"activation: abort requested {utc(now)}")
            return fire(run, config, "aborted", "activation failed", notes)
        done = (run / "done").exists() and (run / "done").read_text().strip()
        if done in ("pass", "fail"):
            notes.append(f"signal: operator saw the reply ({done}) {utc(now)}")
            return fire(run, config, done, "operator signal", notes)
        if activated is None:
            activated = _read_json(run / "activated")
            if activated is not None:
                notes.append(f"activation: confirmed {utc(activated['t'])}")
                if config.get("log"):
                    tail = _LogTail(config["log"], int(activated.get("offset", 0)))
        if activated is None:
            if now >= armed + limit:
                notes.append(f"activation: not confirmed by {utc(armed + limit)}")
                return fire(run, config, "aborted", "activation not confirmed", notes)
        else:
            deadline = activated["t"] + config["timeout"]
            for line in tail.lines() if tail is not None and pending is None else []:
                word = completion(line)
                if word is not None:
                    notes.append(f"signal: chart_delivery line seen {utc(now)}")
                    pending = (word, "chart_delivery line", now + config["settle"])
                    break
            if pending is not None and now >= min(pending[2], deadline):
                return fire(run, config, pending[0], pending[1], notes)
            if now >= deadline:
                notes.append(f"signal: none by the timeout {utc(deadline)}")
                return fire(run, config, "fail", "trial timeout", notes)
        time.sleep(POLL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/chart_trial_armed.sh")
    sub = parser.add_subparsers(dest="cmd", required=True)
    arm = sub.add_parser("arm", help="start the watchdog; before step 1")
    arm.add_argument("--record-dir", required=True, help="existing, mode 700")
    arm.add_argument("--log", help="the idx server log (IDX_LOG_FILE) to watch")
    arm.add_argument("--activation-limit", type=int, default=ACTIVATION_LIMIT[0])
    arm.add_argument("--timeout", type=int, default=TIMEOUT[0])
    arm.add_argument("--settle", type=int, default=SETTLE[0])
    for name in ("activated", "abort", "status", "_watch"):
        sub.add_parser(name).add_argument("run")
    done = sub.add_parser("done")
    done.add_argument("run")
    done.add_argument("word", choices=["pass", "fail"])
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
        "activated": cmd_activated,
        "abort": cmd_signal,
        "done": cmd_signal,
        "status": cmd_status,
        "_watch": cmd_watch,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
