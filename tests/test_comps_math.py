"""Price-check math and sentences (WO-011): pure unit tests, no database.

All values are invented. Middles are what the SQL would return for an ordered
sample; each expected number carries its arithmetic in a comment.
"""

from __future__ import annotations

import inspect
import re
from decimal import Decimal
from itertools import product

import pytest
from pydantic import ValidationError

from idx_agent.db import comps as db_comps
from idx_agent.domain import comps
from idx_agent.domain.comps import (
    FORBIDDEN_WORDS,
    LEVELS,
    NOT_CHECKABLE_SENTENCE,
    NOT_ENOUGH_SENTENCE,
    SENTENCE_PATTERNS,
    WINDOW_MONTHS,
    CompsAggregate,
    CompSubject,
    Uncheckable,
    area_band,
    bed_band,
    contains_forbidden,
    in_bands,
    needs_widening,
    place_names,
    price_band,
    price_check,
    price_check_sentence,
    reference_price_check,
    sentence_shape,
    subject_from_listing,
)
from idx_agent.domain.market import MIN_SAMPLE
from idx_agent.domain.models import CompEvidence, Listing
from idx_agent.domain.valid_values import CITIES, CITY_SPELLINGS

D = Decimal


def subject(**overrides) -> CompSubject:
    """An invented Monrovia single-family subject: 1,000 sqft, 3 beds, 500,000."""
    values = {
        "city": "Monrovia",
        "postal_code": "91016",
        "subtype": "SingleFamilyResidence",
        "living_area": 1000,
        "bedrooms": 3,
        "list_price": 500_000,
    }
    return CompSubject(**(values | overrides))


def city(count: int, *middles, name: str = "Monrovia") -> CompsAggregate:
    """A city-level aggregate with the given count and middle values."""
    return CompsAggregate("city", name, count, tuple(D(m) for m in middles), None)


def zip_level(count: int, *middles) -> CompsAggregate:
    """A ZIP-level aggregate for 91016, widened from Monrovia."""
    return CompsAggregate(
        "postal_code", "91016", count, tuple(D(m) for m in middles), "Monrovia"
    )


def listing(**overrides) -> Listing:
    """An invented active listing with every comps fact present."""
    values = {
        "listing_key": 9_990_001,
        "listing_id": "EX9990001",
        "city": "Monrovia",
        "postal_code": "91016",
        "list_price": 500_000,
        "bedrooms": 3,
        "bathrooms": None,
        "living_area": 1000,
        "property_subtype": "SingleFamilyResidence",
    }
    return Listing(**(values | overrides))


# --- bands ---


def test_area_band_is_decimal_and_inclusive_at_both_edges():
    assert area_band(1700) == (D("1360.0"), D("2040.0"))  # 0.8 x 1700, 1.2 x 1700
    assert area_band(1975) == (D("1580.0"), D("2370.0"))
    low, high = area_band(1333)
    assert (low, high) == (D("1066.4"), D("1599.6"))  # not rounded
    s = subject(living_area=1700)
    assert in_bands(s, 1360, 3) and in_bands(s, 2040.0, 3)  # exactly 0.8x and 1.2x
    assert not in_bands(s, 1359.9, 3) and not in_bands(s, 2040.1, 3)
    assert not in_bands(s, None, 3) and not in_bands(s, 1700, None)


@pytest.mark.parametrize(
    "beds,band", [(0, (0, 1)), (1, (0, 2)), (3, (2, 4)), (5, (4, 6))]
)
def test_bed_band_is_within_one_and_floored_at_zero(beds, band):
    assert bed_band(beds) == band
    s = subject(bedrooms=beds)
    assert in_bands(s, 1000, band[0]) and in_bands(s, 1000, band[1])
    assert not in_bands(s, 1000, band[1] + 1)


@pytest.mark.parametrize(
    "price,band",
    [
        (850_000, (637_500, 1_062_500)),  # 0.75 and 1.25 x 850,000 exactly
        (999_999, (750_000, 1_249_998)),  # ceil(749,999.25), floor(1,249,998.75)
        (25_001, (18_751, 31_251)),  # ceil(18,750.75), floor(31,251.25)
    ],
)
def test_price_band_ceils_the_low_end_and_floors_the_high_end(price, band):
    assert price_band(price) == band
    assert all(type(v) is int for v in price_band(price))


# --- medians and the percentage ---


