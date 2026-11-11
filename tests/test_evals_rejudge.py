"""The offline description-routing re-judgment (evals/rejudge.py). Synthetic report
entries only, in the shape the runner saves; no model, key or network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evals import rejudge
from evals import run as runner

FIX = "29888ee"


def _cases():
    cases, errors = runner.load_cases(runner.DEFAULT_CASES_DIR)
    assert errors == []
    return [c for c in cases if c.category == rejudge.CATEGORY]


def _fail(case_id: str, wrong: str, keys=("city", "features"), name="search_listings"):
    return {
        "id": case_id,
        "category": "description_routing",
        "result": "fail",
        "detail": f"step 1 {name}: differs on {wrong}",
        "calls": [{"name": name, "argument_keys": list(keys)}],
        "run": 1,
    }


VERIFIED = [
    _fail("description-local-002", "{'features': ('pool',)}"),
    _fail("description-local-003", "{'features': ('pool', 'solar')}"),
    _fail("description-local-004", "{'features': ('garage', 'pool')}"),
]


@pytest.mark.parametrize("entry", VERIFIED, ids=lambda e: e["id"])
def test_a_tuple_versus_list_failure_verifies(entry):
    case = next(c for c in _cases() if c.id == entry["id"])
    ok, reasons = rejudge.judge_failure(case, entry)
    assert ok, reasons
    assert any("tuple against list" in r for r in reasons)


@pytest.mark.parametrize(
    "entry",
    [
        _fail("description-local-003", "{'features': ('pool',)}"),  # solar missing
        _fail("description-local-002", "{'features': ('pool',), 'city': 'Glendale'}"),
        _fail("description-local-002", "{'pool': True}"),
        _fail("description-local-002", "{'features': ('pool',)}", keys=("features",)),
        _fail("description-local-002", "{'features': ('pool',)}", name="recommend"),
        _fail("description-local-002", "{'features': ['pool']}"),  # not a raw miss
        {**_fail("description-local-002", "x"), "detail": "route ['health']"},
    ],
)
def test_anything_the_record_does_not_prove_stays_unverified(entry):
    case = next(c for c in _cases() if c.id == entry["id"])
    ok, reasons = rejudge.judge_failure(case, entry)
    assert not ok, reasons


def test_counts_keep_raw_and_corrected_apart():
    passed = {"id": "description-local-001", "category": "description_routing"}
    report = {
        "cases": [
            {**passed, "result": "pass", "run": 1},
            *VERIFIED,
            _fail("description-local-003", "{'features': ('pool',)}"),
            {"id": "relay-local-001", "category": "relay", "result": "pass"},
        ]
    }
    rows, counts = rejudge.rejudge(report, _cases())
    assert counts == {
        "attempts": 5,
        "raw_pass": 1,
        "raw_fail": 4,
        "verified_failures": 3,
        "corrected_pass": 4,
        "unverified": 1,
    }
    assert [r["corrected"] for r in rows] == ["pass"] * 4 + ["unverified"]


def test_the_cli_refuses_a_wrong_hash_and_never_overwrites(tmp_path: Path, capsys):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"cases": []}), encoding="utf-8")
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    out = tmp_path / "out.json"
    args = ["--report", str(report), "--fix-commit", FIX, "--out"]
    assert rejudge.main([*args, str(out), "--sha256", "0" * 64]) == 2
    assert "refused" in capsys.readouterr().out and not out.exists()
    assert rejudge.main([*args, str(report), "--sha256", digest]) == 2
    assert json.loads(report.read_text()) == {"cases": []}  # untouched
    out.write_text("{}", encoding="utf-8")
    assert rejudge.main([*args, str(out), "--sha256", digest]) == 2
    assert out.read_text() == "{}"
