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
