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
    report = score_files(tmp_path, "dev")
    numeric = report["numeric.bedrooms"]
    assert (numeric["expected"], numeric["predicted"], numeric["correct"]) == (
        100,
        100,
        99,
    )
    assert numeric["precision"] == numeric["recall"] == numeric["f1"] == 0.99
    assert "3 bedrooms" not in json.dumps(report)
