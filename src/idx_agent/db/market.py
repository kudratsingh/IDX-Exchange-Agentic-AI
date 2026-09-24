"""Closed-sale market aggregates: SQL builder plus executor (WO-008).

`build_market_sql` is pure: eight labelled statements over california_sold, each
naming only allowlisted columns, every value a bound parameter, each returning at
most a few summary rows. `fetch_market_aggregates` runs them, refuses any result
over MAX_ROWS rows, and maps them to a MarketAggregates of counts and middle values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from idx_agent.domain.market import (
    AREA_FLOOR,
    DEFAULT_SUBTYPE,
    EXCLUSION_RULES,
    PRICE_FLOOR,
    MarketAggregates,
    MonthAggregate,
    month_keys,
)
from idx_agent.safety.columns import check_column

if TYPE_CHECKING:
    from idx_agent.domain.asof import AsOfDates
    from idx_agent.domain.models import MarketStatsRequest, StatsWindow

__all__ = [
    "LABELS",
    "MAX_ROWS",
    "MIX_LIMIT",
    "MarketQuery",
    "RowCapExceeded",
    "build_market_sql",
    "fetch_market_aggregates",
]

Stmt = tuple[str, tuple[Any, ...]]

MAX_ROWS = 50
# At most this many other-subtype rows in the mix (the sold table holds 18 subtypes).
MIX_LIMIT = 20
# One statement per label, always in this order.
LABELS = ("count", "price", "dom", "ratio", "ppsf", "months", "mix", "exclusions")
_TABLE = "california_sold"
_MONTH_FORMAT = "%Y-%m"
# Rank 1 of each ListingKey is the kept sale; DaysOnMarket from 0 up is usable.
_KEEP_RANK = 1
_DOM_MIN = 0
# The one or two middle rows of an ordered sample of n, with rn counting from 1:
# lower middle FLOOR((n + 1) / 2), upper middle FLOOR(n / 2) + 1 (equal when n is odd).
_LOWER = "rn = FLOOR((n + %s) / %s)"
_LOWER_PARAMS = (1, 2)
_UPPER = "rn = FLOOR(n / %s) + %s"
_UPPER_PARAMS = (2, 1)
_FIVE_DIGITS = re.compile(r"[0-9]{5}")
# Role -> california_sold column; every name passes check_column when a query is built.
_COLUMNS = {
    "key": "ListingKey",
    "city": "City",
    "zip": "PostalCode",
    "close": "ClosePrice",
    "list": "ListPrice",
    "dom": "DaysOnMarket",
    "area": "LivingArea",
    "subtype": "PropertySubType",
    "close_d": "close_date_d",
    "contract_d": "purchase_contract_date_d",
}


class RowCapExceeded(RuntimeError):
    """A market statement returned more than MAX_ROWS rows; nothing is used."""


@dataclass(frozen=True)
class MarketQuery:
    """The built statements, as (sql, params) pairs, and a label naming each one."""

    statements: tuple[Stmt, ...]
    labels: tuple[str, ...] = LABELS

    def statement(self, label: str) -> Stmt:
        """Return the (sql, params) pair for one label (KeyError if unknown)."""
        if label not in self.labels:
            raise KeyError(label)
        return self.statements[self.labels.index(label)]


def _columns() -> dict[str, str]:
    """Every role's column after the california_sold allowlist check (ValueError)."""
    return {role: check_column(_TABLE, name) for role, name in _COLUMNS.items()}


def _geography(request: MarketStatsRequest, c: dict[str, str]) -> Stmt:
    """The place clause: City = %s, or a five-digit PostalCode prefix (ZIP+4 too)."""
    city, postal = request.city, request.postal_code
    if (city is None) == (postal is None):
        raise ValueError("set exactly one of city or postal_code")
    if city is not None:
        return f"{c['city']} = %s", (city,)
    if not _FIVE_DIGITS.fullmatch(str(postal)):
        raise ValueError("postal_code must be five digits")
    return f"{c['zip']} LIKE %s", (f"{postal}%",)


