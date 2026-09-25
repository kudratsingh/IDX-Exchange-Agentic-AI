"""Human consent tokens for guarded actions. Standard library only.

A token is the file `<consent dir>/<kind>`. `delete` and `gates` tokens are one line,
the unix expiry: a time window. A `paid` token (format v2, ADR-0002 amendment
2026-09-25) starts with the line `paid-token-v2`, so a pre-v2 reader's float() fails and
it sees no token, then `key=value` lines: the expiry, one command line and a call
ceiling. The hook admits that command once (`admit_paid`) and the paid program spends
the token the moment the run starts (`consume_paid`); it never covers a second run.

Only a human creates a token, via consent.sh; guard.py blocks tool calls that run it or
touch the dir. Grants, uses, blocks and refusals go to `<consent dir>/audit.log`,
secrets redacted.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import pathlib
import re
import secrets
import subprocess
import sys
import time
from typing import NamedTuple

try:  # POSIX only; without it consumption still works, just without the lock.
    import fcntl
except ImportError:  # pragma: no cover - not on the platforms we run
    fcntl = None  # type: ignore[assignment]

# delete: deleting files, discarding work, dropping or truncating data.
# paid: anything that calls a paid model or API.
# gates: editing the gates, the guards, the hooks, CI, or .gitignore.
KINDS = ("delete", "paid", "gates")
DEFAULT_MINUTES = 15
MAX_MINUTES = 240  # longest grant; a token expiring further ahead is invalid
# Secret-looking values; _redact keeps the prefix and masks the value.
SECRET_RE = re.compile(
    r"(_API_KEY=|_TOKEN=|PASSWORD=|sk-|ghp_|gho_|github_pat_)[^\s'\"]+"
)
# Line 1 of a paid token. Pre-v2 readers parse line 1 as the expiry and fail on it.
PAID_MAGIC = "paid-token-v2"
# The `key=value` lines a paid token may hold, in the order they are written.
PAID_KEYS = (
    "expiry",
    "command",
    "max_calls",
    "granted",
    "admitted",
    "run_id",
    "consumed",
    "pid",
)
# Why a paid run was refused; NoPaidToken.reason is always one of these.
PAID_REASONS = (
    "missing",
    "expired",
    "malformed",
    "command_mismatch",
    "admitted",
    "consumed",
)
# The interpreter word, matched on the lowercased basename: python or pythonw, with or
# without a version 3 (3, 3.14); never python2. On macOS a venv python re-executes into
# the framework binary `.../Python.app/Contents/MacOS/Python`, which sys.orig_argv
# carries (found live, 2026-09-25).
_PYTHON_RE = re.compile(r"pythonw?(3(\.\d+)*)?")
_ENV_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)


def _git_root(start: pathlib.Path) -> pathlib.Path | None:
    """Return the checkout that owns the git common dir for `start`, or None.

    Every worktree of a repo maps to the same main checkout, so all share one
    consent dir. None when git fails or `start` is not in a repo.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    common = pathlib.Path(out)
    if not common.is_absolute():
        common = start / common
    return common.resolve().parent


