"""Tests for the WhatsApp formatter in idx_agent.channels.format (WO-004).

All listings here are invented. They cover the card lines and their fallbacks,
the reply wrapper, the filters line, and the safety checks: remarks and agent or
deny-listed field names never reach the output.
"""

from __future__ import annotations

from datetime import date

import pytest

from idx_agent.channels.format import (
    MAX_CARDS,
    format_filters,
    format_listing_card,
    format_search_reply,
)
from idx_agent.domain.models import Listing, PropertySearchFilters
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
