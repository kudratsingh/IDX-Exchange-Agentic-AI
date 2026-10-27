"""WO-017 step 1: the analysis reader's SQL (pure) and its fixture integration (db).

Pure tests need no database. The `db` tests run against the synthetic fixture: the
San Gabriel group (60 kept single-family sales, row i closing 3 days apart from
2026-03-20) is re-derived here from its arithmetic, not from the code under test.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Iterator
from datetime import date
from typing import Any

import pymysql
import pytest

from idx_agent.db import analysis, market
from idx_agent.db.analysis import (
    DEADLINE_MS,
    AnalysisDeadlineExceeded,
    build_analysis_sql,
    fetch_analysis_sample,
)
from idx_agent.db.analytics import build_analytics_sql
from idx_agent.db.asof import read_asof_dates
from idx_agent.db.comps import build_comps_sql
from idx_agent.db.market import RowCapExceeded, build_market_sql
from idx_agent.db.pool import DbConfig, connect
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.comps import CompSubject
from idx_agent.domain.fieldmap import _to_zip
from idx_agent.domain.market import AREA_FLOOR, DEFAULT_SUBTYPE, PRICE_FLOOR
from idx_agent.domain.models import MarketStatsRequest, StatsWindow
from idx_agent.safety.columns import AGENT_CONTACT, ALLOWLIST, DENYLIST

AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SIX = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
THREE = StatsWindow(start=date(2026, 6, 18), end=date(2026, 9, 17), months=3)
PROJECTION = [
    "ListingKey",
    "City",
    "PostalCode",
    "PropertySubType",
    "close_date_d",
    "ClosePrice",
    "ListPrice",
    "OriginalListPrice",
    "LivingArea",
    "DaysOnMarket",
]
# SQL words, functions, the CTE name and aliases the builder may emit besides columns.
_SQL_WORDS = {
    *"WITH AS SELECT FROM WHERE AND OR NOT IS NULL BETWEEN LIKE LIMIT".split(),
    *"ROW_NUMBER OVER PARTITION BY ORDER DESC COUNT MAX_EXECUTION_TIME".split(),
    "california_sold",
    "s",  # from the %s placeholders
    *"a dup eligible".split(),
    *"CASE WHEN THEN END TRIM REGEXP".split(),
}


def _request(**fields: Any) -> MarketStatsRequest:
    """A validated request; San Gabriel single-family over 6 months by default."""
    return MarketStatsRequest(**({"city": "San Gabriel"} | fields))


def _sql(request: MarketStatsRequest | None = None, window=SIX) -> tuple[str, tuple]:
    return build_analysis_sql(request or _request(), window, AS_OF)


# --- build_analysis_sql: shape, allowlist, parameters ---


def test_one_statement_with_the_deadline_hint_on_the_top_level_select():
    sql, _params = _sql()
    assert sql.startswith("WITH a AS (SELECT ")
    hint = f"/*+ MAX_EXECUTION_TIME({DEADLINE_MS}) */"
    assert DEADLINE_MS == 2000
    assert sql.count("MAX_EXECUTION_TIME") == 1
    assert f") SELECT {hint} ListingKey, " in sql
    assert sql.count(";") == 0


def test_no_select_star_and_every_identifier_is_allowlisted():
    sql, _params = _sql()
    stripped = sql.replace("COUNT(*)", "COUNT()")
    stripped = re.sub(r"/\*\+ MAX_EXECUTION_TIME\(\d+\) \*/", "", stripped)
    assert "*" not in stripped
    for word in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped)):
        if word in _SQL_WORDS:
            continue
        assert word in ALLOWLIST["california_sold"], word
        assert word not in DENYLIST and word not in AGENT_CONTACT, word


def test_the_projection_is_fixed_and_carries_no_address_text_or_location():
    sql, _params = _sql()
    outer = sql.split(") SELECT ", 1)[1]
    selected = outer.split(" FROM a ", 1)[0].split("*/ ", 1)[1]
    assert selected.split(", ") == [*PROJECTION, "COUNT(*) OVER () AS eligible"]
    inner = sql.split(", ROW_NUMBER()", 1)[0].removeprefix("WITH a AS (SELECT ")
    floored = {"OriginalListPrice", "LivingArea"}
    assert inner.split(", ") == [
        f"CASE WHEN {c} >= %s THEN {c} END AS {c}" if c in floored else c
        for c in PROJECTION
    ]
    for banned in ("UnparsedAddress", "Latitude", "Longitude", "Remarks", "Agent"):
        assert banned not in sql


def test_every_value_is_bound_and_limit_is_the_last_parameter():
    sql, params = _sql()
    assert sql.count("%s") == len(params)
    assert sql.endswith("WHERE dup = %s ORDER BY close_date_d DESC, ListingKey DESC "
                        "LIMIT %s")  # fmt: skip
    assert params[-2:] == (1, 50)
    assert not re.search(r"LIMIT\s+\d", sql)
    assert "San Gabriel" not in sql and "San Gabriel" in params


@pytest.mark.parametrize(
    "fields",
    [
        {"city": "x' OR '1'='1"},
        {"city": "Monrovia", "property_subtype": "Condo'; DROP TABLE t; --"},
    ],
)
def test_injection_text_stays_in_params(fields):
    request = MarketStatsRequest.model_construct(
        **({"city": None, "postal_code": None, "property_subtype": None, "months": 6}
           | fields)
    )  # fmt: skip
    sql, params = build_analysis_sql(request, SIX, AS_OF)
    for text in fields.values():
        assert text not in sql
        assert text in params


def test_zip_is_a_five_digit_prefix_parameter():
    sql, params = _sql(MarketStatsRequest(postal_code="91775"))
    assert "PostalCode LIKE %s" in sql and "City = %s" not in sql
    assert params[2] == "91775%"


def test_floors_compare_the_raw_value_before_any_rounding():
    sql, params = _sql()
    assert sql.startswith(
        "WITH a AS (SELECT ListingKey, City, PostalCode, PropertySubType, "
        "close_date_d, ClosePrice, ListPrice, CASE WHEN OriginalListPrice >= %s THEN "
        "OriginalListPrice END AS OriginalListPrice, CASE WHEN LivingArea >= %s THEN "
        "LivingArea END AS LivingArea, DaysOnMarket, ROW_NUMBER()"
    )
    assert params[:2] == (PRICE_FLOOR, AREA_FLOOR)


def test_zip_scope_keeps_only_a_zip_fieldmap_can_read():
    sql, params = _sql(MarketStatsRequest(postal_code="91776"))
    assert sql.count("AND ListingKey IS NOT NULL AND TRIM(PostalCode) REGEXP %s)") == 1
    assert params[-3] == analysis._ZIP_SHAPE
    assert "REGEXP" not in _sql()[0]  # a city scope never reads the ZIP


@pytest.mark.parametrize(
    "stored,kept",
    [
        ("91776", True),
        ("91776-1234", True),
        ("917761234", True),
        ("91776  ", True),
        ("91776-", False),
        ("917761", False),
        ("91776-12", False),
        ("91776abc", False),
        ("91776\t", False),  # MySQL TRIM leaves the tab, so the row is dropped
    ],
)
def test_the_zip_shape_never_keeps_what_fieldmap_cannot_read(stored, kept):
    # Python stand-in for MySQL's TRIM(PostalCode) REGEXP (spaces only are trimmed).
    keeps = re.search(analysis._ZIP_SHAPE, stored.strip(" ")) is not None
    assert keeps is kept
    if keeps:
        assert _to_zip(stored) == "91776"


def test_the_where_clause_is_market_s_cleaning_plus_a_key():
    sql, params = _sql()
    c = market._columns()
    geo = market._geography(_request(), c)
    where, bound = market._filters(c, geo, SIX, AS_OF, DEFAULT_SUBTYPE)
    assert f"WHERE {' AND '.join(where)} AND ListingKey IS NOT NULL)" in sql
    assert list(params[2 : 2 + len(bound)]) == bound
    raw_sql, raw_params = market._sample("d", c, geo, SIX, AS_OF, DEFAULT_SUBTYPE)
    assert f"WHERE {' AND '.join(where)})" in raw_sql
    assert list(raw_params[1:-1]) == bound
    assert "NOT (purchase_contract_date_d IS NOT NULL" in sql
    assert params.count(PRICE_FLOOR) == 3  # close and list, plus the original floor
    assert DEFAULT_SUBTYPE in params


def test_duplicates_keep_the_latest_close_then_higher_close_then_higher_list():
    sql, _params = _sql()
    assert (
        "ROW_NUMBER() OVER (PARTITION BY ListingKey ORDER BY close_date_d DESC, "
        "ClosePrice DESC, ListPrice DESC) AS dup" in sql
    )
    assert "keyless" not in sql  # unlike the market sample, keyless rows are out


@pytest.mark.parametrize(
    "window,months",
    [
        (THREE, 6),  # window counted for another length
        (StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 18), months=6), 6),
        (StatsWindow(start=date(2026, 3, 1), end=date(2026, 9, 17), months=6), 6),
    ],
)
def test_a_window_not_counted_back_from_the_sold_asof_raises(window, months):
    with pytest.raises(ValueError, match="sold as-of"):
        build_analysis_sql(_request(months=months), window, AS_OF)


@pytest.mark.parametrize(
    "fields",
    [{"city": None, "postal_code": None}, {"city": "Monrovia", "postal_code": "91016"}],
)
def test_a_bad_place_raises_before_any_sql(fields):
    request = MarketStatsRequest.model_construct(
        property_subtype=None, months=6, **fields
    )
    with pytest.raises(ValueError):
        build_analysis_sql(request, SIX, AS_OF)


@pytest.mark.parametrize("bad", ["PrivateRemarks", "ListAgentEmail", "NotAColumn"])
def test_a_projection_column_outside_the_allowlist_raises(monkeypatch, bad):
    monkeypatch.setattr(analysis, "_PROJECTION", (*analysis._PROJECTION, bad))
    with pytest.raises(ValueError):
        build_analysis_sql(_request(), SIX, AS_OF)


# sha256 over each builder's statements ("sql\nparams" joined by newlines), taken
# before WO-017 moved the row exclusions into `market._filters`.
_BEFORE_WO017 = {
    "market_city": "b3e51eac68e38c6a864ef04b42b6e16be9e74d4e40bc83861fd42428f7f14d7a",
    "market_zip_one": (
        "171d70e3766dd264a8ebb70b4ae100fd77049555d00cb5f660d7d3b32b83b05f"
    ),
    "market_condo": "f244f5c6bae7e6723c33fa97d7d7d28ce5cf2245287f794bf20392ff198b32ab",
    "analytics": "c1b0087068b8369ec8a93b1e2745f5c9ecca2ad9ed6ba343d0f384dc36e88d73",
    "comps": "b6ff97f18d954a1895d73fb600a7804cc5cbda501979d57cf01188f1c30dfe67",
}


def _statements(name: str) -> Any:
    one = StatsWindow(start=date(2026, 8, 18), end=date(2026, 9, 17), months=1)
    if name == "market_city":
        return build_market_sql(MarketStatsRequest(city="Monrovia"), SIX, AS_OF)
    if name == "market_zip_one":
        request = MarketStatsRequest(postal_code="91016", months=1)
        return build_market_sql(request, one, AS_OF)
    if name == "market_condo":
        request = MarketStatsRequest(city="Glendale", property_subtype="Condominium")
        return build_market_sql(request, SIX, AS_OF)
    if name == "analytics":
        return build_analytics_sql(MarketStatsRequest(city="Monrovia"), SIX, AS_OF)
    subject = CompSubject(
        city="Monrovia",
        postal_code="91016",
        subtype="SingleFamilyResidence",
        living_area=1700,
        bedrooms=3,
        list_price=850_000,
    )
    return [
        build_comps_sql(subject, lvl, SIX, AS_OF) for lvl in ("postal_code", "city")
    ]


@pytest.mark.parametrize("name", sorted(_BEFORE_WO017))
def test_existing_statements_are_byte_identical_after_the_filter_extraction(name):
    built = _statements(name)
    statements = getattr(built, "statements", built)
    text = "\n".join(f"{sql}\n{params!r}" for sql, params in statements)
    assert hashlib.sha256(text.encode()).hexdigest() == _BEFORE_WO017[name]


# --- fetch_analysis_sample with a fake connection ---


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((sql, params))
        if isinstance(self.rows, Exception):
            raise self.rows

    def fetchall(self) -> list[dict[str, Any]]:
        assert not isinstance(self.rows, Exception)
        return self.rows


class _Conn:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self.cur = _Cursor(rows)

    def cursor(self) -> _Cursor:
        return self.cur


def _row(key: int, **changes: Any) -> dict[str, Any]:
    """A driver-shaped invented row: doubles for numbers, as the sold table has."""
    return {
        "ListingKey": key,
        "City": "San Gabriel",
        "PostalCode": "91776",
        "PropertySubType": "SingleFamilyResidence",
        "close_date_d": date(2026, 9, 1),
        "ClosePrice": 900_000.0,
        "ListPrice": 910_000.0,
        "OriginalListPrice": 925_000.0,
        "LivingArea": 1_500.0,
        "DaysOnMarket": 21,
        "eligible": 75,
    } | changes


def test_fetch_maps_rows_in_order_and_records_the_eligible_count(caplog):
    rows = [
        _row(9_900_003, ClosePrice=1_000_000.4, PostalCode="91776-1234"),
        _row(9_900_002, LivingArea=150.0, OriginalListPrice=20_000.0),
        _row(9_900_001, LivingArea=None, OriginalListPrice=None, DaysOnMarket=None),
        _row(9_900_000, UnparsedAddress="1 Invented Way", DaysOnMarket=7.0),
    ]
    conn = _Conn(rows)
    with caplog.at_level(logging.DEBUG):
        sample = fetch_analysis_sample(_request(), SIX, AS_OF, conn)
    assert caplog.records == []
    assert conn.cur.executed == [_sql()]
    assert sample.eligible == 75
    assert sample.worker_rows() == [
        dict(close_price=1_000_000, list_price=910_000, original_list_price=925_000,
             living_area=1_500, days_on_market=21),
        dict(close_price=900_000, list_price=910_000, original_list_price=None,
             living_area=None, days_on_market=21),
        dict(close_price=900_000, list_price=910_000, original_list_price=None,
             living_area=None, days_on_market=None),
        dict(close_price=900_000, list_price=910_000, original_list_price=925_000,
             living_area=1_500, days_on_market=7),
    ]  # fmt: skip
    assert "4 most recent of 75 eligible" in " ".join(sample.caveats())


def test_an_empty_result_is_an_empty_sample():
    sample = fetch_analysis_sample(_request(), SIX, AS_OF, _Conn([]))
    assert sample.rows == () and sample.eligible == 0
    assert "eligible" not in " ".join(sample.caveats())


def test_more_than_fifty_rows_is_refused():
    rows = [_row(9_900_000 + i) for i in range(51)]
    with pytest.raises(RowCapExceeded, match="51 rows; cap 50"):
        fetch_analysis_sample(_request(), SIX, AS_OF, _Conn(rows))


def test_the_deadline_error_is_typed_and_echoes_nothing():
    error = pymysql.err.OperationalError(3024, "interrupted: secret detail")
    with pytest.raises(AnalysisDeadlineExceeded) as raised:
        fetch_analysis_sample(_request(), SIX, AS_OF, _Conn(error))
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_other_driver_errors_pass_through():
    error = pymysql.err.OperationalError(2013, "lost connection")
    with pytest.raises(pymysql.err.OperationalError):
        fetch_analysis_sample(_request(), SIX, AS_OF, _Conn(error))


@pytest.mark.parametrize(
    "changes",
    [
        {"City": "Monrovia"},
        {"PropertySubType": "Condominium"},
        {"close_date_d": date(2026, 9, 18)},
        {"ListPrice": None},
        {"ListingKey": None},  # the SQL drops keyless rows; one reaching here fails
    ],
)
def test_a_row_outside_the_request_fails_closed(changes):
    with pytest.raises(ValueError):
        fetch_analysis_sample(
            _request(), SIX, AS_OF, _Conn([_row(9_900_000, **changes)])
        )


def test_a_repeated_key_fails_closed():
    rows = [_row(9_900_000), _row(9_900_000, ClosePrice=950_000.0)]
    with pytest.raises(ValueError, match="duplicate"):
        fetch_analysis_sample(_request(), SIX, AS_OF, _Conn(rows))


# --- integration against the synthetic fixture (San Gabriel group) ---

_KEY = 9_320_000
_ZIP_91775 = range(60, 0, -6)  # every sixth row, newest first


def _expected(i: int) -> dict[str, int | None]:
    """Row i of the fixture's San Gabriel group, from its stated arithmetic."""
    close = 700_000 + 4_000 * i
    listed = close + 6_000 - 2_000 * (i % 5)
    row = dict(
        close_price=close,
        list_price=listed,
        original_list_price=listed + 5_000 * (i % 4),
        living_area=1_100 + 13 * i,
        days_on_market=4 + (i * 7) % 50,
    )
    row |= {54: {"original_list_price": None}, 55: {"living_area": None},
            56: {"days_on_market": None}, 57: {"living_area": None},
            58: {"original_list_price": None}}.get(i, {})  # fmt: skip
    return row


