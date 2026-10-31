"""Structural review checks use synthetic evidence only."""

import copy
import hashlib
import json
import sqlite3

import pytest
from scripts.validate_enrichment_review import (
    apply_resolved,
    require_complete,
    require_semantic_attestations,
    validate,
    validate_store,
)


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


def test_completion_requires_manual_review_and_complete_scope():
    scope = {"candidate_discovery_complete": True, "population": 54417}
    require_semantic_attestations(
        [{"semantic_reviewed": True}], [{"semantic_reviewed": True}], scope
    )
    with pytest.raises(ValueError, match="semantic review"):
        require_semantic_attestations([{}], [{"semantic_reviewed": True}], scope)
    with pytest.raises(ValueError, match="discovery incomplete"):
        require_semantic_attestations(
            [{"semantic_reviewed": True}],
            [{"semantic_reviewed": True}],
            {"candidate_discovery_complete": False, "population": 54417},
        )
