"""WO-034 Phase D: the one sealed held-out command (written in Phase B, never run).
Frozen production v2 and frozen v3 on 150 held-out remarks, one shared 600-call
ledger, sealed inputs verified first, nothing released before both are complete.
--dry-run checks the seal and prints the ledger state; no key, token, network or write.
"""

# Contract (docs/ENRICHMENT_EXTRACTION_V3.md, "The Phase D command contract"):
# 150 initial requests per configuration, sent first and alternating case by case;
# retries afterwards in a fixed case order, at most three attempts per remark and
# configuration, from the same 600. Exhaustion stops the run, incomplete and final;
# the ceiling is never expanded. While it runs it prints only calls used, calls left
# and cases complete per configuration. The first invocation's token carries exactly
# the 600. Only after a provider or auth failure with calls left may a resumed
# invocation run, under a new command-bound `paid` token whose ceiling is at most the
# calls left; it reuses the same sealed run and ledger, never resets a count, reuses
# completed checkpoints without resending and keeps the failed request counted. Any
# other stop (token cap or refusal, an interrupted invocation) leaves the run final, and
# a run with no calls left is exhausted whatever stopped it. Before any key is read or
# token spent, every local precondition is checked: the lock (first, before any private
# file is opened), the seal, the ledger, and the token's ceiling, read without spending.

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import enrichment_v3_io as io  # noqa: E402

from idx_agent.enrichment import v3  # noqa: E402
from idx_agent.enrichment.v2 import (  # noqa: E402
    canonical_schema_hash,
    message_parameters,
    parse_v2,
    score_v2,
)
from idx_agent.safety import consent  # noqa: E402

PRIVATE = ROOT / "data" / "enrichment"
FREEZE = "docs/ENRICHMENT_V3_D_FREEZE.json"
LOCK = "docs/ENRICHMENT_V3_D_LOCK.json"
FREEZE_FORMAT = "enrichment-v3-phase-d-freeze/1"
LOCK_FORMAT = "enrichment-v3-phase-d-lock/1"
LEDGER_FORMAT = "enrichment-v3-phase-d-ledger/1"
BUDGET = 600
INITIAL = 150
MAX_ATTEMPTS = 3
CONFIGS = ("v2", "v3")
MODEL = "claude-sonnet-5-5"
RUN_DIR = "v3-heldout"
COMMAND = (
    "python scripts/extract_enrichment_v3_heldout.py --seal-sha256 {seal} "
    "--approved-provider-disclosure"
)
V2_PROMPT = "docs/ENRICHMENT_EXTRACTION_V2.md"
V2_PROMPT_SHA256 = "e1ccb614145cca19f05b403d22a214ba597816049dc192aad057f9e60d25ba24"
V2_SCHEMA_SHA256 = "036155fd435c9ce61891a917252d8f68ee8a02fd9124e3bcf0d689e00cf47a03"
V1_REFERENCE = "predictions-test-heldout.json"
V1_REFERENCE_SHA256 = "7261b397badcecd79e34fbab90e5fb5f8621851190a25954eaf4cff6481e213f"
SEALED_FILES = (
    "scripts/extract_enrichment_v3_heldout.py",
    "scripts/enrichment_v3_io.py",
    "scripts/extract_enrichment_dev.py",
    "scripts/score_enrichment_private.py",
    "src/idx_agent/enrichment/v3.py",
    "src/idx_agent/enrichment/v2.py",
    "src/idx_agent/enrichment/dev_extraction.py",
    "src/idx_agent/enrichment/private_scoring.py",
    "src/idx_agent/enrichment/vocabulary.py",
    "docs/ENRICHMENT_EXTRACTION_V2.md",
    "docs/ENRICHMENT_EXTRACTION_V3.md",
    "docs/ENRICHMENT_V3_FREEZE.json",
    "docs/ENRICHMENT_SCORING_V1.md",
)
# The only stops after which a new token may resume the same run (owner, 2026-11-04).
RESUMABLE = frozenset({"provider_failure", "auth_failure"})
FINAL = frozenset({"exhausted", "failed", "released"})


