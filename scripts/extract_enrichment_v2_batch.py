"""Submit or collect the approved v2 Message Batches tranche."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import extract_enrichment_dev as provider  # noqa: E402
from scripts import extract_enrichment_v21_dev as v21_driver  # noqa: E402
from scripts.extract_enrichment_full import (  # noqa: E402
    active_watermark,
    aggregate,
    private_file,
)
from scripts.extract_enrichment_test import verify_freeze  # noqa: E402
from scripts.extract_enrichment_v2_dev import (  # noqa: E402
    MODELS,
    PROMPT_HASH,
    SCHEMA_HASH,
    contract_hashes,
)

from idx_agent.db.pool import connect  # noqa: E402
from idx_agent.enrichment.batch_v2 import (  # noqa: E402
    ingest_batch,
    initialize_batch_store,
    plan_failed_retries,
    stage_tranche,
    submit_batch,
)
from idx_agent.enrichment.full_batch import (  # noqa: E402
    records,
    verify_complete_source,
)
from idx_agent.enrichment.v2 import canonical_schema_hash  # noqa: E402
from idx_agent.enrichment.wave_gate import (  # noqa: E402
    EXPECTED_BUDGET,
    console_delta,
    next_wave,
    record_console_baseline,
    verify_stored_wave,
)
from idx_agent.safety import consent  # noqa: E402
from idx_agent.semantic.build_index import iter_pages  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"


def source_matches(db, source):
    incoming = iter(source)
    for index, (sequence, key, digest) in enumerate(
        db.execute(
            "SELECT sequence,listing_key,input_hash FROM inputs ORDER BY sequence"
        ),
        1,
    ):
        row = next(incoming, None)
        if (
            sequence != index
            or row is None
            or row[0] != key
            or hashlib.sha256(row[1].encode()).hexdigest() != digest
        ):
            return False
    return True


def v21_is_eligible(dev, report):
    """Apply the owner's v2.1 dev rule from recorded, unrounded metrics."""
    sonnet = dev["sonnet"]["metrics"]["overall"]["f1"]
    haiku = report["metrics"]["overall"]["f1"]
    output = report["usage"]["output_tokens"]
    if any(type(x) not in (int, float) for x in (sonnet, haiku, output)):
        raise ValueError("incomplete v2.1 metrics")
    return haiku + 0.03 + 1e-12 >= sonnet and output / 100 < 400


def sonnet_fallback_selected(dev):
    v21_driver.verify_v21_freeze()
    report = json.loads((PRIVATE / "usage-dev-v21-haiku.json").read_text())
    expected = {
        "prompt": v21_driver.PROMPT_HASH,
        "schema": v21_driver.SCHEMA_HASH,
        "implementation": hashlib.sha256(
            (ROOT / "src/idx_agent/enrichment/v21.py").read_bytes()
        ).hexdigest(),
        "driver": hashlib.sha256(Path(v21_driver.__file__).read_bytes()).hexdigest(),
    }
    if (
        report.get("contract_hashes") != expected
        or report.get("model") != MODELS["haiku"]
    ):
        raise ValueError("v2.1 provenance mismatch")
    return not v21_is_eligible(dev, report)


def load_v1_reuse(path):
    """Read the explicitly selected v1 table without changing it."""
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("invalid v1 table")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        tag = db.execute(
            "SELECT value FROM metadata WHERE name='extractor_version'"
        ).fetchone()
        if tag != ("v1",):
            raise ValueError("v1 provenance missing")
        rows = db.execute(
            "SELECT listing_key,input_hash,facets,diagnostic_count,usage FROM results"
        ).fetchall()
        if len(rows) != 324:
            raise ValueError("v1 row count changed")
        return {
            key: (digest, facets, errors, usage)
            for key, digest, facets, errors, usage in rows
        }
    finally:
        db.close()


