"""One copy of a card tool's result for the model (relay fix Layer 2, 2026-11-05).

`one_copy` puts the result dict in JavaScript's shape, and `javascript_json` writes the
card tools' SDK text block exactly as OpenClaw re-serializes the structuredContent, so
OpenClaw drops the duplicate (see the notes below; server._CardServer uses both).
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

import math
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


# JavaScript's spelling of a number differs from Python's (and the SDK's pydantic_core)
# beyond whole floats: 1e-6 is `0.000001` in JavaScript and `1e-6`/`1e-06` in Python;
# 1e16 is `10000000000000000` in JavaScript and `1e+16` in Python. No value-preserving
# rewrite of the dict closes that gap, so the card tools' SDK text block is written
# with `javascript_json`, which spells numbers, strings and indentation exactly as
# `JSON.stringify(JSON.parse(wire), null, 2)` does (ECMA-262 Number::toString and
# QuoteJSONString). The structuredContent itself is left as it is.

# JSON.parse reads an integer beyond this as the nearest double.
_SAFE = 2**53
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n"}
_ESCAPES |= {"\r": "\\r", "\t": "\\t"}


def _js_float(number: float) -> str:
    """ECMA-262 Number::toString(10) for a finite float (shortest round-trip digits,
    which Python's repr also gives)."""
    if number == 0:
        return "0"  # -0 too: JSON.stringify(-0) is "0"
    sign = "-" if number < 0 else ""
    mantissa, _, exponent = repr(abs(number)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    point = len(whole) + int(exponent or 0) - (len(whole + fraction) - len(digits))
    digits = digits.rstrip("0")
    k, n = len(digits), point
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        e = n - 1
        head = digits[0] + ("." + digits[1:] if k > 1 else "")
        text = f"{head}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + text


def _js_string(text: str) -> str:
    """ECMA-262 QuoteJSONString: control characters and lone surrogates escaped in
    lowercase hex, everything else (U+2028 included) as it is."""
    out = []
    for char in text:
        code = ord(char)
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _utf16(key: str) -> bytes:
    """Array.prototype.sort's default order: UTF-16 code units (big-endian bytes)."""
    return key.encode("utf-16-be", "surrogatepass")


def javascript_json(value: Any, sort_keys: bool = False, _indent: str = "") -> str:
    """`JSON.stringify(JSON.parse(json_of(value)), null, 2)` for a JSON value: keys in
    JSON.parse's order (sort_keys: UTF-16 sorted first, as OpenClaw's stableStringify),
    JavaScript's number and string spelling, two-space indent; non-finite is null."""
    if value is None or value is True or value is False:
        return {None: "null", True: "true", False: "false"}[value]
    if isinstance(value, int):
        if abs(value) <= _SAFE:
            return str(value)
        try:
            return _js_float(float(value))
        except OverflowError:  # JSON.parse reads it as Infinity, printed as null
            return "null"
    if isinstance(value, float):
        return _js_float(value) if math.isfinite(value) else "null"
    if isinstance(value, str):
        return _js_string(value)
    inner = _indent + "  "
    if isinstance(value, list | tuple):
        if not value:
            return "[]"
        items = [javascript_json(item, sort_keys, inner) for item in value]
        return "[\n" + ",\n".join(inner + item for item in items) + "\n" + _indent + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        keys = sorted(value, key=_utf16) if sort_keys else list(value)
        keys = list(one_copy(dict.fromkeys(keys)))  # JSON.parse's order: indices first
        items = [
            inner
            + _js_string(key)
            + ": "
            + javascript_json(value[key], sort_keys, inner)
            for key in keys
        ]
        return "{\n" + ",\n".join(items) + "\n" + _indent + "}"
    raise TypeError(f"not a JSON value: {type(value).__name__}")
