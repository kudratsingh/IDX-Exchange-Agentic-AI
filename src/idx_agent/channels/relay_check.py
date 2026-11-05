"""Deterministic relay check: did a reply carry a card tool's `message` unchanged?

Model-free detection for acceptance runs and evals, not prevention: it never alters,
sends or blocks a reply and is not wired into the gateway (P1-4, 2026-11-05).
`summary()` reports positions, units and counts only, never listing text or values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Literal

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?"
    r"|(?<![A-Za-z0-9_.])[0-9]+(?:\.[0-9]+)?"
)
_UNIT = re.compile(
    r"\s*(sq\s*ft|sqft|square\s+feet|beds?|bedrooms?|baths?|bathrooms?|"
    r"days?\s+on\s+market|photos?|active\s+listings?|sales?)\b",
    re.IGNORECASE,
)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# A card's first line is its bolded address or place (channels/format.py).
_CARD_TITLE = re.compile(r"^\*[^*\n]+\*$")
_MAX_TEXT = 100_000
_MAX_NUMBERS = 4096

Status = Literal["pass", "fail", "unavailable"]
# exact: the reply is the message. whole: the message is in the reply, and the rest has
# no digit. extra_numbers: the message is whole, but the added text states a number.
# changed: the message is not in the reply unchanged. unavailable: an input is missing,
# empty or too long (never a pass).
Reason = Literal["exact", "whole", "extra_numbers", "changed", "unavailable"]


@dataclass(frozen=True)
class NumberToken:
    """One number in a text, with the unit after it and the card it sits in."""

    value: Decimal
    unit: str  # sqft, beds, baths, days_on_market, photos, listings, sales, price,
    # date, or number
    card: int  # 0 before the first card (the summary line), else 1-based
    line: int


@dataclass(frozen=True)
class RelayMismatch:
    """One numeric difference: the message's token, the reply's, or both."""

    expected: NumberToken | None
    got: NumberToken | None

    @property
    def card(self) -> int:
        return (self.expected or self.got).card  # type: ignore[union-attr]

    @property
    def unit(self) -> str:
        return (self.expected or self.got).unit  # type: ignore[union-attr]


@dataclass(frozen=True)
class RelayCheck:
    status: Status
    reason: Reason
    message_numbers: int = 0
    reply_numbers: int = 0
    extra_digits: int = 0  # digits in the reply outside the message (when whole)
    mismatches: tuple[RelayMismatch, ...] = field(default=())
    # Values in the reply that appear nowhere in the message (e.g. a rounded figure).
    reply_only: tuple[Decimal, ...] = field(default=())

    def summary(self) -> dict[str, Any]:
        """Counts, card positions and units only: no listing text, no values."""
        first = self.mismatches[0] if self.mismatches else None
        return {
            "status": self.status,
            "reason": self.reason,
            "message_numbers": self.message_numbers,
            "reply_numbers": self.reply_numbers,
            "extra_digits": self.extra_digits,
            "mismatch_count": len(self.mismatches),
            "first_mismatch": (
                None if first is None else {"card": first.card, "unit": first.unit}
            ),
            "reply_only_count": len(self.reply_only),
        }


def _normalize(text: str) -> str:
    """Line endings to \\n, trailing spaces off each line, outer blank lines off."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _unit(text: str, start: int, end: int) -> str:
    if start > 0 and text[start - 1] == "$":
        return "price"
    if _DATE.match(text, start):
        return "date"
    match = _UNIT.match(text, end)
    if not match:
        return "number"
    word = re.sub(r"\s+", "", match.group(1).lower())
    if word in {"sqft", "squarefeet"}:
        return "sqft"
    for prefix, unit in (
        ("bed", "beds"),
        ("bath", "baths"),
        ("day", "days_on_market"),
        ("photo", "photos"),
        ("active", "listings"),
        ("sale", "sales"),
    ):
        if word.startswith(prefix):
            return unit
    return "number"


def number_tokens(text: str) -> list[NumberToken]:
    """Every number in `text` in order, with its unit and card position."""
    tokens: list[NumberToken] = []
    card = 0
    for line_no, line in enumerate(text.split("\n"), 1):
        if _CARD_TITLE.match(line.strip()):
            card += 1
        for match in _NUMBER.finditer(line):
            tokens.append(
                NumberToken(
                    Decimal(match.group().replace(",", "")),
                    _unit(line, match.start(), match.end()),
                    card,
                    line_no,
                )
            )
    return tokens


def check_card_relay(message: str | None, reply: str | None) -> RelayCheck:
    """Compare a card tool's `message` with the visible reply.

    Pass only for the message itself, or the message whole with digit-free added text;
    else fail, each numeric difference tied to a card and unit. Missing, empty or
    oversized input is `unavailable`, never a pass."""
    if (
        not isinstance(message, str)
        or not isinstance(reply, str)
        or not message.strip()
        or not reply.strip()
        or len(message) > _MAX_TEXT
        or len(reply) > _MAX_TEXT
    ):
        return RelayCheck("unavailable", "unavailable")
    msg, rep = _normalize(message), _normalize(reply)
    try:
        expected, actual = number_tokens(msg), number_tokens(rep)
    except InvalidOperation:
        return RelayCheck("unavailable", "unavailable")
    if len(expected) > _MAX_NUMBERS or len(actual) > _MAX_NUMBERS:
        return RelayCheck("unavailable", "unavailable")
    mismatches: list[RelayMismatch] = []
    pairs = SequenceMatcher(
        None,
        [(t.value, t.unit) for t in expected],
        [(t.value, t.unit) for t in actual],
        autojunk=False,
    ).get_opcodes()
    for op, i1, i2, j1, j2 in pairs:
        if op == "equal":
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            mismatches.append(
                RelayMismatch(
                    expected[i1 + k] if i1 + k < i2 else None,
                    actual[j1 + k] if j1 + k < j2 else None,
                )
            )
    reply_only = tuple(sorted({t.value for t in actual} - {t.value for t in expected}))
    counts = {
        "message_numbers": len(expected),
        "reply_numbers": len(actual),
        "mismatches": tuple(mismatches),
        "reply_only": reply_only,
    }
    if msg == rep:
        return RelayCheck("pass", "exact", **counts)
    if msg in rep:
        extra = rep.replace(msg, "", 1)
        digits = sum(c.isdigit() for c in extra)
        if digits == 0:
            return RelayCheck("pass", "whole", **counts)
        return RelayCheck("fail", "extra_numbers", extra_digits=digits, **counts)
    return RelayCheck("fail", "changed", **counts)
