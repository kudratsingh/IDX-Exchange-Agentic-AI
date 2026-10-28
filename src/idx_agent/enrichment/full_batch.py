"""Private, append-only facet table and resumable active-remarks batch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from idx_agent.enrichment.dev_extraction import parse_response
from idx_agent.semantic.embedder import _LINK, _WHITESPACE, prepare, redact_text

CHECKPOINT_EVERY = 50


def initialize(db: sqlite3.Connection, signature: str, active_asof: str) -> None:
    """Create metadata once; reject changed inputs or a completed table."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
            name TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
            sequence INTEGER PRIMARY KEY, listing_key TEXT NOT NULL UNIQUE,
            input_hash TEXT NOT NULL, facets TEXT NOT NULL,
            diagnostic_count INTEGER NOT NULL,
            usage TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            completed INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    expected = {"signature": signature, "active_asof": active_asof, "format": "1"}
    existing = dict(db.execute("SELECT name, value FROM metadata"))
    if not existing:
        db.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?)", expected.items()
        )
        db.commit()
    elif any(existing.get(k) != v for k, v in expected.items()):
        raise ValueError("batch metadata mismatch")
    if existing.get("complete") == "yes":
        raise ValueError("batch is already complete")


def records(pages: Iterable[tuple[list[Mapping[str, Any]], str]]):
    """Newest active row per ID; redact the whole non-empty remark, never truncate."""
    last_key = None
    for rows, _ in pages:
        if len(rows) > 50:
            raise ValueError("page exceeds 50 rows")
        for row in rows:
            key = str(row["L_ListingID"]).strip()
            if not key.isascii() or not key.isdigit():
                raise ValueError("invalid listing key")
            if key == last_key:
                continue
            last_key = key
            remark = row.get("L_Remarks")
            if not isinstance(remark, str) or not remark.strip():
                continue
            prepared = prepare(
                remark, max_chars=max(4000, len(remark) * 8 + 100), redact=True
            )
            if prepared.truncated:
                raise ValueError("remark preparation failed")
            # The embedding index drops short text; this job covers every
            # non-empty remark, using the same normalization and redaction.
            text = prepared.text
            if text is None:
                normalized = _WHITESPACE.sub(" ", remark).strip()
                text = redact_text(_LINK.sub("[link]", normalized))
            yield key, text


def verify_complete_source(
    db: sqlite3.Connection, source: Iterable[tuple[str, str]]
) -> bool:
    """Check every source key and prepared remark against the durable table."""
    saved = iter(
        db.execute(
            "SELECT sequence, listing_key, input_hash FROM results ORDER BY sequence"
        )
    )
    for index, (key, text) in enumerate(source, 1):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if next(saved, None) != (index, key, digest):
            return False
    return next(saved, None) is None


def verify_source_prefix(
    db: sqlite3.Connection, source: Iterable[tuple[str, str]]
) -> bool:
    """Check all stored rows against the corresponding source prefix."""
    incoming = iter(source)
    for index, (sequence, key, digest) in enumerate(
        db.execute(
            "SELECT sequence, listing_key, input_hash FROM results ORDER BY sequence"
        ),
        1,
    ):
        row = next(incoming, None)
        if (
            sequence != index
            or row is None
            or row[0] != key
            or hashlib.sha256(row[1].encode("utf-8")).hexdigest() != digest
        ):
            return False
    return True


def run_batch(
    db: sqlite3.Connection,
    source: Iterable[tuple[str, str]],
    invoke: Callable[[str], tuple[Any, dict | None, bytes]],
    source_unchanged: Callable[[], bool],
    diagnostic: Callable[[list[dict], bytes], None],
    progress: Callable[[int], None] = lambda _: None,
    stop_after: int | None = None,
    partial_unchanged: Callable[[], bool] = lambda: True,
) -> dict[str, int]:
    """Verify the saved prefix, then commit each result and checkpoint every 50."""
    saved = iter(
        db.execute(
            "SELECT sequence, listing_key, input_hash FROM results ORDER BY sequence"
        )
    )
    prior = next(saved, None)
    old_count = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    if stop_after is not None and (stop_after < 1 or old_count > stop_after):
        raise ValueError("invalid tranche limit")
    seen = 0
    for key, text in source:
        seen += 1
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if prior is not None:
            if prior != (seen, key, digest):
                raise ValueError("source changed since checkpoint")
            prior = next(saved, None)
            if stop_after == seen and prior is None:
                if not partial_unchanged():
                    raise ValueError("source changed during tranche")
                return {
                    "completed": seen,
                    "previously_completed": old_count,
                    "newly_completed": 0,
                    "paused": 1,
                }
            continue
        response, usage, raw = invoke(text)
        annotations, errors = parse_response(response, text)
        if errors:
            diagnostic(errors, raw)
        facets = [
            {
                name: annotation[name]
                for name in ("group", "value", "polarity", "temporality")
            }
            for annotation in annotations
            if annotation["kind"] == "facet"
        ]
        with db:
            db.execute(
                "INSERT INTO results (sequence, listing_key, input_hash, facets, "
                "diagnostic_count, usage) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    seen,
                    key,
                    digest,
                    json.dumps(facets, sort_keys=True),
                    len(errors),
                    json.dumps(usage),
                ),
            )
            if seen % CHECKPOINT_EVERY == 0:
                db.execute("INSERT INTO checkpoints (completed) VALUES (?)", (seen,))
        if seen % CHECKPOINT_EVERY == 0:
            progress(seen)
        if stop_after == seen:
            if not partial_unchanged():
                raise ValueError("source changed during tranche")
            return {
                "completed": seen,
                "previously_completed": old_count,
                "newly_completed": seen - old_count,
                "paused": 1,
            }
    if prior is not None or seen < old_count:
        raise ValueError("source ended before checkpoint")
    if not seen:
        raise ValueError("no eligible remarks")
    if not source_unchanged():
        raise ValueError("source as-of changed")
    with db:
        if seen and seen % CHECKPOINT_EVERY:
            db.execute("INSERT INTO checkpoints (completed) VALUES (?)", (seen,))
        db.execute("INSERT INTO metadata (name, value) VALUES ('complete', 'yes')")
    return {
        "completed": seen,
        "previously_completed": old_count,
        "newly_completed": seen - old_count,
    }
