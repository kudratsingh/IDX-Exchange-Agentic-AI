"""Phrases a user may write for a field, a table, or a measure (WO-012, own words).

Each alias maps to chunk ids in order; retrieval puts the ones present in the index
first, as exact-name hits. Matching ignores case and treats "-" as a space, on word
boundaries. Primer targets are section positions from the spike (decision 13).
"""

from __future__ import annotations

import re

__all__ = ["ALIASES", "alias_hits", "normalize"]

_DOM = ("trestle#DaysOnMarket", "primer#s8")
_RATIO = ("glossary#sale_to_list_ratio", "primer#s3")
_SOLD = ("schema_notes#california_sold",)
_ACTIVE = ("schema_notes#rets_property",)

# Phrase -> chunk ids, in the order retrieval tries them.
ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dom", _DOM),
    ("days on market", _DOM),
    ("cdom", ("trestle#CumulativeDaysOnMarket",)),
    ("list-to-close", _RATIO),
    ("list to close", _RATIO),
    ("sale-to-list", _RATIO),
    ("sale to list", _RATIO),
    ("close-to-list", _RATIO),
    ("sold table", _SOLD),
    ("sold data", _SOLD),
    ("closed sales table", _SOLD),
    ("california_sold", _SOLD),
    ("active table", _ACTIVE),
    ("listings table", _ACTIVE),
    ("rets_property", _ACTIVE),
)


def normalize(text: str) -> str:
    """Lowercase, "-" as a space, whitespace collapsed."""
    return " ".join(text.lower().replace("-", " ").split())


_PATTERNS = tuple(
    (re.compile(rf"(?<![a-z0-9_]){re.escape(normalize(phrase))}(?![a-z0-9_])"), ids)
    for phrase, ids in ALIASES
)


def alias_hits(question: str) -> list[str]:
    """Chunk ids named through an alias in the question: table order, no repeats."""
    text = normalize(question)
    hits: list[str] = []
    for pattern, ids in _PATTERNS:
        if pattern.search(text):
            hits += [cid for cid in ids if cid not in hits]
    return hits
