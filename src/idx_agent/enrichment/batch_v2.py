"""Offline preparation for v2 batches; performs no provider or filesystem calls.

The provider submission, polling, result ingestion, and paid gate are deliberately
not implemented until their current documented contract can be verified.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from idx_agent.enrichment.v2 import message_parameters

MAX_BATCH_REQUESTS = 1000


def prepare_batch(
    cases: Sequence[tuple[str, str]], model: str, prompt: str
) -> list[dict]:
    """Construct a bounded request plan using only opaque generated identifiers."""
    if not cases or len(cases) > MAX_BATCH_REQUESTS:
        raise ValueError("batch must contain 1..1000 requests")
    seen = set()
    requests = []
    for opaque_id, remark in cases:
        if (
            not isinstance(opaque_id, str)
            or not re.fullmatch(r"case-[0-9]{8}", opaque_id)
            or opaque_id in seen
        ):
            raise ValueError("invalid or duplicate opaque request id")
        seen.add(opaque_id)
        requests.append(
            {
                "custom_id": opaque_id,
                "params": message_parameters(model, prompt, remark),
            }
        )
    return requests


def initialize_batch_store(db) -> None:
    """Create a private, append-only staging and result schema."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inputs (
            sequence INTEGER PRIMARY KEY, listing_key TEXT NOT NULL UNIQUE,
            input_hash TEXT NOT NULL, remark TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batches (
            batch_number INTEGER PRIMARY KEY, start_sequence INTEGER NOT NULL,
            end_sequence INTEGER NOT NULL, status TEXT NOT NULL, provider_id TEXT
        );
        CREATE TABLE IF NOT EXISTS results (
            sequence INTEGER PRIMARY KEY, listing_key TEXT NOT NULL UNIQUE,
            input_hash TEXT NOT NULL, facets TEXT NOT NULL,
            diagnostic_count INTEGER NOT NULL, usage TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checkpoints (completed INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS verifications (
            completed INTEGER PRIMARY KEY, watermark TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS failed_items (
            batch_number INTEGER NOT NULL, sequence INTEGER NOT NULL,
            result_type TEXT NOT NULL, PRIMARY KEY(batch_number, sequence)
        );
    """)
    db.commit()


def stage_tranche(
    db, source, model, prompt_hash, schema_hash, watermark, limit=2000, *, extend=False
):
    """Stage a tranche; extensions require completed batches and an unchanged prefix."""
    import hashlib

    if not 1 <= limit <= 2000:
        raise ValueError("invalid tranche size")
    expected = {
        "model": model,
        "prompt_hash": prompt_hash,
        "schema_hash": schema_hash,
        "watermark": watermark,
        "version": "v2",
    }
    existing = dict(db.execute("SELECT name, value FROM settings"))
    previous = 0
    next_batch = 1
    if existing:
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ValueError("batch configuration changed")
        previous = db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]
        if not extend:
            return previous
        if db.execute(
            "SELECT COUNT(*) FROM batches WHERE status NOT IN ('complete','resolved')"
        ).fetchone()[0]:
            raise ValueError("previous batches incomplete")
        verified = db.execute("SELECT MAX(completed) FROM verifications").fetchone()[0]
        if verified != previous:
            raise ValueError("previous tranche is not verified")
        next_batch = db.execute(
            "SELECT COALESCE(MAX(batch_number),0)+1 FROM batches"
        ).fetchone()[0]
    incoming = iter(source)
    if existing:
        for index, (sequence, saved_key, saved_hash) in enumerate(
            db.execute(
                "SELECT sequence,listing_key,input_hash FROM inputs ORDER BY sequence"
            ),
            1,
        ):
            item = next(incoming, None)
            if (
                item is None
                or sequence != index
                or item[0] != saved_key
                or hashlib.sha256(item[1].encode()).hexdigest() != saved_hash
            ):
                raise ValueError("source changed since previous tranche")
    rows = []
    for key, remark in incoming:
        rows.append(
            (
                previous + len(rows) + 1,
                key,
                hashlib.sha256(remark.encode()).hexdigest(),
                remark,
            )
        )
        if len(rows) == limit:
            break
    if not rows and not existing:
        raise ValueError("empty tranche")
    if not rows:
        return previous
    with db:
        if not existing:
            db.executemany(
                "INSERT INTO settings(name,value) VALUES (?,?)", expected.items()
            )
        db.executemany(
            "INSERT INTO inputs(sequence,listing_key,input_hash,remark) "
            "VALUES (?,?,?,?)",
            rows,
        )
        for batch_number, start in enumerate(
            range(previous + 1, previous + len(rows) + 1, MAX_BATCH_REQUESTS),
            next_batch,
        ):
            end = min(start + MAX_BATCH_REQUESTS - 1, previous + len(rows))
            db.execute(
                "INSERT INTO batches(batch_number,start_sequence,end_sequence,status) "
                "VALUES (?,?,?,?)",
                (batch_number, start, end, "planned"),
            )
    return previous + len(rows)


def submit_batch(db, number, model, prompt, spend, submit):
    """Persist uncertainty before the non-idempotent POST; never auto-resubmit."""
    row = db.execute(
        "SELECT start_sequence,end_sequence,status FROM batches WHERE batch_number=?",
        (number,),
    ).fetchone()
    if not row or row[2] != "planned":
        raise ValueError("batch is not planned")
    start, end, _ = row
    cases = [
        (f"case-{sequence:08d}", remark)
        for sequence, remark in db.execute(
            "SELECT sequence,remark FROM inputs WHERE sequence BETWEEN ? AND ? "
            "ORDER BY sequence",
            (start, end),
        )
    ]
    if len(cases) != end - start + 1:
        raise ValueError("incomplete staged batch")
    payload = prepare_batch(cases, model, prompt)
    spend(len(payload))
    with db:
        db.execute(
            "UPDATE batches SET status='uncertain' "
            "WHERE batch_number=? AND status='planned'",
            (number,),
        )
    response = submit({"requests": payload})
    remote_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(remote_id, str) or not re.fullmatch(
        r"msgbatch_[A-Za-z0-9]+", remote_id
    ):
        raise ValueError("invalid batch acknowledgement")
    with db:
        db.execute(
            "UPDATE batches SET status='submitted',provider_id=? "
            "WHERE batch_number=? AND status='uncertain'",
            (remote_id, number),
        )
    return {"requests": len(payload), "status": "submitted"}


def ingest_batch(db, number, results, on_diagnostic):
    """Reconcile unordered results by opaque ID, then commit each listing once."""
    import json

    from idx_agent.enrichment.v2 import parse_v2

    batch = db.execute(
        "SELECT start_sequence,end_sequence,status FROM batches WHERE batch_number=?",
        (number,),
    ).fetchone()
    if not batch or batch[2] != "submitted":
        raise ValueError("batch is not submitted")
    start, end, _ = batch
    expected = {f"case-{i:08d}" for i in range(start, end + 1)}
    by_id = {}
    for item in results:
        if (
            not isinstance(item, dict)
            or item.get("custom_id") not in expected
            or item["custom_id"] in by_id
        ):
            raise ValueError("invalid batch result identifiers")
        by_id[item["custom_id"]] = item.get("result")
    if set(by_id) != expected:
        raise ValueError("incomplete batch results")
    failures = {"errored": 0, "canceled": 0, "expired": 0}
    for opaque_id, result in by_id.items():
        if not isinstance(result, dict) or result.get("type") not in {
            "succeeded",
            *failures,
        }:
            raise ValueError("invalid batch result type")
        if result["type"] == "succeeded" and not isinstance(
            result.get("message"), dict
        ):
            raise ValueError("invalid successful result")
        if result["type"] in failures:
            failures[result["type"]] += 1
            sequence = int(opaque_id.removeprefix("case-"))
            with db:
                db.execute(
                    "INSERT OR IGNORE INTO failed_items(batch_number,sequence, "
                    "result_type) VALUES (?,?,?)",
                    (number, sequence, result["type"]),
                )
            on_diagnostic(
                [
                    {
                        "error_class": "BatchResultError",
                        "field": "provider",
                        "rule": "batch_" + result["type"],
                    }
                ],
                result,
            )
    for sequence, listing_key, input_hash, remark in db.execute(
        "SELECT sequence,listing_key,input_hash,remark FROM inputs "
        "WHERE sequence BETWEEN ? AND ? ORDER BY sequence",
        (start, end),
    ).fetchall():
        item = by_id[f"case-{sequence:08d}"]
        if item["type"] != "succeeded":
            continue
        response = item["message"]
        annotations, errors = parse_v2(response, remark)
        if errors:
            on_diagnostic(errors, response)
        facets = [
            {
                name: annotation[name]
                for name in ("group", "value", "polarity", "temporality")
            }
            for annotation in annotations
        ]
        fields = (
            sequence,
            listing_key,
            input_hash,
            json.dumps(facets, sort_keys=True),
            len(errors),
            json.dumps(response.get("usage")),
        )
        existing = db.execute(
            "SELECT sequence,listing_key,input_hash,facets,diagnostic_count,usage "
            "FROM results WHERE sequence=?",
            (sequence,),
        ).fetchone()
        if existing is not None:
            if existing != fields:
                raise ValueError("stored result differs")
            continue
        with db:
            db.execute(
                "INSERT INTO results(sequence,listing_key,input_hash,facets, "
                "diagnostic_count,usage) VALUES (?,?,?,?,?,?)",
                fields,
            )
            completed = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
            if completed % 50 == 0:
                db.execute(
                    "INSERT INTO checkpoints(completed) VALUES (?)", (completed,)
                )
    with db:
        db.execute(
            "UPDATE batches SET status=? WHERE batch_number=? AND status='submitted'",
            ("partial" if sum(failures.values()) else "complete", number),
        )
        db.execute(
            "UPDATE batches SET status='resolved' "
            "WHERE status='partial' AND NOT EXISTS "
            "(SELECT 1 FROM failed_items AS f "
            "WHERE f.batch_number=batches.batch_number "
            "AND NOT EXISTS (SELECT 1 FROM results AS r WHERE r.sequence=f.sequence))"
        )
    return {"completed": end - start + 1 - sum(failures.values()), "failures": failures}


def plan_failed_retries(db):
    """Create new bounded planned batches for failed rows, only after approval."""
    sequences = [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT f.sequence FROM failed_items AS f "
            "WHERE NOT EXISTS (SELECT 1 FROM results AS r WHERE r.sequence=f.sequence) "
            "ORDER BY f.sequence"
        )
    ]
    if not sequences:
        raise ValueError("no unresolved failed requests")
    if db.execute(
        "SELECT COUNT(*) FROM batches "
        "WHERE status IN ('planned','submitted','uncertain')"
    ).fetchone()[0]:
        raise ValueError("other batches require reconciliation")
    groups = []
    start = end = sequences[0]
    for sequence in sequences[1:]:
        if sequence == end + 1 and sequence - start < MAX_BATCH_REQUESTS:
            end = sequence
        else:
            groups.append((start, end))
            start = end = sequence
    groups.append((start, end))
    number = db.execute(
        "SELECT COALESCE(MAX(batch_number),0)+1 FROM batches"
    ).fetchone()[0]
    with db:
        for start, end in groups:
            db.execute(
                "INSERT INTO batches(batch_number,start_sequence,end_sequence,status) "
                "VALUES (?,?,?,'planned')",
                (number, start, end),
            )
            number += 1
    return len(sequences)
