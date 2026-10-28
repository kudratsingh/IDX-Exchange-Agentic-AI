"""Run the separately approved 100-case Haiku v2.1 development comparison."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import extract_enrichment_dev as old  # noqa: E402
from scripts.extract_enrichment_test import verify_freeze  # noqa: E402
from scripts.score_enrichment_private import _read_private, _sample_jsonl  # noqa: E402

from idx_agent.enrichment.v2 import score_v2  # noqa: E402
from idx_agent.enrichment.v21 import parameters, parse, schema  # noqa: E402
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"
PROMPT_HASH = "7548bfb1590249ef6015ffe62b947e209d84f5a986b9d9f995b0ccb2caa4e1de"
SCHEMA_HASH = "036155fd435c9ce61891a917252d8f68ee8a02fd9124e3bcf0d689e00cf47a03"
MANIFEST_HASH = "b59c6690fe135b52aa1428d12b2a71480e4387589758e9c8433512aebae7b907"


def verify_v21_freeze():
    """Verify the pinned manifest and all of its files before using a token."""
    raw = (ROOT / "docs/ENRICHMENT_V21_FREEZE.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_HASH:
        raise ValueError("v2.1 manifest changed")
    manifest = json.loads(raw)
    if manifest.get("version") != 1 or manifest.get("schema_sha256") != SCHEMA_HASH:
        raise ValueError("invalid v2.1 manifest")
    for relative, expected in manifest["files"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("v2.1 dependency changed")
    actual_schema = hashlib.sha256(
        json.dumps(
            schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    if actual_schema != manifest["schema_sha256"]:
        raise ValueError("v2.1 schema changed")


def send(text, prompt, key, retries):
    request = urllib.request.Request(
        old.ENDPOINT,
        data=json.dumps(parameters(prompt, text), ensure_ascii=False).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    retry_cause = None
    for attempt in range(1, 4):
        consent.spend_paid_call()
        if retry_cause is not None:
            retries[retry_cause] = retries.get(retry_cause, 0) + 1
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            body = exc.read()
            category = (
                "RateLimitError"
                if exc.code == 429
                else "ServerError"
                if 500 <= exc.code <= 599
                else "AuthenticationError"
                if exc.code in (401, 403)
                else "ClientError"
            )
            retryable = exc.code == 429 or 500 <= exc.code <= 599
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            category = (
                "TimeoutError"
                if isinstance(reason, TimeoutError)
                else "ConnectionError"
            )
            retryable, body = True, None
        print(
            json.dumps(
                {
                    "provider_error": {
                        "error_class": category,
                        "attempt": attempt,
                        "retrying": retryable and attempt < 3,
                    }
                }
            ),
            flush=True,
        )
        if not retryable or attempt == 3:
            raise old.ProviderFailure(body, "provider_failure") from None
        time.sleep(2 ** (attempt - 1))
        retry_cause = category
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"invalid_response": True}, None, raw
    return response, response.get("usage") if isinstance(response, dict) else None, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args()
    if not args.approved_provider_disclosure:
        return 2
    budget = None
    completed = 0
    retries = {}
    try:
        verify_v21_freeze()
        verify_freeze()
        prompt = (ROOT / "docs/ENRICHMENT_EXTRACTION_V21.md").read_text()
        if (
            hashlib.sha256(prompt.encode()).hexdigest() != PROMPT_HASH
            or hashlib.sha256(
                json.dumps(
                    schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            != SCHEMA_HASH
        ):
            raise ValueError("v2.1 contract changed")
        from evals.run import _local_setting

        key = _local_setting("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("missing key")
        sample = _sample_jsonl(PRIVATE, "dev")
        cases = [(x["id"], x["text"]) for x in sample["cases"] if x["split"] == "dev"]
        if len(cases) != 100 or len({x[0] for x in cases}) != 100:
            raise ValueError("invalid dev set")
        output = PRIVATE / "predictions-dev-v21-haiku.json"
        usage_path = PRIVATE / "usage-dev-v21-haiku.json"
        if output.exists() or usage_path.exists():
            raise ValueError("existing output")
        journal = PRIVATE / "checkpoints" / "v21-dev-haiku"
        if journal.parent.is_symlink():
            raise ValueError("invalid checkpoint parent")
        journal.mkdir(mode=0o700, parents=True, exist_ok=False)
        if journal.stat().st_mode & 0o077:
            raise ValueError("invalid checkpoint permissions")
        budget = consent.start_paid_run()
        if budget.max_calls < 300:
            raise ValueError("insufficient ceiling")
        fields = (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        totals, known = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0)
        rows, misses, no_calls, thinking, thinking_known = [], 0, 0, 0, 0
        for index, (case_id, text) in enumerate(cases, 1):
            try:
                response, usage, raw = send(text, prompt, key, retries)
            except old.ProviderFailure as error:
                if error.raw is not None:
                    debug = PRIVATE / "debug"
                    if debug.is_symlink():
                        raise ValueError("invalid debug") from None
                    debug.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if debug.stat().st_mode & 0o077:
                        raise ValueError("debug permissions") from None
                    fd = os.open(
                        debug / f"v21-http-{uuid.uuid4().hex}.json",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                    )
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(error.raw)
                print(
                    json.dumps(
                        {
                            "diagnostic": {
                                "error_class": "ProviderFailure",
                                "field": "provider",
                                "rule": error.rule,
                            }
                        }
                    ),
                    flush=True,
                )
                raise
            old._write_new(
                journal / f"{index:03d}.json",
                {"raw": base64.b64encode(raw).decode("ascii"), "usage": usage},
            )
            completed += 1
            if isinstance(usage, dict):
                for field in fields:
                    if type(usage.get(field)) is int and usage[field] >= 0:
                        totals[field] += usage[field]
                        known[field] += 1
                details = usage.get("output_tokens_details")
                if (
                    isinstance(details, dict)
                    and type(details.get("thinking_tokens")) is int
                ):
                    thinking += details["thinking_tokens"]
                    thinking_known += 1
            annotations, errors = parse(response, text)
            if errors:
                misses += 1
                no_calls += any(e["rule"] == "no_extraction_tool_call" for e in errors)
                debug = PRIVATE / "debug"
                if debug.is_symlink():
                    raise ValueError("invalid debug")
                debug.mkdir(mode=0o700, parents=True, exist_ok=True)
                if debug.stat().st_mode & 0o077:
                    raise ValueError("debug permissions")
                old._write_new(
                    debug / f"v21-{index:03d}.json",
                    {"raw": base64.b64encode(raw).decode("ascii")},
                )
                for error in errors:
                    print(json.dumps({"diagnostic": error}, sort_keys=True), flush=True)
            rows.append({"id": case_id, "annotations": annotations})
        predictions = {"version": 1, "dataset_id": sample["dataset_id"], "labels": rows}
        scores = score_v2(
            sample, _read_private(PRIVATE, "labels.json"), predictions, "dev"
        )
        metrics = {
            name: {
                "gold": x.expected,
                "predicted": x.predicted,
                "correct": x.correct,
                "precision": x.precision,
                "recall": x.recall,
                "f1": x.f1,
            }
            for name, x in scores.items()
        }
        f1 = scores["overall"].f1
        output_average = (
            totals["output_tokens"] / 100 if known["output_tokens"] == 100 else None
        )
        report = {
            "model": "claude-haiku-5-5",
            "requests_made": budget.calls_made,
            "retries_by_error_class": retries,
            "remarks_with_misses": misses,
            "no_tool_calls": no_calls,
            "thinking_tokens": thinking if thinking_known == 100 else None,
            "usage": {f: totals[f] if known[f] == 100 else None for f in fields},
            "metrics": metrics,
            "bulk_eligible": f1 is not None
            and f1 + 0.03 >= 0.946927374301676
            and output_average is not None
            and output_average < 400,
            "contract_hashes": {
                "prompt": hashlib.sha256(prompt.encode()).hexdigest(),
                "schema": hashlib.sha256(
                    json.dumps(
                        schema(),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
                "implementation": hashlib.sha256(
                    (ROOT / "src/idx_agent/enrichment/v21.py").read_bytes()
                ).hexdigest(),
                "driver": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
        }
        old._write_new(output, predictions)
        old._write_new(usage_path, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        consent.abort_paid_run("v21_dev_failed")
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
