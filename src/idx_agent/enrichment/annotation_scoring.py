"""Offline scoring of synthetic span annotations; never accesses data or a model."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from idx_agent.domain.enrichment import SyntheticAnnotationCase, SyntheticFacetEvidence


@dataclass(frozen=True)
class Counts:
    """Exact-match counts; undefined precision/recall use None, never a fake score."""

    expected: int
    predicted: int
    correct: int

    @property
    def precision(self) -> float | None:
        return self.correct / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.correct / self.expected if self.expected else None


def _key(evidence: SyntheticFacetEvidence) -> tuple:
    return (
        evidence.facet.group.value,
        evidence.facet.value,
        evidence.start,
        evidence.end,
        evidence.polarity,
        evidence.temporality,
    )


def score_case(
    expected: SyntheticAnnotationCase, predicted: SyntheticAnnotationCase
) -> Counts:
    """Count exact span, facet, polarity and time matches for one synthetic case.

    Neither text nor excerpts are logged or returned. A different case, split or
    original text is an error, not a score. This is not a real-data benchmark.
    """
    if (expected.id, expected.split, expected.text) != (
        predicted.id,
        predicted.split,
        predicted.text,
    ):
        raise ValueError("annotation cases do not match")
    gold = Counter(_key(item) for item in expected.annotations)
    candidate = Counter(_key(item) for item in predicted.annotations)
    return Counts(
        expected=sum(gold.values()),
        predicted=sum(candidate.values()),
        correct=sum((gold & candidate).values()),
    )


def score_breakdown(
    expected: SyntheticAnnotationCase, predicted: SyntheticAnnotationCase
) -> dict[str, dict[str, Counts]]:
    """Return exact counts by facet and polarity without exposing source text."""
    score_case(expected, predicted)  # validates case identity and original text
    gold = Counter(_key(item) for item in expected.annotations)
    candidate = Counter(_key(item) for item in predicted.annotations)
    matches = gold & candidate

    def group(index: int) -> dict[str, Counts]:
        keys = sorted({key[index] for key in gold.keys() | candidate.keys()})
        return {
            label: Counts(
                expected=sum(
                    count for key, count in gold.items() if key[index] == label
                ),
                predicted=sum(
                    count for key, count in candidate.items() if key[index] == label
                ),
                correct=sum(
                    count for key, count in matches.items() if key[index] == label
                ),
            )
            for label in keys
        }

    # Facet identifiers include their group, so identical values cannot collide.
    by_facet = {}
    for group_name, value in sorted(
        {(key[0], key[1]) for key in gold.keys() | candidate.keys()}
    ):
        by_facet[f"{group_name}.{value}"] = Counts(
            expected=sum(
                count for key, count in gold.items() if key[:2] == (group_name, value)
            ),
            predicted=sum(
                count
                for key, count in candidate.items()
                if key[:2] == (group_name, value)
            ),
            correct=sum(
                count
                for key, count in matches.items()
                if key[:2] == (group_name, value)
            ),
        )
    return {"facet": by_facet, "polarity": group(4)}


@dataclass(frozen=True)
class DatasetCounts:
    """Aggregate counts for a single declared synthetic split."""

    split: str
    cases: int
    overall: Counts
    by_facet: dict[str, Counts]
    by_polarity: dict[str, Counts]


def _add_counts(left: Counts, right: Counts) -> Counts:
    return Counts(
        expected=left.expected + right.expected,
        predicted=left.predicted + right.predicted,
        correct=left.correct + right.correct,
    )


def score_dataset(
    expected: list[SyntheticAnnotationCase], predicted: list[SyntheticAnnotationCase]
) -> DatasetCounts:
    """Aggregate a complete, single-split synthetic set with exact case identity.

    Empty, duplicate, missing, extra or cross-split cases are errors, not scores.
    No source text or spans are returned; no files or providers are accessed.
    """
    if not expected or not predicted:
        raise ValueError("annotation dataset is empty")
    gold = {case.id: case for case in expected}
    candidate = {case.id: case for case in predicted}
    if len(gold) != len(expected) or len(candidate) != len(predicted):
        raise ValueError("duplicate annotation case")
    if gold.keys() != candidate.keys():
        raise ValueError("annotation case sets do not match")
    splits = {case.split for case in expected} | {case.split for case in predicted}
    if len(splits) != 1:
        raise ValueError("annotation datasets must use one split")
    overall = Counts(0, 0, 0)
    facets: dict[str, Counts] = {}
    polarities: dict[str, Counts] = {}
    for case_id in sorted(gold):
        left, right = gold[case_id], candidate[case_id]
        overall = _add_counts(overall, score_case(left, right))
        breakdown = score_breakdown(left, right)
        for name, target in (("facet", facets), ("polarity", polarities)):
            for key, counts in breakdown[name].items():
                target[key] = _add_counts(target.get(key, Counts(0, 0, 0)), counts)
    return DatasetCounts(next(iter(splits)), len(gold), overall, facets, polarities)
