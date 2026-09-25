"""Comparable closed sales for one subject: SQL builder plus executor (WO-011).

`build_comps_sql` is pure: WO-008's sample CTE (every exclusion, the duplicate-key
collapse, the floors, the window) with the subject's place, subtype, area band, and
bed band, then WO-008's price-per-sqft median. One summary row; never a per-sale row.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from idx_agent.db.market import (
    Stmt,
    _columns,
    _count,
    _decimal,
    _geography,
    _median,
    _middles,
    _run,
    _sample,
)
from idx_agent.domain.comps import (
    LEVELS,
    WINDOW_MONTHS,
    CompsAggregate,
    CompSubject,
    Level,
    area_band,
    bed_band,
    needs_widening,
    zip_area,
)
from idx_agent.domain.market import AREA_FLOOR
from idx_agent.domain.models import MarketStatsRequest
from idx_agent.safety.columns import check_column

if TYPE_CHECKING:
    from idx_agent.domain.asof import AsOfDates
    from idx_agent.domain.models import StatsWindow

__all__ = ["MAX_STATEMENTS", "build_comps_sql", "fetch_comps"]

# The ZIP statement, then the city statement only when the ZIP has too few.
MAX_STATEMENTS = len(LEVELS)
_TABLE = "california_sold"
_BEDS = "BedroomsTotal"  # a double in the sold table; bathrooms are never read
# The middle half's ends over the same ordered sample, with k = FLOOR(n / 4):
# rank k + 1 (`lo_q_*`) and rank n - k (`hi_q_*`); every number is bound.
_RANGE_RANKS: tuple[tuple[str, Stmt], ...] = (
    ("lo_q", ("rn = FLOOR(n / %s) + %s", (4, 1))),
    ("hi_q", ("rn = n - FLOOR(n / %s)", (4,))),
)


def _place(subject: CompSubject, level: Level) -> MarketStatsRequest:
    """The subject's city or five-digit ZIP as the place WO-008's `_geography` reads.

    Built without validation: the city is the listing's stored value, not user text.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown comps level {level!r}")
    city = subject.city if level == "city" else None
    postal = subject.postal_code if level == "postal_code" else None
    return MarketStatsRequest.model_construct(
        city=city,
        postal_code=postal,
        property_subtype=subject.subtype,
        months=WINDOW_MONTHS,
    )


def _bands(subject: CompSubject, c: dict[str, str]) -> Stmt:
    """LivingArea within 20% and BedroomsTotal within 1, inclusive, all bound."""
    area_low, area_high = area_band(subject.living_area)
    beds_low, beds_high = bed_band(subject.bedrooms)
    beds = check_column(_TABLE, _BEDS)
    return (
        f"{c['area']} BETWEEN %s AND %s AND {beds} BETWEEN %s AND %s",
        (area_low, area_high, beds_low, beds_high),
    )


def build_comps_sql(
    subject: CompSubject, level: Level, window: StatsWindow, as_of: AsOfDates
) -> Stmt:
    """Build one comps statement ("postal_code" or "city") without a database.

    Returns n and the close_price and area at the two middle rows and at the middle
    half's two ends, ordered by close_price / area over sales of at least 200 sqft.
    The window must be AsOfDates.window(6); else, or a bad level, ValueError.
    """
    if not isinstance(subject, CompSubject):
        raise TypeError("build_comps_sql needs a CompSubject")
    if window.months != WINDOW_MONTHS or (window.start, window.end) != as_of.window(
        WINDOW_MONTHS
    ):
        raise ValueError("the comps window is the six months to the sold as-of date")
    c = _columns()
    geo = _geography(_place(subject, level), c)
    sample = _sample("d", c, geo, window, as_of, subject.subtype, _bands(subject, c))
    return _median(
        sample,
        "close_price / area",
        ("close_price", "area"),
        ("area >= %s", (AREA_FLOOR,)),
        _RANGE_RANKS,
    )


def _range_ends(row: Mapping[str, Any]) -> tuple[Decimal, ...]:
    """The middle half's two ends as close_price / area in Decimal, () when empty."""
    if _count(row.get("n")) == 0:
        return ()
    return tuple(
        _decimal(row[f"{prefix}_close_price"]) / _decimal(row[f"{prefix}_area"])
        for prefix, _pred in _RANGE_RANKS
    )


def _aggregate(
    conn: Any, subject: CompSubject, level: Level, window: StatsWindow, as_of: AsOfDates
) -> CompsAggregate:
    """Run one level's statement (row cap checked) and map its one summary row."""
    rows = _run(conn, f"comps_{level}", build_comps_sql(subject, level, window, as_of))
    row = rows[0] if rows else {}
    zip_name = zip_area(subject.postal_code)
    return CompsAggregate(
        level=level,
        area=zip_name if level == "postal_code" else subject.city,
        count=_count(row.get("n")),
        middles=_middles(row, "close_price", "area") if row else (),
        widened_from=zip_name if level == "city" else None,
        range_ends=_range_ends(row) if row else (),
    )


def fetch_comps(
    subject: CompSubject, window: StatsWindow, as_of: AsOfDates, conn: Any
) -> CompsAggregate:
    """The ZIP comps, or the city comps when the ZIP has fewer than MIN_SAMPLE.

    At most two statements; the level returned is the one whose count is reported
    (the city once widened, even if still short). Rows are never logged.
    """
    first = _aggregate(conn, subject, "postal_code", window, as_of)
    if not needs_widening(first.count):
        return first
    return _aggregate(conn, subject, "city", window, as_of)
