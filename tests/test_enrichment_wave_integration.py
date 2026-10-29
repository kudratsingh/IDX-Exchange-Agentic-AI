"""Synthetic wave staging and gate tests; no provider or private data."""

import json
import sqlite3
from decimal import Decimal

import pytest

from idx_agent.enrichment.batch_v2 import initialize_batch_store, stage_tranche
from idx_agent.enrichment.wave_gate import (
    console_delta,
    estimated_cost,
    next_wave,
    record_console_baseline,
    verify_stored_wave,
)

USAGE = json.dumps(
    dict(
        input_tokens=500,
        output_tokens=200,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1000,
    )
)


def setup_wave():
    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    source = [(str(i), "synthetic") for i in range(18000)]
    for _ in range(4):
        stage_tranche(
            db,
            source,
            "m",
            "p",
            "s",
            "wm",
            extend=bool(db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]),
        )
        n = db.execute("SELECT COUNT(*) FROM inputs").fetchone()[0]
        db.execute("UPDATE batches SET status='complete'")
        db.execute("INSERT INTO verifications VALUES (?,?)", (n, "wm"))
        db.commit()
    db.execute(
        "INSERT INTO results SELECT sequence,listing_key,input_hash,'[]',0,? "
        "FROM inputs",
        (USAGE,),
    )
    db.execute("INSERT INTO result_origins SELECT sequence,'v2' FROM inputs")
    db.commit()
    stage_tranche(db, source, "m", "p", "s", "wm", limit=10000, extend=True, wave=True)
    return db, source


def test_ten_thousand_staged_as_ten_batches_and_gate():
    db, _ = setup_wave()
    assert (
        db.execute("SELECT COUNT(*) FROM batches WHERE start_sequence>8000").fetchone()[
            0
        ]
        == 10
    )
    assert (
        db.execute("SELECT MAX(end_sequence-start_sequence+1) FROM batches").fetchone()[
            0
        ]
        == 1000
    )
    db.execute("UPDATE batches SET status='complete'")
    db.execute(
        "INSERT INTO results SELECT sequence,listing_key,input_hash,'[]',0,? "
        "FROM inputs "
        "WHERE sequence>8000",
        (USAGE,),
    )
    db.execute(
        "INSERT INTO result_origins SELECT sequence,'v2' FROM inputs "
        "WHERE sequence>8000"
    )
    db.execute("INSERT INTO verifications VALUES (18000,'wm')")
    assert verify_stored_wave(db, 8001, 18000, "wm")["rows"] == 10000
    assert next_wave(18000) == 8000


def test_wave_fail_closed_for_missing_results_and_changed_source():
    db, source = setup_wave()
    with pytest.raises(ValueError):
        verify_stored_wave(db, 8001, 18000, "wm")
    db.execute("UPDATE batches SET status='complete'")
    db.execute("INSERT INTO verifications VALUES (18000,'wm')")
    with pytest.raises(ValueError, match="source changed"):
        stage_tranche(
            db, [("0", "changed"), *source[1:]], "m", "p", "s", "wm", extend=True
        )


def test_pricing_requires_complete_usage():
    assert estimated_cost(json.loads(USAGE)) == Decimal("0.00155")
    with pytest.raises(ValueError):
        estimated_cost({})


