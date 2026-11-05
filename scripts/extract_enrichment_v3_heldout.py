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
# the 600. After a provider or auth failure or an interrupted invocation, with calls
# left, a resumed invocation may run under a new command-bound `paid` token whose
# ceiling is at most the calls left, and only if the sealed inputs re-verify, the
# durable ledger, the run evidence and every checkpoint agree, the stop is recorded in
# the evidence and nothing has been released. It reuses the same sealed run and
# ledger, never resets a count, never resends a completed request and keeps every
# failed or ambiguous attempt counted. Corrupt or unverifiable run state stops the run
# and marks it final. A token cap or refusal leaves the run final, and a run with no
# calls left is exhausted whatever stopped it. Before any key is read or token spent,
# every local precondition is checked: the lock (first, before any private file is
# opened), the seal, the run state, and the token's ceiling, read without spending.

from __future__ import annotations

import argparse
import json
import os
import re
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
# Owner decision 1, 2026-11-04: the exposed held-out case, excluded from the primary
# score only (still requested). Private; its case ids are never printed or tracked.
EXCLUSIONS = "v3-heldout-exclusions-v1.json"
EXCLUSIONS_SHA256 = "2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0"
EXCLUSION_KEYS = frozenset(
    {
        "version",
        "excluded_case_ids",
        "reason",
        "date",
        "split",
        "primary_n",
        "diagnostic_n",
    }
)
DIAGNOSTIC_NOTE = (
    "owner decision 1 (2026-11-04): the full-150 score, from the same outputs, is a "
    "diagnostic only and never decides the pass; the primary score excludes the "
    "exposed held-out case"
)
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
# The only stops after which a new token may resume the same run (owner, 2026-11-04,
# decisions on the provider or auth failure and decision 2 on interrupted runs).
RESUMABLE = frozenset({"provider_failure", "auth_failure", "interrupted"})
FINAL = frozenset({"exhausted", "failed", "released"})
STATUSES = frozenset({"running", "stopped", "complete", *FINAL})
ITEM_STATES = frozenset({"pending", "in_flight", "retry", "done", "failed"})
# Written once when the run state does not verify; every later invocation refuses.
FINAL_MARKER = "final.json"
RELEASE_FILES = frozenset(
    {"result.json"}
    | {f"{kind}-{c}.json" for kind in ("predictions", "mapping") for c in CONFIGS}
)
_CHECKPOINT_NAME = re.compile(r"[0-9]{3}\.json")


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
    if not (private / EXCLUSIONS).is_file():
        raise v3.ContractError("the held-out exclusion file is missing")
    exclusions_sha = io.file_sha256(private / EXCLUSIONS)
    if exclusions_sha != EXCLUSIONS_SHA256:
        raise v3.ContractError("the held-out exclusion is not the frozen file")
    splits = io.read_private(private, "splits.json")["splits"]
    excluded = load_exclusions(private, {k for k, v in splits.items() if v == "test"})
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
            "exclusions": {
                "file": EXCLUSIONS,
                "sha256": exclusions_sha,
                "excluded": len(excluded),
                "primary_n": INITIAL - len(excluded),
                "diagnostic_n": INITIAL,
            },
        },
    }


