"""Pure batch planning tests; no network or provider SDK."""

import pytest

from idx_agent.enrichment.batch_v2 import prepare_batch


def test_batch_plan_caps_requests_and_uses_opaque_ids():
    cases = [(f"case-{i:08d}", "invented remark") for i in range(1000)]
    batch = prepare_batch(cases, "invented-model", "invented prompt")
    assert len(batch) == 1000 and batch[0]["custom_id"] == "case-00000000"
    assert batch[0]["params"]["model"] == "invented-model"
    with pytest.raises(ValueError, match="1..1000"):
        prepare_batch(cases + [("case-00001000", "invented")], "m", "p")


def test_batch_plan_rejects_duplicate_or_source_identifier():
    with pytest.raises(ValueError):
        prepare_batch([("12345678", "invented")], "m", "p")
    with pytest.raises(ValueError):
        prepare_batch([("case-00000001", "a"), ("case-00000001", "b")], "m", "p")


def test_uncertain_submission_is_never_automatically_retried():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import (
        initialize_batch_store,
        stage_tranche,
        submit_batch,
    )

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    stage_tranche(
        db, [("private-key", "invented")], "model", "prompt", "schema", "time"
    )
    spent = []

    def fail(_):
        raise TimeoutError("unknown submission state")

    with pytest.raises(TimeoutError):
        submit_batch(db, 1, "model", "prompt", spent.append, fail)
    assert spent == [1]
    assert db.execute("SELECT status FROM batches").fetchone()[0] == "uncertain"
    with pytest.raises(ValueError, match="not planned"):
        submit_batch(db, 1, "model", "prompt", spent.append, fail)
    assert spent == [1]


def test_out_of_order_results_are_matched_and_checkpointed():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import (
        ingest_batch,
        initialize_batch_store,
        stage_tranche,
        submit_batch,
    )

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    stage_tranche(
        db,
        [(str(i), "invented") for i in range(51)],
        "model",
        "prompt",
        "schema",
        "time",
    )
    sent = []
    submit_batch(
        db,
        1,
        "model",
        "prompt",
        lambda n: sent.append(n),
        lambda payload: {"id": "msgbatch_abc123"},
    )
    message = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ],
        "usage": {"input_tokens": 1},
    }
    result = [
        {
            "custom_id": f"case-{i:08d}",
            "result": {"type": "succeeded", "message": message},
        }
        for i in reversed(range(1, 52))
    ]
    assert ingest_batch(db, 1, result, lambda *_: None) == {
        "completed": 51,
        "failures": {"errored": 0, "canceled": 0, "expired": 0},
    }
    assert sent == [51]
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 51
    assert db.execute("SELECT completed FROM checkpoints").fetchall() == [(50,)]
    assert db.execute("SELECT status FROM batches").fetchone()[0] == "complete"


def test_partial_or_errored_batch_cannot_appear_complete():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import (
        ingest_batch,
        initialize_batch_store,
        stage_tranche,
        submit_batch,
    )

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    stage_tranche(
        db, [("1", "invented"), ("2", "invented")], "model", "prompt", "schema", "time"
    )
    submit_batch(
        db, 1, "model", "prompt", lambda _: None, lambda _: {"id": "msgbatch_abc"}
    )
    bad = [
        {"custom_id": "case-00000001", "result": {"type": "errored"}},
        {"custom_id": "case-00000002", "result": {"type": "expired"}},
    ]
    result = ingest_batch(db, 1, bad, lambda *_: None)
    assert result["failures"] == {"errored": 1, "canceled": 0, "expired": 1}
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    assert db.execute("SELECT status FROM batches").fetchone()[0] == "partial"


def test_extend_requires_complete_prior_batches_and_identical_source():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import initialize_batch_store, stage_tranche

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    source = [(str(i), f"invented {i}") for i in range(4)]
    assert stage_tranche(db, source, "model", "prompt", "schema", "time", limit=2) == 2
    with pytest.raises(ValueError, match="previous batches incomplete"):
        stage_tranche(
            db, source, "model", "prompt", "schema", "time", limit=2, extend=True
        )
    db.execute("UPDATE batches SET status='complete'")
    db.execute("INSERT INTO verifications(completed,watermark) VALUES (2,'time')")
    db.commit()
    with pytest.raises(ValueError, match="source changed"):
        stage_tranche(
            db,
            [("0", "changed"), *source[1:]],
            "model",
            "prompt",
            "schema",
            "time",
            limit=2,
            extend=True,
        )
    assert (
        stage_tranche(
            db, source, "model", "prompt", "schema", "time", limit=2, extend=True
        )
        == 4
    )
    assert db.execute(
        "SELECT start_sequence,end_sequence FROM batches ORDER BY batch_number"
    ).fetchall() == [(1, 2), (3, 4)]


def test_successes_are_saved_even_when_another_batch_item_fails():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import (
        ingest_batch,
        initialize_batch_store,
        stage_tranche,
        submit_batch,
    )

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    stage_tranche(db, [("1", "invented"), ("2", "invented")], "m", "p", "s", "t")
    submit_batch(db, 1, "m", "p", lambda _: None, lambda _: {"id": "msgbatch_abc"})
    message = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ],
        "usage": {},
    }
    outcomes = [
        {
            "custom_id": "case-00000001",
            "result": {"type": "succeeded", "message": message},
        },
        {"custom_id": "case-00000002", "result": {"type": "errored"}},
    ]
    notes = []
    result = ingest_batch(db, 1, outcomes, lambda errors, raw: notes.extend(errors))
    assert result["completed"] == 1 and result["failures"]["errored"] == 1
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
    assert db.execute("SELECT status FROM batches").fetchone()[0] == "partial"
    assert notes[0]["rule"] == "batch_errored"


def test_failed_items_can_be_planned_and_resolved_without_repeating_successes():
    import sqlite3

    from idx_agent.enrichment.batch_v2 import (
        ingest_batch,
        initialize_batch_store,
        plan_failed_retries,
        stage_tranche,
        submit_batch,
    )

    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    stage_tranche(db, [(str(i), "invented") for i in range(3)], "m", "p", "s", "t")
    submit_batch(db, 1, "m", "p", lambda _: None, lambda _: {"id": "msgbatch_first"})
    message = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ],
        "usage": {},
    }
    first = [
        {
            "custom_id": f"case-{i:08d}",
            "result": (
                {"type": "errored"}
                if i == 2
                else {"type": "succeeded", "message": message}
            ),
        }
        for i in range(1, 4)
    ]
    ingest_batch(db, 1, first, lambda *_: None)
    assert plan_failed_retries(db) == 1
    sent = []
    submit_batch(
        db,
        2,
        "m",
        "p",
        lambda n: sent.append(n),
        lambda payload: {"id": "msgbatch_retry"},
    )
    assert sent == [1]
    ingest_batch(
        db,
        2,
        [
            {
                "custom_id": "case-00000002",
                "result": {"type": "succeeded", "message": message},
            }
        ],
        lambda *_: None,
    )
    assert db.execute(
        "SELECT status FROM batches ORDER BY batch_number"
    ).fetchall() == [("resolved",), ("complete",)]
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 3
