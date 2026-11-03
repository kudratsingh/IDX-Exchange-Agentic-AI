# Feature-aware recommendations: decision record (WO-021 deliverable 3, draft)

Experimental only. `recommend`'s ranking is unchanged, and no weight here is approved.

## Today
`recommend` takes the subject's own stored embedding and ranks active listings that
share its city and subtype, with a list price within 25% of the subject's. Ranking is
cosine similarity, with ties broken by key. Candidates are re-checked in SQL. Each
recommendation carries its own comparable-sales price check, which never depends on the
ranking. `score_components` holds only `semantic`.

## Proposal
Re-rank the at most 200 semantic candidates before the fetch:

**score = semantic + min(cap, Σ w(f))**

The sum runs over eligible features `f` that are `present` on both the subject and the
candidate. The code is `src/idx_agent/enrichment/recommend_features.py` (not wired in).
- **Hard filters are unchanged:** city, subtype, price band, SQL re-check, price checks.
  Features only reorder the same candidates.
- **Never a penalty:** missing, uncertain, planned, historical, negated or contradictory
  statuses add nothing and never subtract.
- **Freshness:** no bonus for a candidate changed since the snapshot, and none for anyone
  when the subject changed. These are the same freshness rules as search and badges.
- **Area facets excluded:** `near_grocery_mentioned` and `near_transit_mentioned` are
  left out, because they describe the area, not the home.
- **Zero weights reproduce today's order exactly (tested).** The explanation would add
  "Also mentions: solar, pool" from the shared features, with the existing limitation
  line.

## Offline effect on real data
`scripts/eval_recommend_features.py` ran on 400 seeded subjects, using stored vectors
only, with no embedding calls. 339 subjects had at least 6 neighbours.
- **Baseline:** the top 5 already shares 1.52 present features per card with the
  subject. The median score gap between rank 1 and rank 5 is only 0.046.
- **Effect of each candidate weight:**

| Candidate weights | Top-5 set changed | Replaced per subject | Shared/card after | Semantic loss/card |
|---|---|---|---|---|
| 0.005 each, cap 0.015 | 18% | 0.20 | 1.59 | 0.0002 |
| 0.01 each, cap 0.03 | 37% | 0.43 | 1.66 | 0.0007 |
| 0.02 each, cap 0.06 | 56% | 0.76 | 1.78 | 0.0022 |
| Rarity-weighted, median 0.01, cap 0.03 | 29% | 0.33 | 1.63 | 0.0004 |

At 0.02 a few picks came from beyond rank 20. That is the point where features start to
override what the description says.

## Worked example (invented)
The subject has solar and a pool. Candidates A, B and C all score 0.80 semantically:
- A has both features.
- B has solar only.
- C has solar planned and a pool marked uncertain.

With 0.01 each, the order becomes A (0.82), B (0.81), C (0.80). C is never pushed below
an equal candidate for what its listing does not confirm.

## Evaluation cases (tests/test_recommend_features.py)
- Zero weights give the exact order.
- Equal baselines are ordered by shared present features.
- Non-present statuses add nothing.
- Subject statuses that are not present are ignored.
- Uncounted and ineligible facets are refused.
- The cap bounds the lift.
- Changed listings get no bonus.
- Re-ranking only permutes the same candidates, so the price-check inputs are unchanged.
- The offline comparison excludes area facets.

## Regression risks
- **Description intent drift:** at higher weights, a listing that matches the subject's
  description less well can outrank a closer one because of common features.
- **Extraction errors:** an estimated 1,600 rule-kept and 600 read errors remain
  uncorrected. They now affect order, not only search.
- **Common facets dominate uniform weights:** garage (25k listings) and open plan (18k)
  count as much as rare ones unless rarity-weighted.
- **Explanation honesty:** "also mentions" must not imply the others lack it.
- **Existing suite:** the recommendation eval cases pin exact ranked keys and would need
  a new set version if order changes.

## Decisions needed from the owner
1. Whether features may change the order at all, or only add an explanation line. A
   line only is the lowest risk.
2. If order may change: the weight scheme (uniform or rarity-weighted) and the exact
   per-feature weight and cap.
   - The table above is the measured tradeoff.
   - A conservative choice is 0.005 each with a 0.015 cap.
3. Whether user-stated feature preferences ("like this but with solar") become a
   `recommend` argument, either as a hard filter or as a boost. Either is a contract
   change.
4. Which facets count: confirm excluding the two area facets, and whether `condominium`
   counts given that subtype is already a hard filter.
5. Whether to re-version the recommendation eval set, or keep the old order as the
   regression baseline.
