"""Comparable-sales price check (WO-011): pure code, no database, no clock.

The db layer returns a CompsAggregate (level used, count, one or two middle price
per sqft values); this module turns it into a CompEvidence and writes its one
fixed-shape sentence. Nothing here values, advises, or forecasts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import (
    AREA_FLOOR,
    MIN_SAMPLE,
    PRICE_FLOOR,
    median_from_middles,
    round_dollars,
)
from idx_agent.domain.models import CompEvidence, Listing, StatsWindow

__all__ = [
    "FORBIDDEN_WORDS",
    "LEVELS",
    "NOT_CHECKABLE_SENTENCE",
    "NOT_ENOUGH_SENTENCE",
    "SENTENCE_PATTERNS",
    "WINDOW_MONTHS",
    "CompSubject",
    "CompsAggregate",
    "Level",
    "Uncheckable",
    "area_band",
    "bed_band",
    "comps_window",
    "contains_forbidden",
    "in_bands",
    "needs_widening",
    "place_names",
    "price_band",
    "price_check",
    "price_check_sentence",
    "reference_price_check",
    "sentence_shape",
    "subject_from_listing",
]

Level = Literal["city", "postal_code"]
# The two geography levels, in the order they are tried; there is no county step.
LEVELS: tuple[Level, ...] = ("city", "postal_code")
WINDOW_MONTHS = 6  # the sentence says "the last six months"
NOT_ENOUGH_SENTENCE = "Not enough comparable sales to check the price."
NOT_CHECKABLE_SENTENCE = (
    "The price cannot be checked: this listing is missing its size, bedroom count, "
    "or type."
)
# Bands (decided 2026-09-24): area within 20%, bedrooms within 1, price within 25%.
_AREA_LOW, _AREA_HIGH = Decimal("0.8"), Decimal("1.2")
_BED_STEP = 1
_PRICE_LOW, _PRICE_HIGH = Decimal("0.75"), Decimal("1.25")
_ONE = Decimal(1)
_HUNDRED = Decimal(100)
_FIVE_DIGITS = re.compile(r"[0-9]{5}")
_TAIL = " over the last six months"
# A city is any text without parentheses (digits allowed: "29 Palms") that does not
# open like the ZIP area, so the city and ZIP shapes never both match.
_CITY = r"(?!ZIP [0-9])[^()]+?"
_ZIP_TAIL = (
    r"ZIP [0-9]{5}" + _TAIL + r" \(widened from " + _CITY + r", which had too few\)\."
)
_HEAD = r"^Listed [1-9][0-9]*% (?:above|below) the median price per square foot of "
_AT = r"^Listed at the median price per square foot of "
_COUNT = r"[1-9][0-9]* comparable sales in "
# The five sentence shapes; every sentence price_check_sentence writes matches one.
SENTENCE_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "city": re.compile(_HEAD + _COUNT + _CITY + _TAIL + r"\.$"),
    "at": re.compile(
        _AT + _COUNT + r"(?:" + _CITY + _TAIL + r"\.|" + _ZIP_TAIL + r")$"
    ),
    "postal_code": re.compile(_HEAD + _COUNT + _ZIP_TAIL + r"$"),
    "not_enough": re.compile("^" + re.escape(NOT_ENOUGH_SENTENCE) + "$"),
    "not_checkable": re.compile("^" + re.escape(NOT_CHECKABLE_SENTENCE) + "$"),
}
# Words that would read as advice, a forecast, or a valuation (whole words).
FORBIDDEN_WORDS: tuple[str, ...] = (
    "overpriced",
    "underpriced",
    "good deal",
    "great deal",
    "bargain",
    "steal",
    "should",
    "worth",
    "fair",
    "expect",
    "will",
    "forecast",
    "estimate",
    "valuation",
    "appraise",
    "recommend",
)
_FORBIDDEN = re.compile(
    r"\b(?:"
    + "|".join(r"\s+".join(map(re.escape, w.split())) for w in FORBIDDEN_WORDS)
    + r")\b",
    re.IGNORECASE,
)
# What an exempt place name becomes before the word scan ("Fair Oaks" holds "fair").
_PLACEHOLDER = "PLACE"


@dataclass(frozen=True)
class CompSubject:
    """The facts a price check needs, all present: from an active Listing.

    `postal_code` is five digits, `living_area` at least AREA_FLOOR, and
    `list_price` at least PRICE_FLOOR; anything else raises ValueError.
    """

    city: str
    postal_code: str
    subtype: str
    living_area: int
    bedrooms: int
    list_price: int

    def __post_init__(self) -> None:
        """Refuse a subject subject_from_listing would have called Uncheckable."""
        if not self.city or not self.subtype:
            raise ValueError("a comps subject needs a city and a subtype")
        if not _FIVE_DIGITS.fullmatch(self.postal_code):
            raise ValueError("a comps subject needs a five-digit ZIP")
        if self.living_area < AREA_FLOOR or self.bedrooms < 0:
            raise ValueError("a comps subject needs an area and a bed count")
        if self.list_price < PRICE_FLOOR:
            raise ValueError("a comps subject needs a list price above the floor")


@dataclass(frozen=True)
class Uncheckable:
    """A listing whose price cannot be checked; `reason` names the first gap."""

    reason: str


@dataclass(frozen=True)
class CompsAggregate:
    """What the comps SQL returns at the level used: counts and middles only.

    `middles` holds the one (odd count) or two (even count) middle price per sqft
    values, () when count is 0. `widened_from` is the city at the ZIP level.
    """

    level: Level
    area: str
    count: int
    middles: tuple[Decimal, ...]
    widened_from: str | None

    def __post_init__(self) -> None:
        """Refuse middles that do not fit the count, or a level without its names."""
        if self.level not in LEVELS or not self.area or self.count < 0:
            raise ValueError("a comps aggregate needs a known level, area, and count")
        expected = 0 if self.count == 0 else (1 if self.count % 2 else 2)
        if len(self.middles) != expected:
            raise ValueError(f"{len(self.middles)} middles for {self.count} comps")
        if (self.level == "postal_code") != (self.widened_from is not None):
            raise ValueError("widened_from is set exactly at the postal_code level")


def subject_from_listing(listing: Listing) -> CompSubject | Uncheckable:
    """The listing's comps facts, or Uncheckable naming the first missing one.

    Checked in order: city, ZIP (first five digits), subtype, living area (at
    least 200 sqft), bedrooms, list price (at least 25,000).
    """
    zip5 = (listing.postal_code or "")[:5]
    checks = (
        ("city", bool(listing.city)),
        ("postal_code", bool(_FIVE_DIGITS.fullmatch(zip5))),
        ("property_subtype", bool(listing.property_subtype)),
        ("living_area", (listing.living_area or 0) >= AREA_FLOOR),
        ("bedrooms", listing.bedrooms is not None),
        ("list_price", listing.list_price >= PRICE_FLOOR),
    )
    for reason, ok in checks:
        if not ok:
            return Uncheckable(reason=reason)
    return CompSubject(
        city=str(listing.city),
        postal_code=zip5,
        subtype=str(listing.property_subtype),
        living_area=int(listing.living_area or 0),
        bedrooms=int(listing.bedrooms or 0),
        list_price=listing.list_price,
    )


def area_band(living_area: int) -> tuple[Decimal, Decimal]:
    """0.8 and 1.2 times the area, in Decimal, both inclusive (1700 -> 1360, 2040)."""
    area = Decimal(living_area)
    return _AREA_LOW * area, _AREA_HIGH * area


def bed_band(bedrooms: int) -> tuple[int, int]:
    """Bedrooms minus 1 (floored at 0) to bedrooms plus 1, inclusive."""
    return max(bedrooms - _BED_STEP, 0), bedrooms + _BED_STEP


def price_band(list_price: int) -> tuple[int, int]:
    """(ceil(0.75 x price), floor(1.25 x price)) as ints, inclusive, in Decimal."""
    price = Decimal(list_price)
    return math.ceil(_PRICE_LOW * price), math.floor(_PRICE_HIGH * price)


def in_bands(subject: CompSubject, area: float | None, beds: float | None) -> bool:
    """True when a sale's area and bed count fall in the subject's bands (tests)."""
    if area is None or beds is None:
        return False
    low, high = area_band(subject.living_area)
    beds_low, beds_high = bed_band(subject.bedrooms)
    return low <= Decimal(repr(float(area))) <= high and beds_low <= beds <= beds_high


def comps_window(as_of: AsOfDates) -> StatsWindow:
    """The six-month window counted back from the sold as-of date."""
    start, end = as_of.window(WINDOW_MONTHS)
    return StatsWindow(start=start, end=end, months=WINDOW_MONTHS)


def needs_widening(count: int) -> bool:
    """The level rule: the ZIP statement runs only when the city has too few."""
    return count < MIN_SAMPLE


def _where(level: Level, area: str) -> str:
    """The area as a sentence names it: the city, or "ZIP nnnnn"."""
    return area if level == "city" else f"ZIP {area}"


def _sentence(
    level: Level | None,
    area: str | None,
    count: int,
    delta: int | None,
    widened_from: str | None,
) -> str:
    """The one writer of the fixed shapes; a None delta is the not-enough shape."""
    if level is None or area is None:
        return NOT_CHECKABLE_SENTENCE
    if delta is None:
        return NOT_ENOUGH_SENTENCE
    where = _where(level, area)
    end = (
        "."
        if level == "city"
        else f" (widened from {widened_from}, which had too few)."
    )
    if delta == 0:
        head = "Listed at the median"
    else:
        head = f"Listed {abs(delta)}% {'above' if delta > 0 else 'below'} the median"
    return (
        f"{head} price per square foot of {count} comparable sales in {where}"
        f"{_TAIL}{end}"
    )


def price_check_sentence(evidence: CompEvidence) -> str:
    """The fixed-shape sentence for a CompEvidence (the only sentence writer).

    Not checkable (no level), not enough comps, or "Listed N% above/below" /
    "Listed at" the median with the count and the area (ZIP with its city).
    """
    delta = int(evidence.delta_pct) if evidence.sufficient else None
    return _sentence(
        evidence.level, evidence.area, evidence.count, delta, evidence.widened_from
    )


def price_check(
    aggregate: CompsAggregate | None, subject: CompSubject | Uncheckable
) -> CompEvidence:
    """Compare the subject's list price per sqft with the comps' median price per sqft.

    delta = (price / area / median - 1) x 100 in Decimal, rounded half-even to a
    whole percent once, at the end; the median in whole dollars separately.
    Uncheckable takes no aggregate; a CompSubject needs one.
    """
    if isinstance(subject, Uncheckable):
        return CompEvidence(
            count=0,
            window_months=WINDOW_MONTHS,
            sufficient=False,
            sentence=NOT_CHECKABLE_SENTENCE,
        )
    if aggregate is None:
        raise ValueError("a checkable subject needs its comps aggregate")
    delta: int | None = None
    median_ppsf: int | None = None
    if aggregate.count >= MIN_SAMPLE:
        median = median_from_middles(aggregate.middles)
        if median is None or median <= 0:
            raise ValueError("a sufficient comps sample needs a positive median")
        ppsf = Decimal(subject.list_price) / Decimal(subject.living_area)
        exact = (ppsf / median - _ONE) * _HUNDRED
        delta = int(exact.quantize(_ONE, rounding=ROUND_HALF_EVEN))
        median_ppsf = round_dollars(median)
    return CompEvidence(
        count=aggregate.count,
        window_months=WINDOW_MONTHS,
        subtype=subject.subtype,
        delta_pct=float(delta) if delta is not None else None,
        sufficient=delta is not None,
        level=aggregate.level,
        area=aggregate.area,
        widened_from=aggregate.widened_from,
        median_price_per_sqft=median_ppsf,
        sentence=_sentence(
            aggregate.level,
            aggregate.area,
            aggregate.count,
            delta,
            aggregate.widened_from,
        ),
    )


def sentence_shape(text: str) -> str | None:
    """The SENTENCE_PATTERNS name the text matches, else None."""
    for name, pattern in SENTENCE_PATTERNS.items():
        if pattern.match(text):
            return name
    return None


def place_names(evidence: CompEvidence) -> tuple[str, ...]:
    """The place names the evidence's sentence holds: its area, then widened_from.

    The area as written ("Fair Oaks", "ZIP 95628"); () when there is no level.
    """
    if evidence.level is None or evidence.area is None:
        return ()
    where = _where(evidence.level, evidence.area)
    return tuple(name for name in (where, evidence.widened_from) if name)


def contains_forbidden(text: str, exempt: Iterable[str] = ()) -> bool:
    """True when the text holds a FORBIDDEN_WORDS entry as a whole word, any case.

    Each `exempt` place name (a city, "ZIP nnnnn") standing whole in the text, in
    its exact spelling, is replaced by a placeholder before the scan: "Fair Oaks"
    passes, "a fair price" next to it still does not.
    """
    names = (exempt,) if isinstance(exempt, str) else exempt
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", _PLACEHOLDER, text)
    return _FORBIDDEN.search(text) is not None


def _reference_aggregate(
    sales: Iterable[tuple[float | int, float | int]],
    level: Level,
    area: str,
    widened_from: str | None,
) -> CompsAggregate:
    """The aggregate the SQL should return, from per-sale (close price, area)."""
    ppsf = sorted(
        _exact(close) / _exact(sqft) for close, sqft in sales if sqft >= AREA_FLOOR
    )
    n = len(ppsf)
    middles = () if n == 0 else tuple(ppsf[(n - 1) // 2 : n // 2 + 1])
    return CompsAggregate(level, area, n, middles, widened_from)


def _exact(value: float | int) -> Decimal:
    """Decimal of a number as written (a float through its shortest repr)."""
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def reference_price_check(
    sales: Iterable[tuple[float | int, float | int]],
    subject: CompSubject | Uncheckable,
    zip_sales: Iterable[tuple[float | int, float | int]] | None = None,
) -> CompEvidence:
    """Python reference for tests: per-sale (close price, area) pairs in, evidence out.

    `sales` are the city comps and `zip_sales` the ZIP comps, each already in the
    subject's subtype, bands, window, and exclusions; the area floor, the level
    rule, and the middles are applied here, then price_check does the math.
    """
    if isinstance(subject, Uncheckable):
        return price_check(None, subject)
    city = _reference_aggregate(sales, "city", subject.city, None)
    if not needs_widening(city.count):
        return price_check(city, subject)
    if zip_sales is None:
        raise ValueError("the city has too few comps: the ZIP comps are needed")
    widened = _reference_aggregate(
        zip_sales, "postal_code", subject.postal_code, subject.city
    )
    return price_check(widened, subject)
