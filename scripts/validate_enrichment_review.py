"""Validate private review records without printing listing-level material."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.policy_rules import (
    POLICY_FACETS,
    POLICY_RULES_VERSION,
    triage,
)
from idx_agent.enrichment.source_check import validate_store
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
        "dataset_rules",
    }
    if set(manifest) != expected or set(artifacts) != expected:
        raise ValueError("invalid freeze manifest")
    for name, path in artifacts.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest[name] != actual:
            raise ValueError(f"frozen {name} hash mismatch")


MIN_RULE_AGREEMENT = 0.95
MIN_RULE_SAMPLE = 100
LABEL_METHODS = ("rule", "read", "prior_read")
RULE_ACTIONS = {"support": "keep", "omit": "remove", "retemporal": "retag"}
RULE_TARGETS = {"retemporal": ["uncertain", "unspecified"]}


def require_semantic_attestations(diagnostic_decisions, dataset_decisions, scope):
    """Require recorded review: every diagnostic label read; dataset rules audited.

    These records show how labels were decided, not that the decisions are right.
    """
    if any(d.get("semantic_reviewed") is not True for d in diagnostic_decisions):
        raise ValueError("semantic review attestations incomplete")
    if scope.get("candidate_discovery_complete") is not True:
        raise ValueError("dataset candidate discovery incomplete")
    if scope.get("population") != 54417:
        raise ValueError("dataset audit scope mismatch")
    if scope.get("rules_version") != POLICY_RULES_VERSION:
        raise ValueError("scope rules version mismatch")
    audit = scope.get("rule_audit", {})
    if audit.get("rules_version") != POLICY_RULES_VERSION:
        raise ValueError("rule audit version mismatch")
    for decision in dataset_decisions:
        for review in decision.get("label_reviews") or ():
            if review.get("method") not in LABEL_METHODS:
                raise ValueError("invalid label review method")
            if review["method"] == "rule":
                measured = audit.get("rules", {}).get(review.get("rule"), {})
                if measured.get("sampled", 0) < MIN_RULE_SAMPLE:
                    raise ValueError(f"rule not audited: {review.get('rule')}")
                if measured.get("agreement", 0) < MIN_RULE_AGREEMENT:
                    raise ValueError(f"rule below agreement: {review.get('rule')}")


def _key(label):
    return (label["value"], label["polarity"], label["temporality"])


def _expected_labels(reviews, unchanged=()):
    expected = list(unchanged)
    for review in reviews:
        label = {"value": review["value"], "polarity": review["polarity"]}
        label["temporality"] = review["temporality"]
        if review["action"] in ("keep", "unresolved"):
            expected.append(_key(label))
        elif review["action"] == "retag":
            polarity, temporality = review["target"]
            expected.append((review["value"], polarity, temporality))
        elif review["action"] != "remove":
            raise ValueError("invalid label review action")
    return expected


def require_reviews_match_changes(case, decision, reviews, unchanged=()):
    """Require the applied overlay to equal what the label reviews say."""
    if decision["status"] == "unresolved":
        if not any(r["action"] == "unresolved" for r in reviews):
            raise ValueError("unresolved status without an unresolved label")
        return
    if any(r["action"] == "unresolved" for r in reviews):
        raise ValueError("unresolved label in a resolved disposition")
    actual = Counter(
        _key(label) for label in apply_resolved(case["stored_facets"], decision)
    )
    expected = _expected_labels(reviews, unchanged)
    if set(actual) != set(expected):
        raise ValueError("label reviews do not match the applied changes")
    ceiling = Counter(expected)
    if any(count > max(ceiling[key], 1) for key, count in actual.items()):
        raise ValueError("applied changes double a label")


def require_label_coverage(cases, decisions):
    """Require one review per in-scope dataset label, consistent with its changes."""
    for case, decision in zip(cases, decisions, strict=True):
        in_scope = [
            label for label in case["stored_facets"] if label["value"] in POLICY_FACETS
        ]
        reviews = decision.get("label_reviews") or ()
        actual = Counter((r["value"], r["polarity"], r["temporality"]) for r in reviews)
        if not in_scope or Counter(map(_key, in_scope)) != actual:
            raise ValueError("label review coverage mismatch")
        for review in reviews:
            if review["method"] != "rule":
                continue
            label = next(item for item in in_scope if _key(item) == _key(review))
            triaged = triage(case["remark"], label)
            if (
                review.get("rule_version") != POLICY_RULES_VERSION
                or not review.get("evidence")
                or triaged.rule != review["rule"]
                or RULE_ACTIONS.get(triaged.outcome) != review["action"]
                or RULE_TARGETS.get(triaged.outcome) != review.get("target")
            ):
                raise ValueError("rule outcome is not reproducible")
        out_of_scope = [
            _key(label)
            for label in case["stored_facets"]
            if label["value"] not in POLICY_FACETS
        ]
        require_reviews_match_changes(case, decision, reviews, out_of_scope)


def require_diagnostic_coverage(cases, decisions):
    """Require every stored and earlier-added diagnostic label to have been read."""
    for case, decision in zip(cases, decisions, strict=True):
        earlier = (decision.get("correction_history") or [{}])[0].get("changes", [])
        labels = list(case["stored_facets"]) + [
            change["corrected_annotation"]
            for change in earlier
            if change["operation"] == "add"
        ]
        reviews = decision.get("label_reviews") or ()
        if Counter(map(_key, labels)) != Counter(map(_key, reviews)):
            raise ValueError("diagnostic review coverage mismatch")
        if any(review["method"] != "read" for review in reviews):
            raise ValueError("diagnostic label not read")
        require_reviews_match_changes(case, decision, reviews)


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
        require_label_coverage(dataset_cases, dataset_decisions)
        require_diagnostic_coverage(cases, decisions)
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
                "dataset_rules": Path("src/idx_agent/enrichment/policy_rules.py"),
            },
        )
    elif args.manifest is not None:
        raise ValueError("manifest requires --require-complete")
    print(json.dumps({"dispositions": dispositions, "coverage": coverage}))


if __name__ == "__main__":
    main()
