"""Read-only checks that the extraction source still matches the frozen audit.

Shared by the review validator and the effective-store builder, so a store is never
published from a results table that differs from what the audit certified.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from idx_agent.enrichment.policy_audit import candidates

# What the frozen audit covered (WO-018): every active remark, and the rows outside the
# 471 diagnostic cases that the policy audit screened.
EXPECTED_ROWS = 54888
EXPECTED_POPULATION = 54417
# The source's latest modification time when the extraction was verified. A feature
# search's freshness test compares against it, so it must not drift.
EXPECTED_WATERMARK = "2026-09-18 06:58:44"
# The owner-approved canonical digest of all 54,888 original result records (sequence,
# listing key, source-text hash, facets, diagnostic count, usage and extractor), frozen
# 2026-11-02 after the WO-018 completion gate passed. A build compares against this
# constant and never computes its own expected value.
EXPECTED_RESULTS_DIGEST = (
    "46cd0a6be8cece97e09d3865ee87aae80c17fe2b16e4aaaa1412f87649209815"
)
_DIGEST_VERSION = "results-digest-v1"


def validate_store(db, cases):
    """Validate the saved source, provenance and diagnostic coverage read-only."""
    source = db.execute(
        "SELECT i.sequence,i.listing_key,i.input_hash,i.remark,"
        "r.listing_key,r.input_hash,r.facets,r.diagnostic_count,o.extractor "
        "FROM inputs i LEFT JOIN results r USING(sequence) "
        "LEFT JOIN result_origins o USING(sequence) ORDER BY i.sequence"
    )
    diagnostics = {case["sequence"]: case for case in cases}
    origins = Counter()
    count = 0
    seen_keys = set()
    for seq, key, digest, remark, result_key, result_hash, facets, n, origin in source:
        count += 1
        if (
            seq != count
            or key in seen_keys
            or key != result_key
            or digest != result_hash
            or hashlib.sha256(remark.encode()).hexdigest() != digest
            or origin not in ("v1", "v2")
        ):
            raise ValueError("source, result or provenance mismatch")
        seen_keys.add(key)
        origins[origin] += 1
        case = diagnostics.pop(seq, None)
        if bool(n) != (case is not None):
            raise ValueError("diagnostic coverage mismatch")
        if case is not None and (
            case["listing_key"] != key
            or case["remark"] != remark
            or case["origin"] != origin
            or case["stored_facets"] != json.loads(facets)
        ):
            raise ValueError("review packet differs from stored result")
    if diagnostics:
        raise ValueError("extra diagnostic cases")
    if (
        db.execute("SELECT COUNT(*) FROM results").fetchone()[0] != count
        or db.execute("SELECT COUNT(*) FROM result_origins").fetchone()[0] != count
    ):
        raise ValueError("extra result or origin")
    return {"rows": count, "origins": dict(origins)}


def results_digest(db) -> str:
    """Canonical sha256 over every result record and its provenance, in sequence order.

    Each record is one compact, key-sorted JSON line; facets are parsed and re-encoded,
    so storage formatting cannot change the digest but any value or order change does.
    """
    digest = hashlib.sha256(f"{_DIGEST_VERSION}\n".encode())
    rows = db.execute(
        "SELECT r.sequence, r.listing_key, r.input_hash, r.facets, "
        "r.diagnostic_count, r.usage, o.extractor FROM results r "
        "LEFT JOIN result_origins o USING(sequence) ORDER BY r.sequence"
    )
    for sequence, key, input_hash, facets, diagnostics, usage, extractor in rows:
        record = {
            "sequence": sequence,
            "listing_key": key,
            "input_hash": input_hash,
            "facets": json.loads(facets),
            "diagnostic_count": diagnostics,
            "usage": json.loads(usage),
            "extractor": extractor,
        }
        line = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest.update(line.encode() + b"\n")
    return digest.hexdigest()


def verify_source(
    db,
    diagnostic_cases,
    dataset_cases,
    dataset_decisions,
    scope,
    expected_rows=EXPECTED_ROWS,
    expected_population=EXPECTED_POPULATION,
    expected_watermark=EXPECTED_WATERMARK,
    expected_digest=EXPECTED_RESULTS_DIGEST,
):
    """Raise ValueError unless the results table is exactly what the audit certified.

    Checks every row, hash and provenance, the diagnostic and dataset coverage, and the
    frozen scope's counts. Returns the number of validated result rows.
    """
    coverage = validate_store(db, diagnostic_cases)
    # Covers every record, including the rows outside both audit packets.
    if results_digest(db) != expected_digest:
        raise ValueError("results differ from the approved results digest")
    settings = dict(db.execute("SELECT name, value FROM settings"))
    recorded = {w for (w,) in db.execute("SELECT watermark FROM verifications")}
    if settings.get("watermark") != expected_watermark or recorded != {
        expected_watermark
    }:
        raise ValueError("source watermark differs from the verified extraction")
    if coverage["rows"] != expected_rows:
        raise ValueError("results do not cover every audited remark")
    population = db.execute(
        "SELECT COUNT(*) FROM results WHERE diagnostic_count=0"
    ).fetchone()[0]
    if population != expected_population or scope.get("population") != population:
        raise ValueError("dataset audit population mismatch")
    if dataset_cases != list(candidates(db)):
        raise ValueError("dataset audit inventory differs from the results")
    if scope.get("inventory_rows") != len(dataset_cases):
        raise ValueError("dataset audit inventory differs from the frozen scope")
    decided = [decision["sequence"] for decision in dataset_decisions]
    if decided != [case["sequence"] for case in dataset_cases]:
        raise ValueError("dataset overlay does not cover the audited inventory")
    return coverage["rows"]
