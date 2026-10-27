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


def test_synthetic_case_model_validates_original_spans():
    from pydantic import ValidationError

    from idx_agent.domain.enrichment import SyntheticAnnotationCase

    for split in ("dev", "test"):
        for case in _cases(split):
            SyntheticAnnotationCase.model_validate(case)
    broken = _cases("test")[0]
    broken["annotations"][0]["start"] += 1
    with pytest.raises(ValidationError):
        SyntheticAnnotationCase.model_validate(broken)
    broken = _cases("test")[0]
    broken["source"] = "real"
    with pytest.raises(ValidationError):
        SyntheticAnnotationCase.model_validate(broken)


def test_exact_scoring_preserves_polarity_time_and_zero_denominators():
    from idx_agent.domain.enrichment import SyntheticAnnotationCase
    from idx_agent.enrichment.annotation_scoring import score_case

    raw = _cases("dev")[0]
    expected = SyntheticAnnotationCase.model_validate(raw)
    partial = dict(raw, annotations=raw["annotations"][:1])
    result = score_case(expected, SyntheticAnnotationCase.model_validate(partial))
    assert (result.expected, result.predicted, result.correct) == (2, 1, 1)
    assert result.precision == 1 and result.recall == 0.5
    empty = SyntheticAnnotationCase.model_validate(dict(raw, annotations=[]))
    assert score_case(empty, empty).precision is None
    assert score_case(empty, empty).recall is None
    different = _cases("dev")[1]
    with pytest.raises(ValueError, match="annotation cases do not match"):
        score_case(expected, SyntheticAnnotationCase.model_validate(different))


def test_scoring_does_not_conflate_negated_with_affirmed():
    from idx_agent.domain.enrichment import SyntheticAnnotationCase
    from idx_agent.enrichment.annotation_scoring import score_case

    raw = _cases("dev")[1]
    changed = json.loads(json.dumps(raw))
    changed["annotations"][0]["polarity"] = "affirmed"
    gold = SyntheticAnnotationCase.model_validate(raw)
    predicted = SyntheticAnnotationCase.model_validate(changed)
    result = score_case(gold, predicted)
    assert (result.expected, result.predicted, result.correct) == (1, 1, 0)


def test_synthetic_boundary_rejects_duplicate_invalid_and_oversize_input():
    from pydantic import ValidationError

    from idx_agent.domain.enrichment import SyntheticAnnotationCase

    raw = _cases("dev")[0]
    duplicate = json.loads(json.dumps(raw))
    duplicate["annotations"].append(duplicate["annotations"][0])
    invalid_start = json.loads(json.dumps(raw))
    invalid_start["annotations"][0]["start"] = True
    for bad in (
        duplicate,
        invalid_start,
        dict(raw, text="x" * 16_001),
        dict(raw, text="bad\x00text"),
        dict(raw, id="test-001"),
    ):
        with pytest.raises(ValidationError):
            SyntheticAnnotationCase.model_validate(bad)


def test_scoring_breakdown_does_not_hide_wrong_polarity():
    from idx_agent.domain.enrichment import SyntheticAnnotationCase
    from idx_agent.enrichment.annotation_scoring import score_breakdown

    raw = _cases("dev")[1]
    changed = json.loads(json.dumps(raw))
    changed["annotations"][0]["polarity"] = "affirmed"
    gold = SyntheticAnnotationCase.model_validate(raw)
    predicted = SyntheticAnnotationCase.model_validate(changed)
    report = score_breakdown(gold, predicted)
    facet = report["facet"]["exterior_lot.pool"]
    assert (facet.expected, facet.predicted, facet.correct) == (1, 1, 0)
    assert report["polarity"]["negated"].recall == 0
    assert report["polarity"]["affirmed"].precision == 0
