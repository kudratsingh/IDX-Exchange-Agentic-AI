"""Compare draft preview numbers after a reply is available; never alter output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Literal

from idx_agent.observability.logging import log_event

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
)
_UNIT = re.compile(
    r"^\s*[- ]?(sq\s*ft|sqft|square\s+feet|beds?|bedrooms?|"
    r"baths?|bathrooms?|days?\s+on\s+market|photos?|sales?)\b",
    re.IGNORECASE,
)
_TRACE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_MAX_TEXT = 100_000
_MAX_NUMBERS = 4096


@dataclass(frozen=True)
class PreviewCheck:
    """Only counts and status leave the comparison; source text stays in memory."""

    status: Literal["match", "mismatch", "unavailable"]
    source_numbers: int = 0
    reply_numbers: int = 0
    mismatch_count: int = 0


def _numbers(text: str) -> list[tuple[Decimal, str]]:
    values = []
    for match in _NUMBER.finditer(text):
        unit_match = _UNIT.match(text[match.end() :])
        unit = unit_match.group(1).lower().replace(" ", "") if unit_match else ""
        if unit in {"sqft", "squarefeet"}:
            unit = "sqft"
        elif unit.startswith(("bed", "bedroom")):
            unit = "beds"
        elif unit.startswith(("bath", "bathroom")):
            unit = "baths"
        elif unit.startswith("day"):
            unit = "daysonmarket"
        elif unit.startswith("photo"):
            unit = "photos"
        elif unit.startswith("sale"):
            unit = "sales"
        elif not unit and match.start() > 0 and text[match.start() - 1] == "$":
            unit = "currency"
        values.append((Decimal(match.group().replace(",", "")), unit))
    return values


def verify_preview_numbers(
    payload: str | None, reply: str | None, *, trace_id: str
) -> PreviewCheck:
    """Compare ordered numeric tokens and log only counts for a mismatch.

    The caller supplies both texts after generation. This function neither sees
    nor changes a gateway reply, and missing/truncated inputs are not a pass.
    """
    if (
        not isinstance(payload, str)
        or not isinstance(reply, str)
        or not payload.strip()
        or not reply.strip()
        or len(payload) > _MAX_TEXT
        or len(reply) > _MAX_TEXT
        or not isinstance(trace_id, str)
        or not _TRACE.fullmatch(trace_id)
    ):
        return PreviewCheck("unavailable")
    try:
        expected, actual = _numbers(payload), _numbers(reply)
    except InvalidOperation:
        return PreviewCheck("unavailable")
    if not expected or len(expected) > _MAX_NUMBERS or len(actual) > _MAX_NUMBERS:
        return PreviewCheck("unavailable")
    changes = SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
    mismatches = sum(
        max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in changes if op != "equal"
    )
    result = PreviewCheck(
        "mismatch" if mismatches else "match", len(expected), len(actual), mismatches
    )
    if mismatches:
        log_event(
            "draft_preview_numeric_mismatch",
            trace_id,
            source_numbers=result.source_numbers,
            reply_numbers=result.reply_numbers,
            mismatch_count=result.mismatch_count,
        )
    return result
