"""Alert text comes only from validated filters and public listing cards."""

from idx_agent.channels.format import format_filters, format_listing_card
from idx_agent.email.bodies import check_content, dates_footer
from idx_agent.enrichment.access import LIMITATION


def feature_lines(snapshot, left_out):
    """WO-025: what a feature alert matched on, what it left out, and its limits."""
    text = (
        "Listing features were matched only where the description states them, "
        f"as of the {snapshot} snapshot; listings first listed after it are "
        "checked once it is rebuilt."
    )
    if left_out:
        text += (
            f" {left_out} other new listing(s) changed after the snapshot, so their "
            "features could not be checked; they are not included here and are "
            "checked again once it is rebuilt."
        )
    return text + " " + LIMITATION


def alert_body(search, count, listings, as_of, *, features=None):
    """`features` is (snapshot date, left-out count) for a saved feature search."""
    listings = listings[:10]
    place = search.filters.city or search.filters.postal_code
    subject = f"IDX: {count} new listings in {place}"
    body = (
        f"Saved search: {format_filters(search.filters)}\n"
        f"{count} new matching listings as of {as_of.active}.\n\n"
        + "\n\n".join(format_listing_card(item, as_of.active) for item in listings)
    )
    if count > len(listings):
        body += f"\n\nAnd {count - len(listings)} more; ask for this search in chat."
    if features is not None:
        body += "\n\n" + feature_lines(*features)
    body += '\n\nTo stop alerts, send "stop alerts" in chat.\n' + dates_footer(as_of)
    check_content(subject, body)
    return subject, body
