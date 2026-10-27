"""Validate the invented annotation splits and their original-text evidence."""

import json
from pathlib import Path

import pytest

from idx_agent.domain.enrichment import FacetRef
from idx_agent.enrichment.vocabulary import FACETS

FIXTURES = Path(__file__).parent / "fixtures" / "enrichment"
POLARITIES = {"affirmed", "negated", "uncertain"}
TIMES = {"current", "planned", "historical", "unspecified"}


def _cases(split):
    return json.loads((FIXTURES / f"{split}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("split", ["dev", "test"])
def test_synthetic_spans_and_facets_are_valid(split):
    cases = _cases(split)
    assert len(cases) >= 10
    ids = set()
    for case in cases:
        assert set(case) == {"id", "split", "source", "text", "annotations"}
        assert case["id"].startswith(split + "-") and case["id"] not in ids
        ids.add(case["id"])
        assert case["split"] == split and case["source"] == "synthetic"
        assert isinstance(case["text"], str) and case["text"]
        for ann in case["annotations"]:
            assert set(ann) == {
                "facet",
                "start",
                "end",
                "quote",
                "polarity",
                "temporality",
            }
            FacetRef.model_validate(ann["facet"])
            assert ann["polarity"] in POLARITIES and ann["temporality"] in TIMES
            assert type(ann["start"]) is int and type(ann["end"]) is int
            assert 0 <= ann["start"] < ann["end"] <= len(case["text"])
            assert case["text"][ann["start"] : ann["end"]] == ann["quote"]


def test_splits_are_disjoint_and_cover_boundary_cases():
    dev, held_out = _cases("dev"), _cases("test")
    canonical = lambda case: " ".join(case["text"].casefold().split())  # noqa: E731
    assert not {case["id"] for case in dev} & {case["id"] for case in held_out}
    assert not {canonical(case) for case in dev} & {
        canonical(case) for case in held_out
    }
    annotations = [ann for case in dev + held_out for ann in case["annotations"]]
    assert {ann["facet"]["group"] for ann in annotations} == set(FACETS)
    assert {ann["polarity"] for ann in annotations} == POLARITIES
    assert {ann["temporality"] for ann in annotations} == TIMES
    assert any(not case["annotations"] for case in dev)
    assert any(not case["annotations"] for case in held_out)
    assert any(
        ann["polarity"] == "uncertain" and ann["temporality"] == "planned"
        for ann in annotations
    )
    assert any(ord(char) > 127 for case in held_out for char in case["text"])


def test_proposal_and_current_absence_remain_separate():
    case = next(case for case in _cases("test") if case["id"] == "test-006")
    assert {(ann["polarity"], ann["temporality"]) for ann in case["annotations"]} == {
        ("affirmed", "planned"),
        ("negated", "current"),
    }
