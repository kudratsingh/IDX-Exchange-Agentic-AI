"""Tests for the WhatsApp formatter in idx_agent.channels.format (WO-004, WO-008).

All listings and market figures here are invented. They cover the card lines and
their fallbacks, the reply wrapper, the filters line, the market card and the
not-enough-comps reply, and the safety checks: remarks and agent or deny-listed
field names never reach the output.
"""

from __future__ import annotations

from datetime import date

import pytest

from idx_agent.channels.format import (
    MAX_CARDS,
    format_filters,
    format_listing_card,
    format_market_reply,
    format_not_enough_comps,
    format_search_reply,
)
from idx_agent.domain.models import (
    Geography,
    Listing,
    MarketStats,
    MonthRow,
    PropertySearchFilters,
    StatsWindow,
)
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

AS_OF = date(2026, 9, 18)
SENTINEL = "SENTINEL-REMARK-ZQ7"
# Remarks stuffed with the sentinel and every forbidden column name; none may leak.
POISONED_REMARKS = " ".join([SENTINEL, *sorted(AGENT_CONTACT), *sorted(DENYLIST)])


def make_listing(**overrides: object) -> Listing:
    """An invented, fully filled listing; keyword overrides replace single fields."""
    fields: dict[str, object] = {
        "listing_key": 900001,
        "listing_id": "TEST-0001",
        "address": "42 Invented Way",
        "city": "Pasadena",
        "postal_code": "91101",
        "list_price": 1250000,
        "bedrooms": 3,
        "bathrooms": 2.0,
        "living_area": 1800,
        "property_subtype": "SingleFamilyResidence",
        "status": "Active",
        "year_built": 1962,
        "hoa_fee_monthly": 350,
        "days_on_market": 12,
        "photo_count": 3,
        "remarks": POISONED_REMARKS,
    }
    fields.update(overrides)
    return Listing(**fields)


def test_full_card_lines() -> None:
    assert format_listing_card(make_listing(), AS_OF).splitlines() == [
        "*42 Invented Way*",
        "Pasadena 91101",
        "$1,250,000",
        "3 beds · 2 baths · 1,800 sqft",
        "Single Family Residence · built 1962",
        "HOA $350/month",
        "12 days on market (as of 2026-09-18)",
        "3 photos",
    ]


@pytest.mark.parametrize(
    ("pool", "view", "line"),
    [
        (True, None, "pool"),
        (False, None, "no pool marked"),
        (None, True, "view"),
        (None, False, "no view marked"),
        (False, True, "no pool marked · view"),
    ],
)
def test_flag_line_when_known(pool: bool | None, view: bool | None, line: str) -> None:
    lines = format_listing_card(make_listing(pool=pool, view=view), AS_OF).splitlines()
    assert line in lines
    assert lines.index(line) == lines.index("HOA $350/month") + 1


def test_no_flag_line_when_unknown() -> None:
    card = format_listing_card(make_listing(), AS_OF)
    assert "pool" not in card and "view" not in card


def test_missing_address_falls_back_to_city_and_zip() -> None:
    lines = format_listing_card(make_listing(address=None), AS_OF).splitlines()
    assert lines[0] == "*Pasadena 91101*"
    # The city line is not repeated under the fallback heading.
    assert lines[1] == "$1,250,000"


def test_missing_address_city_and_zip() -> None:
    listing = make_listing(address=None, city=None, postal_code=None)
    assert format_listing_card(listing, AS_OF).splitlines()[0] == "*Address not shown*"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"bedrooms": None}, "2 baths · 1,800 sqft"),
        ({"bathrooms": None}, "3 beds · 1,800 sqft"),
        ({"living_area": None}, "3 beds · 2 baths"),
        ({"bedrooms": 1, "bathrooms": 1.0}, "1 bed · 1 bath · 1,800 sqft"),
    ],
)
def test_size_line_skips_missing_parts(
    overrides: dict[str, object], expected: str
) -> None:
    lines = format_listing_card(make_listing(**overrides), AS_OF).splitlines()
    assert lines[3] == expected


