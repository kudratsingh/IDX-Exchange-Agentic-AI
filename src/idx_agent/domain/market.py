"""Market math for get_market_stats (WO-008): pure code, no database, no clock.

The db layer returns the one or two middle values of each ordered sample
(MarketAggregates); this module averages them in Decimal, rounds once at the
end, applies the minimum-sample rule and the fixed labels, and builds MarketStats.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.models import (
    MarketStats,
    MarketStatsRequest,
    MonthRow,
    StatsWindow,
)

__all__ = [
    "AREA_FLOOR",
    "DEFAULT_SUBTYPE",
    "EXCLUSION_RULES",
    "MIN_SAMPLE",
    "MONTH_MIN",
    "PRICE_FLOOR",
    "MarketAggregates",
    "MonthAggregate",
    "build_market_stats",
    "coverage_months",
    "dom_band",
    "exclusion_warnings",
    "market_lean",
    "median",
    "median_from_middles",
    "month_keys",
    "round_dollars",
    "round_ratio",
    "sale_to_list_reading",
]

MIN_SAMPLE = 5  # sales needed for figures; below it one sale moves the median
MONTH_MIN = 3  # sales needed to show a month's median
PRICE_FLOOR = 25_000  # ClosePrice and ListPrice under this are excluded
AREA_FLOOR = 200  # LivingArea under this leaves the price-per-sqft median only
# A request without a subtype is benchmarked on single-family sales (DECISIONS.md).
DEFAULT_SUBTYPE = "SingleFamilyResidence"
# One entry per rule, in this order, in MarketStats.exclusions_applied.
EXCLUSION_RULES: tuple[str, ...] = (
    "after_active_asof",
    "unreadable_close_date",
    "close_before_contract",
    "price_under_floor",
    "duplicate_listing_key",
    "area_under_floor",
    "dom_missing",
)
# Plain words for a non-zero exclusion count; "{n}" is the count.
_EXCLUSION_WORDS: dict[str, str] = {
    "after_active_asof": "{n} sale(s) dated after the data's as-of date were left out",
    "unreadable_close_date": "{n} sale(s) with an unreadable close date were left out",
    "close_before_contract": (
        "{n} sale(s) closing before their contract date were left out"
    ),
    "price_under_floor": (
        "{n} sale(s) with a close or list price under $25,000 were left out"
    ),
    "duplicate_listing_key": (
        "{n} repeated sale record(s) were counted once, at the latest close"
    ),
    "area_under_floor": (
        "{n} sale(s) with living area under 200 sqft or missing were left out "
        "of the price per sqft median only"
    ),
    "dom_missing": (
        "{n} sale(s) without days on market were left out "
        "of the days-on-market median only"
    ),
}
_ONE = Decimal(1)
_RATIO_PLACES = Decimal("0.001")
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class MonthAggregate:
    """One calendar month of the sample: key "YYYY-MM", sale count, middle prices.

    `price_middles` holds the one (odd count) or two (even count) middle close
    prices, and is () when the month has no sales.
    """

    key: str
    count: int
    price_middles: tuple[Decimal, ...]


@dataclass(frozen=True)
class MarketAggregates:
    """Everything the SQL returns for one request: counts and middle values only.

    Middles are 1 or 2 values per metric, () when that metric's sample is empty.
    `subtype_mix` counts other subtypes (None = unknown type); `exclusions` has
    one (rule, count) per EXCLUSION_RULES name. No row-level data lives here.
    """

    sample_count: int
    price_middles: tuple[Decimal, ...]
    dom_middles: tuple[Decimal, ...]
    dom_sample: int
    ratio_middles: tuple[Decimal, ...]
    ppsf_middles: tuple[Decimal, ...]
    ppsf_sample: int
    months: tuple[MonthAggregate, ...]
    subtype_mix: tuple[tuple[str | None, int], ...]
    exclusions: tuple[tuple[str, int], ...]


def _dec(value: Decimal | int | float | str) -> Decimal:
    """Convert to Decimal exactly as written; floats go through their shortest repr.

    Decimal(str(0.1)) is 0.1, whereas Decimal(0.1) carries binary noise.
    """
    if isinstance(value, bool):
        raise TypeError("a boolean is not a number here")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def median(values: Iterable[Decimal | int | float | str]) -> Decimal:
    """Reference median over a plain list, exact in Decimal (for tests and evals).

    Odd count: the middle value; even: the two middles averaged. Empty raises.
    """
    ordered = sorted(_dec(v) for v in values)
    if not ordered:
        raise ValueError("median of an empty sample")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def median_from_middles(
    middles: Sequence[Decimal | int | float | str],
) -> Decimal | None:
    """Median from the SQL middle values: one is the median, two are averaged.

    () means an empty sample and returns None; more than two raises.
    """
    if len(middles) == 0:
        return None
    if len(middles) == 1:
        return _dec(middles[0])
    if len(middles) == 2:
        return (_dec(middles[0]) + _dec(middles[1])) / 2
    raise ValueError("a median has one or two middle values")


def round_dollars(value: Decimal | int | float | str) -> int:
    """Round to whole dollars, half-even (100000.5 -> 100000, 100001.5 -> 100002)."""
    return int(_dec(value).quantize(_ONE, rounding=ROUND_HALF_EVEN))


def round_ratio(value: Decimal | int | float | str) -> Decimal:
    """Round a sale-to-list ratio half-even to 3 decimals (1.0325 -> 1.032)."""
    return _dec(value).quantize(_RATIO_PLACES, rounding=ROUND_HALF_EVEN)


def sale_to_list_reading(ratio: Decimal | int | float | str) -> str:
    """Plain reading of the ratio, rounded to 3 decimals first: "3% over asking".

    The difference from 1 in whole percent, half-even: 0 -> "at asking",
    above -> "N% over asking", below -> "N% under asking".
    """
    pct = ((round_ratio(ratio) - _ONE) * _HUNDRED).quantize(
        _ONE, rounding=ROUND_HALF_EVEN
    )
    if pct == 0:
        return "at asking"
    if pct > 0:
        return f"{pct}% over asking"
    return f"{-pct}% under asking"


def dom_band(
    median_dom: Decimal | int | float | str,
) -> Literal["very_low", "low", "average", "high"]:
    """Band for the median days on market: <15, 15 to <30, 30 to <60, 60 and over."""
    days = _dec(median_dom)
    if days < 15:
        return "very_low"
    if days < 30:
        return "low"
    if days < 60:
        return "average"
    return "high"


def market_lean(
    ratio: Decimal | int | float | str, median_dom: Decimal | int | float | str
) -> Literal["seller", "buyer", "balanced"]:
    """Lean from the ratio (rounded to 3 decimals) and median days, in this order.

    seller: ratio >= 1.000 and days < 30; else buyer: ratio < 0.980 or
    days >= 60; else balanced.
    """
    rounded = round_ratio(ratio)
    days = _dec(median_dom)
    if rounded >= Decimal("1.000") and days < 30:
        return "seller"
    if rounded < Decimal("0.980") or days >= 60:
        return "buyer"
    return "balanced"


def month_keys(window: StatsWindow) -> tuple[str, ...]:
    """Every calendar month the window touches, oldest first, as "YYYY-MM".

    A window from 2025-12-18 to 2026-02-03 gives 2025-12, 2026-01, 2026-02.
    """
    first = window.start.year * 12 + window.start.month - 1
    last = window.end.year * 12 + window.end.month - 1
    return tuple(f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(first, last + 1))


def coverage_months(earliest: date, sold_asof: date) -> int:
    """Fewest months whose window, counted back from `sold_asof`, reaches `earliest`.

    Used when a requested window would start before the earliest valid close
    date: the tool then uses start=earliest and this month count.
    """
    if earliest > sold_asof:
        raise ValueError("earliest close date is after the sold as-of date")
    as_of = AsOfDates(sold=sold_asof, active=sold_asof)
    months = 1
    while as_of.window(months)[0] > earliest:
        months += 1
    return months


def exclusion_warnings(exclusions: Iterable[tuple[str, int]]) -> list[str]:
    """One plain sentence per non-zero exclusion count, in EXCLUSION_RULES order."""
    counts = _exclusion_counts(exclusions)
    return [
        _EXCLUSION_WORDS[name].format(n=counts[name])
        for name in EXCLUSION_RULES
        if counts[name] > 0
    ]


def _exclusion_counts(exclusions: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Map rule -> count; refuses unknown, repeated, missing, or negative entries."""
    counts: dict[str, int] = {}
    for name, count in exclusions:
        if name not in EXCLUSION_RULES or name in counts:
            raise ValueError(f"unexpected exclusion entry {name!r}")
        if count < 0:
            raise ValueError(f"negative count for exclusion {name!r}")
        counts[name] = count
    missing = [name for name in EXCLUSION_RULES if name not in counts]
    if missing:
        raise ValueError(f"exclusion counts missing for {missing}")
    return counts


