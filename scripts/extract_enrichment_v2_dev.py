"""Compare frozen v2 on the 100 private dev cases under one paid token."""

from __future__ import annotations

import argparse
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
from scripts.score_enrichment_private import _read_private, _sample_jsonl  # noqa: E402

from idx_agent.enrichment.dev_extraction import ProviderFailure  # noqa: E402
from idx_agent.enrichment.v2 import (  # noqa: E402
    V2_FACETS,
    canonical_schema_hash,
    compare_dev_cases,
    haiku_meets_dev_rule,
    score_v2,
    tool_schema,
)
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"
PROMPT_HASH = "e1ccb614145cca19f05b403d22a214ba597816049dc192aad057f9e60d25ba24"
SCHEMA_HASH = "036155fd435c9ce61891a917252d8f68ee8a02fd9124e3bcf0d689e00cf47a03"
MODELS = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def contract_hashes():
    """Bind held-out and batch work to the exact development implementation."""
    return {
        "prompt": hashlib.sha256(
            (ROOT / "docs/ENRICHMENT_EXTRACTION_V2.md").read_bytes()
        ).hexdigest(),
        "schema": canonical_schema_hash(),
        "v2_implementation": hashlib.sha256(
            (ROOT / "src/idx_agent/enrichment/v2.py").read_bytes()
        ).hexdigest(),
        "dev_driver": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def send_v2(text, prompt, model, key, retries):
    """Reuse the frozen synchronous retry boundary in this single-threaded CLI."""
    old_facets, old_schema = provider.FACETS, provider._tool_schema
    try:
        provider.FACETS, provider._tool_schema = V2_FACETS, tool_schema
        return provider._send(text, prompt, model, key, retries)
    finally:
        provider.FACETS, provider._tool_schema = old_facets, old_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    budget = None
    retries = {name: {} for name in MODELS}
    requests_made = {name: 0 for name in MODELS}
    completed = {name: 0 for name in MODELS}
    tag = uuid.uuid4().hex
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
        sample = _sample_jsonl(PRIVATE, "dev")
        cases = [
            (case["id"], case["text"])
            for case in sample["cases"]
            if case["split"] == "dev"
        ]
        if len(cases) != 100:
            raise ValueError("invalid development split")
        outputs = {name: PRIVATE / f"predictions-dev-v2-{name}.json" for name in MODELS}
        if (
            any(path.exists() for path in outputs.values())
            or (PRIVATE / "usage-dev-v2.json").exists()
        ):
            raise ValueError("v2 output already exists")
        journal = PRIVATE / "checkpoints" / "v2-dev"
        if journal.parent.is_symlink():
            raise ValueError("invalid checkpoint directory")
        journal.mkdir(mode=0o700, parents=True, exist_ok=False)
        if journal.is_symlink() or journal.stat().st_mode & 0o077:
            raise ValueError("invalid checkpoint permissions")
        budget = consent.start_paid_run()
        if budget.max_calls < 600:
            raise ValueError("insufficient call ceiling")
        prompt = prompt_bytes.decode("utf-8")
        by_id = {value: name for name, value in MODELS.items()}

        def invoke(model, text):
            name = by_id[model]
            before = budget.calls_made
            try:
                return send_v2(text, prompt, model, key, retries[name])
            except ProviderFailure as error:
                diagnostic(
                    name,
                    completed[name] + 1,
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
            finally:
                requests_made[name] += budget.calls_made - before

        def checkpoint(name, index, raw, usage):
            import base64

            provider._write_new(
                journal / f"{name}-{index:03d}.json",
                {"raw": base64.b64encode(raw).decode("ascii"), "usage": usage},
            )
            completed[name] += 1

        def diagnostic(name, index, raw, errors):
            debug = PRIVATE / "debug"
            if debug.is_symlink():
                raise ValueError("invalid debug directory")
            debug.mkdir(mode=0o700, parents=True, exist_ok=True)
            if debug.stat().st_mode & 0o077:
                raise ValueError("invalid debug permissions")
            if raw is not None:
                fd = os.open(
                    debug / f"v2-{tag}-{name}-{index:03d}.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
            for error in errors:
                print(
                    json.dumps({"model": name, "diagnostic": error}, sort_keys=True),
                    flush=True,
                )

        predictions, reports = compare_dev_cases(
            sample["dataset_id"], cases, MODELS, invoke, checkpoint, diagnostic
        )
        gold = _read_private(PRIVATE, "labels.json")
        for name in MODELS:
            counts = score_v2(sample, gold, predictions[name], "dev")
            reports[name]["metrics"] = {
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
            reports[name]["retries_by_error_class"] = retries[name]
            reports[name]["requests_made"] = requests_made[name]
            reports[name]["model"] = MODELS[name]
            provider._write_new(outputs[name], predictions[name])
        reports["haiku_within_three_points"] = haiku_meets_dev_rule(
            reports["sonnet"]["metrics"]["overall"]["f1"],
            reports["haiku"]["metrics"]["overall"]["f1"],
        )
        reports["requests_made"] = budget.calls_made
        reports["contract_hashes"] = contract_hashes()
        provider._write_new(PRIVATE / "usage-dev-v2.json", reports)
        print(json.dumps(reports, sort_keys=True))
        return 0
    except Exception:
        consent.abort_paid_run("v2_dev_failed")
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "completed": completed,
                    "requests_made": budget.calls_made if budget else 0,
                    "requests_by_model": requests_made,
                    "retries_by_error_class": retries,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
