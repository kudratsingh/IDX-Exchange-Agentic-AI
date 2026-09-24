"""Integration tests for the db layer against the local MySQL (`@pytest.mark.db`).

Skipped unless MYSQL_HOST is set. Other MYSQL_* values missing from the environment
come from .env through `pool.dotenv_values`, the same path the MCP server takes; no
value is printed or logged. Run with: MYSQL_HOST=localhost pytest -q -m db
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymysql
import pytest
from evals import run as runner

from idx_agent.db import asof
from idx_agent.db.listings import (
    MAX_ROWS,
    count_active_listings,
    search_active_listings,
)
from idx_agent.db.market import fetch_market_aggregates
from idx_agent.db.pool import DbConfig, connect
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import (
    DEFAULT_SUBTYPE,
    EXCLUSION_RULES,
    MarketAggregates,
    build_market_stats,
    month_keys,
)
from idx_agent.domain.models import (
    Listing,
    MarketStatsRequest,
    PropertySearchFilters,
    StatsWindow,
)
from idx_agent.mcp_server import server as mcp
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST, check_column

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def conn() -> Iterator[Any]:
    """One reader connection for the module, closed afterwards.

    `DbConfig.from_env()` takes the environment first and fills the gaps from
    `pool.dotenv_values()`, so this test reads .env exactly as the server does.
    """
    connection = connect(DbConfig.from_env())
    try:
        yield connection
    finally:
        connection.close()


def _pasadena(**extra: Any) -> PropertySearchFilters:
    """The WO-004 example: 3+ beds in Pasadena at or under 1.5M."""
    return PropertySearchFilters(
        city="Pasadena", min_beds=3, max_price=1_500_000, **extra
    )


def test_pasadena_returns_one_to_five_listings_with_the_expected_shape(conn):
    outcome = search_active_listings(_pasadena(), conn)
    assert 1 <= len(outcome.listings) <= 5
    for item in outcome.listings:
        assert isinstance(item, Listing)
        assert item.city == "Pasadena"
        assert item.bedrooms is not None and item.bedrooms >= 3
        assert item.list_price <= 1_500_000
        assert item.status == "Active"
        keys = set(item.model_dump())
        assert not keys & (DENYLIST | AGENT_CONTACT)
    prices = [item.list_price for item in outcome.listings]
    assert prices == sorted(prices)


def test_page_two_differs_from_page_one(conn):
    first = search_active_listings(_pasadena(page=1), conn).listings
    second = search_active_listings(_pasadena(page=2), conn).listings
    assert first and second
    first_ids = {item.listing_id for item in first}
    assert first_ids.isdisjoint(item.listing_id for item in second)


def test_the_count_covers_every_page_of_the_same_search(conn):
    """WO-006: the COUNT uses the search's WHERE, so it is at least two pages here
    and matches a page of 50 when the total fits in one. Skipped rows count too:
    the COUNT sees them, the listings do not."""
    total = count_active_listings(_pasadena(), conn)
    assert total >= 6
    outcome = search_active_listings(_pasadena(limit=MAX_ROWS), conn)
    assert len(outcome.listings) + outcome.skipped_rows == min(total, MAX_ROWS)


def test_same_query_twice_returns_the_same_page(conn):
    one = search_active_listings(_pasadena(page=2), conn).listings
    two = search_active_listings(_pasadena(page=2), conn).listings
    assert [i.listing_id for i in one] == [i.listing_id for i in two]


def test_a_request_for_500_returns_50_with_a_warning(conn):
    filters = PropertySearchFilters.model_construct(city="Los Angeles", limit=500)
    outcome = search_active_listings(filters, conn)
    assert len(outcome.listings) + outcome.skipped_rows == MAX_ROWS
    assert any(str(MAX_ROWS) in warning for warning in outcome.warnings)


def _latest_modification_day(conn: Any) -> date:
    """The date of MAX(ModificationTimestamp), read with an allowlisted column."""
    column = check_column("rets_property", "ModificationTimestamp")
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT MAX({column}) AS latest FROM rets_property")
        latest = cursor.fetchone()["latest"]
    if isinstance(latest, datetime):
        return latest.date()
    return date.fromisoformat(str(latest)[:10])


def test_asof_dates_follow_the_data_not_a_fixed_day(conn):
    asof.clear_asof_cache()
    try:
        dates = asof.get_asof_dates(conn)
        assert dates.active == _latest_modification_day(conn)
        # Sold is bounded by active, so a typo year in close dates never wins.
        assert dates.sold <= dates.active
        assert asof.get_asof_dates(conn) is dates
    finally:
        asof.clear_asof_cache()


def test_the_session_refuses_writes(conn):
    # Inserts zero rows even if it were allowed; it must fail on grants or the
    # read-only session before anything runs.
    sql = (
        "INSERT INTO rets_property (L_City) "
        "SELECT L_City FROM rets_property WHERE 1 = 0"
    )
    with pytest.raises(pymysql.MySQLError), conn.cursor() as cursor:
        cursor.execute(sql)


# --- WO-008 market aggregates ---

# The real sold table holds about 98,500 rows and the fixture a few dozen; a count
# (never a row) tells them apart for the one test that needs real Pasadena sales.
_REAL_DATA_MIN_ROWS = 10_000
_BEST_OF = 3
_MAX_SECONDS = 2.0


def _one(conn: Any, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    """Run a one-row aggregate query and return its row."""
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def _six_months(conn: Any) -> tuple[AsOfDates, StatsWindow]:
    """The as-of dates (read, not cached) and the default six-month window."""
    dates = asof.read_asof_dates(conn)
    start, end = dates.window(6)
    return dates, StatsWindow(start=start, end=end, months=6)


def _middle_count(n: int) -> int:
    """How many middle values a sample of n has: 0, 1 (odd), or 2 (even)."""
    return 0 if n == 0 else 1 if n % 2 else 2


def _largest_city(conn: Any, window: StatsWindow) -> str:
    """The city with the most sales of any subtype in the window (kept in memory)."""
    city, close_d = (
        check_column("california_sold", c) for c in ("City", "close_date_d")
    )
    sql = (
        f"SELECT {city} AS city, COUNT(*) AS n FROM california_sold "
        f"WHERE {close_d} BETWEEN %s AND %s GROUP BY {city} "
        f"ORDER BY n DESC, {city} LIMIT %s"
    )
    return _one(conn, sql, (window.start, window.end, 1))["city"]


def _assert_consistent(agg: MarketAggregates, window: StatsWindow) -> None:
    """Middles fit each metric's sample; months cover the window and add up."""
    assert len(agg.price_middles) == _middle_count(agg.sample_count)
    assert len(agg.ratio_middles) == _middle_count(agg.sample_count)
    assert len(agg.dom_middles) == _middle_count(agg.dom_sample)
    assert len(agg.ppsf_middles) == _middle_count(agg.ppsf_sample)
    assert tuple(m.key for m in agg.months) == month_keys(window)
    assert sum(m.count for m in agg.months) == agg.sample_count
    for month in agg.months:
        assert len(month.price_middles) == _middle_count(month.count)
    assert tuple(rule for rule, _ in agg.exclusions) == EXCLUSION_RULES
    assert all(count >= 0 for _, count in agg.exclusions)
    counts = dict(agg.exclusions)
    assert agg.dom_sample + counts["dom_missing"] == agg.sample_count
    assert agg.ppsf_sample + counts["area_under_floor"] == agg.sample_count