@pytest.fixture(scope="module")
def conn() -> Iterator[Any]:
    connection = connect(DbConfig.from_env())
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.db
def test_fixture_asof_dates_are_the_ones_these_tests_assume(conn):
    assert read_asof_dates(conn) == AS_OF


@pytest.mark.db
def test_the_cap_binds_at_fifty_newest_first_with_key_ties(conn):
    sql, params = _sql()
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.execute("SHOW WARNINGS")
        assert cursor.fetchall() in ((), [])
    assert [int(r["ListingKey"]) for r in rows] == [_KEY + i for i in range(60, 10, -1)]
    assert rows[0]["close_date_d"] == rows[1]["close_date_d"] == date(2026, 9, 10)
    assert {int(r["eligible"]) for r in rows} == {60}

    sample = fetch_analysis_sample(_request(), SIX, AS_OF, conn)
    assert sample.worker_rows() == [_expected(i) for i in range(60, 10, -1)]
    assert sample.eligible == 60
    assert "50 most recent of 60 eligible" in " ".join(sample.caveats())


@pytest.mark.db
def test_dedup_and_exclusions_drop_their_rows(conn):
    prices = {
        r.close_price for r in fetch_analysis_sample(_request(), SIX, AS_OF, conn).rows
    }
    # the older copy of 9320060, the price under the floor, the close before contract
    assert prices.isdisjoint({905_000, 19_000, 950_000})
    condo = _request(property_subtype="Condominium")
    rows = fetch_analysis_sample(condo, SIX, AS_OF, conn).worker_rows()
    assert [r["close_price"] for r in rows] == [610_000, 590_000]


