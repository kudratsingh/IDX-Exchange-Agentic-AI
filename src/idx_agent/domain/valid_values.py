"""Valid value sets the parser checks against: user text -> parser -> db query.

Filled from the profiling run of 2026-09-23 (docs/data/schema_notes.md sections 4-6):
city names, property subtypes, the "active" status rule, and the flag encoding.
Parsing never guesses: an out-of-set value is a validation error or a follow-up.
"""

from __future__ import annotations

import re
from pathlib import Path

# False once the sets below come from a profiling run rather than from placeholders.
PROVISIONAL = False


def normalize_city(value: str) -> str:
    """Casing and spacing normalization used on both the data and the user's text.

    Trims, collapses inner whitespace to one space, and title-cases, so that
    "  san  JOSE " and "San Jose" compare equal. Returns the normalized string.
    """
    return re.sub(r"\s+", " ", value.strip()).title()


def _load_cities() -> frozenset[str]:
    """Read cities.txt (one raw city name per line, union of both tables) normalized."""
    path = Path(__file__).with_name("cities.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(normalize_city(line) for line in lines if line.strip())


# 1,082 distinct spellings across both tables; the profiling run found no casing or
# spacing variants, so normalization is a safety net rather than a repair.
CITIES: frozenset[str] = _load_cities()

# Both tables use the RESO PropertySubType vocabulary (L_Type_ in the active table),
# so one set serves both and no mapping is needed. Null subtype rows exist in both.
SUBTYPES: frozenset[str] = frozenset(
    {
        "SingleFamilyResidence",
        "Condominium",
        "Townhouse",
        "ManufacturedOnLand",
        "Duplex",
        "Cabin",
        "StockCooperative",
        "Triplex",
        "MixedUse",
        "MobileHome",
        "Quadruplex",
        "ManufacturedHome",
        "BoatSlip",
        "OwnYourOwn",
        "CoOwnership",
        "Farm",
        "Studio",
        "Timeshare",  # active table only
        "Loft",
        "DeededParking",  # active table only
    }
)
SUBTYPE_MAP_ACTIVE_TO_RESO: dict[str, str] = {}  # identical vocabularies

# Status: every row of rets_property is "Active" in both L_Status and StandardStatus
# (one value each, identical cross-tab). The RESO column is the rule; the sold table
# has no status column and is closed by definition.
ACTIVE_STATUS_COLUMN: str | None = "StandardStatus"
ACTIVE_STATUS_VALUES: frozenset[str] = frozenset({"Active"})

# Flag encoding seen in both tables (ViewYN, PoolPrivateYN, FireplaceYN): "1" means
# yes; an empty string means the feature was not marked; null means unknown.
FLAG_TRUE: frozenset[str] = frozenset({"Y", "YES", "1", "TRUE", "T"})
FLAG_FALSE: frozenset[str] = frozenset({"N", "NO", "0", "FALSE", "F", ""})


def parse_flag(value: str | None) -> bool | None:
    """Map a raw yes/no column value to True, False, or None.

    Case- and whitespace-insensitive match against FLAG_TRUE / FLAG_FALSE. An empty
    string is False (not marked); None or an unrecognized value returns None.
    """
    if value is None:
        return None
    key = value.strip().upper()
    if key in FLAG_TRUE:
        return True
    if key in FLAG_FALSE:
        return False
    return None
