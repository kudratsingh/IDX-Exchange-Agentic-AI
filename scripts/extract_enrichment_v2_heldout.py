"""Run the separately approved frozen-v2 Haiku held-out confirmation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import extract_enrichment_dev as provider  # noqa: E402
from scripts.extract_enrichment_test import verify_freeze  # noqa: E402
from scripts.extract_enrichment_v2_dev import (  # noqa: E402
    MODELS,
    PROMPT_HASH,
    SCHEMA_HASH,
    contract_hashes,
    send_v2,
)
from scripts.score_enrichment_private import _read_private, _sample_jsonl  # noqa: E402

from idx_agent.enrichment.dev_extraction import ProviderFailure  # noqa: E402
from idx_agent.enrichment.v2 import (  # noqa: E402
    canonical_schema_hash,
    parse_v2,
    score_v2,
)
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    budget = None
    completed = 0
    retries: dict[str, int] = {}
    tag = uuid.uuid4().hex
    try:
        verify_freeze()
        raw_prompt = (ROOT / "docs" / "ENRICHMENT_EXTRACTION_V2.md").read_bytes()
        if (
            hashlib.sha256(raw_prompt).hexdigest() != PROMPT_HASH
            or canonical_schema_hash() != SCHEMA_HASH
        ):
            raise ValueError("v2 contract changed")
        dev = _read_private(PRIVATE, "usage-dev-v2.json")
        if not dev.get("haiku_within_three_points"):
            raise ValueError("haiku dev criterion not met")
        if dev.get("contract_hashes") != contract_hashes():
            raise ValueError("v2 contract differs from dev")
        for name in ("predictions-test-v2-haiku.json", "usage-test-v2-haiku.json"):
            if (PRIVATE / name).exists():
                raise ValueError("held-out output exists")
        from evals.run import _local_setting

        key = _local_setting("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("missing provider key")
        sample = _sample_jsonl(PRIVATE, "test")
        cases = [
            (case["id"], case["text"])
            for case in sample["cases"]
            if case["split"] == "test"
        ]
        if len(cases) != 150 or len({key for key, _ in cases}) != 150:
            raise ValueError("invalid held-out split")
        journal = PRIVATE / "checkpoints" / "v2-heldout-haiku"
        if journal.parent.is_symlink():
            raise ValueError("invalid journal")
        journal.mkdir(mode=0o700, parents=True, exist_ok=False)
        if journal.is_symlink() or journal.stat().st_mode & 0o077:
            raise ValueError("invalid journal permissions")
        budget = consent.start_paid_run()
        if budget.max_calls < 450:
            raise ValueError("insufficient call ceiling")
        fields = (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        totals, known = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0)
        rows, misses, no_calls = [], 0, 0
        prompt = raw_prompt.decode("utf-8")

        def diagnostic(index, raw, errors):
            debug = PRIVATE / "debug"
            if debug.is_symlink():
                raise ValueError("invalid debug directory")
            debug.mkdir(mode=0o700, parents=True, exist_ok=True)
            if debug.stat().st_mode & 0o077:
                raise ValueError("invalid debug permissions")
            if raw is not None:
                fd = os.open(
                    debug / f"v2-heldout-{tag}-{index:03d}.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
            for error in errors:
                print(json.dumps({"diagnostic": error}, sort_keys=True), flush=True)

        for index, (case_id, remark) in enumerate(cases, 1):
            try:
                response, usage, raw = send_v2(
                    remark, prompt, MODELS["haiku"], key, retries
                )
            except ProviderFailure as error:
                diagnostic(
                    index,
                    error.raw,
                    [
                        {
                            "error_class": "ProviderFailure",
                            "field": "provider",
                            "rule": error.rule,
                        }
                    ],
                )
                raise
            provider._write_new(
                journal / f"{index:03d}.json",
                {"raw": base64.b64encode(raw).decode("ascii"), "usage": usage},
            )
            completed += 1
            if isinstance(usage, dict):
                for field in fields:
                    if type(usage.get(field)) is int and usage[field] >= 0:
                        totals[field] += usage[field]
                        known[field] += 1
            annotations, errors = parse_v2(response, remark)
            if errors:
                misses += 1
                no_calls += any(
                    error["rule"] == "no_extraction_tool_call" for error in errors
                )
                diagnostic(index, raw, errors)
            rows.append({"id": case_id, "annotations": annotations})
        predictions = {"version": 1, "dataset_id": sample["dataset_id"], "labels": rows}
        gold = _read_private(PRIVATE, "labels.json")
        counts = score_v2(sample, gold, predictions, "test")
        metrics = {
            facet: {
                "gold": value.expected,
                "predicted": value.predicted,
                "correct": value.correct,
                "precision": value.precision,
                "recall": value.recall,
                "f1": value.f1,
            }
            for facet, value in counts.items()
        }
        eligible = sorted(
            facet
            for facet, value in counts.items()
            if facet != "overall"
            and value.expected >= 10
            and value.f1 is not None
            and value.f1 >= 0.8
        )
        f1 = counts["overall"].f1
        report = {
            "model": MODELS["haiku"],
            "cases": 150,
            "requests_made": budget.calls_made,
            "retries_by_error_class": retries,
            "no_tool_calls": no_calls,
            "remarks_with_misses": misses,
            "usage": {
                field: totals[field] if known[field] == 150 else None
                for field in fields
            },
            "metrics": metrics,
            "eligible_facets": eligible,
            "confirmation_passed": f1 is not None and f1 >= 0.85,
            "prompt_hash": PROMPT_HASH,
            "schema_hash": SCHEMA_HASH,
            "contract_hashes": contract_hashes(),
        }
        provider._write_new(PRIVATE / "predictions-test-v2-haiku.json", predictions)
        provider._write_new(PRIVATE / "usage-test-v2-haiku.json", report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        consent.abort_paid_run("v2_heldout_failed")
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


if __name__ == "__main__":
    raise SystemExit(main())
