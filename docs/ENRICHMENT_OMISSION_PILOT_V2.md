# WO-018/021 omission-risk pilot v2 (WO-033)

**Results of the model review (2026-11-03).** All 400 frozen items were reviewed after
#144 and #154 merged. Every number below is an aggregate of private judgments; no key,
remark or quote is in this file.

**This is model review, not human review.** Claude (Opus 5.5) agent sessions read each
remark against the annotation guide, review policy v4 and its v5 extension, and the
owner's three approved decisions. Every record carries `human_review: pending` until the
owner's human pass. No paid or provider API call was made: the reading was done inside
this agent session.

**Headline.** The population-weighted no-cue omission rate is **0.56%**, 95% interval
**0.11% to 2.81%** (Wilson on Kish n_eff 207.0). The interval contains the accepted 1%
threshold, so **the result is inconclusive** under the accepted rule. This is a finding
for the owner, not a decision.

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

## Results plan (fixed before the review)

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

## Results (model review, human review pending)

The plan above was followed as written. Rates are omissions over items reviewed, with
unclear items in the denominator, and 95% Wilson intervals.

**How the review ran.**
- 400 of 400 items have a validated model judgment. All carry the v2 guide version and
  `human_review: pending`, and each records its reviewer, rubric hash and the sample
  hash added by `record`.
- The packet was made by the CLI and split into 8 shards of 50: 30 no cue, 15 cue and
  5 labeled each, all 20 facets in every shard. A separate agent session read each
  shard against a private rubric. The rubric restates the guide, v4 with its
  clarifications, v5 rulings 1-8 and the three approved decisions.
- **Second read.** A further session re-read 71 items, chosen from the first-read
  decisions alone:
  - all 31 first-read omissions or unclear calls;
  - a seeded random 40 of the other 369.
  It agreed on 66 of 71 (93.0%): 40 of 40 random items (100%) and 26 of 31 targeted
  items (83.9%).
- **Adjudication.** Each of the 5 disagreements was decided against the rubric:
  - first read upheld once;
  - second read adopted four times.
  Final judgment = first read, unless adjudicated.
- The second-read rate is agreement between two model readings. It is not an accuracy
  figure, and it says nothing about human agreement.

**1. Pooled by stratum** (O = omitted, N = non-present mention, U = unclear).

| Stratum | Items | O | N | U | Rate | Wilson 95% |
|---|---:|---:|---:|---:|---:|---|
| No cue | 240 | 2 | 0 | 0 | 0.83% | 0.23-2.99% |
| Cue | 120 | 14 | 5 | 3 | 11.7% | 7.1-18.6% |
| Labeled non-present | 40 | 5 | 14 | 5 | 12.5% | 5.5-26.1% |
| All | 400 | 21 | 19 | 8 | 5.25% | 3.5-7.9% |

These pools are not population-representative. The sample oversamples nine facets,
near_grocery_mentioned most of all. The cue figure weighted by cue population is 6.2%
(2.0-17.8%, n_eff 42.2).

**2. Pooled by facet group.**

| Group | No cue | Cue | Labeled | All |
|---|---|---|---|---|
| Six limited facets | 0/104 (at most 3.6%) | 8/52, 15.4% (8.0-27.5%) | 5/40, 12.5% (5.5-26.1%) | 13/196, 6.6% |
| bonus_room, clubhouse, open_plan | 2/48, 4.2% (1.2-14.0%) | 5/24, 20.8% (9.2-40.5%) | — | 7/72, 9.7% |
| Other 11 | 0/88 (at most 4.2%) | 1/44, 2.3% (0.4-11.8%) | — | 1/132, 0.8% |

**3. Per facet and stratum.** Cells read O/N/U of n. These are counts, not rates.

Every facet's n is 24 or less, so no single facet supports a rate. Ten facets are left
out because all their items (8 no cue and 4 cue each) are `correctly_absent`:
community_pool, fitness_center, gated_community, hardwood, mountain_view, patio, pool,
solar, walk_in_closet and water_view.