def _checked_median(middles: Sequence[Decimal], sample: int, what: str) -> Decimal:
    """Median from middles after checking their number fits a non-empty sample.

    An odd sample has one middle and an even one two; anything else raises.
    """
    expected = 1 if sample % 2 else 2
    if sample <= 0 or len(middles) != expected:
        raise ValueError(f"{what}: {len(middles)} middles for a sample of {sample}")
    result = median_from_middles(middles)
    if result is None:  # unreachable: middles is non-empty here
        raise ValueError(f"{what}: no median")
    return result


def _trend(aggregates: MarketAggregates, window: StatsWindow) -> list[MonthRow]:
    """One MonthRow per month the window touches; months under MONTH_MIN get no median.

    A month the SQL did not return has zero sales; a month outside the window raises.
    """
    keys = month_keys(window)
    by_key: dict[str, MonthAggregate] = {}
    for month in aggregates.months:
        if month.key not in keys or month.key in by_key:
            raise ValueError(f"month {month.key!r} is outside the window or repeated")
        by_key[month.key] = month
    if sum(m.count for m in by_key.values()) != aggregates.sample_count:
        raise ValueError("month counts do not add up to the sample count")
    rows = []
    for key in keys:
        month = by_key.get(key, MonthAggregate(key=key, count=0, price_middles=()))
        price = None
        if month.count >= MONTH_MIN:
            middle = _checked_median(month.price_middles, month.count, key)
            price = float(round_dollars(middle))
        rows.append(
            MonthRow(month=key, sample_count=month.count, median_close_price=price)
        )
    return rows