def transport(body: dict, key: str) -> bytes:
    """One standard Messages API request (replaced by a fake in tests)."""
    return io.attempt(body, key)


def current_command() -> str:
    """This process's command line as the token reader normalizes it."""
    return consent.display_command(consent.invocation_argv())


def v2_hashes(root: Path) -> dict[str, str]:
    """Frozen production v2: prompt file bytes, canonical schema, request settings."""
    prompt = io.file_sha256(root / V2_PROMPT)
    if prompt != V2_PROMPT_SHA256 or canonical_schema_hash() != V2_SCHEMA_SHA256:
        raise v3.ContractError("v2 contract changed")
    built = message_parameters(MODEL, "prompt", "remark")
    settings = {
        k: built[k]
        for k in ("model", "max_tokens", "thinking", "output_config", "tool_choice")
    }
    return {
        "prompt_sha256": prompt,
        "schema_sha256": V2_SCHEMA_SHA256,
        "request_sha256": v3.sha256(v3.canonical(settings)),
    }


def v3_hashes(root: Path) -> dict[str, str]:
    v3.verify_contract(root)
    return {
        "prompt_sha256": v3.PROMPT_SHA256,
        "schema_sha256": v3.SCHEMA_SHA256,
        "request_sha256": v3.REQUEST_SHA256,
        "freeze_file_sha256": io.file_sha256(root / v3.FREEZE_FILE),
    }


def build_lock(root: Path) -> dict:
    """The content `docs/ENRICHMENT_V3_D_LOCK.json` must hold (written after C)."""
    return {
        "format": LOCK_FORMAT,
        "work_order": "WO-034",
        "v3": v3_hashes(root),
        "parser": {
            path: io.file_sha256(root / path)
            for path in (
                "src/idx_agent/enrichment/v3.py",
                "scripts/extract_enrichment_v3_heldout.py",
            )
        },
        "mapper": v3.mapper_hashes(),
    }


def build_seal(root: Path, private: Path, gold_name: str) -> dict:
    """The content the final freeze must hold, recomputed from the current files.

    The lock must verify first. Private files contribute hashes only."""
    lock_raw = (root / LOCK).read_bytes()
    if json.loads(lock_raw) != build_lock(root):
        raise v3.ContractError("the Phase D lock does not verify")
    gold_sha = io.file_sha256(private / gold_name)
    if gold_name == "labels.json" or gold_sha == io.ORIGINAL_GOLD_SHA256:
        raise v3.ContractError("a revised held-out gold is required")
    if io.file_sha256(private / V1_REFERENCE) != V1_REFERENCE_SHA256:
        raise v3.ContractError("v1 reference predictions changed")
    return {
        "format": FREEZE_FORMAT,
        "work_order": "WO-034",
        "paid_calls_before_freeze": 0,
        "command": COMMAND,
        "budget": BUDGET,
        "initial_per_configuration": INITIAL,
        "max_attempts": MAX_ATTEMPTS,
        "configurations": list(CONFIGS),
        "lock": {"file": LOCK, "sha256": v3.sha256(lock_raw)},
        "repo_files": {path: io.file_sha256(root / path) for path in SEALED_FILES},
        "contracts": {"v2": v2_hashes(root), "v3": v3_hashes(root)},
        "mapper": v3.mapper_hashes(),
        "private_files": {
            "gold": {"file": gold_name, "sha256": gold_sha},
            "splits.json": io.file_sha256(private / "splits.json"),
            "sample.jsonl": io.file_sha256(private / "sample.jsonl"),
            "v1_reference": {"file": V1_REFERENCE, "sha256": V1_REFERENCE_SHA256},
        },
    }