def load_exclusions(private: Path, test_ids: set[str]) -> frozenset[str]:
    """The case ids excluded from the primary score (owner decision 1), validated
    against the held-out split. Never printed: errors name no id."""
    if not (private / EXCLUSIONS).is_file():
        raise v3.ContractError("the held-out exclusion file is missing")
    value = io.read_private(private, EXCLUSIONS)
    ids = value.get("excluded_case_ids")
    if (
        set(value) != EXCLUSION_KEYS
        or value["version"] != 1
        or value["split"] != "test"
        or not isinstance(ids, list)
        or not ids
        or any(not isinstance(case_id, str) for case_id in ids)
        or len(set(ids)) != len(ids)
        or not set(ids) <= test_ids
        or value["diagnostic_n"] != len(test_ids)
        or value["primary_n"] != len(test_ids) - len(ids)
    ):
        raise v3.ContractError("invalid held-out exclusion")
    return frozenset(ids)


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
    if not isinstance(gold_name, str) or Path(gold_name).name != gold_name:
        raise v3.ContractError("a sealed input changed")
    if not (private / gold_name).is_file():
        raise v3.ContractError("the revised held-out gold file is missing")
    sealed_exclusions = seal.get("private_files", {}).get("exclusions")
    if (
        not isinstance(sealed_exclusions, dict)
        or sealed_exclusions.get("file") != EXCLUSIONS
    ):
        raise v3.ContractError("the seal does not record the held-out exclusion")
    if not (private / EXCLUSIONS).is_file():
        raise v3.ContractError("the held-out exclusion file is missing")
    if io.file_sha256(private / EXCLUSIONS) != sealed_exclusions.get("sha256"):
        raise v3.ContractError("held-out exclusion hash mismatch")
    if seal != build_seal(root, private, gold_name):
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
    excluded = load_exclusions(private, {key for key, _ in cases})
    prompt, schema, request = v3.verify_contract(root)
    return {
        "seal_sha256": seal_sha256,
        "excluded": excluded,
        "exclusions_sha256": sealed_exclusions["sha256"],
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
    every = [x for c in CONFIGS for x in items[c]]
    if any(
        not isinstance(x, dict)
        or set(x) != {"attempts", "state"}
        or type(x["attempts"]) is not int
        or x["state"] not in ITEM_STATES
        for x in every
    ):
        raise ValueError("invalid ledger counts")
    attempts = sum(x["attempts"] for x in every)
    used = ledger.get("calls_used")
    if type(used) is not int or not attempts == used <= BUDGET:
        raise ValueError("invalid ledger counts")
    if any(not 0 <= x["attempts"] <= MAX_ATTEMPTS for x in every):
        raise ValueError("invalid ledger counts")
    if any((x["state"] == "pending") != (x["attempts"] == 0) for x in every):
        raise ValueError("invalid ledger counts")
    if sum(x["state"] == "in_flight" for x in every) > 1:
        raise ValueError("invalid ledger counts")
    if ledger.get("status") not in STATUSES:
        raise ValueError("invalid ledger status")
    invocations = ledger.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        raise ValueError("invalid ledger invocations")
    start = 0
    for number, invocation in enumerate(invocations, 1):
        if (
            not isinstance(invocation, dict)
            or invocation.get("number") != number
            or invocation.get("kind") != ("initial" if number == 1 else "resume")
            or invocation.get("calls_at_start") != start
            or type(invocation.get("calls")) is not int
            or type(invocation.get("token_max_calls")) is not int
            or not 0 <= invocation["calls"] <= invocation["token_max_calls"]
        ):
            raise ValueError("invalid ledger invocations")
        start += invocation["calls"]
    if start != used:
        raise ValueError("invalid ledger invocations")


class UnverifiableRun(ValueError):
    """Corrupt or unverifiable run state (owner decision 2, 2026-11-04): the run
    stops and is final. `marked` when an earlier invocation already marked it."""

    def __init__(self, reason: str, *, marked: bool = False) -> None:
        super().__init__(reason)
        self.reason, self.marked = reason, marked


def _read_evidence(path: Path) -> list[dict]:
    if not path.is_file() or path.is_symlink():
        raise UnverifiableRun("the run evidence is missing")
    try:
        text = path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in text.splitlines()]
    except (OSError, ValueError):
        raise UnverifiableRun("the run evidence is unreadable") from None
    if not text.endswith("\n") or any(
        not isinstance(e, dict) or not isinstance(e.get("event"), str) for e in events
    ):
        raise UnverifiableRun("the run evidence is unreadable")
    return events


