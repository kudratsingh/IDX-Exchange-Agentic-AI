"""Validate private review records without printing listing-level material."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.v2 import V2_FACETS


def require_complete(dispositions, dataset_dispositions, manifest, artifacts):
    """Reject unresolved reviews and changes to externally frozen artifacts.

    This is a structural gate; semantic correctness still requires review.
    """
    if dispositions.get("unresolved", 0):
        raise ValueError("unresolved diagnostic cases")
    if dataset_dispositions.get("unresolved", 0):
        raise ValueError("unresolved dataset audit cases")
    expected = {
        "packet",
        "overlay",
        "policy",
        "dataset_packet",
        "dataset_overlay",
        "dataset_scope",
    }
    if set(manifest) != expected or set(artifacts) != expected:
        raise ValueError("invalid freeze manifest")
    for name, path in artifacts.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest[name] != actual:
            raise ValueError(f"frozen {name} hash mismatch")


def require_semantic_attestations(diagnostic_decisions, dataset_decisions, scope):
    """Require recorded manual review; these attestations are not semantic proof."""
    if any(
        decision.get("semantic_reviewed") is not True
        for decision in (*diagnostic_decisions, *dataset_decisions)
    ):
        raise ValueError("semantic review attestations incomplete")
    if scope.get("candidate_discovery_complete") is not True:
        raise ValueError("dataset candidate discovery incomplete")
    if scope.get("population") != 54417:
        raise ValueError("dataset audit scope mismatch")


def validate_store(db, cases):
    """Validate the saved source, provenance and diagnostic coverage read-only."""
    source = db.execute(
        "SELECT i.sequence,i.listing_key,i.input_hash,i.remark,"
        "r.listing_key,r.input_hash,r.facets,r.diagnostic_count,o.extractor "
        "FROM inputs i LEFT JOIN results r USING(sequence) "
        "LEFT JOIN result_origins o USING(sequence) ORDER BY i.sequence"
    )
    diagnostics = {case["sequence"]: case for case in cases}
    origins = Counter()
    count = 0
    seen_keys = set()
    for seq, key, digest, remark, result_key, result_hash, facets, n, origin in source:
        count += 1
        if (
            seq != count
            or key in seen_keys
            or key != result_key
            or digest != result_hash
            or hashlib.sha256(remark.encode()).hexdigest() != digest
            or origin not in ("v1", "v2")
        ):
            raise ValueError("source, result or provenance mismatch")
        seen_keys.add(key)
        origins[origin] += 1
        case = diagnostics.pop(seq, None)
        if bool(n) != (case is not None):
            raise ValueError("diagnostic coverage mismatch")
        if case is not None and (
            case["listing_key"] != key
            or case["remark"] != remark
            or case["origin"] != origin
            or case["stored_facets"] != json.loads(facets)
        ):
            raise ValueError("review packet differs from stored result")
    if diagnostics:
        raise ValueError("extra diagnostic cases")
    if (
        db.execute("SELECT COUNT(*) FROM results").fetchone()[0] != count
        or db.execute("SELECT COUNT(*) FROM result_origins").fetchone()[0] != count
    ):
        raise ValueError("extra result or origin")
    return {"rows": count, "origins": dict(origins)}


def validate(cases, decisions):
    if (
        len(cases) != len(decisions)
        or len({c["sequence"] for c in cases}) != len(cases)
        or len({c["listing_key"] for c in cases}) != len(cases)
    ):
        raise ValueError("coverage or duplicate case")
    counts = Counter()
    for case, decision in zip(cases, decisions, strict=True):
        if any(case[k] != decision[k] for k in ("sequence", "listing_key", "origin")):
            raise ValueError("case identity mismatch")
        status = decision["status"]
        if (
            status not in ("corrected", "accepted_unchanged", "unresolved")
            or not decision["reason"]
        ):
            raise ValueError("invalid disposition")
        changes = decision["changes"]
        serialized = [json.dumps(change, sort_keys=True) for change in changes]
        if len(set(serialized)) != len(serialized):
            raise ValueError("duplicate change")
        remaining = list(case["stored_facets"])
        if (
            status == "corrected"
            and not changes
            or status == "accepted_unchanged"
            and changes
        ):
            raise ValueError("invalid disposition changes")
        for change in changes:
            operation = change["operation"]
            original = change["original"]
            annotation = change["corrected_annotation"]
            if (
                not change["evidence_quote"]
                or change["evidence_quote"] not in case["remark"]
                or not change["reason"]
            ):
                raise ValueError("invalid evidence")
            if operation == "remove":
                if original not in remaining or annotation is not None:
                    raise ValueError("invalid removal")
                remaining.remove(original)
            elif operation == "add":
                if original is not None or not isinstance(annotation, dict):
                    raise ValueError("invalid addition")
                if annotation.get("value") not in V2_FACETS.get(
                    annotation.get("group"), ()
                ):
                    raise ValueError("invalid facet")
                if annotation.get("polarity") not in (
                    "affirmed",
                    "negated",
                    "uncertain",
                ):
                    raise ValueError("invalid polarity")
                if annotation.get("temporality") not in (
                    "current",
                    "planned",
                    "historical",
                    "unspecified",
                ):
                    raise ValueError("invalid temporality")
            else:
                raise ValueError("invalid operation")
        counts[status] += 1
    return dict(counts)


def apply_resolved(stored, decision):
    """Combine a resolved overlay in memory; never apply unresolved changes."""
    result = list(stored)
    if decision["status"] == "unresolved":
        return result
    for change in decision["changes"]:
        if change["operation"] == "remove":
            result.remove(change["original"])
        else:
            result.append(change["corrected_annotation"])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    root = Path("data/enrichment")
    cases = [
        json.loads(line) for line in (root / "diagnostic-review-packet.jsonl").open()
    ]
    decisions = [
        json.loads(line)
        for line in (root / "diagnostic-review-dispositions.jsonl").open()
    ]
    if len(cases) != 471:
        raise ValueError("unexpected case count")
    dispositions = validate(cases, decisions)
    for case, decision in zip(cases, decisions, strict=True):
        apply_resolved(case["stored_facets"], decision)
    store = root / "full" / "active-facets-v2.sqlite3"
    with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
        coverage = validate_store(db, cases)
    if coverage["rows"] != 54888:
        raise ValueError("unexpected source count")
    if args.require_complete:
        if args.manifest is None:
            raise ValueError("freeze manifest required for completion")
        dataset_packet = root / "policy-audit-packet.jsonl"
        dataset_overlay = root / "policy-audit-dispositions.jsonl"
        dataset_scope = root / "policy-audit-scope.json"
        dataset_cases = [json.loads(line) for line in dataset_packet.open()]
        dataset_decisions = [json.loads(line) for line in dataset_overlay.open()]
        if not dataset_cases:
            raise ValueError("dataset audit packet is empty")
        require_semantic_attestations(
            decisions, dataset_decisions, json.loads(dataset_scope.read_text())
        )
        with sqlite3.connect(f"file:{store}?mode=ro", uri=True) as db:
            if (
                db.execute(
                    "SELECT COUNT(*) FROM results WHERE diagnostic_count=0"
                ).fetchone()[0]
                != 54417
            ):
                raise ValueError("dataset audit population mismatch")
            if dataset_cases != list(candidates(db)):
                raise ValueError("dataset audit screening coverage mismatch")
        require_complete(
            dispositions,
            validate(dataset_cases, dataset_decisions),
            json.loads(args.manifest.read_text()),
            {
                "packet": root / "diagnostic-review-packet.jsonl",
                "overlay": root / "diagnostic-review-dispositions.jsonl",
                "policy": Path("docs/ENRICHMENT_REVIEW_POLICY.md"),
                "dataset_packet": dataset_packet,
                "dataset_overlay": dataset_overlay,
                "dataset_scope": dataset_scope,
            },
        )
    elif args.manifest is not None:
        raise ValueError("manifest requires --require-complete")
    print(json.dumps({"dispositions": dispositions, "coverage": coverage}))


if __name__ == "__main__":
    main()