def verify_seal(root: Path, private: Path, seal_sha256: str) -> dict:
    """Verify every sealed input; return the run context. No token, no network.

    The lock is checked first: before it exists nothing private is opened."""
    if not (root / LOCK).is_file():
        raise v3.ContractError("the Phase D lock is missing")
    path = root / FREEZE
    if not path.is_file():
        raise v3.ContractError("the Phase D final freeze is missing")
    raw = path.read_bytes()
    if v3.sha256(raw) != seal_sha256:
        raise v3.ContractError("final freeze hash mismatch")
    seal = json.loads(raw)
    gold_name = seal.get("private_files", {}).get("gold", {}).get("file")
    if not isinstance(gold_name, str) or seal != build_seal(root, private, gold_name):
        raise v3.ContractError("a sealed input changed")
    sample, subtypes = io.load_split(private, "test")
    cases = [(c["id"], c["text"]) for c in sample["cases"] if c["split"] == "test"]
    if len(cases) != INITIAL or len({key for key, _ in cases}) != INITIAL:
        raise ValueError("invalid held-out set")
    gold, _ = io.revised_gold(
        private, gold_name, seal["private_files"]["gold"]["sha256"]
    )
    check = score_v2(sample, gold, gold, "test")["overall"]
    if not check.expected == check.predicted == check.correct:
        raise ValueError("the scorer rejects the revised gold")
    v3.gold_consistency(gold, sample, subtypes, "test")
    prompt, schema, request = v3.verify_contract(root)
    return {
        "seal_sha256": seal_sha256,
        "sample": sample,
        "subtypes": subtypes,
        "cases": cases,
        "gold": gold,
        "private": private,
        "v2_prompt": (root / V2_PROMPT).read_text(encoding="utf-8"),
        "v3": (prompt, schema, request),
    }


def body_for(ctx: dict, config: str, index: int) -> dict:
    text = ctx["cases"][index][1]
    if config == "v2":
        return message_parameters(MODEL, ctx["v2_prompt"], text)
    prompt, schema, request = ctx["v3"]
    return v3.request_body(prompt, schema, request, text)


# The ledger: one private JSON file per sealed run, rewritten atomically after every
# change and before every request is sent.


def new_ledger(seal_sha256: str) -> dict:
    return {
        "format": LEDGER_FORMAT,
        "seal_sha256": seal_sha256,
        "budget": BUDGET,
        "initial_per_configuration": INITIAL,
        "max_attempts": MAX_ATTEMPTS,
        "calls_used": 0,
        "status": "running",
        "stop_reason": None,
        "items": {
            c: [{"attempts": 0, "state": "pending"} for _ in range(INITIAL)]
            for c in CONFIGS
        },
        "errors_by_class": {c: {} for c in CONFIGS},
        "invocations": [],
    }


def check_ledger(ledger: dict, seal_sha256: str) -> None:
    """A ledger belongs to one sealed run and can never hold a larger ceiling."""
    items = ledger.get("items", {})
    if (
        ledger.get("format") != LEDGER_FORMAT
        or ledger.get("seal_sha256") != seal_sha256
        or ledger.get("budget") != BUDGET
        or ledger.get("initial_per_configuration") != INITIAL
        or ledger.get("max_attempts") != MAX_ATTEMPTS
        or set(items) != set(CONFIGS)
        or any(len(items[c]) != INITIAL for c in CONFIGS)
    ):
        raise ValueError("the ledger does not belong to this sealed run")
    attempts = sum(x["attempts"] for c in CONFIGS for x in items[c])
    used = ledger.get("calls_used")
    if type(used) is not int or not attempts == used <= BUDGET:
        raise ValueError("invalid ledger counts")
    if any(not 0 <= x["attempts"] <= MAX_ATTEMPTS for c in CONFIGS for x in items[c]):
        raise ValueError("invalid ledger counts")


def calls_left(ledger: dict) -> int:
    return ledger["budget"] - ledger["calls_used"]


def complete_counts(ledger: dict) -> dict[str, int]:
    return {c: sum(x["state"] == "done" for x in ledger["items"][c]) for c in CONFIGS}


def progress(ledger: dict) -> dict:
    return {
        "calls_used": ledger["calls_used"],
        "calls_left": calls_left(ledger),
        "complete": complete_counts(ledger),
    }


def next_action(ledger: dict) -> tuple[str, int, bool] | None:
    """Initial requests first, alternating case by case; then retries in a fixed
    case order, second attempts before third."""
    items = ledger["items"]
    for index in range(INITIAL):
        for config in CONFIGS:
            if items[config][index]["attempts"] == 0:
                return config, index, False
    for attempts in range(1, MAX_ATTEMPTS):
        for index in range(INITIAL):
            for config in CONFIGS:
                item = items[config][index]
                if item["state"] == "retry" and item["attempts"] == attempts:
                    return config, index, True
    return None


