"""Assemble private policy-audit overlays from rule outcomes and reader decisions.

Outputs stay in the gitignored data directory; stored results are read-only. Earlier
files are archived and each row keeps its earlier decision as correction history.
"""

import argparse
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.policy_overlay import (
    build_decision,
    label_review,
    read_outcome,
    rule_outcome,
)
from idx_agent.enrichment.policy_rules import POLICY_FACETS, triage

ROOT = Path("data/enrichment")
WORK = ROOT / "policy-audit-work"
ARCHIVE = WORK / "archive"


def load_decisions(paths):
    """Map (sequence, facet, polarity/temporality) to one queued code per label."""
    decisions = defaultdict(list)
    for path in paths:
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            key = (int(parts[0].lstrip("#")), parts[1], parts[2])
            decisions[key].append((parts[3], parts[4] if len(parts) > 4 else ""))
    return decisions


def apply_overrides(decisions, path):
    """Replace a reader's code with the adjudicated one, requiring an exact match."""
    if not path.exists():
        return 0
    applied = 0
    for line in path.read_text().splitlines():
        sequence, facet, stored, old, new, *reason = line.split("\t")
        queue = decisions[(int(sequence), facet, stored)]
        for index, (code, note) in enumerate(queue):
            if code == old:
                queue[index] = (new, reason[0] if reason else note)
                applied += 1
                break
        else:
            raise ValueError(f"override has no matching decision: {line}")
    return applied


def dedupe_additions(decision, stored):
    """Drop any add whose annotation is already present after removals."""
    present = list(stored)
    for change in decision["changes"]:
        if change["operation"] == "remove":
            present.remove(change["original"])
    changes = []
    for change in decision["changes"]:
        annotation = change["corrected_annotation"]
        if change["operation"] == "add":
            if annotation in present:
                continue
            present.append(annotation)
        changes.append(change)
    decision["changes"] = changes
    if decision["status"] == "corrected" and not changes:
        decision["status"] = "accepted_unchanged"
        decision["reason"] = "All labels supported after re-reading."
    return decision


def replace_decisions(decisions, paths):
    """Let a later full re-read of a label replace every earlier code for it."""
    replacement = load_decisions(paths)
    for key, codes in replacement.items():
        decisions[key] = list(codes)
    return len(replacement)