def test_size_line_dropped_when_all_missing() -> None:
    listing = make_listing(bedrooms=None, bathrooms=None, living_area=None)
    card = format_listing_card(listing, AS_OF)
    assert "bed" not in card and "bath" not in card and "sqft" not in card


def test_half_bath_display() -> None:
    card = format_listing_card(make_listing(bathrooms=2.5), AS_OF)
    assert "2.5 baths" in card


def test_missing_year_and_subtype() -> None:
    card = format_listing_card(make_listing(year_built=None), AS_OF)
    assert "built" not in card
    assert "Single Family Residence" in card
    bare = format_listing_card(
        make_listing(year_built=None, property_subtype=None), AS_OF
    )
    assert "Single Family" not in bare and "built" not in bare


def test_missing_hoa_days_and_photos() -> None:
    listing = make_listing(hoa_fee_monthly=None, days_on_market=None, photo_count=0)
    lines = format_listing_card(listing, AS_OF).splitlines()
    assert not any(line.startswith("HOA") for line in lines)
    assert "Days on market not given (as of 2026-09-18)" in lines
    assert lines[-1] == "No photos"


@pytest.mark.parametrize(
    ("price", "shown"),
    [(0, "$0"), (999, "$999"), (1250000, "$1,250,000"), (12500000, "$12,500,000")],
)
def test_price_formatting(price: int, shown: str) -> None:
    lines = format_listing_card(make_listing(list_price=price), AS_OF).splitlines()
    assert lines[2] == shown


def test_stray_newlines_in_stored_text_stay_on_one_line() -> None:
    card = format_listing_card(make_listing(address="42 Invented\nWay"), AS_OF)
    assert card.splitlines()[0] == "*42 Invented Way*"


def test_remarks_sentinel_never_in_card_or_reply() -> None:
    listing = make_listing()
    assert SENTINEL not in format_listing_card(listing, AS_OF)
    assert SENTINEL not in format_search_reply([listing], AS_OF)


def test_no_forbidden_field_names_in_any_output() -> None:
    listings = [make_listing(listing_key=900001 + i) for i in range(7)]
    filters = PropertySearchFilters(city="Pasadena", min_beds=2, pool=True)
    outputs = [
        format_listing_card(listings[0], AS_OF),
        format_search_reply(listings, AS_OF, format_filters(filters)),
        format_search_reply([], AS_OF, format_filters(filters)),
        format_filters(filters),
    ]
    for text in outputs:
        for name in AGENT_CONTACT | DENYLIST:
            assert name not in text, name


def test_empty_reply() -> None:
    assert format_search_reply([], AS_OF) == (
        "No active listings matched on page 1, as of 2026-09-18."
    )
    assert format_search_reply([], AS_OF, page=3).startswith(
        "No active listings matched on page 3"
    )


def test_reply_summary_and_filters_line() -> None:
    reply = format_search_reply([make_listing()], AS_OF, "Filters: city Pasadena")
    sections = reply.split("\n\n")
    assert sections[0] == "Showing 1 active listing on page 1, as of 2026-09-18"
    assert sections[1] == format_listing_card(make_listing(), AS_OF)
    assert sections[-1] == "Filters: city Pasadena"


def test_reply_renders_every_listing_of_the_page() -> None:
    """A limit of 10 shows 10 cards, so page 2 starts where this reply ends."""
    listings = [
        make_listing(listing_key=900001 + i, address=f"{i + 1} Invented Way")
        for i in range(10)
    ]
    sections = format_search_reply(listings, AS_OF, page=2).split("\n\n")
    assert sections[0] == "Showing 10 active listings on page 2, as of 2026-09-18"
    assert len(sections) == 1 + 10
    assert "*10 Invented Way*" in sections[-1]


def test_reply_caps_cards_at_the_row_limit() -> None:
    listings = [
        make_listing(listing_key=900001 + i, address=f"{i + 1} Invented Way")
        for i in range(MAX_CARDS + 3)
    ]
    sections = format_search_reply(listings, AS_OF).split("\n\n")
    assert len(sections) == 1 + MAX_CARDS + 1
    assert sections[-1] == "and 3 more"


