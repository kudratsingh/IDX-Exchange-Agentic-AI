"""Structured logging: one JSON line per event, one trace id per request.

Every line goes through `redact()` so an email, phone number, or secret never reaches
a log (CLAUDE.md, SAFETY_INVARIANTS.md); deny-listed field names join the scrub list
in WO-002. Standard library only; writes to stderr so stdout stays the MCP transport.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

# Patterns `redact()` replaces inside strings: email addresses, separated 10-digit
# phone numbers, "key: value" secrets (key name kept), and bare token-shaped values.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_SECRET = re.compile(r"(?i)(api[_-]?key|password|token|secret)(\W*[:=]\W*)([^\s'\",]+)")
_SECRET_VALUE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,})")

# Dict keys (case-insensitive) whose whole value is replaced, whatever it contains.
REDACTED_KEYS = frozenset({"password", "api_key", "token", "secret", "authorization"})


def new_trace_id() -> str:
    """Return a new 16-hex-character id that ties one request's result and logs."""
    return uuid.uuid4().hex[:16]


def redact(value: Any) -> Any:
    """Scrub emails, phone numbers, and secret-looking values from a JSON-able value.

    Strings are pattern-scrubbed; dicts and lists/tuples are walked recursively
    (tuples come back as lists), and values under REDACTED_KEYS are replaced
    whole. Any other type is returned unchanged.
    """
    if isinstance(value, str):
        value = _EMAIL.sub("[email]", value)
        value = _PHONE.sub("[phone]", value)
        value = _SECRET.sub(r"\1\2[redacted]", value)
        return _SECRET_VALUE.sub("[redacted]", value)
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if str(k).lower() in REDACTED_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def log_event(event: str, trace_id: str, **fields: Any) -> dict[str, Any]:
    """Write one redacted JSON line to stderr and return it (tests read the return).

    Input: event name, trace id, and any extra fields. Steps: 1. build the record
    with a UTC timestamp, 2. redact it, 3. write it as sorted-key JSON to stderr.
    Called by the MCP server once per tool call and once at start.
    """
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "event": event,
        "trace_id": trace_id,
        **fields,
    }
    record = redact(record)
    sys.stderr.write(json.dumps(record, default=str, sort_keys=True) + "\n")
    sys.stderr.flush()
    return record


class Timer:
    """Measure a tool call: `with Timer() as t: ...; t.ms`.

    `ms` is the elapsed wall time in milliseconds, rounded to 2 places; it is
    set on exit, even when the block raised.
    """

    def __enter__(self) -> Timer:
        # Start the clock; `ms` reads 0.0 until the block exits.
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        # Record elapsed ms; returns None, so an exception in the block propagates.
        self.ms = round((time.perf_counter() - self._start) * 1000, 2)