| Facet | No cue | Cue | Labeled |
|---|---|---|---|
| near_grocery_mentioned | 0/0/0 of 24 | 6/0/0 of 12 | 4/1/3 of 10 |
| bonus_room | 1/0/0 of 16 | 3/0/0 of 8 | — |
| open_plan | 1/0/0 of 16 | 1/0/0 of 8 | — |
| clubhouse | 0/0/0 of 16 | 1/0/0 of 8 | — |
| condominium | 0/0/0 of 16 | 1/0/0 of 8 | 0/2/1 of 6 |
| stainless_appliances | 0/0/0 of 16 | 1/0/1 of 8 | 0/4/0 of 6 |
| single_level | 0/0/0 of 16 | 0/1/1 of 8 | 1/0/0 of 6 |
| garage | 0/0/0 of 16 | 0/4/1 of 8 | 0/4/0 of 6 |
| near_transit_mentioned | 0/0/0 of 16 | 0/0/0 of 8 | 0/3/1 of 6 |
| adu | 0/0/0 of 8 | 1/0/0 of 4 | — |

**4. No-cue upper bound.**
- Unweighted: 2 of 240, 0.83% (0.23-2.99%).
- **Population-weighted, the accepted method: p_w = 0.56%, 95% interval 0.11-2.81%,
  n_eff 207.0, deff 1.16.** These come from the new `weighted_by_stratum` field of
  `aggregates.json`, computed by `omission_pilot.weighted_rate`. They match the design
  values fixed before the review.
- Both no-cue omissions are on owner-named facets of weight 2, with 16 items each:
  - bonus_room, 5.1% of the no-cue population: an existing room offered for a
    second, living use, counted under v5 ruling 7;
  - open_plan, 3.9%: connected living spaces described without open-plan wording.
- The other 18 facets show 0 no-cue omissions in 192 items.

**Sensitivity of the weighted no-cue figure** (all on n_eff 207.0):

| Case | p_w | 95% interval |
|---|---:|---|
| Final judgments | 0.56% | 0.11-2.81% |
| Unclear counted as omitted (no unclear no-cue items remain) | 0.56% | 0.11-2.81% |
| The second read's call on the contested bonus_room item | 0.24% | 0.03-2.27% |
| One adjudicated no-cue item (first read unclear) counted as an omission | 0.87% | 0.23-3.31% |
| No omissions at all | 0.00% | 0.00-1.82% |

Every case contains 1%. The condo flag below touches no no-cue item.

**5. Existing non-present statuses** (40 labeled items): 12 correct, 28 wrong.

| Stored status | Items | Correct | Wrong |
|---|---:|---:|---:|
| uncertain | 29 | 2 | 27 |
| planned | 8 | 7 | 1 |
| stated_absent | 2 | 2 | 0 |
| historical | 1 | 1 | 0 |

The 27 wrong `uncertain` labels split as follows:
- 16 have no supported mention at all (`unsupported_uncertain_label`);
- 5 are plain affirmations, so the facet is omitted;
- 5 are unclear on the decision but wrong either way, because the remark has no doubt
  wording;
- 1 is a different non-present status.

The 6 sampled items the ruling 8 overlay would remove (condominium 2, garage 2,
stainless 2) are all judged unsupported uncertain labels. Each is `correctly_absent`
with the status wrong, which is what the overlay does.

**Condo subtype not checked.** Two condominium items rest on a direct condo claim, and
the subtype column that ruling 4 says decides is not available offline:
- 1 cue omission;
- 1 labeled item whose status was judged correct.
Without the cue omission, cue is 13/120, 10.8% (6.4-17.7%), and all is 20/400, 5.0%
(3.3-7.6%). No-cue is unchanged.

