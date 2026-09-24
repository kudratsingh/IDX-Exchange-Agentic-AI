"""The `search_listings` tool: validate, then search, over the MCP layer, no database.

The db layer is replaced with fakes (monkeypatch), so these are unit tests. Covers the
three outcomes (results, Clarification, error), provenance, and the log line; then
the WO-006 memory modes, the reset outcome, and the over-cap question.
All listings and sender ids below are invented.
"""

import asyncio
import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import sys
import threading
from datetime import UTC, date, datetime, timedelta

import pytest

from idx_agent.db import listings as db_listings
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import (
    Clarification,
    Listing,
    PropertySearchFilters,
    SearchResult,
)
from idx_agent.domain.results import AgentResult
from idx_agent.domain.valid_values import SUBTYPES
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore

# Parses any search_listings payload back into the typed envelope.
Envelope = AgentResult[SearchResult | Clarification]
# Invented as-of dates for the fake database.
ASOF = AsOfDates(sold=date(2026, 6, 30), active=date(2026, 7, 2))
# Text that must never reach a log line.
REMARK = "Invented remark text that must stay out of every log line"


def _listing(key, price):
    """One invented Pasadena listing, with a remark to prove it is never logged."""
    return Listing(
        listing_key=key,
        listing_id=f"TEST{key}",
        address=f"{key} Example Lane",
        city="Pasadena",
        postal_code="91100",
        list_price=price,
        bedrooms=3,
        bathrooms=2.0,
        living_area=1600,
        property_subtype="SingleFamilyResidence",
        status="Active",
        days_on_market=12,
        photo_count=20,
        remarks=REMARK,
    )


class FakeConn:
    """Stands in for a database connection; records whether it was closed."""

    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_db(monkeypatch):
    """Patch pool, as-of, and search; return a dict recording every call."""
    calls = {"connect": 0, "search": [], "conn": FakeConn()}

    def connect(config=None):
        calls["connect"] += 1
        return calls["conn"]

    def search(filters, conn):
        calls["search"].append((filters, conn))
        return db_listings.SearchOutcome(
            listings=[_listing(1, 1_200_000), _listing(2, 1_450_000)],
            warnings=["limit clamped to 50"],
            skipped_rows=0,
        )

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    return calls


def _keys(value):
    """Return every dict key found anywhere inside a JSON-like value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_search_listings_is_registered_with_flat_filter_arguments():
    """The tool is listed, and its arguments are exactly the filter fields plus
    the three WO-006 control arguments (the SDK Context is not an argument)."""
    assert "search_listings" in mcp.tool_names()
    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "search_listings"
    )
    assert set(tool.input_schema["properties"]) == set(
        PropertySearchFilters.model_fields
    ) | {"sender_id", "mode", "clear"}


def test_a_valid_search_returns_listings_and_applied_filters(fake_db):
    """Ok envelope: SearchResult data, validated filters, provenance, db warnings."""
    payload = mcp.search_listings(city="  pasadena ", min_beds=3, max_price=1_500_000)
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is True and envelope.error is None
    assert isinstance(envelope.data, SearchResult)
    assert [x.listing_key for x in envelope.data.listings] == [1, 2]
    applied = envelope.data.applied_filters
    assert applied.city == "Pasadena"  # stored spelling, not the raw input
    assert applied.min_beds == 3 and applied.max_price == 1_500_000
    assert applied.limit == 5 and applied.page == 1
    assert envelope.provenance.tables == ["rets_property"]
    assert envelope.provenance.as_of.sold == ASOF.sold
    assert envelope.provenance.as_of.active == ASOF.active
    assert envelope.provenance.tool == "search_listings"
    assert envelope.warnings == ["limit clamped to 50"]
    # The db layer got the validated filters, and the connection was closed.
    ((filters, conn),) = fake_db["search"]
    assert filters == applied and conn.closed is True
    json.dumps(payload)  # serializable as-is


def test_search_over_the_mcp_call_path(fake_db):
    """Call through the MCP server's own `call_tool`, as the runtime would."""
    args = {"city": "Pasadena", "min_beds": 3}
    result = asyncio.run(mcp.server.call_tool("search_listings", args))
    content = result.structured_content or json.loads(result.content[0].text)
    envelope = Envelope.model_validate(content)
    assert envelope.ok and isinstance(envelope.data, SearchResult)


