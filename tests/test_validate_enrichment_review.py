"""Structural review checks use synthetic evidence only."""

import copy
import hashlib
import json
import sqlite3

import pytest
from scripts.validate_enrichment_review import (
    apply_resolved,
    require_complete,
    require_diagnostic_coverage,
    require_label_coverage,
    require_semantic_attestations,
    validate,
    validate_store,
)

from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION


@pytest.fixture
def review():
    case = dict(
        sequence=1,
        listing_key="1",
        origin="v2",
        remark="A private patio.",
        stored_facets=[],
    )
    change = dict(
        operation="add",
        original=None,
        corrected_annotation=dict(
            group="exterior_lot",
            value="patio",
            polarity="affirmed",
            temporality="current",
        ),
        evidence_quote="private patio",
        reason="Explicit patio",
    )
    decision = dict(
        sequence=1,
        listing_key="1",
        origin="v2",
        status="corrected",
        reason="Supported",
        changes=[change],
    )
    return case, decision


def test_supported_structure(review):
    case, decision = review
    assert validate([case], [decision]) == {"corrected": 1}


@pytest.mark.parametrize(
    "field,value",
    [("value", "not_a_facet"), ("polarity", "maybe"), ("temporality", "tomorrow")],
)
def test_bad_annotation_rejected(review, field, value):
    case, decision = copy.deepcopy(review)
    decision["changes"][0]["corrected_annotation"][field] = value
    with pytest.raises(ValueError):
        validate([case], [decision])


def test_wrong_evidence_rejected(review):
    case, decision = review
    decision["changes"][0]["evidence_quote"] = "invented"
    with pytest.raises(ValueError):
        validate([case], [decision])


def test_duplicate_change_rejected(review):
    case, decision = review
    decision["changes"].append(copy.deepcopy(decision["changes"][0]))
    with pytest.raises(ValueError, match="duplicate change"):
        validate([case], [decision])


def test_unresolved_partial_changes_are_not_applied(review):
    case, decision = review
    decision["status"] = "unresolved"
    assert apply_resolved(case["stored_facets"], decision) == []
    decision["status"] = "corrected"
    assert apply_resolved(case["stored_facets"], decision) == [
        decision["changes"][0]["corrected_annotation"]
    ]
    assert case["stored_facets"] == []


def test_repeated_removal_cannot_exceed_originals(review):
    case, decision = review
    facet = decision["changes"][0]["corrected_annotation"]
    case["stored_facets"] = [facet]
    removal = dict(
        operation="remove",
        original=facet,
        corrected_annotation=None,
        evidence_quote="private patio",
        reason="First removal",
    )
    second = dict(removal, reason="Second removal")
    decision["changes"] = [removal, second]
    with pytest.raises(ValueError, match="invalid removal"):
        validate([case], [decision])


