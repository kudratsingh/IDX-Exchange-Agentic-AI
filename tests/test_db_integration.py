"""Integration tests for the db layer against the local MySQL (`@pytest.mark.db`).

Skipped unless MYSQL_HOST is set. Other MYSQL_* values missing from the environment
come from .env through `pool.dotenv_values`, the same path the MCP server takes; no
value is printed or logged. Run with: MYSQL_HOST=localhost pytest -q -m db
"""

from __future__ import annotations

import importlib.util
import time
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pymysql
import pytest
from evals import run as runner

from idx_agent.db import asof
from idx_agent.db import comps as db_comps
from idx_agent.db.comps import fetch_comps
from idx_agent.db.listings import (
    MAX_ROWS,
    count_active_listings,
    fetch_candidates,
    search_active_listings,
)
from idx_agent.db.market import fetch_market_aggregates
from idx_agent.db.pool import DbConfig, connect
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.comps import (
    CompSubject,
    comps_window,
    price_check,
    subject_from_listing,
)
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


# --- WO-010 candidate fetch ---

# Fixture listings (tests/fixtures/make_synthetic.py), all active in Pasadena:
# 9100001 single-family 3 beds $845,000; 9100002 single-family 4 beds $925,000;
# 9100003 townhouse 3 beds $989,000. 9100010 is in Los Angeles; key 1 does not exist.
_FIXTURE_KEYS = [9100003, 9100001, 9100002]


def _require_fixture(conn: Any) -> None:
    """Skip on the real data: these keys and their values are the fixture's own."""
    if _one(conn, "SELECT COUNT(*) AS n FROM rets_property", ())["n"] >= 10_000:
        pytest.skip("the candidate keys are fixture keys; not in the real data")


def test_fetch_candidates_returns_the_keys_in_the_order_asked(conn):
    _require_fixture(conn)
    outcome = fetch_candidates(PropertySearchFilters(), _FIXTURE_KEYS, conn)
    assert [x.listing_key for x in outcome.listings] == _FIXTURE_KEYS
    assert outcome.skipped_rows == 0 and outcome.warnings == []
    for item in outcome.listings:
        assert item.status == "Active" and item.city == "Pasadena"
        # The candidate statement never selects remarks.
        assert item.remarks is None
        assert not set(item.model_dump()) & (DENYLIST | AGENT_CONTACT)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"city": "Pasadena", "min_beds": 4}, [9100002]),
        ({"max_price": 900_000}, [9100001]),
        ({"property_subtype": "Townhouse"}, [9100003]),
        ({"city": "Glendale"}, []),
    ],
    ids=["beds", "price", "subtype", "city"],
)
def test_fetch_candidates_drops_keys_that_fail_a_filter(conn, filters, expected):
    _require_fixture(conn)
    outcome = fetch_candidates(PropertySearchFilters(**filters), _FIXTURE_KEYS, conn)
    assert [x.listing_key for x in outcome.listings] == expected


def test_fetch_candidates_drops_unknown_and_other_city_keys(conn):
    _require_fixture(conn)
    keys = [1, 9100010, 9100001]
    filters = PropertySearchFilters(city="Pasadena")
    outcome = fetch_candidates(filters, keys, conn)
    assert [x.listing_key for x in outcome.listings] == [9100001]
    everywhere = fetch_candidates(PropertySearchFilters(), keys, conn)
    assert [x.listing_key for x in everywhere.listings] == [9100010, 9100001]


# --- WO-010 full similar path over the CI fixture index ---

_SEMANTIC_CASES = ("semantic-ci-001", "semantic-ci-003")


def _require_semantic_group(conn: Any) -> None:
    """Skip on the real data, and on a fixture database loaded before WO-010 added the
    Sierra Madre group (the ranked keys are that group's)."""
    _require_fixture(conn)
    sql = "SELECT COUNT(*) AS n FROM rets_property WHERE L_City = %s"
    if _one(conn, sql, ("Sierra Madre",))["n"] == 0:
        pytest.skip("the fixture database predates the Sierra Madre rows; reload it")


def _semantic_case(case_id: str) -> runner.Case:
    """One case from semantic_retrieval.yaml, through the runner's loader."""
    cases, _ = runner.load_cases(_CASES_DIR)
    (case,) = [c for c in cases if c.id == case_id]
    return case


def _semantic_fixture() -> ModuleType:
    """tests/semantic_fixture.py, imported by path (tests/ is no package)."""
    path = Path(__file__).resolve().parent / "semantic_fixture.py"
    spec = importlib.util.spec_from_file_location("semantic_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case_id", _SEMANTIC_CASES)
def test_the_similar_path_returns_the_case_files_keys(
    conn, case_id, tmp_path, monkeypatch
):
    """similar_result end to end (validation, the fixture index, the hashing embedder,
    the real candidate SQL) returns the keys the case file pins, in rank order."""
    pytest.importorskip("numpy")
    _require_semantic_group(conn)
    fixture = _semantic_fixture()
    path = fixture.build_fixture_index(tmp_path)
    for name, value in fixture.fixture_env(path).items():
        monkeypatch.setenv(name, value)
    mcp.reset_semantic_for_tests()
    try:
        case = _semantic_case(case_id)
        envelope = mcp.similar_result(dict(case.input_filters or {}))
    finally:
        mcp.reset_semantic_for_tests()
    assert envelope.ok, envelope.error
    keys = [m.listing.listing_key for m in envelope.data.matches]
    assert keys == case.expect["keys"]


