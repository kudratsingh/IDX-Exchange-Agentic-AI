"""Valid value sets the parser validates against (docs/CONTRACTS.md, WO-002).

PROVISIONAL until the profiling run: the sets below hold only the shapes and the
normalization rules. The WO-002 run fills CITIES and SUBTYPES from the generated
docs/data/schema_notes.md (sections 5 and 6), and the status decision names which
column and values mean "active". Parsing never guesses: a value outside these sets is a
validation error or a follow-up question.
"""

from __future__ import annotations

import re

PROVISIONAL = True


def normalize_city(value: str) -> str:
    """Casing and spacing normalization used on both the data and the user's text."""
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
    if value is None:
        return None
    key = value.strip().upper()
    if key in FLAG_TRUE:
        return True
    if key in FLAG_FALSE:
        return False
    return None
