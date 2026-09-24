"""The `search_listings` tool: validate, then search, over the MCP layer, no database.

The db layer is replaced with fakes (monkeypatch), so these are unit tests. Covers the
three outcomes (results, Clarification, error), provenance, and the log line.
All listings below are invented.
"""

import asyncio
import json
import pathlib
from datetime import date

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
    """The tool is listed, and its arguments are exactly the filter fields."""
    assert "search_listings" in mcp.tool_names()
    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "search_listings"
    )
    assert set(tool.input_schema["properties"]) == set(
        PropertySearchFilters.model_fields
    )


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
