"""Invented tests for quote alignment, diagnostics and per-remark misses."""

import pytest

from idx_agent.enrichment.dev_extraction import (
    DiagnosticError,
    extract_dev_cases,
    locate_quote,
    parse_response,
)


def tool(items):
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "record_extractions",
                "input": {"annotations": items},
            }
        ]
    }


def facet(quote="fenced yard"):
    return {
        "kind": "facet",
        "group": "exterior_lot",
        "facet_value": "fenced_yard",
        "polarity": "affirmed",
        "temporality": "current",
        "quote": quote,
    }


def test_quote_alignment_exact_and_whitespace():
    text = "🏠 fenced\n  yard nearby"
    start, end = locate_quote(text, "fenced yard")
    assert text[start:end] == "fenced\n  yard"
    assert locate_quote(text, "nearby") == (16, 22)
    with pytest.raises(DiagnosticError, match="ambiguous_quote"):
        locate_quote("pool and pool", "pool")
    with pytest.raises(DiagnosticError, match="quote_not_found"):
        locate_quote("no feature", "pool")


def test_invalid_field_and_unfound_quote_are_sanitized():
    first = facet("missing secret")
    second = dict(facet(), group="unknown")
    annotations, errors = parse_response(tool([first, second]), "fenced yard")
    assert annotations == []
    assert errors == [
        {
            "error_class": "DiagnosticError",
            "field": "annotations[0].quote",
            "rule": "quote_not_found",
        },
        {
            "error_class": "DiagnosticError",
            "field": "annotations[1].group",
            "rule": "known_group_required",
        },
    ]
    assert "missing secret" not in str(errors)


def test_failed_remark_is_miss_and_next_remark_continues():
    cases = [(str(i), "fenced yard") for i in range(100)]
    calls = 0
    failures = []

    def invoke(_):
        nonlocal calls
        calls += 1
        item = facet("missing") if calls == 1 else facet()
        return (
            tool([item]),
            {
                "input_tokens": 30,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            b"invented raw",
        )

    predictions, usage = extract_dev_cases(
        "invented", cases, invoke, lambda *args: failures.append(args)
    )
    assert calls == 100 and len(failures) == 1
    assert predictions["labels"][0]["annotations"] == []
    assert len(predictions["labels"][1]["annotations"]) == 1
    assert usage["requests_made"] == 100 and usage["remarks_with_misses"] == 1
    assert usage["input_tokens_per_remark"] == 30


def test_provider_exception_is_not_retried():
    cases = [(str(i), "fenced yard") for i in range(100)]
    calls = []

    def invoke(_):
        calls.append(1)
        raise RuntimeError("network error")

    with pytest.raises(RuntimeError):
        extract_dev_cases("invented", cases, invoke, lambda *_: None)
    assert len(calls) == 1


def test_missing_tool_call_and_invalid_types_become_misses():
    predictions, diagnostics = parse_response(
        {"content": [{"type": "text", "text": "private text"}]}, "fenced yard"
    )
    assert predictions == []
    assert diagnostics == [
        {
            "error_class": "DiagnosticError",
            "field": "content",
            "rule": "no_extraction_tool_call",
        }
    ]
    for malformed in (
        dict(facet(), group=[]),
        dict(facet(), facet_value=[]),
        dict(facet(), polarity=[]),
        dict(facet(), temporality=[]),
    ):
        predictions, diagnostics = parse_response(tool([malformed]), "fenced yard")
        assert predictions == [] and len(diagnostics) == 1
        assert "private text" not in str(diagnostics)


def test_missing_usage_is_reported_unknown_without_aborting():
    cases = [(str(i), "fenced yard") for i in range(100)]
    predictions, usage = extract_dev_cases(
        "invented", cases, lambda _: (tool([]), None, b"invented raw"), lambda *_: None
    )
    assert len(predictions["labels"]) == 100
    assert usage["requests_made"] == 100 and usage["responses_with_usage"] == 0
    assert usage["input_tokens"] is None and usage["output_tokens_per_remark"] is None


def test_provider_failure_records_sanitized_diagnostic_and_stops():
    from idx_agent.enrichment.dev_extraction import ProviderFailure

    cases = [(str(i), "fenced yard") for i in range(100)]
    failures = []

    def fail(_):
        raise ProviderFailure(b"invented private body", "provider_http_error")

    with pytest.raises(ProviderFailure):
        extract_dev_cases("invented", cases, fail, lambda *args: failures.append(args))
    assert len(failures) == 1
    assert failures[0][1] == b"invented private body"
    assert failures[0][2] == [
        {
            "error_class": "ProviderFailure",
            "field": "provider",
            "rule": "provider_http_error",
        }
    ]
    assert "private body" not in str(failures[0][2])


def test_no_call_count_distinguishes_missing_and_malformed_calls():
    cases = [(str(i), "fenced yard") for i in range(100)]
    calls = 0

    def invoke(_):
        nonlocal calls
        calls += 1
        response = {"content": []} if calls == 1 else tool([])
        return (
            response,
            {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            b"invented",
        )

    _, usage = extract_dev_cases("invented", cases, invoke, lambda *_: None)
    assert usage["no_tool_calls"] == 1
    assert usage["remarks_with_misses"] == 1


def test_cache_usage_is_included_in_total_tokens():
    cases = [(str(i), "fenced yard") for i in range(100)]
    api_usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_creation_input_tokens": 30,
        "cache_read_input_tokens": 40,
    }
    _, usage = extract_dev_cases(
        "invented", cases, lambda _: (tool([]), api_usage, b"{}"), lambda *_: None
    )
    assert usage["input_tokens"] == 8000
    assert usage["input_tokens_per_remark"] == 80
    assert usage["uncached_input_tokens"] == 1000
    assert usage["cache_creation_input_tokens"] == 3000
    assert usage["cache_read_input_tokens"] == 4000


def test_missing_cache_usage_does_not_hide_known_output_usage():
    cases = [(str(i), "fenced yard") for i in range(100)]
    partial = {"input_tokens": 10, "output_tokens": 2}
    _, usage = extract_dev_cases(
        "invented", cases, lambda _: (tool([]), partial, b"{}"), lambda *_: None
    )
    assert usage["input_tokens"] is None
    assert usage["uncached_input_tokens"] == 1000
    assert usage["output_tokens"] == 200
    assert usage["cache_read_input_tokens"] is None
