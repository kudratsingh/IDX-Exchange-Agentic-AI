"""Structured logging: one JSON line per event, one trace id per request.

Every line goes through `redact()` so an email, phone number, or secret never reaches
a log (CLAUDE.md, SAFETY_INVARIANTS.md). Writes to stderr so stdout stays the MCP
transport, and with IDX_LOG_FILE set also appends the line to that file (WO-007).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from idx_agent.db.pool import env_setting

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
    line = json.dumps(record, default=str, sort_keys=True) + "\n"
    sys.stderr.write(line)
    sys.stderr.flush()
    append_to_log_file(line)
    return record


# The fallback log file (WO-007): path and rotation size come from the environment
# or .env. Archives are renamed, never removed; pruning is a human act (AGENT_RULES).
LOG_FILE_ENV = "IDX_LOG_FILE"
LOG_FILE_MAX_BYTES_ENV = "IDX_LOG_FILE_MAX_BYTES"
DEFAULT_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
_file_lock = threading.Lock()
_file_failure_reported = False
# Both settings are read once per process, on first use (None: not read yet); a
# changed value needs a restart. reset_log_file_settings_for_tests() clears them.
_target: str | None = None
_limit: int | None = None


def _log_file_target() -> str:
    """IDX_LOG_FILE, stripped ("" when unset), read once per process."""
    global _target
    if _target is None:
        _target = (env_setting(LOG_FILE_ENV) or "").strip()
    return _target


def _max_bytes() -> int:
    """IDX_LOG_FILE_MAX_BYTES as a positive int, else the 10 MB default; read once."""
    global _limit
    if _limit is None:
        raw = (env_setting(LOG_FILE_MAX_BYTES_ENV) or "").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 0
        _limit = value if value > 0 else DEFAULT_LOG_FILE_MAX_BYTES
    return _limit


def reset_log_file_settings_for_tests() -> None:
    """Forget the cached log-file settings and the once-only failure flag."""
    global _target, _limit, _file_failure_reported
    _target, _limit, _file_failure_reported = None, None, False


def archive_path(path: Path, now: datetime | None = None) -> Path:
    """A free archive name beside `path`: `<stem>.<UTC timestamp>-<pid>.log`.

    The pid keeps two processes rotating in the same microsecond apart (a rename
    onto an existing name would replace it); within one process a taken name gets
    `-2`, `-3`, ... So an existing archive is never overwritten.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")
    base = f"{path.stem}.{stamp}-{os.getpid()}"
    candidate = path.with_name(f"{base}.log")
    n = 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{base}-{n}.log")
    return candidate


def _rotate_if_full(path: Path, limit: int) -> None:
    """Rename a file at or over `limit` bytes to a fresh archive name.

    Two processes may both decide to rotate; the loser's rename finds the file
    gone (nothing to do) or moves a small new file. No line is ever lost.
    """
    try:
        if path.stat().st_size < limit:
            return
        os.rename(path, archive_path(path))
    except FileNotFoundError:
        return


def append_to_log_file(line: str) -> None:
    """Append one whole line to IDX_LOG_FILE, if set; rotate it first when full.

    One O_APPEND write per line, so lines from several processes never split.
    The first failure is reported once on stderr; later ones are ignored.
    """
    global _file_failure_reported
    target = _log_file_target()
    if not target:
        return
    data = line.encode("utf-8")
    try:
        path = Path(target)  # a relative path resolves against the working directory
        with _file_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_full(path, _max_bytes())
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
    except (OSError, ValueError) as exc:
        if not _file_failure_reported:
            _file_failure_reported = True
            notice = {
                "event": "log_file_error",
                "error": type(exc).__name__,
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            }
            sys.stderr.write(json.dumps(notice, sort_keys=True) + "\n")
            sys.stderr.flush()


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