def project_root(ignore_env: bool = False) -> pathlib.Path:
    """Return the main checkout's path, used as the parent of `.local/consent`.

    Order: $CLAUDE_PROJECT_DIR, then $IDX_PROJECT_ROOT (skipped when ignore_env),
    then the git root of the current dir, then of this file, then this file's repo.
    """
    if not ignore_env:
        for var in ("CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
            value = os.environ.get(var)
            if value:
                return _git_root(pathlib.Path(value)) or pathlib.Path(value)
    return (
        _git_root(pathlib.Path.cwd())
        or _git_root(pathlib.Path(__file__).resolve().parent)
        or pathlib.Path(__file__).resolve().parents[2]
    )


def consent_dir(ignore_env: bool = False) -> pathlib.Path:
    """Return `<project root>/.local/consent` (gitignored).

    $IDX_CONSENT_DIR overrides it for tests. The commit gate passes ignore_env=True,
    so an env prefix on `git commit` cannot point it at a fake token.
    """
    override = None if ignore_env else os.environ.get("IDX_CONSENT_DIR")
    if override:
        return pathlib.Path(override)
    return project_root(ignore_env) / ".local" / "consent"


def token_path(kind: str, ignore_env: bool = False) -> pathlib.Path:
    """Return the token file path for `kind`; raise ValueError for an unknown kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}; choose one of {KINDS}")
    return consent_dir(ignore_env) / kind


def expiry(kind: str, ignore_env: bool = False) -> float | None:
    """Unix time at which the token expires, or None when there is no usable token.

    For `paid` only the v2 form counts; an old one-line paid token has no expiry.
    """
    try:
        text = token_path(kind, ignore_env).read_text(encoding="utf-8")
        if kind == "paid":
            return _parse_token(text)[0]
        return float(text.strip().splitlines()[0])
    except (OSError, IndexError, ValueError):
        return None


# Decision steps, in execution order:
# 1. Resolve the consent dir under the checkout owning the git common dir
#    (env vars ignored when ignore_env=True, as the commit gate does).
# 2. Read the first line of `<dir>/<kind>` as a float; missing or bad -> invalid.
# 3. Valid only if now < expiry <= now + MAX_MINUTES (+60 s slack); a far-future
#    hand-written expiry is rejected.
# 4. The caller allows the action or fails, and logs "use" or "block".
def is_valid(kind: str, now: float | None = None, ignore_env: bool = False) -> bool:
    """Return True when a usable, unexpired token for `kind` exists at time `now`."""
    exp = expiry(kind, ignore_env)
    current = time.time() if now is None else now
    return exp is not None and current < exp <= current + MAX_MINUTES * 60 + 60


def remaining_minutes(kind: str, now: float | None = None) -> float:
    """Return minutes left on a valid token for `kind`, or 0.0 when none is valid."""
    if not is_valid(kind, now):
        return 0.0
    exp = expiry(kind) or 0.0
    current = time.time() if now is None else now
    return max(0.0, (exp - current) / 60)


def _redact(text: str) -> str:
    """Mask secret values, flatten whitespace to one line, and cap at 200 chars."""
    text = SECRET_RE.sub(r"\1***", text)
    return re.sub(r"[\r\n\t]+", " ", text)[:200]


def log(event: str, kind: str, detail: str = "", ignore_env: bool = False) -> None:
    """Append one tab-separated line (UTC time, event, kind, redacted detail).

    Writes to `<consent dir>/audit.log`. Best effort: OS errors are swallowed.
    """
    try:
        directory = consent_dir(ignore_env)
        directory.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)  # noqa: UP017 - runs on any python3
        stamp = now.isoformat(timespec="seconds")
        line = f"{stamp}\t{event}\t{kind}\t{_redact(detail)}\n"
        with (directory / "audit.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def clamp_minutes(minutes: int) -> int:
    """Return minutes limited to the range 1..MAX_MINUTES."""
    return max(1, min(int(minutes), MAX_MINUTES))


def grant(
    kind: str,
    minutes: int = DEFAULT_MINUTES,
    now: float | None = None,
    command: str | None = None,
    max_calls: int | None = None,
) -> float:
    """Write a token for `kind` expiring after `minutes` (clamped); log the grant.

    A `paid` token needs `command` (the argv words of the one run it covers) and
    `max_calls` (a positive call ceiling); other kinds take neither. Raises ValueError
    otherwise. Returns the expiry as unix time.
    """
    minutes = clamp_minutes(minutes)
    current = time.time() if now is None else now
    exp = current + minutes * 60
    path = token_path(kind)
    if kind != "paid":
        if command is not None or max_calls is not None:
            raise ValueError(f"a {kind!r} token takes no command or call ceiling")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{exp:.0f}\n", encoding="utf-8")
        log("grant", kind, f"{minutes} min")
        return exp
    words = " ".join((command or "").split())
    if not words:
        raise ValueError("a paid token needs --command with the run's argv words")
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1:
        raise ValueError("a paid token needs --max-calls with a positive integer")
    fields = {
        "command": words,
        "max_calls": str(max_calls),
        "granted": f"{current:.0f}",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _PaidLock(path):  # never replace a token mid-admit or mid-consume
        _write_token(path, exp, fields)
    log("grant", kind, f"{minutes} min; max_calls={max_calls}; command={words}")
    return exp


def revoke(kind: str) -> bool:
    """Delete the token for `kind` and log it; return False if there was none."""
    try:
        token_path(kind).unlink()
    except FileNotFoundError:
        return False
    log("revoke", kind)
    return True


# ----- paid tokens, format v2 -------------------------------------------------------
class NoPaidToken(Exception):
    """No paid token covers this run; `reason` is one of PAID_REASONS."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PaidGrant(NamedTuple):
    """What a consumed paid token allows: one run of `command`, `max_calls` calls."""

    command: str
    max_calls: int
    run_id: str
    expiry: float


def normalize_command(words: str | list[str] | tuple[str, ...]) -> list[str]:
    """Return the argv words in the form `command_matches` compares.

    Drops a leading `env` and leading `NAME=value` words, collapses whitespace, keeps
    only the basename of the first word, and maps any spelling of the interpreter
    (`python3`, `python3.x`, `pythonw`, the macOS framework `Python`, by any path) to
    `python`.
    """
    if isinstance(words, str):
        words = [words]
    flat = " ".join(str(word) for word in words).split()
    while flat and (flat[0] == "env" or _ENV_WORD_RE.fullmatch(flat[0])):
        flat = flat[1:]
    if flat:
        head = flat[0].rsplit("/", 1)[-1]
        flat[0] = "python" if _PYTHON_RE.fullmatch(head.lower()) else head
    return flat


def command_matches(
    token_command: str, argv: str | list[str] | tuple[str, ...]
) -> bool:
    """True when `argv` is exactly the token's command, after normalizing both sides."""
    want = normalize_command(token_command)
    return bool(want) and want == normalize_command(argv)


def process_argv() -> list[str]:
    """This process's command line as typed: `sys.orig_argv` (Python 3.10+).

    For `python -m evals.run --suite local`, `sys.argv[0]` is the module's file path
    and the interpreter words are gone; `sys.orig_argv` keeps them.
    """
    return [str(word) for word in (getattr(sys, "orig_argv", None) or sys.argv)]


def _parse_token(text: str) -> tuple[float, dict[str, str]]:
    """Expiry and the other `key=value` fields of a v2 paid token; ValueError otherwise.

    Line 1 must be PAID_MAGIC and an `expiry=` line must hold a finite unix time.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != PAID_MAGIC:
        raise ValueError("not a v2 paid token")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in PAID_KEYS or key in fields:
            raise ValueError(f"bad token line {line[:40]!r}")
        fields[key] = value.strip()
    exp = float(fields.pop("expiry", "nan"))
    if not math.isfinite(exp):
        raise ValueError("expiry is missing or not a finite number")
    return exp, fields


def _write_token(path: pathlib.Path, exp: float, fields: dict[str, str]) -> None:
    """Write a v2 paid token atomically: a temp file in the same dir, then a rename."""
    body = {**fields, "expiry": f"{exp:.0f}"}
    lines = [PAID_MAGIC] + [f"{k}={body[k]}" for k in PAID_KEYS if k in body]
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number >= 1 else None


def _paid_check(
    argv: list[str] | None, now: float | None = None
) -> tuple[str | None, float | None, dict[str, str]]:
    """(refusal reason or None, expiry, fields) for the paid token.

    With `argv` None the command is not compared (status output). Never raises.
    """
    try:
        text = token_path("paid").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing", None, {}
    except (OSError, ValueError):
        return "malformed", None, {}
    try:
        exp, fields = _parse_token(text)
    except (ValueError, IndexError):
        return "malformed", None, {}
    if not fields.get("command") or _positive_int(fields.get("max_calls")) is None:
        return "malformed", exp, fields  # an old one-line token never unlocks paid
    current = time.time() if now is None else now
    if exp <= current:
        return "expired", exp, fields
    if exp > current + MAX_MINUTES * 60 + 60:
        return "malformed", exp, fields  # a hand-written far-future expiry
    if argv is not None and not command_matches(fields["command"], argv):
        return "command_mismatch", exp, fields
    if "consumed" in fields:
        return "consumed", exp, fields
    return None, exp, fields


def paid_reason(
    argv: list[str] | tuple[str, ...], now: float | None = None
) -> str | None:
    """Why the hook could not admit `argv` (one of PAID_REASONS), or None. Read-only."""
    try:
        reason, _, fields = _paid_check([str(a) for a in argv], now)
    except Exception:  # noqa: BLE001 - the hook must never crash on odd input
        return "malformed"
    if reason is None and "admitted" in fields:
        return "admitted"
    return reason


def paid_allows(argv: list[str] | tuple[str, ...], now: float | None = None) -> bool:
    """True when `admit_paid(argv)` would succeed now: an unexpired, un-admitted,
    unconsumed paid token whose command matches `argv`. Read-only."""
    return paid_reason(argv, now) is None


class _PaidLock:
    """An exclusive flock on `<consent dir>/paid.lock`: two runs cannot both consume."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path.with_name("paid.lock")
        self.handle = None

    def __enter__(self) -> _PaidLock:
        try:
            self.handle = self.path.open("a", encoding="utf-8")
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            self.handle = None  # no dir means no token; the check says "missing"
        return self

    def __exit__(self, *exc: object) -> None:
        if self.handle is not None:
            self.handle.close()  # closing releases the flock


def admit_paid(argv: list[str] | tuple[str, ...], now: float | None = None) -> str:
    """The hook lets `argv` through once; return the run_id it writes into the token.

    Needs an unexpired, un-admitted, unconsumed token naming `argv`; writes `admitted`
    and `run_id` atomically under the paid lock. Raises NoPaidToken(reason) otherwise.
    """
    words = [str(a) for a in argv]
    detail = " ".join(words)
    path = token_path("paid")
    with _PaidLock(path):
        reason, exp, fields = _paid_check(words, now)
        if reason is None and "admitted" in fields:
            reason = "admitted"
        if reason is not None or exp is None:
            log("block", "paid", f"{reason}: {detail}")
            raise NoPaidToken(reason or "malformed")
        current = time.time() if now is None else now
        run_id = secrets.token_hex(8)
        fields.update(admitted=f"{current:.0f}", run_id=run_id)
        try:
            _write_token(path, exp, fields)
        except OSError:
            log("block", "paid", f"malformed (cannot mark it admitted): {detail}")
            raise NoPaidToken("malformed") from None
    log("admit", "paid", f"run_id={run_id}; {detail}")
    return run_id


def consume_paid(
    argv: list[str] | tuple[str, ...] | None = None, now: float | None = None
) -> PaidGrant:
    """Spend the paid token for this run; raise NoPaidToken(reason) when none covers it.

    `argv` defaults to `process_argv()`. The token must be unexpired, name this exact
    command, and be unspent; admitted by the hook or not (a human's own terminal has no
    hook). It gains `consumed` and `pid`, keeps the admitted run_id, and refuses later.
    """
    words = process_argv() if argv is None else [str(a) for a in argv]
    detail = " ".join(words)
    path = token_path("paid")
    with _PaidLock(path):
        reason, exp, fields = _paid_check(words, now)
        if reason is not None or exp is None:
            log("block", "paid", f"{reason}: {detail}")
            raise NoPaidToken(reason or "malformed")
        current = time.time() if now is None else now
        run_id = fields.get("run_id") or secrets.token_hex(8)
        fields.update(consumed=f"{current:.0f}", pid=str(os.getpid()), run_id=run_id)
        try:
            _write_token(path, exp, fields)
        except OSError:
            log("block", "paid", f"malformed (cannot mark the token spent): {detail}")
            raise NoPaidToken("malformed") from None
    max_calls = _positive_int(fields.get("max_calls")) or 0
    log("consume", "paid", f"run_id={run_id}; max_calls={max_calls}; {detail}")
    return PaidGrant(fields["command"], max_calls, run_id, exp)


def paid_token_status(now: float | None = None) -> dict[str, object]:
    """The paid token as a dict for status output; never raises.

    Keys: state (valid | admitted | consumed | expired | malformed | missing), command,
    max_calls, expiry, remaining_minutes, granted, admitted, consumed, pid, run_id.
    """
    try:
        reason, exp, fields = _paid_check(None, now)
    except Exception:  # noqa: BLE001
        reason, exp, fields = "malformed", None, {}
    current = time.time() if now is None else now

    def _number(key: str) -> float | None:
        try:
            return float(fields[key])
        except (KeyError, ValueError):
            return None

    remaining = max(0.0, (exp - current) / 60) if reason is None and exp else 0.0
    if reason is None and "admitted" in fields:
        reason = "admitted"
    return {
        "state": reason or "valid",
        "command": fields.get("command"),
        "max_calls": _positive_int(fields.get("max_calls")),
        "expiry": exp,
        "remaining_minutes": remaining,
        "granted": _number("granted"),
        "admitted": _number("admitted"),
        "consumed": _number("consumed"),
        "pid": _positive_int(fields.get("pid")),
        "run_id": fields.get("run_id"),
    }


def _paid_status_line(now: float | None = None) -> str:
    """One line for `status`: the command, the ceiling, and whether it is spent."""
    info = paid_token_status(now)
    state = info["state"]
    what = f"`{info['command']}`, at most {info['max_calls']} calls"
    if state == "valid":
        mins = float(info["remaining_minutes"] or 0.0)
        return f"paid    valid for {mins:.1f} more minutes, unspent: {what}"
    if state == "admitted":
        mins = float(info["remaining_minutes"] or 0.0)
        when = _clock(float(info["admitted"])) if info["admitted"] else "?"
        return (
            f"paid    admitted at {when} as run {info['run_id']}, not yet started, "
            f"{mins:.1f} more minutes: {what}"
        )
    if state == "consumed":
        when = _clock(float(info["consumed"])) if info["consumed"] else "?"
        return (
            f"paid    spent at {when} by run {info['run_id']} (pid {info['pid']}): "
            f"{what}; a new run needs a new token"
        )
    if state == "expired":
        return f"paid    expired: {what}"
    if state == "malformed":
        return (
            "paid    unusable (malformed or old format); mint a new one with --command"
        )
    return "paid    none"


def _clock(exp: float) -> str:
    """Format a unix time as local HH:MM:SS for CLI output ("?" when out of range)."""
    try:
        return dt.datetime.fromtimestamp(exp).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "?"


def _grant_args(args: list[str]) -> tuple[int, str | None, int | None]:
    """Parse `[minutes] [--command WORDS] [--max-calls N]`; ValueError on bad input."""
    minutes: int | None = None
    command: str | None = None
    max_calls: int | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        name, eq, inline = arg.partition("=")
        if name in ("--command", "--max-calls"):
            if eq:
                value = inline
            elif i + 1 < len(args):
                i += 1
                value = args[i]
            else:
                raise ValueError(f"{name} needs a value")
            if name == "--command":
                command = value
            else:
                max_calls = int(value)
        elif minutes is None and not arg.startswith("-"):
            minutes = int(arg)
        else:
            raise ValueError(f"unexpected argument {arg!r}")
        i += 1
    return (
        clamp_minutes(DEFAULT_MINUTES if minutes is None else minutes),
        command,
        max_calls,
    )


def main(argv: list[str]) -> int:
    """CLI behind consent.sh: grant <kind> [minutes] [paid flags] | revoke | status.

    Returns the exit code: 0 on success, 2 on a usage error.
    """
    usage = (
        "usage: consent_token.py grant delete|gates [minutes]\n"
        '       consent_token.py grant paid [minutes] --command "<argv words>" '
        "--max-calls <N>\n"
        "       consent_token.py revoke <kind> | status\n"
        f"kinds: {', '.join(KINDS)}"
    )
    if len(argv) < 2:
        print(usage, file=sys.stderr)
        return 2
    command = argv[1]
    if command == "status":
        for kind in KINDS:
            if kind == "paid":
                print(_paid_status_line())
            elif is_valid(kind):
                print(f"{kind:7} valid for {remaining_minutes(kind):.1f} more minutes")
            else:
                print(f"{kind:7} none")
        return 0
    if command in ("grant", "revoke") and len(argv) >= 3 and argv[2] in KINDS:
        kind = argv[2]
        if command == "revoke":
            print(f"consent '{kind}' " + ("revoked" if revoke(kind) else "was not set"))
            return 0
        try:
            minutes, run_command, max_calls = _grant_args(argv[3:])
            exp = grant(kind, minutes, command=run_command, max_calls=max_calls)
        except ValueError as exc:
            print(f"consent_token.py: {exc}\n{usage}", file=sys.stderr)
            return 2
        if kind == "paid":
            words = " ".join((run_command or "").split())
            print(
                f"consent 'paid' granted until {_clock(exp)} ({minutes} min) for "
                f"`{words}`, at most {max_calls} calls, one invocation"
            )
        else:
            print(f"consent '{kind}' granted until {_clock(exp)} ({minutes} min)")
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
