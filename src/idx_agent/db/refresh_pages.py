"""Read-only keyset pages and aggregate counts for the refresh preflight (WO-021).

Each page names three allowlisted columns and returns at most 50 rows; the counts
return numbers only. Every value is bound. Nothing here writes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from idx_agent.db.listings import MAX_ROWS, SearchQuery
from idx_agent.domain.valid_values import ACTIVE_STATUS_COLUMN, ACTIVE_STATUS_VALUES
from idx_agent.safety.columns import check_column

__all__ = [
    "PAGE_ROWS",
    "build_inventory_counts_sql",
    "build_key_page_sql",
    "fetch_inventory_counts",
    "iter_listing_rows",
]

PAGE_ROWS = MAX_ROWS
_TABLE = "rets_property"
_KEY = check_column(_TABLE, "L_ListingID")
_MODIFIED = check_column(_TABLE, "ModificationTimestamp")
_COUNT_NAMES = (
    "total_rows",
    "listing_ids",
    "rows_without_key",
    "rows_without_timestamp",
    "active_ids",
)


def _status_column() -> str:
    if ACTIVE_STATUS_COLUMN is None or not ACTIVE_STATUS_VALUES:
        raise ValueError("no active status rule in valid_values")
    return check_column(_TABLE, ACTIVE_STATUS_COLUMN)


def build_key_page_sql(after: str, limit: int = PAGE_ROWS) -> SearchQuery:
    """One keyset page: key, change time and status of rows whose key is after `after`.

    The limit is bound and never above 50 rows.
    """
    if not isinstance(after, str) or not 1 <= int(limit) <= MAX_ROWS:
        raise ValueError(f"a page needs a text cursor and 1 to {MAX_ROWS} rows")
    columns = ", ".join((_KEY, _MODIFIED, _status_column()))
    sql = (
        f"SELECT {columns}\nFROM {_TABLE}\nWHERE {_KEY} > %s\nORDER BY {_KEY}\nLIMIT %s"
    )
    return SearchQuery(sql=sql, params=(after, int(limit)))


def build_inventory_counts_sql() -> SearchQuery:
    """Aggregate counts and the latest change time over the whole table; no row data."""
    status = _status_column()
    values = sorted(ACTIVE_STATUS_VALUES)
    marks = ", ".join(["%s"] * len(values))
    sql = (
        "SELECT COUNT(*) AS total_rows, "
        f"COUNT(DISTINCT {_KEY}) AS listing_ids, "
        f"COALESCE(SUM(CASE WHEN {_KEY} IS NULL THEN 1 ELSE 0 END), 0) "
        "AS rows_without_key, "
        f"COALESCE(SUM(CASE WHEN {_MODIFIED} IS NULL THEN 1 ELSE 0 END), 0) "
        "AS rows_without_timestamp, "
        f"COUNT(DISTINCT CASE WHEN {status} IN ({marks}) THEN {_KEY} END) "
        "AS active_ids, "
        f"CAST(MAX({_MODIFIED}) AS CHAR) AS max_modified\n"
        f"FROM {_TABLE}"
    )
    return SearchQuery(sql=sql, params=tuple(values))


def fetch_inventory_counts(conn: Any) -> dict[str, Any]:
    """Run `build_inventory_counts_sql`: integer counts plus `max_modified` as text."""
    query = build_inventory_counts_sql()
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("the count statement must return one row")
    row = rows[0]
    names = (*_COUNT_NAMES, "max_modified")
    values = (
        dict(row) if isinstance(row, Mapping) else dict(zip(names, row, strict=True))
    )
    counts: dict[str, Any] = {name: int(values[name] or 0) for name in _COUNT_NAMES}
    mx = values["max_modified"]
    counts["max_modified"] = None if mx is None else str(mx)
    return counts


def _page(conn: Any, after: str, limit: int) -> list[tuple[Any, Any, Any]]:
    query = build_key_page_sql(after, limit)
    with conn.cursor() as cursor:
        cursor.execute(query.sql, query.params)
        rows = cursor.fetchall()
    if len(rows) > limit:
        raise ValueError(f"a page returned more than {limit} rows")
    status = _status_column()
    return [
        (r[_KEY], r[_MODIFIED], r[status]) if isinstance(r, Mapping) else tuple(r)
        for r in rows
    ]


def iter_listing_rows(
    conn: Any, limit: int = PAGE_ROWS
) -> Iterator[tuple[str, Any, Any]]:
    """Yield (key, modified, status) for every keyed row, page by page, in key order.

    A full page holds back its last key, which the next page re-reads whole; a key
    filling a page, or keys out of order, raise ValueError (the scan is not trusted).
    """
    after = ""
    while True:
        rows = _page(conn, after, limit)
        full = len(rows) == limit
        if full:
            last = rows[-1][0]
            rows = [row for row in rows if row[0] != last]
            if not rows:
                raise ValueError("a listing ID fills a whole page")
        previous = after
        for row in rows:
            key = row[0]
            if not isinstance(key, str) or key <= after or key < previous:
                raise ValueError("the page scan returned keys out of order")
            previous = key
            yield row
        if not full:
            return
        after = previous
