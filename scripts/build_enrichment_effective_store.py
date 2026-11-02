"""Build the private effective-facet store from frozen results and both overlays.

Refuses unless the frozen artifacts match the manifest and the results table is exactly
what the audit certified. Writes only the gitignored data directory; prints counts only.
"""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment.effective import effective_rows
from idx_agent.enrichment.effective_store import open_store, write_store
from idx_agent.enrichment.source_check import EXPECTED_RESULTS_DIGEST, verify_source

ROOT = Path("data/enrichment")
STORE = ROOT / "full" / "active-facets-v2.sqlite3"
OUTPUT = ROOT / "full" / "effective-facets-v1.sqlite3"
MANIFEST = ROOT / "policy-audit-freeze-manifest.json"
ARTIFACTS = {
    "packet": ROOT / "diagnostic-review-packet.jsonl",
    "overlay": ROOT / "diagnostic-review-dispositions.jsonl",
    "policy": Path("docs/ENRICHMENT_REVIEW_POLICY.md"),
    "dataset_packet": ROOT / "policy-audit-packet.jsonl",
    "dataset_overlay": ROOT / "policy-audit-dispositions.jsonl",
    "dataset_scope": ROOT / "policy-audit-scope.json",
    "dataset_rules": Path("src/idx_agent/enrichment/policy_rules.py"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(manifest: dict, artifacts: dict) -> None:
    """Raise ValueError unless each frozen artifact matches its manifest hash."""
    if set(manifest) != set(artifacts):
        raise ValueError("freeze manifest names different artifacts")
    for name, path in artifacts.items():
        if digest(path) != manifest[name]:
            raise ValueError(f"frozen {name} no longer matches the manifest")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    verify_manifest(manifest, ARTIFACTS)
    diagnostic_packet = load_jsonl(ARTIFACTS["packet"])
    diagnostic_overlay = load_jsonl(ARTIFACTS["overlay"])
    diagnostic = {}
    for case, decision in zip(diagnostic_packet, diagnostic_overlay, strict=True):
        if case["sequence"] != decision["sequence"]:
            raise ValueError("diagnostic packet and overlay are out of step")
        diagnostic[case["sequence"]] = decision
    dataset_decisions = load_jsonl(ARTIFACTS["dataset_overlay"])
    dataset = {d["sequence"]: d for d in dataset_decisions}
    scope = json.loads(ARTIFACTS["dataset_scope"].read_text())
    with sqlite3.connect(f"file:{STORE}?mode=ro", uri=True) as db:
        # The results the overlays apply to must be exactly the audited ones.
        source_rows = verify_source(
            db,
            diagnostic_packet,
            load_jsonl(ARTIFACTS["dataset_packet"]),
            dataset_decisions,
            scope,
        )
        watermark = dict(db.execute("SELECT name, value FROM settings"))["watermark"]
        results = [
            (sequence, key, json.loads(facets))
            for sequence, key, facets in db.execute(
                "SELECT sequence, listing_key, facets FROM results ORDER BY sequence"
            )
        ]
    rows = list(effective_rows(results, diagnostic, dataset))
    if len(rows) != source_rows:
        raise ValueError("effective rows differ from the validated source")
    meta = {
        "source_rows": source_rows,
        # verify_source matched the source to this frozen constant.
        "results_digest": EXPECTED_RESULTS_DIGEST,
        "source_watermark": watermark,
        "policy_version": scope["policy_version"],
        "rules_version": scope["rules_version"],
        "built_from": json.dumps(manifest, sort_keys=True),
    }
    written = write_store(args.output, rows, meta)
    opened = open_store(args.output)
    if not hasattr(opened, "keys_with_all"):
        raise ValueError(f"store failed validation: {opened.reason}")
    opened.close()
    statuses = Counter(status for _, facets in rows for status in facets.values())
    print(json.dumps({"listings": written, "statuses": dict(sorted(statuses.items()))}))


if __name__ == "__main__":
    main()
