"""The `get_market_stats` tool (WO-008) over the MCP layer, with no database.

The db layer is replaced with fakes (monkeypatch) that return invented aggregates
built from the domain dataclasses. Covers the four outcomes, the window fallback,
the log line and spans, and that the tool never touches the session store.
"""

import asyncio
import json
import pathlib
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from idx_agent.channels.format import format_market_reply
from idx_agent.db import listings as db_listings
from idx_agent.db import market as db_market
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import (
    EXCLUSION_RULES,
    MIN_SAMPLE,
    MarketAggregates,
    MonthAggregate,
)
from idx_agent.domain.models import (
    Clarification,
    Listing,
    MarketStats,
    MarketStatsRequest,
    SearchResult,
    StatsWindow,
)
from idx_agent.domain.results import AgentResult
from idx_agent.mcp_server import server as mcp
from idx_agent.memory import InMemorySessionStore
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

# Parses any get_market_stats payload back into the typed envelope.
Envelope = AgentResult[MarketStats | Clarification]
# Invented as-of dates matching the spike's shape: the 6-month window starts
# 2026-03-18, the day the invented earliest close falls on (so 6 needs no fallback).
ASOF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
EARLIEST = date(2026, 3, 18)
SIX_MONTHS = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
SRC = str(pathlib.Path(mcp.__file__).resolve().parents[2])
# The real fetch, kept before the fake_db fixture patches it (row-cap test).
REAL_FETCH = db_market.fetch_market_aggregates


def _exclusions(**counts):
    """One (rule, count) per EXCLUSION_RULES name; unnamed rules count 0."""
    return tuple((name, counts.get(name, 0)) for name in EXCLUSION_RULES)


def _aggregates(**overrides):
    """Seven invented single-family sales over the six-month window.

    Price middle 1,050,000; days middles 20 and 23 (21.5); ratio middle 1.0125
    (1.012 half-even); price per sqft middles 700.25 and 712.75 (706.5 -> 706).
    """
    fields = {
        "sample_count": 7,
        "price_middles": (Decimal("1050000"),),
        "dom_middles": (Decimal("20"), Decimal("23")),
        "dom_sample": 6,
        "ratio_middles": (Decimal("1.0125"),),
        "ppsf_middles": (Decimal("700.25"), Decimal("712.75")),
        "ppsf_sample": 6,
        "months": (
            MonthAggregate("2026-03", 1, (Decimal("900000"),)),
            MonthAggregate("2026-05", 3, (Decimal("1000000"),)),
            MonthAggregate("2026-07", 2, (Decimal("1100000"), Decimal("1200000"))),
            MonthAggregate("2026-09", 1, (Decimal("1300000"),)),
        ),
        "subtype_mix": (("Condominium", 4), (None, 1)),
        "exclusions": _exclusions(
            close_before_contract=1, duplicate_listing_key=1, dom_missing=1
        ),
    }
    fields.update(overrides)
    return MarketAggregates(**fields)


def _few(count, mix=(("Condominium", 2),)):
    """An invented under-minimum sample: `count` sales, no figures computed."""
    return _aggregates(
        sample_count=count,
        price_middles=(),
        dom_middles=(),
        dom_sample=0,
        ratio_middles=(),
        ppsf_middles=(),
        ppsf_sample=0,
        months=(),
        subtype_mix=mix,
        exclusions=_exclusions(price_under_floor=1),
    )


class FakeConn:
    """Stands in for a database connection; records whether it was closed."""

    closed = False

    def close(self):
        self.closed = True


def _listing(key):
    """One invented active listing for the search half of the memory test."""
    return Listing(
        listing_key=key,
        listing_id=f"TEST{key}",
        address=f"{key} Example Lane",
        city="Pasadena",
        postal_code="91100",
        list_price=1_000_000 + key,
        property_subtype="SingleFamilyResidence",
        photo_count=3,
    )