def test_question_is_the_last_section_after_the_filters() -> None:
    """WO-006: the narrowing question ends the reply, after the filters line."""
    question = "A budget or a home type to narrow it?"
    reply = format_search_reply(
        [make_listing()], AS_OF, "Filters: city Pasadena", question=question
    )
    sections = reply.split("\n\n")
    assert sections[-2] == "Filters: city Pasadena"
    assert sections[-1] == question
    assert reply.splitlines()[-1] == question


def test_no_question_leaves_the_reply_unchanged() -> None:
    listing = make_listing()
    plain = format_search_reply([listing], AS_OF, "Filters: city Pasadena")
    for empty in (None, ""):
        assert (
            format_search_reply(
                [listing], AS_OF, "Filters: city Pasadena", question=empty
            )
            == plain
        )


def test_question_stays_on_one_line() -> None:
    reply = format_search_reply([], AS_OF, question="Narrow\nit?")
    assert reply.splitlines()[-1] == "Narrow it?"


def test_filters_only_set_fields() -> None:
    filters = PropertySearchFilters(city="Pasadena", min_price=500000)
    assert format_filters(filters) == "Filters: city Pasadena, price from $500,000"


def test_filters_all_fields_in_words() -> None:
    filters = PropertySearchFilters(
        city="Pasadena",
        postal_code="91101",
        min_price=500000,
        max_price=1000000,
        min_beds=3,
        min_baths=2.5,
        min_sqft=1500,
        property_subtype="Condominium",
        pool=False,
        view=True,
        max_hoa_monthly=400,
        page=2,
    )
    assert format_filters(filters) == (
        "Filters: city Pasadena, ZIP 91101, price $500,000 to $1,000,000, "
        "at least 3 beds, at least 2.5 baths, at least 1,500 sqft, Condominium, "
        "without pool, with view, HOA at most $400/month, page 2"
    )


def test_filters_show_stored_city_spelling() -> None:
    filters = PropertySearchFilters(city="  mcfarland ")
    assert format_filters(filters) == "Filters: city McFarland"


def test_filters_empty() -> None:
    assert format_filters(PropertySearchFilters()) == "Filters: none"


def test_functions_are_pure() -> None:
    listing = make_listing()
    listings = [listing, make_listing(listing_key=900002)]
    filters = PropertySearchFilters(city="Pasadena", max_price=900000)
    before = listing.model_dump()
    assert format_listing_card(listing, AS_OF) == format_listing_card(listing, AS_OF)
    first = format_search_reply(listings, AS_OF, "Filters: none")
    assert format_search_reply(listings, AS_OF, "Filters: none") == first
    assert format_filters(filters) == format_filters(filters)
    assert listing.model_dump() == before
    assert len(listings) == 2


# --- WO-008: the market card and the not-enough-comps reply ---

SOLD = date(2026, 9, 17)
WINDOW_6 = StatsWindow(start=date(2026, 3, 18), end=SOLD, months=6)
RULES = (
    "after_active_asof",
    "unreadable_close_date",
    "close_before_contract",
    "price_under_floor",
    "duplicate_listing_key",
    "area_under_floor",
    "dom_missing",
)
MIX = (("Condominium", 4), (None, 1), ("Townhouse", 0))


def _excluded(**counts: int) -> list[str]:
    """One "rule: count" entry per rule, as build_market_stats writes them."""
    return [f"{name}: {counts.get(name, 0)}" for name in RULES]


def make_stats(**overrides: object) -> MarketStats:
    """Invented Monrovia single-family figures over six months (11 sales, 10 with
    days on market, enough for every median); overrides replace."""
    fields: dict[str, object] = {
        "geography": Geography(city="Monrovia"),
        "property_subtype": "SingleFamilyResidence",
        "window": WINDOW_6,
        "as_of": SOLD,
        "sample_count": 11,
        "low_sample": False,
        "median_close_price": 1_050_000.0,
        "median_price_per_sqft": 706.0,
        "median_dom": 21.5,
        "dom_band": "low",
        "sale_to_list_ratio": 1.012,
        "sale_to_list_reading": "1% over asking",
        "market_lean": "seller",
        "trend": [
            MonthRow(month="2026-03", sample_count=1),
            MonthRow(month="2026-04", sample_count=0),
            MonthRow(month="2026-05", sample_count=3, median_close_price=1_000_000.0),
            MonthRow(month="2026-06", sample_count=0),
            MonthRow(month="2026-07", sample_count=6, median_close_price=1_150_000.0),
            MonthRow(month="2026-08", sample_count=0),
            MonthRow(month="2026-09", sample_count=1),
        ],
        "exclusions_applied": _excluded(close_before_contract=1, dom_missing=1),
    }
    fields.update(overrides)
    return MarketStats(**fields)


