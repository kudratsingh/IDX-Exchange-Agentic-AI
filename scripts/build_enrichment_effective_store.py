"""Build the private effective-facet store from frozen results and the overlays.

Refuses unless the frozen artifacts match the manifest and the results table is exactly
what the audit certified. Writes only the gitignored data directory; prints counts only.
"""

# `--policy v4` (the default) is the v4 build, pinned by the policy-audit freeze
# manifest, which nothing here ever changes. `--policy v5` (WO-035) also applies review
# policy v5's ruling 8 correction overlay on top of the v4 overlays. It is pinned by a
# separate v5 manifest, which the owner freezes and which pins the v4 manifest too. A v5
# build never writes over the v4 store, so switching back means pointing
# IDX_ENRICHMENT_STORE at the v4 file. `--dry-run` verifies and counts, writing nothing.

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment import store_v5
from idx_agent.enrichment.effective import effective_labels, facet_statuses
from idx_agent.enrichment.effective_store import open_store, write_store
from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION
from idx_agent.enrichment.source_check import (
    EXPECTED_RESULTS_DIGEST,
    EXPECTED_WATERMARK,
    trusted_source_rows,
    verify_source,
)

ROOT = Path("data/enrichment")
STORE = ROOT / "full" / "active-facets-v2.sqlite3"
OUTPUT = ROOT / "full" / "effective-facets-v1.sqlite3"
OUTPUT_V5 = ROOT / "full" / "effective-facets-v5.sqlite3"
MANIFEST = ROOT / "policy-audit-freeze-manifest.json"
# Where the owner freezes a proposed v5 manifest (propose_enrichment_v5_manifest.py).
MANIFEST_V5 = ROOT / "effective-store-v5-manifest.json"
ARTIFACTS = {
    "packet": ROOT / "diagnostic-review-packet.jsonl",
    "overlay": ROOT / "diagnostic-review-dispositions.jsonl",
    "policy": Path("docs/ENRICHMENT_REVIEW_POLICY.md"),
    "dataset_packet": ROOT / "policy-audit-packet.jsonl",
    "dataset_overlay": ROOT / "policy-audit-dispositions.jsonl",
    "dataset_scope": ROOT / "policy-audit-scope.json",
    "dataset_rules": Path("src/idx_agent/enrichment/policy_rules.py"),
}
V5_ARTIFACTS = {
    **ARTIFACTS,
    "v4_manifest": MANIFEST,
    "policy_v5": Path("docs/ENRICHMENT_REVIEW_POLICY_V5.md"),
    "cleanup_overlay": ROOT / "v5-uncertain-cleanup-overlay.jsonl",
    "cleanup_manifest": ROOT / "v5-uncertain-cleanup-manifest.json",
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


def paths(root: Path = ROOT) -> dict:
    """Every private path rebased on `root`; tracked files stay in the checkout."""

    def rebase(path: Path) -> Path:
        return root / path.relative_to(ROOT) if path.is_relative_to(ROOT) else path

    return {
        "store": rebase(STORE),
        "output": rebase(OUTPUT),
        "output_v5": rebase(OUTPUT_V5),
        "manifest": rebase(MANIFEST),
        "manifest_v5": rebase(MANIFEST_V5),
        "artifacts": {k: rebase(v) for k, v in ARTIFACTS.items()},
        "v5_artifacts": {k: rebase(v) for k, v in V5_ARTIFACTS.items()},
    }


def v4_labels(artifacts: dict, store: Path, check=verify_source):
    """The verified v4 effective labels: (labelled rows, source rows, watermark, scope).

    `check` is the source check (`verify_source` with the frozen constants).
    """
    diagnostic_packet = load_jsonl(artifacts["packet"])
    diagnostic_overlay = load_jsonl(artifacts["overlay"])
    diagnostic = {}
    for case, decision in zip(diagnostic_packet, diagnostic_overlay, strict=True):
        if case["sequence"] != decision["sequence"]:
            raise ValueError("diagnostic packet and overlay are out of step")
        diagnostic[case["sequence"]] = decision
    dataset_decisions = load_jsonl(artifacts["dataset_overlay"])
    dataset = {d["sequence"]: d for d in dataset_decisions}
    scope = json.loads(artifacts["dataset_scope"].read_text())
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        # The results the overlays apply to must be exactly the audited ones.
        source_rows = check(
            db,
            diagnostic_packet,
            load_jsonl(artifacts["dataset_packet"]),
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
    labelled = list(effective_labels(results, diagnostic, dataset))
    return labelled, source_rows, watermark, scope


def _check_count(rows: list, source_rows: int, results_digest: str) -> None:
    """The store must cover exactly the count trusted for the approved digest."""
    if len(rows) != source_rows:
        raise ValueError("effective rows differ from the validated source")
    if source_rows != trusted_source_rows(results_digest):
        raise ValueError("validated source count is not the trusted count")


def _check_output(output: Path, where: dict, v5_manifest: Path | None) -> None:
    """Neither the destination nor the atomic writer's temp file may replace input.

    Protect every frozen artifact, both manifests and the original results database,
    including a custom v5 manifest and aliases reached through symlinks.
    """
    inputs = {
        where["store"],
        where["manifest"],
        where["manifest_v5"],
        *where["artifacts"].values(),
        *where["v5_artifacts"].values(),
    }
    if v5_manifest is not None:
        inputs.add(v5_manifest)
    protected = {path.resolve() for path in inputs}
    destinations = (output, output.with_name(output.name + ".tmp"))
    if any(path.resolve() in protected for path in destinations):
        raise ValueError("build output would overwrite a frozen input")


def build(
    policy: str,
    output: Path | None,
    *,
    root: Path = ROOT,
    v5_manifest: Path | None = None,
    dry_run: bool = False,
    check=verify_source,
    results_digest: str = EXPECTED_RESULTS_DIGEST,
    source_watermark: str = EXPECTED_WATERMARK,
) -> dict:
    """Verify, build (unless `dry_run`) and return the aggregate counts.

    The keyword defaults are the frozen production values; tests pass synthetic ones.
    """
    where = paths(root)
    manifest = json.loads(where["manifest"].read_text())
    verify_manifest(manifest, where["artifacts"])
    if policy == "v5":
        v5_path = v5_manifest or where["manifest_v5"]
        if v5_path.resolve() == where["manifest"].resolve():
            raise ValueError("the v5 manifest must not be the v4 manifest")
        output = output or where["output_v5"]
        if output.resolve() == where["output"].resolve():
            raise ValueError("a v5 build never writes over the v4 store")
        raw = v5_path.read_bytes()
        pinned = store_v5.verify_v5_manifest(
            raw,
            where["v5_artifacts"],
            results_digest=results_digest,
            source_rows=trusted_source_rows(results_digest),
            source_watermark=source_watermark,
            rules_version=POLICY_RULES_VERSION,
        )
    elif policy == "v4":
        output = output or where["output"]
    else:
        raise ValueError("policy must be v4 or v5")
    _check_output(output, where, v5_path if policy == "v5" else None)
    labelled, source_rows, watermark, scope = v4_labels(
        where["artifacts"], where["store"], check
    )
    removed: Counter = Counter()
    if policy == "v4":
        rows = [(key, facet_statuses(labels)) for _, key, labels in labelled]
        meta_policy, built = (
            scope["policy_version"],
            json.dumps(manifest, sort_keys=True),
        )
    else:
        if scope["rules_version"] != pinned["rules_version"]:
            raise ValueError(
                "frozen scope's rules version differs from the v5 manifest"
            )
        if watermark != pinned["source_watermark"]:
            raise ValueError("source watermark differs from the v5 manifest")
        artifacts = where["v5_artifacts"]
        cleanup = store_v5.validate_cleanup(
            load_jsonl(artifacts["cleanup_overlay"]),
            json.loads(artifacts["cleanup_manifest"].read_text()),
            overlay_name=artifacts["cleanup_overlay"].name,
            overlay_sha256=pinned["artifacts"]["cleanup_overlay"],
            dataset_overlay_sha256=manifest["dataset_overlay"],
        )
        rows = list(store_v5.cleaned_rows(labelled, cleanup, removed))
        meta_policy = store_v5.POLICY_VERSION
        built = store_v5.built_from(
            where["manifest"].name, digest(where["manifest"]), v5_path.name, pinned
        )
    _check_count(rows, source_rows, results_digest)
    statuses = Counter(status for _, facets in rows for status in facets.values())
    summary = {
        "policy_version": meta_policy,
        "listings": len(rows),
        "statuses": dict(sorted(statuses.items())),
    }
    if policy == "v5":
        summary["policy_scope"] = store_v5.POLICY_SCOPE
        summary["removed_by_facet"] = dict(sorted(removed.items()))
    if dry_run:
        return dict(summary, written=False)
    meta = {
        "source_rows": source_rows,
        # verify_source matched the source to this frozen constant.
        "results_digest": results_digest,
        "source_watermark": watermark,
        "policy_version": meta_policy,
        "rules_version": scope["rules_version"],
        "built_from": built,
    }
    if policy == "v5":
        # Only ruling 8 is applied; rulings 1-7 and 9-15 are not applied to the stored
        # labels, and the store says so.
        meta["policy_scope"] = store_v5.POLICY_SCOPE
    written = write_store(output, rows, meta)
    opened = open_store(output)
    if not hasattr(opened, "keys_with_all"):
        raise ValueError(f"store failed validation: {opened.reason}")
    info = opened.info
    opened.close()
    with sqlite3.connect(f"{output.resolve().as_uri()}?mode=ro", uri=True) as db:
        stored = dict(db.execute("SELECT name, value FROM meta"))
    if info.policy_version != meta_policy or info.listing_count != written:
        raise ValueError("written store differs from the build")
    if policy == "v5":
        named = json.loads(stored["built_from"])["manifests"]
        frozen = {
            "v4": digest(where["manifest"]),
            "v5": hashlib.sha256(raw).hexdigest(),
        }
        if {k: v["sha256"] for k, v in named.items()} != frozen:
            raise ValueError("written store does not name the frozen manifests")
        if stored.get("policy_scope") != store_v5.POLICY_SCOPE:
            raise ValueError("written store does not state the v5 policy scope")
    return {"listings": written, "statuses": summary["statuses"]} | (
        {
            "policy_version": meta_policy,
            "policy_scope": summary["policy_scope"],
            "removed_by_facet": summary["removed_by_facet"],
        }
        if policy == "v5"
        else {}
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--policy", choices=("v4", "v5"), default="v4")
    parser.add_argument("--v5-manifest", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    summary = build(
        args.policy,
        args.output,
        root=args.data_root,
        v5_manifest=args.v5_manifest,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
