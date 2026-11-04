"""Key-free preconditions for a supplement extraction wave (WO-032).

Reads the preflight inventory, the results table (read-only) and the active pages and
returns aggregate counts. It never builds a request, reads a key or writes anything.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from idx_agent.enrichment.full_batch import records, verify_complete_source
from idx_agent.enrichment.source_check import (
    EXPECTED_RESULTS_DIGEST,
    EXPECTED_ROWS,
    EXPECTED_WATERMARK,
    results_digest,
)

# The preflight's recorded count of never-extracted active listings (2026-11-02).
EXPECTED_SUPPLEMENT_IDS = 321
# Owner ceiling on consent units for the paid step: one per message plus one per
# batch creation request.
MAX_CALLS = 400
MAX_BATCH_REQUESTS = 1000
NEVER_EXTRACTED = "never_extracted"
_CLASSES = frozenset(
    {"unchanged", "changed", "new", NEVER_EXTRACTED, "no_longer_active", "ambiguous"}
)


class PreconditionFailed(ValueError):
    """A precondition did not hold; `code` is a fixed name, never data."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def never_extracted_keys(lines: Iterable[str]) -> list[str]:
    """The inventory's never_extracted listing keys; refuse a malformed inventory."""
    keys: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        key, kind = entry.get("listing_key"), entry.get("class")
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdigit()
            or kind not in _CLASSES
            or key in seen
        ):
            raise PreconditionFailed("inventory_malformed")
        seen.add(key)
        if kind == NEVER_EXTRACTED:
            keys.append(key)
    return keys


def check_results_table(
    db,
    contract: Mapping[str, str],
    *,
    rows: int = EXPECTED_ROWS,
    watermark: str = EXPECTED_WATERMARK,
    digest: str = EXPECTED_RESULTS_DIGEST,
) -> dict[str, Any]:
    """The results table is the frozen full run: its contract, size, digest and state.

    `contract` holds the model, prompt hash and schema hash the full run must have
    recorded. Raises PreconditionFailed with the first failing check.
    """
    settings = dict(db.execute("SELECT name, value FROM settings"))
    expected = dict(contract, version="v2", watermark=watermark)
    if any(settings.get(name) != value for name, value in expected.items()):
        raise PreconditionFailed("full_run_contract_mismatch")
    counts = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("inputs", "results", "result_origins")
    }
    if set(counts.values()) != {rows}:
        raise PreconditionFailed("results_row_count_mismatch")
    if results_digest(db) != digest:
        raise PreconditionFailed("results_digest_mismatch")
    verified = {w for (w,) in db.execute("SELECT watermark FROM verifications")}
    final = db.execute(
        "SELECT watermark FROM verifications WHERE completed = ?", (rows,)
    ).fetchone()
    if verified != {watermark} or final != (watermark,):
        raise PreconditionFailed("verification_watermark_mismatch")
    open_batches = db.execute(
        "SELECT COUNT(*) FROM batches WHERE status NOT IN ('complete','resolved')"
    ).fetchone()[0]
    if open_batches:
        raise PreconditionFailed("batches_not_complete")
    origins = dict(
        db.execute("SELECT extractor, COUNT(*) FROM result_origins GROUP BY extractor")
    )
    return {"rows": rows, "origins": origins, "batches_complete": True}


def disjoint_from_results(db, keys: Iterable[str]) -> int:
    """How many of `keys` already have an input or result row (must be zero)."""
    wanted = set(keys)
    stored = {k for (k,) in db.execute("SELECT listing_key FROM results")}
    stored |= {k for (k,) in db.execute("SELECT listing_key FROM inputs")}
    return len(wanted & stored)


def _observe(
    pages: Iterable[tuple[list[Mapping[str, Any]], str]],
    keys: set[str],
    counts: Counter,
) -> Iterator[tuple[list[Mapping[str, Any]], str]]:
    """Pass pages through unchanged, counting the supplement keys' rows and remarks."""
    for rows, after in pages:
        for row in rows:
            if str(row["L_ListingID"]).strip() in keys:
                remark = row.get("L_Remarks")
                counts["rows"] += 1
                if remark is None:
                    counts["remark_null"] += 1
                elif not isinstance(remark, str) or not remark.strip():
                    counts["remark_blank"] += 1
                else:
                    counts["remark_text"] += 1
        yield rows, after