@pytest.fixture
def fake_db(monkeypatch):
    """Patch pool, as-of, earliest close, the market fetch, and the search.

    Returns a dict recording calls; set calls["aggregates"] to change the answer.
    """
    calls = {"connect": 0, "fetch": [], "conn": FakeConn(), "aggregates": _aggregates()}

    def connect(config=None):
        calls["connect"] += 1
        calls["conn"] = FakeConn()
        return calls["conn"]

    def fetch(request, window, as_of, conn):
        calls["fetch"].append((request, window, as_of, conn))
        return calls["aggregates"]

    def search(filters, conn):
        return db_listings.SearchOutcome(listings=[_listing(1), _listing(2)])

    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    monkeypatch.setattr(mcp.db_asof, "get_asof_dates", lambda conn: ASOF)
    monkeypatch.setattr(mcp.db_asof, "get_earliest_close", lambda conn: EARLIEST)
    monkeypatch.setattr(mcp.db_market, "fetch_market_aggregates", fetch)
    monkeypatch.setattr(mcp.db_listings, "search_active_listings", search)
    return calls


def _market(**kwargs):
    """Call the MCP entry point and parse the envelope."""
    return Envelope.model_validate(mcp.get_market_stats(**kwargs))


def _keys(value):
    """Return every dict key found anywhere inside a JSON-like value."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _log_lines(capsys):
    """The JSON log lines written to stderr since the last read."""
    err = capsys.readouterr().err
    return [json.loads(x) for x in err.strip().splitlines()], err


# --- registration and the stats outcome ---


def test_get_market_stats_is_registered_with_four_flat_arguments():
    """Listed next to search; exactly the request fields, and no sender id."""
    assert {"health", "search_listings", "get_market_stats"} <= set(mcp.tool_names())
    tool = next(
        t for t in asyncio.run(mcp.server.list_tools()) if t.name == "get_market_stats"
    )
    assert set(tool.input_schema["properties"]) == set(MarketStatsRequest.model_fields)
    assert "sender_id" not in tool.input_schema["properties"]
    assert "get_market_stats" in mcp.server.instructions


def test_stats_outcome_carries_figures_card_and_provenance(fake_db):
    """ok with low_sample False, every figure set, the card as message, and the
    validated request and the six-month window handed to the db layer."""
    envelope = _market(city="  monrovia ")
    assert envelope.ok is True and envelope.error is None
    stats = envelope.data
    assert isinstance(stats, MarketStats) and stats.low_sample is False
    assert stats.geography.city == "Monrovia"
    assert stats.property_subtype == "SingleFamilyResidence"
    assert stats.window == SIX_MONTHS and stats.as_of == ASOF.sold
    assert stats.sample_count == 7
    assert stats.median_close_price == 1_050_000
    assert stats.median_price_per_sqft == 706  # 706.5 rounds half-even, once
    assert stats.median_dom == 21.5 and stats.dom_band == "low"
    assert stats.sale_to_list_ratio == 1.012
    assert stats.sale_to_list_reading == "1% over asking"
    assert stats.market_lean == "seller"
    assert [row.month for row in stats.trend] == [
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    assert "close_before_contract: 1" in stats.exclusions_applied
    # Provenance: the sold table and both as-of dates; the connection was closed.
    assert envelope.provenance.tables == ["california_sold"]
    assert envelope.provenance.as_of.sold == ASOF.sold
    assert envelope.provenance.as_of.active == ASOF.active
    assert envelope.provenance.tool == "get_market_stats"
    ((request, window, as_of, conn),) = fake_db["fetch"]
    assert request == MarketStatsRequest(city="Monrovia")
    assert window == SIX_MONTHS and as_of == ASOF and conn.closed is True
    # The message is the formatter's card; exclusion warnings in plain words.
    assert envelope.message == format_market_reply(
        stats, (("Condominium", 4), (None, 1)), ASOF.sold, widen_months=6
    )
    assert envelope.message.startswith("*Market in Monrovia: Single Family Residence*")
    assert len(envelope.warnings) == 3
    assert any("before their contract date" in w for w in envelope.warnings)


def test_a_named_subtype_is_used_and_the_mix_line_is_left_out(fake_db):
    """property_subtype reaches the db layer as given; no default-mix line."""
    envelope = _market(city="Monrovia", property_subtype="Condominium", months=6)
    ((request, window, _, _),) = fake_db["fetch"]
    assert request.property_subtype == "Condominium" and window == SIX_MONTHS
    assert envelope.data.property_subtype == "Condominium"
    assert "Other types sold here" not in envelope.message


def test_the_mix_line_appears_for_the_default_subtype(fake_db):
    envelope = _market(postal_code="91016")
    assert envelope.data.geography.postal_code == "91016"
    assert envelope.message.startswith("*Market in ZIP 91016:")
    assert (
        "Other types sold here in the same window: Condominium 4, unknown type 1"
        in (envelope.message)
    )


def test_market_over_the_mcp_call_path(fake_db):
    """Call through the MCP server's own `call_tool`, as the runtime would."""
    args = {"city": "Monrovia", "months": 6}
    result = asyncio.run(mcp.server.call_tool("get_market_stats", args))
    content = result.structured_content or json.loads(result.content[0].text)
    envelope = Envelope.model_validate(content)
    assert envelope.ok and isinstance(envelope.data, MarketStats)


