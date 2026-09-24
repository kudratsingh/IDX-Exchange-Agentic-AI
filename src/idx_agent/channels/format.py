"""WhatsApp text for property search results: pure functions, no I/O.

Cards read only display fields of a Listing. Remarks are never shown, and a
Listing cannot hold agent or deny-listed fields, so no card can carry them.
Plain text with *bold* and line breaks; WhatsApp renders no tables.
"""

from __future__ import annotations

import re
from datetime import date

from idx_agent.domain.models import Listing, PropertySearchFilters

__all__ = ["MAX_CARDS", "format_filters", "format_listing_card", "format_search_reply"]

# Hard ceiling on cards in one reply, equal to the 50-row query cap; anything past
# it (only possible if the cap ever changes) is counted in an "and N more" line.
MAX_CARDS = 50
# Splits a RESO subtype at inner capitals: "SingleFamilyResidence" -> three words.
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _clean(text: str | None) -> str:
    """Collapse whitespace (newlines too) so a stored value stays on its own line."""
    return re.sub(r"\s+", " ", text).strip() if text else ""


def _money(amount: int) -> str:
    """Whole dollars with thousands separators: 1250000 -> "$1,250,000"."""
    return f"${amount:,}"


def _plural(count: int, word: str) -> str:
    """The count and the word, plural unless the count is 1: "1 bed", "3 beds"."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _baths(count: float) -> str:
    """Bathrooms in whole or half steps: 2.0 -> "2 baths", 2.5 -> "2.5 baths"."""
    # :g drops a trailing .0 and keeps a real half.
    shown = f"{count:g}"
    return f"{shown} bath" if shown == "1" else f"{shown} baths"


def _subtype_words(subtype: str) -> str:
    """RESO subtype as words: "SingleFamilyResidence" -> "Single Family Residence"."""
    return _CAMEL.sub(" ", subtype)


def _place(listing: Listing) -> str:
    """City and ZIP joined by a space, skipping whichever is missing."""
    return " ".join(p for p in (_clean(listing.city), listing.postal_code or "") if p)


def format_listing_card(listing: Listing, as_of: date) -> str:
    """Return one short WhatsApp card for a listing, one fact per line.

    Lines with nothing to show are skipped. With no street address the first line
    falls back to city and ZIP, and the separate city line is dropped.
    `as_of` is the active table's as-of date, shown next to days on market.
    """
    lines: list[str] = []
    address = _clean(listing.address)
    place = _place(listing)
    if address:
        lines.append(f"*{address}*")
        if place:
            lines.append(place)
    else:
        lines.append(f"*{place or 'Address not shown'}*")
    lines.append(_money(listing.list_price))

    size: list[str] = []
    if listing.bedrooms is not None:
        size.append(_plural(listing.bedrooms, "bed"))
    if listing.bathrooms is not None:
        size.append(_baths(listing.bathrooms))
    if listing.living_area is not None:
        size.append(f"{listing.living_area:,} sqft")
    if size:
        lines.append(" · ".join(size))

    kind: list[str] = []
    if listing.property_subtype:
        kind.append(_subtype_words(_clean(listing.property_subtype)))
    if listing.year_built is not None:
        kind.append(f"built {listing.year_built}")
    if kind:
        lines.append(" · ".join(kind))

    if listing.hoa_fee_monthly is not None:
        lines.append(f"HOA {_money(listing.hoa_fee_monthly)}/month")

    note = f"(as of {as_of.isoformat()})"
    if listing.days_on_market is not None:
        lines.append(f"{_plural(listing.days_on_market, 'day')} on market {note}")
    else:
        lines.append(f"Days on market not given {note}")

    photos = listing.photo_count
    lines.append(_plural(photos, "photo") if photos else "No photos")
    return "\n".join(lines)


def format_search_reply(
    listings: list[Listing],
    as_of: date,
    applied_filters_text: str | None = None,
    page: int = 1,
) -> str:
    """Return a full reply: a summary line, one card per listing, then the filters.

    Every listing of the page is rendered (the tool caps a page at 50), so page 2
    starts where this reply ends. Sections are separated by a blank line.
    """
    stamp = f"as of {as_of.isoformat()}"
    if not listings:
        sections = [f"No active listings matched on page {page}, {stamp}."]
    else:
        total = len(listings)
        noun = "active listing" if total == 1 else "active listings"
        sections = [f"Showing {total} {noun} on page {page}, {stamp}"]
        sections += [format_listing_card(x, as_of) for x in listings[:MAX_CARDS]]
        if total > MAX_CARDS:
            sections.append(f"and {total - MAX_CARDS} more")
    if applied_filters_text:
        sections.append(_clean(applied_filters_text))
    return "\n\n".join(sections)


def _price_range(low: int | None, high: int | None) -> str | None:
    """Price bounds in words, or None when neither bound is set."""
    if low is not None and high is not None:
        return f"price {_money(low)} to {_money(high)}"
    if low is not None:
        return f"price from {_money(low)}"
    if high is not None:
        return f"price up to {_money(high)}"
    return None


def _yes_no(value: bool | None, word: str) -> str | None:
    """A set flag in words ("with pool" or "without pool"); None when unset."""
    if value is None:
        return None
    return f"with {word}" if value else f"without {word}"


def format_filters(filters: PropertySearchFilters) -> str:
    """Return one line naming the accepted filters in words, only those that are set.

    City shows its stored spelling (the validator already normalized it). Page is
    shown only past page 1; the result limit is a display detail and is left out.
    """
    f = filters
    parts = [
        f"city {f.city}" if f.city else None,
        f"ZIP {f.postal_code}" if f.postal_code else None,
        _price_range(f.min_price, f.max_price),
        f"at least {_plural(f.min_beds, 'bed')}" if f.min_beds is not None else None,
        f"at least {_baths(f.min_baths)}" if f.min_baths is not None else None,
        f"at least {f.min_sqft:,} sqft" if f.min_sqft is not None else None,
        _subtype_words(f.property_subtype) if f.property_subtype else None,
        _yes_no(f.pool, "pool"),
        _yes_no(f.view, "view"),
        (
            f"HOA at most {_money(f.max_hoa_monthly)}/month"
            if f.max_hoa_monthly is not None
            else None
        ),
        f"page {f.page}" if f.page > 1 else None,
    ]
    named = [p for p in parts if p]
    return "Filters: " + (", ".join(named) if named else "none")
