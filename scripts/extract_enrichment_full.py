"""Build or resume a private active-listing facet table under a paid token."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import extract_enrichment_dev as frozen  # noqa: E402
from scripts.extract_enrichment_test import MODEL, verify_freeze  # noqa: E402

from idx_agent.db.asof import _ACTIVE_SQL  # noqa: E402
from idx_agent.db.pool import connect  # noqa: E402
from idx_agent.enrichment.dev_extraction import ProviderFailure  # noqa: E402
from idx_agent.enrichment.full_batch import (  # noqa: E402
    initialize,
    records,
    run_batch,
    verify_complete_source,
)
from idx_agent.safety import consent  # noqa: E402
from idx_agent.semantic.build_index import iter_pages  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment" / "full"


def active_watermark(conn) -> str:
    """Reuse the allowlisted as-of query without discarding its time component."""
    with conn.cursor() as cursor:
        cursor.execute(_ACTIVE_SQL, ())
        row = cursor.fetchone()
    watermark = row.get("active_max") if row else None
    if not isinstance(watermark, str) or not watermark:
        raise ValueError("active watermark unavailable")
    return watermark


def private_file(path: Path) -> None:
    """Create once, with owner-only access; refuse symlinks and public files."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("invalid private table") from None
    else:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    budget = conn = db = lock = None
    retries: dict[str, int] = {}
    try:
        verify_freeze()
        from evals.run import _local_setting

        api_key = _local_setting("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("missing provider key")
        if PRIVATE.is_symlink():
            raise ValueError("invalid private directory")
        PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        if PRIVATE.stat().st_mode & 0o077:
            raise ValueError("private directory permissions")
        lock_path = PRIVATE / "active-facets-v1.lock"
        private_file(lock_path)
        lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        table = PRIVATE / "active-facets-v1.sqlite3"
        private_file(table)
        db = sqlite3.connect(table)
        db.execute("PRAGMA synchronous=FULL")
        budget = consent.start_paid_run()
        conn = connect()
        active = active_watermark(conn)
        prompt = (ROOT / "docs" / "ENRICHMENT_EXTRACTION_PROMPT.md").read_text(
            encoding="utf-8"
        )
        signature = hashlib.sha256(
            json.dumps(
                {
                    "model": MODEL,
                    "prompt": prompt,
                    "schema": frozen._tool_schema(),
                    "batch_format": 1,
                    "implementation_hashes": {
                        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                        for path in (
                            "scripts/extract_enrichment_full.py",
                            "src/idx_agent/enrichment/full_batch.py",
                            "src/idx_agent/semantic/embedder.py",
                            "src/idx_agent/semantic/build_index.py",
                        )
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        initialize(db, signature, active)

        def report(errors, raw):
            if raw is not None:
                debug = PRIVATE.parent / "debug"
                if debug.is_symlink():
                    raise ValueError("invalid debug directory")
                debug.mkdir(mode=0o700, parents=True, exist_ok=True)
                if debug.stat().st_mode & 0o077:
                    raise ValueError("debug directory permissions")
                fd = os.open(
                    debug / f"full-{uuid.uuid4().hex}.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
            for error in errors:
                print(json.dumps({"diagnostic": error}, sort_keys=True), flush=True)

        def invoke(text):
            try:
                return frozen._send(text, prompt, MODEL, api_key, retries)
            except ProviderFailure as error:
                report(
                    [
                        {
                            "error_class": "ProviderFailure",
                            "field": "provider",
                            "rule": error.rule,
                        }
                    ],
                    error.raw,
                )
                raise

        summary = run_batch(
            db,
            records(iter_pages(conn)),
            invoke,
            lambda: (
                active_watermark(conn) == active
                and verify_complete_source(db, records(iter_pages(conn)))
                and active_watermark(conn) == active
            ),
            report,
            lambda count: print(
                json.dumps({"checkpoint_completed": count}), flush=True
            ),
        )
        summary.update(
            requests_made=budget.calls_made,
            retries_by_error_class=retries,
            status="complete",
        )
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception:
        consent.abort_paid_run("full_enrichment_stopped")
        completed = (
            db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
            if db
            and db.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='results'"
            ).fetchone()[0]
            else 0
        )
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "completed": completed,
                    "requests_made": budget.calls_made if budget else 0,
                    "retries_by_error_class": retries,
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