@pytest.mark.parametrize(
    ("args", "field", "reason"),
    [
        ({"city": "Not A Real Town"}, "city", "unknown_city"),
        ({"min_beds": 3}, "city", "missing_location"),
        (
            {"city": "Pasadena", "property_subtype": "Castle"},
            "property_subtype",
            "unknown_subtype",
        ),
        (
            {"city": "Pasadena", "min_price": 9, "max_price": 1},
            "min_price",
            "min_above_max",
        ),
    ],
)
def test_a_bad_filter_returns_a_clarification_and_runs_no_query(
    fake_db, args, field, reason
):
    """A Clarification is ok=True with the question as message; no db call at all."""
    envelope = Envelope.model_validate(mcp.search_listings(**args))
    assert envelope.ok is True and envelope.error is None
    assert isinstance(envelope.data, Clarification)
    assert envelope.data.field == field and envelope.data.reason == reason
    assert envelope.message == envelope.data.question
    assert fake_db["connect"] == 0 and fake_db["search"] == []
    assert envelope.provenance.tables == []


def test_database_not_configured_is_a_db_error_without_detail(monkeypatch):
    """No MYSQL_HOST: ok=False, a plain "db" error, and no connection attempt."""
    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: False)

    def connect(config=None):
        raise AssertionError("must not connect")

    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    payload = mcp.search_listings(city="Pasadena")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.data is None
    assert envelope.error.category == "db"
    assert "not configured" in envelope.error.message
    assert "detail" not in _keys(payload)


def test_a_database_failure_becomes_a_tool_error_without_detail(fake_db, monkeypatch):
    """The exception text stays internal; the connection is still closed."""

    def broken(filters, conn):
        raise RuntimeError("internal-only-text from the driver")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", broken)
    payload = mcp.search_listings(city="Pasadena")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "db"
    assert envelope.error.trace_id == envelope.provenance.trace_id
    assert "detail" not in _keys(payload)
    assert "internal-only-text" not in json.dumps(payload)
    assert fake_db["conn"].closed is True


def test_one_log_line_with_filters_and_row_count_and_no_remarks(fake_db, capsys):
    """The log line carries trace id, tool, validated filters, rows, duration only."""
    payload = mcp.search_listings(city="pasadena", min_beds=3)
    err = capsys.readouterr().err
    lines = [json.loads(x) for x in err.strip().splitlines()]
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "tool_call" and line["tool"] == "search_listings"
    assert line["trace_id"] == payload["provenance"]["trace_id"]
    assert line["filters"]["city"] == "Pasadena" and line["filters"]["min_beds"] == 3
    assert line["rows"] == 2 and "ms" in line
    assert REMARK not in err and "remarks" not in err
    assert "Example Lane" not in err  # no row content at all