# --- not enough comps ---


@pytest.mark.parametrize("count", [0, 3, MIN_SAMPLE - 1])
def test_under_the_minimum_is_not_enough_comps(fake_db, count):
    """ok with the real count, low_sample, no figures, empty trend, exclusions kept."""
    fake_db["aggregates"] = _few(count)
    envelope = _market(city="Monrovia")
    stats = envelope.data
    assert envelope.ok is True and stats.low_sample is True
    assert stats.sample_count == count
    for name in (
        "median_close_price",
        "median_price_per_sqft",
        "median_dom",
        "dom_band",
        "sale_to_list_ratio",
        "sale_to_list_reading",
        "market_lean",
    ):
        assert getattr(stats, name) is None, name
    assert stats.trend == []
    assert "price_under_floor: 1" in stats.exclusions_applied
    assert envelope.message.startswith("*Not enough comps*")
    sales = "1 sale" if count == 1 else f"{count} sales"
    assert f"{sales} in the last 6 months" in envelope.message
    assert f"at least {MIN_SAMPLE}" in envelope.message
    assert envelope.provenance.tables == ["california_sold"]


def test_at_the_minimum_figures_are_filled(fake_db):
    fake_db["aggregates"] = _aggregates(
        sample_count=MIN_SAMPLE,
        dom_sample=MIN_SAMPLE,
        dom_middles=(Decimal("40"),),
        ppsf_sample=MIN_SAMPLE,
        ppsf_middles=(Decimal("650"),),
        months=(MonthAggregate("2026-05", MIN_SAMPLE, (Decimal("1000000"),)),),
    )
    envelope = _market(city="Monrovia")
    assert envelope.data.low_sample is False
    assert envelope.data.median_dom == 40 and envelope.data.dom_band == "average"


def test_a_short_window_suggests_six_months(fake_db):
    """3 months under the minimum: the step offered is the six-month window."""
    fake_db["aggregates"] = _few(2, mix=(("Condominium", 9),))
    envelope = _market(city="Monrovia", months=3)
    assert "ask for the last 6 months" in envelope.message
    assert "Condominium has" not in envelope.message


def test_at_six_months_a_subtype_with_enough_sales_is_suggested(fake_db):
    fake_db["aggregates"] = _few(2, mix=(("Townhouse", 2), ("Condominium", 9)))
    envelope = _market(city="Monrovia")
    assert "Condominium has 9 sales here in the same window" in envelope.message
    assert "last 6 months:" not in envelope.message


def test_with_no_runnable_step_it_says_so_and_names_no_other_city(fake_db):
    fake_db["aggregates"] = _few(0, mix=((None, 7), ("Townhouse", 2)))
    envelope = _market(city="Alhambra")
    assert "Neither a longer window nor another type" in envelope.message
    assert "Pasadena" not in envelope.message and "Monrovia" not in envelope.message


