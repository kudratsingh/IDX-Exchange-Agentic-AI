"""WO-017 strict parser for the worker's single JSON object; input is untrusted.

Size, encoding, nesting, duplicate keys and non-finite numbers are checked before
the strict models see the value. Every failure raises WorkerOutputError with a
fixed message that never quotes the input.
"""

from __future__ import annotations

import json
import math
from typing import Any

from pydantic import ValidationError

from idx_agent.domain.analysis_output import WorkerOutput

MAX_OUTPUT_BYTES = 64 * 1024
MAX_DEPTH = 6


class WorkerOutputError(ValueError):
    """Worker output was refused; the message is generic and echoes nothing."""


def _refuse() -> WorkerOutputError:
    return WorkerOutputError("worker output was refused")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _refuse()
        result[key] = value
    return result


def _no_constant(_token: str) -> Any:
    raise _refuse()


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise _refuse()
    return value


def _finite_int(token: str) -> int:
    value = int(token)
    try:
        float(value)
    except OverflowError:
        raise _refuse() from None
    return value


def _depth_ok(text: str) -> bool:
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return False
        elif char in "]}":
            depth -= 1
    return True


def _tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_tuples(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuples(item) for key, item in value.items()}
    return value


def parse_worker_output(raw: bytes) -> WorkerOutput:
    """Accept exactly one bounded, strict JSON object or raise WorkerOutputError."""
    if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
        raise _refuse()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _refuse()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _refuse() from None
    if not _depth_ok(text):
        raise _refuse()
    try:
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_no_constant,
            parse_float=_finite_float,
            parse_int=_finite_int,
        )
    except (ValueError, RecursionError):
        raise _refuse() from None
    if not isinstance(value, dict):
        raise _refuse()
    try:
        return WorkerOutput.model_validate(_tuples(value), strict=True)
    except ValidationError:
        raise _refuse() from None
