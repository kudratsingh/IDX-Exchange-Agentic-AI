"""Channel adapters such as WhatsApp formatting.

Last stage before the user: takes a tool's AgentResult and renders it for a channel.
`format` holds the pure WhatsApp text functions for property search (WO-004).
"""

from idx_agent.channels.format import (
    format_filters,
    format_listing_card,
    format_search_reply,
)

__all__ = ["format_filters", "format_listing_card", "format_search_reply"]