@pytest.mark.db
def test_a_shorter_window_keeps_only_its_own_sales(conn):
    sample = fetch_analysis_sample(_request(months=3), THREE, AS_OF, conn)
    assert sample.worker_rows() == [_expected(i) for i in range(60, 30, -1)]
    assert sample.eligible == 30
    assert "eligible" not in " ".join(sample.caveats())


@pytest.mark.db
def test_zip_scope_includes_the_zip_plus_four_row(conn):
    request = MarketStatsRequest(postal_code="91775")
    sample = fetch_analysis_sample(request, SIX, AS_OF, conn)
    assert sample.worker_rows() == [_expected(i) for i in _ZIP_91775]
    assert sample.eligible == 10


@pytest.mark.db
def test_an_empty_scope_is_an_empty_sample(conn):
    sample = fetch_analysis_sample(_request(city="Alhambra"), SIX, AS_OF, conn)
    assert sample.rows == () and sample.eligible == 0


@pytest.mark.db
def test_the_hint_is_kept_on_the_real_statement(conn):
    sql, params = _sql()
    with conn.cursor() as cursor:
        cursor.execute("EXPLAIN " + sql, params)
        cursor.execute("SHOW WARNINGS")
        notes = cursor.fetchall()
        # The same hint inside the CTE is ignored with a warning: the check can fail.
        cursor.execute(f"EXPLAIN WITH a AS (SELECT {analysis._HINT} ListingKey "
                       "FROM california_sold) SELECT ListingKey FROM a")  # fmt: skip
        cursor.execute("SHOW WARNINGS")
        misplaced = cursor.fetchall()
    assert not [n for n in notes if n["Level"] == "Warning"]
    assert any(f"MAX_EXECUTION_TIME({DEADLINE_MS})" in n["Message"] for n in notes)
    assert [n["Code"] for n in misplaced if n["Level"] == "Warning"] == [3125]