def _before_contract(c: dict[str, str]) -> str:
    """True when a sale closed before its contract date (a NULL contract is kept)."""
    return f"({c['contract_d']} IS NOT NULL AND {c['close_d']} < {c['contract_d']})"


def _sample(
    name: str,
    c: dict[str, str],
    geo: Stmt,
    window: StatsWindow,
    as_of: AsOfDates,
    subtype: str | None,
    extra: Stmt = ("", ()),
) -> Stmt:
    """CTEs `<name>_raw` (window rows after the row exclusions, ranked per ListingKey)
    and `<name>` (rank 1: latest close, then higher close, then higher list price).

    A NULL key is never a repeat. `subtype` None keeps every subtype (the mix).
    `extra` (WO-011 comps) adds bound predicates last; empty leaves the SQL as it was.
    """
    where = [
        geo[0],
        f"{c['close_d']} BETWEEN %s AND %s",  # a NULL close date never matches
        f"{c['close_d']} <= %s",  # never after the active as-of date
        f"NOT {_before_contract(c)}",
        f"{c['close']} >= %s",  # also drops NULL, zero, and negative prices
        f"{c['list']} >= %s",
    ]
    params: list[Any] = [
        _MONTH_FORMAT,
        *geo[1],
        window.start,
        window.end,
        as_of.active,
        PRICE_FLOOR,
        PRICE_FLOOR,
    ]
    if subtype is not None:
        where.append(f"{c['subtype']} = %s")
        params.append(subtype)
    if extra[0]:
        where.append(extra[0])
        params.extend(extra[1])
    raw = (
        f"{name}_raw AS (SELECT {c['close']} AS close_price, "
        f"{c['list']} AS list_price, {c['dom']} AS dom, {c['area']} AS area, "
        f"{c['subtype']} AS subtype, DATE_FORMAT({c['close_d']}, %s) AS ym, "
        f"{c['key']} IS NULL AS keyless, ROW_NUMBER() OVER (PARTITION BY {c['key']} "
        f"ORDER BY {c['close_d']} DESC, {c['close']} DESC, {c['list']} DESC) AS dup "
        f"FROM {_TABLE} WHERE {' AND '.join(where)})"
    )
    kept = (
        f"{name} AS (SELECT close_price, list_price, dom, area, subtype, ym "
        f"FROM {name}_raw WHERE dup = %s OR keyless)"
    )
    return f"{raw}, {kept}", (*params, _KEEP_RANK)


def _median(cte: Stmt, order: str, picks: Sequence[str], keep: Stmt = ("", ())) -> Stmt:
    """Order-statistics median over CTE `d`: n and each pick at the two middle rows.

    `order` sorts the sample; each pick (a column of `d`) is read at the lower
    (`lo_<pick>`) and upper (`hi_<pick>`) middle row. `keep` filters the sample.
    """
    where = f" WHERE {keep[0]}" if keep[0] else ""
    cols = ", ".join(picks)
    lower = ", ".join(f"MAX(CASE WHEN {_LOWER} THEN {p} END) AS lo_{p}" for p in picks)
    upper = ", ".join(f"MAX(CASE WHEN {_UPPER} THEN {p} END) AS hi_{p}" for p in picks)
    sql = (
        f"WITH {cte[0]}, o AS (SELECT {cols}, ROW_NUMBER() OVER (ORDER BY {order}) "
        f"AS rn, COUNT(*) OVER () AS n FROM d{where}) "
        f"SELECT MAX(n) AS n, {lower}, {upper} FROM o"
    )
    params = (
        *cte[1],
        *keep[1],
        *(_LOWER_PARAMS * len(picks)),
        *(_UPPER_PARAMS * len(picks)),
    )
    return sql, params


