"""Alert text comes only from validated filters and public listing cards."""

from idx_agent.channels.format import format_filters, format_listing_card
from idx_agent.email.bodies import check_content, dates_footer


def alert_body(search, count, listings, as_of):
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
    body += '\n\nTo stop alerts, send "stop alerts" in chat.\n' + dates_footer(as_of)
    check_content(subject, body)
    return subject, body
