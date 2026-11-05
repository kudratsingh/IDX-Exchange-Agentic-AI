"""One copy of a card tool's result for the model (relay fix Layer 2, 2026-11-05).

`one_copy` writes the result dict so the MCP SDK's text block equals OpenClaw's JSON of
the same structuredContent, and OpenClaw drops the duplicate (see the notes below).
"""

# Why (read-only check of the installed OpenClaw 2026.9.5, 2026-11-05): a tool returns
# a dict, so the MCP SDK sends it twice, as `structuredContent` and as a text block
# (`pydantic_core.to_json(result, indent=2)`). OpenClaw's
# projectMcpCallToolResultContent gives the model a "structuredContent:" block first,
# then drops each SDK text block whose text equals
# `JSON.stringify(structuredContent, null, 2)` (dist/mcp-content-Dj8o6nFL.mjs:113).
# Python writes an integral float as `2.0` and JavaScript as `2`, so a card with whole
# bathrooms never matched and reached the model twice (Phase 1 turn P1-4). `one_copy`
# turns every integral float in JavaScript's exact-integer range into an int, and puts
# the keys of every object in JavaScript's own-property order (integer-like keys first,
# ascending; the rest as they were), since `JSON.parse` reorders such keys before
# OpenClaw stringifies them. Values are equal before and after (2 == 2.0); no field is
# added, dropped or renamed.

from __future__ import annotations

from typing import Any

# Integral floats below this magnitude print the same digits in Python and JavaScript.
_EXACT = 2**53
# JavaScript treats a key as an array index (and lists it first) up to 2**32 - 2.
_MAX_INDEX = 2**32 - 2


def _index_key(key: str) -> int | None:
    """The key's array index when JavaScript would order it as one, else None."""
    if key == "0":
        return 0
    if not key.isascii() or not key.isdigit() or key.startswith("0"):
        return None
    number = int(key)
    return number if number <= _MAX_INDEX else None


def one_copy(value: Any) -> Any:
    """`value` (a JSON value, e.g. `model_dump(mode="json")`) with integral floats as
    ints and object keys in JavaScript order; see the notes at the top."""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < _EXACT:
            return int(value)
        return value
    if isinstance(value, list):
        return [one_copy(item) for item in value]
    if isinstance(value, dict):
        indexed = sorted(
            (index, key)
            for key in value
            if isinstance(key, str) and (index := _index_key(key)) is not None
        )
        first = [key for _, key in indexed]
        seen = set(first)
        rest = [key for key in value if key not in seen]
        return {key: one_copy(value[key]) for key in [*first, *rest]}
    return value
