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
from idx_agent.enrichment.full_batch import records  # noqa: E402
from idx_agent.enrichment.v2 import canonical_schema_hash  # noqa: E402
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
    parser.add_argument(
        "--v1-reuse",
        choices=("no",),
        help="Explicitly choose not to reuse the 324 v1 rows.",
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
        if args.model == "haiku":
            heldout = json.loads((PRIVATE / "usage-test-v2-haiku.json").read_text())
            if not dev.get("haiku_within_three_points") or not heldout.get(
                "confirmation_passed"
            ):
                raise ValueError("haiku decision not confirmed")
            if heldout.get("contract_hashes") != dev["contract_hashes"]:
                raise ValueError("held-out contract differs from dev")
        elif dev.get("haiku_within_three_points"):
            raise ValueError("haiku selected by dev rule")
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
            if args.v1_reuse != "no":
                raise ValueError("v1 reuse decision required")
            if args.continue_after_approval and args.retry_failed_after_approval:
                raise ValueError("choose continuation or failed-item retry")
            conn = connect()
            watermark = active_watermark(conn)
            first_staging = (
                db.execute("SELECT 1 FROM settings LIMIT 1").fetchone() is None
            )
            staged = stage_tranche(
                db,
                records(iter_pages(conn)),
                MODELS[args.model],
                PROMPT_HASH,
                SCHEMA_HASH,
                watermark,
                extend=args.continue_after_approval,
            )
            if first_staging and staged != 2000:
                raise ValueError("first tranche requires 2000 remarks")
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
                print(
                    json.dumps(
                        {"status": "tranche_verified", "aggregate": aggregate(db, 0)},
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
    except Exception:
        consent.abort_paid_run("v2_batch_stopped")
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "consent_units_spent": budget.calls_made if budget else 0,
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
