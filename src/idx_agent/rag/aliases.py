"""Phrases a user may write for a field, a table, or a measure (WO-012, own words).

Each alias maps to chunk ids in order; retrieval puts the ones present in the index
first, as exact-name hits. Matching ignores case and treats "-" as a space, on word
boundaries; a phrase ending in "*" is a field-name prefix, so it also matches at the
start of a longer name ("ListAgent*" matches ListAgentEmail). Primer targets are
section positions from the spike (decision 13).
"""

from __future__ import annotations

import re

__all__ = ["ALIASES", "PREFIX_MARK", "alias_hits", "normalize"]

PREFIX_MARK = "*"
_DOM = ("trestle#DaysOnMarket", "primer#s8")
_RATIO = ("glossary#sale_to_list_ratio", "primer#s3")
_SOLD = ("schema_notes#california_sold",)
_ACTIVE = ("schema_notes#rets_property",)
# The agent-related Trestle entries are never indexed (the human's decision of
# 2026-09-25); a question about one lands on the glossary entry that says so.
_AGENT = ("glossary#agent_and_office_fields",)

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
    ("agent fields", _AGENT),
    ("agent field", _AGENT),
    ("office fields", _AGENT),
    ("office field", _AGENT),
    ("listing agent", _AGENT),
    ("listing office", _AGENT),
    ("buyer agent", _AGENT),
    ("buyer's agent", _AGENT),
    ("ListAgent*", _AGENT),
    ("ListOffice*", _AGENT),
    ("BuyerAgent*", _AGENT),
    ("BuyerOffice*", _AGENT),
    ("CoListAgent*", _AGENT),
    ("CoListOffice*", _AGENT),
    ("CoBuyerAgent*", _AGENT),
    ("CoBuyerOffice*", _AGENT),
)


def normalize(text: str) -> str:
    """Lowercase, "-" as a space, whitespace collapsed."""
    return " ".join(text.lower().replace("-", " ").split())


def _pattern(phrase: str) -> re.Pattern[str]:
    """Word boundaries on both sides; a prefix phrase leaves the end open."""
    prefix = phrase.endswith(PREFIX_MARK)
    body = re.escape(normalize(phrase.removesuffix(PREFIX_MARK)))
    return re.compile(rf"(?<![a-z0-9_]){body}" + ("" if prefix else r"(?![a-z0-9_])"))


_PATTERNS = tuple((_pattern(phrase), ids) for phrase, ids in ALIASES)


def alias_hits(question: str) -> list[str]:
    """Chunk ids named through an alias in the question: table order, no repeats."""
    text = normalize(question)
    hits: list[str] = []
    for pattern, ids in _PATTERNS:
        if pattern.search(text):
            hits += [cid for cid in ids if cid not in hits]
    return hits