# --- Clarification ---


@pytest.mark.parametrize(
    ("args", "field", "reason"),
    [
        ({"city": "Not A Real Town"}, "city", "unknown_city"),
        ({}, "city", "missing_location"),
        ({"city": "Monrovia", "postal_code": "91016"}, "city", "invalid_value"),
        ({"city": "Monrovia", "months": 0}, "months", "below_minimum"),
        ({"city": "Monrovia", "months": 30}, "months", "above_maximum"),
        (
            {"city": "Monrovia", "property_subtype": "Castle"},
            "property_subtype",
            "unknown_subtype",
        ),
        ({"postal_code": "9101"}, "postal_code", "invalid_format"),
    ],
)
def test_a_bad_request_is_a_clarification_and_runs_no_query(
    fake_db, capsys, args, field, reason
):
    """ok with the Clarification and its question; no connection; no as-of dates."""
    envelope = _market(**args)
    assert envelope.ok is True and envelope.error is None
    assert isinstance(envelope.data, Clarification)
    assert (envelope.data.field, envelope.data.reason) == (field, reason)
    assert envelope.message == envelope.data.question
    assert fake_db["connect"] == 0 and fake_db["fetch"] == []
    assert envelope.provenance.tables == []
    assert envelope.provenance.as_of.sold is None
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "clarification" and line["clarification"] == reason


# --- errors ---


def test_database_not_configured_is_a_db_error_without_detail(monkeypatch, capsys):
    monkeypatch.setattr(mcp.db_pool, "database_configured", lambda: False)

    def connect(config=None):
        raise AssertionError("must not connect")

    monkeypatch.setattr(mcp.db_pool, "connect", connect)
    payload = mcp.get_market_stats(city="Monrovia")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.data is None
    assert envelope.error.category == "db"
    assert "not configured" in envelope.error.message
    assert "detail" not in _keys(payload)
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "error"


@pytest.mark.parametrize("stage", ["fetch", "earliest"])
def test_a_database_failure_is_a_db_error_and_the_connection_closes(
    fake_db, monkeypatch, capsys, stage
):
    """The driver text stays internal; the log records only the error type."""

    def broken(*args):
        raise RuntimeError("internal-only-text from the driver")

    target = "fetch_market_aggregates" if stage == "fetch" else "get_earliest_close"
    module = mcp.db_market if stage == "fetch" else mcp.db_asof
    monkeypatch.setattr(module, target, broken)
    payload = mcp.get_market_stats(city="Monrovia")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "db"
    assert envelope.error.trace_id == envelope.provenance.trace_id
    assert "detail" not in _keys(payload)
    assert "internal-only-text" not in json.dumps(payload)
    assert fake_db["conn"].closed is True
    ((line,), err) = _log_lines(capsys)
    assert line["outcome"] == "error" and line["error_type"] == "RuntimeError"
    assert "internal-only-text" not in err


class _OverCapCursor:
    """A cursor whose every statement returns one row more than the cap."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return [{"n": 1}] * (db_market.MAX_ROWS + 1)


class _OverCapConn(FakeConn):
    def cursor(self):
        return _OverCapCursor()


def test_a_statement_over_the_row_cap_is_its_own_internal_error(
    fake_db, monkeypatch, capsys
):
    """The real fetch over 51 rows: its own message, category internal, and the log
    line's error_type RowCapExceeded (not a database outage); the connection closes."""
    conn = _OverCapConn()
    monkeypatch.setattr(mcp.db_pool, "connect", lambda config=None: conn)
    monkeypatch.setattr(mcp.db_market, "fetch_market_aggregates", REAL_FETCH)
    payload = mcp.get_market_stats(city="Monrovia")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "internal"
    assert envelope.error.message == (
        "The market query returned more rows than allowed and was stopped."
    )
    assert "detail" not in _keys(payload)
    assert conn.closed is True
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "error" and line["error"] == "internal"
    assert line["error_type"] == "RowCapExceeded"


