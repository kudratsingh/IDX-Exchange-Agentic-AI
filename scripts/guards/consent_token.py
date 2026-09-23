"""Human consent tokens for guarded actions. Standard library only.

A token is a file at ``<consent dir>/<kind>`` holding the unix time at which it
expires. Only a human creates one, with ``scripts/guards/consent.sh``; the Bash guard
refuses to let the agent run that script or touch the directory. Kinds:

- ``delete``: deleting files, discarding work, dropping or truncating data
- ``paid``: anything that calls a paid model or API
- ``gates``: editing the gates, the guards, the hooks, CI, or ``.gitignore``

A token is valid while its expiry is in the future. Every grant, use, block, and
revoke is appended to ``<consent dir>/audit.log`` so the trail outlives the token.

The consent dir is ``<project root>/.local/consent`` (gitignored). The project root
is ``$CLAUDE_PROJECT_DIR``, else the checkout that owns the git common dir (so every
worktree shares one consent dir), else two levels above this file.
``$IDX_CONSENT_DIR`` overrides the dir outright; the tests use that.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import subprocess
import sys
import time

KINDS = ("delete", "paid", "gates")
DEFAULT_MINUTES = 15
MAX_MINUTES = 240


def project_root() -> pathlib.Path:
    for var in ("CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
        value = os.environ.get(var)
        if value:
            return pathlib.Path(value)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        return pathlib.Path(out).resolve().parent
    except (OSError, subprocess.SubprocessError):
        return pathlib.Path(__file__).resolve().parents[2]


def consent_dir() -> pathlib.Path:
    override = os.environ.get("IDX_CONSENT_DIR")
    if override:
        return pathlib.Path(override)
    return project_root() / ".local" / "consent"


def token_path(kind: str) -> pathlib.Path:
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}; choose one of {KINDS}")
    return consent_dir() / kind


def expiry(kind: str) -> float | None:
    """Unix time at which the token expires, or None when there is no usable token."""
    try:
        text = token_path(kind).read_text(encoding="utf-8")
        return float(text.strip().splitlines()[0])
    except (OSError, IndexError, ValueError):
        return None


def is_valid(kind: str, now: float | None = None) -> bool:
    exp = expiry(kind)
    current = time.time() if now is None else now
    return exp is not None and exp > current


def remaining_minutes(kind: str, now: float | None = None) -> float:
    exp = expiry(kind)
    current = time.time() if now is None else now
    return 0.0 if exp is None else max(0.0, (exp - current) / 60)


def log(event: str, kind: str, detail: str = "") -> None:
    """Best-effort append to the audit log; never raises."""
    try:
        directory = consent_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        line = f"{stamp}\t{event}\t{kind}\t{detail[:200]}\n"
        with (directory / "audit.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def grant(kind: str, minutes: int = DEFAULT_MINUTES, now: float | None = None) -> float:
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    current = time.time() if now is None else now
    exp = current + minutes * 60
    path = token_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{exp:.0f}\n", encoding="utf-8")
    log("grant", kind, f"{minutes} min")
    return exp


def revoke(kind: str) -> bool:
    try:
        token_path(kind).unlink()
    except FileNotFoundError:
        return False
    log("revoke", kind)
    return True


def _clock(exp: float) -> str:
    return dt.datetime.fromtimestamp(exp).strftime("%H:%M:%S")


def main(argv: list[str]) -> int:
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
            minutes = int(argv[3]) if len(argv) > 3 else DEFAULT_MINUTES
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