class Run:
    """One invocation's loop over the shared ledger. File and network access are
    the injected callables; the gate itself is pure bookkeeping."""

    def __init__(self, ledger, save, write_checkpoint, record, out):
        self.ledger, self.save, self.write_checkpoint = ledger, save, write_checkpoint
        self.record, self.out = record, out

    def _invocation(self) -> dict:
        return self.ledger["invocations"][-1]

    def begin(self, kind: str, token_max_calls: int) -> None:
        self.ledger["status"] = "running"
        self.ledger["stop_reason"] = None
        self.ledger["invocations"].append(
            {
                "number": len(self.ledger["invocations"]) + 1,
                "kind": kind,
                "token_max_calls": token_max_calls,
                "calls_at_start": self.ledger["calls_used"],
                "calls": 0,
                "stop_reason": None,
            }
        )
        self.save(self.ledger)
        self.record({"event": kind, **self._evidence()})

    def _evidence(self) -> dict:
        invocation = self._invocation()
        return {
            "invocation": invocation["number"],
            "token_max_calls": invocation["token_max_calls"],
            **progress(self.ledger),
        }

    def stop(self, status: str, reason: str, error_class: str | None = None) -> str:
        self.ledger["status"], self.ledger["stop_reason"] = status, reason
        self._invocation()["stop_reason"] = reason
        self.save(self.ledger)
        self.record(
            {
                "event": "stop",
                "status": status,
                "reason": reason,
                "error_class": error_class,
                **self._evidence(),
            }
        )
        return status

    def interrupted(self) -> None:
        """Persist an invocation that ended mid-request (an interrupt or a local
        error): the request stays counted, the run is final, and with no calls left
        it is exhausted. Best effort; the original exception is re-raised."""
        try:
            if calls_left(self.ledger) <= 0:
                self.stop("exhausted", "budget_exhausted", "interrupted")
            else:
                self.stop("stopped", "interrupted")
        except Exception:  # noqa: BLE001 - never mask the interrupt itself
            pass

    def execute(self, token, send, sleep=None) -> str:
        """Spend calls until both configurations are complete or the run stops."""
        ledger, sleep = self.ledger, sleep or time.sleep
        while True:
            items = ledger["items"]
            if any(x["state"] == "failed" for c in CONFIGS for x in items[c]):
                return self.stop("failed", "retry_limit")
            action = next_action(ledger)
            if action is None:
                if all(x["state"] == "done" for c in CONFIGS for x in items[c]):
                    ledger["status"] = "complete"
                    self.save(ledger)
                    return "complete"
                raise ValueError("inconsistent ledger")
            config, index, is_retry = action
            left = calls_left(ledger)
            unsent = sum(x["attempts"] == 0 for c in CONFIGS for x in items[c])
            if left <= 0 or (is_retry and left <= unsent):
                return self.stop("exhausted", "budget_exhausted")
            if token.remaining < 1:
                return self.stop("stopped", "token_cap")
            item = items[config][index]
            if is_retry:
                sleep(2 ** (item["attempts"] - 1))
            try:
                consent.spend_paid_call()
            except consent.PaidRunRefused as exc:
                return self.stop("stopped", "token_refused", exc.reason)
            ledger["calls_used"] += 1
            item["attempts"] += 1
            item["state"] = "in_flight"
            self._invocation()["calls"] += 1
            self.save(ledger)
            try:
                raw = send(config, index)
            except io.AttemptError as error:
                errors = ledger["errors_by_class"][config]
                errors[error.category] = errors.get(error.category, 0) + 1
                item["state"] = "retry" if item["attempts"] < MAX_ATTEMPTS else "failed"
                if error.auth or not error.retryable:
                    if calls_left(ledger) <= 0:
                        # The last call failed: nothing is left to resume with.
                        reason = "budget_exhausted"
                        return self.stop("exhausted", reason, error.category)
                    reason = "auth_failure" if error.auth else "provider_failure"
                    return self.stop("stopped", reason, error.category)
                self.save(ledger)
                self.out(progress(ledger))
                continue
            except BaseException:
                self.interrupted()
                raise
            try:
                self.write_checkpoint(config, index, raw)
            except BaseException:
                self.interrupted()
                raise
            item["state"] = "done"
            self.save(ledger)
            self.out(progress(ledger))


