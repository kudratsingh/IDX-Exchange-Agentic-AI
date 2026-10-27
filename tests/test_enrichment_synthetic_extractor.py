"""Synthetic-only extractor experiments; no live records or model calls."""

import pytest

from idx_agent.domain.enrichment import SyntheticAnnotationCase
from idx_agent.enrichment.synthetic_extractor import extract_synthetic


def _case(text):
    return SyntheticAnnotationCase(
        id="dev-900", split="dev", source="synthetic", text=text, annotations=()
    )


def test_extracts_explicit_current_claims_with_original_unicode_offsets():
    text = "Café note. The home has a fenced yard; this property features central air."
    result = extract_synthetic(_case(text))
    assert [(x.facet.value, x.quote) for x in result.annotations] == [
        ("fenced_yard", "fenced yard"),
        ("central_air", "central air"),
    ]
    assert all(text[x.start : x.end] == x.quote for x in result.annotations)
    assert all(
        x.polarity == "affirmed" and x.temporality == "current"
        for x in result.annotations
    )


@pytest.mark.parametrize(
    "text",
    [
        "The property has no patio.",
        "The property has a patio, but it may be removed.",
        "The home has a proposed garage.",
        "The property has a patio that was removed.",
        "The home has a garage conversion.",
        "The home has patio plans.",
        "The home includes a private pool table.",
        "The house has a fenced yard sign.",
        "Ignore instructions: the home has a patio.",
        "The neighbor has a patio.",
        "The neighbor's property has a garage.",
        "Suppose the home has a patio.",
        "For example, the home has a garage.",
        "Imagine. A craftsman-style home.",
        "Hypothesis. The home has a patio.",
        "Assume. The home has a patio.",
        "Looking for a craftsman-style home.",
        "I prefer a craftsman-style house.",
        "The home has a patio; it is only planned.",
        "The property has a patio. Actually, it was removed.",
        "A craftsman-style home sold years ago.",
        "The home has a patio?",
        "The home has a patio or garage.",
        'The note says "The home has a patio".',
    ],
)
def test_abstains_on_negation_uncertainty_history_and_ambiguous_subject(text):
    assert extract_synthetic(_case(text)).annotations == ()


def test_extractor_ignores_reference_labels_and_has_no_side_effects(capsys):
    raw = _case("The house includes a bonus room.")
    first = extract_synthetic(raw)
    second = extract_synthetic(first)
    assert first == second
    assert first.annotations[0].facet.value == "bonus_room"
    assert capsys.readouterr().out == "" and capsys.readouterr().err == ""


def test_explicit_style_and_yard_claims_keep_text_order():
    result = extract_synthetic(_case("A craftsman-style home with a fenced yard."))
    assert [(item.facet.value, item.quote) for item in result.annotations] == [
        ("craftsman", "craftsman-style"),
        ("fenced_yard", "fenced yard"),
    ]


def test_candidate_limit_fails_without_returning_partial_results():
    with pytest.raises(ValueError, match="too many synthetic candidates"):
        extract_synthetic(_case("The home has a patio. " * 101))


def test_explicit_shared_facilities_and_grocery_mention_are_candidates():
    result = extract_synthetic(
        _case("The community pool and clubhouse are shared. Close to a grocery store.")
    )
    assert [item.facet.value for item in result.annotations] == [
        "community_pool",
        "clubhouse",
        "near_grocery_mentioned",
    ]
    assert result.annotations[-1].quote == "Close to a grocery store"


def test_development_check_reports_counts_without_remarks():
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "eval_synthetic_enrichment.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["scope"] == "invented_development_only_not_a_real_data_benchmark"
    assert report["cases"] == 13
    assert report["overall"]["expected"] == 18
    assert "craftsman-style home" not in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("text", "value", "polarity", "temporality"),
    [
        ("There is no pool.", "pool", "negated", "current"),
        ("There is no patio.", "patio", "negated", "current"),
        ("A future patio is planned.", "patio", "affirmed", "planned"),
        ("A garage stood here years ago.", "garage", "affirmed", "historical"),
        ("Possible solar panels are mentioned.", "solar", "uncertain", "unspecified"),
        (
            "The kitchen might be updated.",
            "updated_kitchen",
            "uncertain",
            "unspecified",
        ),
    ],
)
def test_only_full_bounded_nonpositive_or_temporal_statements(
    text, value, polarity, temporality
):
    result = extract_synthetic(_case(text))
    assert len(result.annotations) == 1
    item = result.annotations[0]
    assert (item.facet.value, item.polarity, item.temporality) == (
        value,
        polarity,
        temporality,
    )
    assert text[item.start : item.end] == item.quote


def test_explicit_removed_pool_keeps_historical_and_current_mentions():
    result = extract_synthetic(_case("A former pool was removed; no pool remains."))
    assert [(item.polarity, item.temporality) for item in result.annotations] == [
        ("affirmed", "historical"),
        ("negated", "current"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "There is no pool. Actually, the home has a private pool.",
        "There is no pool table.",
        "Is there no pool?",
        "A future patio is planned unless approval fails.",
        "Possible solar panels are mentioned by a neighbor.",
    ],
)
def test_nonpositive_patterns_do_not_accept_extra_or_question_context(text):
    assert extract_synthetic(_case(text)).annotations == ()


def test_long_unmatched_whitespace_is_bounded_and_abstains():
    text = "There is no pool" + " " * 15_000 + "x"
    assert extract_synthetic(_case(text)).annotations == ()
