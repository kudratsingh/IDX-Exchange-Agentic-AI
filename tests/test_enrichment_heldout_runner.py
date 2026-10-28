"""Held-out boundary checks use invented remarks and no provider calls."""

import pytest
from scripts import extract_enrichment_test as heldout


def test_recorded_freeze_matches_real_public_code():
    heldout.verify_freeze()


def test_changed_frozen_file_refuses_run(tmp_path, monkeypatch):
    (tmp_path / "frozen").write_text("different", encoding="utf-8")
    monkeypatch.setattr(heldout, "ROOT", tmp_path)
    monkeypatch.setattr(heldout, "HASHES", {"frozen": "0" * 64})
    with pytest.raises(ValueError, match="frozen file changed"):
        heldout.verify_freeze()


def test_heldout_150_cases_keep_ids_and_aggregate_usage():
    cases = [(str(i), "invented remark") for i in range(150)]
    checkpoints = []
    usage = {
        "input_tokens": 2,
        "output_tokens": 3,
        "cache_creation_input_tokens": 4,
        "cache_read_input_tokens": 5,
    }
    response = {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": []},
            }
        ]
    }
    result, totals = heldout.run(
        "synthetic",
        cases,
        lambda _: (response, usage, b"{}"),
        lambda i, raw, u: checkpoints.append(i),
        lambda *_: pytest.fail("unexpected diagnostic"),
    )
    assert [row["id"] for row in result["labels"]] == [key for key, _ in cases]
    assert checkpoints == list(range(1, 151))
    assert totals["total_input_tokens"] == 1650
    assert totals["uncached_input_tokens_per_remark"] == 2
    assert totals["output_tokens"] == 450


def test_wrong_split_size_refused_before_invoke():
    with pytest.raises(ValueError, match="invalid held-out sample"):
        heldout.run(
            "synthetic",
            [("1", "invented")],
            lambda _: pytest.fail("called"),
            None,
            None,
        )