def write_private(path, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with os.fdopen(
        os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
    ) as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def archive(path, label):
    ARCHIVE.mkdir(mode=0o700, exist_ok=True)
    target = ARCHIVE / f"{path.name}.{label}"
    if path.exists() and not target.exists():
        shutil.copy2(path, target)


def earlier_state(name):
    """Read the pre-rebuild overlay, so that rebuilding is idempotent."""
    archived = ARCHIVE / f"{name}.before-policy-v3"
    path = archived if archived.exists() else ROOT / name
    return [json.loads(line) for line in path.read_text().splitlines()]


def build_dataset(db, decisions, read_only_rules):
    """Return (cases, dispositions), failing if any label is left undecided."""
    prior = {
        row["sequence"]: row
        for row in earlier_state("policy-audit-dispositions.jsonl")
        if row["reason"] != "Not yet individually reviewed."
    }
    cases, rows, missing = [], [], []
    for case in candidates(db):
        outcomes = []
        for label in case["stored_facets"]:
            if label["value"] not in POLICY_FACETS:
                continue
            key = (
                case["sequence"],
                label["value"],
                f"{label['polarity']}/{label['temporality']}",
            )
            if decisions.get(key):
                code, note = decisions[key].pop(0)
                outcomes.append(read_outcome(label, code, note))
                continue
            triaged = triage(case["remark"], label)
            if triaged.outcome == "read" or triaged.rule in read_only_rules:
                missing.append(key)
                continue
            outcomes.append(rule_outcome(label, triaged))
        history = None
        if case["sequence"] in prior:
            earlier = prior[case["sequence"]]
            history = {
                "pass": "codex-two-label-audit",
                "status": earlier["status"],
                "reason": earlier["reason"],
                "changes": earlier["changes"],
            }
        cases.append(case)
        rows.append(build_decision(case, outcomes, history=history))
    if missing:
        raise ValueError(f"undecided labels: {len(missing)}, for example {missing[:3]}")
    leftover = sum(len(codes) for codes in decisions.values())
    if leftover:
        raise ValueError(f"decisions with no matching label: {leftover}")
    return cases, rows


def build_diagnostic(decisions):
    """Rebuild the 471-case overlay from per-label readings of every label."""
    cases = [
        json.loads(line)
        for line in (ROOT / "diagnostic-review-packet.jsonl").read_text().splitlines()
    ]
    earlier = earlier_state("diagnostic-review-dispositions.jsonl")
    rows = []
    for case, old in zip(cases, earlier, strict=True):
        adds = [c for c in old["changes"] if c["operation"] == "add"]
        outcomes, base = [], []
        for label in case["stored_facets"]:
            key = (
                case["sequence"],
                label["value"],
                f"{label['polarity']}/{label['temporality']}",
            )
            code, note = decisions[key].pop(0)
            outcomes.append(read_outcome(label, code, note))
        added_outcomes = []
        for change in adds:
            label = change["corrected_annotation"]
            key = (
                case["sequence"],
                label["value"],
                f"{label['polarity']}/{label['temporality']}",
            )
            code, note = decisions[key].pop(0)
            outcome = read_outcome(label, code, note)
            added_outcomes.append(outcome)
            if outcome.action == "keep":
                base.append(change)
            elif outcome.action == "retag":
                polarity, temporality = outcome.target
                annotation = dict(label, polarity=polarity, temporality=temporality)
                base.append(
                    dict(change, corrected_annotation=annotation, reason=outcome.reason)
                )
            elif outcome.action == "unresolved":
                outcomes.append(outcome)
        decision = build_decision(
            case,
            outcomes,
            base_changes=base,
            history={
                "pass": "diagnostic-review-before-policy-v3",
                "status": old["status"],
                "reason": old["reason"],
                "changes": old["changes"],
            },
        )
        # Labels the earlier overlay added are reviewed too. Every label in these
        # cases was read; a case with no labels has nothing left to attest.
        decision["label_reviews"] += [
            dict(label_review(o, case["remark"]), origin="earlier_addition")
            for o in added_outcomes
        ]
        decision["review_mode"] = "individually_reviewed"
        decision["semantic_reviewed"] = True
        rows.append(dedupe_additions(decision, case["stored_facets"]))
    leftover = sum(len(codes) for codes in decisions.values())
    if leftover:
        raise ValueError(f"diagnostic decisions with no matching label: {leftover}")
    return cases, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only-rules", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    read_only = set(json.loads(args.read_only_rules.read_text()))
    dataset = load_decisions(sorted(WORK.glob("final-decisions-*.tsv")))
    diagnostic = load_decisions(sorted(WORK.glob("final-diag-decisions-*.tsv")))
    overrides = apply_overrides(dataset, WORK / "final-overrides.tsv")
    overrides += apply_overrides(diagnostic, WORK / "final-diag-overrides.tsv")
    replaced = replace_decisions(dataset, sorted(WORK.glob("v4-decisions-*.tsv")))
    replaced += replace_decisions(diagnostic, [WORK / "v4-diag-decisions.tsv"])
    overrides += apply_overrides(dataset, WORK / "v4-overrides.tsv")
    overrides += apply_overrides(diagnostic, WORK / "v4-diag-overrides.tsv")
    # Reasoned resolutions of labels whose adjudicators had no majority.
    overrides += apply_overrides(dataset, WORK / "closeout-resolutions.tsv")
    print(json.dumps({"adjudicated_overrides": overrides, "v4_reread_keys": replaced}))
    store = ROOT / "full" / "active-facets-v2.sqlite3"
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        cases, rows = build_dataset(db, dataset, read_only)
    diag_cases, diag_rows = build_diagnostic(diagnostic)
    counts = {
        "dataset": dict(Counter(row["status"] for row in rows)),
        "dataset_review_mode": dict(Counter(row["review_mode"] for row in rows)),
        "diagnostic": dict(Counter(row["status"] for row in diag_rows)),
    }
    print(json.dumps(counts))
    if args.dry_run:
        return
    for name in (
        "policy-audit-packet.jsonl",
        "policy-audit-dispositions.jsonl",
        "diagnostic-review-dispositions.jsonl",
    ):
        archive(ROOT / name, "before-policy-v3")
    write_private(ROOT / "policy-audit-packet.jsonl", cases)
    write_private(ROOT / "policy-audit-dispositions.jsonl", rows)
    write_private(ROOT / "diagnostic-review-dispositions.jsonl", diag_rows)


if __name__ == "__main__":
    main()