def _months(cte: Stmt) -> Stmt:
    """Per calendar month (close_date_d as YYYY-MM): count and the middle prices."""
    sql = (
        f"WITH {cte[0]}, o AS (SELECT ym, close_price, ROW_NUMBER() OVER "
        "(PARTITION BY ym ORDER BY close_price) AS rn, COUNT(*) OVER "
        "(PARTITION BY ym) AS n FROM d) "
        f"SELECT ym, MAX(n) AS n, MAX(CASE WHEN {_LOWER} THEN close_price END) "
        f"AS lo_close_price, MAX(CASE WHEN {_UPPER} THEN close_price END) "
        "AS hi_close_price FROM o GROUP BY ym ORDER BY ym"
    )
    return sql, (*cte[1], *_LOWER_PARAMS, *_UPPER_PARAMS)


def _mix(cte: Stmt, subtype: str) -> Stmt:
    """Sale counts of the other subtypes (NULL = unknown type) over CTE `m`."""
    sql = (
        f"WITH {cte[0]} SELECT subtype, COUNT(*) AS n FROM m "
        "WHERE subtype IS NULL OR subtype <> %s "
        "GROUP BY subtype ORDER BY n DESC, subtype LIMIT %s"
    )
    return sql, (*cte[1], subtype, MIX_LIMIT)


def _exclusions(
    cte: Stmt,
    c: dict[str, str],
    geo: Stmt,
    window: StatsWindow,
    as_of: AsOfDates,
    subtype: str,
) -> Stmt:
    """One row: a count per EXCLUSION_RULES name, same place and subtype.

    Rules are disjoint in this order, so the window rows with a readable date add
    up to close_before_contract + price_under_floor + duplicate_listing_key + sample.
    """
    in_window = f"{c['close_d']} BETWEEN %s AND %s AND {c['close_d']} <= %s"
    window_params = (window.start, window.end, as_of.active)
    bad_price = (
        f"({c['close']} IS NULL OR {c['close']} < %s "
        f"OR {c['list']} IS NULL OR {c['list']} < %s)"
    )
    base = (
        f"x AS (SELECT SUM({c['close_d']} > %s) AS after_active_asof, "
        f"SUM({c['close_d']} IS NULL) AS unreadable_close_date, "
        f"SUM({in_window} AND {_before_contract(c)}) AS close_before_contract, "
        f"SUM({in_window} AND NOT {_before_contract(c)} AND {bad_price}) "
        f"AS price_under_floor FROM {_TABLE} "
        f"WHERE {geo[0]} AND {c['subtype']} = %s)"
    )
    sql = (
        f"WITH {cte[0]}, {base} SELECT x.after_active_asof, x.unreadable_close_date, "
        "x.close_before_contract, x.price_under_floor, "
        "(SELECT COUNT(*) FROM d_raw WHERE NOT (dup = %s OR keyless)) "
        "AS duplicate_listing_key, "
        "(SELECT COUNT(*) FROM d WHERE area IS NULL OR area < %s) "
        "AS area_under_floor, "
        "(SELECT COUNT(*) FROM d WHERE dom IS NULL OR dom < %s) AS dom_missing FROM x"
    )
    params = (
        *cte[1],
        as_of.active,
        *window_params,
        *window_params,
        PRICE_FLOOR,
        PRICE_FLOOR,
        *geo[1],
        subtype,
        _KEEP_RANK,
        AREA_FLOOR,
        _DOM_MIN,
    )
    return sql, params


