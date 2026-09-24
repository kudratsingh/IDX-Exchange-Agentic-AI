"""Unit tests for db/comps.py (WO-011); no database.

The builder is checked as (sql, params) over every statement it can emit: bound
values only, allowlisted columns only, no bathroom, county, or agent column, each
WO-008 exclusion present. The executor runs on a fake connection: the level rule.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Any

import pytest

from idx_agent.db.comps import MAX_STATEMENTS, build_comps_sql, fetch_comps
from idx_agent.db.market import MAX_ROWS, RowCapExceeded
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.comps import (
    LEVELS,
    CompsAggregate,
    CompSubject,
    Uncheckable,
    comps_window,
)
from idx_agent.domain.market import AREA_FLOOR, PRICE_FLOOR
from idx_agent.domain.models import StatsWindow
from idx_agent.safety.columns import AGENT_CONTACT, ALLOWLIST, DENYLIST

AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SIX = comps_window(AS_OF)
# SQL words, functions, CTE names, and aliases the builder may emit besides columns.
_SQL_WORDS = {
    *"WITH AS SELECT FROM WHERE AND OR NOT IS NULL IN BETWEEN LIKE".split(),
    *"ROW_NUMBER OVER PARTITION BY ORDER DESC COUNT MAX CASE WHEN THEN".split(),
    *"END FLOOR DATE_FORMAT".split(),
    "california_sold",
    "s",  # from the %s placeholders
    *"d d_raw o rn n dup keyless ym".split(),
    *"close_price list_price dom area subtype".split(),
    *"lo_close_price hi_close_price lo_area hi_area".split(),
}
_BATH_COLUMNS = ("LM_Dec_3", "BathroomsTotalInteger")


def subject(**overrides: Any) -> CompSubject:
    """An invented Monrovia single-family subject: 1,700 sqft, 3 beds, 850,000."""
    values = {
        "city": "Monrovia",
        "postal_code": "91016",
        "subtype": "SingleFamilyResidence",
        "living_area": 1700,
        "bedrooms": 3,
        "list_price": 850_000,
    }
    return CompSubject(**(values | overrides))


def every_statement() -> list[tuple[str, tuple[Any, ...]]]:
    """Every statement shape the builder emits: both levels, beds 0/1/5, subtypes."""
    subjects = [
        subject(),
        subject(bedrooms=0, living_area=200),
        subject(bedrooms=1, subtype="Condominium"),
        subject(bedrooms=5, living_area=4321),
    ]
    return [
        build_comps_sql(s, level, SIX, AS_OF) for s, level in product(subjects, LEVELS)
    ]


# --- build_comps_sql ---


def test_every_value_is_a_bound_parameter():
    """One %s per param, no quoted literal, and no number written into the SQL."""
    for sql, params in every_statement():
        assert sql.count("%s") == len(params)
        assert "'" not in sql and '"' not in sql
        assert not re.search(r"(?<![A-Za-z_])[0-9]", sql), sql
        assert "SELECT *" not in sql and ".*" not in sql


def test_every_identifier_is_allowlisted():
    for sql, _params in every_statement():
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)) - _SQL_WORDS
        assert names <= ALLOWLIST["california_sold"], (
            names - ALLOWLIST["california_sold"]
        )


def test_no_bathroom_county_or_agent_column_in_any_statement():
    for sql, _params in every_statement():
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))
        assert not words & (AGENT_CONTACT | DENYLIST)
        assert not any(bath in sql for bath in _BATH_COLUMNS)
        assert "County" not in sql and "county" not in sql.lower()


def test_no_statement_returns_a_key_an_address_or_a_per_sale_row():
    """The outer SELECT is one aggregate row: n and the middle rows' two values."""
    for sql, _params in every_statement():
        assert "UnparsedAddress" not in sql
        outer = sql.rsplit(") SELECT ", 1)[-1]
        assert outer == (
            "MAX(n) AS n, "
            "MAX(CASE WHEN rn = FLOOR((n + %s) / %s) THEN close_price END) "
            "AS lo_close_price, "
            "MAX(CASE WHEN rn = FLOOR((n + %s) / %s) THEN area END) AS lo_area, "
            "MAX(CASE WHEN rn = FLOOR(n / %s) + %s THEN close_price END) "
            "AS hi_close_price, "
            "MAX(CASE WHEN rn = FLOOR(n / %s) + %s THEN area END) AS hi_area FROM o"
        )


