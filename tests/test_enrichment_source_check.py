"""The effective-store builder's source check: the results table must be exactly what
the frozen audit certified. Synthetic SQLite source; every remark is invented."""

import hashlib
import json
import sqlite3

import pytest

from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.source_check import verify_source

SOLAR = dict(
    group="interior_systems", value="solar", polarity="affirmed", temporality="current"
)
GARAGE = dict(
    group="exterior_lot", value="garage", polarity="affirmed", temporality="current"
)
WATERMARK = "2026-09-18 06:58:44"
REMARKS = {
    1: ("901", "Invented remark one with owned solar.", [SOLAR], 1),
    2: ("902", "Invented remark two with owned solar.", [SOLAR], 0),
    3: ("903", "Invented remark three with a garage.", [GARAGE], 0),
}


def source():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE inputs(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                            remark);
        CREATE TABLE results(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                             facets, diagnostic_count);
        CREATE TABLE result_origins(sequence INTEGER PRIMARY KEY, extractor);
        CREATE TABLE settings(name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE verifications(completed INTEGER PRIMARY KEY, watermark TEXT);
        """
    )
    db.execute("INSERT INTO settings VALUES ('watermark', ?)", (WATERMARK,))
    db.execute("INSERT INTO verifications VALUES (3, ?)", (WATERMARK,))
    for seq, (key, remark, facets, diag) in REMARKS.items():
        digest = hashlib.sha256(remark.encode()).hexdigest()
        db.execute("INSERT INTO inputs VALUES (?,?,?,?)", (seq, key, digest, remark))
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?)",
            (seq, key, digest, json.dumps(facets), diag),
        )
        db.execute("INSERT INTO result_origins VALUES (?, 'v2')", (seq,))
    return db


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


def check(db, frozen):
    return verify_source(
        db,
        *frozen,
        expected_rows=3,
        expected_population=2,
        expected_watermark=WATERMARK,
    )


def test_the_intact_source_passes():
    db = source()
    assert check(db, audit(db)) == 3


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


def test_a_changed_label_is_refused():
    db = source()
    frozen = audit(db)
    db.execute(
        "UPDATE results SET facets = ? WHERE sequence = 2", (json.dumps([GARAGE]),)
    )
    with pytest.raises(ValueError, match="inventory differs from the results"):
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


def test_the_real_constant_is_the_verified_extraction_watermark():
    from idx_agent.enrichment.source_check import EXPECTED_WATERMARK

    assert EXPECTED_WATERMARK == WATERMARK