def build_market_sql(
    request: MarketStatsRequest, window: StatsWindow, as_of: AsOfDates
) -> MarketQuery:
    """Build the eight statements (LABELS order) without touching a database.

    Raises ValueError on a non-allowlisted column, a bad place, or a window that
    ends after the sold as-of date. No subtype means DEFAULT_SUBTYPE.
    """
    if window.end > as_of.sold or window.start > window.end:
        raise ValueError("the window must end on or before the sold as-of date")
    c = _columns()
    geo = _geography(request, c)
    subtype = request.property_subtype or DEFAULT_SUBTYPE
    d = _sample("d", c, geo, window, as_of, subtype)
    count = (
        f"WITH {d[0]} SELECT COUNT(*) AS sample_count, "
        "SUM(dom >= %s) AS dom_sample, SUM(area >= %s) AS ppsf_sample FROM d",
        (*d[1], _DOM_MIN, AREA_FLOOR),
    )
    statements = (
        count,
        _median(d, "close_price", ("close_price",)),
        _median(d, "dom", ("dom",), ("dom >= %s", (_DOM_MIN,))),
        _median(d, "close_price / list_price", ("close_price", "list_price")),
        _median(
            d,
            "close_price / area",
            ("close_price", "area"),
            ("area >= %s", (AREA_FLOOR,)),
        ),
        _months(d),
        _mix(_sample("m", c, geo, window, as_of, None), subtype),
        _exclusions(d, c, geo, window, as_of, subtype),
    )
    return MarketQuery(statements=statements)


def _run(conn: Any, label: str, stmt: Stmt) -> list[Mapping[str, Any]]:
    """Execute one statement (dict rows); RowCapExceeded if over MAX_ROWS rows."""
    with conn.cursor() as cursor:
        cursor.execute(stmt[0], stmt[1])
        rows = list(cursor.fetchall())
    if len(rows) > MAX_ROWS:
        raise RowCapExceeded(
            f"market statement {label!r} returned {len(rows)} rows; cap {MAX_ROWS}"
        )
    return rows


def _decimal(value: Any) -> Decimal:
    """Exact Decimal of a driver value; a double goes through its shortest repr."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _count(value: Any) -> int:
    """A COUNT or SUM result as an int; NULL (an empty SUM) is 0."""
    return int(value or 0)


def _middles(
    row: Mapping[str, Any], num: str, den: str | None = None
) -> tuple[Decimal, ...]:
    """The one (odd n) or two (even n) middle values of a median row, () when empty.

    With `den`, each middle is num / den of that row, divided in Decimal.
    """
    n = _count(row.get("n"))
    if n == 0:
        return ()
    ends = ("lo",) if n % 2 else ("lo", "hi")
    values = []
    for end in ends:
        value = _decimal(row[f"{end}_{num}"])
        if den is not None:
            value = value / _decimal(row[f"{end}_{den}"])
        values.append(value)
    return tuple(values)


def fetch_market_aggregates(
    request: MarketStatsRequest, window: StatsWindow, as_of: AsOfDates, conn: Any
) -> MarketAggregates:
    """Run `build_market_sql` on `conn` (dict-row cursors) and map to MarketAggregates.

    Every month the window touches is present (zero sales included); rows are never
    logged, and none carries a listing key, an address, or a per-sale value.
    """
    query = build_market_sql(request, window, as_of)
    rows = {
        label: _run(conn, label, stmt)
        for label, stmt in zip(query.labels, query.statements, strict=True)
    }
    count = rows["count"][0] if rows["count"] else {}
    one = {label: (rows[label][0] if rows[label] else {}) for label in LABELS[1:5]}
    by_month = {str(row["ym"]): row for row in rows["months"]}
    months = tuple(
        MonthAggregate(
            key=key,
            count=_count(by_month.get(key, {}).get("n")),
            price_middles=_middles(by_month.get(key, {}), "close_price"),
        )
        for key in month_keys(window)
    )
    exclusion_row = rows["exclusions"][0] if rows["exclusions"] else {}
    return MarketAggregates(
        sample_count=_count(count.get("sample_count")),
        price_middles=_middles(one["price"], "close_price"),
        dom_middles=_middles(one["dom"], "dom"),
        dom_sample=_count(count.get("dom_sample")),
        ratio_middles=_middles(one["ratio"], "close_price", "list_price"),
        ppsf_middles=_middles(one["ppsf"], "close_price", "area"),
        ppsf_sample=_count(count.get("ppsf_sample")),
        months=months,
        subtype_mix=tuple((row["subtype"], _count(row["n"])) for row in rows["mix"]),
        exclusions=tuple(
            (rule, _count(exclusion_row.get(rule))) for rule in EXCLUSION_RULES
        ),
    )