def test_the_city_statement_matches_the_city_and_binds_every_band():
    sql, params = build_comps_sql(subject(), "city", SIX, AS_OF)
    assert "WHERE City = %s AND " in sql and "PostalCode" not in sql
    assert (
        "PropertySubType = %s AND LivingArea BETWEEN %s AND %s "
        "AND BedroomsTotal BETWEEN %s AND %s)"
    ) in sql
    # 0.8 x 1700 = 1360, 1.2 x 1700 = 2040; beds 3 - 1 to 3 + 1.
    assert params[:12] == (
        "%Y-%m",
        "Monrovia",
        SIX.start,
        SIX.end,
        AS_OF.active,
        PRICE_FLOOR,
        PRICE_FLOOR,
        "SingleFamilyResidence",
        Decimal("1360.0"),
        Decimal("2040.0"),
        2,
        4,
    )
    assert params[12:] == (1, AREA_FLOOR, 1, 2, 1, 2, 2, 1, 2, 1)


def test_the_zip_statement_is_a_five_digit_prefix():
    sql, params = build_comps_sql(subject(), "postal_code", SIX, AS_OF)
    assert "WHERE PostalCode LIKE %s AND " in sql and "City = %s" not in sql
    assert params[1] == "91016%" and "Monrovia" not in params


def test_the_bed_band_floors_at_zero():
    _sql, params = build_comps_sql(subject(bedrooms=0), "city", SIX, AS_OF)
    assert params[10:12] == (0, 1)


def test_the_median_orders_by_price_per_sqft_over_the_area_floor():
    sql, _params = build_comps_sql(subject(), "city", SIX, AS_OF)
    assert "ROW_NUMBER() OVER (ORDER BY close_price / area) AS rn" in sql
    assert "COUNT(*) OVER () AS n FROM d WHERE area >= %s)" in sql


def test_each_wo008_exclusion_is_in_the_sample():
    for sql, _params in every_statement():
        assert "close_date_d BETWEEN %s AND %s" in sql  # the window
        assert "close_date_d <= %s" in sql  # never after the active as-of date
        assert (
            "NOT (purchase_contract_date_d IS NOT NULL "
            "AND close_date_d < purchase_contract_date_d)"
        ) in sql
        assert "ClosePrice >= %s" in sql and "ListPrice >= %s" in sql
        assert (
            "ROW_NUMBER() OVER (PARTITION BY ListingKey ORDER BY close_date_d DESC, "
            "ClosePrice DESC, ListPrice DESC) AS dup"
        ) in sql
        assert "WHERE dup = %s OR keyless" in sql
        assert "FROM d WHERE area >= %s" in sql


def test_injection_text_stays_in_params():
    evil = "Monrovia' OR '1'='1'; DROP TABLE california_sold; --"
    s = subject(city=evil, subtype="x' OR 1=1 --")
    for level in LEVELS:
        sql, params = build_comps_sql(s, level, SIX, AS_OF)
        assert "DROP" not in sql and "OR 1=1" not in sql
        assert "x' OR 1=1 --" in params
    assert evil in build_comps_sql(s, "city", SIX, AS_OF)[1]


@pytest.mark.parametrize(
    "window",
    [
        StatsWindow(start=date(2026, 8, 18), end=date(2026, 9, 17), months=1),
        StatsWindow(start=date(2026, 3, 25), end=date(2026, 9, 24), months=6),
        StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 16), months=6),
    ],
)
def test_only_the_six_months_to_the_sold_asof_date(window):
    with pytest.raises(ValueError, match="six months"):
        build_comps_sql(subject(), "city", window, AS_OF)


