"""Provider calls are mocked; no live service or credentials are used."""

import io
import urllib.error

import pytest
from scripts import extract_enrichment_v2_batch as batch


def test_get_retries_transient_errors_and_spends_each_attempt(monkeypatch):
    attempts, spent, slept = [], [], []

    def open_stub(request, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(
                "private", 429, "private", {}, io.BytesIO(b"private")
            )
        return io.BytesIO(b"{}")

    monkeypatch.setattr(batch.consent, "spend_paid_call", lambda: spent.append(1))
    monkeypatch.setattr(batch.urllib.request, "urlopen", open_stub)
    monkeypatch.setattr(batch.time, "sleep", slept.append)
    assert batch.request_http("/batches/id", "fake") == b"{}"
    assert len(attempts) == len(spent) == 3 and slept == [1, 2]


def test_post_timeout_is_not_retried(monkeypatch):
    attempts, spent = [], []

    def fail(request, timeout):
        attempts.append(1)
        raise TimeoutError("private")

    monkeypatch.setattr(batch.consent, "spend_paid_call", lambda: spent.append(1))
    monkeypatch.setattr(batch.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="provider_request_failed"):
        batch.request_http("/batches", "fake", payload={"requests": []})
    assert len(attempts) == len(spent) == 1


def test_cli_retries_failed_item_after_extending_to_4000(tmp_path, monkeypatch, capsys):
    import json
    import sqlite3
    from types import SimpleNamespace

    from evals import run

    from idx_agent.enrichment.batch_v2 import initialize_batch_store, stage_tranche

    private = tmp_path / "enrichment"
    directory = private / "full"
    directory.mkdir(parents=True, mode=0o700)
    (private / "usage-dev-v2.json").write_text(
        json.dumps(
            {"haiku_within_three_points": False, "contract_hashes": {"test": "hash"}}
        )
    )
    path = directory / "active-facets-v2.sqlite3"
    db = sqlite3.connect(path)
    path.chmod(0o600)
    initialize_batch_store(db)
    import hashlib

    source = [(str(i), "invented") for i in range(4000)]
    reused = {
        str(i): (hashlib.sha256(b"invented").hexdigest(), "[]", 0, "{}")
        for i in range(324)
    }
    stage_tranche(
        db,
        source,
        batch.MODELS["sonnet"],
        batch.PROMPT_HASH,
        batch.SCHEMA_HASH,
        "watermark",
        reuse_v1=reused,
    )
    db.execute("UPDATE batches SET status='complete'")
    db.execute(
        "INSERT INTO verifications(completed,watermark) VALUES (2000,'watermark')"
    )
    db.commit()
    stage_tranche(
        db,
        source,
        batch.MODELS["sonnet"],
        batch.PROMPT_HASH,
        batch.SCHEMA_HASH,
        "watermark",
        extend=True,
        reuse_v1=reused,
    )
    db.execute("UPDATE batches SET status='complete' WHERE batch_number=4")
    db.execute("UPDATE batches SET status='partial' WHERE batch_number=3")
    db.execute(
        "INSERT INTO failed_items(batch_number,sequence,result_type) "
        "VALUES (3,3000,'errored')"
    )
    db.commit()
    db.close()

    budget = SimpleNamespace(max_calls=6000, calls_made=0)
    monkeypatch.setattr(batch, "PRIVATE", private)
    monkeypatch.setattr(batch, "verify_freeze", lambda: None)
    monkeypatch.setattr(batch, "contract_hashes", lambda: {"test": "hash"})
    monkeypatch.setattr(batch, "sonnet_fallback_selected", lambda _: True)
    monkeypatch.setattr(batch, "load_v1_reuse", lambda _: reused)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake")
    monkeypatch.setattr(batch, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(batch, "active_watermark", lambda _: "watermark")
    monkeypatch.setattr(batch, "iter_pages", lambda _: [])
    monkeypatch.setattr(batch, "source_matches", lambda *_: True)
    monkeypatch.setattr(batch.consent, "start_paid_run", lambda: budget)
    monkeypatch.setattr(batch.consent, "abort_paid_run", lambda _: None)
    monkeypatch.setattr(
        batch.consent,
        "spend_paid_call",
        lambda n=1: setattr(budget, "calls_made", budget.calls_made + n),
    )
    submissions = []

    def request(path, key, *, payload=None, on_error=None):
        submissions.append(payload)
        return b'{"id":"msgbatch_retry"}'

    monkeypatch.setattr(batch, "request_http", request)
    monkeypatch.setattr(
        batch.sys,
        "argv",
        [
            "script",
            "--action",
            "submit",
            "--model",
            "sonnet",
            "--approved-provider-disclosure",
            "--v1-reuse",
            "yes",
            "--retry-failed-after-approval",
        ],
    )
    assert batch.main() == 0
    assert len(submissions) == 1 and len(submissions[0]["requests"]) == 1
    assert submissions[0]["requests"][0]["custom_id"] == "case-00003000"
    assert budget.calls_made == 1
    assert '"status": "done"' in capsys.readouterr().out


def test_cli_rejects_short_initial_tranche_on_both_invocations(
    tmp_path, monkeypatch, capsys
):
    import json
    import sqlite3
    from types import SimpleNamespace

    from evals import run

    private = tmp_path / "enrichment"
    (private / "full").mkdir(parents=True, mode=0o700)
    (private / "usage-dev-v2.json").write_text(
        json.dumps(
            {"haiku_within_three_points": False, "contract_hashes": {"test": "hash"}}
        )
    )
    import hashlib

    source = [(str(i), "invented") for i in range(1500)]
    reused = {
        str(i): (hashlib.sha256(b"invented").hexdigest(), "[]", 0, "{}")
        for i in range(324)
    }
    monkeypatch.setattr(batch, "PRIVATE", private)
    monkeypatch.setattr(batch, "verify_freeze", lambda: None)
    monkeypatch.setattr(batch, "contract_hashes", lambda: {"test": "hash"})
    monkeypatch.setattr(batch, "sonnet_fallback_selected", lambda _: True)
    monkeypatch.setattr(batch, "load_v1_reuse", lambda _: reused)
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake")
    monkeypatch.setattr(batch, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(batch, "active_watermark", lambda _: "watermark")
    monkeypatch.setattr(batch, "iter_pages", lambda _: [])
    monkeypatch.setattr(batch, "records", lambda _: iter(source))
    monkeypatch.setattr(batch, "source_matches", lambda *_: True)
    monkeypatch.setattr(
        batch.consent,
        "start_paid_run",
        lambda: SimpleNamespace(max_calls=6000, calls_made=0),
    )
    monkeypatch.setattr(batch.consent, "abort_paid_run", lambda _: None)
    spent, submissions = [], []
    monkeypatch.setattr(batch.consent, "spend_paid_call", lambda n=1: spent.append(n))

    def request(path, key, *, payload=None, on_error=None):
        submissions.append(payload)
        return b'{"id":"msgbatch_invented"}'

    monkeypatch.setattr(batch, "request_http", request)
    monkeypatch.setattr(
        batch.sys,
        "argv",
        [
            "script",
            "--action",
            "submit",
            "--model",
            "sonnet",
            "--approved-provider-disclosure",
            "--v1-reuse",
            "yes",
        ],
    )

    assert batch.main() == 1
    assert batch.main() == 1
    assert spent == [] and submissions == []
    db = sqlite3.connect(private / "full" / "active-facets-v2.sqlite3")
    assert db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0] == 1500
    assert (
        db.execute("SELECT COUNT(*) FROM batches WHERE status != 'planned'").fetchone()[
            0
        ]
        == 0
    )
    db.close()
    assert capsys.readouterr().out.count('"status": "stopped"') == 2