def _sold_row_count(conn: Any) -> int:
    """How many rows the sold table holds (a count, never a row)."""
    return _one(conn, "SELECT COUNT(*) AS n FROM california_sold", ())["n"]


def test_pasadena_single_family_six_months_has_every_figure(conn):
    """Real data only: Pasadena single-family has enough sales for every median."""
    if _sold_row_count(conn) < _REAL_DATA_MIN_ROWS:
        pytest.skip("needs the real sold table; the fixture has few Pasadena sales")
    dates, window = _six_months(conn)
    request = MarketStatsRequest(city="Pasadena", property_subtype=DEFAULT_SUBTYPE)
    agg = fetch_market_aggregates(request, window, dates, conn)
    assert agg.sample_count >= 5
    for middles in (
        agg.price_middles,
        agg.dom_middles,
        agg.ratio_middles,
        agg.ppsf_middles,
    ):
        assert len(middles) in (1, 2) and all(value > 0 for value in middles)
    _assert_consistent(agg, window)


def test_market_sample_and_row_exclusions_add_up_to_the_window_rows(conn):
    """Every window row of the place and subtype is either a sale or excluded once."""
    dates, window = _six_months(conn)
    city = _largest_city(conn, window)
    agg = fetch_market_aggregates(MarketStatsRequest(city=city), window, dates, conn)
    _assert_consistent(agg, window)
    city_c, sub_c, close_d = (
        check_column("california_sold", c)
        for c in ("City", "PropertySubType", "close_date_d")
    )
    sql = (
        f"SELECT COUNT(*) AS n FROM california_sold WHERE {city_c} = %s "
        f"AND {sub_c} = %s AND {close_d} BETWEEN %s AND %s"
    )
    in_window = _one(conn, sql, (city, DEFAULT_SUBTYPE, window.start, window.end))
    counts = dict(agg.exclusions)
    dropped = sum(
        counts[rule]
        for rule in (
            "close_before_contract",
            "price_under_floor",
            "duplicate_listing_key",
        )
    )
    assert in_window["n"] == agg.sample_count + dropped


