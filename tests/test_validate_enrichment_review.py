"""Structural review checks use synthetic evidence only."""

import copy
import hashlib
import json
import sqlite3

import pytest
from scripts.validate_enrichment_review import validate, validate_store


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
