"""Unit tests for db/market.py and the earliest close date in db/asof.py; no database.

The builder is checked as (sql, params): allowlisted columns only, every value bound,
each exclusion rule and the duplicate ranking present. The executor runs on a fake
connection with invented aggregate rows: the 50-row cap and the MarketAggregates map.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from idx_agent.db import asof, market
from idx_agent.db.market import (
    LABELS,
    MAX_ROWS,
    MIX_LIMIT,
    build_market_sql,
    fetch_market_aggregates,
)
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import (
    AREA_FLOOR,
    DEFAULT_SUBTYPE,
    EXCLUSION_RULES,
    PRICE_FLOOR,
    MarketAggregates,
    MonthAggregate,
)
from idx_agent.domain.models import MarketStatsRequest, StatsWindow
from idx_agent.safety.columns import AGENT_CONTACT, ALLOWLIST, DENYLIST

AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SIX = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
ONE = StatsWindow(start=date(2026, 8, 18), end=date(2026, 9, 17), months=1)

# SQL words, functions, CTE names, and aliases the builder may emit besides columns.
_SQL_WORDS = {
    *"WITH AS SELECT FROM WHERE AND OR NOT IS NULL IN BETWEEN LIKE".split(),
    *"ROW_NUMBER OVER PARTITION BY ORDER DESC COUNT SUM MAX CASE WHEN THEN".split(),
    *"END FLOOR DATE_FORMAT GROUP LIMIT".split(),
    "california_sold",
    "s",  # from the %s placeholders
    *"d d_raw m m_raw o x rn n dup keyless ym".split(),
    *"close_price list_price dom area subtype".split(),
    *"lo_close_price hi_close_price lo_list_price hi_list_price lo_dom hi_dom".split(),
    *"lo_area hi_area sample_count dom_sample ppsf_sample".split(),
    *EXCLUSION_RULES,
}


def _request(**fields: Any) -> MarketStatsRequest:
    """A validated request; Pasadena single-family default unless overridden."""
    return MarketStatsRequest(**({"city": "Pasadena"} | fields))


def _statements(request: MarketStatsRequest | None = None) -> list[tuple[str, Any]]:
    """The built (sql, params) pairs for a request (Pasadena, 6 months, default)."""
    return list(build_market_sql(request or _request(), SIX, AS_OF).statements)


# --- build_market_sql: shape, allowlist, parameters ---


def test_eight_statements_in_label_order():
    query = build_market_sql(_request(), SIX, AS_OF)
    assert query.labels == LABELS
    assert LABELS == (
        "count",
        "price",
        "dom",
        "ratio",
        "ppsf",
        "months",
        "mix",
        "exclusions",
    )
    assert len(query.statements) == len(LABELS)
    assert query.statement("mix") is query.statements[LABELS.index("mix")]
    with pytest.raises(KeyError):
        query.statement("rows")


@pytest.mark.parametrize(
    "request_fields",
    [{}, {"postal_code": "91101", "city": None}, {"property_subtype": "Condominium"}],
)
def test_every_value_is_a_bound_parameter(request_fields):
    """One %s per param, no quoted literal, and no number written into the SQL."""
    for sql, params in _statements(_request(**request_fields)):
        assert sql.count("%s") == len(params)
        assert "'" not in sql and '"' not in sql
        assert not re.search(r"(?<![A-Za-z_])[0-9]", sql), sql
        assert "SELECT *" not in sql and ".*" not in sql


def test_every_identifier_is_allowlisted_and_no_agent_or_denied_column_appears():
    for sql, _params in _statements() + _statements(
        _request(postal_code="91101", city=None)
    ):
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)) - _SQL_WORDS
        assert names <= ALLOWLIST["california_sold"], (
            names - ALLOWLIST["california_sold"]
        )
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))
        assert not words & (AGENT_CONTACT | DENYLIST)


def test_no_statement_selects_a_key_an_address_or_a_per_sale_column():
    """ListingKey is only partitioned on inside the CTE; no address is ever named."""
    for sql, _params in _statements():
        assert "UnparsedAddress" not in sql
        outer = sql.rsplit(") SELECT ", 1)[-1]
        assert "ListingKey" not in outer


@pytest.mark.parametrize(
    "bad", ["NotAColumn", "ListAgentFirstName", "BuyerOfficeName", "PrivateRemarks"]
)
def test_a_column_outside_the_allowlist_raises(monkeypatch, bad):
    monkeypatch.setitem(market._COLUMNS, "dom", bad)
    with pytest.raises(ValueError):
        build_market_sql(_request(), SIX, AS_OF)


def test_a_column_dropped_from_the_allowlist_raises(monkeypatch):
    shrunk = ALLOWLIST["california_sold"] - {"LivingArea"}
    monkeypatch.setitem(ALLOWLIST, "california_sold", shrunk)
    with pytest.raises(ValueError, match="LivingArea"):
        build_market_sql(_request(), SIX, AS_OF)


def test_injection_text_stays_in_params():
    evil = "Pasadena' OR '1'='1'; DROP TABLE california_sold; --"
    request = MarketStatsRequest.model_construct(
        city=evil, postal_code=None, property_subtype="x' OR 1=1 --", months=6
    )
    for sql, params in _statements(request):
        assert "DROP" not in sql and "OR 1=1" not in sql
        assert evil in params
    assert "x' OR 1=1 --" in _statements(request)[0][1]


def test_window_dates_asof_floors_and_month_format_are_bound():
    for sql, params in _statements():
        assert SIX.start in params and SIX.end in params
        assert AS_OF.active in params
        assert params.count(PRICE_FLOOR) >= 2
        assert "%Y-%m" in params
        assert "DATE_FORMAT(close_date_d, %s) AS ym" in sql
    count_params = build_market_sql(_request(), SIX, AS_OF).statement("count")[1]
    assert count_params[-2:] == (0, AREA_FLOOR)


def test_the_one_month_window_binds_its_own_dates():
    sql, params = build_market_sql(_request(months=1), ONE, AS_OF).statement("price")
    assert (ONE.start, ONE.end) == (params[2], params[3])
    assert "close_date_d BETWEEN %s AND %s" in sql


def test_city_is_an_exact_match_and_a_zip_is_a_five_digit_prefix():
    sql, params = build_market_sql(_request(), SIX, AS_OF).statement("count")
    assert "City = %s" in sql and "Pasadena" in params
    zip_request = _request(city=None, postal_code="91101")
    sql, params = build_market_sql(zip_request, SIX, AS_OF).statement("count")
    assert "PostalCode LIKE %s" in sql and "91101%" in params
    assert "City = %s" not in sql


@pytest.mark.parametrize(
    "fields",
    [
        {"city": None, "postal_code": "9110"},
        {"city": None, "postal_code": "91101-1234"},
        {"city": None, "postal_code": None},
        {"city": "Pasadena", "postal_code": "91101"},
    ],
)
def test_a_bad_place_raises_before_any_sql(fields):
    request = MarketStatsRequest.model_construct(
        property_subtype=None, months=6, **fields
    )
    with pytest.raises(ValueError):
        build_market_sql(request, SIX, AS_OF)


def test_a_window_ending_after_the_sold_asof_date_raises():
    today_like = StatsWindow(start=date(2026, 3, 25), end=date(2026, 9, 24), months=6)
    with pytest.raises(ValueError, match="as-of"):
        build_market_sql(_request(), today_like, AS_OF)


def test_each_exclusion_rule_is_in_the_sample():
    sql = build_market_sql(_request(), SIX, AS_OF).statement("price")[0]
    assert "close_date_d BETWEEN %s AND %s" in sql  # window; NULL dates drop out
    assert "close_date_d <= %s" in sql  # never after the active as-of date
    assert (
        "NOT (purchase_contract_date_d IS NOT NULL "
        "AND close_date_d < purchase_contract_date_d)"
    ) in sql
    assert "ClosePrice >= %s" in sql and "ListPrice >= %s" in sql
    assert "PropertySubType = %s" in sql
    assert "WHERE dup = %s OR keyless" in sql


def test_duplicates_rank_latest_close_then_higher_close_then_higher_list():
    sql, params = build_market_sql(_request(), SIX, AS_OF).statement("count")
    assert (
        "ROW_NUMBER() OVER (PARTITION BY ListingKey ORDER BY close_date_d DESC, "
        "ClosePrice DESC, ListPrice DESC) AS dup"
    ) in sql
    assert "ListingKey IS NULL AS keyless" in sql  # a missing key is never a repeat
    assert params[-3] == 1  # the kept rank, bound


def test_the_exclusions_statement_counts_every_rule():
    sql, params = build_market_sql(_request(), SIX, AS_OF).statement("exclusions")
    for rule in EXCLUSION_RULES:
        assert f"AS {rule}" in sql
    assert "SUM(close_date_d > %s) AS after_active_asof" in sql
    assert "SUM(close_date_d IS NULL) AS unreadable_close_date" in sql
    assert "WHERE area IS NULL OR area < %s" in sql
    assert "WHERE dom IS NULL OR dom < %s" in sql
    assert params[-3:] == (1, AREA_FLOOR, 0)


def test_dom_and_ppsf_medians_leave_out_only_their_own_missing_values():
    query = build_market_sql(_request(), SIX, AS_OF)
    dom_sql, dom_params = query.statement("dom")
    assert "FROM d WHERE dom >= %s" in dom_sql and 0 in dom_params
    ppsf_sql, ppsf_params = query.statement("ppsf")
    assert "FROM d WHERE area >= %s" in ppsf_sql and AREA_FLOOR in ppsf_params
    price_sql = query.statement("price")[0]
    assert "FROM d)" in price_sql  # no metric filter on the price sample


def test_medians_use_the_window_function_middle_rows():
    sql, params = build_market_sql(_request(), SIX, AS_OF).statement("ratio")
    assert "ROW_NUMBER() OVER (ORDER BY close_price / list_price) AS rn" in sql
    assert "COUNT(*) OVER () AS n" in sql
    assert "MAX(CASE WHEN rn = FLOOR((n + %s) / %s) THEN close_price END)" in sql
    assert "MAX(CASE WHEN rn = FLOOR(n / %s) + %s THEN list_price END)" in sql
    assert params[-8:] == (1, 2, 1, 2, 2, 1, 2, 1)


def test_months_bucket_on_close_date_d():
    sql = build_market_sql(_request(), SIX, AS_OF).statement("months")[0]
    assert "PARTITION BY ym ORDER BY close_price" in sql
    assert sql.endswith("GROUP BY ym ORDER BY ym")


def test_no_subtype_uses_the_default_and_the_mix_leaves_it_out():
    query = build_market_sql(_request(), SIX, AS_OF)
    assert DEFAULT_SUBTYPE in query.statement("count")[1]
    sql, params = query.statement("mix")
    assert "PropertySubType = %s" not in sql  # every subtype is in the mix sample
    assert "WHERE subtype IS NULL OR subtype <> %s" in sql
    assert params[-2:] == (DEFAULT_SUBTYPE, MIX_LIMIT)
    condo = build_market_sql(_request(property_subtype="Condominium"), SIX, AS_OF)
    assert condo.statement("mix")[1][-2:] == ("Condominium", MIX_LIMIT)
    assert "Condominium" in condo.statement("price")[1]


# --- fetch_market_aggregates on a fake connection ---


class FakeCursor:
    """Records the executed statement and returns the rows queued for its label."""

    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self.label: str | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn.executed.append((sql, tuple(params)))
        self.label = self.conn.labels[sql]

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.conn.rows.get(self.label, []))

    def fetchone(self) -> dict[str, Any] | None:
        return self.conn.rows[self.label][0]


class FakeConnection:
    """Stands in for a pymysql connection: rows by statement label (dict rows)."""

    def __init__(self, request: MarketStatsRequest, rows: dict[str, list[dict]]):
        query = build_market_sql(request, SIX, AS_OF)
        pairs = zip(query.labels, query.statements, strict=True)
        self.labels = {sql: label for label, (sql, _) in pairs}
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


# Invented aggregates: 7 sales (odd), 6 with DaysOnMarket (even), 6 with area (even).
ROWS: dict[str, list[dict[str, Any]]] = {
    "count": [{"sample_count": 7, "dom_sample": Decimal(6), "ppsf_sample": Decimal(6)}],
    "price": [{"n": 7, "lo_close_price": 812345.5, "hi_close_price": 812345.5}],
    "dom": [{"n": 6, "lo_dom": 21, "hi_dom": 24}],
    "ratio": [
        {
            "n": 7,
            "lo_close_price": 1_030_000.0,
            "lo_list_price": 1_000_000.0,
            "hi_close_price": 1_030_000.0,
            "hi_list_price": 1_000_000.0,
        }
    ],
    "ppsf": [
        {
            "n": 6,
            "lo_close_price": 900_000.0,
            "lo_area": 1500.0,
            "hi_close_price": 1_000_000.0,
            "hi_area": 1600.0,
        }
    ],
    "months": [
        {
            "ym": "2026-03",
            "n": 1,
            "lo_close_price": 700_000.0,
            "hi_close_price": 700_000.0,
        },
        {
            "ym": "2026-05",
            "n": 4,
            "lo_close_price": 800_000.0,
            "hi_close_price": 850_000.0,
        },
        {
            "ym": "2026-09",
            "n": 2,
            "lo_close_price": 810_000.0,
            "hi_close_price": 990_000.0,
        },
    ],
    "mix": [{"subtype": "Condominium", "n": 4}, {"subtype": None, "n": 1}],
    "exclusions": [
        {
            "after_active_asof": Decimal(1),
            "unreadable_close_date": Decimal(0),
            "close_before_contract": Decimal(1),
            "price_under_floor": None,  # an empty SUM
            "duplicate_listing_key": 1,
            "area_under_floor": 1,
            "dom_missing": 1,
        }
    ],
}


def test_the_rows_map_to_market_aggregates():
    conn = FakeConnection(_request(), ROWS)
    result = fetch_market_aggregates(_request(), SIX, AS_OF, conn)
    assert isinstance(result, MarketAggregates)
    assert [sql for sql, _ in conn.executed] == [
        sql for sql, _ in build_market_sql(_request(), SIX, AS_OF).statements
    ]
    assert result.sample_count == 7
    assert result.price_middles == (Decimal("812345.5"),)  # a double, exactly
    assert result.dom_middles == (Decimal(21), Decimal(24))
    assert (result.dom_sample, result.ppsf_sample) == (6, 6)
    assert result.ratio_middles == (Decimal("1.03"),)
    assert result.ppsf_middles == (Decimal(600), Decimal(625))
    assert result.subtype_mix == (("Condominium", 4), (None, 1))
    assert result.exclusions == (
        ("after_active_asof", 1),
        ("unreadable_close_date", 0),
        ("close_before_contract", 1),
        ("price_under_floor", 0),
        ("duplicate_listing_key", 1),
        ("area_under_floor", 1),
        ("dom_missing", 1),
    )
    assert all(type(count) is int for _rule, count in result.exclusions)


def test_every_window_month_is_present_oldest_first_with_zero_months():
    result = fetch_market_aggregates(
        _request(), SIX, AS_OF, FakeConnection(_request(), ROWS)
    )
    assert result.months == (
        MonthAggregate("2026-03", 1, (Decimal(700000),)),
        MonthAggregate("2026-04", 0, ()),
        MonthAggregate("2026-05", 4, (Decimal(800000), Decimal(850000))),
        MonthAggregate("2026-06", 0, ()),
        MonthAggregate("2026-07", 0, ()),
        MonthAggregate("2026-08", 0, ()),
        MonthAggregate("2026-09", 2, (Decimal(810000), Decimal(990000))),
    )
    assert sum(m.count for m in result.months) == result.sample_count


def test_an_empty_sample_has_no_middles_and_zero_counts():
    empty = {
        "count": [{"sample_count": 0, "dom_sample": None, "ppsf_sample": None}],
        "price": [{"n": None, "lo_close_price": None, "hi_close_price": None}],
        "dom": [{"n": None, "lo_dom": None, "hi_dom": None}],
        "ratio": [{"n": None}],
        "ppsf": [{"n": None}],
        "months": [],
        "mix": [],
        "exclusions": [dict.fromkeys(EXCLUSION_RULES)],
    }
    result = fetch_market_aggregates(
        _request(), SIX, AS_OF, FakeConnection(_request(), empty)
    )
    assert result.sample_count == result.dom_sample == result.ppsf_sample == 0
    assert result.price_middles == result.dom_middles == ()
    assert result.ratio_middles == result.ppsf_middles == ()
    assert [m.count for m in result.months] == [0] * 7
    assert result.subtype_mix == ()
    assert result.exclusions == tuple((rule, 0) for rule in EXCLUSION_RULES)


@pytest.mark.parametrize("label", ["months", "mix", "price"])
def test_a_statement_returning_more_than_the_cap_raises(label):
    too_many = dict(ROWS)
    too_many[label] = [dict(ROWS["months"][0]) for _ in range(MAX_ROWS + 1)]
    conn = FakeConnection(_request(), too_many)
    with pytest.raises(RuntimeError, match=f"'{label}' returned {MAX_ROWS + 1} rows"):
        fetch_market_aggregates(_request(), SIX, AS_OF, conn)


def test_exactly_the_cap_is_allowed():
    at_cap = dict(ROWS)
    at_cap["mix"] = [{"subtype": "Townhouse", "n": 1}] * MAX_ROWS
    result = fetch_market_aggregates(
        _request(), SIX, AS_OF, FakeConnection(_request(), at_cap)
    )
    assert len(result.subtype_mix) == MAX_ROWS


# --- db/asof.py: the earliest close date ---


class ScalarConnection:
    """Returns queued one-row results from fetchone, in order; records each query."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> ScalarConnection:
        return self

    def __enter__(self) -> ScalarConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.calls.append((sql, tuple(params)))

    def fetchone(self) -> dict[str, Any]:
        return self.rows.pop(0)


