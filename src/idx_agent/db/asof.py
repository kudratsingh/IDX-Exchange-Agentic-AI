"""Read the as-of dates (WO-004) and the earliest close date (WO-008) once per process.

Definitions from docs/data/schema_notes.md section 3: active = the latest
ModificationTimestamp date in rets_property; sold = the latest close date in
california_sold that is not after the active date (drops typo years like 2072).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from idx_agent.domain.asof import AsOfDates
from idx_agent.safety.columns import check_column

__all__ = [
    "clear_asof_cache",
    "get_asof_dates",
    "get_earliest_close",
    "read_asof_dates",
    "read_earliest_close",
]

# Column names pass the allowlist once, at import; the SQL below is fixed text.
_ACTIVE_COLUMN = check_column("rets_property", "ModificationTimestamp")
_SOLD_COLUMN = check_column("california_sold", "close_date_d")

# MAX is cast to text so a zero or odd date comes back as a string, not a driver
# error; the first ten characters are parsed in Python.
_ACTIVE_SQL = (
    f"SELECT CAST(MAX({_ACTIVE_COLUMN}) AS CHAR) AS active_max FROM rets_property"
)
_SOLD_SQL = (
    f"SELECT CAST(MAX({_SOLD_COLUMN}) AS CHAR) AS sold_max "
    f"FROM california_sold WHERE {_SOLD_COLUMN} <= %s"
)
# WO-008: the earliest valid close date (never after the active as-of date), the
# start of the data's coverage for the market window fallback.
_EARLIEST_SQL = (
    f"SELECT CAST(MIN({_SOLD_COLUMN}) AS CHAR) AS sold_min "
    f"FROM california_sold WHERE {_SOLD_COLUMN} <= %s"
)

# The dates read by the first get_asof_dates call; None until then.
_cached: AsOfDates | None = None
# The earliest close date read by the first get_earliest_close call; None until then.
_cached_earliest: date | None = None


def _to_day(value: Any, label: str) -> date:
    """Return a date from a date, datetime, or text starting YYYY-MM-DD.

    Raises RuntimeError naming `label` when the value is missing or unusable
    (for example a zero date), since no window can be counted from it.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise RuntimeError(f"no usable {label} as-of date in the data") from None


def _scalar(conn: Any, sql: str, params: tuple[Any, ...], key: str) -> Any:
    """Run a one-row query and return column `key` of that row (None if no row)."""
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return None if row is None else row[key]


def read_asof_dates(conn: Any) -> AsOfDates:
    """Query both tables for their as-of dates; no caching.

    `conn` is a connection whose cursors return dict rows (see pool.connect).
    Raises RuntimeError if either date cannot be read.
    """
    active = _to_day(_scalar(conn, _ACTIVE_SQL, (), "active_max"), "active")
    sold = _to_day(_scalar(conn, _SOLD_SQL, (active,), "sold_max"), "sold")
    return AsOfDates(sold=sold, active=active)


def get_asof_dates(conn: Any) -> AsOfDates:
    """Return the cached as-of dates, reading them through `conn` the first time."""
    global _cached
    if _cached is None:
        _cached = read_asof_dates(conn)
    return _cached


def read_earliest_close(conn: Any, active: date) -> date:
    """Query the earliest close date on or before `active`; no caching.

    MIN ignores a NULL close date. Raises RuntimeError if none is usable.
    """
    return _to_day(_scalar(conn, _EARLIEST_SQL, (active,), "sold_min"), "earliest")


def get_earliest_close(conn: Any) -> date:
    """Return the cached earliest valid close date, reading it the first time.

    Bounded by the (cached) active as-of date, as the sold as-of date is (WO-008).
    """
    global _cached_earliest
    if _cached_earliest is None:
        active = get_asof_dates(conn).active
        _cached_earliest = read_earliest_close(conn, active)
    return _cached_earliest


def clear_asof_cache() -> None:
    """Forget the cached as-of and earliest close dates, so both read again (tests)."""
    global _cached, _cached_earliest
    _cached = None
    _cached_earliest = None