def make_few(count: int, window: StatsWindow = WINDOW_6, **overrides: object):
    """An invented under-minimum result: the count, no figures, empty trend."""
    fields: dict[str, object] = {
        "geography": Geography(city="Monrovia"),
        "property_subtype": "SingleFamilyResidence",
        "window": window,
        "as_of": SOLD,
        "sample_count": count,
        "low_sample": True,
        "exclusions_applied": _excluded(price_under_floor=2),
    }
    fields.update(overrides)
    return MarketStats(**fields)


def test_market_card_layout() -> None:
    """The whole card, pinned: head lines, trend, exclusions, other types."""
    assert format_market_reply(make_stats(), MIX, SOLD) == "\n".join(
        [
            "*Market in Monrovia: Single Family Residence*",
            "Last 6 months, 2026-03-18 to 2026-09-17 (sales to 2026-09-17)",
            "11 sales",
            "Median price $1,050,000",
            "Median price per sqft $706",
            "Median days on market 21.5 (low)",
            "Sale-to-list 1.012 (1% over asking)",
            "Leans toward sellers",
            "",
            "Trend by month (a median needs at least 3 sales):",
            "2026-03 (partial): 1 sale, too few sales for a median",
            "2026-04: no sales",
            "2026-05: 3 sales, median $1,000,000",
            "2026-06: no sales",
            "2026-07: 6 sales, median $1,150,000",
            "2026-08: no sales",
            "2026-09 (partial): 1 sale, too few sales for a median",
            "",
            "Left out: 1 closed before its contract date; "
            "1 days on market missing (days median only)",
            "",
            "Single Family Residence only by default. Other types sold here in the "
            "same window: Condominium 4, unknown type 1",
        ]
    )


def test_market_card_months_cut_by_the_window_only() -> None:
    """A window from the 1st to a month's last day marks no month partial."""
    window = StatsWindow(start=date(2026, 4, 1), end=date(2026, 6, 30), months=3)
    trend = [
        MonthRow(month=m, sample_count=3, median_close_price=900_000.0)
        for m in ("2026-04", "2026-05", "2026-06")
    ]
    stats = make_stats(window=window, as_of=date(2026, 6, 30), trend=trend)
    text = format_market_reply(stats, MIX, date(2026, 6, 30))
    assert "(partial)" not in text
    assert "2026-06: 3 sales, median $900,000" in text
    assert "Last 3 months, 2026-04-01 to 2026-06-30 (sales to 2026-06-30)" in text


def test_market_card_mix_line_only_for_the_default_subtype() -> None:
    stats = make_stats(property_subtype="Condominium")
    named = format_market_reply(stats, MIX, SOLD, default_subtype=False)
    assert "Other types" not in named and "by default" not in named
    assert "Other types" not in format_market_reply(make_stats(), None, SOLD)
    empty = format_market_reply(make_stats(), (), SOLD)
    assert empty.endswith(
        "Single Family Residence only by default. No other types sold here in the "
        "same window."
    )


@pytest.mark.parametrize(
    ("band", "lean", "band_words", "lean_words"),
    [
        ("very_low", "seller", "(very low)", "Leans toward sellers"),
        ("low", "balanced", "(low)", "Balanced between buyers and sellers"),
        ("average", "balanced", "(average)", "Balanced between buyers and sellers"),
        ("high", "buyer", "(high)", "Leans toward buyers"),
    ],
)
def test_market_card_band_and_lean_in_words(band, lean, band_words, lean_words) -> None:
    text = format_market_reply(make_stats(dom_band=band, market_lean=lean), MIX, SOLD)
    assert f"Median days on market 21.5 {band_words}" in text
    assert lean_words in text


