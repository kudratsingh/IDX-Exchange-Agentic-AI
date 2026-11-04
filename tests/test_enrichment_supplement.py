"""WO-032 supplement-wave preconditions and the key-free dry run.

Synthetic SQLite results table and invented remarks only; no key, database or network.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.request

import pytest
from scripts import extract_enrichment_supplement as script

from idx_agent.enrichment.batch_v2 import initialize_batch_store
from idx_agent.enrichment.full_batch import records
from idx_agent.enrichment.source_check import results_digest
from idx_agent.enrichment.supplement import (
    MAX_CALLS,
    PreconditionFailed,
    never_extracted_keys,
    planned_units,
    run_preconditions,
)

WATERMARK = "2026-09-18 06:58:44"
CONTRACT = {"model": "model-x", "prompt_hash": "p" * 64, "schema_hash": "s" * 64}
STORED = {"101": "Invented remark one.", "102": "Invented remark two."}
SUPPLEMENT = ["201", "202", "203"]


def build_table(db: sqlite3.Connection) -> str:
    """A finished two-row full run; returns its approved digest."""
    initialize_batch_store(db)
    db.executemany(
        "INSERT INTO settings VALUES (?,?)",
        [*CONTRACT.items(), ("version", "v2"), ("watermark", WATERMARK)],
    )
    for sequence, (key, remark) in enumerate(STORED.items(), 1):
        ((_, text),) = records([([{"L_ListingID": key, "L_Remarks": remark}], key)])
        digest = hashlib.sha256(text.encode()).hexdigest()
        db.execute("INSERT INTO inputs VALUES (?,?,?,?)", (sequence, key, digest, text))
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?,?)",
            (sequence, key, digest, "[]", 0, json.dumps({"output_tokens": 5})),
        )
        db.execute("INSERT INTO result_origins VALUES (?, 'v2')", (sequence,))
    db.execute("INSERT INTO batches VALUES (1, 1, 2, 'complete', 'msgbatch_x')")
    db.execute("INSERT INTO verifications VALUES (2, ?)", (WATERMARK,))
    db.commit()
    return results_digest(db)


def inventory(keys=SUPPLEMENT, extra=()):
    lines = [json.dumps({"listing_key": k, "class": "unchanged"}) for k in STORED]
    lines += [json.dumps({"listing_key": k, "class": "never_extracted"}) for k in keys]
    return [*lines, *extra]


def pages(supplement_remarks, stored=STORED):
    rows = [{"L_ListingID": k, "L_Remarks": v} for k, v in stored.items()]
    rows += [
        {"L_ListingID": k, "L_Remarks": supplement_remarks.get(k)} for k in SUPPLEMENT
    ]
    rows.sort(key=lambda row: row["L_ListingID"])
    return [(rows, rows[-1]["L_ListingID"])]


def run(db, digest, remarks, **overrides):
    called = {"pages": 0}
    source = overrides.pop("source", None)

    def read_pages():
        called["pages"] += 1
        return source or pages(remarks)

    arguments = dict(
        freeze_checks=[("freeze", lambda: None)],
        db=db,
        contract=CONTRACT,
        inventory_lines=inventory(),
        watermark=lambda: WATERMARK,
        pages=read_pages,
        expected_ids=len(SUPPLEMENT),
        table_checks={"rows": 2, "watermark": WATERMARK, "digest": digest},
    )
    arguments.update(overrides)
    return run_preconditions(**arguments), called


@pytest.fixture
def table():
    db = sqlite3.connect(":memory:")
    return db, build_table(db)


TEXT = {k: f"Invented supplement remark {k} with a garage." for k in SUPPLEMENT}


def test_ready_when_every_precondition_holds(table):
    db, digest = table
    summary, _ = run(db, digest, TEXT)
    assert summary["status"] == "ready"
    assert all(p["result"] == "pass" for p in summary["preconditions"])
    counts = summary["counts"]
    assert counts["eligible_remarks"] == 3
    assert counts["planned_consent_units"] == 4  # three messages, one batch creation
    assert counts["original_source_matches"] is True


def test_listings_without_remarks_leave_nothing_to_extract(table):
    """The local data's case: every never_extracted ID has a NULL or blank remark."""
    db, digest = table
    summary, _ = run(db, digest, {"201": None, "202": "   ", "203": None})
    assert summary["status"] == "refused"
    assert summary["reason"] == "no_eligible_remarks"
    counts = summary["counts"]
    assert counts["supplement_remark_null"] == 2
    assert counts["supplement_remark_blank"] == 1
    assert counts["eligible_remarks"] == 0
    assert "planned_consent_units" not in counts


def test_a_freeze_hash_mismatch_stops_before_any_read(table):
    db, digest = table

    def changed():
        raise ValueError("frozen file changed")

    summary, called = run(db, digest, TEXT, freeze_checks=[("freeze", changed)])
    assert summary["reason"] == "freeze_hash_mismatch"
    assert called["pages"] == 0


