# WO-018/021 omission-risk pilot v2 (WO-033)

**Skeleton: no results yet.** The sample is frozen. The model review of its 400 items
has not started; the owner allowed it to start once #144 and #154 are merged
(2026-11-03). Every results section below is a plan; no table holds data.

**Once filled, this is model review, not human review.** A Claude model will read each
remark against the annotation guide, review policy v4 and its v5 extension. Every
record carries `human_review: pending` until the owner's human pass.

**Pilot findings, not dataset-wide accuracy.** Like v1, this measures how often a feature
search would miss a listing because of an omission, on a small frozen sample. It makes no
production accuracy claim and changes no label.

## Why a second pilot

v1 (`docs/ENRICHMENT_OMISSION_PILOT.md`) found 6 omissions in 142 items. All were in
cue or labeled strata; 0 were in 46 no-cue items. The no-cue upper bound was 7.7%. That
is too wide to rule out a meaningful rate over about 849,000 no-cue listing x facet pairs,
which is where most of the population sits. v2 spends most of its items there.

## Method

**Population.** As in v1: the 54,888 extraction inputs minus the same 792 excluded
listings (250 benchmark, 40 deal-signal supplement, 32 WO-021 spot check, 471
diagnostic). The 142 v1 items are also excluded, as (listing, facet) items. Remaining:
848,575 no-cue, 60,808 cue and 7,073 labeled non-present pairs. That is v1's population
minus exactly its 46, 84 and 12 items.

**Unit, strata, cues, ranking, decisions.** Unchanged from v1. The unit is a listing and
an eligible facet whose effective status is not `present`. Strata are
`labeled_non_present`, `cue` and `no_cue`. Within a stratum, keys are ranked by
`sha256(seed|facet|stratum|key)`. The decisions are `omitted_present`,
`correctly_absent`, `non_present_mention` and `unclear`, plus `existing_status_check`
for labeled items.

**Strata source.** Statuses come from the v4 effective store as served today (file sha256
`7d9007b3…1bef`). The v5 ruling 8 cleanup overlay is **not** applied to the strata: it is
private and its human review is pending, so the strata stay those a search sees now.
Ruling 8 only turns `uncertain` into unknown. Neither status matches a search, so the
choice cannot create or hide an omission. The manifest counts the 6 labeled items the
overlay would move.

**Review standard.** Guide plus policy v4 plus v5 (`ENRICHMENT_REVIEW_POLICY_V5.md`).
v1 was judged under v4 alone. Rulings 1 to 7 refine what counts as present for six
facets, so a v2 judgment can differ from what v4 alone would give.

## Sample design

Seed `wo033-omission-20261103`. **400 items:** 240 no cue (60%), 120 cue (30%), 40
labeled non-present (10%). Each stratum total is split across facets by weight, largest
remainder first, ties broken by facet name. Weight is 1, plus 1 for the six limited
facets, plus 1 for the four facets the owner named from v1's omission patterns
(bonus_room, clubhouse, open_plan, near_grocery_mentioned). v1 also recorded single
omissions in stainless_appliances and condominium; both are already oversampled as
limited facets (weight 2) and get no third point.

| Weight | Facets | Labeled | Cue | No cue |
|---:|---|---:|---:|---:|
| 3 | near_grocery_mentioned (limited and owner-named) | 10 | 12 | 24 |
| 2 | condominium, garage, near_transit_mentioned, single_level, stainless_appliances | 6 each | 8 each | 16 each |
| 2 | bonus_room, clubhouse, open_plan (owner-named) | — | 8 each | 16 each |
| 1 | adu, community_pool, fitness_center, gated_community, hardwood, mountain_view, patio, pool, solar, walk_in_closet, water_view | — | 4 each | 8 each |

Labeled items are drawn for the six limited facets only, as in v1, because the policy
audit already read the other facets' labels. No stratum was short.

**Frozen artifacts (private, gitignored).** `data/enrichment/omission-pilot-v2/`:
- `sample.jsonl`, sha256 `a109dd99d45c9554a905d3d11690352dcc6f4b38e821823bbc7fe3a31738411d`.
- `manifest.json`, sha256 `64d4071d…bdc4a4`. It records the seed, design, allocation,
  population counts, exclusions, the v1 sample and manifest hashes, store hash and meta,
  the overlay note, the guide version and code commit `1346aae` (unmodified).

## Planned results (empty until the review)

Rates are omissions over items reviewed; unclear items stay in the denominator. Each
rate comes with a 95% Wilson interval.

1. **Pooled by stratum** (items, omitted, non-present, unclear, rate, Wilson): no cue,
   cue, labeled non-present, all.
2. **Pooled by facet group:** six limited facets, the three owner-named facets outside
   them (bonus_room, clubhouse, open_plan), the other 11.
3. **Per facet and stratum:** O/N/U of n with the stratum population. As in v1, these
   rows are not rates; small n is flagged.
4. **The no-cue upper bound,** two ways:
   - unweighted: the Wilson upper bound of the pooled 240;
   - population-weighted: each facet's no-cue rate weighted by its no-cue population,
     with the interval defined below. The sample oversamples nine facets, so the
     unweighted pool is not population-representative.
5. **Existing non-present statuses** (40 labeled items): correct, wrong, unclear. The 6
   items the ruling 8 overlay would remove are counted separately.
6. **Patterns** in the omissions and in the cue matches that were not mentions,
   aggregate only.
7. **New unresolved questions:** definitional cases v4 plus v5 do not settle. Items stay
   `unclear` and are listed privately.

