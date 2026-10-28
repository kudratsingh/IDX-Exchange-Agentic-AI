"""The explicitly scoped 20-facet v2 extraction contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from idx_agent.enrichment.dev_extraction import parse_response
from idx_agent.enrichment.private_scoring import score_private_labels
from idx_agent.enrichment.vocabulary import FACETS

V2_FACETS = {
    "community_amenities": frozenset(
        {"clubhouse", "community_pool", "fitness_center", "gated_community"}
    ),
    "exterior_lot": frozenset({"adu", "garage", "patio", "pool"}),
    "interior_systems": frozenset({"hardwood", "solar", "stainless_appliances"}),
    "location_views": frozenset(
        {
            "mountain_view",
            "near_grocery_mentioned",
            "near_transit_mentioned",
            "water_view",
        }
    ),
    "property_type": frozenset({"condominium"}),
    "rooms_layout": frozenset(
        {"bonus_room", "open_plan", "single_level", "walk_in_closet"}
    ),
}
assert sum(map(len, V2_FACETS.values())) == 20
assert all(values <= FACETS[group] for group, values in V2_FACETS.items())


def tool_schema() -> dict[str, Any]:
    values = sorted({value for group in V2_FACETS.values() for value in group})
    return {
        "name": "record_extractions",
        "description": "Record facet mentions from the supplied remark.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "annotations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["facet"]},
                            "quote": {"type": "string"},
                            "group": {"type": "string", "enum": sorted(V2_FACETS)},
                            "facet_value": {"type": "string", "enum": values},
                            "polarity": {
                                "type": "string",
                                "enum": ["affirmed", "negated", "uncertain"],
                            },
                            "temporality": {
                                "type": "string",
                                "enum": [
                                    "current",
                                    "planned",
                                    "historical",
                                    "unspecified",
                                ],
                            },
                        },
                        "required": [
                            "kind",
                            "quote",
                            "group",
                            "facet_value",
                            "polarity",
                            "temporality",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["annotations"],
            "additionalProperties": False,
        },
    }


def canonical_schema_hash() -> str:
    return hashlib.sha256(
        json.dumps(
            tool_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def message_parameters(model: str, prompt: str, remark: str) -> dict[str, Any]:
    """Build a v2 request without sending it or reading credentials."""
    if not model or not prompt or not isinstance(remark, str):
        raise ValueError("invalid message parameters")
    pairs = json.dumps(
        {group: sorted(values) for group, values in V2_FACETS.items()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "model": model,
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
        "tools": [tool_schema()],
        "tool_choice": {"type": "auto"},
        "system": [
            {
                "type": "text",
                "text": prompt + "\nAllowed group/value pairs: " + pairs,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": json.dumps({"remark": remark}, ensure_ascii=False),
            }
        ],
    }


def parse_v2(response: Any, remark: str) -> tuple[list[dict], list[dict]]:
    annotations, diagnostics = parse_response(response, remark)
    accepted = []
    for item in annotations:
        if item["kind"] == "facet" and item["value"] in V2_FACETS.get(
            item["group"], ()
        ):
            accepted.append(item)
        else:
            diagnostics.append(
                {
                    "error_class": "DiagnosticError",
                    "field": "annotations",
                    "rule": "v2_facet_required",
                }
            )
    return accepted, diagnostics


def score_v2(sample: dict, labels: dict, predictions: dict, split: str) -> dict:
    """Apply the frozen overlap scorer after limiting both sides to the 20 facets."""
    selected_ids = {case["id"] for case in sample["cases"] if case["split"] == split}
    known_ids = {case["id"] for case in sample["cases"]}

    def filtered(data):
        ids = [row.get("id") for row in data["labels"]]
        if any(key not in known_ids for key in ids) or len(ids) != len(set(ids)):
            raise ValueError("invalid label row")
        return {
            **data,
            "labels": [
                {
                    **row,
                    "annotations": [
                        a
                        for a in row["annotations"]
                        if a.get("kind") == "facet"
                        and a.get("value") in V2_FACETS.get(a.get("group"), ())
                    ],
                }
                for row in data["labels"]
                if row.get("id") in selected_ids
            ],
        }

    counts = score_private_labels(
        sample, filtered(labels), filtered(predictions), split, categorical_overlap=True
    )
    result = {"overall": counts["categorical"]}
    for group, values in V2_FACETS.items():
        for value in values:
            key = f"facet.{group}.{value}"
            result[key] = counts[key]
    return result


def haiku_meets_dev_rule(sonnet_f1: float | None, haiku_f1: float | None) -> bool:
    """Haiku must be at most three percentage points below Sonnet."""
    if sonnet_f1 is None or haiku_f1 is None:
        return False
    if not (0 <= sonnet_f1 <= 1 and 0 <= haiku_f1 <= 1):
        raise ValueError("invalid F1")
    return haiku_f1 + 0.03 + 1e-12 >= sonnet_f1


def compare_dev_cases(dataset_id, cases, model_ids, invoke, checkpoint, diagnostic):
    """Orchestrate two 100-case comparisons; the caller supplies the paid boundary."""
    if not dataset_id or len(cases) != 100 or len({key for key, _ in cases}) != 100:
        raise ValueError("invalid development cases")
    if set(model_ids) != {"sonnet", "haiku"} or not all(model_ids.values()):
        raise ValueError("two explicit model identifiers required")
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    predictions, reports = {}, {}
    for model_label in ("sonnet", "haiku"):
        totals, known = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0)
        rows, misses, no_calls, diagnostic_count = [], 0, 0, 0
        for index, (key, remark) in enumerate(cases, 1):
            response, usage, raw = invoke(model_ids[model_label], remark)
            checkpoint(model_label, index, raw, usage)
            if isinstance(usage, dict):
                for field in fields:
                    if type(usage.get(field)) is int and usage[field] >= 0:
                        totals[field] += usage[field]
                        known[field] += 1
            annotations, errors = parse_v2(response, remark)
            if errors:
                misses += 1
                diagnostic_count += len(errors)
                no_calls += any(
                    error["rule"] == "no_extraction_tool_call" for error in errors
                )
                diagnostic(model_label, index, raw, errors)
            rows.append({"id": key, "annotations": annotations})
        predictions[model_label] = {
            "version": 1,
            "dataset_id": dataset_id,
            "labels": rows,
        }
        reports[model_label] = {
            "cases": 100,
            "remarks_with_misses": misses,
            "no_tool_calls": no_calls,
            "diagnostic_count": diagnostic_count,
            "usage": {
                field: totals[field] if known[field] == 100 else None
                for field in fields
            },
        }
    return predictions, reports
