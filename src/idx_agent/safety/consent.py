"""The one paid check in our code: one `paid` token, one run (paid gate v2, 2026-09-25).

`start_paid_run()` spends the token minted for this process's own command line and
sets its call budget; `spend_paid_call()` runs before every provider request. Token
rules live only in `scripts/guards/consent_token.py`, loaded by path. Never mints."""

from __future__ import annotations

import importlib.util
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

__all__ = [
    "MINT_MINUTES",
    "SERVER_ARGV",
    "PaidBudget",
    "PaidRunRefused",
    "abort_paid_run",
    "active_budget",
    "allow_lazy_server_run",
    "display_command",
    "invocation_argv",
    "mint_command",
    "reader",
    "reset_for_tests",
    "spend_paid_call",
    "start_paid_run",
]

# The tool server's command line as OpenClaw starts it (scripts/install.sh).
SERVER_ARGV = ("python", "-m", "idx_agent.mcp_server.server")
# The window a printed mint command asks for; the run must finish inside it.
MINT_MINUTES = 30
_READER_REL = Path("scripts") / "guards" / "consent_token.py"
_READER_NAMES = (
    "consume_paid",
    "command_matches",
    "consent_dir",
    "normalize_command",
    "process_argv",
    "project_root",
    "NoPaidToken",
    "PaidGrant",
)
# Characters a double-quoted shell word needs escaped (the backslash first).
_ESCAPE_IN_QUOTES = ("\\", '"', "$", "`")


