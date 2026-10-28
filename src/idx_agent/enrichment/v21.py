"""Frozen v2.1 contract: Haiku without thinking and bounded quotations."""

from __future__ import annotations

import copy

from idx_agent.enrichment.v2 import message_parameters, parse_v2, tool_schema


def schema():
    result = copy.deepcopy(tool_schema())
    return result


def parameters(prompt, remark):
    result = message_parameters("claude-haiku-5-5", prompt, remark)
    result["thinking"] = {"type": "disabled"}
    result["tools"] = [schema()]
    return result


def parse(response, remark):
    annotations, diagnostics = parse_v2(response, remark)
    accepted = []
    for item in annotations:
        if len(item["quote"]) > 80:
            diagnostics.append(
                {
                    "error_class": "DiagnosticError",
                    "field": "annotations.quote",
                    "rule": "quote_exceeds_80",
                }
            )
        else:
            accepted.append(item)
    return accepted, diagnostics