@pytest.mark.parametrize(
    "tamper, reason",
    [
        (
            "UPDATE settings SET value='model-y' WHERE name='model'",
            "full_run_contract_mismatch",
        ),
        (
            "UPDATE settings SET value='2030-01-01 00:00:00' WHERE name='watermark'",
            "full_run_contract_mismatch",
        ),
        (
            'UPDATE results SET facets=\'[{"group":"g"}]\' WHERE sequence=1',
            "results_digest_mismatch",
        ),
        (
            "UPDATE result_origins SET extractor='v1' WHERE sequence=2",
            "results_digest_mismatch",
        ),
        (
            "UPDATE verifications SET watermark='2030-01-01 00:00:00'",
            "verification_watermark_mismatch",
        ),
        ("UPDATE batches SET status='submitted'", "batches_not_complete"),
        ("DELETE FROM result_origins WHERE sequence=2", "results_row_count_mismatch"),
    ],
)
def test_a_modified_full_run_table_is_refused(table, tamper, reason):
    db, digest = table
    db.execute(tamper)
    summary, called = run(db, digest, TEXT)
    assert summary["reason"] == reason
    assert called["pages"] == 0


def test_an_appended_row_is_refused_as_a_source_mismatch(table):
    db, digest = table
    db.execute("INSERT INTO inputs VALUES (3,'201','h','t')")
    db.execute("INSERT INTO results VALUES (3,'201','h','[]',0,'{}')")
    db.execute("INSERT INTO result_origins VALUES (3,'v2')")
    summary, _ = run(db, digest, TEXT)
    assert summary["reason"] == "results_row_count_mismatch"


def test_the_input_set_count_must_match_the_preflight(table):
    db, digest = table
    summary, _ = run(db, digest, TEXT, inventory_lines=inventory(SUPPLEMENT[:2]))
    assert summary["reason"] == "input_set_count_mismatch"


def test_an_input_already_extracted_is_refused(table):
    db, digest = table
    lines = inventory(["101", "202", "203"])
    lines = [line for line in lines if '"101", "class": "unchanged"' not in line]
    summary, _ = run(db, digest, TEXT, inventory_lines=lines)
    assert summary["reason"] == "input_set_overlaps"


@pytest.mark.parametrize(
    "lines",
    [
        ['{"listing_key": "20x", "class": "never_extracted"}'],
        ['{"listing_key": "201", "class": "invented"}'],
        ['{"listing_key": "201", "class": "never_extracted"}'] * 2,
    ],
)
def test_a_malformed_inventory_is_refused(lines):
    with pytest.raises(PreconditionFailed, match="inventory_malformed"):
        never_extracted_keys(lines)


def test_a_watermark_change_during_the_scan_ends_the_run(table):
    db, digest = table
    marks = iter([WATERMARK, "2026-09-19 00:00:00"])
    summary, _ = run(db, digest, TEXT, watermark=lambda: next(marks))
    assert summary["reason"] == "watermark_changed"
    assert summary["preconditions"][-1]["name"] == "watermark_unchanged_after_scan"


def test_a_changed_original_remark_is_a_source_mismatch(table):
    db, digest = table
    edited = dict(STORED, **{"102": "Edited invented remark."})
    summary, _ = run(db, digest, TEXT, source=pages(TEXT, edited))
    assert summary["reason"] == "source_mismatch"


def test_a_supplement_listing_missing_from_the_source_is_a_source_mismatch(table):
    db, digest = table
    rows = [r for r in pages(TEXT)[0][0] if r["L_ListingID"] != "203"]
    summary, _ = run(db, digest, TEXT, source=[(rows, rows[-1]["L_ListingID"])])
    assert summary["reason"] == "source_mismatch"


def _source(rows):
    rows.sort(key=lambda row: row["L_ListingID"])  # stable: newest stays first
    return [(rows, rows[-1]["L_ListingID"])]


def test_a_duplicate_row_cannot_hide_a_missing_supplement_listing(table):
    """Presence counts distinct IDs: 203 missing and 202 twice is still a mismatch."""
    db, digest = table
    rows = [{"L_ListingID": k, "L_Remarks": v} for k, v in STORED.items()]
    rows += [
        {"L_ListingID": "201", "L_Remarks": TEXT["201"]},
        {"L_ListingID": "202", "L_Remarks": TEXT["202"]},
        {"L_ListingID": "202", "L_Remarks": "Older invented remark."},
    ]
    summary, _ = run(db, digest, TEXT, source=_source(rows))
    assert summary["status"] == "refused"
    assert summary["reason"] == "source_mismatch"
    assert summary["preconditions"][-1]["name"] == "input_set_active_in_source"
    assert summary["counts"]["supplement_ids_in_source"] == 2
    assert summary["counts"]["supplement_rows_in_source"] == 3


def test_remark_counts_describe_the_row_the_reader_uses(table):
    """An older row's remark is not counted; only the newest row per ID is."""
    db, digest = table
    rows = [{"L_ListingID": k, "L_Remarks": v} for k, v in STORED.items()]
    rows += [
        {"L_ListingID": "201", "L_Remarks": None},
        {"L_ListingID": "201", "L_Remarks": "Older invented remark."},
        {"L_ListingID": "202", "L_Remarks": None},
        {"L_ListingID": "203", "L_Remarks": None},
    ]
    summary, _ = run(db, digest, TEXT, source=_source(rows))
    assert summary["reason"] == "no_eligible_remarks"
    counts = summary["counts"]
    assert counts["supplement_ids_in_source"] == 3
    assert counts["supplement_remark_null"] == 3
    assert counts["supplement_remark_text"] == 0
    assert counts["eligible_remarks"] == 0