@pytest.mark.db
def test_the_deadline_cuts_off_a_slow_statement():
    # Test-only statement in the reader's own form; unbounded it sleeps for ~11 s.
    slow = (
        "WITH a AS (SELECT ListingKey, ROW_NUMBER() OVER (ORDER BY ListingKey) AS rn "
        "FROM california_sold WHERE SLEEP(%s) = %s) "
        f"SELECT {analysis._HINT} ListingKey FROM a LIMIT %s",
        (0.1, 0, 1),
    )
    connection = connect(DbConfig.from_env())
    try:
        started = time.monotonic()
        with pytest.raises(AnalysisDeadlineExceeded):
            analysis._run(connection, slow)
        elapsed = time.monotonic() - started
    finally:
        connection.close()
    assert DEADLINE_MS / 1000 - 0.5 <= elapsed < DEADLINE_MS / 1000 + 2.5


# Edge rows the fixture cannot hold (the lint needs invented keys; the real data has
# no negatives): (key, PostalCode, close day in 2026-08, OriginalListPrice, LivingArea)
_EDGE = (
    (None, "91776", 31, 900_000.0, 1_500.0),  # keyless: dropped
    (9_329_001, "91776", 30, 24_999.5, 199.5),  # under the floors before rounding
    (9_329_002, "91776", 29, -1.0, -5.0),  # negative: unknown, not an error
    (9_329_003, "91776-", 28, 25_000.0, 200.0),  # ZIP unreadable: out of ZIP scope
    (9_329_004, "91776  ", 27, 925_000.0, 1_500.0),
    (9_329_005, "91776-1234", 26, 25_000.4, 200.4),
)


