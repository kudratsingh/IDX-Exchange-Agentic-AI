# WO-018/021 omission-risk pilot v2 (WO-033)

**Results of the model review (2026-11-03).** All 400 frozen items were reviewed after
#144 and #154 merged. Every number below is an aggregate of private judgments; no key,
remark or quote is in this file.

**Revision r2 (2026-11-04).** The owner reported an uncovered-population bug in
`omission_pilot.weighted_rate`. It is fixed, and the aggregate was re-run into a new
private file, `aggregates-r2.json`. Every published figure is unchanged, because the
v2 design samples all 20 facets in the no-cue and cue strata. The no-cue estimate covers
**100% of the no-cue population** (848,575 pairs, 20 of 20 facets). Details are under
"Coverage correction (r2)" below. This revision also applies the owner's 2026-11-04
decisions on publication, the judgments and the human packet.

**This is model review, not human review.** Claude (Opus 5.5) agent sessions read each
remark against the annotation guide, review policy v4 and its v5 extension, and the
owner's three approved decisions. Every record carries `human_review: pending` until the
owner's human pass. No paid or provider API call was made: the reading was done inside
this agent session.

**Headline.** The population-weighted no-cue omission rate is **0.56%**, 95% interval
**0.11% to 2.81%** (Wilson on Kish n_eff 207.0). It covers 100% of the no-cue
population: all 20 facets have sampled no-cue items. The interval contains the accepted
1% threshold, so **the result is inconclusive** under the accepted rule. The owner
publishes it as the v2 result with the full interval (2026-11-04). This is a finding for
the owner, not a decision.

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
(2.0-17.8%, n_eff 42.2). It covers 100% of the cue population.

No weighted figure is given for the labeled stratum. Labeled items were drawn for the
six limited facets only, so a weighted labeled rate would cover only 26.2% of the labeled
population: 1,851 of 7,073 pairs. The other 14 facets (5,222 pairs) are uncovered and
are not imputed.

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
  n_eff 207.0, deff 1.16.**
  - Basis: the covered no-cue population, which is all of it: 848,575 of 848,575 pairs
    and 20 of 20 facets. No uncovered facet.
  - Source: the `weighted_by_stratum` field of `aggregates-r2.json`, computed by the
    corrected `omission_pilot.weighted_rate`. It is identical to `aggregates.json`.
  - The figures match the design values fixed before the review.
- Both no-cue omissions are on owner-named facets of weight 2, with 16 items each:
  - bonus_room, 5.1% of the no-cue population: an existing room offered for a
    second, living use, counted under v5 ruling 7;
  - open_plan, 3.9%: connected living spaces described without open-plan wording.
- The other 18 facets show 0 no-cue omissions in 192 items.

**Sensitivity of the weighted no-cue figure** (all on n_eff 207.0, 100% of the no-cue
population):

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

**Condo subtype (checked 2026-11-04, see below; both judgments stand).** Two condominium
items rest on a direct condo claim, and ruling 4 says the subtype column decides:
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
- `aggregates.json`, `bb14a396…fcbe3`, written before the r2 fix and kept as it is;
- `aggregates-r2.json`, `bf3f15cb…a468`, the corrected aggregate (r2, 2026-11-04);
- `human/human-packet-r1.jsonl`, `b310b740…87ff`, the human packet (2026-11-04);
- `judgments-draft.jsonl`, `ca1737c0…fbc7c`;
- under `review/`: the rubric (`a5090f62…a1720`), 8 shard packets and judgments, the
  shard index, `second-read.jsonl` (`8f4ef062…5687`) and `adjudication.jsonl`
  (`e8e27e35…3894`).

The frozen sample and manifest and every v1 file have the same hashes as before the
review.

## Coverage correction (r2)

**The defect.** `weighted_rate` summed the uncovered population only over the facets that
had a cell.
- A facet with population but no cell dropped out of both the covered and the uncovered
  figures, so the result showed full coverage it did not have. `aggregate` built its
  population map from the sampled facets only, so a facet with population and no sampled
  item was lost the same way.
- Sampled items in a facet with no population were left out of n without a word.
- Counts with k > n raised an unrelated math error instead of a clear refusal.
- The result gave no covered share and no list of uncovered facets.

