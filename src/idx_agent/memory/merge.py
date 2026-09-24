"""Merge a refinement into the last accepted filters, in code (WO-006 req. 1, 2, 5).

The model supplies only the changed fields and a mode; this module decides what
carries over. Every result goes through `PropertySearchFilters.from_input`, so a
bad merge comes back as a Clarification and is never raised.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Literal

from idx_agent.domain.models import Clarification, PropertySearchFilters

__all__ = ["MergeMode", "merge_filters", "next_page"]

MergeMode = Literal["update", "replace", "reset"]

# Setting one location field unsets the other: a new city drops the old ZIP.
_LOCATION_PAIRS: dict[str, str] = {"city": "postal_code", "postal_code": "city"}


def _unsupported(name: str) -> Clarification:
    """Return the `unsupported_filter` Clarification for a name that is not a filter.

    Built by `from_input` on the unknown name alone, so the field, question, and
    options match every other unsupported-filter answer.
    """
    result = PropertySearchFilters.from_input({name: None})
    if isinstance(result, Clarification):
        return result
    raise AssertionError("an unknown filter name validated")  # pragma: no cover


def merge_filters(
    previous: PropertySearchFilters | None,
    update: Mapping[str, object],
    mode: MergeMode,
    clear: Collection[str] = (),
) -> PropertySearchFilters | Clarification:
    """Combine the previous filters and an update by mode; validate the result.

    update: previous fields, minus `clear`, overwritten by the update; page back to
    1 unless the update sets it. replace and reset: the update alone. A None value
    in the update means "not given"; a name is unset only through `clear`.
    """
    if mode not in ("update", "replace", "reset"):
        raise ValueError(f"unknown merge mode {mode!r}")
    names = PropertySearchFilters.model_fields
    # A single string is one name, not a collection of characters.
    clear_names = (clear,) if isinstance(clear, str) else tuple(clear)
    for name in clear_names:
        if name not in names:
            return _unsupported(name)
    # Unknown keys are kept even when None so from_input reports them.
    changes = {k: v for k, v in update.items() if v is not None or k not in names}

    merged: dict[str, object] = {}
    if mode == "update" and previous is not None:
        merged = previous.model_dump(exclude_none=True)
        for name in clear_names:
            merged.pop(name, None)
        for name, other in _LOCATION_PAIRS.items():
            if name in changes:
                merged.pop(other, None)
        merged.pop("page", None)
    merged.update(changes)
    return PropertySearchFilters.from_input(merged)


def next_page(previous: PropertySearchFilters) -> PropertySearchFilters | Clarification:
    """Return the same filters one page further ("show me more").

    Past the last allowed page (1000) this is the page Clarification, not a guess.
    """
    return merge_filters(previous, {"page": previous.page + 1}, "update")
