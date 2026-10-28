"""Dev-only structured extraction, local quote alignment and safe diagnostics."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from idx_agent.enrichment.private_scoring import NUMERIC_FIELDS, _key
from idx_agent.enrichment.vocabulary import FACETS


class ProviderFailure(RuntimeError):
    """A sanitized provider failure with optional private response bytes."""

    def __init__(self, raw: bytes | None, rule: str) -> None:
        super().__init__(rule)
        self.raw, self.rule = raw, rule


class DiagnosticError(ValueError):
    """A sanitized error with no model-supplied values or source text."""

    def __init__(self, path: str, rule: str) -> None:
        super().__init__(rule)
        self.path, self.rule = path, rule


def _normalized(text: str) -> tuple[str, list[tuple[int, int]]]:
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"\s+|\S", text):
        part = match.group()
        chars.append(" " if part.isspace() else part)
        spans.append(match.span())
    return "".join(chars), spans


def locate_quote(text: str, quote: str) -> tuple[int, int]:
    """Locate one unambiguous exact or whitespace-normalized source quote."""
    if not isinstance(quote, str) or not quote.strip():
        raise DiagnosticError("quote", "nonempty_quote_required")
    first = text.find(quote)
    if first >= 0:
        if text.find(quote, first + 1) >= 0:
            raise DiagnosticError("quote", "ambiguous_quote")
        return first, first + len(quote)
    source, spans = _normalized(text)
    needle, _ = _normalized(quote)
    first = source.find(needle)
    if first < 0:
        raise DiagnosticError("quote", "quote_not_found")
    if source.find(needle, first + 1) >= 0:
        raise DiagnosticError("quote", "ambiguous_quote")
    return spans[first][0], spans[first + len(needle) - 1][1]


def parse_response(response: Any, remark: str) -> tuple[list[dict], list[dict]]:
    """Keep valid candidates and return sanitized diagnostics for invalid ones."""
    diagnostics: list[dict] = []
    annotations: list[dict] = []
    try:
        if not isinstance(response, dict) or not isinstance(
            response.get("content"), list
        ):
            raise DiagnosticError("content", "provider_response_object_required")
        blocks = [
            b
            for b in response["content"]
            if isinstance(b, dict)
            and b.get("type") == "tool_use"
            and b.get("name") == "record_extractions"
        ]
        if not blocks:
            raise DiagnosticError("content", "no_extraction_tool_call")
        if len(blocks) != 1 or not isinstance(blocks[0].get("input"), dict):
            raise DiagnosticError("content", "one_valid_extraction_tool_call_required")
        items = blocks[0]["input"].get("annotations")
        if not isinstance(items, list):
            raise DiagnosticError("annotations", "array_required")
        seen = set()
        for index, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise DiagnosticError("", "object_required")
                start, end = locate_quote(remark, item.get("quote"))
                if item.get("kind") == "facet":
                    group = item.get("group")
                    if not isinstance(group, str) or group not in FACETS:
                        raise DiagnosticError("group", "known_group_required")
                    if (
                        not isinstance(item.get("facet_value"), str)
                        or item["facet_value"] not in FACETS[group]
                    ):
                        raise DiagnosticError(
                            "facet_value", "known_facet_value_required"
                        )
                    if not isinstance(item.get("polarity"), str) or item[
                        "polarity"
                    ] not in {"affirmed", "negated", "uncertain"}:
                        raise DiagnosticError("polarity", "known_polarity_required")
                    if not isinstance(item.get("temporality"), str) or item[
                        "temporality"
                    ] not in {
                        "current",
                        "planned",
                        "historical",
                        "unspecified",
                    }:
                        raise DiagnosticError(
                            "temporality", "known_temporality_required"
                        )
                    converted = {
                        "kind": "facet",
                        "group": item.get("group"),
                        "value": item.get("facet_value"),
                        "polarity": item.get("polarity"),
                        "temporality": item.get("temporality"),
                    }
                elif item.get("kind") == "numeric":
                    if (
                        not isinstance(item.get("field"), str)
                        or item["field"] not in NUMERIC_FIELDS
                    ):
                        raise DiagnosticError("field", "known_numeric_field_required")
                    number = item.get("number")
                    if type(number) not in (int, float) or not 0 <= number < float(
                        "inf"
                    ):
                        raise DiagnosticError(
                            "number", "nonnegative_finite_number_required"
                        )
                    converted = {
                        "kind": "numeric",
                        "field": item.get("field"),
                        "value": item.get("number"),
                    }
                else:
                    raise DiagnosticError("kind", "known_kind_required")
                converted.update(start=start, end=end, quote=remark[start:end])
                try:
                    key = _key(converted, remark)
                except (ValueError, TypeError):
                    raise DiagnosticError(
                        "", "facet_or_numeric_value_invalid"
                    ) from None
                if key in seen:
                    raise DiagnosticError("", "duplicate_annotation")
                seen.add(key)
                annotations.append(converted)
            except DiagnosticError as exc:
                suffix = f".{exc.path}" if exc.path else ""
                diagnostics.append(
                    {
                        "error_class": "DiagnosticError",
                        "field": f"annotations[{index}]{suffix}",
                        "rule": exc.rule,
                    }
                )
    except DiagnosticError as exc:
        diagnostics.append(
            {"error_class": "DiagnosticError", "field": exc.path, "rule": exc.rule}
        )
    return annotations, diagnostics


def extract_dev_cases(
    dataset_id: str,
    cases: list[tuple[str, str]],
    invoke: Callable[[str], tuple[Any, dict | None, bytes]],
    on_failure: Callable[[int, bytes | None, list[dict]], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Process 100 dev cases, recording local misses and reporting aggregate usage."""
    if not dataset_id or len(cases) != 100 or len({key for key, _ in cases}) != 100:
        raise ValueError("invalid dev case set")
    labels, failed, diagnostic_count, no_tool_calls = [], 0, 0, 0
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    totals = dict.fromkeys(fields, 0)
    known = dict.fromkeys(fields, 0)
    known_usage = 0
    for index, (key, remark) in enumerate(cases, 1):
        if not isinstance(key, str) or not isinstance(remark, str):
            raise ValueError("invalid dev case")
        try:
            response, usage, raw = invoke(remark)
        except ProviderFailure as exc:
            on_failure(
                index,
                exc.raw,
                [
                    {
                        "error_class": "ProviderFailure",
                        "field": "provider",
                        "rule": exc.rule,
                    }
                ],
            )
            raise
        if isinstance(usage, dict):
            valid = [
                key for key in fields if type(usage.get(key)) is int and usage[key] >= 0
            ]
            for key in valid:
                totals[key] += usage[key]
                known[key] += 1
            known_usage += len(valid) == len(fields)
        annotations, diagnostics = parse_response(response, remark)
        if diagnostics:
            failed += 1
            diagnostic_count += len(diagnostics)
            no_tool_calls += any(
                d["rule"] == "no_extraction_tool_call" for d in diagnostics
            )
            on_failure(index, raw, diagnostics)
        labels.append({"id": key, "annotations": annotations})
    input_complete = all(
        known[key] == 100
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )
    output_complete = known["output_tokens"] == 100
    total_input = sum(
        totals[key]
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )

    return {"version": 1, "dataset_id": dataset_id, "labels": labels}, {
        "cases": 100,
        "requests_made": 100,
        "remarks_with_misses": failed,
        "no_tool_calls": no_tool_calls,
        "diagnostic_count": diagnostic_count,
        "responses_with_usage": known_usage,
        "input_tokens": total_input if input_complete else None,
        "uncached_input_tokens": totals["input_tokens"]
        if known["input_tokens"] == 100
        else None,
        "cache_creation_input_tokens": totals["cache_creation_input_tokens"]
        if known["cache_creation_input_tokens"] == 100
        else None,
        "cache_read_input_tokens": totals["cache_read_input_tokens"]
        if known["cache_read_input_tokens"] == 100
        else None,
        "output_tokens": totals["output_tokens"] if output_complete else None,
        "input_tokens_per_remark": total_input / 100 if input_complete else None,
        "output_tokens_per_remark": totals["output_tokens"] / 100
        if output_complete
        else None,
    }
