"""Exercise development extraction using invented inputs and a fake provider."""

import json

import pytest

from idx_agent.enrichment.dev_extraction import extract_dev_cases


def test_dev_output_shape_and_actual_usage_aggregation():
    cases = [(f"dev-{i}", "pool") for i in range(100)]
    annotation = {
        "kind": "facet",
        "group": "exterior_lot",
        "value": "pool",
        "polarity": "affirmed",
        "temporality": "current",
        "start": 0,
        "end": 4,
        "quote": "pool",
    }
    result, usage = extract_dev_cases(
        "invented",
        cases,
        lambda _: (
            json.dumps({"annotations": [annotation]}),
            {"input_tokens": 30, "output_tokens": 10},
        ),
    )
    assert len(result["labels"]) == 100
    assert usage["input_tokens_per_remark"] == 30
    assert usage["output_tokens_per_remark"] == 10


def test_refuses_incomplete_usage_or_unverifiable_span():
    cases = [(str(i), "pool") for i in range(100)]
    with pytest.raises(ValueError, match="usage"):
        extract_dev_cases("invented", cases, lambda _: ('{"annotations":[]}', {}))
    with pytest.raises(ValueError, match="span"):
        extract_dev_cases(
            "invented",
            cases,
            lambda _: (
                '{"annotations":[{"start":0,"end":1,"quote":"x"}]}',
                {"input_tokens": 1, "output_tokens": 1},
            ),
        )
