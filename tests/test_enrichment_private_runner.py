"""Exercise the private aggregate runner using only temporary invented files."""

import json

import pytest
from scripts.score_enrichment_private import score_files


def write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_runner_returns_counts_only_and_requires_complete_split(tmp_path):
    cases = [
        {"id": f"dev-{i}", "split": "dev", "text": "3 bedrooms"} for i in range(100)
    ]
    labels = [{"id": case["id"], "annotations": []} for case in cases]
    sample = {"version": 1, "dataset_id": "invented", "cases": cases}
    label_data = {"version": 1, "dataset_id": "invented", "labels": labels}
    write(tmp_path / "sample.json", sample)
    write(tmp_path / "labels.json", label_data)
    write(tmp_path / "predictions-dev.json", label_data)
    result = score_files(tmp_path, "dev")["counts"]
    assert result["overall"] == {
        "expected": 0,
        "predicted": 0,
        "correct": 0,
        "precision": None,
        "recall": None,
        "f1": None,
    }
    assert "3 bedrooms" not in json.dumps(result)
    label_data["labels"].pop()
    write(tmp_path / "predictions-dev.json", label_data)
    with pytest.raises(ValueError, match="incomplete"):
        score_files(tmp_path, "dev")


def test_runner_refuses_a_symlink_to_outside_private_root(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    outside = tmp_path / "outside.json"
    write(outside, {})
    (private / "sample.json").symlink_to(outside)
    with pytest.raises(ValueError, match="invalid private file"):
        score_files(private, "dev")


def test_jsonl_sample_and_private_manifest_score_together(tmp_path):
    from idx_agent.enrichment.sample_builder import build_sample, write_private

    rows = [
        {
            "L_ListingID": str(i),
            "L_Type_": "house",
            "L_Remarks": "Invented home with a garden. " * 10,
        }
        for i in range(260)
    ]
    pages = [rows[i : i + 50] for i in range(0, len(rows), 50)]
    sample, manifest = build_sample(lambda: iter(pages))
    write_private(tmp_path, sample, manifest)
    labels = {
        "version": 1,
        "dataset_id": manifest["dataset_id"],
        "labels": [
            {"id": row["key"], "annotations": []}
            for row in sample
            if manifest["splits"][row["key"]] == "dev"
        ],
    }
    write(tmp_path / "labels.json", labels)
    write(tmp_path / "predictions-dev.json", labels)
    result = score_files(tmp_path, "dev")["counts"]
    assert result["overall"]["expected"] == 0
    assert result["overall"]["f1"] is None
    assert "Invented home" not in json.dumps(result)


def test_scoring_run_id_uses_separate_private_predictions(tmp_path):
    cases = [{"id": str(i), "split": "dev", "text": "invented"} for i in range(100)]
    sample = {"version": 1, "dataset_id": "invented", "cases": cases}
    labels = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": case["id"], "annotations": []} for case in cases],
    }
    write(tmp_path / "sample.json", sample)
    write(tmp_path / "labels.json", labels)
    write(tmp_path / "predictions-dev-dev2.json", labels)
    assert score_files(tmp_path, "dev", "dev2")["counts"]["overall"]["expected"] == 0
    with pytest.raises(ValueError, match="run identifier"):
        score_files(tmp_path, "dev", "../other")
