"""Proposed remark-feature re-ranking for recommendations (WO-021 deliverable 3).

`rerank` is an evaluation scaffold: `recommend` never calls it and no weight is approved
(WO-024 shows shared features only). Only features present on both listings add; none
subtract. Zero weights give exactly the semantic order."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

from idx_agent.enrichment.access import present_in
from idx_agent.enrichment.effective import ELIGIBLE_FACETS

__all__ = [
    "ZERO_WEIGHTS",
    "FeatureWeights",
    "Reranked",
    "present_features",
    "rerank",
    "shared_features",
    "uniform_weights",
]


@dataclass(frozen=True)
class FeatureWeights:
    """Per-facet bonus for a feature present on both listings, and a total cap."""

    per_facet: Mapping[str, float] = field(default_factory=dict)
    cap: float = 0.0

    def __post_init__(self) -> None:
        unknown = set(self.per_facet) - ELIGIBLE_FACETS
        if unknown:
            raise ValueError(f"ineligible facets {sorted(unknown)}")
        if self.cap < 0 or any(w < 0 for w in self.per_facet.values()):
            raise ValueError("feature weights and the cap must not be negative")


ZERO_WEIGHTS = FeatureWeights()


def uniform_weights(
    weight: float, cap: float, facets: Collection[str] = ELIGIBLE_FACETS
) -> FeatureWeights:
    """The same bonus for every listed facet."""
    return FeatureWeights(per_facet=dict.fromkeys(sorted(facets), weight), cap=cap)


def present_features(statuses: Mapping[str, str]) -> frozenset[str]:
    """Eligible facets whose effective status is present (the shared WO-023 rule)."""
    return present_in(dict(statuses))


def shared_features(
    subject: Mapping[str, str], candidate: Mapping[str, str], facets: Collection[str]
) -> list[str]:
    """Facets present on both listings and counted by the weights, sorted."""
    both = present_features(subject) & present_features(candidate)
    return sorted(both & set(facets))


@dataclass(frozen=True)
class Reranked:
    """One candidate after re-ranking, with its score parts."""

    key: int
    semantic: float
    feature: float
    total: float
    shared: tuple[str, ...]


def rerank(
    ranked: Sequence[tuple[int, float]],
    subject_statuses: Mapping[str, str],
    statuses_of: Callable[[int], Mapping[str, str]],
    weights: FeatureWeights,
    *,
    subject_fresh: bool = True,
    changed: Collection[int] = (),
) -> list[Reranked]:
    """Re-rank (key, semantic score) pairs by semantic score plus the feature bonus.

    No bonus at all for a stale subject, none for a candidate in `changed`. Totals are
    rounded to 6 decimals; ties keep today's rule: total descending, then key ascending.
    """
    out: list[Reranked] = []
    for key, semantic in ranked:
        shared: list[str] = []
        if subject_fresh and key not in changed and weights.per_facet:
            shared = shared_features(
                subject_statuses, statuses_of(key), weights.per_facet
            )
        bonus = min(weights.cap, sum(weights.per_facet[f] for f in shared))
        total = round(semantic + bonus, 6)
        out.append(Reranked(key, semantic, round(bonus, 6), total, tuple(shared)))
    return sorted(out, key=lambda r: (-r.total, r.key))