def scan_source(
    db, pages: Iterable[tuple[list[Mapping[str, Any]], str]], keys: Iterable[str]
) -> dict[str, Any]:
    """One pass over the active pages, with the full run's own source reader.

    Every record outside the supplement keys must equal the stored results exactly (the
    full run's completion audit); the supplement keys' eligible records are counted.
    """
    wanted = set(keys)
    counts: Counter = Counter()
    eligible: list[str] = []
    seen: set[str] = set()

    def original() -> Iterator[tuple[str, str]]:
        for key, text in records(_observe(pages, wanted, counts)):
            if key in wanted:
                eligible.append(key)
                seen.add(key)
                continue
            yield key, text

    unchanged = verify_complete_source(db, original())
    present = counts["rows"]
    return {
        "original_source_matches": unchanged,
        "supplement_rows_in_source": present,
        "supplement_remark_null": counts["remark_null"],
        "supplement_remark_blank": counts["remark_blank"],
        "supplement_remark_text": counts["remark_text"],
        "eligible_remarks": len(eligible),
        "eligible_digest": hashlib.sha256("\n".join(sorted(seen)).encode()).hexdigest(),
    }


def planned_units(eligible: int) -> int:
    """Consent units the submit step would spend: each message plus each creation."""
    batches = -(-eligible // MAX_BATCH_REQUESTS)
    return eligible + batches


def run_preconditions(
    *,
    freeze_checks: Iterable[tuple[str, Callable[[], None]]],
    db,
    contract: Mapping[str, str],
    inventory_lines: Iterable[str],
    watermark: Callable[[], str],
    pages: Callable[[], Iterable[tuple[list[Mapping[str, Any]], str]]],
    expected_ids: int = EXPECTED_SUPPLEMENT_IDS,
    ceiling: int = MAX_CALLS,
    table_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every precondition in order; stop at the first failure.

    Returns {"status": "ready" | "refused", "preconditions": [...], "counts": {...}}
    with fixed names and aggregate counts only.
    """
    results: list[dict[str, str]] = []
    counts: dict[str, Any] = {}

    def record(name: str, ok: bool, code: str | None = None) -> None:
        results.append({"name": name, "result": "pass" if ok else (code or "fail")})
        if not ok:
            raise PreconditionFailed(code or name)

    try:
        for name, check in freeze_checks:
            try:
                check()
            except ValueError:
                record(name, False, "freeze_hash_mismatch")
            record(name, True)
        try:
            table = check_results_table(db, contract, **(table_checks or {}))
        except PreconditionFailed as exc:
            record("results_table_is_frozen_full_run", False, exc.code)
        record("results_table_is_frozen_full_run", True)
        counts["results_rows"] = table["rows"]
        counts["results_origins"] = table["origins"]
        keys = never_extracted_keys(inventory_lines)
        counts["never_extracted_ids"] = len(keys)
        record("input_set_count", len(keys) == expected_ids, "input_set_count_mismatch")
        overlap = disjoint_from_results(db, keys)
        counts["already_in_results"] = overlap
        record("input_set_has_no_result_row", overlap == 0, "input_set_overlaps")
        stored = dict(db.execute("SELECT name, value FROM settings"))["watermark"]
        before = watermark()
        record("watermark_unchanged_before_scan", before == stored, "watermark_changed")
        scanned = scan_source(db, pages(), keys)
        after = watermark()
        record("watermark_unchanged_after_scan", after == stored, "watermark_changed")
        counts.update(scanned)
        record(
            "original_source_unchanged",
            scanned["original_source_matches"],
            "source_mismatch",
        )
        record(
            "input_set_active_in_source",
            scanned["supplement_rows_in_source"] == len(keys),
            "source_mismatch",
        )
        eligible = scanned["eligible_remarks"]
        record("input_set_has_eligible_remarks", eligible > 0, "no_eligible_remarks")
        units = planned_units(eligible)
        counts["planned_consent_units"] = units
        record("within_call_ceiling", units <= ceiling, "ceiling_exceeded")
    except PreconditionFailed as exc:
        return {
            "status": "refused",
            "reason": exc.code,
            "preconditions": results,
            "counts": counts,
        }
    return {"status": "ready", "preconditions": results, "counts": counts}