def test_a_supplement_listing_seen_twice_out_of_order_is_a_source_mismatch(table):
    db, digest = table
    rows = pages(TEXT)[0][0]
    rows.append({"L_ListingID": "201", "L_Remarks": "Out-of-order invented remark."})
    summary, _ = run(db, digest, TEXT, source=[(rows, rows[-1]["L_ListingID"])])
    assert summary["reason"] == "source_mismatch"
    assert summary["preconditions"][-1]["name"] == "input_set_active_in_source"


def test_the_call_ceiling_is_enforced_in_code(table):
    db, digest = table
    assert MAX_CALLS == 400
    assert planned_units(399) == 400 and planned_units(400) == 401
    summary, _ = run(db, digest, TEXT, ceiling=3)
    assert summary["reason"] == "ceiling_exceeded"


# --- The script: key-free, read-only, no provider client ---


def private_inputs(tmp_path, remarks):
    data = tmp_path / "enrichment"
    (data / "full").mkdir(parents=True, mode=0o700)
    (data / "refresh").mkdir(mode=0o700)
    table = data / "full" / "active-facets-v2.sqlite3"
    db = sqlite3.connect(table)
    digest = build_table(db)
    db.close()
    table.chmod(0o600)
    inv = data / "refresh" / "preflight-inventory.jsonl"
    inv.write_text("\n".join(inventory()) + "\n")
    inv.chmod(0o600)
    return data, table, digest


@pytest.fixture
def offline(monkeypatch):
    """Any provider client, key read or paid-run start fails the test."""
    from types import SimpleNamespace

    from evals import run as evals_run

    def forbidden(*_a, **_k):
        raise AssertionError("provider path touched in a dry run")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request, "Request", forbidden)
    monkeypatch.setattr(script.full_run, "request_http", forbidden)
    monkeypatch.setattr(script.full_run.consent, "start_paid_run", forbidden)
    monkeypatch.setattr(script.full_run.consent, "spend_paid_call", forbidden)
    monkeypatch.setattr(evals_run, "_local_setting", forbidden)
    monkeypatch.setattr(
        script.full_run, "connect", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(script.full_run, "active_watermark", lambda _: WATERMARK)
    monkeypatch.setattr(
        script,
        "contract_checks",
        lambda _data: [("freeze", lambda: None)],
    )
    return monkeypatch


def configure(monkeypatch, digest, remarks):
    from idx_agent.enrichment import supplement

    monkeypatch.setattr(script.full_run, "iter_pages", lambda _: pages(remarks))
    monkeypatch.setattr(supplement, "EXPECTED_SUPPLEMENT_IDS", len(SUPPLEMENT))
    original = supplement.check_results_table

    def check(db, contract, **_):
        return original(db, CONTRACT, rows=2, watermark=WATERMARK, digest=digest)

    monkeypatch.setattr(supplement, "check_results_table", check)
    monkeypatch.setattr(
        script,
        "run_preconditions",
        lambda **kw: supplement.run_preconditions(
            **dict(kw, expected_ids=len(SUPPLEMENT))
        ),
    )


def test_dry_run_is_key_free_and_read_only(tmp_path, offline, capsys):
    data, table, digest = private_inputs(tmp_path, TEXT)
    configure(offline, digest, TEXT)
    before = table.read_bytes()
    assert script.main(["--dry-run", "--data-root", str(data)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ready" and out["mode"] == "dry_run"
    assert out["counts"]["planned_consent_units"] == 4
    assert table.read_bytes() == before
    assert sorted(p.name for p in (data / "full").iterdir()) == [table.name]


def test_dry_run_on_remarkless_listings_refuses_and_prints_counts_only(
    tmp_path, offline, capsys
):
    remarks = dict.fromkeys(SUPPLEMENT)
    data, _, digest = private_inputs(tmp_path, remarks)
    configure(offline, digest, remarks)
    assert script.main(["--dry-run", "--data-root", str(data)]) == 1
    printed = capsys.readouterr().out
    out = json.loads(printed)
    assert out["reason"] == "no_eligible_remarks"
    assert out["counts"]["supplement_remark_null"] == 3
    for key in (*STORED, *SUPPLEMENT):
        assert f'"{key}"' not in printed


def test_without_dry_run_the_script_refuses_before_reading_anything(
    tmp_path, offline, capsys
):
    assert script.main(["--data-root", str(tmp_path / "absent")]) == 2
    assert "paid_path_not_built" in capsys.readouterr().out


def test_a_public_private_input_is_refused(tmp_path, offline, capsys):
    data, table, digest = private_inputs(tmp_path, TEXT)
    configure(offline, digest, TEXT)
    table.chmod(0o644)
    assert script.main(["--dry-run", "--data-root", str(data)]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "check_failed"