**The owner's hypothesis does not hold for v2.** The hypothesis was that 14 non-limited
facets got 0 no-cue items while the weights used their full no-cue population. In fact
the v2 allocation gives every facet no-cue items: 24, 16 or 8 each, 240 in all. The 14
non-limited facets have 0 items in the **labeled** stratum only, by design. The old code
already reported that stratum's 5,222 uncovered pairs correctly, because those facets
had cells from their other strata. So the defect was real, but it did not change any v2
or v1 figure. A hand recomputation from the manifest gives the same covered population,
n_eff and interval in every stratum.

**The fix** (`02c2e64`; tests committed first in `1ea89fb`):
- The estimate, n, N_covered, n_eff and the Wilson interval use the covered facets only:
  facets with N_f > 0 and at least one sampled item.
- Every other facet with population is uncovered. It is listed with its N in
  `uncovered_facets`, never imputed, neither as zero nor at the covered rate. Each result
  also carries `population`, `covered_share`, `covered_facets` and a `basis` line.
- With nothing covered, the result is explicit: no estimate, no interval, covered share
  0, every facet listed.
- Items without a population, counts outside 0 <= k <= n, and negative populations are
  refused.
- `aggregate` now covers every facet in the population counts, sampled or not, and adds
  a per-facet `covered_share`.

**Coverage by stratum** (from `aggregates-r2.json`):

| Stratum | Population | Covered | Covered share | Facets covered |
|---|---:|---:|---:|---:|
| No cue | 848,575 | 848,575 | 100% | 20 of 20 |
| Cue | 60,808 | 60,808 | 100% | 20 of 20 |
| Labeled non-present | 7,073 | 1,851 | 26.2% | 6 of 20 |

**Conclusiveness on the corrected basis:** unchanged, **inconclusive**. The lower
bound, 0.11%, is below 1%, and the upper bound, 2.81%, is above it. The v1 no-cue
allocation also covers all 20 facets (2 or 3 items each), so the pooled sensitivity
line, 0.50% (0.10-2.37%, n_eff 253.1), is on a 100%-covered basis too.

## Comparison with v1

v1 was judged under v4 alone; v2 under v4 plus v5 and the approved decisions. The item
sets are disjoint. **Owner decision, 2026-11-04:** pooling with v1 is a sensitivity line
only, because the two designs differ. The v2 result stands on its own.

| Stratum | v1 (142 items) | v2 (400 items) | v1 + v2 pooled (sensitivity only) |
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
  - For v2, the owner chose neither (2026-11-04). The v2 result is published on its own
    with the full interval. Pooling is a sensitivity line only, and no further sample is
    drawn before WO-034 Phase D.
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
- **Coverage:** the estimate covers 100% of the no-cue population (848,575 pairs, 20 of
  20 facets). The r2 correction changed no figure, and the reading is the same.
- **Owner decision, 2026-11-04:**
  - publish the existing v2 result with the full interval;
  - pooling with v1 is a sensitivity line only, because the designs differ;
  - no additional sample before WO-034 Phase D.
- **Pooled with v1, sensitivity only:** 0.50% (0.10-2.37%), n_eff 253.1. Still
  inconclusive.
- **What a further sample would need: a rough guide, not a plan or a power
  calculation.**
  - Hold the observed estimate fixed. An upper bound below 1% then needs n_eff of 1,945
    at p_w = 0.558%, and 1,522 at 0.50%, the pooled sensitivity figure.
  - At v2's design effect (1.159), that is about 2,255 and 1,764 no-cue items. At the
    pooled design effect (1.130), the 0.50% case is about 1,720.
  - These are the sizes at which the bound just reaches 1% **if the new estimate equals
    the old one**. If the true rate equals the observed one, a sample of that size would
    give a bound below 1% only about half the time. A sample meant to settle the question
    would need to be larger, and its size depends on the true rate, which is unknown.
  - The zero-omission figure, n_eff 381 or about 442 items (above), applies only if no
    further omission is found.
  - No further sample is planned before WO-034 Phase D (owner, 2026-11-04).
- **Human review pending:** every judgment is a model's and is pending human review. The
  owner's human pass, the condo subtype check and the answers to the new questions in
  Results section 7 could move single items. One no-cue item changed either way moves
  p_w by 0.21 to 0.72 points, depending on its facet (see the planning values).

## Judgments, the pinned standard and the human pass (2026-11-04)

**The original v2 judgments are preserved as they are.** `judgments.jsonl`
(`4d0d565318665cc3ed0f551bd0a89f52909be3682cd25402819511d0a9531159`) is not edited.
They were read under:
- **Rubric:** `review/rubric-v2.md`, sha256
  `a5090f620a9e1293849c021b057c90d0436288ff2b8e33df64aeb069ce8a1720`. Every judgment
  records this hash.
