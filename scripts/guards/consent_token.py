"""Human consent tokens for guarded actions. Standard library only.

A token is the file `<consent dir>/<kind>` holding its unix expiry time. Only a human
creates one, via consent.sh; guard.py blocks tool calls that run it or touch the dir.
Grants, uses, blocks and refusals go to `<consent dir>/audit.log`, secrets redacted.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import subprocess
import sys
import time

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
    """Unix time at which the token expires, or None when there is no usable token."""
    try:
        text = token_path(kind, ignore_env).read_text(encoding="utf-8")
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


def grant(kind: str, minutes: int = DEFAULT_MINUTES, now: float | None = None) -> float:
    """Write a token for `kind` expiring after `minutes` (clamped); log the grant.

    Returns the expiry as unix time.
    """
    minutes = clamp_minutes(minutes)
    current = time.time() if now is None else now
    exp = current + minutes * 60
    path = token_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{exp:.0f}\n", encoding="utf-8")
    log("grant", kind, f"{minutes} min")
    return exp


def revoke(kind: str) -> bool:
    """Delete the token for `kind` and log it; return False if there was none."""
    try:
        token_path(kind).unlink()
    except FileNotFoundError:
        return False
    log("revoke", kind)
    return True


def _clock(exp: float) -> str:
    """Format a unix time as local HH:MM:SS for CLI output."""
    return dt.datetime.fromtimestamp(exp).strftime("%H:%M:%S")


def main(argv: list[str]) -> int:
    """CLI behind consent.sh: grant <kind> [minutes] | revoke <kind> | status.

    Returns the exit code: 0 on success, 2 on a usage error.
    """
    usage = (
        "usage: consent_token.py grant <kind> [minutes] | revoke <kind> | status\n"
        f"kinds: {', '.join(KINDS)}"
    )
    if len(argv) < 2:
        print(usage, file=sys.stderr)
        return 2
    command = argv[1]
    if command == "status":
        for kind in KINDS:
            if is_valid(kind):
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
            minutes = clamp_minutes(int(argv[3]) if len(argv) > 3 else DEFAULT_MINUTES)
        except ValueError:
            print(usage, file=sys.stderr)
            return 2
        exp = grant(kind, minutes)
        print(f"consent '{kind}' granted until {_clock(exp)} ({minutes} min)")
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
