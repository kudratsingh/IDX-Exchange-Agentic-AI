"""Read-only check for a human `paid` consent token before a paid call (WO-010).

Mirrors the reader in scripts/guards/consent_token.py (same file, same validity rule)
so the package does not import from scripts/. It never writes, mints, or removes a
token: only a human grants one, with `scripts/guards/consent.sh paid`.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

__all__ = ["MAX_MINUTES", "consent_dir", "paid_consent_active", "token_expiry"]

# Same limit as consent_token.MAX_MINUTES: a token expiring further ahead is invalid.
MAX_MINUTES = 240
_SLACK_S = 60
_PAID = "paid"


def _git_root(start: Path) -> Path | None:
    """The checkout owning the git common dir of `start` (shared by worktrees)."""
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
    common = Path(out)
    if not common.is_absolute():
        common = start / common
    return common.resolve().parent


def consent_dir(environ: Mapping[str, str] | None = None) -> Path:
    """`<main checkout>/.local/consent`, resolved in consent_token.py's order.

    $IDX_CONSENT_DIR (tests), then $CLAUDE_PROJECT_DIR / $IDX_PROJECT_ROOT, then
    the git root of the working directory, then of this file.
    """
    env = os.environ if environ is None else environ
    override = env.get("IDX_CONSENT_DIR")
    if override:
        return Path(override)
    for var in ("CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
        value = env.get(var)
        if value:
            root = _git_root(Path(value)) or Path(value)
            return root / ".local" / "consent"
    here = Path(__file__).resolve().parent
    root = (
        _git_root(Path.cwd()) or _git_root(here) or Path(__file__).resolve().parents[3]
    )
    return root / ".local" / "consent"


def token_expiry(environ: Mapping[str, str] | None = None) -> float | None:
    """Unix expiry on the first line of the `paid` token file, or None if unusable."""
    try:
        text = (consent_dir(environ) / _PAID).read_text(encoding="utf-8")
        return float(text.strip().splitlines()[0])
    except (OSError, IndexError, ValueError):
        return None


def paid_consent_active(
    now: float | None = None, environ: Mapping[str, str] | None = None
) -> bool:
    """True when a `paid` token exists and now < expiry <= now + 240 min (+60 s).

    The same rule as consent_token.is_valid: a far-future hand-written expiry fails.
    """
    exp = token_expiry(environ)
    current = time.time() if now is None else now
    return exp is not None and current < exp <= current + MAX_MINUTES * 60 + _SLACK_S
