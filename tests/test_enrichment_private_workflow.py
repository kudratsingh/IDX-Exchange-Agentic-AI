"""Exercise sampling and aggregate scoring together on invented remarks."""

import json
from collections import Counter

from scripts.score_enrichment_private import score_files

from idx_agent.enrichment.stratified_plan import CandidateGroup, stratified_plan


def test_synthetic_stratified_dev_scoring_workflow(tmp_path):
    population = [
        CandidateGroup(f"synthetic-{i}", "house" if i < 240 else "condo")
        for i in range(300)
    ]
    assignment = stratified_plan(population, "fixed-seed")
    assert Counter(assignment.values()) == {"dev": 100, "test": 150}
    cases = [
        {"id": group, "split": split, "text": "3 bedrooms"}
        for group, split in sorted(assignment.items())
    ]
    sample = {"version": 1, "dataset_id": "invented", "cases": cases}
    annotation = {
        "kind": "numeric",
        "field": "bedrooms",
        "value": 3,
        "start": 0,
        "end": 10,
        "quote": "3 bedrooms",
    }
    labels = [
        {"id": case["id"], "annotations": [dict(annotation)]}
        for case in cases
        if case["split"] == "dev"
    ]
    gold = {"version": 1, "dataset_id": "invented", "labels": labels}
    predicted = json.loads(json.dumps(gold))
    predicted["labels"][0]["annotations"][0]["value"] = 4
    for name, obj in (
        ("sample.json", sample),
        ("labels.json", gold),
        ("predictions-dev.json", predicted),
    ):
        (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")
    report = score_files(tmp_path, "dev")["counts"]
    numeric = report["numeric.bedrooms"]
    assert (numeric["expected"], numeric["predicted"], numeric["correct"]) == (
        100,
        100,
        99,
    )
    assert numeric["precision"] == numeric["recall"] == numeric["f1"] == 0.99
    assert "3 bedrooms" not in json.dumps(report)


def test_macro_reports_supported_classes_only(tmp_path):
    population = [CandidateGroup(f"synthetic-{i}", "house") for i in range(250)]
    assignment = stratified_plan(population, "fixed-seed")
    cases = [
        {"id": key, "split": split, "text": "3 bedrooms"}
        for key, split in assignment.items()
    ]
    sample = {"version": 1, "dataset_id": "invented", "cases": cases}
    annotation = {
        "kind": "numeric",
        "field": "bedrooms",
        "value": 3,
        "start": 0,
        "end": 10,
        "quote": "3 bedrooms",
    }
    rows = [
        {"id": case["id"], "annotations": [annotation]}
        for case in cases
        if case["split"] == "dev"
    ]
    labels = {"version": 1, "dataset_id": "invented", "labels": rows}
    for name, value in (
        ("sample.json", sample),
        ("labels.json", labels),
        ("predictions-dev.json", labels),
    ):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    result = score_files(tmp_path, "dev")
    assert result["macro_supported_classes"] == 1
    assert result["macro_f1"] == 1
    assert result["counts"]["numeric.bathrooms"]["f1"] is None


def test_disagreements_report_contains_counts_only(tmp_path):
    cases = [{"id": str(i), "split": "dev", "text": "3 bedrooms"} for i in range(100)]
    annotation = {
        "kind": "numeric",
        "field": "bedrooms",
        "value": 3,
        "start": 0,
        "end": 10,
        "quote": "3 bedrooms",
    }
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": case["id"], "annotations": [annotation]} for case in cases],
    }
    predicted = json.loads(json.dumps(gold))
    predicted["labels"][0]["annotations"][0]["value"] = 4
    for name, value in (
        ("sample.json", {"version": 1, "dataset_id": "invented", "cases": cases}),
        ("labels.json", gold),
        ("predictions-dev.json", predicted),
    ):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    result = score_files(tmp_path, "dev")
    assert result["worst_disagreements"] == [
        {
            "facet": "numeric.bedrooms",
            "false_positive_spans": 1,
            "false_negative_spans": 1,
        }
    ]
    assert "3 bedrooms" not in json.dumps(result)