def score_and_release(ctx: dict, run_dir: Path, ledger: dict) -> dict:
    """Machine-only parsing, mapping and scoring after both configurations are
    complete; the private result is written and the aggregate release returned."""
    sample, subtypes, gold = ctx["sample"], ctx["subtypes"], ctx["gold"]
    ids = [case_id for case_id, _ in ctx["cases"]]
    scores, report = {}, {}
    for config in CONFIGS:
        rows, spans, usage = [], {}, io.Usage()
        misses = no_calls = 0
        for index, (case_id, text) in enumerate(ctx["cases"]):
            response, used, _ = io.read_checkpoint(_checkpoint(run_dir, config, index))
            usage.add(used)
            if config == "v2":
                annotations, errors = parse_v2(response, text)
            else:
                annotations, errors, spans[case_id] = v3.parse_v3(response, text)
            misses += bool(errors)
            no_calls += any(e["rule"] == "no_extraction_tool_call" for e in errors)
            rows.append({"id": case_id, "annotations": annotations})
        predictions = {"version": 1, "dataset_id": sample["dataset_id"], "labels": rows}
        io.atomic_write(run_dir / f"predictions-{config}.json", predictions)
        mapped, sides, removed = v3.map_payload(predictions, sample, subtypes, "test")
        io.atomic_write(
            run_dir / f"mapping-{config}.json",
            {"version": 1, "rule": v3.SUBTYPE_RULE, "cases": sides},
        )
        scores[config] = score_v2(sample, gold, mapped, "test")
        report[config] = {
            "metrics": v3.counts_json(scores[config]),
            "removed_by_polarity": removed,
            "remarks_with_misses": misses,
            "no_tool_calls": no_calls,
            "attempts": sum(x["attempts"] for x in ledger["items"][config]),
            "errors_by_class": ledger["errors_by_class"][config],
            "usage": usage.report(INITIAL),
        }
        if config == "v3":
            report[config]["span_quality"] = v3.span_quality(spans, gold, ids)
    reference = io.read_private(ctx["private"], V1_REFERENCE)
    mapped, _, removed = v3.map_payload(reference, sample, subtypes, "test")
    v1 = score_v2(sample, gold, mapped, "test")
    result = {
        "verdict": v3.phase_d_verdict(scores["v3"], scores["v2"]),
        "configurations": report,
        "v1_reference": {
            "note": "historical reference only; sets no bar",
            "metrics": v3.counts_json(v1),
            "removed_by_polarity": removed,
        },
        "subtype_counts": dict(sorted(Counter(subtypes.values()).items())),
        "calls_used": ledger["calls_used"],
        "budget": BUDGET,
        "invocations": len(ledger["invocations"]),
        "seal_sha256": ctx["seal_sha256"],
        "second_use_of_heldout": True,
    }
    io.atomic_write(run_dir / "result.json", result)
    return result


def _checkpoint(run_dir: Path, config: str, index: int) -> Path:
    return run_dir / "checkpoints" / config / f"{index + 1:03d}.json"


def _emit(value: dict) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def ledger_state(ledger: dict | None) -> dict:
    """What the next invocation may do, for the dry run and refusals. A ledger left
    `running` belongs to an interrupted invocation, which is not resumable; a ledger
    with no calls left is exhausted, whatever its last stop."""
    if ledger is None:
        return {
            "status": "not_started",
            "calls_used": 0,
            "calls_left": BUDGET,
            "max_token_calls": BUDGET,
        }
    status, reason = ledger["status"], ledger["stop_reason"]
    if any(x["state"] == "failed" for c in CONFIGS for x in ledger["items"][c]):
        status, reason = "failed", "retry_limit"
    elif status not in ("complete", "released") and calls_left(ledger) <= 0:
        status, reason = "exhausted", "budget_exhausted"
    elif status == "running":
        status, reason = "stopped", "interrupted"
    resumable = status == "stopped" and reason in RESUMABLE
    return {
        "status": status,
        "stop_reason": reason,
        **progress(ledger),
        "resumable": resumable,
        "max_token_calls": calls_left(ledger) if resumable else 0,
    }


