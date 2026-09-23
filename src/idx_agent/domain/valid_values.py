"""Valid value sets the parser checks against: user text -> parser -> db query.

PROVISIONAL (WO-002, docs/CONTRACTS.md): the profiling run fills CITIES, SUBTYPES,
and the "active" status column/values from docs/data/schema_notes.md sections 5-6.
Parsing never guesses: an out-of-set value is a validation error or a follow-up.
"""

from __future__ import annotations

import re

# True until the profiling run replaces the empty sets below with real values.
PROVISIONAL = True


def normalize_city(value: str) -> str:
    """Casing and spacing normalization used on both the data and the user's text.

    Trims, collapses inner whitespace to one space, and title-cases, so that
    "  san  JOSE " and "San Jose" compare equal. Returns the normalized string.
    """
    return re.sub(r"\s+", " ", value.strip()).title()


# Filled from the profiling run: normalized city names present in either table.
CITIES: frozenset[str] = frozenset()

# Filled from the profiling run: PropertySubType (sold) and L_Type_ (active) values,
# plus the mapping between the two vocabularies where they differ.
SUBTYPES: frozenset[str] = frozenset()
SUBTYPE_MAP_ACTIVE_TO_RESO: dict[str, str] = {}

# Status: the column and values that define "active" (decision recorded in
# docs/data/schema_notes.md and docs/DECISIONS.md after the run).
ACTIVE_STATUS_COLUMN: str | None = None
ACTIVE_STATUS_VALUES: frozenset[str] = frozenset()

# True/False/empty flag encodings seen in the data ("Y"/"N", "1"/"0", "True"/"False").
FLAG_TRUE: frozenset[str] = frozenset({"Y", "YES", "1", "TRUE", "T"})
FLAG_FALSE: frozenset[str] = frozenset({"N", "NO", "0", "FALSE", "F"})


def parse_flag(value: str | None) -> bool | None:
    """Map a raw yes/no column value to True, False, or None.

    Case- and whitespace-insensitive match against FLAG_TRUE / FLAG_FALSE.
    None, empty, or unrecognized input returns None (unknown), never a guess.
    """
    if value is None:
        return None
    key = value.strip().upper()
    if key in FLAG_TRUE:
        return True
    if key in FLAG_FALSE:
        return False
    return None