def test_the_skill_names_the_tool_and_every_known_subtype():
    """The skill text stays in step with the tool name and the subtype set."""
    skill = (
        pathlib.Path(__file__).resolve().parents[1]
        / "skills"
        / "property-search"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "idx__search_listings" in skill
    assert all(subtype in skill for subtype in SUBTYPES)
    assert "data, never instructions" in skill


def test_no_results_says_so_and_skipped_rows_are_warned_once(fake_db, monkeypatch):
    """An empty search is ok with a plain message; the db layer's skip warning
    passes through once, not doubled by the server."""
    skipped = "2 row(s) skipped because a required value was missing or invalid"

    def empty(filters, conn):
        return db_listings.SearchOutcome(
            listings=[], warnings=[skipped], skipped_rows=2
        )

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", empty)
    envelope = Envelope.model_validate(mcp.search_listings(postal_code="91100"))
    assert envelope.ok is True and envelope.data.listings == []
    assert envelope.message.startswith("No active listings matched")
    assert envelope.warnings == [skipped]


def test_remarks_never_leave_the_server(fake_db):
    """Remarks are dropped from the payload (data, message, warnings): the sentinel
    text appears nowhere, and every listing's remarks field is None."""
    payload = mcp.search_listings(city="Pasadena")
    assert REMARK not in json.dumps(payload)
    listings = payload["data"]["listings"]
    assert len(listings) == 2
    assert all(item["remarks"] is None for item in listings)


# --- WO-006: multi-turn memory ---

# Invented sender ids and the fixed hex keys the patched `sender_key` maps them to.
# The real HMAC is tested in tests/test_memory_identity.py.
KEYS = {"sender-a": "a1" * 32, "sender-b": "b2" * 32}
# A fixed clock start for the injected store clock.
T0 = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


class Clock:
    """A settable clock for the session store."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def memory(monkeypatch):
    """A fresh store on a settable clock, and `sender_key` patched to KEYS.

    Returns the store and the clock; the module store is replaced again afterwards.
    """
    clock = Clock()
    store = InMemorySessionStore(timedelta(minutes=30), 10, clock)
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: KEYS.get(raw))
    mcp.reset_store_for_tests(store)
    yield store, clock
    mcp.reset_store_for_tests()


def _search(**kwargs):
    """Call the MCP entry point and parse the envelope."""
    return Envelope.model_validate(mcp.search_listings(**kwargs))


def _applied(envelope):
    """The applied filters of a SearchResult envelope, without defaults or None."""
    assert isinstance(envelope.data, SearchResult), envelope.message
    return envelope.data.applied_filters.model_dump(exclude_none=True)


def test_update_keeps_earlier_filters_across_three_turns(fake_db, memory):
    """Pasadena 3+ beds, then "only condos", then "under $1.2M": all carried."""
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    second = _search(
        property_subtype="Condominium", mode="update", sender_id="sender-a"
    )
    assert _applied(second) == {
        "city": "Pasadena",
        "min_beds": 3,
        "property_subtype": "Condominium",
        "page": 1,
        "limit": 5,
    }
    third = _search(max_price=1_200_000, mode="update", sender_id="sender-a")
    assert _applied(third)["max_price"] == 1_200_000
    assert _applied(third)["property_subtype"] == "Condominium"
    assert _applied(third)["city"] == "Pasadena"
    # The reply's filters line shows the merged filters, so the user sees them.
    assert "city Pasadena" in third.message and "Condominium" in third.message
    assert [f.max_price for f, _ in fake_db["search"]] == [None, None, 1_200_000]


def test_update_overwrites_a_field_and_clear_unsets_one(fake_db, memory):
    _search(city="Pasadena", min_beds=3, max_price=900_000, sender_id="sender-a")
    changed = _search(
        min_beds=4, clear=["max_price"], mode="update", sender_id="sender-a"
    )
    applied = _applied(changed)
    assert applied["min_beds"] == 4 and "max_price" not in applied
    assert applied["city"] == "Pasadena"


def test_a_new_city_replaces_the_old_zip(fake_db, memory):
    _search(postal_code="91101", sender_id="sender-a")
    moved = _search(city="Pasadena", mode="update", sender_id="sender-a")
    assert _applied(moved)["city"] == "Pasadena"
    assert "postal_code" not in _applied(moved)


def test_more_is_the_stored_search_one_page_on(fake_db, memory):
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    second = _search(mode="more", sender_id="sender-a")
    third = _search(mode="more", sender_id="sender-a")
    assert _applied(second)["page"] == 2 and _applied(third)["page"] == 3
    assert _applied(third)["min_beds"] == 3 and _applied(third)["city"] == "Pasadena"
    assert second.warnings == third.warnings == ["limit clamped to 50"]


def test_more_with_nothing_stored_asks_for_a_location(fake_db, memory):
    envelope = _search(mode="more", sender_id="sender-a")
    assert isinstance(envelope.data, Clarification)
    assert envelope.data.reason == "missing_location"
    assert fake_db["search"] == []


def test_update_with_nothing_stored_is_a_replace_with_a_warning(fake_db, memory):
    envelope = _search(city="Pasadena", mode="update", sender_id="sender-a")
    assert _applied(envelope)["city"] == "Pasadena"
    assert mcp.NO_PREVIOUS_WARNING in envelope.warnings


def test_reset_with_no_filters_is_the_fourth_outcome(fake_db, memory):
    """ok, no data, the cleared message; then a refinement with no city asks."""
    store, _ = memory
    _search(city="Pasadena", sender_id="sender-a")
    cleared = _search(mode="reset", sender_id="sender-a")
    assert cleared.ok is True and cleared.data is None and cleared.error is None
    assert cleared.message == mcp.CLEARED_MESSAGE
    assert store.get(KEYS["sender-a"]) is None
    after = _search(property_subtype="Condominium", mode="update", sender_id="sender-a")
    assert isinstance(after.data, Clarification)
    assert after.data.reason == "missing_location"
    assert mcp.NO_PREVIOUS_WARNING in after.warnings
    assert len(fake_db["search"]) == 1  # only the first search reached the db


def test_reset_with_filters_searches_only_those(fake_db, memory):
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    fresh = _search(postal_code="91101", mode="reset", sender_id="sender-a")
    assert _applied(fresh) == {"postal_code": "91101", "page": 1, "limit": 5}


def test_two_senders_never_see_each_other(fake_db, memory):
    """Sender b's refinement finds no earlier search; sender a's state is intact."""
    store, _ = memory
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    other = _search(property_subtype="Condominium", mode="update", sender_id="sender-b")
    assert isinstance(other.data, Clarification)
    assert "Pasadena" not in json.dumps(other.model_dump(mode="json"))
    assert store.get(KEYS["sender-b"]) is None
    mine = _search(mode="more", sender_id="sender-a")
    assert _applied(mine)["city"] == "Pasadena" and _applied(mine)["page"] == 2


def test_state_is_written_only_after_a_search_that_ran(fake_db, memory, monkeypatch):
    """A Clarification and a db error both leave the stored state as it was."""
    store, _ = memory
    _search(city="Pasadena", max_price=1_000_000, sender_id="sender-a")
    before = store.get(KEYS["sender-a"])
    conflict = _search(min_price=2_000_000, mode="update", sender_id="sender-a")
    assert isinstance(conflict.data, Clarification)
    assert conflict.data.reason == "min_above_max"
    bad_clear = _search(clear=["colour"], mode="update", sender_id="sender-a")
    assert bad_clear.data.reason == "unsupported_filter"

    def broken(filters, conn):
        raise RuntimeError("driver down")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", broken)
    failed = _search(mode="more", sender_id="sender-a")
    assert failed.ok is False and failed.error.category == "db"
    after = store.get(KEYS["sender-a"])
    assert after.filters == before.filters and after.step == before.step == 1


def test_the_store_holds_filters_and_listing_keys_only(fake_db, memory):
    store, _ = memory
    _search(city="Pasadena", sender_id="sender-a")
    _search(mode="more", sender_id="sender-a")
    session = store.get(KEYS["sender-a"])
    assert session.sender_id == KEYS["sender-a"]
    assert session.filters.page == 2 and session.last_result_keys == [1, 2]
    assert session.step == 2
    assert REMARK not in json.dumps(session.model_dump(mode="json"))


def test_an_idle_session_expires_after_the_ttl(fake_db, memory):
    _, clock = memory
    _search(city="Pasadena", sender_id="sender-a")
    clock.now = T0 + timedelta(minutes=31)
    envelope = _search(mode="more", sender_id="sender-a")
    assert isinstance(envelope.data, Clarification)


def test_no_key_means_stateless_with_a_warning(fake_db, memory, monkeypatch):
    """No configured key (sender_key gives None): the search runs, nothing is kept."""
    store, _ = memory
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: None)
    first = _search(city="Pasadena", sender_id="sender-a")
    assert first.ok and mcp.NO_SESSION_WARNING in first.warnings
    assert len(store) == 0
    more = _search(mode="more", sender_id="sender-a")
    assert isinstance(more.data, Clarification)
    assert mcp.NO_SESSION_WARNING in more.warnings


def test_a_mode_without_a_sender_warns_and_keeps_nothing(fake_db, memory):
    store, _ = memory
    envelope = _search(city="Pasadena", mode="update")
    assert _applied(envelope)["city"] == "Pasadena"
    assert mcp.NO_SESSION_WARNING in envelope.warnings
    assert len(store) == 0


def test_no_sender_and_replace_behaves_as_in_wo004(fake_db, memory):
    store, _ = memory
    envelope = _search(city="Pasadena")
    assert envelope.warnings == ["limit clamped to 50"]
    assert len(store) == 0


def test_the_log_line_has_mode_and_key_prefix_never_the_sender(fake_db, memory, capsys):
    _search(city="Pasadena", sender_id="sender-a")
    _search(mode="more", sender_id="sender-a")
    err = capsys.readouterr().err
    lines = [json.loads(x) for x in err.strip().splitlines()]
    assert [x["mode"] for x in lines] == ["replace", "more"]
    assert all(x["key_prefix"] == KEYS["sender-a"][:8] for x in lines)
    assert "sender-a" not in err and KEYS["sender-a"] not in err


def test_over_the_cap_the_reply_ends_with_a_narrowing_question(fake_db, monkeypatch):
    """A full page and a count of 51: total_matches and the question, last line."""

    def full_page(filters, conn):
        rows = [_listing(k, 1_000_000 + k) for k in range(1, filters.limit + 1)]
        return db_listings.SearchOutcome(listings=rows)

    counted = []

    def count(filters, conn):
        counted.append(filters)
        return 51

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", full_page)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", count)
    envelope = _search(city="Pasadena")
    assert envelope.data.total_matches == 51
    assert envelope.data.narrowing_question == mcp.NARROWING_QUESTION
    assert envelope.message.splitlines()[-1] == mcp.NARROWING_QUESTION
    assert len(counted) == 1 and counted[0] == envelope.data.applied_filters
    # Later pages of the same search do not repeat the question.
    second = _search(city="Pasadena", page=2)
    assert second.data.total_matches == 51
    assert second.data.narrowing_question is None
    assert second.message.splitlines()[-1] != mcp.NARROWING_QUESTION


def test_at_or_under_the_cap_there_is_no_question(fake_db, monkeypatch):
    """A full page with a count of exactly 50: the count runs once, total_matches is
    50, and no question. A short page gives its total without a COUNT."""

    def full_page(filters, conn):
        rows = [_listing(k, 1_000_000 + k) for k in range(1, filters.limit + 1)]
        return db_listings.SearchOutcome(listings=rows)

    counted = []

    def count(filters, conn):
        counted.append(filters)
        return 50

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", full_page)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", count)
    at_cap = _search(city="Pasadena")
    assert len(counted) == 1
    assert at_cap.data.total_matches == 50
    assert at_cap.data.narrowing_question is None
    assert mcp.NARROWING_QUESTION not in at_cap.message
    # A short page (the default fake: 2 rows) needs no COUNT at all.
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", _two_rows)
    short = _search(city="Pasadena")
    assert len(counted) == 1
    assert short.data.total_matches == 2 and short.data.narrowing_question is None


def _two_rows(filters, conn):
    """A short page of two invented rows, whatever the filters."""
    return db_listings.SearchOutcome(
        listings=[_listing(1, 1_200_000), _listing(2, 1_450_000)]
    )


def test_a_failed_count_still_shows_the_page(fake_db, monkeypatch, capsys):
    def full_page(filters, conn):
        rows = [_listing(k, 1_000_000 + k) for k in range(1, filters.limit + 1)]
        return db_listings.SearchOutcome(listings=rows)

    def count(filters, conn):
        raise RuntimeError("count failed")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", full_page)
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", count)
    envelope = _search(city="Pasadena")
    assert envelope.ok and envelope.data.total_matches is None
    assert envelope.data.narrowing_question is None
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["count_error"] == "RuntimeError"


def test_every_card_shows_the_photo_count(fake_db, memory):
    envelope = _search(city="Pasadena", sender_id="sender-a")
    assert envelope.message.count("20 photos") == len(envelope.data.listings) == 2


def test_modes_over_the_mcp_call_path(fake_db, memory):
    """The runtime's path: arguments as JSON, `clear` as a list, mode as a string."""

    def call(args):
        result = asyncio.run(mcp.server.call_tool("search_listings", args))
        content = result.structured_content or json.loads(result.content[0].text)
        return Envelope.model_validate(content)

    call({"city": "Pasadena", "max_price": 900_000, "sender_id": "sender-a"})
    refined = call(
        {
            "mode": "update",
            "clear": ["max_price"],
            "min_beds": 2,
            "sender_id": "sender-a",
        }
    )
    assert _applied(refined) == {
        "city": "Pasadena",
        "min_beds": 2,
        "page": 1,
        "limit": 5,
    }


def _pager(total):
    """A fake search over `total` invented rows, one page per the filters."""
    rows = [_listing(k, 1_000_000 + k) for k in range(1, total + 1)]

    def search(filters, conn):
        start = (filters.page - 1) * filters.limit
        return db_listings.SearchOutcome(listings=rows[start : start + filters.limit])

    return search


def test_more_past_the_last_page_says_so_and_keeps_the_state(
    fake_db, memory, monkeypatch
):
    """7 rows: page 1, page 2 (2 rows), then "more" twice is the last-page answer
    (ok, data None, the fixed text) and the stored page stays at 2."""
    store, _ = memory
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", _pager(7))
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", lambda f, c: 7)
    _search(city="Pasadena", sender_id="sender-a")
    second = _search(mode="more", sender_id="sender-a")
    assert _applied(second)["page"] == 2 and second.data.total_matches == 7
    before = store.get(KEYS["sender-a"])
    for _ in range(2):
        last = _search(mode="more", sender_id="sender-a")
        assert last.ok is True and last.data is None and last.error is None
        assert last.message == mcp.LAST_PAGE_MESSAGE
        assert last.provenance.tables == ["rets_property"]
    after = store.get(KEYS["sender-a"])
    assert after.filters == before.filters and after.filters.page == 2
    assert after.step == before.step and after.last_result_keys == [6, 7]


def test_more_past_the_last_page_with_a_failed_count(fake_db, memory, monkeypatch):
    """An empty page past page 1 is the last page even when the count fails."""
    store, _ = memory

    def broken_count(filters, conn):
        raise RuntimeError("count failed")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", _pager(2))
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", broken_count)
    _search(city="Pasadena", sender_id="sender-a")
    last = _search(mode="more", sender_id="sender-a")
    assert last.data is None and last.message == mcp.LAST_PAGE_MESSAGE
    assert store.get(KEYS["sender-a"]).filters.page == 1


def test_an_empty_page_past_page_one_is_never_stored(fake_db, memory, monkeypatch):
    """A named page past the end shows no rows; the stored search stays as it was."""
    store, _ = memory
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", _pager(2))
    monkeypatch.setattr(mcp.db_listings, "count_active_listings", lambda f, c: 2)
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    before = store.get(KEYS["sender-a"])
    beyond = _search(city="Pasadena", page=4, sender_id="sender-a")
    assert beyond.data.listings == [] and beyond.data.total_matches == 2
    after = store.get(KEYS["sender-a"])
    assert after.filters == before.filters and after.step == before.step


def test_reset_with_filters_keeps_the_old_state_until_the_search_runs(
    fake_db, memory, monkeypatch
):
    """A reset whose filters ask back, or whose search fails, leaves the earlier
    search stored; one that runs replaces it with a fresh state (step 1)."""
    store, _ = memory
    _search(city="Pasadena", min_beds=3, sender_id="sender-a")
    before = store.get(KEYS["sender-a"])
    asked = _search(city="Not A Real Town", mode="reset", sender_id="sender-a")
    assert isinstance(asked.data, Clarification)
    assert asked.data.reason == "unknown_city"
    assert store.get(KEYS["sender-a"]).filters == before.filters

    def broken(filters, conn):
        raise RuntimeError("driver down")

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", broken)
    failed = _search(postal_code="91101", mode="reset", sender_id="sender-a")
    assert failed.ok is False and failed.error.category == "db"
    assert store.get(KEYS["sender-a"]).filters == before.filters
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", _two_rows)
    fresh = _search(postal_code="91101", mode="reset", sender_id="sender-a")
    session = store.get(KEYS["sender-a"])
    assert session.filters == fresh.data.applied_filters and session.step == 1


def test_the_store_is_built_on_first_use_not_at_import(fake_db, monkeypatch):
    """A bad IDX_SESSION_* value breaks neither the import nor health nor a
    stateless search; a call that needs the store gets an internal error."""
    env = {
        **os.environ,
        "IDX_SESSION_TTL_MINUTES": "soon",
        "PYTHONPATH": str(pathlib.Path(mcp.__file__).resolve().parents[2]),
    }
    code = "import idx_agent.mcp_server.server as s; print(s._store is None)"
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0 and done.stdout.strip() == "True"
    monkeypatch.setattr(mcp, "_store", None)
    monkeypatch.setenv("IDX_SESSION_TTL_MINUTES", "soon")
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: KEYS.get(raw))
    assert mcp.health()["ok"] is True
    assert _search(city="Pasadena").ok is True
    stateful = _search(city="Pasadena", sender_id="sender-a")
    assert stateful.ok is False and stateful.error.category == "internal"
    assert mcp._store is None


