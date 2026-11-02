"""Write the private audit scope and freeze manifest for the WO-018 policy audit.

The scope record states exactly what was searched and what was not. The manifest
holds hashes only. Both stay in the private, gitignored data directory; the printed
summary is aggregate and contains no listing-level material.
"""

import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment.policy_audit import (
    screen_hardwood_engineered,
    screen_solar_heating_broad,
    screen_solar_heating_exact,
)
from idx_agent.enrichment.policy_overlay import POLICY_VERSION
from idx_agent.enrichment.policy_rules import POLICY_FACETS, POLICY_RULES_VERSION
from idx_agent.enrichment.v2 import V2_FACETS

ROOT = Path("data/enrichment")
WORK = ROOT / "policy-audit-work"
POLICY = Path("docs/ENRICHMENT_REVIEW_POLICY.md")
RULES = Path("src/idx_agent/enrichment/policy_rules.py")
SCREENS = {
    "owner_hardwood_159_reconstruction": ("hardwood", screen_hardwood_engineered),
    "owner_solar_27_reconstruction": ("solar", screen_solar_heating_exact),
    "owner_solar_27_broad_superset": ("solar", screen_solar_heating_broad),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile(cases, decisions):
    """Report every screened row's inventory membership and final label outcome."""
    report = {}
    by_sequence = {decision["sequence"]: decision for decision in decisions}
    for name, (value, screen) in SCREENS.items():
        actions = Counter()
        rows = 0
        for case in cases:
            if not screen(case["remark"], case["stored_facets"]):
                continue
            rows += 1
            reviews = by_sequence[case["sequence"]]["label_reviews"]
            for review in reviews:
                if review["value"] == value:
                    actions[f"{review['action']}:{review['method']}"] += 1
        report[name] = {"rows": rows, "label_outcomes": dict(actions)}
    return report


def summarize(decisions):
    labels = Counter()
    for decision in decisions:
        for review in decision["label_reviews"]:
            labels[(review["value"], review["method"], review["action"])] += 1
    per_facet = {}
    for (value, method, action), count in sorted(labels.items()):
        per_facet.setdefault(value, {})[f"{method}:{action}"] = count
    return per_facet


def main():
    packet = ROOT / "policy-audit-packet.jsonl"
    overlay = ROOT / "policy-audit-dispositions.jsonl"
    cases = [json.loads(line) for line in packet.read_text().splitlines()]
    decisions = [json.loads(line) for line in overlay.read_text().splitlines()]
    audit = json.loads((WORK / "rule-audit.json").read_text())
    store = ROOT / "full" / "active-facets-v2.sqlite3"
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        population = db.execute(
            "SELECT COUNT(*) FROM results WHERE diagnostic_count=0"
        ).fetchone()[0]
    all_facets = {value for values in V2_FACETS.values() for value in values}
    scope = {
        "population": population,
        "inventory_rows": len(cases),
        "candidate_discovery_complete": True,
        "candidate_definition": (
            "Every non-diagnostic row carrying at least one label in policy_facets."
        ),
        "policy_facets": list(POLICY_FACETS),
        "facets_not_audited_outside_diagnostics": sorted(
            all_facets - set(POLICY_FACETS)
        ),
        "limitations": [
            "Audits stored labels only: omitted features were not searched for.",
            "Rule-processed labels were sampled, not individually read.",
            "Reviews were performed by Claude agents, not humans.",
            "Owner screen reconstructions match reported counts, not proven row sets.",
        ],
        "policy_version": POLICY_VERSION,
        "rules_version": POLICY_RULES_VERSION,
        "rubric_sha256": digest(WORK / "RUBRIC.md"),
        "read_only_rules": json.loads((WORK / "read-only-rules.json").read_text()),
        "rule_audit": audit,
        "reader_audit": json.loads((WORK / "reader-audit.json").read_text()),
        "screen_reconciliation": reconcile(cases, decisions),
        "label_summary": summarize(decisions),
        "record_review_mode": dict(Counter(d["review_mode"] for d in decisions)),
    }
    scope_path = ROOT / "policy-audit-scope.json"
    with os.fdopen(
        os.open(scope_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
    ) as out:
        json.dump(scope, out, indent=1)
    manifest = {
        "packet": digest(ROOT / "diagnostic-review-packet.jsonl"),
        "overlay": digest(ROOT / "diagnostic-review-dispositions.jsonl"),
        "policy": digest(POLICY),
        "dataset_packet": digest(packet),
        "dataset_overlay": digest(overlay),
        "dataset_scope": digest(scope_path),
        "dataset_rules": digest(RULES),
    }
    manifest_path = ROOT / "policy-audit-freeze-manifest.json"
    with os.fdopen(
        os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
    ) as out:
        json.dump(manifest, out, indent=1)
    print(
        json.dumps(
            {
                k: scope[k]
                for k in (
                    "inventory_rows",
                    "screen_reconciliation",
                    "record_review_mode",
                )
            }
        )
    )
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
