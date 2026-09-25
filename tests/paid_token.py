"""Paid-gate helpers for tests. conftest points the reader at a temp consent dir for
every test; tokens here are written by the reader's own `grant` (production never
mints), and `run_as` sets the command line the paid check observes."""

from __future__ import annotations

from collections.abc import Sequence

from idx_agent.safety import consent


def _words(command: str | Sequence[str]) -> list[str]:
    return command.split() if isinstance(command, str) else [str(w) for w in command]


def run_as(command: str | Sequence[str]) -> list[str]:
    """Make the reader report `command` as this process's argv (conftest's autouse
    fixture puts the real `process_argv` back when the test ends)."""
    words = _words(command)
    consent.reader().process_argv = lambda: list(words)
    return words


def grant_paid(
    command: str | Sequence[str],
    max_calls: int,
    minutes: int = 15,
    now: float | None = None,
) -> None:
    """Mint a `paid` token for `command` with `max_calls` in the temp consent dir."""
    words = " ".join(_words(command))
    consent.reader().grant("paid", minutes, now=now, command=words, max_calls=max_calls)


def token_state() -> str:
    """The paid token's state as the reader reports it (valid, consumed, ...)."""
    return str(consent.reader().paid_token_status()["state"])