def test_the_largest_city_statement_set_runs_under_two_seconds(conn):
    """The WO-008 median-in-SQL rule: the whole set, best of three, under 2 s."""
    dates, window = _six_months(conn)
    request = MarketStatsRequest(city=_largest_city(conn, window))
    times = []
    for _ in range(_BEST_OF):
        started = time.perf_counter()
        fetch_market_aggregates(request, window, dates, conn)
        times.append(time.perf_counter() - started)
    assert min(times) < _MAX_SECONDS


_CASES_DIR = Path(__file__).resolve().parents[1] / "evals" / "cases"


def _market_stats_cases() -> list[runner.Case]:
    """Every stats_exact case in market_stats.yaml, through the runner's loader."""
    cases, _ = runner.load_cases(_CASES_DIR)
    return [
        c for c in cases if c.source == "market_stats.yaml" and c.check == "stats_exact"
    ]


@pytest.mark.parametrize("case", _market_stats_cases(), ids=lambda c: c.id)
def test_market_stats_cases_hold_on_the_fixture(conn, case: runner.Case):
    """Fixture only: validation, the tool's window fallback, the real SQL, and
    build_market_stats, judged by the runner's own stats_exact comparison."""
    if _sold_row_count(conn) >= _REAL_DATA_MIN_ROWS:
        pytest.skip("the stats_exact literals hold only for the synthetic fixture")
    request = MarketStatsRequest.from_input(case.input_filters or {})
    assert isinstance(request, MarketStatsRequest), case.id
    dates = asof.read_asof_dates(conn)
    earliest = asof.read_earliest_close(conn, dates.active)
    warnings: list[str] = []
    window, _ = mcp._market_window(request.months, dates, earliest, warnings)
    agg = fetch_market_aggregates(request, window, dates, conn)
    _assert_consistent(agg, window)
    stats = build_market_stats(agg, request, window, dates, warnings=warnings)
    envelope = SimpleNamespace(ok=True, data=stats, warnings=warnings, error=None)
    verdict, detail = runner._judge_stats(case.expect, envelope)
    assert verdict == runner.PASS, f"{case.id}: {detail}"