def _run_files(run_dir: Path) -> tuple[set[str], dict[tuple[str, int], Path]]:
    """The run directory's top-level file names and its checkpoint files. Anything
    else (a symlink, a stray file or directory) is unverifiable."""
    names, checkpoints = set(), {}
    for path in run_dir.iterdir():
        if path.is_symlink():
            raise UnverifiableRun("an unexpected file in the run directory")
        if path.is_dir() and path.name == "checkpoints":
            continue
        if not path.is_file():
            raise UnverifiableRun("an unexpected file in the run directory")
        names.add(path.name)
    base = run_dir / "checkpoints"
    if not base.is_dir():
        return names, checkpoints
    for folder in base.iterdir():
        if folder.is_symlink() or not folder.is_dir() or folder.name not in CONFIGS:
            raise UnverifiableRun("an unexpected file in the run directory")
        for path in folder.iterdir():
            if (
                path.is_symlink()
                or not path.is_file()
                or not _CHECKPOINT_NAME.fullmatch(path.name)
                or not 1 <= int(path.name[:3]) <= INITIAL
            ):
                raise UnverifiableRun("an unexpected file in the run directory")
            checkpoints[(folder.name, int(path.name[:3]) - 1)] = path
    return names, checkpoints


def _check_lifecycle(ledger: dict, events: list[dict]) -> None:
    """Each invocation's start, and its stop, are in the evidence in order; the
    latest stop matches the ledger (a resume needs the stop's record)."""
    life = [e for e in events if e["event"] in ("initial", "resume", "stop")]
    invocations, position, last_stop = ledger["invocations"], 0, None
    for number, invocation in enumerate(invocations, 1):
        start = life[position] if position < len(life) else {}
        if (
            start.get("event") != invocation["kind"]
            or start.get("invocation") != number
            or start.get("token_max_calls") != invocation["token_max_calls"]
            or start.get("calls_used") != invocation["calls_at_start"]
        ):
            raise UnverifiableRun("the ledger and the run evidence disagree")
        position += 1
        stop = life[position] if position < len(life) else {}
        last_stop = None
        if stop.get("event") == "stop":
            if (
                stop.get("invocation") != number
                or stop.get("reason") != invocation["stop_reason"]
            ):
                raise UnverifiableRun("the ledger and the run evidence disagree")
            position, last_stop = position + 1, stop
        elif number != len(invocations):
            raise UnverifiableRun("the stop is not recorded in the run evidence")
    if position != len(life):
        raise UnverifiableRun("the ledger and the run evidence disagree")
    if ledger["status"] in ("complete", "released"):
        return
    if last_stop is None:
        raise UnverifiableRun("the stop is not recorded in the run evidence")
    recorded = (last_stop.get("status"), last_stop.get("calls_used"))
    if (
        recorded != (ledger["status"], ledger["calls_used"])
        or last_stop.get("reason") != ledger["stop_reason"]
    ):
        raise UnverifiableRun("the ledger and the run evidence disagree")


def _check_attempts(ledger: dict, events: list[dict]) -> tuple[str, int] | None:
    """Every counted attempt is in the evidence, numbered call by call, and the
    ledger holds no fewer attempts than the evidence proves. Only the request in
    flight may be counted in the ledger with its evidence line not yet written;
    that item is returned."""
    seen: dict[tuple[str, int], int] = {}
    per_invocation: Counter = Counter()
    attempts = [e for e in events if e["event"] == "attempt"]
    for call, event in enumerate(attempts, 1):
        key = (event.get("config"), event.get("case"))
        if (
            event.get("call") != call
            or key[0] not in CONFIGS
            or type(key[1]) is not int
            or not 0 <= key[1] < INITIAL
            or event.get("attempt") != seen.get(key, 0) + 1
        ):
            raise UnverifiableRun("the run evidence is inconsistent")
        seen[key] = event["attempt"]
        per_invocation[event.get("invocation")] += 1
    gap = None
    for config in CONFIGS:
        for index, item in enumerate(ledger["items"][config]):
            recorded = seen.get((config, index), 0)
            if item["attempts"] < recorded:
                raise UnverifiableRun("the ledger's totals are below the run evidence")
            if item["attempts"] > recorded:
                if item["attempts"] != recorded + 1 or item["state"] != "in_flight":
                    raise UnverifiableRun("an attempt is missing from the run evidence")
                gap = (config, index)
    invocations = ledger["invocations"]
    for number, invocation in enumerate(invocations, 1):
        unrecorded = 1 if gap and number == len(invocations) else 0
        if per_invocation.pop(number, 0) + unrecorded != invocation["calls"]:
            raise UnverifiableRun("the ledger and the run evidence disagree")
    if per_invocation:
        raise UnverifiableRun("the ledger's totals are below the run evidence")
    return gap


