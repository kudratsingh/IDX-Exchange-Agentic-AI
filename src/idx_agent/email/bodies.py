"""Code-built email text with a final restricted-content backstop."""

from __future__ import annotations

import re

from idx_agent.channels.format import format_listing_card
from idx_agent.domain.results import AsOf
from idx_agent.observability.logging import redact
from idx_agent.safety.approval import ApprovalRefused
from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

FOOTER = "Delivery requires the owner's approval of this exact draft."


def check_content(subject: str, body: str, *, allow_photos: bool = False) -> None:
    scanned_body = body
    if allow_photos:
        from idx_agent.email.photos import safe_photo_url

        lines = []
        for line in body.splitlines():
            match = re.fullmatch(r"Photo ([1-3]): (https://\S+)", line)
            if match and safe_photo_url(match[2]):
                line = f"Photo {match[1]}: [validated feed image reference]"
            lines.append(line)
        scanned_body = "\n".join(lines)
    text = subject + "\n" + scanned_body
    if (
        not subject.strip()
        or not body.strip()
        or "\n" in subject
        or "\r" in subject
        or len(subject) > 200
        or len(body) > 100_000
    ):
        raise ApprovalRefused("safety_refusal")
    if (
        redact(text) != text
        or "@" in text
        or re.search(r"(?<!\d)\+?\d{10,15}(?!\d)", text)
        or any(name.lower() in text.lower() for name in AGENT_CONTACT | DENYLIST)
    ):
        raise ApprovalRefused("safety_refusal")


def dates_footer(as_of: AsOf) -> str:
    return f"Listings as of {as_of.active}; closed sales to {as_of.sold}.\n{FOOTER}"


def listing_body(listings, as_of: AsOf, missing: int = 0) -> tuple[str, str]:
    cards = "\n\n".join(format_listing_card(item, as_of.active) for item in listings)
    if missing:
        cards += f"\n\n{missing} requested listings are no longer available."
    subject = f"IDX: {len(listings)} active homes, as of {as_of.active}"
    return subject, cards + "\n\n" + dates_footer(as_of)


def market_body(message: str, as_of: AsOf) -> tuple[str, str]:
    return (
        f"IDX market summary, sales to {as_of.sold}",
        message + "\n\n" + dates_footer(as_of),
    )


def document_body(chunks) -> tuple[str, str]:
    # Only schema notes, glossary and saved market cards are authored by this project.
    own_sources = {"schema_notes", "glossary", "summaries"}
    passages = [
        f"{c.source_doc}: {c.section_or_field}\n{c.text}"
        for c in chunks
        if c.source_doc in own_sources and c.text.strip()
    ]
    if not passages:
        raise ApprovalRefused("no_shareable_answer")
    if any(c.source_doc not in own_sources for c in chunks):
        passages.append("Licensed reference passages are omitted from this email.")
    return "IDX reference notes", "\n\n".join(passages) + "\n\n" + FOOTER