def _literal(value: Any) -> str:
    if isinstance(value, float):
        return f"CAST({value!r} AS DOUBLE)"
    if isinstance(value, str):
        return f"'{value}'"
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    return "CAST(NULL AS SIGNED)" if value is None else f"CAST({value} AS SIGNED)"


def _edge_table() -> str:
    """The edge rows as a derived table with the reader's columns (literals only)."""
    selects = []
    for key, postal, day, original, area in _EDGE:
        values = {
            "ListingKey": key,
            "City": "San Gabriel",
            "PostalCode": postal,
            "PropertySubType": DEFAULT_SUBTYPE,
            "close_date_d": date(2026, 8, day),
            "purchase_contract_date_d": None,
            "ClosePrice": 900_000.0,
            "ListPrice": 910_000.0,
            "OriginalListPrice": original,
            "LivingArea": area,
            "DaysOnMarket": 21,
        }
        cast = {"purchase_contract_date_d": "CAST(NULL AS DATE)"}
        selects.append("SELECT " + ", ".join(
            f"{cast.get(name) or _literal(value)} AS {name}"
            for name, value in values.items()
        ))  # fmt: skip
    return " UNION ALL ".join(selects)


@pytest.mark.db
@pytest.mark.parametrize(
    "request_,keys",
    [
        (_request(), [9_329_001, 9_329_002, 9_329_003, 9_329_004, 9_329_005]),
        (MarketStatsRequest(postal_code="91776"), [9_329_001, 9_329_002, 9_329_004,
                                                    9_329_005]),
    ],
)  # fmt: skip
def test_edge_rows_through_the_reader_s_own_statement(
    conn, monkeypatch, request_, keys
):
    build = analysis.build_analysis_sql

    def on_edge_rows(*args: Any) -> tuple[str, tuple]:
        sql, params = build(*args)
        assert sql.count("FROM california_sold WHERE") == 1
        table = f"FROM ({_edge_table()}) AS california_sold WHERE"
        return sql.replace("FROM california_sold WHERE", table), params

    monkeypatch.setattr(analysis, "build_analysis_sql", on_edge_rows)
    with conn.cursor() as cursor:
        cursor.execute(*on_edge_rows(request_, SIX, AS_OF))
        assert [int(r["ListingKey"]) for r in cursor.fetchall()] == keys
    sample = fetch_analysis_sample(request_, SIX, AS_OF, conn)
    expected = {
        9_329_001: (None, None),
        9_329_002: (None, None),
        9_329_003: (25_000, 200),
        9_329_004: (925_000, 1_500),
        9_329_005: (25_000, 200),
    }
    assert [(r.original_list_price, r.living_area) for r in sample.rows] == [
        expected[k] for k in keys
    ]
    assert sample.eligible == len(keys)