**6. Patterns** (aggregate only).
- **Grocery dominates.** near_grocery_mentioned has 10 of the 21 omissions: 6 of 12
  cue items and 4 of 10 labeled.
  - The cue omissions name groceries or a grocer plainly among nearby places.
  - One is a warehouse club, counted under v5 ruling 1.
  - The labeled ones carry an `uncertain` label with no doubt wording.
- **Owner-named facets.** bonus_room, clubhouse and open_plan have 7 of the 21
  omissions, and both no-cue omissions. The misses are flexible-use rooms and lofts,
  connected layouts without the key phrase, and shared recreation rooms.
- **v5 changed outcomes.** 15 judgments carry `v5_changed_outcome`; 6 of them are
  omissions, which v4 alone might not have counted:
  - bonus_room 2;
  - clubhouse 1;
  - grocery 2;
  - stainless outdoor kitchen 1.
- **Cue matches are mostly not mentions.** 96 of the 160 cue and labeled items carry
  `cue_not_mention`. The causes are parking counts, comparisons, road wording, proximity
  to a facility, and other objects.
- **No-cue items are almost always truly absent.** 238 of 240 are `correctly_absent`.
  None is a non-present mention, and after adjudication none is unclear.

**7. Unclear cases** (8: 3 cue, 5 labeled, 0 no-cue), by type:
- grocery: is a named shop or hall called a market a grocery retailer? (3 labeled)
- transit: is a scheduled passenger ferry public transit? (1 labeled)
- condominium: wording only about a multi-unit building or HOA, with the only condo
  word in a comparison (1 labeled)
- garage: an assigned space in a shared building garage (1 cue)
- single_level: a unit whose living space is on one floor, above an entry stair (1 cue)
- stainless: a stainless part built into an outdoor cooking structure (1 cue)

All 8 are on limited facets. Counting them as omissions moves the labeled pool to 10/40
and cue to 17/120. It does not move the no-cue figure.

**New unresolved questions for the owner** (own words; items are listed privately):
1. Does "market" in a shop's name, or a public market hall, make it a named grocery
   retailer?
2. Is a scheduled passenger ferry public transit under v5 ruling 2?
3. Does an assigned space in a shared building garage count as the unit's garage?
4. Is a unit whose rooms are all on one floor, reached by an entry stair, single level?
5. Is a stainless insert in a built outdoor barbecue a stainless outdoor-kitchen
   appliance?
6. Should a utility room offered for a second, living use count as a bonus room? This
   decides one of the two no-cue omissions. The adjudicator counted it under v5 ruling
   7; the table above shows the estimate without it.
7. The condo subtype check (ruling 4) is still to be run where MySQL is in scope.

One patio question raised in review was settled by v4 ruling 4 in adjudication: a
cover's product name does not make the covered space a patio.

**Private files** (`data/enrichment/omission-pilot-v2/`, owner-only, new):
- `judgments.jsonl`, sha256 `4d0d5653…1159`;
- `aggregates.json`, `bb14a396…fcbe3`;
- `judgments-draft.jsonl`, `ca1737c0…fbc7c`;
- under `review/`: the rubric (`a5090f62…a1720`), 8 shard packets and judgments, the
  shard index, `second-read.jsonl` (`8f4ef062…5687`) and `adjudication.jsonl`
  (`e8e27e35…3894`).

The frozen sample and manifest and every v1 file have the same hashes as before the
review.

## Comparison with v1

v1 was judged under v4 alone; v2 under v4 plus v5 and the approved decisions. The item
sets are disjoint.

| Stratum | v1 (142 items) | v2 (400 items) | v1 + v2 pooled |
|---|---|---|---|
| No cue, unweighted | 0/46, at most 7.7% | 2/240, 0.83% (0.23-2.99%) | 2/286, 0.70% (0.19-2.51%) |
| No cue, weighted | — | 0.56% (0.11-2.81%), n_eff 207.0 | 0.50% (0.10-2.37%), n_eff 253.1 |
| Cue | 5/84, 6.0% (2.6-13.2%) | 14/120, 11.7% (7.1-18.6%) | 19/204, 9.3% (6.0-14.1%) |
| Labeled non-present | 1/12, 8.3% (1.5-35.4%) | 5/40, 12.5% (5.5-26.1%) | — |
| All | 6/142, 4.2% (2.0-8.9%) | 21/400, 5.25% (3.5-7.9%) | — |

