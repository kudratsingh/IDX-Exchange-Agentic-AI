"""Market math (WO-008): medians, rounding, labels, windows, and build_market_stats.

Pure unit tests, no database. All sale values are invented. Each label boundary
from the work order has a case; SQL middles are simulated by `middles()` below.
"""

import inspect
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from idx_agent.domain import market
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.market import (
    AREA_FLOOR,
    DEFAULT_SUBTYPE,
    EXCLUSION_RULES,
    MIN_SAMPLE,
    MONTH_MIN,
    PRICE_FLOOR,
    MarketAggregates,
    MonthAggregate,
    build_market_stats,
    coverage_months,
    dom_band,
    exclusion_warnings,
    market_lean,
    median,
    median_from_middles,
    month_keys,
    round_dollars,
    round_ratio,
    sale_to_list_reading,
)
from idx_agent.domain.models import MarketStatsRequest, MonthRow, StatsWindow

AS_OF = AsOfDates(sold=date(2026, 9, 17), active=date(2026, 9, 18))
SIX = StatsWindow(start=date(2026, 3, 18), end=date(2026, 9, 17), months=6)
REQUEST = MarketStatsRequest(city="Monrovia")
NO_EXCLUSIONS = tuple((name, 0) for name in EXCLUSION_RULES)

# Seven invented sales: (close date, close price, list price, days on market, sqft).
# Sale 5 has 150 sqft (price per sqft only); sale 6 has no days on market.
SALES = [
    (date(2026, 6, 5), 800_000, 800_000, 20, 1600),
    (date(2026, 6, 12), 850_000, 840_000, 10, 1600),
    (date(2026, 6, 20), 900_000, 880_000, 25, 1500),
    (date(2026, 7, 1), 950_000, 960_000, 40, 2000),
    (date(2026, 8, 18), 1_000_000, 990_000, 15, 150),
    (date(2026, 9, 17), 1_050_000, 1_000_000, None, 2100),
    (date(2026, 9, 1), 1_100_000, 1_050_000, 30, 2000),
]


