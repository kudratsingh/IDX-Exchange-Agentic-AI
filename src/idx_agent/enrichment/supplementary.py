"""Deterministic keyword selection for owner-labeled deal-signal remarks."""

from __future__ import annotations

import hashlib
import re
from bisect import insort
from collections.abc import Iterable

SEED = "deal-signals-20261028-v1"
PATTERNS = {
    "as_is": re.compile(r"\bas[\s-]+is\b", re.I),
    "back_on_market": re.compile(r"\bback\s+(?:on|to)\s+(?:the\s+)?market\b", re.I),
    "price_reduction": re.compile(
        r"\b(?:price\s+(?:reduced|reduction|cut|improved|improvement)|"
        r"(?:reduced|reduction|cut|lowered)\s+(?:asking\s+)?price|"
        r"(?:just\s+)?reduced)\b",
        re.I,
    ),
}


def select(source: Iterable[tuple[str, str]], excluded: set[str], count: int = 40):
    """Round-robin keyword buckets after a seeded stable ranking; no text logged."""
    buckets = {name: [] for name in PATTERNS}
    available = dict.fromkeys(PATTERNS, 0)
    for key, remark in source:
        if key in excluded:
            continue
        rank = hashlib.sha256(f"{SEED}:{key}".encode()).hexdigest()
        for name, pattern in PATTERNS.items():
            if pattern.search(remark):
                available[name] += 1
                insort(buckets[name], (rank, key, remark))
                if len(buckets[name]) > count:
                    buckets[name].pop()
    selected, seen, offsets = [], set(), dict.fromkeys(PATTERNS, 0)
    while len(selected) < count:
        progress = False
        for name, values in buckets.items():
            while offsets[name] < len(values):
                _, key, remark = values[offsets[name]]
                offsets[name] += 1
                if key in seen:
                    continue
                selected.append((key, remark, name))
                seen.add(key)
                progress = True
                break
            if len(selected) == count:
                break
        if not progress:
            break
    return selected, available