# --- WO-011 comps and the recommend path over the fixture ---


def _require_recommend_group(conn: Any) -> None:
    """Skip on the real data, and on a fixture database loaded before WO-011 added its
    Duarte listings and Bradbury sales (the case literals are those rows')."""
    _require_fixture(conn)
    active = "SELECT COUNT(*) AS n FROM rets_property WHERE L_City = %s"
    sold = "SELECT COUNT(*) AS n FROM california_sold WHERE City = %s"
    if not (
        _one(conn, active, ("Duarte",))["n"] and _one(conn, sold, ("Bradbury",))["n"]
    ):
        pytest.skip("the fixture database predates the WO-011 rows; reload it")


def _recommend_cases(*checks: str) -> list[runner.Case]:
    """The fixture-only ci cases of recommendations.yaml, via the runner's loader."""
    cases, _ = runner.load_cases(_CASES_DIR)
    return [
        c
        for c in cases
        if c.source == "recommendations.yaml"
        and c.suite == "ci"
        and c.database == "fixture"
        and (not checks or c.check in checks)
    ]


def _recommend_reference() -> ModuleType:
    """tests/test_recommend_cases.py, for its Python comps reference (by path)."""
    path = Path(__file__).resolve().parent / "test_recommend_cases.py"
    spec = importlib.util.spec_from_file_location("recommend_reference", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "case", _recommend_cases("price_check_exact"), ids=lambda c: c.id
)
def test_fetch_comps_matches_the_case_literals(conn, case: runner.Case):
    """The real comps SQL for each fixture subject: the subject check equals the case
    literal, and the level, count, middles, and middle-half ends equal the Python
    reference's, at the level used and at each level on its own."""
    pytest.importorskip("numpy")
    _require_recommend_group(conn)
    reference = _recommend_reference()
    key = int((case.input_filters or {})["listing_key"])
    (listing,) = fetch_candidates(PropertySearchFilters(), [key], conn).listings
    subject = subject_from_listing(listing)
    assert isinstance(subject, CompSubject), case.id
    dates = asof.read_asof_dates(conn)
    window = comps_window(dates)
    aggregate = fetch_comps(subject, window, dates, conn)
    assert aggregate == reference.fake_fetch_comps(subject, window, dates, conn)
    for level in ("postal_code", "city"):
        got = db_comps._aggregate(conn, subject, level, window, dates)
        middles, ends = reference._order_statistics(
            reference.comp_sales(subject, level)
        )
        assert (got.middles, got.range_ends) == (middles, ends), (case.id, level)
    evidence = price_check(aggregate, subject)
    assert runner._evidence_diff("subject", case.expect["subject"], evidence) == []


def test_a_short_zip_widens_to_the_city_against_real_sql(conn):
    """An invented ZIP no fixture sale carries: the ZIP statement finds 0, the city
    statement finds the five Monrovia comps of ci-001, and the sentence names both."""
    _require_recommend_group(conn)
    subject = CompSubject(
        city="Monrovia", postal_code="91099", subtype="SingleFamilyResidence",
        living_area=1700, bedrooms=3, list_price=1_020_000,
    )  # fmt: skip
    dates = asof.read_asof_dates(conn)
    aggregate = fetch_comps(subject, comps_window(dates), dates, conn)
    assert (aggregate.level, aggregate.count, aggregate.widened_from) == (
        "city", 5, "ZIP 91099",
    )  # fmt: skip
    evidence = price_check(aggregate, subject)
    assert (evidence.median_price_per_sqft, evidence.delta_pct) == (579, 4.0)
    assert (evidence.range_low_price_per_sqft, evidence.range_high_price_per_sqft) == (
        575, 587,
    )  # fmt: skip
    assert evidence.sentence == (
        "Listed 4% above the median price per square foot of 5 comparable sales in "
        "Monrovia over the last six months (widened from ZIP 91099, which had too few)."
    )
    assert evidence.range_sentence == (
        "The middle half of those sales ran from $575 to $587 per square foot."
    )


@pytest.mark.parametrize("case", _recommend_cases(), ids=lambda c: c.id)
def test_the_recommend_path_passes_each_fixture_case(
    conn, case: runner.Case, tmp_path, monkeypatch
):
    """recommend_result end to end (validation, the fixture index, the neighbour
    ranking, the real candidate and comps SQL, the card), judged by the case's own
    check: exact price checks, ranked keys, the card, and the absences."""
    pytest.importorskip("numpy")
    _require_recommend_group(conn)
    fixture = _semantic_fixture()
    path = fixture.build_fixture_index(tmp_path)
    for name, value in fixture.fixture_env(path).items():
        monkeypatch.setenv(name, value)
    mcp.reset_semantic_for_tests()
    try:
        envelope = mcp.recommend_result(dict(case.input_filters or {}))
    finally:
        mcp.reset_semantic_for_tests()
    verdict, detail = runner.CHECKS[case.check].judge(case.expect, envelope)
    assert verdict == runner.PASS, f"{case.id}: {detail}"