def middles(values):
    """What the SQL returns: the one or two middle values of the ordered sample."""
    ordered = sorted(Decimal(v) for v in values)
    n = len(ordered)
    if n == 0:
        return ()
    if n % 2:
        return (ordered[n // 2],)
    return (ordered[n // 2 - 1], ordered[n // 2])


def aggregates_for(sales, exclusions=NO_EXCLUSIONS):
    """Build MarketAggregates from invented sales, as the db layer would."""
    closes = [s[1] for s in sales]
    doms = [s[3] for s in sales if s[3] is not None and s[3] >= 0]
    ratios = [Decimal(s[1]) / Decimal(s[2]) for s in sales]
    ppsf = [Decimal(s[1]) / Decimal(s[4]) for s in sales if s[4] >= AREA_FLOOR]
    by_month: dict[str, list[int]] = {}
    for s in sales:
        by_month.setdefault(s[0].strftime("%Y-%m"), []).append(s[1])
    months = tuple(
        MonthAggregate(key=k, count=len(v), price_middles=middles(v))
        for k, v in sorted(by_month.items())
    )
    return MarketAggregates(
        sample_count=len(sales),
        price_middles=middles(closes),
        dom_middles=middles(doms),
        dom_sample=len(doms),
        ratio_middles=middles(ratios),
        ppsf_middles=middles(ppsf),
        ppsf_sample=len(ppsf),
        months=months,
        subtype_mix=(("Condominium", 4), (None, 1)),
        exclusions=exclusions,
    )


# --- constants ---


def test_constants_pinned():
    """The fixed thresholds from the work order and the spike."""
    assert (MIN_SAMPLE, MONTH_MIN, PRICE_FLOOR, AREA_FLOOR) == (5, 3, 25_000, 200)
    assert DEFAULT_SUBTYPE == "SingleFamilyResidence"
    assert EXCLUSION_RULES == (
        "after_active_asof",
        "unreadable_close_date",
        "close_before_contract",
        "price_under_floor",
        "duplicate_listing_key",
        "area_under_floor",
        "dom_missing",
    )


def test_module_never_reads_the_clock():
    """Windows count back from the data's as-of dates, never from today."""
    source = inspect.getsource(market)
    for call in ("today(", "now(", "utcnow(", "time.time"):
        assert call not in source


# --- median ---


def test_median_odd_count_is_the_middle_value():
    """Seven values: the fourth after sorting, whatever the input order."""
    assert median([5, 1, 4, 2, 3, 7, 6]) == Decimal(4)


def test_median_even_count_averages_two_middles_in_decimal():
    """Two middles are averaged exactly: (2 + 3) / 2 = 2.5, not a float."""
    result = median([4, 1, 3, 2])
    assert result == Decimal("2.5") and isinstance(result, Decimal)


def test_median_one_value_and_all_ties():
    """One value is its own median; a sample of ties has that value."""
    assert median([812_345]) == Decimal(812_345)
    assert median([700_000] * 6) == Decimal(700_000)


def test_median_tie_across_the_middle():
    """A tie straddling the middle of an even sample gives the tied value."""
    assert median([1, 5, 5, 9]) == Decimal(5)


def test_median_floats_are_read_as_written():
    """A float price like 812345.5 is taken at its shortest repr, no binary noise."""
    assert median([812_345.5, 812_346.1]) == Decimal("812345.8")


def test_median_empty_raises():
    """There is no median of nothing."""
    with pytest.raises(ValueError):
        median([])


def test_median_from_middles():
    """() is no sample, one middle is the median, two are averaged, three raise."""
    assert median_from_middles(()) is None
    assert median_from_middles((Decimal(950_000),)) == Decimal(950_000)
    assert median_from_middles((Decimal("100000.5"), Decimal(100_001))) == Decimal(
        "100000.75"
    )
    with pytest.raises(ValueError):
        median_from_middles((1, 2, 3))


@pytest.mark.parametrize(
    "values", [[3, 1, 2], [4, 1, 3, 2], [9], [2, 2, 2, 2], [10.5, 3.25, 7, 7.75]]
)
def test_median_from_middles_matches_reference(values):
    """The SQL-middles path equals the reference median over the whole list."""
    assert median_from_middles(middles(values)) == median(values)


# --- rounding ---


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("100000.5"), 100_000),
        (Decimal("100001.5"), 100_002),
        (Decimal("100000.49"), 100_000),
        (Decimal("100000.51"), 100_001),
        (Decimal("515.625"), 516),
    ],
)
def test_round_dollars_half_even(value, expected):
    """Whole dollars, ties to even."""
    assert round_dollars(value) == expected


def test_rounding_once_at_the_end_differs_from_rounding_first():
    """Averaging then rounding gives 100001; rounding each middle first gives 100000."""
    pair = (Decimal("100000.5"), Decimal("100001"))
    once = round_dollars(median_from_middles(pair))
    first = round_dollars(median_from_middles(tuple(round_dollars(p) for p in pair)))
    assert (once, first) == (100_001, 100_000)


@pytest.mark.parametrize(
    "value,expected",
    [("1.0325", "1.032"), ("1.0335", "1.034"), ("0.9995", "1.000"), ("1", "1.000")],
)
def test_round_ratio_three_places_half_even(value, expected):
    """The ratio is rounded half-even to 3 decimals."""
    assert round_ratio(Decimal(value)) == Decimal(expected)


def test_ratio_is_close_over_final_list():
    """The per-sale ratio is ClosePrice / ListPrice; its median is then rounded."""
    ratios = [Decimal(c) / Decimal(lp) for _, c, lp, _, _ in SALES]
    assert round_ratio(median(ratios)) == Decimal("1.012")  # 850,000 / 840,000


# --- sale_to_list_reading ---


@pytest.mark.parametrize(
    "ratio,reading",
    [
        ("1", "at asking"),
        ("1.000", "at asking"),
        ("1.001", "at asking"),  # 0.1% rounds to 0
        ("0.999", "at asking"),
        ("1.005", "at asking"),  # 0.5% ties to even: 0
        ("0.995", "at asking"),
        ("1.006", "1% over asking"),  # just over
        ("0.994", "1% under asking"),  # just under
        ("1.01", "1% over asking"),
        ("0.99", "1% under asking"),
        ("1.015", "2% over asking"),  # 1.5% ties to even: 2
        ("1.025", "2% over asking"),  # 2.5% ties to even: 2
        ("1.03", "3% over asking"),
        ("0.97", "3% under asking"),
    ],
)
def test_sale_to_list_reading(ratio, reading):
    """Whole percent from 1, half-even: at asking, N% over, N% under."""
    assert sale_to_list_reading(Decimal(ratio)) == reading


def test_reading_uses_the_rounded_ratio():
    """1.0149 rounds to 1.015 first, so it reads 2% (the raw value would read 1%)."""
    assert sale_to_list_reading(Decimal("1.0149")) == "2% over asking"


# --- dom_band ---


@pytest.mark.parametrize(
    "days,band",
    [
        (0, "very_low"),
        (Decimal("14.5"), "very_low"),
        (15, "low"),
        (Decimal("29.5"), "low"),
        (30, "average"),
        (Decimal("59.5"), "average"),
        (60, "high"),
        (400, "high"),
    ],
)
def test_dom_band_boundaries(days, band):
    """very_low under 15, low 15 to under 30, average 30 to under 60, high 60+."""
    assert dom_band(days) == band


# --- market_lean ---


@pytest.mark.parametrize(
    "ratio,days,lean",
    [
        ("1.000", Decimal("29.5"), "seller"),  # both seller bounds met
        ("1.000", 30, "balanced"),  # days reach 30: not seller
        ("0.9995", 10, "seller"),  # rounds to 1.000 first
        ("0.999", 10, "balanced"),  # under 1.000: not seller
        ("0.980", Decimal("59.5"), "balanced"),  # neither buyer bound
        ("0.979", 10, "buyer"),  # ratio under 0.980
        ("0.9795", 10, "balanced"),  # rounds to 0.980 (tie to even)
        ("0.990", 60, "buyer"),  # days 60 or more
        ("1.050", 60, "buyer"),  # over asking but slow: seller fails, then buyer
        ("1.050", 45, "balanced"),
    ],
)
def test_market_lean_boundaries_in_order(ratio, days, lean):
    """seller: ratio >= 1.000 and days < 30; else buyer: < 0.980 or >= 60 days."""
    assert market_lean(Decimal(ratio), days) == lean


# --- month_keys and coverage_months ---


def test_month_keys_mid_month_across_a_year_end():
    """A window from mid-November to early February touches four months."""
    window = StatsWindow(start=date(2025, 11, 18), end=date(2026, 2, 3), months=3)
    assert month_keys(window) == ("2025-11", "2025-12", "2026-01", "2026-02")


def test_month_keys_default_and_one_month_windows():
    """Six months to 2026-09-17 touch seven months; one month touches two."""
    assert month_keys(SIX) == tuple(f"2026-{m:02d}" for m in range(3, 10))
    start, end = AS_OF.window(1)
    one = StatsWindow(start=start, end=end, months=1)
    assert month_keys(one) == ("2026-08", "2026-09")


def test_month_keys_single_day():
    """A window inside one month has one key."""
    day = StatsWindow(start=date(2026, 9, 17), end=date(2026, 9, 17), months=1)
    assert month_keys(day) == ("2026-09",)


@pytest.mark.parametrize(
    "earliest,months",
    [
        (date(2026, 3, 18), 6),  # exactly the six-month start
        (date(2026, 3, 17), 7),  # one day earlier needs a seventh month
        (date(2026, 4, 2), 6),
        (date(2026, 8, 18), 1),
        (date(2026, 8, 17), 2),
        (date(2026, 9, 17), 1),
        (date(2025, 9, 18), 12),
    ],
)
def test_coverage_months(earliest, months):
    """The fewest months whose window reaches the earliest close date."""
    assert coverage_months(earliest, AS_OF.sold) == months
    assert AS_OF.window(months)[0] <= earliest
    if months > 1:
        assert AS_OF.window(months - 1)[0] > earliest


def test_coverage_fallback_for_a_twelve_month_request():
    """Data from 2026-03-18 on: a 12-month request falls back to six months."""
    earliest = date(2026, 3, 18)
    assert AS_OF.window(12)[0] < earliest
    assert coverage_months(earliest, AS_OF.sold) == 6


def test_coverage_months_earliest_after_as_of_raises():
    """An earliest close after the as-of date is a data error."""
    with pytest.raises(ValueError):
        coverage_months(date(2026, 9, 18), AS_OF.sold)


# --- build_market_stats ---


def test_build_market_stats_full_sample():
    """Seven invented sales give fixed figures, labels, and a seven-month trend."""
    stats = build_market_stats(aggregates_for(SALES), REQUEST, SIX, AS_OF)
    assert stats.low_sample is False and stats.sample_count == 7
    assert stats.geography.city == "Monrovia"
    assert stats.property_subtype == DEFAULT_SUBTYPE
    assert stats.as_of == date(2026, 9, 17) and stats.window == SIX
    assert stats.median_close_price == 950_000.0  # 4th of 7
    # ppsf over 6 sales (the 150 sqft sale is left out): middles 500 and 531.25
    assert stats.median_price_per_sqft == 516.0  # 515.625 rounded half-even
    # days over 6 sales (one missing): 10 15 20 25 30 40 -> (20 + 25) / 2
    assert stats.median_dom == 22.5 and stats.dom_band == "low"
    assert stats.sale_to_list_ratio == 1.012
    assert stats.sale_to_list_reading == "1% over asking"
    assert stats.market_lean == "seller"
    assert stats.mean_close_price is None
    assert stats.trend == [
        MonthRow(month="2026-03", sample_count=0),
        MonthRow(month="2026-04", sample_count=0),
        MonthRow(month="2026-05", sample_count=0),
        MonthRow(month="2026-06", sample_count=3, median_close_price=850_000.0),
        MonthRow(month="2026-07", sample_count=1),
        MonthRow(month="2026-08", sample_count=1),
        MonthRow(month="2026-09", sample_count=2),  # under MONTH_MIN: no median
    ]


def test_build_market_stats_matches_the_reference_math():
    """Every figure equals the reference median over the plain lists."""
    stats = build_market_stats(aggregates_for(SALES), REQUEST, SIX, AS_OF)
    closes = [s[1] for s in SALES]
    doms = [s[3] for s in SALES if s[3] is not None]
    ratios = [Decimal(s[1]) / Decimal(s[2]) for s in SALES]
    assert stats.median_close_price == round_dollars(median(closes))
    assert stats.median_dom == float(median(doms))
    assert stats.sale_to_list_ratio == float(round_ratio(median(ratios)))


def test_build_market_stats_rounds_once_at_the_end():
    """Even sample with fractional middles: 100000.75 -> 100001, not 100000."""
    sales = [
        (date(2026, 6, d), p, p, 20, 1000)
        for d, p in zip(
            range(1, 7),
            [90_000, 95_000, 100_000.5, 100_001, 120_000, 130_000],
            strict=True,
        )
    ]
    stats = build_market_stats(aggregates_for(sales), REQUEST, SIX, AS_OF)
    assert stats.median_close_price == 100_001.0
    assert stats.trend[3] == MonthRow(
        month="2026-06", sample_count=6, median_close_price=100_001.0
    )


def test_build_market_stats_keeps_a_named_subtype_and_zip():
    """A request with a subtype and a ZIP carries both into the result."""
    request = MarketStatsRequest(postal_code="91016", property_subtype="Condominium")
    stats = build_market_stats(aggregates_for(SALES), request, SIX, AS_OF)
    assert stats.property_subtype == "Condominium"
    assert (stats.geography.city, stats.geography.postal_code) == (None, "91016")


@pytest.mark.parametrize("count", [0, 1, MIN_SAMPLE - 1])
def test_build_market_stats_under_min_sample_is_not_enough_comps(count):
    """Under MIN_SAMPLE: real count, low_sample, no figures, no trend, exclusions."""
    exclusions = tuple(
        (name, 1 if name == "close_before_contract" else 0) for name in EXCLUSION_RULES
    )
    aggregates = aggregates_for(SALES[:count], exclusions=exclusions)
    stats = build_market_stats(aggregates, REQUEST, SIX, AS_OF)
    assert stats.low_sample is True and stats.sample_count == count
    for field in (
        "median_close_price",
        "mean_close_price",
        "median_price_per_sqft",
        "median_dom",
        "dom_band",
        "sale_to_list_ratio",
        "sale_to_list_reading",
        "market_lean",
    ):
        assert getattr(stats, field) is None, field
    assert stats.trend == []
    assert "close_before_contract: 1" in stats.exclusions_applied
    assert stats.property_subtype == DEFAULT_SUBTYPE


def test_build_market_stats_at_min_sample_has_every_figure():
    """Exactly MIN_SAMPLE sales: stats, not the not-enough-comps outcome."""
    stats = build_market_stats(aggregates_for(SALES[:MIN_SAMPLE]), REQUEST, SIX, AS_OF)
    assert stats.low_sample is False and stats.sample_count == MIN_SAMPLE
    assert stats.median_close_price == 900_000.0  # 3rd of 5
    assert None not in (
        stats.median_dom,
        stats.dom_band,
        stats.sale_to_list_ratio,
        stats.sale_to_list_reading,
        stats.market_lean,
        stats.median_price_per_sqft,
    )


def test_exclusions_listed_in_rule_order_with_counts_and_warned():
    """One "rule: count" entry per rule; non-zero counts become plain warnings."""
    exclusions = (
        ("after_active_asof", 1),
        ("unreadable_close_date", 0),
        ("close_before_contract", 1),
        ("price_under_floor", 2),
        ("duplicate_listing_key", 1),
        ("area_under_floor", 1),
        ("dom_missing", 1),
    )
    warnings: list[str] = ["an earlier warning"]
    stats = build_market_stats(
        aggregates_for(SALES, exclusions=exclusions), REQUEST, SIX, AS_OF, warnings
    )
    assert stats.exclusions_applied == [
        "after_active_asof: 1",
        "unreadable_close_date: 0",
        "close_before_contract: 1",
        "price_under_floor: 2",
        "duplicate_listing_key: 1",
        "area_under_floor: 1",
        "dom_missing: 1",
    ]
    assert warnings[0] == "an earlier warning" and len(warnings) == 7
    assert warnings[1:] == exclusion_warnings(exclusions)
    assert not any("unreadable" in w for w in warnings)
    assert all("_" not in w for w in warnings[1:])  # plain words, not rule ids
    # A NULL LivingArea counts here too, so the words say "or missing".
    assert (
        "1 sale(s) with living area under 200 sqft or missing were left out "
        "of the price per sqft median only"
    ) in warnings


def test_exclusions_in_any_input_order_come_out_in_rule_order():
    """The db layer's order does not matter; the output follows EXCLUSION_RULES."""
    shuffled = tuple(reversed(NO_EXCLUSIONS))
    stats = build_market_stats(
        aggregates_for(SALES, exclusions=shuffled), REQUEST, SIX, AS_OF
    )
    assert [e.split(":")[0] for e in stats.exclusions_applied] == list(EXCLUSION_RULES)


@pytest.mark.parametrize(
    "exclusions",
    [
        NO_EXCLUSIONS[:-1],  # a rule missing
        NO_EXCLUSIONS + (("made_up_rule", 0),),
        NO_EXCLUSIONS + (("dom_missing", 0),),  # repeated
        (("after_active_asof", -1),) + NO_EXCLUSIONS[1:],
    ],
)
def test_bad_exclusion_counts_raise(exclusions):
    """A missing, unknown, repeated, or negative exclusion entry is a bug, not data."""
    with pytest.raises(ValueError):
        build_market_stats(
            aggregates_for(SALES, exclusions=exclusions), REQUEST, SIX, AS_OF
        )


def test_no_usable_days_on_market_leaves_dom_readings_empty():
    """Every DaysOnMarket missing: median_dom, dom_band, market_lean are None."""
    sales = [(d, c, lp, None, a) for d, c, lp, _, a in SALES]
    stats = build_market_stats(aggregates_for(sales), REQUEST, SIX, AS_OF)
    assert stats.low_sample is False
    assert (stats.median_dom, stats.dom_band, stats.market_lean) == (None, None, None)
    assert stats.sale_to_list_reading == "1% over asking"


def test_no_sale_over_the_area_floor_leaves_ppsf_empty():
    """Every LivingArea under 200 sqft: no price per sqft median, other figures kept."""
    sales = [(d, c, lp, dom, 100) for d, c, lp, dom, _ in SALES]
    stats = build_market_stats(aggregates_for(sales), REQUEST, SIX, AS_OF)
    assert stats.median_price_per_sqft is None
    assert stats.median_close_price == 950_000.0


def test_middles_that_do_not_fit_the_sample_raise():
    """An odd sample with two middles (or none) means the SQL and the count disagree."""
    good = aggregates_for(SALES)
    for bad in (
        replace(good, price_middles=good.price_middles * 2),
        replace(good, ratio_middles=()),
        replace(good, dom_sample=99),
    ):
        with pytest.raises(ValueError):
            build_market_stats(bad, REQUEST, SIX, AS_OF)


def test_months_outside_the_window_or_miscounted_raise():
    """A month the window does not touch, or counts not adding up, raises."""
    good = aggregates_for(SALES)
    stray = MonthAggregate(key="2025-12", count=0, price_middles=())
    outside = replace(good, months=good.months + (stray,))
    short = replace(good, months=good.months[1:])
    for bad in (outside, short):
        with pytest.raises(ValueError):
            build_market_stats(bad, REQUEST, SIX, AS_OF)