@pytest.fixture
def fresh_asof_cache():
    """Start and end with an empty as-of cache."""
    asof.clear_asof_cache()
    yield
    asof.clear_asof_cache()


def _asof_rows() -> list[dict[str, Any]]:
    """Invented as-of rows (active, sold) then the earliest close."""
    return [
        {"active_max": "2026-09-18 17:30:00"},
        {"sold_max": "2026-09-17"},
        {"sold_min": "2026-03-18"},
    ]


def test_earliest_close_is_read_once_bounded_by_the_active_date(fresh_asof_cache):
    conn = ScalarConnection(_asof_rows())
    assert asof.get_earliest_close(conn) == date(2026, 3, 18)
    assert asof.get_earliest_close(conn) == date(2026, 3, 18)
    assert len(conn.calls) == 3  # active, sold, earliest; the second call is cached
    sql, params = conn.calls[-1]
    assert sql == (
        "SELECT CAST(MIN(close_date_d) AS CHAR) AS sold_min "
        "FROM california_sold WHERE close_date_d <= %s"
    )
    assert params == (date(2026, 9, 18),)


def test_clear_asof_cache_forgets_the_earliest_close_too(fresh_asof_cache):
    conn = ScalarConnection(_asof_rows() + _asof_rows())
    asof.get_earliest_close(conn)
    asof.clear_asof_cache()
    asof.get_earliest_close(conn)
    assert len(conn.calls) == 6


def test_an_unusable_earliest_close_raises(fresh_asof_cache):
    conn = ScalarConnection([{"sold_min": None}])
    with pytest.raises(RuntimeError, match="earliest"):
        asof.read_earliest_close(conn, date(2026, 9, 18))