def test_market_card_missing_figures_say_so() -> None:
    """Fewer than 10 usable days or areas: the lines say not available, and why."""
    stats = make_stats(
        median_price_per_sqft=None, median_dom=None, dom_band=None, market_lean=None
    )
    text = format_market_reply(stats, MIX, SOLD)
    reason = "not available (fewer than 10 sales with a usable value)"
    assert f"Median price per sqft {reason}" in text.splitlines()
    assert f"Median days on market {reason}" in text.splitlines()
    assert "Leans" not in text and "Balanced" not in text


def test_market_card_zip_whole_days_and_no_exclusions() -> None:
    stats = make_stats(
        geography=Geography(postal_code="91016"),
        median_dom=21.0,
        exclusions_applied=_excluded(),
    )
    text = format_market_reply(stats, MIX, SOLD)
    assert text.startswith("*Market in ZIP 91016: Single Family Residence*")
    assert "Median days on market 21 (low)" in text
    assert "Left out: none" in text


def test_market_card_every_exclusion_in_words() -> None:
    counts = dict.fromkeys(RULES, 1)
    text = format_market_reply(
        make_stats(exclusions_applied=_excluded(**counts)), MIX, SOLD
    )
    line = next(x for x in text.split("\n") if x.startswith("Left out:"))
    for words in (
        "close date after the data date",
        "close date unreadable",
        "closed before its contract date",
        "price under $25,000",
        "repeated listing (latest sale kept)",
        "living area under 200 sqft or missing (price per sqft only)",
        "days on market missing (days median only)",
    ):
        assert f"1 {words}" in line


def test_not_enough_comps_names_count_minimum_window_and_a_longer_window() -> None:
    """Three months under the minimum: the step is the six-month window."""
    window = StatsWindow(start=date(2026, 6, 18), end=SOLD, months=3)
    text = format_market_reply(make_few(3, window), MIX, SOLD, widen_months=6)
    first, step, excluded = text.split("\n\n")
    assert first == (
        "*Not enough comps* for Single Family Residence in Monrovia: 3 sales in the "
        "last 3 months, 2026-06-18 to 2026-09-17 (sales to 2026-09-17). Figures need "
        "at least 5."
    )
    assert step == "A longer window may have enough: ask for the last 6 months."
    assert excluded == "Left out: 2 price under $25,000"
    assert "Median" not in text and "Trend" not in text


def test_not_enough_comps_suggests_a_subtype_with_enough_sales() -> None:
    """At six months: the largest known other subtype at or over the minimum."""
    mix = ((None, 30), ("SingleFamilyResidence", 40), ("Townhouse", 4), ("Loft", 6))
    stats = make_few(1, property_subtype="Condominium")
    text = format_not_enough_comps(stats, mix, SOLD, widen_months=6)
    assert "1 sale in the last 6 months" in text
    assert (
        "Single Family Residence has 40 sales here in the same window: ask for that "
        "type to see its figures." in text
    )
    few = ((None, 30), ("Townhouse", 4), ("Condominium", 9))
    assert "Condominium has" not in format_not_enough_comps(stats, few, SOLD)


def test_not_enough_comps_with_no_step_never_names_another_place() -> None:
    stats = make_few(0, geography=Geography(city="Alhambra"))
    text = format_market_reply(stats, ((None, 9), ("Townhouse", 2)), SOLD)
    assert "0 sales in the last 6 months" in text
    assert "Neither a longer window nor another type has enough sales" in text
    assert "Monrovia" not in text and "Pasadena" not in text and "ZIP" not in text


def test_market_text_is_pure_and_names_no_agent_field() -> None:
    stats = make_stats()
    before = stats.model_dump()
    card = format_market_reply(stats, MIX, SOLD)
    assert format_market_reply(stats, MIX, SOLD) == card
    few = format_market_reply(make_few(2), MIX, SOLD, widen_months=6)
    assert stats.model_dump() == before
    for text in (card, few):
        assert not [name for name in AGENT_CONTACT | DENYLIST if name in text]