def test_an_unknown_level_raises():
    with pytest.raises(ValueError, match="level"):
        build_comps_sql(subject(), "county", SIX, AS_OF)


def test_a_not_checkable_subject_is_refused():
    with pytest.raises(TypeError):
        build_comps_sql(Uncheckable("bedrooms"), "city", SIX, AS_OF)  # type: ignore[arg-type]


def test_the_bed_column_dropped_from_the_allowlist_raises(monkeypatch):
    shrunk = ALLOWLIST["california_sold"] - {"BedroomsTotal"}
    monkeypatch.setitem(ALLOWLIST, "california_sold", shrunk)
    with pytest.raises(ValueError, match="BedroomsTotal"):
        build_comps_sql(subject(), "city", SIX, AS_OF)


# --- fetch_comps on a fake connection ---


class FakeConnection:
    """Returns queued rows per level (by the statement's place clause)."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._level = ""

    def cursor(self) -> FakeConnection:
        return self

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, tuple(params)))
        self._level = "postal_code" if "PostalCode LIKE" in sql else "city"

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows.get(self._level, []))


def row(n: int | None, *pairs: tuple[float, float]) -> list[dict[str, Any]]:
    """One summary row: n, then the lower and upper middle (close, area) pairs."""
    lo = pairs[0] if pairs else (None, None)
    hi = pairs[-1] if pairs else (None, None)
    return [
        {
            "n": n,
            "lo_close_price": lo[0],
            "lo_area": lo[1],
            "hi_close_price": hi[0],
            "hi_area": hi[1],
        }
    ]


def test_enough_city_comps_run_one_statement():
    # 5 comps; middle 850,000 / 1,700 = 500.
    conn = FakeConnection({"city": row(5, (850_000.0, 1700.0))})
    result = fetch_comps(subject(), SIX, AS_OF, conn)
    assert result == CompsAggregate("city", "Monrovia", 5, (Decimal(500),), None)
    assert len(conn.executed) == 1
    assert conn.executed[0] == build_comps_sql(subject(), "city", SIX, AS_OF)


def test_too_few_city_comps_widen_to_the_zip():
    # City 4; ZIP 6 with middles 816,000 / 1,700 = 480 and 884,000 / 1,700 = 520.
    conn = FakeConnection(
        {
            "city": row(4, (816_000.0, 1700.0), (884_000.0, 1700.0)),
            "postal_code": row(6, (816_000.0, 1700.0), (884_000.0, 1700.0)),
        }
    )
    result = fetch_comps(subject(), SIX, AS_OF, conn)
    assert result == CompsAggregate(
        "postal_code", "91016", 6, (Decimal(480), Decimal(520)), "Monrovia"
    )
    assert len(conn.executed) == 2 == MAX_STATEMENTS
    assert conn.executed[1] == build_comps_sql(subject(), "postal_code", SIX, AS_OF)


def test_the_zip_level_is_reported_even_when_still_short():
    conn = FakeConnection({"city": row(0), "postal_code": row(3, (850_000.0, 1700.0))})
    result = fetch_comps(subject(), SIX, AS_OF, conn)
    assert (result.level, result.count, result.widened_from) == (
        "postal_code",
        3,
        "Monrovia",
    )


def test_an_empty_or_missing_row_is_zero_comps():
    for rows in ({"city": row(None)}, {}):
        conn = FakeConnection(rows | {"postal_code": row(None)})
        result = fetch_comps(subject(), SIX, AS_OF, conn)
        assert (result.count, result.middles) == (0, ())


def test_a_statement_over_the_row_cap_raises():
    conn = FakeConnection({"city": row(5, (850_000.0, 1700.0)) * (MAX_ROWS + 1)})
    with pytest.raises(RowCapExceeded, match="comps_city"):
        fetch_comps(subject(), SIX, AS_OF, conn)
