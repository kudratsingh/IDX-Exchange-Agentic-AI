"""Execute the one approved held-out run using the frozen extraction boundary."""

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

from scripts import extract_enrichment_dev as frozen  # noqa: E402
from scripts.score_enrichment_private import _sample_jsonl  # noqa: E402

from idx_agent.enrichment.dev_extraction import (  # noqa: E402
    ProviderFailure,
    parse_response,
)
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"
MODEL = "claude-sonnet-5-5"
HASHES = {
    "docs/ENRICHMENT_EXTRACTION_PROMPT.md": (
        "1d23e9ecd81d8ede5304d8a7ea9aadaa81850a77ff2eceece80c40b6b835fcd4"
    ),
    "src/idx_agent/enrichment/dev_extraction.py": (
        "e81900c2c707999d3b45f2fdbbd719b14912665f395cebe611fdc98f6e9ae32a"
    ),
    "scripts/extract_enrichment_dev.py": (
        "ae4852c84a82b28473b37172087fc2f57b8f42887e689b7be79bdc40b298c089"
    ),
    "src/idx_agent/enrichment/vocabulary.py": (
        "0f5f83a1c9291a842414364112e783d3ca757b86fe51fc8cae33a84ec2ebe1a5"
    ),
    "src/idx_agent/enrichment/private_scoring.py": (
        "21d429d637e75ddaabdb20f9ae1a15a5855c93f97f65ee9159ac6752242df30b"
    ),
    "scripts/score_enrichment_private.py": (
        "ed8a0b7495941923a23a3b0e0cd9296bd28bd7a39b63bbee03f0d91aba95ab3a"
    ),
}
SCHEMA_HASH = "feb5deb09af283f5d049536466a0b750323250a3b1626e6242fa6095363be779"
FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def verify_freeze() -> None:
    for name, expected in HASHES.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("frozen file changed")
    schema = json.dumps(
        frozen._tool_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if hashlib.sha256(schema).hexdigest() != SCHEMA_HASH:
        raise ValueError("frozen schema changed")


def run(
    dataset: str, cases: list[tuple[str, str]], invoke, checkpoint, diagnostic
) -> tuple[dict, dict]:
    """Extract precisely 150 held-out cases, keeping identifiers out of diagnostics."""
    if not dataset or len(cases) != 150 or len({key for key, _ in cases}) != 150:
        raise ValueError("invalid held-out sample")
    labels, totals = [], dict.fromkeys(FIELDS, 0)
    known = dict.fromkeys(FIELDS, 0)
    misses = no_call = diagnostics_count = 0
    for index, (key, remark) in enumerate(cases, 1):
        response, usage, raw = invoke(remark)
        checkpoint(index, raw, usage)
        if isinstance(usage, dict):
            for field in FIELDS:
                if type(usage.get(field)) is int and usage[field] >= 0:
                    totals[field] += usage[field]
                    known[field] += 1
        annotations, errors = parse_response(response, remark)
        if errors:
            misses += 1
            diagnostics_count += len(errors)
            no_call += any(item["rule"] == "no_extraction_tool_call" for item in errors)
            diagnostic(index, raw, errors)
        labels.append({"id": key, "annotations": annotations})
    out_usage = {
        field: totals[field] if known[field] == 150 else None for field in FIELDS
    }
    components = [
        out_usage[field]
        for field in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    ]
    total_input = (
        sum(components) if all(value is not None for value in components) else None
    )
    out_usage.update(
        cases=150,
        total_input_tokens=total_input,
        total_input_tokens_per_remark=total_input / 150
        if total_input is not None
        else None,
        uncached_input_tokens_per_remark=out_usage["input_tokens"] / 150
        if out_usage["input_tokens"] is not None
        else None,
        output_tokens_per_remark=out_usage["output_tokens"] / 150
        if out_usage["output_tokens"] is not None
        else None,
        remarks_with_misses=misses,
        no_tool_calls=no_call,
        diagnostic_count=diagnostics_count,
    )
    return {"version": 1, "dataset_id": dataset, "labels": labels}, out_usage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    budget = None
    retries: dict[str, int] = {}
    completed = 0
    tag = uuid.uuid4().hex
    try:
        verify_freeze()
        if (PRIVATE / "predictions-test-heldout.json").exists() or (
            PRIVATE / "usage-test-heldout.json"
        ).exists():
            raise ValueError("held-out outputs already exist")
        from evals.run import _local_setting

        api_key = _local_setting("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("missing provider key")
        sample = _sample_jsonl(PRIVATE, "test")
        cases = [
            (case["id"], case["text"])
            for case in sample["cases"]
            if case["split"] == "test"
        ]
        spec = (ROOT / "docs" / "ENRICHMENT_EXTRACTION_PROMPT.md").read_text(
            encoding="utf-8"
        )
        journal_root = PRIVATE / "checkpoints"
        if journal_root.is_symlink():
            raise ValueError("invalid journal")
        journal = journal_root / "heldout"
        journal.mkdir(mode=0o700, parents=True, exist_ok=False)
        if journal.is_symlink() or journal.stat().st_mode & 0o077:
            raise ValueError("journal is not private")
        budget = consent.start_paid_run()
        if budget.max_calls < 150:
            raise ValueError("insufficient call budget")

        def checkpoint(index, raw, usage):
            nonlocal completed
            frozen._write_new(
                journal / f"{index:03d}.json",
                {
                    "index": index,
                    "raw": base64.b64encode(raw).decode("ascii"),
                    "usage": usage,
                },
            )
            completed += 1

        def diagnostic(index, raw, errors):
            debug = PRIVATE / "debug"
            if debug.is_symlink():
                raise ValueError("invalid debug directory")
            debug.mkdir(mode=0o700, parents=True, exist_ok=True)
            if debug.stat().st_mode & 0o077:
                raise ValueError("debug directory is not private")
            fd = os.open(
                debug / f"heldout-{tag}-{index:03d}.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
            for error in errors:
                print(json.dumps({"diagnostic": error}, sort_keys=True), flush=True)

        def invoke(remark):
            try:
                return frozen._send(remark, spec, MODEL, api_key, retries)
            except ProviderFailure as error:
                diagnostic(
                    completed + 1,
                    error.raw or b"",
                    [
                        {
                            "error_class": "ProviderFailure",
                            "field": "provider",
                            "rule": error.rule,
                        }
                    ],
                )
                raise

        predictions, usage = run(
            sample["dataset_id"], cases, invoke, checkpoint, diagnostic
        )
        usage.update(requests_made=budget.calls_made, retries_by_error_class=retries)
        frozen._write_new(PRIVATE / "predictions-test-heldout.json", predictions)
        frozen._write_new(PRIVATE / "usage-test-heldout.json", usage)
    except Exception:
        consent.abort_paid_run("heldout_extraction_failed")
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
    print(json.dumps(usage, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
