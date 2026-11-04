"""Check, key-free, whether the WO-032 supplement wave could start (dry run only).

Reuses the full Sonnet run's own checks and prints aggregate counts only. It never reads
a provider key, starts a paid run or builds a request; the results table is read-only.
The paid steps are not built: WO-032 is blocked on an owner decision (see its Status).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import extract_enrichment_v2_batch as full_run  # noqa: E402
from scripts.extract_enrichment_test import verify_freeze  # noqa: E402
from scripts.extract_enrichment_v21_dev import verify_v21_freeze  # noqa: E402

from idx_agent.enrichment.supplement import run_preconditions  # noqa: E402

DATA = ROOT / "data" / "enrichment"


def contract_checks(data: Path):
    """The full run's contract checks, in its order, as (name, check) pairs."""

    def prompt_and_schema():
        raw = (ROOT / "docs" / "ENRICHMENT_EXTRACTION_V2.md").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != full_run.PROMPT_HASH
            or full_run.canonical_schema_hash() != full_run.SCHEMA_HASH
        ):
            raise ValueError("v2 contract changed")

    def dev_decision():
        dev = json.loads((data / "usage-dev-v2.json").read_text())
        if dev.get("contract_hashes") != full_run.contract_hashes():
            raise ValueError("v2 contract differs from dev")
        # The full run's own check reads its private directory from this attribute.
        full_run.PRIVATE = data
        if not full_run.sonnet_fallback_selected(dev):
            raise ValueError("Sonnet fallback not selected")

    return [
        ("frozen_v1_files", verify_freeze),
        ("v21_freeze_manifest", verify_v21_freeze),
        ("v2_prompt_and_schema", prompt_and_schema),
        ("dev_decision_selects_sonnet", dev_decision),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DATA,
        help="private enrichment directory (default: this checkout's data/enrichment)",
    )
    args = parser.parse_args(argv)
    if not args.dry_run:
        print(
            json.dumps(
                {"status": "refused", "reason": "paid_path_not_built_see_wo_032"}
            )
        )
        return 2
    data = args.data_root.resolve()
    table = data / "full" / "active-facets-v2.sqlite3"
    inventory = data / "refresh" / "preflight-inventory.jsonl"
    db = conn = None
    try:
        for path in (table, inventory):
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise ValueError("invalid private input")
        db = sqlite3.connect(f"{table.as_uri()}?mode=ro", uri=True)
        conn = full_run.connect()
        summary = run_preconditions(
            freeze_checks=contract_checks(data),
            db=db,
            contract={
                "model": full_run.MODELS["sonnet"],
                "prompt_hash": full_run.PROMPT_HASH,
                "schema_hash": full_run.SCHEMA_HASH,
            },
            inventory_lines=inventory.read_text(encoding="utf-8").splitlines(),
            watermark=lambda: full_run.active_watermark(conn),
            pages=lambda: full_run.iter_pages(conn),
        )
    except Exception as exc:  # a broken input is a refusal, never a partial plan
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "check_failed",
                    "error_class": type(exc).__name__,
                }
            )
        )
        return 1
    finally:
        if db is not None:
            db.close()
        if conn is not None:
            conn.close()
    print(json.dumps(dict(summary, mode="dry_run"), sort_keys=True))
    return 0 if summary["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
