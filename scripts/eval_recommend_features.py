"""Offline effect of candidate feature weights on recommendation order (WO-021).

Reads the private semantic index (stored vectors only: nothing embedded or paid) and
the private effective-facet store, re-ranks sampled subjects with `rerank`, and prints
aggregate counts only. No SQL re-check, so the candidates are approximate."""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

from idx_agent.domain.comps import price_band
from idx_agent.enrichment.access import AREA_FACETS
from idx_agent.enrichment.effective import ELIGIBLE_FACETS
from idx_agent.enrichment.recommend_features import (
    FeatureWeights,
    rerank,
    uniform_weights,
)
from idx_agent.semantic.index import load_index, read_meta
from idx_agent.semantic.neighbors import SubjectNotIndexed, rank_neighbors

TOP = 5
POOL = 200
HOME = ELIGIBLE_FACETS - AREA_FACETS


def candidate_weights(counts: Counter, listings: int) -> dict[str, FeatureWeights]:
    """The weightings compared; placeholders for the owner's decision, not proposals
    of record. Rarity: log(listings / count) scaled so the median facet gets 0.01."""
    idf = {f: math.log(listings / max(counts[f], 1)) for f in HOME}
    middle = statistics.median(idf.values())
    rarity = {f: round(0.01 * v / middle, 6) for f, v in idf.items()}
    return {
        "uniform_0.005_cap_0.015": uniform_weights(0.005, 0.015, HOME),
        "uniform_0.01_cap_0.03": uniform_weights(0.01, 0.03, HOME),
        "uniform_0.02_cap_0.06": uniform_weights(0.02, 0.06, HOME),
        "rarity_median_0.01_cap_0.03": FeatureWeights(per_facet=rarity, cap=0.03),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--subjects", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20261102)
    args = parser.parse_args()
    meta = read_meta(args.index)
    index = load_index(args.index, meta.model, meta.dims)
    store = sqlite3.connect(f"{args.store.resolve().as_uri()}?mode=ro", uri=True)
    statuses: dict[int, dict[str, str]] = {}
    for key, facet, status in store.execute(
        "SELECT listing_key, facet, status FROM facets"
    ):
        statuses.setdefault(int(key), {})[facet] = status
    listings = store.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    counts = Counter(
        f for s in statuses.values() for f, v in s.items() if v == "present"
    )
    weights = candidate_weights(counts, listings)
    rng = random.Random(args.seed)
    eligible_rows = [
        row
        for row in range(index.rows)
        if index.attrs.city[row]
        and index.attrs.property_subtype[row]
        and index.attrs.list_price[row] > 0
    ]
    sample = rng.sample(eligible_rows, min(args.subjects, len(eligible_rows)))
    stats = {name: Counter() for name in weights}
    gaps, no_features, few = [], 0, 0
    for row in sample:
        key = int(index.keys[row])
        low, high = price_band(int(index.attrs.list_price[row]))
        try:
            ranked = rank_neighbors(
                index,
                key,
                str(index.attrs.city[row]),
                str(index.attrs.property_subtype[row]),
                low,
                high,
                POOL,
            )
        except SubjectNotIndexed:
            continue
        if len(ranked) <= TOP:
            few += 1
            continue
        gaps.append(ranked[0][1] - ranked[TOP - 1][1])
        subject = statuses.get(key, {})
        if not any(v == "present" for v in subject.values()):
            no_features += 1
        base = [k for k, _ in ranked[:TOP]]
        base_scores = {k: s for k, s in ranked}
        for name, w in weights.items():
            out = rerank(ranked, subject, lambda k: statuses.get(k, {}), w)
            top = [r.key for r in out[:TOP]]
            changed = len(set(top) - set(base))
            c = stats[name]
            c["subjects"] += 1
            c["top_set_changed"] += changed > 0
            c["top_order_changed"] += top != base
            c["replaced"] += changed
            c["shared_base_x1000"] += round(
                1000 * sum(len(r.shared) for r in out if r.key in base) / TOP
            )
            c["shared_new_x1000"] += round(
                1000 * sum(len(r.shared) for r in out[:TOP]) / TOP
            )
            c["semantic_loss_x1e6"] += round(
                1e6
                * (sum(base_scores[k] for k in base) - sum(base_scores[k] for k in top))
                / TOP
            )
            c["from_beyond_20"] += sum(
                1 for k in top if k not in [x for x, _ in ranked[:20]]
            )
    report = {
        "subjects_sampled": len(sample),
        "skipped_fewer_than_6_neighbours": few,
        "subjects_without_present_features": no_features,
        "median_score_gap_rank1_to_rank5": round(statistics.median(gaps), 4),
        "weights": {},
    }
    for name, c in stats.items():
        n = c["subjects"] or 1
        report["weights"][name] = {
            "share_top5_set_changed": round(c["top_set_changed"] / n, 3),
            "share_top5_order_changed": round(c["top_order_changed"] / n, 3),
            "mean_replaced_in_top5": round(c["replaced"] / n, 2),
            "mean_shared_per_card_before": round(c["shared_base_x1000"] / n / 1000, 2),
            "mean_shared_per_card_after": round(c["shared_new_x1000"] / n / 1000, 2),
            "mean_semantic_loss_per_card": round(c["semantic_loss_x1e6"] / n / 1e6, 4),
            "picks_from_beyond_rank_20": c["from_beyond_20"],
        }
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
