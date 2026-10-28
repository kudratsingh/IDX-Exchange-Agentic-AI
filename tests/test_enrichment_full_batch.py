"""Full extraction batch tests use only invented remarks and fake responses."""

import sqlite3

import pytest

from idx_agent.enrichment.full_batch import (
    initialize,
    records,
    run_batch,
    verify_complete_source,
)


def source(n):
    return [(str(i), f"invented remark {i}") for i in range(n)]


def reply(_):
    return (
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "record_extractions",
                    "input": {"annotations": []},
                }
            ]
        },
        {"input_tokens": 1},
        b"{}",
    )


def test_resume_preserves_completed_results_and_checkpoints(tmp_path):
    path = tmp_path / "table.sqlite3"
    db = sqlite3.connect(path)
    initialize(db, "frozen", "2026-09-18")
    calls = []

    def interrupted(text):
        calls.append(text)
        if len(calls) == 53:
            raise RuntimeError("interrupt")
        return reply(text)

    with pytest.raises(RuntimeError):
        run_batch(db, source(105), interrupted, lambda: True, lambda *_: None)
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 52
    assert db.execute("SELECT completed FROM checkpoints").fetchall() == [(50,)]
    db.close()
    db = sqlite3.connect(path)
    initialize(db, "frozen", "2026-09-18")
    calls.clear()

    def resume(text):
        calls.append(text)
        return reply(text)

    report = run_batch(db, source(105), resume, lambda: True, lambda *_: None)
    assert len(calls) == 53 and calls[0] == "invented remark 52"
    assert report == {
        "completed": 105,
        "previously_completed": 52,
        "newly_completed": 53,
    }
    assert db.execute(
        "SELECT completed FROM checkpoints ORDER BY completed"
    ).fetchall() == [(50,), (100,), (105,)]
    with pytest.raises(ValueError, match="already complete"):
        initialize(db, "frozen", "2026-09-18")


def test_resume_rejects_changed_source_before_paid_call():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")

    def fail(text):
        if text.endswith("1"):
            raise RuntimeError("interrupt")
        return reply(text)

    with pytest.raises(RuntimeError):
        run_batch(db, source(2), fail, lambda: True, lambda *_: None)
    with pytest.raises(ValueError, match="source changed"):
        run_batch(
            db,
            [("0", "changed"), ("1", "invented")],
            lambda _: pytest.fail("paid call"),
            lambda: True,
            lambda _: None,
        )


def test_source_redacts_and_deduplicates_without_truncation():
    pages = [
        (
            [
                {
                    "L_ListingID": "1",
                    "L_Remarks": "Email replace-me@example.com for a patio",
                },
                {"L_ListingID": "1", "L_Remarks": "older"},
                {"L_ListingID": "2", "L_Remarks": " "},
            ],
            "2",
        )
    ]
    result = list(records(pages))
    assert len(result) == 1 and result[0][0] == "1"
    assert "replace-me@example.com" not in result[0][1] and "patio" in result[0][1]


def test_short_nonempty_remark_is_not_dropped():
    pages = [([{"L_ListingID": "1", "L_Remarks": "as-is"}], "1")]
    assert list(records(pages)) == [("1", "as-is")]


def test_changed_freeze_or_source_asof_never_completes():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    with pytest.raises(ValueError, match="metadata mismatch"):
        initialize(db, "changed", "2026-09-18")
    with pytest.raises(ValueError, match="as-of changed"):
        run_batch(db, source(1), reply, lambda: False, lambda *_: None)
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
    assert (
        db.execute("SELECT value FROM metadata WHERE name='complete'").fetchone()
        is None
    )


def test_table_stores_facets_without_quote_or_remark():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {
                    "annotations": [
                        {
                            "kind": "facet",
                            "quote": "patio",
                            "group": "exterior_lot",
                            "facet_value": "patio",
                            "polarity": "affirmed",
                            "temporality": "current",
                        }
                    ]
                },
            }
        ]
    }
    run_batch(
        db,
        [("1", "invented patio")],
        lambda _: (response, {}, b"{}"),
        lambda: True,
        lambda *_: None,
    )
    facets = db.execute("SELECT facets FROM results").fetchone()[0]
    assert '"value": "patio"' in facets
    assert "quote" not in facets and "invented" not in facets


def test_completion_source_audit_catches_missing_and_changed_rows():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    run_batch(db, source(2), reply, lambda: True, lambda *_: None)
    assert verify_complete_source(db, source(2))
    assert not verify_complete_source(db, source(1))
    assert not verify_complete_source(db, [("0", "different"), source(2)[1]])
    assert not verify_complete_source(db, source(3))


def test_tranche_stops_at_limit_and_can_resume():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    calls = []

    def invoke(text):
        calls.append(text)
        return reply(text)

    paused = run_batch(
        db, source(55), invoke, lambda: True, lambda *_: None, stop_after=50
    )
    assert paused == {
        "completed": 50,
        "previously_completed": 0,
        "newly_completed": 50,
        "paused": 1,
    }
    assert len(calls) == 50
    assert (
        db.execute("SELECT value FROM metadata WHERE name='complete'").fetchone()
        is None
    )
    assert db.execute("SELECT completed FROM checkpoints").fetchall() == [(50,)]
    calls.clear()
    finished = run_batch(db, source(55), invoke, lambda: True, lambda *_: None)
    assert len(calls) == 5 and finished["completed"] == 55


def test_tranche_source_change_fails_after_durable_checkpoint():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    with pytest.raises(ValueError, match="source changed during tranche"):
        run_batch(
            db,
            source(55),
            reply,
            lambda: True,
            lambda *_: None,
            stop_after=50,
            partial_unchanged=lambda: False,
        )
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 50
    assert (
        db.execute("SELECT value FROM metadata WHERE name='complete'").fetchone()
        is None
    )


def test_tranche_one_never_sends_2001st_remark():
    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    sent = []

    def invoke(text):
        sent.append(text)
        return reply(text)

    summary = run_batch(
        db, source(2001), invoke, lambda: True, lambda *_: None, stop_after=2000
    )
    assert len(sent) == 2000
    assert summary["completed"] == 2000 and summary["paused"] == 1
    assert db.execute("SELECT MAX(completed) FROM checkpoints").fetchone()[0] == 2000


def test_aggregate_includes_all_prior_tranche_results():
    from scripts.extract_enrichment_full import aggregate

    db = sqlite3.connect(":memory:")
    initialize(db, "frozen", "2026-09-18")
    run_batch(db, source(3), reply, lambda: True, lambda *_: None, stop_after=2)
    total = aggregate(db, 0)
    new = aggregate(db, 1)
    assert total["remarks"] == 2 and total["usage"]["input_tokens"] == 2
    assert new["remarks"] == 1 and new["usage"]["input_tokens"] == 1
    assert total["usage"]["output_tokens"] is None
