"""WO-034 Phase C on the 100 dev remarks, bound to a revised gold by name and hash.
--comparator: saved v2 dev predictions, identical mapping, score_v2; no provider call.
--dry-run: every precondition, aggregates only; no key, token, network or write.
Default: the paid run under one `paid` token for this exact command, ceiling 300.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import enrichment_v3_io as io  # noqa: E402

from idx_agent.enrichment import v3  # noqa: E402
from idx_agent.enrichment.v2 import score_v2  # noqa: E402
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"
CEILING = 300
CASES = 100
HISTORICAL_V2_SONNET_DEV_F1 = 0.946927374301676
V2_PREDICTIONS = "predictions-dev-v2-sonnet.json"
V2_PREDICTIONS_SHA256 = (
    "53bfae92df8dc504cc6a7e4c741928c7e6c5a8207c42b5001bd9c7ecc8bcd31d"
)
OUTPUT = "predictions-dev-v3-sonnet.json"
MAPPING = "mapping-dev-v3-sonnet.json"
USAGE = "usage-dev-v3-sonnet.json"
JOURNAL = ("checkpoints", "v3-dev-sonnet")
# The v3 implementation and the unchanged scorer path, pinned by bytes. A change to
# any of them stops every mode before a token is used.
PINNED = {
    "src/idx_agent/enrichment/v3.py": (
        "ace0b5d388daad5ee5b9a0087d07805c56d0e3d491baed0df600785319418a7f"
    ),
    "scripts/enrichment_v3_io.py": (
        "a186d8acf98b36a9abe2870715be22b41d8a13108dcf5a9caa16c1663aae2267"
    ),
    "src/idx_agent/enrichment/v2.py": (
        "5762b2b3fac28e42b19af56f5ebb35c7cfdd56e50ded72a1eacbc6dca58d6d7d"
    ),
    "src/idx_agent/enrichment/private_scoring.py": (
        "21d429d637e75ddaabdb20f9ae1a15a5855c93f97f65ee9159ac6752242df30b"
    ),
    "src/idx_agent/enrichment/dev_extraction.py": (
        "e81900c2c707999d3b45f2fdbbd719b14912665f395cebe611fdc98f6e9ae32a"
    ),
    "scripts/score_enrichment_private.py": (
        "ed8a0b7495941923a23a3b0e0cd9296bd28bd7a39b63bbee03f0d91aba95ab3a"
    ),
    "scripts/extract_enrichment_dev.py": (
        "ae4852c84a82b28473b37172087fc2f57b8f42887e689b7be79bdc40b298c089"
    ),
    "docs/ENRICHMENT_SCORING_V1.md": (
        "cdb4cb469d38f7477b9dd9ebd5ce98d08cbd2b595b154bdfef535817813cce61"
    ),
}


def verify_pins(root: Path) -> None:
    for relative, expected in PINNED.items():
        if io.file_sha256(root / relative) != expected:
            raise v3.ContractError("pinned implementation file changed")


def preconditions(root: Path, private: Path, gold_name: str, gold_sha256: str):
    """Every check a mode needs, with no key, token, network or write."""
    prompt, schema, request = v3.verify_contract(root)
    verify_pins(root)
    sample, subtypes = io.load_split(private, "dev")
    cases = [(c["id"], c["text"]) for c in sample["cases"] if c["split"] == "dev"]
    if len(cases) != CASES or len({key for key, _ in cases}) != CASES:
        raise ValueError("invalid dev set")
    gold, gold_digest = io.revised_gold(private, gold_name, gold_sha256)
    check = score_v2(sample, gold, gold, "dev")["overall"]
    if not check.expected == check.predicted == check.correct:
        raise ValueError("the scorer rejects the revised gold")
    v3.gold_consistency(gold, sample, subtypes, "dev")
    if io.file_sha256(private / V2_PREDICTIONS) != V2_PREDICTIONS_SHA256:
        raise ValueError("saved v2 dev predictions changed")
    return {
        "prompt": prompt,
        "schema": schema,
        "request": request,
        "sample": sample,
        "subtypes": subtypes,
        "cases": cases,
        "gold": gold,
        "gold_sha256": gold_digest,
        "private": private,
    }


def comparator(ctx: dict) -> dict:
    """Prerequisite 3a: saved v2 dev predictions, identical mapping, score_v2."""
    saved = io.read_private(ctx["private"], V2_PREDICTIONS)
    mapped, _, removed = v3.map_payload(saved, ctx["sample"], ctx["subtypes"], "dev")
    scores = score_v2(ctx["sample"], ctx["gold"], mapped, "dev")
    unmapped = score_v2(ctx["sample"], ctx["gold"], saved, "dev")["overall"]
    return {
        "metric": "score_v2 over the 20 facets, overall f1, unrounded, after mapping",
        "comparator": {
            name: [x.expected, x.predicted, x.correct, x.f1]
            for name, x in scores.items()
        },
        "removed_by_polarity": removed,
        "reference_unmapped_overall": [
            unmapped.expected,
            unmapped.predicted,
            unmapped.correct,
            unmapped.f1,
        ],
        "gold_sha256": ctx["gold_sha256"],
        "predictions_sha256": V2_PREDICTIONS_SHA256,
        "mapper": v3.mapper_hashes(),
    }


def paid_command() -> str:
    """The command a Phase C token must be bound to (this one, without --dry-run)."""
    words = [w for w in consent.invocation_argv() if w != "--dry-run"]
    return consent.display_command(words)


def _outputs_absent(private: Path) -> None:
    for name in (OUTPUT, MAPPING, USAGE):
        if (private / name).exists():
            raise ValueError("existing output")
    if (private.joinpath(*JOURNAL)).exists():
        raise ValueError("existing checkpoints")


def _refused(exc: Exception) -> dict:
    return {
        "status": "refused",
        "error_class": type(exc).__name__,
        "reason": str(exc) if isinstance(exc, ValueError) else None,
    }


def run(ctx: dict, key: str, budget, send=None, sleep=None) -> dict:
    """The paid loop (v2.1 retry gate, checkpoints, usage accounting)."""
    private = ctx["private"]
    journal = io.private_subdir(private.joinpath(*JOURNAL), exist_ok=False)
    calls, retries, usage = [0], {}, io.Usage()

    def spend():
        if calls[0] >= CEILING:
            raise ValueError("Phase C ceiling reached")
        consent.spend_paid_call()
        calls[0] += 1

    rows, sides_spans, misses, no_calls, thinking = [], {}, 0, 0, [0, 0]
    extra = {} if sleep is None else {"sleep": sleep}
    for index, (case_id, text) in enumerate(ctx["cases"], 1):
        body = v3.request_body(ctx["prompt"], ctx["schema"], ctx["request"], text)
        response, used, raw = io.send_with_retries(
            body, key, retries, spend, send=send, **extra
        )
        io.write_checkpoint(journal / f"{index:03d}.json", raw, used)
        usage.add(used)
        if isinstance(used, dict):
            details = used.get("output_tokens_details")
            if (
                isinstance(details, dict)
                and type(details.get("thinking_tokens")) is int
            ):
                thinking[0] += details["thinking_tokens"]
                thinking[1] += 1
        annotations, errors, spans = v3.parse_v3(response, text)
        sides_spans[case_id] = spans
        if errors:
            misses += 1
            no_calls += any(e["rule"] == "no_extraction_tool_call" for e in errors)
            debug = io.private_subdir(private / "debug", exist_ok=True)
            io.write_new(
                debug / f"v3-dev-{index:03d}.json",
                {"raw": base64.b64encode(raw).decode("ascii")},
            )
            for error in errors:
                print(json.dumps({"diagnostic": error}, sort_keys=True), flush=True)
        rows.append({"id": case_id, "annotations": annotations})
    predictions = {
        "version": 1,
        "dataset_id": ctx["sample"]["dataset_id"],
        "labels": rows,
    }
    mapped, sides, removed = v3.map_payload(
        predictions, ctx["sample"], ctx["subtypes"], "dev"
    )
    scores = score_v2(ctx["sample"], ctx["gold"], mapped, "dev")
    compared = comparator(ctx)
    v3_f1 = scores["overall"].f1
    comparator_f1 = compared["comparator"]["overall"][3]
    ids = [case_id for case_id, _ in ctx["cases"]]
    report = {
        "model": ctx["request"]["model"],
        "requests_made": calls[0],
        "retries_by_error_class": retries,
        "remarks_with_misses": misses,
        "no_tool_calls": no_calls,
        "thinking_tokens": thinking[0] if thinking[1] == CASES else None,
        "usage": usage.report(CASES),
        "metrics": v3.counts_json(scores),
        "removed_by_polarity": {"v3": removed, "v2": compared["removed_by_polarity"]},
        "comparator": compared,
        "historical_v2_sonnet_dev_f1": HISTORICAL_V2_SONNET_DEV_F1,
        "phase_c_clears": v3_f1 is not None
        and comparator_f1 is not None
        and v3_f1 >= comparator_f1,
        "span_quality": v3.span_quality(sides_spans, ctx["gold"], ids),
        "gold_sha256": ctx["gold_sha256"],
        "contract": {
            "freeze_version": v3.FREEZE_VERSION,
            "prompt_sha256": v3.PROMPT_SHA256,
            "schema_sha256": v3.SCHEMA_SHA256,
            "request_sha256": v3.REQUEST_SHA256,
            "pinned": PINNED,
            "driver_sha256": io.file_sha256(Path(__file__)),
            "mapper": v3.mapper_hashes(),
        },
    }
    io.write_new(private / OUTPUT, predictions)
    io.write_new(
        private / MAPPING, {"version": 1, "rule": v3.SUBTYPE_RULE, "cases": sides}
    )
    io.write_new(private / USAGE, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--gold-sha256", required=True)
    parser.add_argument("--private-dir", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--comparator", action="store_true")
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args(argv)
    private = args.private_dir or PRIVATE
    if args.comparator or args.dry_run:
        try:
            ctx = preconditions(ROOT, private, args.gold, args.gold_sha256)
            if args.comparator:
                print(
                    json.dumps(
                        {"mode": "comparator", **comparator(ctx)}, sort_keys=True
                    )
                )
                return 0
            _outputs_absent(private)
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "cases": len(ctx["cases"]),
                        "subtype_cases": len(ctx["subtypes"]),
                        "gold_sha256": ctx["gold_sha256"],
                        "contract": {
                            "freeze_version": v3.FREEZE_VERSION,
                            "prompt_sha256": v3.PROMPT_SHA256,
                            "schema_sha256": v3.SCHEMA_SHA256,
                            "request_sha256": v3.REQUEST_SHA256,
                        },
                        "paid_ceiling": CEILING,
                        "paid_command": paid_command(),
                        "requests_made": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0
        except Exception as exc:
            print(json.dumps({**_refused(exc), "requests_made": 0}, sort_keys=True))
            return 1
    if not args.approved_provider_disclosure:
        print("Explicit provider disclosure is required.")
        return 2
    budget = None
    try:
        ctx = preconditions(ROOT, private, args.gold, args.gold_sha256)
        _outputs_absent(private)
        # The token's ceiling is checked read-only first, so a wrong or missing token
        # refuses with no key read and the token unspent; then again on the grant.
        if io.paid_token_preflight() != CEILING:
            raise ValueError("the Phase C token ceiling must be 300")
        key = io.read_key()
        if not key:
            raise ValueError("missing provider key")
        budget = consent.start_paid_run()
        if budget.max_calls != CEILING:
            raise ValueError("the Phase C token ceiling must be 300")
        report = run(ctx, key, budget)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        consent.abort_paid_run("v3_dev_failed")
        print(
            json.dumps(
                {
                    **_refused(exc),
                    "status": "stopped",
                    "requests_made": budget.calls_made if budget else 0,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