def test_odd_count_uses_the_one_middle():
    # 7 comps, middle 480; subject 500,000 / 1,000 = 500; 500 / 480 - 1 = 4.17% -> 4.
    evidence = price_check(city(7, 480), subject())
    assert (evidence.delta_pct, evidence.median_price_per_sqft) == (4.0, 480)
    assert evidence.count == 7 and evidence.sufficient


def test_even_count_averages_the_two_middles_in_decimal():
    # Middles 490 and 530 -> 510; 500 / 510 - 1 = -1.96% -> -2.
    evidence = price_check(city(6, 490, 530), subject())
    assert (evidence.delta_pct, evidence.median_price_per_sqft) == (-2.0, 510)
    assert evidence.sentence.startswith("Listed 2% below the median")


def test_the_percentage_is_rounded_once_at_the_end():
    # Subject 102,600 / 1,000 = 102.6; median (100 + 101) / 2 = 100.5.
    # Once: 102.6 / 100.5 - 1 = 2.09% -> 2. Rounding the median first (to 100,
    # half-even) would give 102.6 / 100 - 1 = 2.6% -> 3.
    s = subject(list_price=102_600)
    evidence = price_check(city(6, 100, 101), s)
    assert evidence.delta_pct == 2.0
    first = (D("102.6") / D(evidence.median_price_per_sqft) - 1) * 100
    assert evidence.median_price_per_sqft == 100
    assert round(first) == 3 != evidence.delta_pct


@pytest.mark.parametrize(
    "price,delta",
    [
        (410_000, 2),  # 410 / 400 - 1 = 2.5% -> 2 (half-even)
        (414_000, 4),  # 3.5% -> 4
        (390_000, -2),  # -2.5% -> -2
        (386_000, -4),  # -3.5% -> -4
        (402_000, 0),  # 0.5% -> 0: "at"
        (398_000, 0),  # -0.5% -> 0: "at"
        (402_004, 1),  # 0.501% -> 1
        (800_000, 100),  # 100% above
    ],
)
def test_half_even_at_point_five(price, delta):
    evidence = price_check(city(5, 400), subject(list_price=price))
    assert evidence.delta_pct == delta and evidence.median_price_per_sqft == 400


def test_the_median_is_rounded_half_even_to_whole_dollars_separately():
    # (500 + 501) / 2 = 500.5 -> 500; (501 + 502) / 2 = 501.5 -> 502.
    assert price_check(city(6, 500, 501), subject()).median_price_per_sqft == 500
    assert price_check(city(6, 501, 502), subject()).median_price_per_sqft == 502
    # 500 / 500.5 - 1 = -0.0999% -> 0, computed from the unrounded median.
    assert price_check(city(6, 500, 501), subject()).delta_pct == 0.0


def test_at_the_median_when_it_rounds_to_zero():
    evidence = price_check(city(5, 499), subject())  # 500 / 499 - 1 = 0.2% -> 0
    assert evidence.sentence == (
        "Listed at the median price per square foot of 5 comparable sales in "
        "Monrovia over the last six months."
    )


@pytest.mark.parametrize("count,sufficient", [(4, False), (5, True), (0, False)])
def test_the_minimum_is_five(count, sufficient):
    middles = () if count == 0 else ((480,) if count % 2 else (470, 490))
    evidence = price_check(city(count, *middles), subject())
    assert evidence.sufficient is sufficient and evidence.count == count
    assert needs_widening(count) is (count < MIN_SAMPLE)
    if not sufficient:
        assert evidence.sentence == NOT_ENOUGH_SENTENCE
        assert evidence.delta_pct is None and evidence.median_price_per_sqft is None
        assert evidence.level == "city" and evidence.area == "Monrovia"


def test_comp_price_estimate_is_never_set():
    for aggregate in (city(5, 480), city(4, 470, 490), zip_level(6, 490, 530)):
        assert price_check(aggregate, subject()).comp_price_estimate is None
    assert price_check(None, Uncheckable("bedrooms")).comp_price_estimate is None


# --- sentences ---