def test_the_real_hmac_through_the_entry_point(fake_db, monkeypatch, capsys):
    """With a test key set, a fictional-range id reaches neither the log nor the
    envelope; the log's key_prefix is the start of the HMAC computed here."""
    secret = hashlib.sha256(b"invented mcp test secret").hexdigest()
    monkeypatch.setenv("IDX_SENDER_KEY", secret)
    store = InMemorySessionStore(timedelta(minutes=30), 10, Clock())
    monkeypatch.setattr(mcp, "_store", store)
    # Country code 1, the fictional 555-010x range, then four digits; never a literal.
    digits = "".join(["1", "555", "010", "7", "3", "4", "2"])
    payload = mcp.search_listings(city="Pasadena", sender_id="+" + digits)
    err = capsys.readouterr().err
    expected = hmac.new(
        secret.encode("utf-8"), ("+" + digits).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    line = json.loads(err.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert line["key_prefix"] == expected[:8]
    assert store.get(expected) is not None
    text = err + json.dumps(payload)
    assert digits not in text and digits[1:] not in text and expected not in text


def test_a_reset_waits_for_an_in_flight_search_of_the_same_sender(
    fake_db, memory, monkeypatch
):
    """A "more" is held inside its search; a reset for the same sender waits for it
    and wins, while another sender's call is not blocked. The lock is then freed."""
    store, _ = memory
    _search(city="Pasadena", sender_id="sender-a")
    started, release = threading.Event(), threading.Event()

    def slow(filters, conn):
        started.set()
        assert release.wait(5)
        return _two_rows(filters, conn)

    monkeypatch.setattr(mcp.db_listings, "search_active_listings", slow)
    results = {}

    def run(name, **kwargs):
        results[name] = _search(sender_id="sender-a", **kwargs)

    more = threading.Thread(target=run, args=("more",), kwargs={"mode": "more"})
    more.start()
    assert started.wait(5)
    reset = threading.Thread(target=run, args=("reset",), kwargs={"mode": "reset"})
    reset.start()
    reset.join(0.2)
    assert reset.is_alive()  # held by sender-a's lock
    other = _search(mode="reset", sender_id="sender-b")  # other keys run at once
    assert other.message == mcp.CLEARED_MESSAGE
    release.set()
    more.join(5)
    reset.join(5)
    assert _applied(results["more"])["page"] == 2
    assert results["reset"].message == mcp.CLEARED_MESSAGE
    assert store.get(KEYS["sender-a"]) is None
    assert mcp._sender_locks == {}


def test_the_stateless_path_takes_no_lock(fake_db, monkeypatch):
    """Without a sender key no per-sender lock is taken at all."""

    def no_lock(key):
        raise AssertionError("a stateless call must not lock")

    monkeypatch.setattr(mcp, "_sender_lock", no_lock)
    assert _search(city="Pasadena").ok is True
