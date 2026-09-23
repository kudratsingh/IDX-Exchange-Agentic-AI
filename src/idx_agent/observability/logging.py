"""Structured logging: one JSON line per event, one trace id per request.

Everything passes through redaction.

Every log line goes through `redact()` so an email address, a phone number, or a secret
never reaches a log even by accident (CLAUDE.md, SAFETY_INVARIANTS.md). Deny-listed
listing fields are added to the scrub list in WO-002 once their names are confirmed.
Standard library only; stderr, so an MCP stdio server keeps stdout for the protocol.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_SECRET = re.compile(r"(?i)(api[_-]?key|password|token|secret)(\W*[:=]\W*)([^\s'\",]+)")
_SECRET_VALUE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,})")

REDACTED_KEYS = frozenset({"password", "api_key", "token", "secret", "authorization"})


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def redact(value: Any) -> Any:
    """Scrub emails, phone numbers, and secret-looking values from a JSON-able value."""
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
    """Write one redacted JSON line to stderr and return it (tests read the return)."""
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
    """Measure a tool call: `with Timer() as t: ...; t.ms`."""

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = round((time.perf_counter() - self._start) * 1000, 2)
