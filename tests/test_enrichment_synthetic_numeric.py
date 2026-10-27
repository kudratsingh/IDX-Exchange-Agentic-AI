"""Test the narrow numeric experiment on invented inputs only."""

import json
from pathlib import Path

import pytest

from idx_agent.enrichment.synthetic_numeric import extract_invented_numbers


def test_visible_numeric_examples_match_requested_values_and_original_spans():
    path = Path(__file__).parent / "fixtures/enrichment/numeric_dev.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        result = extract_invented_numbers(case["text"])
        assert {candidate.field: candidate.value for candidate in result} == case[
            "expected"
        ]
        for candidate in result:
            assert case["text"][candidate.start : candidate.end] == candidate.quote


def test_refuses_out_of_bounds_text_and_unknown_contexts():
    assert extract_invented_numbers("The guest house has 2 bedrooms.") == ()
    assert extract_invented_numbers("Primary suite plus 2 more bedrooms.") == ()
    with pytest.raises(ValueError):
        extract_invented_numbers("x" * 16001)
    with pytest.raises(ValueError):
        extract_invented_numbers("a\x00b")
