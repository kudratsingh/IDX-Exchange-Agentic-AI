"""Score invented private-label shapes without exposing their text."""

import copy

import pytest

from idx_agent.enrichment.private_scoring import Counts, score_private_labels


def example():
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [
            {"id": "dev-1", "split": "dev", "text": "3 bedrooms and pool"},
            {"id": "dev-2", "split": "dev", "text": "Nothing."},
            {"id": "test-1", "split": "test", "text": "A separate case."},
        ],
    }
    annotations = [
        {
            "kind": "numeric",
            "field": "bedrooms",
            "value": 3,
            "start": 0,
            "end": 10,
            "quote": "3 bedrooms",
        },
        {
            "kind": "facet",
            "group": "exterior_lot",
            "value": "pool",
            "polarity": "affirmed",
            "temporality": "current",
            "start": 15,
            "end": 19,
            "quote": "pool",
        },
    ]
    labels = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {"id": "dev-1", "annotations": annotations},
            {"id": "dev-2", "annotations": []},
        ],
    }
    return sample, labels


def test_aggregate_counts_and_wrong_value():
    sample, gold = example()
    pred = copy.deepcopy(gold)
    pred["labels"][0]["annotations"][0]["value"] = 4
    result = score_private_labels(sample, gold, pred, "dev")
    assert result["overall"] == Counts(2, 2, 1)
    assert result["numeric.bedrooms"] == Counts(1, 1, 0)
    assert result["facet.exterior_lot.pool"] == Counts(1, 1, 1)
    assert result["structured_numeric"].f1 == 0
    assert Counts(0, 0, 0).f1 is None
    assert Counts(0, 1, 0).precision == 0
    assert Counts(0, 1, 0).recall is None
    assert "bedrooms and pool" not in repr(result)


def test_incomplete_duplicate_and_wrong_dataset_are_rejected():
    sample, gold = example()
    incomplete = copy.deepcopy(gold)
    incomplete["labels"].pop()
    duplicate = copy.deepcopy(gold)
    duplicate["labels"].append(duplicate["labels"][0])
    wrong = dict(gold, dataset_id="different")
    for bad in (incomplete, duplicate, wrong):
        with pytest.raises(ValueError):
            score_private_labels(sample, gold, bad, "dev")


def test_invalid_span_and_duplicate_annotation_are_rejected():
    sample, gold = example()
    bad_span = copy.deepcopy(gold)
    bad_span["labels"][0]["annotations"][0]["start"] = 1
    duplicate = copy.deepcopy(gold)
    duplicate["labels"][0]["annotations"].append(
        duplicate["labels"][0]["annotations"][0]
    )
    for bad in (bad_span, duplicate):
        with pytest.raises(ValueError):
            score_private_labels(sample, gold, bad, "dev")


def test_polarity_mismatch_counts_false_positive_and_false_negative():
    sample, gold = example()
    predicted = copy.deepcopy(gold)
    predicted["labels"][0]["annotations"][1]["polarity"] = "negated"
    result = score_private_labels(sample, gold, predicted, "dev")
    assert result["polarity.affirmed"] == Counts(1, 0, 0)
    assert result["polarity.negated"] == Counts(0, 1, 0)
    assert result["polarity.uncertain"] == Counts(0, 0, 0)
    assert result["overall"] == Counts(2, 2, 1)


def test_dev_scoring_does_not_validate_held_out_annotations():
    sample, gold = example()
    gold["labels"].append({"id": "test-1", "annotations": [{"kind": "invalid"}]})
    result = score_private_labels(sample, gold, gold, "dev")
    assert result["overall"].correct == 2


def test_facet_overlap_counts_one_per_case_and_numeric_remains_exact():
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [{"id": "a", "split": "dev", "text": "large sunny patio; 3 beds"}],
    }
    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {
                "id": "a",
                "annotations": [
                    {
                        "kind": "facet",
                        "group": "exterior_lot",
                        "value": "patio",
                        "polarity": "affirmed",
                        "temporality": "current",
                        "start": 0,
                        "end": 17,
                        "quote": "large sunny patio",
                    },
                    {
                        "kind": "numeric",
                        "field": "bedrooms",
                        "value": 3,
                        "start": 19,
                        "end": 25,
                        "quote": "3 beds",
                    },
                ],
            }
        ],
    }
    predictions = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [
            {
                "id": "a",
                "annotations": [
                    {
                        "kind": "facet",
                        "group": "exterior_lot",
                        "value": "patio",
                        "polarity": "uncertain",
                        "temporality": "unspecified",
                        "start": 12,
                        "end": 17,
                        "quote": "patio",
                    },
                    {
                        "kind": "facet",
                        "group": "exterior_lot",
                        "value": "patio",
                        "polarity": "affirmed",
                        "temporality": "current",
                        "start": 6,
                        "end": 17,
                        "quote": "sunny patio",
                    },
                    {
                        "kind": "numeric",
                        "field": "bedrooms",
                        "value": 3,
                        "start": 19,
                        "end": 20,
                        "quote": "3",
                    },
                ],
            }
        ],
    }
    exact = score_private_labels(sample, gold, predictions, "dev")
    overlap = score_private_labels(
        sample, gold, predictions, "dev", categorical_overlap=True
    )
    assert exact["facet.exterior_lot.patio"] == Counts(1, 2, 0)
    assert overlap["facet.exterior_lot.patio"] == Counts(1, 1, 1)
    assert overlap["numeric.bedrooms"] == Counts(1, 1, 0)
    assert overlap["overall"] == Counts(2, 2, 1)


def test_same_facet_nonoverlapping_spans_are_fp_and_fn():
    sample = {
        "version": 1,
        "dataset_id": "invented",
        "cases": [{"id": "a", "split": "dev", "text": "pool and pool"}],
    }

    def evidence(start):
        return {
            "kind": "facet",
            "group": "exterior_lot",
            "value": "pool",
            "polarity": "affirmed",
            "temporality": "current",
            "start": start,
            "end": start + 4,
            "quote": "pool",
        }

    gold = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": "a", "annotations": [evidence(0)]}],
    }
    predicted = {
        "version": 1,
        "dataset_id": "invented",
        "labels": [{"id": "a", "annotations": [evidence(9)]}],
    }
    result = score_private_labels(
        sample, gold, predicted, "dev", categorical_overlap=True
    )
    assert result["facet.exterior_lot.pool"] == Counts(1, 1, 0)


def test_overlap_multiple_cases_preserves_prediction_mapping():
    sample, labels = example()
    repeated = copy.deepcopy(labels["labels"][0]["annotations"])
    sample["cases"][1]["text"] = sample["cases"][0]["text"]
    labels["labels"][1]["annotations"] = repeated
    result = score_private_labels(
        sample, labels, labels, "dev", categorical_overlap=True
    )
    assert result["facet.exterior_lot.pool"] == Counts(2, 2, 2)