The pooled weighted no-cue figure uses v1's populations, as planned. It is approximate,
because v2's population is v1's minus 46 pairs.

The higher v2 cue and labeled rates come mostly from the design, not from a change in
the extractor:
- v2 gives near_grocery_mentioned and the three owner-named facets more items, and
  those facets carry most of the omissions.
- Weighted by population, the v2 cue rate is 6.2%, close to v1's 6.0%.
- v5 rulings account for 4 of the 14 cue omissions and 1 of the 5 labeled omissions.

The labeled pool is not pooled across pilots: v2 judges `uncertain` labels with ruling 8
and the doubt-wording decision. v1 judgments are not re-made under v5 here.

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

### Reading of the v2 result: inconclusive

This is a finding for the owner, not a decision.

- **Weighted no-cue rate:** p_w = 0.56%, 95% interval 0.11% to 2.81%, n_eff 207.0.
- **Against the rule:**
  - The lower bound, 0.11%, is below 1%, so a v3 extraction is **not** shown to be
    justified on omission grounds.
  - The upper bound, 2.81%, is at or above 1%, so it is **not** ruled out either.
  - Under the accepted rule, the result is **inconclusive**.
- **Robustness:** the same holds in every sensitivity case in Results section 4.
  - The upper bound ranges from 1.82% (no omissions) to 3.31% (one more omission).
  - The lower bound never exceeds 0.23%.
- **Pooled with v1,** the rule's next option: 0.50% (0.10-2.37%), n_eff 253.1. Still
  inconclusive.
- **What a further sample would need,** indicative only and not a plan:
  - If the true rate were near the observed 0.5-0.56%, an upper bound below 1% would
    need an n_eff of about 1,500-1,950. At v2's design effect that is about 1,750-2,250
    no-cue items.
  - The zero-omission figure of about 442 items (above) applies only if no further
    omission is found.
- **Human review pending:** every judgment is a model's and is pending human review. The
  owner's human pass, the condo subtype check and the answers to the new questions in
  Results section 7 could move single items. One no-cue item changed either way moves
  p_w by 0.21 to 0.72 points, depending on its facet (see the planning values).

## What this does not do

It does not:
- re-audit the 54,888 results or re-judge v1 under v5;
- apply the ruling 8 overlay or change any overlay, store, label or search;
- re-run extraction or make a paid call;
- estimate dataset-wide recall.

The judgments come from Claude model sessions, the same model family as the extractor, so
they may share its biases. The second read checks consistency between model readings,
not their accuracy.

## How the review ran

The commands ran from the WO-033 worktree, with `--data-root` set to the main checkout's
gitignored `data/enrichment/`:

```
python scripts/omission_pilot.py --pilot v2 packet
python scripts/omission_pilot.py --pilot v2 record --kind model \
  --draft data/enrichment/omission-pilot-v2/judgments-draft.jsonl
python scripts/omission_pilot.py --pilot v2 aggregate --name aggregates.json
```

The packet carries WO-026's output-confinement and frozen source-hash checks. `record`
requires the v2 guide version and `human_review: pending` on model records. A human pass
uses `record --kind human` as in v1.

Between `packet` and `record`, the 400 items were split into 8 shards, read, re-read in
part and adjudicated, as described in Results. Shard outputs were checked by a private
validator before they were combined. It runs `validate_judgments`, a fixed field set,
and checks that no record contains a sampled key or six consecutive remark words.
`aggregate` now also writes `weighted_by_stratum`: for each stratum, the weighted rate
and its Kish-n_eff Wilson interval, both as recorded and with unclear items counted as
omissions.
