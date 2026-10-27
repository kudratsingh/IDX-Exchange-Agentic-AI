"""WO-017 analysis reader: one fixed, bounded projection of cleaned closed sales.

`build_analysis_sql` is pure: WO-008's exclusions (`market._filters`), keyed rows,
one per ListingKey, allowlisted columns, newest first, LIMIT 50 bound, a deadline.
`fetch_analysis_sample` runs it into `make_analysis_sample`; rows are never logged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import pymysql

from idx_agent.db.market import (
    RowCapExceeded,
    Stmt,
    _columns,
    _filters,
    _geography,
)
from idx_agent.domain.analysis import (
    ANALYSIS_MAX_ROWS,
    AnalysisSample,
    make_analysis_sample,
)
from idx_agent.domain.fieldmap import to_sold_comp
from idx_agent.domain.market import DEFAULT_SUBTYPE
from idx_agent.safety.columns import check_column

if TYPE_CHECKING:
    from idx_agent.domain.asof import AsOfDates
    from idx_agent.domain.models import MarketStatsRequest, StatsWindow

__all__ = [
    "DEADLINE_MS",
    "AnalysisDeadlineExceeded",
    "build_analysis_sql",
    "fetch_analysis_sample",
]

# MySQL stops the statement after this many milliseconds (optimizer hint, server side).
DEADLINE_MS = 2000
# Only valid right after the top-level SELECT; MySQL warns (3125) and ignores it
# anywhere else, which the fixture integration test checks.
_HINT = f"/*+ MAX_EXECUTION_TIME({DEADLINE_MS:d}) */"
_TABLE = "california_sold"
_KEEP_RANK = 1
# MySQL error raised when MAX_EXECUTION_TIME interrupts a statement.
_ER_QUERY_TIMEOUT = 3024
# The fixed projection, in output order; nothing else is selected.
_PROJECTION = (
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
)


class AnalysisDeadlineExceeded(RuntimeError):
    """The analysis statement ran past DEADLINE_MS; nothing is returned."""


def build_analysis_sql(
    request: MarketStatsRequest, window: StatsWindow, as_of: AsOfDates
) -> Stmt:
    """Build the one analysis statement without touching a database.

    The window must be `as_of.window(request.months)`; a bad place, a column off
    the allowlist or another window raises ValueError. No subtype: the default.
    """
    if window.months != request.months or (window.start, window.end) != as_of.window(
        request.months
    ):
        raise ValueError("the analysis window must count back from the sold as-of")
    c = _columns()
    cols = [check_column(_TABLE, name) for name in _PROJECTION]
    key, close_d = c["key"], c["close_d"]
    subtype = request.property_subtype or DEFAULT_SUBTYPE
    keyed = (f"{key} IS NOT NULL", ())  # duplicate refusal needs a key
    where, params = _filters(c, _geography(request, c), window, as_of, subtype, keyed)
    listed = ", ".join(cols)
    sql = (
        f"WITH a AS (SELECT {listed}, ROW_NUMBER() OVER (PARTITION BY {key} "
        f"ORDER BY {close_d} DESC, {c['close']} DESC, {c['list']} DESC) AS dup "
        f"FROM {_TABLE} WHERE {' AND '.join(where)}) "
        f"SELECT {_HINT} {listed}, "
        "COUNT(*) OVER () AS eligible FROM a WHERE dup = %s "
        f"ORDER BY {close_d} DESC, {key} DESC LIMIT %s"
    )
    return sql, (*params, _KEEP_RANK, ANALYSIS_MAX_ROWS)


def _run(conn: Any, stmt: Stmt) -> list[Mapping[str, Any]]:
    """Execute (dict rows); deadline and over-cap results raise, values unechoed."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(stmt[0], stmt[1])
            rows = list(cursor.fetchall())
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == _ER_QUERY_TIMEOUT:
            raise AnalysisDeadlineExceeded(
                f"analysis statement exceeded {DEADLINE_MS} ms"
            ) from None
        raise
    if len(rows) > ANALYSIS_MAX_ROWS:
        raise RowCapExceeded(
            f"analysis statement returned {len(rows)} rows; cap {ANALYSIS_MAX_ROWS}"
        )
    return rows


def fetch_analysis_sample(
    request: MarketStatsRequest, window: StatsWindow, as_of: AsOfDates, conn: Any
) -> AnalysisSample:
    """Run `build_analysis_sql` on `conn` and return the validated numeric sample.

    Rows keep the statement's order; `eligible` counts every kept sale before
    the cap. Each row goes through `to_sold_comp`; nothing is logged.
    """
    rows = _run(conn, build_analysis_sql(request, window, as_of))
    eligible = int(rows[0]["eligible"]) if rows else 0
    comps = [to_sold_comp(row) for row in rows]
    return make_analysis_sample(comps, request, window, as_of, eligible=eligible)