def test_high_cost_first_wave_is_not_forgotten_after_cheap_wave():
    db, _ = setup_wave()
    db.execute("UPDATE batches SET status='complete'")
    expensive = json.dumps(
        dict(
            input_tokens=4000,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
    )
    db.execute(
        "INSERT INTO results SELECT sequence,listing_key,input_hash,'[]',0,? "
        "FROM inputs "
        "WHERE sequence>8000",
        (expensive,),
    )
    db.execute(
        "INSERT INTO result_origins SELECT sequence,'v2' FROM inputs "
        "WHERE sequence>8000"
    )
    source = [(str(i), "synthetic") for i in range(26000)]
    db.execute("INSERT INTO verifications VALUES (18000,'wm')")
    db.commit()
    stage_tranche(db, source, "m", "p", "s", "wm", limit=8000, extend=True, wave=True)
    db.execute("UPDATE batches SET status='complete'")
    cheap = json.dumps(
        dict(
            input_tokens=100,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
    )
    db.execute(
        "INSERT INTO results SELECT sequence,listing_key,input_hash,'[]',0,? "
        "FROM inputs "
        "WHERE sequence>18000",
        (cheap,),
    )
    db.execute(
        "INSERT INTO result_origins SELECT sequence,'v2' FROM inputs "
        "WHERE sequence>18000"
    )
    db.execute("INSERT INTO verifications VALUES (26000,'wm')")
    with pytest.raises(ValueError, match="projected budget exceeded"):
        verify_stored_wave(db, 18001, 26000, "wm")


def test_console_delta_requires_same_scope_non_decreasing_totals():
    assert console_delta(Decimal("15.50"), Decimal("24.25")) == Decimal("8.75")
    with pytest.raises(ValueError, match="below baseline"):
        console_delta(Decimal("15.50"), Decimal("8.75"))
    with pytest.raises(ValueError):
        console_delta(Decimal("NaN"), Decimal("1"))


def test_console_baseline_is_persisted_and_immutable():
    db = sqlite3.connect(":memory:")
    initialize_batch_store(db)
    with pytest.raises(ValueError, match="required"):
        record_console_baseline(db, 8000, None)
    with pytest.raises(ValueError, match="required"):
        record_console_baseline(db, 18000, Decimal("12"))
    assert record_console_baseline(db, 8000, Decimal("12.34")) == Decimal("12.34")
    assert record_console_baseline(db, 18000, None) == Decimal("12.34")
    with pytest.raises(ValueError, match="changed"):
        record_console_baseline(db, 18000, Decimal("13"))


def test_runner_stops_before_provider_when_previous_wave_incomplete(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    from evals import run
    from scripts import extract_enrichment_v2_batch as runner

    private = tmp_path / "enrichment"
    directory = private / "full"
    directory.mkdir(parents=True, mode=0o700)
    (private / "usage-dev-v2.json").write_text(
        json.dumps({"contract_hashes": {"test": "hash"}})
    )
    source_db, _ = setup_wave()
    path = directory / "active-facets-v2.sqlite3"
    target = sqlite3.connect(path)
    source_db.backup(target)
    target.close()
    source_db.close()
    path.chmod(0o600)
    monkeypatch.setattr(runner, "PRIVATE", private)
    monkeypatch.setattr(runner, "verify_freeze", lambda: None)
    monkeypatch.setattr(runner, "contract_hashes", lambda: {"test": "hash"})
    monkeypatch.setattr(runner, "sonnet_fallback_selected", lambda _: True)
    monkeypatch.setattr(runner, "load_v1_reuse", lambda _: {})
    monkeypatch.setattr(run, "_local_setting", lambda _: "fake")
    monkeypatch.setattr(runner, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(runner, "active_watermark", lambda _: "wm")
    monkeypatch.setattr(
        runner.consent, "start_paid_run", lambda: SimpleNamespace(calls_made=0)
    )
    monkeypatch.setattr(runner.consent, "abort_paid_run", lambda _: None)
    calls = []
    monkeypatch.setattr(runner, "request_http", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(
        runner.sys,
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
            "--continue-after-approval",
            "--wave-size",
            "8000",
        ],
    )
    assert runner.main() == 1
    assert calls == []
    assert '"status": "stopped"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure", ["status", "missing", "misses", "watermark", "hash", "cost"]
)
def test_stored_wave_rejects_failures(failure):
    db, _ = setup_wave()
    db.execute("UPDATE batches SET status='complete'")
    db.execute(
        "INSERT INTO results SELECT sequence,listing_key,input_hash,'[]',0,? "
        "FROM inputs "
        "WHERE sequence>8000",
        (USAGE,),
    )
    db.execute(
        "INSERT INTO result_origins SELECT sequence,'v2' FROM inputs "
        "WHERE sequence>8000"
    )
    db.execute("INSERT INTO verifications VALUES (18000,'wm')")
    if failure == "status":
        db.execute("UPDATE batches SET status='uncertain' WHERE start_sequence=8001")
    elif failure == "missing":
        db.execute("DELETE FROM results WHERE sequence=8001")
    elif failure == "misses":
        db.execute(
            "UPDATE results SET diagnostic_count=1 WHERE sequence BETWEEN 8001 AND 8201"
        )
    elif failure == "hash":
        db.execute("UPDATE results SET input_hash='changed' WHERE sequence=8001")
    elif failure == "cost":
        costly = json.dumps(
            dict(
                input_tokens=1000000,
                output_tokens=1000000,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            )
        )
        db.execute("UPDATE results SET usage=? WHERE sequence=8001", (costly,))
    with pytest.raises(ValueError):
        verify_stored_wave(
            db, 8001, 18000, "changed" if failure == "watermark" else "wm"
        )
