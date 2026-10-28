"""Dev-only extraction preparation and strict private prediction validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from idx_agent.enrichment.private_scoring import _key


def extract_dev_cases(
    dataset_id: str,
    cases: list[tuple[str, str]],
    invoke: Callable[[str], tuple[str, dict[str, int]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract exactly 100 supplied dev remarks; never print input or output text."""
    if not dataset_id or len(cases) != 100 or len({key for key, _ in cases}) != 100:
        raise ValueError("invalid dev case set")
    labels = []
    total_input = total_output = 0
    for key, remark in cases:
        if not isinstance(key, str) or not isinstance(remark, str):
            raise ValueError("invalid dev case")
        response, usage = invoke(remark)
        if not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0
            for k in ("input_tokens", "output_tokens")
        ):
            raise ValueError("provider usage unavailable")
        value = json.loads(response)
        if (
            not isinstance(value, dict)
            or set(value) != {"annotations"}
            or not isinstance(value["annotations"], list)
        ):
            raise ValueError("invalid model output")
        annotations = value["annotations"]
        keys = [_key(annotation, remark) for annotation in annotations]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate model annotation")
        labels.append({"id": key, "annotations": annotations})
        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]
    return {"version": 1, "dataset_id": dataset_id, "labels": labels}, {
        "cases": 100,
        "requests_made": 100,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "input_tokens_per_remark": total_input / 100,
        "output_tokens_per_remark": total_output / 100,
    }
