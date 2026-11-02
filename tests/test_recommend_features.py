"""Evaluation cases for the proposed feature re-ranking (WO-021 deliverable 3).

The scaffold is not wired into `recommend`; these cases pin the properties any approved
weights must keep. Invented keys and statuses only."""

import pytest

from idx_agent.enrichment.effective import ELIGIBLE_FACETS
from idx_agent.enrichment.recommend_features import (
    ZERO_WEIGHTS,
    FeatureWeights,
    rerank,
    shared_features,
    uniform_weights,
)

SUBJECT = {"solar": "present", "pool": "present", "adu": "uncertain"}
STATUSES = {
    1: {},  # unknown everywhere
    2: {"solar": "present"},
    3: {"solar": "present", "pool": "present"},
    4: {"solar": "planned", "pool": "uncertain", "adu": "present"},
    5: {"solar": "stated_absent", "pool": "contradictory"},
    6: {"solar": "historical"},
}
# Equal semantic baseline, so only features can separate them.
TIED = [(k, 0.8) for k in sorted(STATUSES)]


def order(results):
    return [r.key for r in results]


def test_zero_weights_reproduce_the_semantic_order_exactly():
    ranked = [(9, 0.912345), (4, 0.9), (2, 0.9), (7, 0.5)]
    out = rerank(ranked, SUBJECT, STATUSES.get, ZERO_WEIGHTS)
    assert order(out) == [9, 2, 4, 7]  # score desc, then key asc, as today
    assert [r.total for r in out] == [0.912345, 0.9, 0.9, 0.5]
    assert all(r.feature == 0 and r.shared == () for r in out)


def test_equal_baselines_are_ordered_by_shared_present_features():
    out = rerank(TIED, SUBJECT, STATUSES.get, uniform_weights(0.01, 0.03))
    assert order(out) == [3, 2, 1, 4, 5, 6]
    assert out[0].shared == ("pool", "solar") and out[0].feature == 0.02


@pytest.mark.parametrize("key", [1, 4, 5, 6])
def test_missing_or_non_present_statuses_add_nothing_and_never_subtract(key):
    (only,) = rerank([(key, 0.8)], SUBJECT, STATUSES.get, uniform_weights(0.05, 0.1))
    assert only.feature == 0 and only.total == 0.8


def test_a_subject_status_that_is_not_present_earns_no_bonus():
    # adu is present on 4 but only uncertain on the subject.
    assert shared_features(SUBJECT, STATUSES[4], ELIGIBLE_FACETS) == []


def test_only_counted_facets_score_and_ineligible_ones_are_refused():
    solar_only = FeatureWeights(per_facet={"solar": 0.01}, cap=0.01)
    out = rerank(TIED, SUBJECT, STATUSES.get, solar_only)
    assert {r.key: r.shared for r in out}[3] == ("solar",)
    with pytest.raises(ValueError):
        FeatureWeights(per_facet={"office": 0.01}, cap=0.01)
    with pytest.raises(ValueError):
        FeatureWeights(per_facet={"solar": -0.01}, cap=0.01)


def test_the_cap_bounds_how_far_features_can_lift_a_candidate():
    ranked = [(1, 0.85), (3, 0.80)]
    capped = rerank(ranked, SUBJECT, STATUSES.get, uniform_weights(0.05, 0.04))
    assert order(capped) == [1, 3]  # 0.80 + 0.04 stays below 0.85
    lifted = rerank(ranked, SUBJECT, STATUSES.get, uniform_weights(0.05, 0.1))
    assert order(lifted) == [3, 1]


def test_stale_listings_earn_no_bonus():
    weights = uniform_weights(0.01, 0.03)
    changed = rerank(TIED, SUBJECT, STATUSES.get, weights, changed={3})
    assert {r.key: r.feature for r in changed}[3] == 0
    stale_subject = rerank(TIED, SUBJECT, STATUSES.get, weights, subject_fresh=False)
    assert order(stale_subject) == [k for k, _ in TIED]


def test_reranking_only_reorders_the_same_candidates():
    """The price check and the candidate set are untouched: same keys, same semantic
    scores; only the order and the feature part change."""
    ranked = [(k, 0.9 - k / 100) for k in sorted(STATUSES)]
    out = rerank(ranked, SUBJECT, STATUSES.get, uniform_weights(0.02, 0.04))
    assert sorted((r.key, r.semantic) for r in out) == sorted(ranked)


def test_the_offline_comparison_weights_cover_home_facets_only():
    pytest.importorskip("numpy")
    from collections import Counter

    from scripts.eval_recommend_features import AREA, candidate_weights

    counts = Counter({f: 100 * (i + 1) for i, f in enumerate(sorted(ELIGIBLE_FACETS))})
    weights = candidate_weights(counts, 10_000)
    for w in weights.values():
        assert not set(w.per_facet) & AREA
        assert set(w.per_facet) == ELIGIBLE_FACETS - AREA
    rarity = weights["rarity_median_0.01_cap_0.03"].per_facet
    assert sorted(rarity.values())[len(rarity) // 2] == pytest.approx(0.01, rel=0.2)