- **Policy:** `docs/ENRICHMENT_REVIEW_POLICY_V5.md` with rulings 1-8, as last changed by
  commit `1fe7eb3` (`1fe7eb38ad012886842379fa9773c58dbf646ed9`). That is the file on
  `main` at `48b74ab`, this branch's base, with file sha256 `5c449d08…74af1`.
- **They predate rulings 9-15** (owner, 2026-11-04). Those rulings answer questions 1-6
  in Results section 7, but no v2 judgment applies them. They will be appended to the
  V5 file separately; this branch does not edit the policy.
- Question 6 is answered by ruling 14: a utility room is a bonus room only when it is
  presented as existing, usable living space. That question decides one of the two
  no-cue omissions, the bonus_room item. Its final judgment stays as recorded. Any change
  comes through the versioned human pass. The sensitivity table already shows the
  estimate without that item: 0.24% (0.03-2.27%), still inconclusive.

**A later human override is versioned separately and never edits a judgment in place.**
- The first human pass is recorded as a new file, `judgments-human-r1.jsonl`, with
  `record --kind human --name judgments-human-r1.jsonl`. It uses the same record format
  as the model judgments, with these differences:
  - `review_type` is `human`, and `reviewer` is a non-model name;
  - `human_review` is `confirmed` or `overridden`;
  - `reviewed_at` is the time of the human reading.
- Each human record should also name the policy commit it was read under, in a
  `policy_commit` field. The validator does not enforce that field yet.
- It is aggregated as a new file: `aggregate --human judgments-human-r1.jsonl --name
  aggregates-human-r1.json`. A human record replaces the model's record for that item in
  the merge; the model file is not touched.
- A later pass is `judgments-human-r2.jsonl` and `aggregates-human-r2.json`, and so on.
  No numbered file is ever rewritten.

**The human packet** (owner decision, 2026-11-04), new private file
`human/human-packet-r1.jsonl` (sha256 `b310b740…87ff`), made with the new `human-packet`
subcommand:
- **The union**, deduplicated: the 21 final omissions, the 8 final unclear items and the
  5 adjudicated items. That is 34 before deduplication and **31 unique items**. Three
  adjudicated items are also final omissions (2) or unclear (1).
- **Plus 20 seeded random agreed items from outside the union.** Seed
  `wo033-human-20261104`. Items are ranked by sha256(seed|item_id), smallest first.
  - "Agreed" is defined strictly: the item is not adjudicated, and it has a second read
    whose decision and status check both equal the final ones.
  - 40 such items exist outside the union: the second read's seeded random 40. So all
    20 come from that pool, and the fallback to items without a second read was not
    used (0).
- **Total: 51 items** (11 no cue, 28 cue, 12 labeled).
- Each record carries the remark, verified against its frozen source hash, for the
  human reader; the model's final judgment with its basis, flags, adjudication and
  second-read fields; and blank human fields.

**Condo subtype check.** Approved (2026-11-04) as a read-only select of the allowlisted
subtype column from the main checkout after D1; run 2026-11-04 after D1 (command in
WO-033 Status, 2 rows, no paid call). Under ruling 4 the subtype column decides, and it
agrees with the model judgment on both flagged items: the cue item judged an omission
has a condominium subtype, so the omission stands; the labeled item judged correctly
non-present has a townhouse subtype, so its non-present status stands. No count in this
report changes.

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
# r2, 2026-11-04: corrected weighted_rate; a new file, aggregates.json untouched
python scripts/omission_pilot.py --pilot v2 aggregate --name aggregates-r2.json
python scripts/omission_pilot.py --pilot v2 human-packet   # human/human-packet-r1.jsonl
```

The packet carries WO-026's output-confinement and frozen source-hash checks. `record`
requires the v2 guide version and `human_review: pending` on model records. A human pass
uses `record --kind human` as in v1.

Between `packet` and `record`, the 400 items were split into 8 shards, read, re-read in
part and adjudicated, as described in Results. Shard outputs were checked by a private
validator before they were combined. It runs `validate_judgments`, a fixed field set,
and checks that no record contains a sampled key or six consecutive remark words.
`aggregate` now also writes `weighted_by_stratum`. For each stratum it gives the weighted
rate over the covered facets and its Kish-n_eff Wilson interval, both as recorded and
with unclear items counted as omissions. Since r2, it also gives the stratum population,
the covered share and the uncovered facets with their populations.
