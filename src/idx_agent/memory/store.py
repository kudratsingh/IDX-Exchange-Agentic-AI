"""In-process, per-sender session store with an idle TTL and an entry cap (req. 8).

Holds `UserSession` records keyed by the hashed sender key only. No file, no
database, nothing survives a restart. The clock is injected so tests control time.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from idx_agent.db.pool import env_setting
from idx_agent.domain.models import UserSession

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_MINUTES",
    "InMemorySessionStore",
    "SessionStore",
    "store_from_env",
]

# Defaults when IDX_SESSION_TTL_MINUTES / IDX_SESSION_MAX_ENTRIES are unset.
DEFAULT_TTL_MINUTES = 30
DEFAULT_MAX_ENTRIES = 1000


class SessionStore(Protocol):
    """What the search tool needs from a store: get, put, and reset by sender key."""

    def get(self, key: str) -> UserSession | None:
        """Return the session for `key`, or None when absent or expired."""
        ...

    def put(self, session: UserSession) -> None:
        """Store `session` under its sender_id, stamping updated_at from the clock."""
        ...

    def reset(self, key: str) -> None:
        """Forget the session for `key`; a missing key is not an error."""
        ...


def _utc_now() -> datetime:
    """Return the current time in UTC (the default clock)."""
    return datetime.now(UTC)


class InMemorySessionStore:
    """A SessionStore in a dict: idle sessions expire; past the cap, oldest goes first.

    Lookups use the exact key only. Sessions are copied in and out, so a caller's
    later change to a session object never reaches the store without a put.
    """

    def __init__(
        self, ttl: timedelta, max_entries: int, clock: Callable[[], datetime]
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        # Ordered by last put, oldest first, so eviction pops from the front.
        self._sessions: OrderedDict[str, UserSession] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> UserSession | None:
        """Return a copy of the session for `key`; None if absent or idle past the TTL.

        An expired session is dropped on this read.
        """
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if self._clock() - session.updated_at >= self._ttl:
                del self._sessions[key]
                return None
            return session.model_copy(deep=True)

    def put(self, session: UserSession) -> None:
        """Store a copy of `session` stamped with the clock's time as updated_at.

        The key becomes the newest entry; entries past the cap go oldest first.
        """
        stored = session.model_copy(deep=True)
        with self._lock:
            stored.updated_at = self._clock()
            self._sessions[stored.sender_id] = stored
            self._sessions.move_to_end(stored.sender_id)
            while len(self._sessions) > self._max_entries:
                self._sessions.popitem(last=False)

    def reset(self, key: str) -> None:
        """Remove the session for `key` if there is one."""
        with self._lock:
            self._sessions.pop(key, None)

    def __len__(self) -> int:
        """Number of entries held, expired ones included until read or evicted."""
        return len(self._sessions)


def _positive_int(name: str, default: int) -> int:
    """Read a positive integer from environment variable `name`, else `default`.

    A set but invalid value raises ValueError naming the variable.
    """
    raw = (env_setting(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def store_from_env(
    clock: Callable[[], datetime] | None = None,
) -> InMemorySessionStore:
    """Build the store from IDX_SESSION_TTL_MINUTES and IDX_SESSION_MAX_ENTRIES.

    Defaults: 30 minutes idle and 1000 entries; the clock defaults to UTC now.
    """
    ttl = timedelta(
        minutes=_positive_int("IDX_SESSION_TTL_MINUTES", DEFAULT_TTL_MINUTES)
    )
    cap = _positive_int("IDX_SESSION_MAX_ENTRIES", DEFAULT_MAX_ENTRIES)
    return InMemorySessionStore(ttl, cap, clock or _utc_now)