def test_each_sentence_shape_exactly():
    s = subject()
    assert price_check(city(12, 480, 480), s).sentence == (
        "Listed 4% above the median price per square foot of 12 comparable sales in "
        "Monrovia over the last six months."
    )  # 500 / 480 - 1 = 4.17% -> 4 (12 comps; middles as given)
    assert price_check(city(12, 520, 520), s).sentence == (
        "Listed 4% below the median price per square foot of 12 comparable sales in "
        "Monrovia over the last six months."
    )  # 500 / 520 - 1 = -3.85% -> -4
    assert price_check(zip_level(5, 480), s).sentence == (
        "Listed 4% above the median price per square foot of 5 comparable sales in "
        "ZIP 91016 over the last six months (widened from Monrovia, which had too "
        "few)."
    )
    assert price_check(zip_level(5, 500), s).sentence == (
        "Listed at the median price per square foot of 5 comparable sales in "
        "ZIP 91016 over the last six months (widened from Monrovia, which had too "
        "few)."
    )
    assert price_check(zip_level(3, 500), s).sentence == NOT_ENOUGH_SENTENCE
    assert NOT_ENOUGH_SENTENCE == "Not enough comparable sales to check the price."
    assert NOT_CHECKABLE_SENTENCE == (
        "The price cannot be checked: this listing is missing its size, bedroom "
        "count, or type."
    )


def test_the_zip_level_carries_its_city_and_the_evidence_fields():
    evidence = price_check(zip_level(6, 490, 530), subject())
    assert (evidence.level, evidence.area, evidence.widened_from) == (
        "postal_code",
        "91016",
        "Monrovia",
    )
    assert evidence.window_months == WINDOW_MONTHS == 6
    assert evidence.subtype == "SingleFamilyResidence"


def test_price_check_sentence_rebuilds_every_evidence_sentence():
    for aggregate in (city(5, 480), city(4, 470, 490), zip_level(7, 520)):
        evidence = price_check(aggregate, subject())
        assert price_check_sentence(evidence) == evidence.sentence
    blank = price_check(None, Uncheckable("living_area"))
    assert price_check_sentence(blank) == blank.sentence == NOT_CHECKABLE_SENTENCE


def _every_sentence():
    """Sentences over a grid of levels, counts, deltas, and city names."""
    cities = ["Monrovia", "La Canada Flintridge", "Rancho Palos Verdes"]
    medians = [100, 250, 399, 400, 401, 480, 500, 520, 1000]
    for level, count, median, name in product(
        LEVELS, [0, 3, 4, 5, 6, 57], medians, cities
    ):
        middles = () if count == 0 else ((median,) if count % 2 else (median, median))
        widened = name if level == "postal_code" else None
        area = name if level == "city" else "91016"
        aggregate = CompsAggregate(level, area, count, tuple(map(D, middles)), widened)
        yield price_check(aggregate, subject(city=name)).sentence
    yield price_check(None, Uncheckable("bedrooms")).sentence


def test_every_sentence_matches_exactly_one_shape_and_no_forbidden_word():
    seen = set()
    for sentence in _every_sentence():
        shapes = [n for n, p in SENTENCE_PATTERNS.items() if p.match(sentence)]
        assert len(shapes) == 1, (sentence, shapes)
        assert sentence_shape(sentence) == shapes[0]
        assert not contains_forbidden(sentence), sentence
        seen.add(shapes[0])
    assert seen == {"city", "at", "postal_code", "not_enough", "not_checkable"}


def test_every_valid_city_gets_its_shape_and_no_forbidden_word_outside_its_name():
    """Every city in both spellings, at the city and ZIP levels, above and at.

    Real names include "Fair Oaks" (holds "fair") and "29 Palms" (a digit).
    """
    names = set(CITIES) | set(CITY_SPELLINGS.values())
    assert {"Fair Oaks", "29 Palms"} <= names
    for name in sorted(names):
        s = subject(city=name)
        checks = [
            ("city", CompsAggregate("city", name, 12, (D(480),) * 2, None)),
            ("at", CompsAggregate("city", name, 12, (D(500),) * 2, None)),
            ("postal_code", CompsAggregate("postal_code", "91016", 5, (D(480),), name)),
            ("at", CompsAggregate("postal_code", "91016", 5, (D(500),), name)),
        ]
        for shape, aggregate in checks:
            evidence = price_check(aggregate, s)
            sentence = evidence.sentence
            assert sentence_shape(sentence) == shape, sentence
            shapes = [n for n, p in SENTENCE_PATTERNS.items() if p.match(sentence)]
            assert shapes == [shape], (sentence, shapes)
            assert name in place_names(evidence)
            assert not contains_forbidden(sentence, exempt=place_names(evidence))