class PaidRunRefused(RuntimeError):
    """No paid call is allowed. `reason` is a consume reason (missing, expired,
    malformed, command_mismatch, consumed, ...) or no_budget, over_budget, aborted,
    or reader_outdated. The message is fixed text plus the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"paid run refused: {reason}")
        self.reason = reason


@dataclass
class PaidBudget:
    """This process's paid run: the token's command, ceiling, run id, and expiry,
    the calls spent so far, and why it was aborted (None while it runs)."""

    command: str
    max_calls: int
    run_id: str
    expiry: float
    calls_made: int = 0
    aborted: str | None = None

    @property
    def remaining(self) -> int:
        """Calls left under the ceiling."""
        return max(0, self.max_calls - self.calls_made)


_lock = threading.RLock()
_active: PaidBudget | None = None
_lazy = False
_reader: ModuleType | None = None


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


def _reader_path() -> Path:
    """consent_token.py in the checkout holding this package (in a worktree, that
    worktree's copy, which only a `gates` token may change), else in the main
    checkout that owns the git common dir."""
    here = Path(__file__).resolve()
    own = here.parents[3] / _READER_REL
    if own.is_file():
        return own
    root = _git_root(here.parent)
    if root is not None and (root / _READER_REL).is_file():
        return root / _READER_REL
    raise PaidRunRefused("reader_outdated")


def _pin_consent_dir(module: ModuleType, path: Path) -> None:
    """Fix the reader's consent dir as the commit gate resolves it (ignore_env=True),
    under the checkout owning `path`: no env var or working directory can move it."""
    root = _git_root(path.parent) or path.resolve().parents[2]
    resolve = module.consent_dir

    def project_root(ignore_env: bool = False) -> Path:
        return root

    def consent_dir(ignore_env: bool = False) -> Path:
        return Path(resolve(ignore_env=True))

    module.project_root = project_root
    module.consent_dir = consent_dir


def _load_reader(path: Path) -> ModuleType:
    """Load the reader at `path` with its consent dir pinned; PaidRunRefused
    ("reader_outdated") when it cannot load or lacks the v2 names."""
    spec = importlib.util.spec_from_file_location("_idx_consent_token", path)
    if spec is None or spec.loader is None:
        raise PaidRunRefused("reader_outdated")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if any(not hasattr(module, name) for name in _READER_NAMES):
        raise PaidRunRefused("reader_outdated")
    _pin_consent_dir(module, path)
    return module


def reader() -> ModuleType:
    """The token reader, loaded once by path (an old reader never unlocks a run)."""
    global _reader
    with _lock:
        if _reader is None:
            _reader = _load_reader(_reader_path())
        return _reader


def invocation_argv() -> list[str]:
    """This process's command line as typed (sys.orig_argv), per the reader."""
    return [str(word) for word in reader().process_argv()]


def display_command(argv: Sequence[str]) -> str:
    """`argv` normalized as the token compares it (env words dropped, the python
    word shortened), joined by single spaces."""
    return " ".join(reader().normalize_command([str(a) for a in argv]))


def mint_command(
    argv: Sequence[str], max_calls: int | str, minutes: int = MINT_MINUTES
) -> str:
    """The line a human runs to allow exactly one run of `argv` with `max_calls`:
    `! scripts/guards/consent.sh paid 30 --command "<command>" --max-calls <N>`."""
    words = display_command(argv)
    for ch in _ESCAPE_IN_QUOTES:
        words = words.replace(ch, "\\" + ch)
    return (
        f'! scripts/guards/consent.sh paid {minutes} --command "{words}" '
        f"--max-calls {max_calls}"
    )


def start_paid_run() -> PaidBudget:
    """Spend the `paid` token minted for this process's own command line (never a
    caller's argv) and set the process's budget. PaidRunRefused carries the
    reader's reason (missing, expired, malformed, command_mismatch, consumed, ...)."""
    global _active
    module = reader()
    try:
        grant = module.consume_paid(invocation_argv())
    except module.NoPaidToken as exc:
        raise PaidRunRefused(str(getattr(exc, "reason", "missing"))) from None
    budget = PaidBudget(
        command=str(grant.command),
        max_calls=int(grant.max_calls),
        run_id=str(grant.run_id),
        expiry=float(grant.expiry),
    )
    with _lock:
        _active = budget
    return budget


def _finished(budget: PaidBudget, now: float) -> str | None:
    """Why `budget` allows no further call, or None."""
    if budget.aborted is not None:
        return "aborted"
    if now >= budget.expiry:
        return "expired"
    if budget.remaining < 1:
        return "over_budget"
    return None


def spend_paid_call(n: int = 1) -> None:
    """Count `n` requests against the active budget, right before sending. Refuses
    (and aborts the run): no_budget, over_budget, expired, aborted. In the tool
    server a missing or finished budget first spends a new server token, once."""
    if n < 1:
        raise ValueError("n must be at least 1")
    now = time.time()
    with _lock:
        budget = _active
        if _lazy and (budget is None or _finished(budget, now)):
            previous = None if budget is None else _finished(budget, now)
            try:
                budget = start_paid_run()
            except PaidRunRefused as exc:
                raise PaidRunRefused(previous or exc.reason) from None
        if budget is None:
            raise PaidRunRefused("no_budget")
        reason = _finished(budget, now)
        if reason is None and budget.calls_made + n > budget.max_calls:
            reason = "over_budget"
        if reason is not None:
            if budget.aborted is None:
                budget.aborted = reason
            raise PaidRunRefused(reason)
        budget.calls_made += n


def abort_paid_run(reason: str) -> None:
    """End the active run after a provider refusal or driver error: no further call
    is allowed under its token. No-op without an active run."""
    with _lock:
        if _active is not None and _active.aborted is None:
            _active.aborted = reason


def active_budget() -> PaidBudget | None:
    """The process's paid run, or None when none was started."""
    with _lock:
        return _active


def allow_lazy_server_run() -> bool:
    """Called by the tool server's main(): only when this process really is
    `python -m idx_agent.mcp_server.server` may its first paid call spend a token
    minted for that command. Returns whether lazy mode is on."""
    global _lazy
    try:
        words = reader().normalize_command(invocation_argv())
    except PaidRunRefused:
        return False
    with _lock:
        _lazy = list(words) == list(SERVER_ARGV)
        return _lazy


def reset_for_tests() -> None:
    """Forget the active budget and the lazy server mode. Tests only."""
    global _active, _lazy
    with _lock:
        _active = None
        _lazy = False
