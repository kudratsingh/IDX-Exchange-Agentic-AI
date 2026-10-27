"""Aggregate exact annotation counts without retaining or emitting source text."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from idx_agent.enrichment.vocabulary import FACETS

NUMERIC_FIELDS = frozenset(
    {"bedrooms", "bathrooms", "living_area_sqft", "asking_price_usd"}
)


@dataclass(frozen=True)
class Counts:
    """Counts support undefined precision and recall when denominators are zero."""

    expected: int
    predicted: int
    correct: int

    @property
    def precision(self) -> float | None:
        return self.correct / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.correct / self.expected if self.expected else None

    @property
    def f1(self) -> float | None:
        denominator = self.expected + self.predicted
        return 2 * self.correct / denominator if denominator else None


def _key(item: dict[str, Any], text: str) -> tuple[Any, ...]:
    if not isinstance(item, dict):
        raise ValueError("invalid annotation")
    start, end = item.get("start"), item.get("end")
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or item.get("quote") != text[start:end]
    ):
        raise ValueError("invalid annotation span")
    kind = item.get("kind")
    if kind == "numeric":
        field, value = item.get("field"), item.get("value")
        if (
            field not in NUMERIC_FIELDS
            or type(value) not in (int, float)
            or not 0 <= value < float("inf")
        ):
            raise ValueError("invalid numeric annotation")
        return (kind, field, value, start, end)
    if kind == "facet":
        group, value = item.get("group"), item.get("value")
        if (
            group not in FACETS
            or value not in FACETS[group]
            or item.get("polarity") not in {"affirmed", "negated", "uncertain"}
            or item.get("temporality")
            not in {"current", "planned", "historical", "unspecified"}
        ):
            raise ValueError("invalid facet annotation")
        return (kind, group, value, item["polarity"], item["temporality"], start, end)
    raise ValueError("invalid annotation kind")


def score_private_labels(
    sample: dict[str, Any],
    gold: dict[str, Any],
    predictions: dict[str, Any],
    split: str,
) -> dict[str, Counts]:
    """Count exact matches for a complete split; return aggregate counts only."""
    if split not in {"dev", "test"} or sample.get("version") != 1:
        raise ValueError("invalid sample or split")
    dataset_id = sample.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("invalid dataset")
    cases = sample.get("cases")
    if not isinstance(cases, list):
        raise ValueError("invalid sample")
    by_id = {}
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("id"), str)
            or not case["id"]
            or case["id"] in by_id
            or not isinstance(case.get("text"), str)
            or case.get("split") not in {"dev", "test"}
        ):
            raise ValueError("invalid case")
        by_id[case["id"]] = case
    selected = {k: v for k, v in by_id.items() if v["split"] == split}
    if not selected:
        raise ValueError("empty split")

    def rows(payload: dict[str, Any]) -> dict[str, list[tuple[Any, ...]]]:
        if (
            payload.get("version") != 1
            or payload.get("dataset_id") != dataset_id
            or not isinstance(payload.get("labels"), list)
        ):
            raise ValueError("invalid label file")
        result = {}
        for row in payload["labels"]:
            if (
                not isinstance(row, dict)
                or row.get("id") not in by_id
                or row["id"] in result
                or not isinstance(row.get("annotations"), list)
            ):
                raise ValueError("invalid label row")
            case = by_id[row["id"]]
            keys = [_key(item, case["text"]) for item in row["annotations"]]
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate annotation")
            result[row["id"]] = keys
        if not set(selected).issubset(result):
            raise ValueError("incomplete split")
        return {k: result[k] for k in selected}

    expected, predicted = rows(gold), rows(predictions)
    tallies: dict[str, list[int]] = {
        label: [0, 0, 0]
        for label in (
            "overall",
            "structured_numeric",
            "categorical",
            *(f"numeric.{field}" for field in NUMERIC_FIELDS),
            *(
                f"facet.{group}.{value}"
                for group, values in FACETS.items()
                for value in values
            ),
        )
    }
    for case_id in selected:
        left, right = Counter(expected[case_id]), Counter(predicted[case_id])
        for key in left.keys() | right.keys():
            bucket = (
                f"{key[0]}.{key[1]}"
                if key[0] == "numeric"
                else f"{key[0]}.{key[1]}.{key[2]}"
            )
            for label in (
                "overall",
                bucket,
                "structured_numeric" if key[0] == "numeric" else "categorical",
            ):
                count = tallies.setdefault(label, [0, 0, 0])
                count[0] += left[key]
                count[1] += right[key]
                count[2] += min(left[key], right[key])
    return {key: Counts(*value) for key, value in sorted(tallies.items())}
