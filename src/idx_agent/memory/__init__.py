"""Per-sender conversation state.

Keyed by a hashed sender id so one conversation's context never leaks into
another's. Merge rules, identity hashing, and the in-process store live here.
"""

from idx_agent.memory.identity import SENDER_KEY_ENV, key_prefix, sender_key
from idx_agent.memory.merge import MergeMode, merge_filters, next_page
from idx_agent.memory.store import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_MINUTES,
    InMemorySessionStore,
    SessionStore,
    store_from_env,
)

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_MINUTES",
    "InMemorySessionStore",
    "MergeMode",
    "SENDER_KEY_ENV",
    "SessionStore",
    "key_prefix",
    "merge_filters",
    "next_page",
    "sender_key",
    "store_from_env",
]
