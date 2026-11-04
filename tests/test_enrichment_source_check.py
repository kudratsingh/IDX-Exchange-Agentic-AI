"""The effective-store builder's source check: the results table must be exactly what
the frozen audit certified. Synthetic SQLite source; every remark is invented."""

import hashlib
import inspect
import json
import sqlite3

import pytest

from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.source_check import (
    EXPECTED_RESULTS_DIGEST,
    EXPECTED_WATERMARK,
    results_digest,
    verify_source,
)

WATERMARK = "2026-09-18 06:58:44"
SOLAR = dict(
    group="interior_systems", value="solar", polarity="affirmed", temporality="current"
)
GARAGE = dict(
    group="exterior_lot", value="garage", polarity="affirmed", temporality="current"
)
PATIO = dict(GARAGE, value="patio")
# Row 1 is a diagnostic case, row 2 is in the policy-audit inventory (a solar label),
# and row 3 is outside both packets (garage is not a policy-audited facet).
REMARKS = {
    1: ("901", "Invented remark one with owned solar.", [SOLAR], 1),
    2: ("902", "Invented remark two with owned solar.", [SOLAR], 0),
    3: ("903", "Invented remark three with a garage.", [GARAGE], 0),
}
OUTSIDE = 3


def source():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE inputs(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                            remark);
        CREATE TABLE results(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                             facets, diagnostic_count, usage);
        CREATE TABLE result_origins(sequence INTEGER PRIMARY KEY, extractor);
        CREATE TABLE settings(name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE verifications(completed INTEGER PRIMARY KEY, watermark TEXT);
        """
    )
    for seq, (key, remark, facets, diag) in REMARKS.items():
        digest = hashlib.sha256(remark.encode()).hexdigest()
        db.execute("INSERT INTO inputs VALUES (?,?,?,?)", (seq, key, digest, remark))
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?,?)",
            (seq, key, digest, json.dumps(facets), diag, json.dumps({"output": 10})),
        )
        db.execute("INSERT INTO result_origins VALUES (?, 'v2')", (seq,))
    db.execute("INSERT INTO settings VALUES ('watermark', ?)", (WATERMARK,))
    db.execute("INSERT INTO verifications VALUES (3, ?)", (WATERMARK,))
    return db


# The fixture's approved digest, frozen once from an intact source, the way the real
# one is a constant. Sources under test are edited after it was taken.
APPROVED = results_digest(source())


def audit(db):
    """The frozen audit artifacts, as certified on the intact source."""
    key, remark, facets, _ = REMARKS[1]
    diagnostic = [
        dict(
            sequence=1,
            listing_key=key,
            remark=remark,
            origin="v2",
            stored_facets=facets,
        )
    ]
    dataset = list(candidates(db))
    decisions = [dict(sequence=c["sequence"]) for c in dataset]
    scope = dict(population=2, inventory_rows=len(dataset))
    return diagnostic, dataset, decisions, scope


def check(db, frozen, digest=APPROVED):
    return verify_source(
        db,
        *frozen,
        expected_rows=3,
        expected_population=2,
        expected_watermark=WATERMARK,
        expected_digest=digest,
    )


def test_the_intact_source_passes():
    db = source()
    assert check(db, audit(db)) == 3


def test_row_three_is_outside_both_audit_packets():
    db = source()
    diagnostic, dataset, _, _ = audit(db)
    assert OUTSIDE not in {c["sequence"] for c in diagnostic}
    assert OUTSIDE not in {c["sequence"] for c in dataset}


def test_a_result_removed_without_its_input_is_refused():
    db = source()
    frozen = audit(db)
    db.execute("DELETE FROM results WHERE sequence = 3")
    with pytest.raises(ValueError, match="source, result or provenance mismatch"):
        check(db, frozen)


def test_a_whole_row_removed_is_refused_even_though_the_rest_is_consistent():
    db = source()
    frozen = audit(db)
    for table in ("inputs", "results", "result_origins"):
        db.execute(f"DELETE FROM {table} WHERE sequence = 3")
    with pytest.raises(ValueError):
        check(db, frozen)


def test_a_changed_audited_label_is_refused():
    db = source()
    frozen = audit(db)
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = 2", (json.dumps([GARAGE]),)
    )
    with pytest.raises(ValueError):
        check(db, frozen)


def test_an_edited_remark_is_refused():
    db = source()
    frozen = audit(db)
    db.execute("UPDATE inputs SET remark = 'edited' WHERE sequence = 2")
    with pytest.raises(ValueError, match="mismatch"):
        check(db, frozen)


def test_an_overlay_that_misses_an_audited_row_is_refused():
    db = source()
    diagnostic, dataset, decisions, scope = audit(db)
    with pytest.raises(ValueError, match="does not cover"):
        check(db, (diagnostic, dataset, decisions[:-1], scope))


def test_scope_counts_must_match():
    db = source()
    diagnostic, dataset, decisions, scope = audit(db)
    with pytest.raises(ValueError, match="population"):
        check(db, (diagnostic, dataset, decisions, dict(scope, population=99)))
    with pytest.raises(ValueError, match="frozen scope"):
        check(db, (diagnostic, dataset, decisions, dict(scope, inventory_rows=99)))


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE settings SET value = '2030-01-01 00:00:00' WHERE name = 'watermark'",
        "UPDATE verifications SET watermark = '2030-01-01 00:00:00'",
        "DELETE FROM verifications",
        "DELETE FROM settings",
    ],
)
def test_a_changed_or_missing_watermark_is_refused(tamper):
    """Raising the watermark would make every changed listing look fresh."""
    db = source()
    frozen = audit(db)
    db.execute(tamper)
    with pytest.raises(ValueError, match="watermark"):
        check(db, frozen)


# --- The frozen results digest: rows outside both audit packets ---


def test_a_facet_edit_outside_both_audit_packets_is_refused():
    db = source()
    frozen = audit(db)
    edited = dict(GARAGE, polarity="negated")
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = ?",
        (json.dumps([edited]), OUTSIDE),
    )
    # Coverage, inventory and hashes all still pass; only the frozen digest catches it.
    with pytest.raises(ValueError, match="approved results digest"):
        check(db, frozen)


def test_an_added_facet_outside_both_audit_packets_is_refused():
    db = source()
    frozen = audit(db)
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = ?",
        (json.dumps([GARAGE, PATIO]), OUTSIDE),
    )
    with pytest.raises(ValueError, match="approved results digest"):
        check(db, frozen)


def test_a_provenance_edit_outside_both_audit_packets_is_refused():
    db = source()
    frozen = audit(db)
    db.execute(
        "UPDATE result_origins SET extractor = 'v1' WHERE sequence = ?", (OUTSIDE,)
    )
    with pytest.raises(ValueError, match="approved results digest"):
        check(db, frozen)


def test_a_usage_edit_outside_both_audit_packets_is_refused():
    db = source()
    frozen = audit(db)
    db.execute(
        "UPDATE results SET usage = ? WHERE sequence = ?",
        (json.dumps({"output": 11}), OUTSIDE),
    )
    with pytest.raises(ValueError, match="approved results digest"):
        check(db, frozen)


def test_facet_order_changes_the_digest_but_storage_formatting_does_not():
    db = source()
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = ?",
        (json.dumps([GARAGE, PATIO]), OUTSIDE),
    )
    ordered = results_digest(db)
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = ?",
        (json.dumps([GARAGE, PATIO], indent=2), OUTSIDE),
    )
    assert results_digest(db) == ordered
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = ?",
        (json.dumps([PATIO, GARAGE]), OUTSIDE),
    )
    assert results_digest(db) != ordered


def test_the_build_compares_against_the_frozen_constant():
    """The default expected value is the approved constant, never the source's own."""
    default = inspect.signature(verify_source).parameters["expected_digest"].default
    assert default == EXPECTED_RESULTS_DIGEST
    assert len(EXPECTED_RESULTS_DIGEST) == 64
    int(EXPECTED_RESULTS_DIGEST, 16)
    db = source()
    frozen = audit(db)
    # An intact synthetic source is still not the approved real source.
    with pytest.raises(ValueError, match="approved results digest"):
        verify_source(
            db,
            *frozen,
            expected_rows=3,
            expected_population=2,
            expected_watermark=WATERMARK,
        )


def test_the_real_constants_are_the_verified_extraction_values():
    assert EXPECTED_WATERMARK == WATERMARK


def test_an_appended_supplement_row_is_refused_without_new_approval():
    """WO-032: a complete, internally consistent row appended after the certified ones
    (input, result and v2 provenance, as a supplement wave would write it) changes the
    digest, so the builder refuses it until a new approved value is committed."""
    db = source()
    frozen = audit(db)
    remark = "Invented supplement remark with a garage."
    digest = hashlib.sha256(remark.encode()).hexdigest()
    db.execute("INSERT INTO inputs VALUES (4, '904', ?, ?)", (digest, remark))
    db.execute(
        "INSERT INTO results VALUES (4, '904', ?, ?, 0, ?)",
        (digest, json.dumps([GARAGE]), json.dumps({"output": 10})),
    )
    db.execute("INSERT INTO result_origins VALUES (4, 'v2')")
    with pytest.raises(ValueError, match="approved results digest"):
        check(db, frozen)
