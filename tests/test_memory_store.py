"""The in-process session store (WO-006 req. 8 and the no-leakage requirement).

Covers isolation between two keys, idle TTL expiry and oldest-first eviction with
an injected clock, reset, updated_at stamping, copy semantics, and env settings.
"""

from datetime import UTC, datetime, timedelta

import pytest

from idx_agent.domain.models import PropertySearchFilters, UserSession
from idx_agent.memory import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_MINUTES,
    InMemorySessionStore,
    SessionStore,
    store_from_env,
)

# Invented hashed sender keys (lowercase hex, as sender_key returns).
KEY_A = "a" * 64
KEY_B = "b" * 64
KEY_C = "c" * 64
START = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=30)


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _session(key: str, city: str = "Pasadena", keys=(101, 102)) -> UserSession:
    return UserSession(
        sender_id=key,
        filters=PropertySearchFilters(city=city, max_price=1_200_000),
        last_result_keys=list(keys),
        step=1,
        updated_at=datetime(2000, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(clock) -> InMemorySessionStore:
    return InMemorySessionStore(TTL, 10, clock)


def test_store_satisfies_the_protocol(store):
    typed: SessionStore = store
    assert typed.get(KEY_A) is None


def test_get_missing_key_is_none(store):
    assert store.get(KEY_A) is None


def test_put_then_get_round_trips(store):
    store.put(_session(KEY_A))
    got = store.get(KEY_A)
    assert got is not None
    assert got.sender_id == KEY_A
    assert got.filters == PropertySearchFilters(city="Pasadena", max_price=1_200_000)
    assert got.last_result_keys == [101, 102]
    assert got.step == 1


def test_put_stamps_updated_at_from_the_clock(store, clock):
    store.put(_session(KEY_A))
    assert store.get(KEY_A).updated_at == START
    clock.advance(timedelta(minutes=5))
    store.put(_session(KEY_A))
    assert store.get(KEY_A).updated_at == START + timedelta(minutes=5)


def test_two_keys_are_isolated(store):
    store.put(_session(KEY_A, city="Pasadena", keys=(1, 2)))
    assert store.get(KEY_B) is None
    store.put(_session(KEY_B, city="Arcadia", keys=(3,)))
    a, b = store.get(KEY_A), store.get(KEY_B)
    assert (a.filters.city, a.last_result_keys) == ("Pasadena", [1, 2])
    assert (b.filters.city, b.last_result_keys) == ("Arcadia", [3])
    store.put(_session(KEY_A, city="Glendale", keys=(9,)))
    b = store.get(KEY_B)
    assert (b.filters.city, b.last_result_keys) == ("Arcadia", [3])


def test_lookup_uses_the_exact_key_only(store):
    store.put(_session(KEY_A))
    assert store.get(KEY_A[:8]) is None
    assert store.get(KEY_A.upper()) is None
    assert store.get(KEY_A + "a") is None


def test_session_is_live_just_before_the_ttl(store, clock):
    store.put(_session(KEY_A))
    clock.advance(TTL - timedelta(seconds=1))
    assert store.get(KEY_A) is not None


def test_session_expires_at_the_ttl_and_is_dropped(store, clock):
    store.put(_session(KEY_A))
    clock.advance(TTL)
    assert store.get(KEY_A) is None
    assert len(store) == 0


def test_a_new_put_restarts_the_idle_ttl(store, clock):
    store.put(_session(KEY_A))
    clock.advance(timedelta(minutes=20))
    store.put(_session(KEY_A))
    clock.advance(timedelta(minutes=20))
    assert store.get(KEY_A) is not None


def test_expiry_of_one_key_leaves_the_other(store, clock):
    store.put(_session(KEY_A))
    clock.advance(timedelta(minutes=20))
    store.put(_session(KEY_B))
    clock.advance(timedelta(minutes=15))
    assert store.get(KEY_A) is None
    assert store.get(KEY_B) is not None


def test_oldest_entry_is_evicted_past_the_cap(clock):
    store = InMemorySessionStore(TTL, 2, clock)
    for key in (KEY_A, KEY_B, KEY_C):
        store.put(_session(key))
        clock.advance(timedelta(seconds=1))
    assert len(store) == 2
    assert store.get(KEY_A) is None
    assert store.get(KEY_B) is not None
    assert store.get(KEY_C) is not None


def test_a_new_put_makes_a_key_the_newest(clock):
    store = InMemorySessionStore(TTL, 2, clock)
    store.put(_session(KEY_A))
    store.put(_session(KEY_B))
    store.put(_session(KEY_A))
    store.put(_session(KEY_C))
    assert store.get(KEY_B) is None
    assert store.get(KEY_A) is not None
    assert store.get(KEY_C) is not None


def test_reset_removes_only_that_key(store):
    store.put(_session(KEY_A))
    store.put(_session(KEY_B))
    store.reset(KEY_A)
    assert store.get(KEY_A) is None
    assert store.get(KEY_B) is not None


def test_reset_of_a_missing_key_is_not_an_error(store):
    store.reset(KEY_A)
    assert store.get(KEY_A) is None


def test_changing_a_returned_session_does_not_change_the_store(store):
    store.put(_session(KEY_A))
    got = store.get(KEY_A)
    got.step = 7
    got.last_result_keys.append(999)
    again = store.get(KEY_A)
    assert again.step == 1
    assert again.last_result_keys == [101, 102]


def test_changing_the_put_session_afterwards_does_not_change_the_store(store):
    session = _session(KEY_A)
    store.put(session)
    session.last_result_keys.append(999)
    assert store.get(KEY_A).last_result_keys == [101, 102]
    assert session.updated_at == datetime(2000, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("ttl", "cap"), [(timedelta(0), 10), (timedelta(minutes=-1), 10), (TTL, 0)]
)
def test_bad_settings_are_refused(clock, ttl, cap):
    with pytest.raises(ValueError):
        InMemorySessionStore(ttl, cap, clock)


def test_store_from_env_defaults(monkeypatch, clock):
    monkeypatch.delenv("IDX_SESSION_TTL_MINUTES", raising=False)
    monkeypatch.delenv("IDX_SESSION_MAX_ENTRIES", raising=False)
    store = store_from_env(clock)
    store.put(_session(KEY_A))
    clock.advance(timedelta(minutes=DEFAULT_TTL_MINUTES) - timedelta(seconds=1))
    assert store.get(KEY_A) is not None
    clock.advance(timedelta(seconds=1))
    assert store.get(KEY_A) is None
    assert (DEFAULT_TTL_MINUTES, DEFAULT_MAX_ENTRIES) == (30, 1000)


def test_store_from_env_reads_both_variables(monkeypatch, clock):
    monkeypatch.setenv("IDX_SESSION_TTL_MINUTES", "5")
    monkeypatch.setenv("IDX_SESSION_MAX_ENTRIES", "1")
    store = store_from_env(clock)
    store.put(_session(KEY_A))
    store.put(_session(KEY_B))
    assert store.get(KEY_A) is None
    clock.advance(timedelta(minutes=5))
    assert store.get(KEY_B) is None


def test_store_from_env_default_clock_is_utc(monkeypatch):
    monkeypatch.delenv("IDX_SESSION_TTL_MINUTES", raising=False)
    monkeypatch.delenv("IDX_SESSION_MAX_ENTRIES", raising=False)
    store = store_from_env()
    store.put(_session(KEY_A))
    assert store.get(KEY_A).updated_at.tzinfo is not None


@pytest.mark.parametrize("value", ["zero", "0", "-3", "1.5"])
@pytest.mark.parametrize("name", ["IDX_SESSION_TTL_MINUTES", "IDX_SESSION_MAX_ENTRIES"])
def test_store_from_env_refuses_bad_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        store_from_env()
