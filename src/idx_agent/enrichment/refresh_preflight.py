"""Offline refresh preflight (WO-021): what a future enrichment refresh needs to do.

Pure classification of every in-scope listing ID against the effective store's covered
keys and source watermark. Fail closed: anything uncertain is `ambiguous`, never
`unchanged`. No database, file, model or network access happens here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from idx_agent.domain.valid_values import ACTIVE_STATUS_VALUES

UNCHANGED = "unchanged"
CHANGED = "changed"
NEW = "new"
NEVER_EXTRACTED = "never_extracted"
NO_LONGER_ACTIVE = "no_longer_active"
AMBIGUOUS = "ambiguous"
CLASSES = (UNCHANGED, CHANGED, NEW, NEVER_EXTRACTED, NO_LONGER_ACTIVE, AMBIGUOUS)
# Only these may keep their stored facets in a refresh without re-extraction.
USABLE = frozenset({UNCHANGED})

# Fixed reason codes for `ambiguous`, checked in this order.
KEY_NOT_DIGITS = "key_not_digits"
DUPLICATE_STORE_KEY = "duplicate_store_key"
UNKNOWN_TIMESTAMP = "unknown_timestamp"
AFTER_AS_OF = "after_as_of"
UNKNOWN_STATUS = "unknown_status"
CONFLICTING_STATUS = "conflicting_status"
UNORDERED_DUPLICATE = "unordered_duplicate"
# The reason a store key is no longer active when the database has no row for it.
ABSENT = "absent_from_source"

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class ListingRow:
    """One source row of a listing ID: change time and status, None when unknown."""

    modified: datetime | None
    active: bool | None


@dataclass(frozen=True)
class Entry:
    """A listing ID's class; `reason` is a fixed code for ambiguous or absent IDs."""

    cls: str
    reason: str | None = None


@dataclass(frozen=True)
class Inventory:
    """Every in-scope listing ID's entry, and the IDs outside the refresh scope."""

    entries: dict[str, Entry] = field(default_factory=dict)
    out_of_scope: int = 0


def parse_timestamp(value: Any) -> datetime | None:
    """A datetime from a driver value or `YYYY-MM-DD HH:MM:SS` text; None otherwise."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), _TIMESTAMP_FORMAT)
    except ValueError:
        return None


def to_row(modified: Any, status: Any) -> ListingRow:
    """Map raw column values to a ListingRow; a blank or NULL status is unknown."""
    text = status.strip() if isinstance(status, str) else ""
    active = (text in ACTIVE_STATUS_VALUES) if text else None
    return ListingRow(modified=parse_timestamp(modified), active=active)


def _is_digit_key(key: Any) -> bool:
    return isinstance(key, str) and key.isascii() and key.isdigit()


def _ambiguity(
    key: str, rows: Sequence[ListingRow], duplicated: bool, as_of: datetime
) -> str | None:
    """The first reason this ID cannot be classified with certainty, or None."""
    if not _is_digit_key(key):
        return KEY_NOT_DIGITS
    if duplicated:
        return DUPLICATE_STORE_KEY
    if any(row.modified is None for row in rows):
        return UNKNOWN_TIMESTAMP
    if any(row.modified > as_of for row in rows):  # type: ignore[operator]
        return AFTER_AS_OF
    if any(row.active is None for row in rows):
        return UNKNOWN_STATUS
    if len({row.active for row in rows}) > 1:
        return CONFLICTING_STATUS
    if len(rows) > 1:
        latest = max(row.modified for row in rows)  # type: ignore[type-var]
        if sum(row.modified == latest for row in rows) > 1:
            return UNORDERED_DUPLICATE
    return None


def classify_listing(
    key: str,
    rows: Sequence[ListingRow],
    *,
    in_store: bool,
    watermark: datetime,
    as_of: datetime,
    duplicated: bool = False,
) -> Entry | None:
    """Classify one listing ID; None when it is outside the scope (inactive, unstored).

    In scope: every store key, and every ID with an active or unknown-status row.
    """
    if not in_store and not any(row.active is not False for row in rows):
        return None
    reason = _ambiguity(key, rows, duplicated, as_of)
    if reason is not None:
        return Entry(AMBIGUOUS, reason)
    if in_store and not rows:
        return Entry(NO_LONGER_ACTIVE, ABSENT)
    if in_store and not any(row.active for row in rows):
        return Entry(NO_LONGER_ACTIVE)
    after = any(row.modified > watermark for row in rows)  # type: ignore[operator]
    if in_store:
        return Entry(CHANGED if after else UNCHANGED)
    return Entry(NEW if after else NEVER_EXTRACTED)


def classify_inventory(
    store_keys: Iterable[str],
    watermark: datetime,
    rows: Mapping[str, Sequence[ListingRow]],
    as_of: datetime,
) -> Inventory:
    """Classify every store key and every source ID; each in-scope ID gets one entry.

    Raises ValueError when the store's watermark is after the data's as-of time.
    """
    if watermark > as_of:
        raise ValueError("the store watermark is after the data's as-of time")
    counts = Counter(store_keys)
    entries: dict[str, Entry] = {}
    out_of_scope = 0
    for key in sorted(set(counts) | set(rows)):
        entry = classify_listing(
            key,
            rows.get(key, ()),
            in_store=key in counts,
            watermark=watermark,
            as_of=as_of,
            duplicated=counts[key] > 1,
        )
        if entry is None:
            out_of_scope += 1
        else:
            entries[key] = entry
    return Inventory(entries=entries, out_of_scope=out_of_scope)


def summarize(inventory: Inventory) -> dict[str, Any]:
    """Aggregate counts only: per class, per ambiguous reason, usable, out of scope."""
    classes = Counter(entry.cls for entry in inventory.entries.values())
    reasons = Counter(
        entry.reason
        for entry in inventory.entries.values()
        if entry.cls in (AMBIGUOUS, NO_LONGER_ACTIVE) and entry.reason
    )
    return {
        "classes": {name: classes.get(name, 0) for name in CLASSES},
        "reasons": dict(sorted(reasons.items())),
        "usable": sum(classes.get(name, 0) for name in USABLE),
        "classified": len(inventory.entries),
        "out_of_scope": inventory.out_of_scope,
    }