def test_place_names_are_the_area_as_written_and_the_widened_from_city():
    assert place_names(price_check(city(5, 480, name="Fair Oaks"), subject())) == (
        "Fair Oaks",
    )
    assert place_names(price_check(zip_level(5, 480), subject())) == (
        "ZIP 91016",
        "Monrovia",
    )
    assert place_names(price_check(None, Uncheckable("bedrooms"))) == ()


def test_an_exempt_place_name_passes_but_a_forbidden_word_beside_it_does_not():
    text = "12 comparable sales in Fair Oaks over the last six months."
    assert contains_forbidden(text)
    assert not contains_forbidden(text, exempt=["Fair Oaks"])
    assert not contains_forbidden(text, exempt="Fair Oaks")
    assert contains_forbidden(f"{text} A fair price.", exempt=["Fair Oaks"])
    # Only the whole name, in its exact spelling, is exempt.
    assert contains_forbidden("fair oaks", exempt=["Fair Oaks"])
    assert contains_forbidden("Fair Oaksview", exempt=["Fair Oaks"])
    assert contains_forbidden("fair", exempt=[""])


@pytest.mark.parametrize(
    "text",
    [
        "Listed 4% above the median price per square foot of 12 comparable sales "
        "in Monrovia over the last six months. It is a good deal.",
        "Listed 0% above the median price per square foot of 12 comparable sales "
        "in Monrovia over the last six months.",
        "Listed 4% above the median price per square foot of 12 comparable sales "
        "in ZIP 91016 over the last six months.",
        "Not enough comparable sales to check the price (4 found).",
        "Listed about 4% above the median.",
    ],
)
def test_other_text_matches_no_shape(text):
    assert sentence_shape(text) is None


def test_the_not_enough_and_not_checkable_sentences_hold_no_digit():
    for sentence in (NOT_ENOUGH_SENTENCE, NOT_CHECKABLE_SENTENCE):
        assert not re.search(r"[0-9]", sentence)


@pytest.mark.parametrize(
    "text",
    [
        "This one is overpriced.",
        "A GOOD DEAL for the area",
        "a great\tdeal",
        "You should look",
        "Prices will rise",
        "Worth a look",
        "a fair price",
        "we expect",
        "Estimate: high",
        "no valuation here",
        "Appraise it",
        "I recommend it",
        "a bargain",
        "a steal",
        "underpriced",
        "forecast",
    ],
)
def test_forbidden_words_are_caught_whole_and_any_case(text):
    assert contains_forbidden(text)


@pytest.mark.parametrize(
    "text", ["Fairview Ave", "willow trees", "estimated", "stealth", "recommended"]
)
def test_forbidden_words_match_whole_words_only(text):
    assert not contains_forbidden(text)


def test_the_forbidden_list_holds_at_least_the_work_order_words():
    required = {
        "overpriced", "underpriced", "good deal", "great deal", "bargain", "steal",
        "should", "worth", "fair", "expect", "will", "forecast", "estimate",
        "valuation", "appraise", "recommend",
    }  # fmt: skip
    assert required <= set(FORBIDDEN_WORDS)


# --- the subject ---


def test_a_full_listing_is_a_subject():
    assert subject_from_listing(listing()) == subject()
    assert subject_from_listing(listing(bedrooms=0)).bedrooms == 0


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"city": None}, "city"),
        ({"city": ""}, "city"),
        ({"postal_code": None}, "postal_code"),
        ({"property_subtype": None}, "property_subtype"),
        ({"living_area": None}, "living_area"),
        ({"living_area": 199}, "living_area"),
        ({"bedrooms": None}, "bedrooms"),
        ({"list_price": 24_999}, "list_price"),
    ],
)
def test_each_missing_fact_makes_the_listing_not_checkable(overrides, reason):
    result = subject_from_listing(listing(**overrides))
    assert result == Uncheckable(reason)
    evidence = price_check(None, result)
    assert evidence.sentence == NOT_CHECKABLE_SENTENCE
    assert (evidence.level, evidence.area, evidence.sufficient) == (None, None, False)
    assert evidence.delta_pct is None and evidence.count == 0


def test_the_edges_of_the_floors_are_checkable():
    edge = subject_from_listing(listing(living_area=200, list_price=25_000))
    assert isinstance(edge, CompSubject)