def check_ceiling(max_calls: int, ledger: dict | None, state: dict) -> None:
    """The first token carries exactly the 600; a resume token at most the calls
    left (owner, 2026-11-04)."""
    if ledger is None and max_calls != BUDGET:
        raise ValueError("the first token must carry exactly 600 calls")
    if max_calls > state["max_token_calls"]:
        raise ValueError("the token ceiling exceeds the calls left")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    parser.add_argument("--private-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approved-provider-disclosure", action="store_true")
    args = parser.parse_args(argv)
    private = args.private_dir or PRIVATE
    run_dir = private / RUN_DIR
    ledger_path = run_dir / "ledger.json"
    expected_command = COMMAND.format(seal=args.seal_sha256)
    token = None
    try:
        ctx = verify_seal(ROOT, private, args.seal_sha256)
        words = current_command().split()
        if args.dry_run:
            words = [w for w in words if w != "--dry-run"]
        if " ".join(words) != expected_command:
            raise v3.ContractError("the command differs from the sealed command")
        ledger = None
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            check_ledger(ledger, args.seal_sha256)
        state = ledger_state(ledger)
        if args.dry_run:
            _emit(
                {
                    "mode": "dry_run",
                    "paid_command": expected_command,
                    **state,
                    "requests_made": 0,
                }
            )
            return 0
        if not args.approved_provider_disclosure:
            print("Explicit provider disclosure is required.")
            return 2
        if state["status"] in FINAL:
            raise ValueError(f"the run is final ({state['status']})")
        if state["status"] == "complete":
            return _release(ctx, run_dir, ledger, ledger_path)
        if ledger is not None and not state["resumable"]:
            raise ValueError("the run cannot be resumed")
        # The token's ceiling is checked read-only first, so a wrong or missing token
        # refuses with no key read and the token unspent; then again on the grant.
        check_ceiling(io.paid_token_preflight(), ledger, state)
        key = io.read_key()
        if not key:
            raise ValueError("missing provider key")
        token = consent.start_paid_run()
        check_ceiling(token.max_calls, ledger, state)
        io.private_subdir(run_dir, exist_ok=True)
        for config in CONFIGS:
            io.private_subdir(run_dir / "checkpoints" / config, exist_ok=True)
        evidence = run_dir / "evidence.jsonl"

        def save(value):
            io.atomic_write(ledger_path, value)

        def record(entry):
            with evidence.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")

        def write_checkpoint(config, index, raw):
            _, usage = io.decode(raw)
            io.write_checkpoint(_checkpoint(run_dir, config, index), raw, usage)

        kind = "initial"
        if ledger is None:
            ledger = new_ledger(args.seal_sha256)
        else:
            kind = "resume"
        run = Run(ledger, save, write_checkpoint, record, _emit)
        run.begin(kind, token.max_calls)
        status = run.execute(
            token, lambda config, index: transport(body_for(ctx, config, index), key)
        )
        if status != "complete":
            consent.abort_paid_run(f"v3_heldout_{status}")
            _emit(
                {
                    "status": status,
                    "stop_reason": ledger["stop_reason"],
                    **progress(ledger),
                    "released": False,
                }
            )
            return 1
        return _release(ctx, run_dir, ledger, ledger_path)
    except Exception as exc:
        if token is not None:
            consent.abort_paid_run("v3_heldout_failed")
        _emit(
            {
                "status": "refused" if token is None else "stopped",
                "error_class": type(exc).__name__,
                "reason": str(exc) if isinstance(exc, ValueError) else None,
                "released": False,
            }
        )
        return 1


def _release(ctx, run_dir, ledger, ledger_path) -> int:
    result = score_and_release(ctx, run_dir, ledger)
    ledger["status"] = "released"
    io.atomic_write(ledger_path, ledger)
    _emit({"release": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