def _check_checkpoints(
    ledger: dict, events: list[dict], checkpoints: dict[tuple[str, int], Path]
) -> None:
    """A checkpoint exists exactly for each completed request (and possibly the one
    in flight), and its response bytes hash to the evidence line written before it."""
    responses: dict[tuple[str, int, int], str] = {}
    attempted = {
        (e.get("config"), e.get("case"), e.get("attempt"))
        for e in events
        if e["event"] == "attempt"
    }
    for event in events:
        if event["event"] != "response":
            continue
        key = (event.get("config"), event.get("case"), event.get("attempt"))
        if key not in attempted or key in responses:
            raise UnverifiableRun("the run evidence is inconsistent")
        responses[key] = event.get("raw_sha256")
    for config in CONFIGS:
        for index, item in enumerate(ledger["items"][config]):
            path = checkpoints.get((config, index))
            if path is None:
                if item["state"] == "done":
                    raise UnverifiableRun("a completed request has no checkpoint")
                continue
            if item["state"] not in ("done", "in_flight"):
                raise UnverifiableRun("a checkpoint for a request not completed")
            digest = responses.get((config, index, item["attempts"]))
            if digest is None:
                raise UnverifiableRun("a checkpoint is not in the run evidence")
            try:
                raw = io.read_checkpoint(path)[2]
            except Exception:  # noqa: BLE001 - any unreadable checkpoint
                raise UnverifiableRun("a checkpoint does not verify") from None
            if v3.sha256(raw) != digest:
                raise UnverifiableRun("a checkpoint does not verify")


def settle(ledger: dict, checkpoints, gap) -> dict | None:
    """The request left in flight by an interrupted invocation, settled: complete
    when its checkpoint verified (never resent), otherwise a counted attempt that
    may be retried within the frozen limits. Mutates the ledger in memory only."""
    for config in CONFIGS:
        for index, item in enumerate(ledger["items"][config]):
            if item["state"] != "in_flight":
                continue
            if (config, index) in checkpoints:
                item["state"] = "done"
            else:
                item["state"] = "retry" if item["attempts"] < MAX_ATTEMPTS else "failed"
            return {
                "config": config,
                "case": index,
                "attempt": item["attempts"],
                "state": item["state"],
                "attempt_recorded": gap != (config, index),
                "invocation": len(ledger["invocations"]),
                "call": ledger["calls_used"],
            }
    return None