def build_market_stats(
    aggregates: MarketAggregates,
    request: MarketStatsRequest,
    window: StatsWindow,
    as_of: AsOfDates,
    warnings: list[str] | None = None,
) -> MarketStats:
    """Turn the SQL aggregates into MarketStats; rounding happens once, here.

    Under MIN_SAMPLE: low_sample, figures and readings None, empty trend. Every
    exclusion is listed as "rule: count"; if `warnings` is a list, one plain
    sentence per non-zero exclusion is appended to it.
    """
    counts = _exclusion_counts(aggregates.exclusions)
    exclusions = [f"{name}: {counts[name]}" for name in EXCLUSION_RULES]
    if warnings is not None:
        warnings.extend(exclusion_warnings(aggregates.exclusions))
    common = {
        "geography": request.geography(),
        "property_subtype": request.property_subtype or DEFAULT_SUBTYPE,
        "window": window,
        "as_of": as_of.sold,
        "sample_count": aggregates.sample_count,
        "exclusions_applied": exclusions,
    }
    if aggregates.sample_count < MIN_SAMPLE:
        return MarketStats(low_sample=True, **common)
    n = aggregates.sample_count
    if not (0 <= aggregates.dom_sample <= n and 0 <= aggregates.ppsf_sample <= n):
        raise ValueError("a metric sample is larger than the sale sample")
    price = _checked_median(aggregates.price_middles, n, "price")
    ratio = round_ratio(_checked_median(aggregates.ratio_middles, n, "ratio"))
    ppsf = None
    if aggregates.ppsf_sample > 0:
        ppsf_median = _checked_median(
            aggregates.ppsf_middles, aggregates.ppsf_sample, "ppsf"
        )
        ppsf = float(round_dollars(ppsf_median))
    days = None
    if aggregates.dom_sample > 0:
        days = _checked_median(aggregates.dom_middles, aggregates.dom_sample, "dom")
    return MarketStats(
        low_sample=False,
        median_close_price=float(round_dollars(price)),
        median_price_per_sqft=ppsf,
        median_dom=float(days) if days is not None else None,
        dom_band=dom_band(days) if days is not None else None,
        sale_to_list_ratio=float(ratio),
        sale_to_list_reading=sale_to_list_reading(ratio),
        market_lean=market_lean(ratio, days) if days is not None else None,
        trend=_trend(aggregates, window),
        **common,
    )
