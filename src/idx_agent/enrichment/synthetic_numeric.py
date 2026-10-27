"""Narrow numeric annotation experiment for invented examples only."""

from __future__ import annotations

import re
from dataclasses import dataclass

from idx_agent.domain.enrichment import MAX_REMARKS_CHARS


@dataclass(frozen=True)
class NumericCandidate:
    """A numeric candidate and its original, half-open source span."""

    field: str
    value: int | float
    start: int
    end: int
    quote: str


_PATTERNS = (
    ("bedrooms", re.compile(r"^the home has (?P<quote>(?P<n>\d+) bedrooms)\b", re.I)),
    (
        "bedrooms",
        re.compile(r"^a (?P<quote>(?P<n>\d+)-bedroom property total)\b", re.I),
    ),
    (
        "living_area_sqft",
        re.compile(
            r"^the home has (?P<quote>(?P<n>\d[\d,]*) sqft of living area)\b", re.I
        ),
    ),
    ("asking_price_usd", re.compile(r"^(?P<quote>asking \$(?P<n>\d[\d,]*))\b", re.I)),
)
_BATHS = re.compile(
    r"^the home has (?P<quote>(?P<full>\d+) full and (?P<half>\d+) half baths)\b", re.I
)


def extract_invented_numbers(text: str) -> tuple[NumericCandidate, ...]:
    """Extract a few anchored patterns; this does not certify source provenance."""
    if (
        not isinstance(text, str)
        or not text
        or len(text) > MAX_REMARKS_CHARS
        or "\x00" in text
    ):
        raise ValueError("invalid synthetic text")
    results = []
    for field, pattern in _PATTERNS:
        match = pattern.match(text)
        if match:
            value = int(match.group("n").replace(",", ""))
            results.append(
                NumericCandidate(
                    field, value, *match.span("quote"), match.group("quote")
                )
            )
    match = _BATHS.match(text)
    if match:
        value = int(match.group("full")) + int(match.group("half")) / 2
        results.append(
            NumericCandidate(
                "bathrooms", value, *match.span("quote"), match.group("quote")
            )
        )
    return tuple(results)
