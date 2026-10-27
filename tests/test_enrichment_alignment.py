"""Synthetic abbreviation alignment keeps citations on original text."""

import pytest

from idx_agent.enrichment.alignment import normalize_with_alignment
from idx_agent.enrichment.normalize import normalize_remarks


def test_full_expansion_and_later_unicode_span_map_to_original():
    original = "Café has A/C and a patio."
    result = normalize_with_alignment(original)
    assert result.text == normalize_remarks(original).text
    start = result.text.index("air conditioning")
    left, right = result.original_span(start, start + len("air conditioning"))
    assert original[left:right] == "A/C"
    start = result.text.index("patio")
    left, right = result.original_span(start, start + len("patio"))
    assert original[left:right] == "patio"


def test_partial_expansions_are_refused_rather_than_misquoted():
    result = normalize_with_alignment("No A/C; 3BR.")
    start = result.text.index("air conditioning")
    with pytest.raises(ValueError, match="cuts through"):
        result.original_span(start, start + len("air"))
    start = result.text.index("3 bedrooms")
    with pytest.raises(ValueError, match="cuts through"):
        result.original_span(start, start + 1)


def test_repeated_expansions_map_to_their_own_original_positions():
    original = "A/C here; A/C there."
    result = normalize_with_alignment(original)
    first = result.text.index("air conditioning")
    second = result.text.rindex("air conditioning")
    left, right = result.original_span(first, first + len("air conditioning"))
    left2, right2 = result.original_span(second, second + len("air conditioning"))
    assert original[left:right] == original[left2:right2] == "A/C"
    assert right <= left2


def test_nonempty_and_valid_bounds_are_required():
    result = normalize_with_alignment("A/C")
    for start, end in ((0, 0), (-1, 1), (0, len(result.text) + 1), (True, 2)):
        with pytest.raises(ValueError, match="invalid normalized span"):
            result.original_span(start, end)
    with pytest.raises(ValueError, match="ceiling"):
        normalize_with_alignment("x" * 16_001)


def test_capture_group_expansions_and_cross_expansion_spans():
    original = "3BR/2.5BA"
    result = normalize_with_alignment(original)
    assert result.text == "3 bedrooms/2.5 bathrooms"
    assert result.original_span(0, len(result.text)) == (0, len(original))
    bathrooms = result.text.index("2.5 bathrooms")
    left, right = result.original_span(bathrooms, len(result.text))
    assert original[left:right] == "2.5BA"
    with pytest.raises(ValueError, match="cuts through"):
        result.original_span(0, bathrooms + len("2.5"))


def test_whole_phrase_crosses_multiple_expansions_without_shifting():
    original = "No A/C; W/D excluded."
    result = normalize_with_alignment(original)
    start = result.text.index("air conditioning")
    end = result.text.index(" excluded")
    left, right = result.original_span(start, end)
    assert original[left:right] == "A/C; W/D"
