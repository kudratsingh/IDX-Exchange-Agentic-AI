"""Snapshot-based new-listing rule; modification time never makes a match new."""

from datetime import date


def needs_check(checked_as_of: date, active_as_of: date) -> bool:
    return active_as_of > checked_as_of


def new_keys(
    dated_keys, checked_as_of: date, active_as_of: date, alerted=()
) -> list[int]:
    if not needs_check(checked_as_of, active_as_of):
        return []
    seen = set(alerted)
    result = []
    for key, listed in dated_keys:
        if (
            listed is not None
            and checked_as_of < listed <= active_as_of
            and key not in seen
        ):
            result.append(key)
            seen.add(key)
    return result