**Wilson interval.** For k omissions in n items, with z = 1.96:
centre = (p + z²/2n) / (1 + z²/n),
half-width = z·sqrt(p(1-p)/n + z²/4n²) / (1 + z²/n),
clipped to [0, 1]. It is `omission_pilot.wilson`, the function v1 used. Planning values:
- 0 of 240 gives at most 1.6%;
- 0 of 120 gives at most 3.1%;
- 0 of 40 gives at most 8.8%;
- v1 and v2 no-cue pooled, 0 of 286, would give at most 1.3%.

These are unweighted. The population-weighted figure is wider; see below.

**Population-weighted no-cue rate and its interval (fixed before the review).** Let N_f
be facet f's no-cue population in the manifest (`population_counts`, sum N = 848,575),
n_f its no-cue items reviewed (the allocation: 24, 16 or 8; unclear items stay in), and
k_f its `omitted_present` count.
- Estimate: p_w = sum over f of (N_f / N) x (k_f / n_f). Each item in facet f carries
  weight N_f / n_f.
- Kish effective sample size: n_eff = (sum of weights)² / (sum of squared weights)
  = N² / sum over f of (N_f² / n_f). Design effect: deff = n / n_eff, with n = 240.
- Interval: the Wilson formula above with p = p_w and n = n_eff, not rounded.
- From the manifest populations and the frozen allocation: **n_eff = 207.0, deff = 1.16.**
  These depend only on the design, so they are fixed now.
- Computed from the per-facet no-cue counts in `aggregates.json` and the manifest
  populations; aggregate counts only.

Weighted planning values:
- 0 omissions gives at most **1.8%** (unweighted: 1.6%).
- One omission gives p_w between 0.21% (garage) and 0.72% (water_view, a weight-1
  facet), with an upper bound of 2.2-3.1%.
- v1 + v2 no-cue pooled (286 items): n_eff = 253.1 (deff 1.13), weights from v1's
  population. 0 omissions gives at most 1.5% (unweighted: 1.3%). This is approximate:
  v2 was drawn from v1's population minus v1's items, a difference of 46 pairs.

## Comparison with v1 (planned)

v1's pooled numbers, under v4: overall 6 of 142, 4.2% (2.0-8.9%). By stratum: cue 5/84,
6.0% (2.6-13.2%); no cue 0/46, at most 7.7%; labeled 1/12, 8.3% (1.5-35.4%).

The v2 report will:
- put the same pooled rows side by side with v1's;
- give a pooled v1 + v2 no-cue figure, valid because the item sets are disjoint and the
  rule and seed scheme are the same;
- flag where v5 rulings, not the sample, explain a difference.

v1 judgments are not re-made under v5 here.

## Decision: what rate would justify a v3 extraction

**Accepted by the owner on 2026-11-03, before the review:** the 1% weighted no-cue
threshold and the interval method (Wilson on the Kish effective sample size). They are
no longer proposals. They were written before the review, so the result cannot shape
them.

- **Measure:** the population-weighted no-cue omission rate p_w, with the Wilson
  interval on the Kish effective sample size (see above). Cue omissions can be
  recovered more cheaply, by re-reading cue matches, so they argue for a targeted re-read,
  not a new extraction.
- **Threshold: 1%.** That is about 8,500 silently missed pairs out of 848,575.
  It is about four times the roughly 2,200 stored-label errors WO-018 estimated (1,600
  rule-kept, 600 read). Above it, misses would outweigh known wrong labels, and only a
  new extraction reaches them. Below it, a paid full run buys less than targeted fixes.
- **Reading** (95% weighted interval):
  - The lower bound is at or above 1%: a v3 extraction is justified on omission
    grounds.
  - The upper bound is below 1%: it is not.
  - Otherwise the result is inconclusive. The owner then chooses between pooling with v1
    (286 items) and a further sample.
- **What v2 can show alone** (weighted, n_eff = 207.0):
  - 0 omissions gives an upper bound of 1.8%: inconclusive.
  - The lower bound clears 1% once p_w is about 2.4% or more, that is about 4.9
    effective omissions (p_w x n_eff). The count of raw omissions that reaches it depends
    on their facets. Unweighted, it is 6 of 240 (1.15-5.3%).
  - Ruling 1% out with zero omissions needs n_eff of at least 381. At v2's design effect
    that is about 442 no-cue items. Pooled with v1 (n_eff 253.1) it needs about 149 more
    no-cue items drawn in v2's proportions, or about 119 drawn in proportion to
    population.
  - Unweighted, the corresponding figures would be 381 items, or v1 + v2 plus 95; the
    weighted figures above replace them.
- **Not covered:** cost, which comes from the provider console once a v3 run is scoped
  (WO-034 freezes the v3 contract separately); and per-facet decisions, which this sample
  cannot support.

## What this does not do

It does not:
- re-audit the 54,888 results or re-judge v1 under v5;
- apply the ruling 8 overlay or change any overlay, store, label or search;
- re-run extraction or make a paid call;
- estimate dataset-wide recall.

The judgments, once made, will be one model reviewer's and may share the extractor's
biases.

## How the review will run (once #144 and #154 are merged)

From the main checkout, all files under the gitignored `data/enrichment/`:

```
python scripts/omission_pilot.py --pilot v2 packet
python scripts/omission_pilot.py --pilot v2 record --kind model \
  --draft data/enrichment/omission-pilot-v2/judgments-draft.jsonl
python scripts/omission_pilot.py --pilot v2 aggregate --name aggregates.json
```

The packet carries WO-026's output-confinement and frozen source-hash checks. `record`
requires the v2 guide version and `human_review: pending` on model records. A human pass
uses `record --kind human` as in v1.