def load_run(run_dir: Path, seal_sha256: str) -> tuple[dict | None, dict | None]:
    """The validated ledger of this sealed run (None before it starts) and the
    settlement of a request left in flight. Raises UnverifiableRun for corrupt or
    unverifiable state: run files without a ledger (a ledger is never recreated over
    existing state), an unreadable or inconsistent ledger or evidence, a ledger
    holding fewer calls than the evidence proves, an unrecorded stop, a checkpoint
    that is missing, unexpected or does not hash to its evidence line, or results
    before both configurations are complete. Reads private run files only."""
    if (run_dir / FINAL_MARKER).exists() or (run_dir / FINAL_MARKER).is_symlink():
        raise UnverifiableRun("the run was marked final", marked=True)
    ledger_path = run_dir / "ledger.json"
    if run_dir.is_symlink() or (run_dir.exists() and not run_dir.is_dir()):
        raise UnverifiableRun("an unexpected file in the run directory")
    if not ledger_path.exists() and not ledger_path.is_symlink():
        if run_dir.is_dir():
            names, checkpoints = _run_files(run_dir)
            if names or checkpoints:
                raise UnverifiableRun("run state exists without a ledger")
        return None, None
    names, checkpoints = _run_files(run_dir)
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UnverifiableRun("the ledger is unreadable") from None
    if not isinstance(ledger, dict):
        raise UnverifiableRun("the ledger is unreadable")
    try:
        check_ledger(ledger, seal_sha256)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "invalid ledger counts"
        raise UnverifiableRun(reason) from None
    allowed = {"ledger.json", "evidence.jsonl"}
    if ledger["status"] in ("complete", "released"):
        allowed |= RELEASE_FILES
    elif names & RELEASE_FILES:
        raise UnverifiableRun("results exist before both configurations are complete")
    if names - allowed:
        raise UnverifiableRun("an unexpected file in the run directory")
    events = _read_evidence(run_dir / "evidence.jsonl")
    gap = _check_attempts(ledger, events)
    _check_lifecycle(ledger, events)
    _check_checkpoints(ledger, events, checkpoints)
    return ledger, settle(ledger, checkpoints, gap)


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
    the injected callables; the gate itself is pure bookkeeping.

    Evidence order per request: the ledger is saved with the attempt counted, then an
    `attempt` line, then the request; on a response, a `response` line with the
    SHA-256 of its bytes, then the checkpoint, then the ledger marks it done. A
    checkpoint therefore never exists without its evidence line."""

    def __init__(self, ledger, save, write_checkpoint, record, out):
        self.ledger, self.save, self.write_checkpoint = ledger, save, write_checkpoint
        self.record, self.out = record, out

    def _invocation(self) -> dict:
        return self.ledger["invocations"][-1]

    def begin(self, kind: str, token_max_calls: int, settled=None) -> None:
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
        record_settled(self.record, settled)
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
        """Persist an invocation that ended by an interrupt or a local error,
        wherever it arrived (a request, a back-off sleep, the token spend, a write):
        every counted attempt stays counted, and with no calls left the run is
        exhausted. Best effort; the original exception is re-raised."""
        try:
            if calls_left(self.ledger) <= 0:
                self.stop("exhausted", "budget_exhausted", "interrupted")
            else:
                self.stop("stopped", "interrupted")
        except Exception:  # noqa: BLE001 - never mask the interrupt itself
            pass

    def execute(self, token, send, sleep=None) -> str:
        """Spend calls until both configurations are complete or the run stops. Any
        exception that escapes, an interrupt included, goes through `interrupted`."""
        try:
            return self._execute(token, send, sleep or time.sleep)
        except BaseException:
            if self.ledger["status"] == "running":
                self.interrupted()
            raise

    def _execute(self, token, send, sleep) -> str:
        ledger = self.ledger
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
            attempt = {"config": config, "case": index, "attempt": item["attempts"]}
            self.record(
                {
                    "event": "attempt",
                    "invocation": self._invocation()["number"],
                    "call": ledger["calls_used"],
                    **attempt,
                }
            )
            try:
                raw = send(config, index)
            except io.AttemptError as error:
                errors = ledger["errors_by_class"][config]
                errors[error.category] = errors.get(error.category, 0) + 1
                item["state"] = "retry" if item["attempts"] < MAX_ATTEMPTS else "failed"
                self.record(
                    {"event": "error", **attempt, "error_class": error.category}
                )
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
            self.record({"event": "response", **attempt, "raw_sha256": v3.sha256(raw)})
            self.write_checkpoint(config, index, raw)
            item["state"] = "done"
            self.save(ledger)
            self.out(progress(ledger))


def record_settled(record, settled: dict | None) -> None:
    """Record the settlement of a request left in flight; when its attempt line was
    never written (interrupted between the ledger save and that line), write it now,
    so the evidence keeps proving every counted call."""
    if settled is None:
        return
    keys = ("config", "case", "attempt")
    if not settled["attempt_recorded"]:
        record(
            {
                "event": "attempt",
                "invocation": settled["invocation"],
                "call": settled["call"],
                **{k: settled[k] for k in keys},
                "recorded_late": True,
            }
        )
    record({"event": "settled", **{k: settled[k] for k in (*keys, "state")}})


def _without(payload: dict, excluded: frozenset[str]) -> dict:
    return {
        **payload,
        "labels": [row for row in payload["labels"] if row.get("id") not in excluded],
    }


def score_both(sample, gold, mapped, excluded) -> tuple[dict, dict]:
    """(primary, diagnostic) `score_v2` counts from the same mapped outputs and the
    same revised gold: the primary on the held-out cases not excluded (owner
    decision 1), the diagnostic on all 150."""
    cases = [case for case in sample["cases"] if case["id"] not in excluded]
    if sum(case["split"] == "test" for case in cases) != INITIAL - len(excluded):
        raise ValueError("invalid primary population")
    primary = score_v2(
        {**sample, "cases": cases},
        _without(gold, excluded),
        _without(mapped, excluded),
        "test",
    )
    return primary, score_v2(sample, gold, mapped, "test")


def score_and_release(ctx: dict, run_dir: Path, ledger: dict) -> dict:
    """Machine-only parsing, mapping and scoring after both configurations are
    complete; the private result is written and the aggregate release returned.
    The verdict uses the primary score (the excluded case left out); the full-150
    score from the same outputs is reported beside it as a diagnostic."""
    sample, subtypes, gold = ctx["sample"], ctx["subtypes"], ctx["gold"]
    excluded = ctx["excluded"]
    ids = [case_id for case_id, _ in ctx["cases"]]
    primary_ids = [case_id for case_id in ids if case_id not in excluded]
    scores, full, report = {}, {}, {}
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
        scores[config], full[config] = score_both(sample, gold, mapped, excluded)
        report[config] = {
            "metrics": v3.counts_json(scores[config]),
            "diagnostic_metrics": v3.counts_json(full[config]),
            "removed_by_polarity": removed,
            "remarks_with_misses": misses,
            "no_tool_calls": no_calls,
            "attempts": sum(x["attempts"] for x in ledger["items"][config]),
            "errors_by_class": ledger["errors_by_class"][config],
            "usage": usage.report(INITIAL),
        }
        if config == "v3":
            report[config]["span_quality"] = v3.span_quality(spans, gold, primary_ids)
            report[config]["diagnostic_span_quality"] = v3.span_quality(
                spans, gold, ids
            )
    reference = io.read_private(ctx["private"], V1_REFERENCE)
    mapped, _, removed = v3.map_payload(reference, sample, subtypes, "test")
    v1, v1_full = score_both(sample, gold, mapped, excluded)
    diagnostic = v3.phase_d_verdict(full["v3"], full["v2"])
    diagnostic.pop("pass")  # the diagnostic never decides the pass
    result = {
        "verdict": v3.phase_d_verdict(scores["v3"], scores["v2"]),
        "population": {
            "requested_per_configuration": INITIAL,
            "primary_n": INITIAL - len(excluded),
            "diagnostic_n": INITIAL,
            "excluded": len(excluded),
            "exclusions_sha256": ctx["exclusions_sha256"],
        },
        "diagnostic_full_150": {"note": DIAGNOSTIC_NOTE, **diagnostic},
        "configurations": report,
        "v1_reference": {
            "note": "historical reference only; sets no bar",
            "metrics": v3.counts_json(v1),
            "diagnostic_metrics": v3.counts_json(v1_full),
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
    """What the next invocation may do, for the dry run and refusals, from a
    validated (and settled) ledger. A run with no calls left is exhausted whatever
    its last stop; a ledger still `running` has no recorded stop and is not
    resumable."""
    if ledger is None:
        return {
            "status": "not_started",
            "calls_used": 0,
            "calls_left": BUDGET,
            "max_token_calls": BUDGET,
        }
    status, reason = ledger["status"], ledger["stop_reason"]
    every = [x for c in CONFIGS for x in ledger["items"][c]]
    if status == "released":
        pass
    elif any(x["state"] == "failed" for x in every):
        status, reason = "failed", "retry_limit"
    elif all(x["state"] == "done" for x in every):
        status = "complete"
    elif calls_left(ledger) <= 0:
        status, reason = "exhausted", "budget_exhausted"
    elif status == "running":
        status, reason = "stopped", "stop_not_recorded"
    resumable = status == "stopped" == ledger["status"] and reason in RESUMABLE
    return {
        "status": status,
        "stop_reason": reason,
        **progress(ledger),
        "resumable": resumable,
        "max_token_calls": calls_left(ledger) if resumable else 0,
    }


def unverifiable_state(error: UnverifiableRun) -> dict:
    return {
        "status": "unverifiable",
        "stop_reason": error.reason,
        "resumable": False,
        "max_token_calls": 0,
    }


def mark_final(run_dir: Path, error: UnverifiableRun) -> None:
    """Mark a run whose state does not verify as final, once (exclusive create);
    the reason only, never a record, a response or token content."""
    if error.marked:
        return
    try:
        marker = {"status": "unverifiable", "reason": error.reason}
        io.write_new(run_dir / FINAL_MARKER, marker)
    except FileExistsError:
        pass


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
    evidence = run_dir / "evidence.jsonl"
    expected_command = COMMAND.format(seal=args.seal_sha256)
    token = None
    fresh = False

    def save(value):
        nonlocal fresh
        if fresh:  # the first ledger never replaces an existing file
            io.write_new(ledger_path, value)
            fresh = False
        else:
            io.atomic_write(ledger_path, value)

    def record(entry):
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    try:
        ctx = verify_seal(ROOT, private, args.seal_sha256)
        words = current_command().split()
        if args.dry_run:
            words = [w for w in words if w != "--dry-run"]
        if " ".join(words) != expected_command:
            raise v3.ContractError("the command differs from the sealed command")
        unverifiable = None
        try:
            ledger, settled = load_run(run_dir, args.seal_sha256)
            state = ledger_state(ledger)
        except UnverifiableRun as exc:
            ledger, settled, unverifiable = None, None, exc
            state = unverifiable_state(exc)
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
        if unverifiable is not None:
            mark_final(run_dir, unverifiable)
            raise ValueError(f"the run is final (unverifiable: {unverifiable.reason})")
        if state["status"] in FINAL:
            raise ValueError(f"the run is final ({state['status']})")
        if state["status"] == "complete":
            return _release(ctx, run_dir, ledger, save, record, settled)
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

        def write_checkpoint(config, index, raw):
            _, usage = io.decode(raw)
            io.write_checkpoint(_checkpoint(run_dir, config, index), raw, usage)

        kind = "initial"
        if ledger is None:
            ledger, fresh = new_ledger(args.seal_sha256), True
        else:
            kind = "resume"
        run = Run(ledger, save, write_checkpoint, record, _emit)
        run.begin(kind, token.max_calls, settled)
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
        return _release(ctx, run_dir, ledger, save, record)
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


def _release(ctx, run_dir, ledger, save, record, settled=None) -> int:
    """Score and release a complete run. A completion found by settling the
    request left in flight is persisted and recorded first."""
    if settled is not None:
        save(ledger)
        record_settled(record, settled)
    result = score_and_release(ctx, run_dir, ledger)
    ledger["status"] = "released"
    save(ledger)
    record({"event": "release", **progress(ledger)})
    _emit({"release": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