def test_a_bug_in_the_figures_is_an_internal_error(fake_db, monkeypatch, capsys):
    """Aggregates that do not add up raise in build_market_stats: category internal."""
    fake_db["aggregates"] = _aggregates(sample_count=9)  # months add up to 7
    payload = mcp.get_market_stats(city="Monrovia")
    envelope = Envelope.model_validate(payload)
    assert envelope.ok is False and envelope.error.category == "internal"
    assert "detail" not in _keys(payload)
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "error" and line["error"] == "internal"


# --- the window fallback ---


def test_a_window_before_the_data_falls_back_to_its_coverage(fake_db):
    """12 months asked, the data starts 2026-03-18: six months used, with a warning."""
    envelope = _market(city="Monrovia", months=12)
    ((_, window, _, _),) = fake_db["fetch"]
    assert window == SIX_MONTHS
    assert envelope.data.window == SIX_MONTHS
    note = envelope.warnings[0]
    assert "12 months was asked" in note and "2026-03-18" in note
    assert "6 months, 2026-03-18 to 2026-09-17" in note


def test_a_fallback_window_is_not_offered_again_when_under_the_minimum(fake_db):
    fake_db["aggregates"] = _few(2, mix=())
    envelope = _market(city="Monrovia", months=12)
    assert "longer window may" not in envelope.message


def test_the_default_window_needs_no_fallback(fake_db):
    envelope = _market(city="Monrovia")
    assert not any("was asked" in w for w in envelope.warnings)


# --- the log line and the payload ---


def test_one_log_line_with_outcome_count_exclusions_and_no_rows(fake_db, capsys):
    """Trace id, tool, validated request, outcome, months, sample count, exclusion
    counts, duration; no address, listing key, or sale row."""
    payload = mcp.get_market_stats(city="monrovia")
    ((line,), err) = _log_lines(capsys)
    assert line["event"] == "tool_call" and line["tool"] == "get_market_stats"
    assert line["trace_id"] == payload["provenance"]["trace_id"]
    assert line["filters"] == {"city": "Monrovia", "months": 6}
    assert line["outcome"] == "stats" and line["sample_count"] == 7
    assert line["months"] == 6 and "ms" in line
    assert line["exclusions"]["close_before_contract"] == 1
    assert set(line["exclusions"]) == set(EXCLUSION_RULES)
    # "duplicate_listing_key" is a rule name; a listing key field would be a JSON key.
    for text in ("ListingKey", '"listing_key"', "Example Lane", "UnparsedAddress"):
        assert text not in err


def test_the_not_enough_comps_log_line(fake_db, capsys):
    fake_db["aggregates"] = _few(3)
    mcp.get_market_stats(city="Monrovia")
    ((line,), _) = _log_lines(capsys)
    assert line["outcome"] == "not_enough_comps" and line["sample_count"] == 3


def test_the_payload_holds_no_agent_or_deny_listed_field(fake_db):
    payload = mcp.get_market_stats(city="Monrovia")
    text = json.dumps(payload)
    assert not _keys(payload) & (AGENT_CONTACT | DENYLIST)
    assert not [name for name in AGENT_CONTACT | DENYLIST if name in text]
    assert '"listing_key"' not in text and "ListingKey" not in text


# --- no session state (requirement 12) ---

# Names in the server module that reach the session store or idx_agent.memory.
_STATE_NAMES = {
    name
    for name, value in vars(mcp).items()
    if getattr(value, "__module__", "").startswith("idx_agent.memory")
} | {"_get_store", "_store", "_sender_lock", "_remember", "reset_store_for_tests"}


def _names_used(fn):
    """Global names a function's code (and its nested code) refers to."""
    names, stack = set(), [fn.__code__]
    while stack:
        code = stack.pop()
        names |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return names


def test_the_market_code_names_nothing_from_the_session_store():
    """Every market function in the server refers to no memory or store name."""
    assert {"sender_key", "_get_store", "merge_filters"} <= _STATE_NAMES
    for fn in (
        mcp.get_market_stats,
        mcp.market_result,
        mcp._market_window,
        mcp._market_error,
        mcp._months_text,
    ):
        assert not _names_used(fn) & _STATE_NAMES, fn.__name__