def test_store_coverage_and_source_hash(review):
    case, _ = review
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE inputs(sequence, listing_key, input_hash, remark);
        CREATE TABLE results(
            sequence, listing_key, input_hash, facets, diagnostic_count
        );
        CREATE TABLE result_origins(sequence, extractor);
    """)
    digest = hashlib.sha256(case["remark"].encode()).hexdigest()
    db.execute("INSERT INTO inputs VALUES (?,?,?,?)", (1, "1", digest, case["remark"]))
    db.execute(
        "INSERT INTO results VALUES (?,?,?,?,?)", (1, "1", digest, json.dumps([]), 1)
    )
    db.execute("INSERT INTO result_origins VALUES (?,?)", (1, "v2"))
    assert validate_store(db, [case]) == {"rows": 1, "origins": {"v2": 1}}
    db.execute("UPDATE inputs SET remark = ?", ("altered",))
    with pytest.raises(ValueError, match="source, result or provenance mismatch"):
        validate_store(db, [case])


def test_completion_freeze_rejects_mutation_and_unresolved(tmp_path):
    names = (
        "packet",
        "overlay",
        "policy",
        "dataset_packet",
        "dataset_overlay",
        "dataset_scope",
        "dataset_rules",
    )
    artifacts = {name: tmp_path / name for name in names}
    for path in artifacts.values():
        path.write_text(path.name)
    manifest = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in artifacts.items()
    }
    require_complete({}, {}, manifest, artifacts)
    with pytest.raises(ValueError, match="unresolved diagnostic"):
        require_complete({"unresolved": 1}, {}, manifest, artifacts)
    with pytest.raises(ValueError, match="unresolved dataset"):
        require_complete({}, {"unresolved": 1}, manifest, artifacts)
    artifacts["policy"].write_text("changed")
    with pytest.raises(ValueError, match="policy hash mismatch"):
        require_complete({}, {}, manifest, artifacts)


SCOPE = {
    "candidate_discovery_complete": True,
    "population": 54417,
    "rules_version": POLICY_RULES_VERSION,
    "rule_audit": {
        "rules_version": POLICY_RULES_VERSION,
        "rules": {
            "pool.on_property": {"sampled": 200, "agreement": 0.98},
            "patio.explicit": {"sampled": 200, "agreement": 0.90},
            "pool.tiny_sample": {"sampled": 5, "agreement": 1.0},
        },
    },
}
READ = {"semantic_reviewed": True}


def rule_decision(rule, **extra):
    review = dict(
        value="pool",
        polarity="affirmed",
        temporality="current",
        method="rule",
        rule=rule,
        rule_version=POLICY_RULES_VERSION,
        evidence="backyard pool",
        action="keep",
        target=None,
    )
    return dict(
        status="accepted_unchanged", changes=[], label_reviews=[dict(review, **extra)]
    )


def test_completion_requires_read_diagnostics_and_complete_scope():
    require_semantic_attestations([READ], [READ], SCOPE)
    with pytest.raises(ValueError, match="semantic review"):
        require_semantic_attestations([{}], [READ], SCOPE)
    with pytest.raises(ValueError, match="discovery incomplete"):
        require_semantic_attestations(
            [READ], [READ], dict(SCOPE, candidate_discovery_complete=False)
        )
    with pytest.raises(ValueError, match="scope mismatch"):
        require_semantic_attestations([READ], [READ], dict(SCOPE, population=1))
    with pytest.raises(ValueError, match="scope rules version"):
        require_semantic_attestations([READ], [READ], dict(SCOPE, rules_version="old"))
    stale = dict(SCOPE, rule_audit=dict(SCOPE["rule_audit"], rules_version="old"))
    with pytest.raises(ValueError, match="rule audit version"):
        require_semantic_attestations([READ], [READ], stale)


def test_rule_decided_labels_need_a_measured_passing_audit():
    require_semantic_attestations([READ], [rule_decision("pool.on_property")], SCOPE)
    with pytest.raises(ValueError, match="rule not audited"):
        require_semantic_attestations([READ], [rule_decision("pool.unmeasured")], SCOPE)
    with pytest.raises(ValueError, match="rule not audited"):
        require_semantic_attestations(
            [READ], [rule_decision("pool.tiny_sample")], SCOPE
        )
    with pytest.raises(ValueError, match="below agreement"):
        require_semantic_attestations([READ], [rule_decision("patio.explicit")], SCOPE)
    with pytest.raises(ValueError, match="review method"):
        require_semantic_attestations(
            [READ], [rule_decision("pool.on_property", method="assumed")], SCOPE
        )


def label_case(remark="A sparkling backyard pool."):
    facet = dict(
        group="exterior_lot", value="pool", polarity="affirmed", temporality="current"
    )
    return dict(remark=remark, stored_facets=[facet])


def test_label_coverage_requires_every_in_scope_label():
    case = label_case()
    rule = "pool.on_property"
    require_label_coverage([case], [rule_decision(rule)])
    with pytest.raises(ValueError, match="coverage mismatch"):
        require_label_coverage([case], [dict(label_reviews=[])])
    with pytest.raises(ValueError, match="coverage mismatch"):
        require_label_coverage([case], [rule_decision(rule, value="patio")])


def test_label_coverage_rejects_rule_outcomes_it_cannot_reproduce():
    rule = "pool.on_property"
    with pytest.raises(ValueError, match="not reproducible"):
        require_label_coverage([label_case()], [rule_decision("pool.no_mention")])
    with pytest.raises(ValueError, match="not reproducible"):
        require_label_coverage(
            [label_case()], [rule_decision(rule, rule_version="old")]
        )
    with pytest.raises(ValueError, match="not reproducible"):
        require_label_coverage([label_case()], [rule_decision(rule, evidence="")])


POOL = dict(
    group="exterior_lot", value="pool", polarity="affirmed", temporality="current"
)


def removal(label=POOL):
    return dict(
        operation="remove",
        original=label,
        corrected_annotation=None,
        evidence_quote="pool",
        reason="r",
    )


def read_review(action, target=None, **label):
    base = dict(value="pool", polarity="affirmed", temporality="current")
    return dict(base, **label, action=action, method="read", rule=None, target=target)


@pytest.mark.parametrize(
    ("status", "changes", "review"),
    [
        ("corrected", [removal()], read_review("keep")),
        ("accepted_unchanged", [], read_review("remove")),
        ("accepted_unchanged", [], read_review("retag", ["uncertain", "unspecified"])),
    ],
)
def test_reviews_must_match_applied_changes(status, changes, review):
    case = label_case()
    decision = dict(status=status, changes=changes, label_reviews=[review])
    with pytest.raises(ValueError, match="do not match"):
        require_label_coverage([case], [decision])


def test_unreviewed_addition_and_doubled_label_are_rejected():
    case = label_case()
    added = dict(
        operation="add",
        original=None,
        corrected_annotation=dict(POOL, value="patio", group="exterior_lot"),
        evidence_quote="pool",
        reason="r",
    )
    decision = dict(
        status="corrected", changes=[added], label_reviews=[read_review("keep")]
    )
    with pytest.raises(ValueError, match="do not match"):
        require_label_coverage([case], [decision])
    doubled = dict(added, corrected_annotation=POOL)
    decision = dict(
        status="corrected", changes=[doubled], label_reviews=[read_review("keep")]
    )
    with pytest.raises(ValueError, match="double"):
        require_label_coverage([case], [decision])


def test_rule_review_action_must_match_the_rule_outcome():
    with pytest.raises(ValueError, match="not reproducible"):
        require_label_coverage(
            [label_case()],
            [rule_decision("pool.on_property", action="remove")],
        )


def diagnostic(reviews, changes=(), history=(), status="accepted_unchanged"):
    return dict(
        status=status,
        changes=list(changes),
        label_reviews=reviews,
        correction_history=[dict(changes=list(history))],
    )


def test_diagnostic_coverage_requires_every_label_read():
    case = label_case()
    require_diagnostic_coverage([case], [diagnostic([read_review("keep")])])
    with pytest.raises(ValueError, match="diagnostic review coverage"):
        require_diagnostic_coverage([case], [diagnostic([])])
    ruled = dict(read_review("keep"), method="rule")
    with pytest.raises(ValueError, match="not read"):
        require_diagnostic_coverage([case], [diagnostic([ruled])])


def test_diagnostic_coverage_includes_earlier_additions():
    case = label_case()
    patio = dict(POOL, value="patio")
    earlier = dict(
        operation="add",
        original=None,
        corrected_annotation=patio,
        evidence_quote="pool",
        reason="r",
    )
    with pytest.raises(ValueError, match="diagnostic review coverage"):
        require_diagnostic_coverage(
            [case], [diagnostic([read_review("keep")], history=[earlier])]
        )
    reviews = [read_review("keep"), read_review("keep", value="patio")]
    require_diagnostic_coverage(
        [case], [diagnostic(reviews, [earlier], [earlier], status="corrected")]
    )
