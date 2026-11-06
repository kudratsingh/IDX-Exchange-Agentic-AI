"""The `features` search filter (WO-021): validation, follow-up merges and wording."""

import pytest

from idx_agent.channels.format import feature_words, format_filters, format_search_reply
from idx_agent.domain.models import (
    MAX_FEATURES,
    Clarification,
    FeatureFilter,
    PropertySearchFilters,
    SearchResult,
)
from idx_agent.memory.merge import merge_filters


def parse(features):
    return PropertySearchFilters.from_input({"city": "Pasadena", "features": features})


def test_features_are_normalized_deduplicated_and_sorted():
    assert parse([" Solar", "walk_in_closet", "solar"]).features == (
        "solar",
        "walk_in_closet",
    )


@pytest.mark.parametrize("empty", [None, [], ()])
def test_no_features_means_no_filter(empty):
    assert parse(empty).features is None


@pytest.mark.parametrize(
    "bad", [["jacuzzi"], ["office"], "solar", [3], [None], {"solar"}]
)
def test_unknown_or_malformed_features_ask_instead_of_guessing(bad):
    result = parse(bad)
    assert isinstance(result, Clarification)
    assert result.reason == "unknown_feature"
    assert result.field == "features"
    assert "jacuzzi" not in result.question


def test_unknown_feature_offers_the_eligible_list():
    result = parse(["jacuzzi"])
    assert "solar" in result.options and len(result.options) == 20


def test_too_many_features_ask_which_matter_most():
    names = ["solar", "pool", "patio", "garage", "hardwood", "adu"]
    assert len(names) > MAX_FEATURES
    result = parse(names)
    assert isinstance(result, Clarification) and result.reason == "too_many_features"


def test_follow_ups_keep_replace_and_clear_features():
    previous = parse(["solar"])
    kept = merge_filters(previous, {"min_beds": 3}, "update")
    assert kept.features == ("solar",)
    replaced = merge_filters(previous, {"features": ["pool"]}, "update")
    assert replaced.features == ("pool",)
    cleared = merge_filters(previous, {}, "update", clear=["features"])
    assert cleared.features is None
    # An empty list means "not given", never "clear" (WO-021 owner review).
    assert merge_filters(previous, {"features": []}, "update").features == ("solar",)
    assert merge_filters(previous, {"features": ()}, "update").features == ("solar",)


def test_wording():
    assert feature_words(["adu", "walk_in_closet", "solar"]) == (
        "ADU, walk-in closet, solar"
    )
    assert "features solar" in format_filters(parse(["solar"]))
    assert "features" not in format_filters(parse(None))


def test_reply_note_comes_after_the_filters_and_is_kept():
    from datetime import date

    reply = format_search_reply(
        [], date(2026, 7, 2), "Filters: city X", note="Note text."
    )
    # Layer 2 (2026-11-05): an empty page ends with the widen offer, after the note.
    assert reply.endswith(
        "Filters: city X\n\nNote text.\n\n"
        "Want me to widen one filter, such as the price or the city?"
    )
    plain = format_search_reply([], date(2026, 7, 2), "Filters: city X")
    assert "Note text." not in plain


def test_search_result_keeps_its_old_shape_without_features():
    result = SearchResult(applied_filters=parse(None))
    assert result.feature_filter is None
    feature = FeatureFilter(status="unavailable", features=["solar"], limitation="L")
    assert SearchResult(applied_filters=parse(["solar"]), feature_filter=feature)