def test_the_market_modules_do_not_import_memory():
    """A fresh interpreter importing the market code path loads no idx_agent.memory."""
    code = (
        "import sys\n"
        "import idx_agent.domain.market, idx_agent.db.market\n"
        "import idx_agent.channels.format\n"
        "assert 'idx_agent.memory' not in sys.modules, 'memory imported'\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SRC,
        check=False,
    )
    assert done.returncode == 0, done.stderr


class _TrippedStore:
    """A session store whose every method (and any other attribute) raises."""

    def _boom(self, *args, **kwargs):
        raise AssertionError("the market tool used the session store")

    get = put = reset = _boom

    def __getattr__(self, name):
        raise AssertionError(f"the market tool read store attribute {name!r}")


def test_a_market_call_never_reaches_the_store(fake_db, monkeypatch):
    """Every store and identity entry point broken, and a store installed whose every
    method raises (so a direct `_store` access fails too): the call still works."""

    def boom(*args, **kwargs):
        raise AssertionError("the market tool touched session state")

    for name in (
        "_get_store",
        "sender_key",
        "key_prefix",
        "merge_filters",
        "next_page",
    ):
        monkeypatch.setattr(mcp, name, boom)
    mcp.reset_store_for_tests(_TrippedStore())
    try:
        envelope = _market(city="Monrovia")
    finally:
        mcp.reset_store_for_tests()
    assert envelope.ok is True and isinstance(envelope.data, MarketStats)


def test_a_market_question_between_searches_leaves_more_paging(fake_db, monkeypatch):
    """Search, then a market call, then "more": the stored search is unchanged by
    the market call, and "more" returns page 2 of the same search."""
    keys = {"sender-a": "a1" * 32}
    monkeypatch.setattr(mcp, "sender_key", lambda raw, secret=None: keys.get(raw))
    clock = lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC)  # noqa: E731
    store = mcp.reset_store_for_tests(
        InMemorySessionStore(timedelta(minutes=30), 10, clock)
    )
    try:
        search = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(city="Pasadena", sender_id="sender-a")
        )
        assert search.data.applied_filters.page == 1
        before = store.get(keys["sender-a"]).model_dump()
        market = _market(city="Pasadena")
        assert market.ok and isinstance(market.data, MarketStats)
        assert store.get(keys["sender-a"]).model_dump() == before
        more = AgentResult[SearchResult | Clarification].model_validate(
            mcp.search_listings(mode="more", sender_id="sender-a")
        )
        assert more.data.applied_filters.page == 2
        assert more.data.applied_filters.city == "Pasadena"
    finally:
        mcp.reset_store_for_tests()


# --- spans (WO-007 tracing) ---


def test_market_spans_and_root_attributes(fake_db, monkeypatch):
    """Stage spans under idx.tool_call; the root carries outcome, count, months."""
    memory_exporter = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    )
    from idx_agent.observability import tracing

    monkeypatch.setenv("IDX_OTLP_ENDPOINT", "")
    exporter = memory_exporter.InMemorySpanExporter()
    tracing.configure_for_tests(exporter)
    try:
        mcp.get_market_stats(city="Monrovia")
        spans = {s.name: s for s in exporter.get_finished_spans()}
    finally:
        tracing.configure_for_tests(None)
    root = spans["idx.tool_call"]
    for stage in ("idx.market.validate", "idx.market.query", "idx.market.format"):
        assert spans[stage].parent.span_id == root.context.span_id, stage
    attrs = dict(root.attributes)
    assert attrs["idx.tool"] == "get_market_stats"
    assert attrs["idx.outcome"] == "stats"
    assert attrs["idx.sample_count"] == 7 and attrs["idx.months"] == 6
    assert attrs["idx.filters.city"] == "Monrovia"
    assert not any("exclusions" in name for name in attrs)
