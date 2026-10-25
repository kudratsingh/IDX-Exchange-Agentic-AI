"""Bounded abbreviation expansion only; no extraction, I/O or embeddings."""

import re

from idx_agent.domain.enrichment import (
    MAX_NORMALIZED_CHARS,
    MAX_REMARKS_CHARS,
    NormalizedRemarks,
)

_RULES = (
    ("bed_bath_label", r"(?<!\w)BR[ \t]*/[ \t]*BA(?!\w)", "bedrooms/bathrooms"),
    ("bed_count", r"(?<![\w.])(\d+(?:\.\d+)?)[ \t]*BR(?!\w)", r"\1 bedrooms"),
    ("bath_count", r"(?<![\w.])(\d+(?:\.\d+)?)[ \t]*BA(?!\w)", r"\1 bathrooms"),
    ("air_conditioning", r"(?<!\w)A[ \t]*/[ \t]*C(?!\w)", "air conditioning"),
    ("washer_dryer", r"(?<!\w)W[ \t]*/[ \t]*D(?!\w)", "washer/dryer"),
    (
        "stainless_appliances",
        r"(?<!\w)SS[ \t]+appl(?:iances)?(?!\w)",
        "stainless steel appliances",
    ),
    ("vinyl_plank", r"(?<!\w)LVP(?!\w)", "luxury vinyl plank"),
    ("hardwood_context", r"(?<!\w)hwd(?=[ \t]+(?:floors?|flooring)\b)", "hardwood"),
)
_COMPILED = tuple(
    (name, re.compile(pattern, re.I), replacement)
    for name, pattern, replacement in _RULES
)


def normalize_remarks(text: str) -> NormalizedRemarks:
    """Expand known contexts; preserve numbers, negation and unknown words."""
    if not isinstance(text, str):
        raise TypeError("remarks must be text")
    if len(text) > MAX_REMARKS_CHARS:
        raise ValueError("remarks exceed the normalizer input ceiling")
    if "\x00" in text:
        raise ValueError("remarks contain an unsupported control character")
    changed = []
    for name, pattern, replacement in _COMPILED:
        text, count = pattern.subn(replacement, text)
        if count:
            changed.append(name)
        if len(text) > MAX_NORMALIZED_CHARS:
            raise ValueError("normalized remarks exceed the output ceiling")
    return NormalizedRemarks(text=text, applied_rules=tuple(changed))