def test_bathrooms_are_never_read():
    """A listing with no bathroom count is checkable; no module names a bath field."""
    assert isinstance(subject_from_listing(listing(bathrooms=None)), CompSubject)
    for module in (comps, db_comps):
        source = inspect.getsource(module)
        assert "LM_Dec_3" not in source and "BathroomsTotalInteger" not in source
        assert ".bathrooms" not in source


def test_nothing_reads_the_clock():
    for module in (comps, db_comps):
        source = inspect.getsource(module)
        assert "today(" not in source and "now(" not in source
        assert "import datetime" not in source and "import time" not in source


@pytest.mark.parametrize(
    "overrides",
    [
        {"city": ""},
        {"subtype": ""},
        {"postal_code": "9101"},
        {"postal_code": "91016-1234"},
        {"living_area": 199},
        {"bedrooms": -1},
        {"list_price": 24_999},
    ],
)
def test_a_comp_subject_refuses_a_missing_fact(overrides):
    with pytest.raises(ValueError):
        subject(**overrides)


def test_price_check_needs_an_aggregate_for_a_checkable_subject():
    with pytest.raises(ValueError):
        price_check(None, subject())


@pytest.mark.parametrize(
    "args",
    [
        ("county", "Monrovia", 5, (D(1),), None),
        ("city", "", 5, (D(1),), None),
        ("city", "Monrovia", 5, (D(1), D(2)), None),
        ("city", "Monrovia", 6, (D(1),), None),
        ("city", "Monrovia", 0, (D(1),), None),
        ("city", "Monrovia", 5, (D(1),), "Monrovia"),
        ("postal_code", "91016", 5, (D(1),), None),
    ],
)
def test_a_comps_aggregate_refuses_an_inconsistent_shape(args):
    with pytest.raises(ValueError):
        CompsAggregate(*args)


def test_evidence_refuses_figures_without_sufficiency():
    base = {"count": 4, "window_months": 6, "level": "city", "area": "Monrovia"}
    with pytest.raises(ValidationError):
        CompEvidence(**base, sufficient=False, delta_pct=3.0, sentence="x")


# --- the Python reference ---

# Seven invented comps (close price, sqft): per-sale price per sqft 500, 520, 480,
# 540, 460, 510, and one of 150 sqft left out by the area floor. Six remain:
# ordered 460, 480, 500, 510, 520, 540; middles 500 and 510; median 505.
SALES = [
    (850_000, 1700),
    (884_000, 1700),
    (816_000, 1700),
    (918_000, 1700),
    (782_000, 1700),
    (867_000, 1700),
    (400_000, 150),
]


def test_the_reference_takes_the_middles_after_the_area_floor():
    s = subject(living_area=1700, list_price=850_000)  # 850,000 / 1,700 = 500
    evidence = reference_price_check(SALES, s)
    # 500 / 505 - 1 = -0.99% -> -1.
    assert (evidence.count, evidence.delta_pct) == (6, -1.0)
    assert evidence.median_price_per_sqft == 505
    assert evidence == price_check(city(6, 500, 510), s)


def test_the_reference_widens_only_below_the_minimum():
    s = subject(living_area=1700, list_price=850_000)
    five = SALES[:5]  # 500, 520, 480, 540, 460 -> median 500 -> "at"
    assert reference_price_check(five, s, zip_sales=SALES).level == "city"
    four = SALES[:4]
    widened = reference_price_check(four, s, zip_sales=SALES)
    assert (widened.level, widened.area, widened.widened_from) == (
        "postal_code",
        "91016",
        "Monrovia",
    )
    assert widened.count == 6
    short = reference_price_check(four, s, zip_sales=SALES[:3])
    assert (short.level, short.count, short.sentence) == (
        "postal_code",
        3,
        NOT_ENOUGH_SENTENCE,
    )
    with pytest.raises(ValueError):
        reference_price_check(four, s)


def test_the_reference_matches_the_sql_style_middles_for_floats():
    """Doubles from the driver go through their shortest repr, as the db layer does."""
    s = subject(living_area=1700, list_price=850_000)
    as_doubles = [(float(c), float(a)) for c, a in SALES]
    assert reference_price_check(as_doubles, s) == reference_price_check(SALES, s)


def test_the_reference_for_a_not_checkable_subject():
    evidence = reference_price_check(SALES, Uncheckable("bedrooms"))
    assert evidence.sentence == NOT_CHECKABLE_SENTENCE