def origin_summary(db, origin):
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    totals, known = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0)
    count = misses = 0
    for errors, encoded in db.execute(
        "SELECT r.diagnostic_count,r.usage FROM results AS r "
        "JOIN result_origins AS o ON o.sequence=r.sequence WHERE o.extractor=?",
        (origin,),
    ):
        count += 1
        misses += errors > 0
        usage = json.loads(encoded)
        if isinstance(usage, dict):
            for field in fields:
                if type(usage.get(field)) is int and usage[field] >= 0:
                    totals[field] += usage[field]
                    known[field] += 1
    return {
        "remarks": count,
        "validation_misses": misses,
        "usage": {
            field: totals[field] if count and known[field] == count else None
            for field in fields
        },
    }


def request_http(path, key, *, payload=None, on_error=lambda _: None):
    """Retry safe reads; never retry a potentially accepted batch creation."""
    request = urllib.request.Request(
        provider.ENDPOINT + path,
        data=json.dumps(payload, ensure_ascii=False).encode()
        if payload is not None
        else None,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST" if payload is not None else "GET",
    )
    for attempt in range(1, 4):
        consent.spend_paid_call()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            on_error(exc.read())
            if exc.code == 429:
                category, retryable = "RateLimitError", True
            elif 500 <= exc.code <= 599:
                category, retryable = "ServerError", True
            elif exc.code in (401, 403):
                category, retryable = "AuthenticationError", False
            else:
                category, retryable = "ClientError", False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            category = (
                "TimeoutError"
                if isinstance(reason, TimeoutError)
                else "ConnectionError"
            )
            retryable = True
        retrying = payload is None and retryable and attempt < 3
        print(
            json.dumps(
                {
                    "provider_error": {
                        "error_class": category,
                        "attempt": attempt,
                        "retrying": retrying,
                    }
                }
            ),
            flush=True,
        )
        if not retrying:
            raise RuntimeError("provider_request_failed") from None
        time.sleep(2 ** (attempt - 1))
    raise RuntimeError("provider_request_failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("submit", "collect"), required=True)
    parser.add_argument("--model", choices=tuple(MODELS), required=True)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    parser.add_argument("--continue-after-approval", action="store_true")
    parser.add_argument("--retry-failed-after-approval", action="store_true")
    parser.add_argument("--wave-size", type=int)
    parser.add_argument(
        "--console-baseline",
        type=str,
        help="Verified cumulative console total at 8,000 rows, USD",
    )
    parser.add_argument(
        "--checkpoint-console-cost",
        type=str,
        help="Current cumulative total in the same console scope, USD",
    )
    parser.add_argument(
        "--v1-reuse",
        choices=("yes",),
        help="Reuse the 324 approved v1 rows.",
    )
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    db = conn = lock = budget = None
    try:
        verify_freeze()
        prompt_bytes = (ROOT / "docs" / "ENRICHMENT_EXTRACTION_V2.md").read_bytes()
        if (
            hashlib.sha256(prompt_bytes).hexdigest() != PROMPT_HASH
            or canonical_schema_hash() != SCHEMA_HASH
        ):
            raise ValueError("v2 contract changed")
        from evals.run import _local_setting

        key = _local_setting("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("missing provider key")
        dev = json.loads((PRIVATE / "usage-dev-v2.json").read_text())
        if dev.get("contract_hashes") != contract_hashes():
            raise ValueError("v2 contract differs from dev")
        if not sonnet_fallback_selected(dev):
            raise ValueError("Sonnet fallback not selected")
        if args.model != "sonnet":
            raise ValueError("Sonnet selected by owner decision")
        directory = PRIVATE / "full"
        if directory.is_symlink():
            raise ValueError("invalid private directory")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise ValueError("invalid private directory permissions")
        lock_path = directory / "active-facets-v2.lock"
        private_file(lock_path)
        lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / "active-facets-v2.sqlite3"
        if args.action == "collect" and not path.exists():
            raise ValueError("no staged tranche")
        private_file(path)
        db = sqlite3.connect(path)
        db.execute("PRAGMA synchronous=FULL")
        initialize_batch_store(db)
        budget = consent.start_paid_run()
        prompt = prompt_bytes.decode()

        def save_error_response(raw):
            debug = PRIVATE / "debug"
            if debug.is_symlink():
                raise ValueError("invalid debug directory")
            debug.mkdir(mode=0o700, parents=True, exist_ok=True)
            if debug.stat().st_mode & 0o077:
                raise ValueError("invalid debug permissions")
            fd = os.open(
                debug / f"v2-batch-http-{uuid.uuid4().hex}.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)

        def parse_response(raw):
            try:
                return json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                save_error_response(raw)
                raise ValueError("invalid provider response") from None

        if args.action == "submit":
            if args.v1_reuse != "yes":
                raise ValueError("v1 reuse decision required")
            if args.continue_after_approval and args.retry_failed_after_approval:
                raise ValueError("choose continuation or failed-item retry")
            conn = connect()
            watermark = active_watermark(conn)
            reused = load_v1_reuse(directory / "active-facets-v1.sqlite3")
            count = db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]
            has_waves = db.execute("SELECT COUNT(*) FROM waves").fetchone()[0] > 0
            if (has_waves or count >= 8000) and args.wave_size is None:
                raise ValueError("wave mode required")
            if args.wave_size is not None:
                from decimal import Decimal, InvalidOperation

                if args.retry_failed_after_approval:
                    raise ValueError("wave retry needs separate review")
                try:
                    supplied_baseline = (
                        Decimal(args.console_baseline)
                        if args.console_baseline is not None
                        else None
                    )
                except InvalidOperation:
                    raise ValueError("invalid console baseline") from None
                baseline = record_console_baseline(db, count, supplied_baseline)
                if args.continue_after_approval:
                    previous = db.execute(
                        "SELECT start_sequence,end_sequence FROM waves "
                        "ORDER BY end_sequence DESC LIMIT 1"
                    ).fetchone()
                    start = previous[0] if previous else 6001
                    if previous and previous[1] != count:
                        raise ValueError("wave state mismatch")
                    gate = verify_stored_wave(db, start, count, watermark)
                    print(json.dumps({"wave_gate": gate}), flush=True)
                    approved = args.checkpoint_console_cost is not None
                    if approved:
                        if count not in (26000, 46000):
                            raise ValueError("console checkpoint at wrong boundary")
                        try:
                            amount = Decimal(args.checkpoint_console_cost)
                        except InvalidOperation:
                            raise ValueError("invalid console cost") from None
                        if not amount.is_finite() or amount < 0:
                            raise ValueError("invalid console cost")
                        delta = console_delta(baseline, amount)
                        if (
                            max(delta, Decimal(gate["estimated_spend"]))
                            + Decimal(gate["projected_remaining"])
                            > EXPECTED_BUDGET
                        ):
                            raise ValueError(
                                "console cost and projection exceed budget"
                            )
                        last = db.execute(
                            "SELECT total FROM wave_console_checkpoints "
                            "ORDER BY completed DESC LIMIT 1"
                        ).fetchone()
                        if last and amount < Decimal(last[0]):
                            raise ValueError("console total decreased")
                        prior = db.execute(
                            "SELECT total FROM wave_console_checkpoints "
                            "WHERE completed=?",
                            (count,),
                        ).fetchone()
                        if prior and Decimal(prior[0]) != amount:
                            raise ValueError("console checkpoint changed")
                        with db:
                            db.execute(
                                "INSERT OR IGNORE INTO wave_console_checkpoints "
                                "(completed,total) VALUES (?,?)",
                                (count, str(amount)),
                            )
                    else:
                        last = db.execute(
                            "SELECT completed,total FROM wave_console_checkpoints "
                            "ORDER BY completed DESC LIMIT 1"
                        ).fetchone()
                        if last:
                            from idx_agent.enrichment.wave_gate import estimated_cost

                            later = db.execute(
                                "SELECT usage FROM results "
                                "WHERE sequence>? AND sequence<=?",
                                (last[0], count),
                            ).fetchall()
                            if len(later) != count - last[0]:
                                raise ValueError("cost evidence incomplete")
                            estimate = sum(
                                (estimated_cost(json.loads(row[0])) for row in later),
                                Decimal(0),
                            )
                            if (
                                max(
                                    console_delta(baseline, Decimal(last[1]))
                                    + estimate,
                                    Decimal(gate["estimated_spend"]),
                                )
                                + Decimal(gate["projected_remaining"])
                                > EXPECTED_BUDGET
                            ):
                                raise ValueError(
                                    "console cost and projection exceed budget"
                                )
                    if args.wave_size != next_wave(count, checkpoint_approved=approved):
                        raise ValueError("wave size differs from approved schedule")
                elif not db.execute(
                    "SELECT 1 FROM waves WHERE end_sequence=? "
                    "AND end_sequence-start_sequence+1=?",
                    (count, args.wave_size),
                ).fetchone():
                    raise ValueError("no staged wave to resume")
            staged = stage_tranche(
                db,
                records(iter_pages(conn)),
                MODELS[args.model],
                PROMPT_HASH,
                SCHEMA_HASH,
                watermark,
                limit=args.wave_size if args.wave_size is not None else 2000,
                extend=args.continue_after_approval,
                reuse_v1=reused,
                wave=args.wave_size is not None,
            )
            if staged < 2000:
                raise ValueError("first tranche requires 2000 remarks")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM result_origins WHERE extractor='v1'"
                ).fetchone()[0]
                != 324
            ):
                raise ValueError("not all v1 rows matched source")
            if args.retry_failed_after_approval:
                print(
                    json.dumps({"retry_items_planned": plan_failed_retries(db)}),
                    flush=True,
                )
            for number, state in db.execute(
                "SELECT batch_number,status FROM batches ORDER BY batch_number"
            ).fetchall():
                if state in {"complete", "resolved"}:
                    continue
                if state == "partial" and args.retry_failed_after_approval:
                    continue
                if state != "planned":
                    raise ValueError(
                        "existing non-planned batch requires reconciliation"
                    )
                if (
                    active_watermark(conn) != watermark
                    or not source_matches(db, records(iter_pages(conn)))
                    or active_watermark(conn) != watermark
                ):
                    raise ValueError("source changed")

                def submit(payload):
                    return parse_response(
                        request_http(
                            "/batches",
                            key,
                            payload=payload,
                            on_error=save_error_response,
                        )
                    )

                summary = submit_batch(
                    db,
                    number,
                    MODELS[args.model],
                    prompt,
                    consent.spend_paid_call,
                    submit,
                )
                print(
                    json.dumps({"batch": number, **summary}, sort_keys=True), flush=True
                )
        else:
            settings = dict(db.execute("SELECT name,value FROM settings"))
            if (
                settings.get("model") != MODELS[args.model]
                or settings.get("prompt_hash") != PROMPT_HASH
                or settings.get("schema_hash") != SCHEMA_HASH
            ):
                raise ValueError("batch configuration changed")
            conn = connect()
            watermark = settings.get("watermark")
            if (
                active_watermark(conn) != watermark
                or not source_matches(db, records(iter_pages(conn)))
                or active_watermark(conn) != watermark
            ):
                raise ValueError("source changed")
            for number, remote_id, status in db.execute(
                "SELECT batch_number,provider_id,status FROM batches "
                "ORDER BY batch_number"
            ).fetchall():
                if status in {"complete", "resolved", "partial"}:
                    continue
                if status == "planned":
                    print(
                        json.dumps({"batch": number, "status": "planned"}), flush=True
                    )
                    continue
                if status != "submitted" or not re.fullmatch(
                    r"msgbatch_[A-Za-z0-9]+", remote_id or ""
                ):
                    raise ValueError("batch requires reconciliation")
                remote = parse_response(
                    request_http(
                        f"/batches/{remote_id}", key, on_error=save_error_response
                    )
                )
                if remote.get("processing_status") != "ended":
                    print(
                        json.dumps({"batch": number, "status": "pending"}), flush=True
                    )
                    continue
                raw = request_http(
                    f"/batches/{remote_id}/results", key, on_error=save_error_response
                )
                results = [
                    parse_response(line) for line in raw.splitlines() if line.strip()
                ]

                def diagnostic(errors, response):
                    debug = PRIVATE / "debug"
                    if debug.is_symlink():
                        raise ValueError("invalid debug directory")
                    debug.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if debug.stat().st_mode & 0o077:
                        raise ValueError("invalid debug permissions")
                    provider._write_new(
                        debug / f"v2-batch-{uuid.uuid4().hex}.json", response
                    )
                    for error in errors:
                        print(
                            json.dumps({"diagnostic": error}, sort_keys=True),
                            flush=True,
                        )

                print(
                    json.dumps(
                        {
                            "batch": number,
                            **ingest_batch(db, number, results, diagnostic),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            remaining = db.execute(
                "SELECT COUNT(*) FROM batches "
                "WHERE status NOT IN ('complete','resolved')"
            ).fetchone()[0]
            if remaining == 0:
                if (
                    active_watermark(conn) != watermark
                    or not source_matches(db, records(iter_pages(conn)))
                    or active_watermark(conn) != watermark
                ):
                    raise ValueError("source changed")
                completed = db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]
                if completed == 54888 and (
                    active_watermark(conn) != watermark
                    or not verify_complete_source(db, records(iter_pages(conn)))
                    or active_watermark(conn) != watermark
                ):
                    raise ValueError("full source verification failed")
                verified = db.execute(
                    "SELECT watermark FROM verifications WHERE completed=?",
                    (completed,),
                ).fetchone()
                if verified is None:
                    with db:
                        db.execute(
                            "INSERT INTO verifications(completed,watermark) "
                            "VALUES (?,?)",
                            (completed, watermark),
                        )
                elif verified[0] != watermark:
                    raise ValueError("verification mismatch")
                wave = db.execute(
                    "SELECT start_sequence,end_sequence FROM waves "
                    "WHERE end_sequence=?",
                    (completed,),
                ).fetchone()
                if wave:
                    print(
                        json.dumps(
                            {
                                "wave_gate": verify_stored_wave(
                                    db, wave[0], wave[1], watermark
                                )
                            }
                        ),
                        flush=True,
                    )
                print(
                    json.dumps(
                        {
                            "status": "tranche_verified",
                            "aggregate": aggregate(db, 0),
                            "reused_v1": origin_summary(db, "v1"),
                            "new_v2": origin_summary(db, "v2"),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        status = "done"
        if args.action == "collect":
            exceptional = db.execute(
                "SELECT COUNT(*) FROM batches WHERE status IN ('partial','uncertain')"
            ).fetchone()[0]
            status = (
                "needs_review" if exceptional else ("pending" if remaining else "done")
            )
        print(
            json.dumps(
                {
                    "status": status,
                    "consent_units_spent": budget.calls_made,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        consent.abort_paid_run("v2_batch_stopped")
        known_reasons = {
            "projected budget exceeded",
            "console cost and projection exceed budget",
            "human checkpoint required",
            "validation miss rate exceeded",
            "source changed",
            "full source verification failed",
            "batch incomplete or failed",
            "incomplete results",
            "result provenance invalid",
        }
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "consent_units_spent": budget.calls_made if budget else 0,
                    "reason": str(exc) if str(exc) in known_reasons else "check_failed",
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        if db:
            db.close()
        if conn:
            conn.close()
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
