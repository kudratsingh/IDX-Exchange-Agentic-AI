# WO-018/021 omission-risk pilot (WO-026)

**Model review, not human review.** Every judgment below was made by a Claude model
(`claude-opus-5-5`, one agent session) reading remarks against the approved annotation
guide and review policy v4. No human has reviewed these judgments yet; each record carries
`human_review: pending`.

**Pilot findings, not dataset-wide accuracy.** 142 listing x facet items is far too few
for a per-facet error rate. The intervals below are wide on purpose. Nothing here is a
production accuracy claim, changes eligibility, or changes any stored label.

## Why

The WO-018 audits checked labels the extractor *produced*: about 125,845 labels, with
roughly 1,600 uncorrected rule-kept errors and 600 read errors estimated. Nobody had
looked for features the extractor *missed*: a remark that affirms a current feature
while the effective store has no `present` status for it. Six facets (garage, stainless
appliances, condominium, single level, near transit, near grocery) were audited only in
the 471 diagnostic cases. This pilot measures how often a feature search would miss a
listing because of an omission, on a small frozen sample.

## Method

**Population.** The 54,888 extraction inputs, minus 792 excluded listings: the 250
frozen benchmark listings (dev and held-out splits and their sample file), the 40-case
deal-signal supplement, the 32 WO-021 spot-check listings and the 471 diagnostic cases
(already read in full). Nothing is sampled from a benchmark, so nothing is tuned against
it. Remaining: 54,096 listings.

**Unit.** One listing and one of the 20 eligible facets, where the listing's effective
status for that facet is **not** `present`. Omissions can only occur there.

**Strata, per facet.**

| Stratum | Definition | Items per facet |
|---|---|---|
| `labeled_non_present` | the store has a non-present status (uncertain, planned, historical, stated absent, contradictory) | 2 for the six limited facets; 0 for the other 14 (their labels were read by the policy audit) |
| `cue` | no status; the remark matches a crude public keyword cue for the facet | 7 limited; 3 other |
| `no_cue` | no status; no cue match | 3 limited; 2 other |

The cues (in `src/idx_agent/enrichment/omission_pilot.py`) only concentrate the search so
the pilot finds something; a cue is not a label. The `no_cue` stratum still measures the
rate where no keyword appears. Population counts for every stratum are frozen in the
manifest, so each stratum's rate can be weighted.

**Sampling.** Within each stratum, keys are ranked by
`sha256(seed|facet|stratum|key)` and the smallest are taken; seed
`wo026-omission-20261102`. Total: 6 x 12 + 14 x 5 = **142 items** (72 limited-facet,
70 other). A listing may appear for more than one facet.

**Frozen artifacts (private, gitignored).** `data/enrichment/omission-pilot-v1/`:
`sample.jsonl` (sha256 `5a59e65e3f10ea2ea6700e28738add6fdbf36c4f0c25e74b98127c2b01ebee2b`),
`manifest.json` (sha256 `ab0af6e8…1386d`: seed, method, allocation, population counts,
exclusions, store file sha256 `7d9007b3…1bef`, store watermark `2026-09-18 06:58:44`,
policy `v4`, rules `2026-11-01.4`, results digest `46cd0a6b…9209815`, code commit
`7f13418`, unmodified code files), `packet.jsonl`, `judgments.jsonl`, `aggregates.json`
and private notes. Before sampling, the script re-checks the approved results digest,
validates the effective store with the production loader, and checks every remark
against its recorded hash.

**Remark source.** The prepared, redacted remark text stored with each extraction input,
which is exactly what the extractor saw. No MySQL query and no paid or model API call
was made. Remark text was treated as data; nothing in it was followed as an instruction.

**Decisions.** For each item the reviewer chose one of:

- `omitted_present`: the remark affirms the facet as a current or unspecified-time
  feature under the guide and policy, so the extractor (or the overlay) missed it;
- `correctly_absent`: no supported mention;
- `non_present_mention`: a planned, uncertain, historical or negated mention, correctly
  not `present`;
- `unclear`: the guide or policy does not settle it (listed below).

For `labeled_non_present` items the reviewer also judged whether the stored status itself
is right (`correct`, `wrong`, `unclear`).

## Results

Rates are omissions / items reviewed (unclear items stay in the denominator). 95% Wilson
intervals.

**Overall: 6 omissions in 142 items, 4.2% (2.0-8.9%).** 124 correctly absent, 4
non-present mentions, 8 unclear.

| Pooled stratum | Items | Omitted | Unclear | Rate | 95% Wilson |
|---|---:|---:|---:|---:|---|
| Cue (all facets) | 84 | 5 | 3 | 6.0% | 2.6-13.2% |
| No cue (all facets) | 46 | 0 | 1 | 0.0% | 0.0-7.7% |
| Labeled non-present (six limited facets) | 12 | 1 | 4 | 8.3% | 1.5-35.4% |

| Facet group | Items | Omitted | Non-present | Unclear | Rate | 95% Wilson |
|---|---:|---:|---:|---:|---:|---|
| Six limited facets | 72 | 3 | 4 | 6 | 4.2% | 1.4-11.5% |
| Other 14 facets | 70 | 3 | 0 | 2 | 4.3% | 1.5-11.9% |

Per facet (O = omitted, N = non-present mention, U = unclear, of n reviewed). Population
is the frozen stratum size among the 54,096 listings.

| Facet | Cue: O/N/U of n (population) | No cue: O of n (population) | Labeled: O/U of n (population) |
|---|---|---|---|
| condominium | 0/0/0 of 7 (92) | 0 of 3 (47,749) | 1/1 of 2 (184) |
| garage | 0/2/0 of 7 (215) | 0 of 3 (27,995) | 0/0 of 2 (1,112) |
| near_grocery_mentioned | 1/1/0 of 7 (216) | 0 of 3 (50,727) | 0/1 of 2 (164); 1 planned |
| near_transit_mentioned | 0/0/0 of 7 (3,533) | 0 of 3 (46,316) | 0/1 of 2 (66) |
| single_level | 0/0/0 of 7 (186) | 0 of 3 (46,743) | 0/0 of 2 (199) |
| stainless_appliances | 1/0/2 of 7 (315) | 0 of 3 (42,517) | 0/1 of 2 (138) |
| bonus_room | 1/0/0 of 3 (6,856) | 0 of 2, 1 unclear (43,028) | not sampled (118) |
| clubhouse | 1/0/1 of 3 (1,255) | 0 of 2 (47,891) | not sampled (25) |
| open_plan | 1/0/0 of 3 (3,744) | 0 of 2 (32,702) | not sampled (166) |
| adu, community_pool, fitness_center, gated_community, hardwood, mountain_view, patio, pool, solar, walk_in_closet, water_view | 0 of 3 each | 0 of 2 each | not sampled |

**Do not read the per-facet rows as rates.** One omission in three cue items gives
33% (6-79%); weighting that by the cue population would imply thousands of missed
listings from a single judgment. The script computes population-weighted per-facet
estimates (`aggregates.json`), but at these sizes they are not findings. The defensible
statements are the pooled ones above.

**Existing non-present statuses (12 limited-facet items):** 3 correct, 5 wrong, 4
unclear. Four of the wrong ones are uncertain labels with no supporting text (parking
spaces read as a garage, a sink read as stainless appliances, freeway access read as
transit); they never match a search, so they cannot cause a false result. One is an
uncertain condominium status where the remark's wording implies the unit is a condo.

## What was found (aggregate patterns)

1. **No omission without a cue.** All six omissions were in cue or labeled strata; 0 of 46
   no-cue items. The no-cue upper bound (7.7%) is still too wide to rule out a
   meaningful rate across the 848,621 no-cue listing x facet pairs (60,892 cue and
   7,085 labeled non-present pairs make up the rest).
2. **Cue matches were mostly not facet mentions.** Of 84 cue items, most were comparisons
   (a home compared with condo living), other objects (stainless sinks or hardware,
   walk-in showers and pantries, appliance garages, a solarium, solar tubes), parking
   counts, "commuter routes" meaning roads, or proximity to a named facility. The
   extractor was right to leave these out.
3. **Omissions cluster where policy accepts indirect wording.** Four of the six omissions
   rely on clarifications that accept something other than the literal facet word: a loft
   offered as additional flexible living space (v4 bonus room), resident community rooms
   (v3 clubhouse), a great room combining kitchen, dining and living (v3 connected
   spaces), and a general statement that groceries are nearby. The policy audit reviewed
   the stored labels in its inventory against these rulings; it did not search remarks for
   features the extractor had not labeled, so this direction was unmeasured until now.
4. **One plain miss.** A kitchen explicitly listed with stainless steel appliances had no
   stainless status at all.
5. **Hypothetical and historical wording is handled.** All four non-present mentions were
   correctly not present: two garages converted to living space and two grocers that are
   only planned to open.

## Unresolved decisions (owner)

These are definitional questions the guide and policy do not settle; the items involved
are marked `unclear` and listed privately in
`data/enrichment/omission-pilot-v1/unresolved-decisions-private.md`.

1. Is a warehouse club a "named grocery retailer"? Is a farmers market a grocery claim
   (judged no)?
2. Does a community-operated shuttle or transportation service for residents count as
   transit?
3. Does `stainless_appliances` need more than one stainless appliance? Do stainless
   outdoor-kitchen appliances count? Does a "stainless kitchen" without named appliances
   count?
4. Can a property type be implied by comparison wording (a unit compared with condos)?
5. Does flexible space in a detached accessory structure count as a bonus room
   (ruling 2 scope)?
6. Does a community recreation center count as a clubhouse when resident access is
   implied but not stated?
7. Should an existing loft "offered for" several uses including living space count under
   v4 when ruling 3 treats possibility as uncertain? (Judged present here.)
8. Should the unsupported uncertain labels on limited facets be cleaned? They have no
   matching effect; nothing was changed.

## What this does not do

It does not re-audit the 54,888 results, tune anything, change the overlays, the store,
the benchmark labels or the extractor, or re-run extraction. It does not estimate
dataset-wide recall. The judgments are one model reviewer's and may share the
extractor's biases.

## How a human completes or overrides the review

Run from the main checkout (all files stay under the gitignored `data/enrichment/`):

```
python scripts/omission_pilot.py packet --name packet-human.jsonl    # remarks to read, if needed
# write data/enrichment/omission-pilot-v1/human-draft.jsonl: one record per item reviewed,
# same fields as judgments.jsonl, with review_type "human", a non-model reviewer name and
# human_review "confirmed" (agrees with the model) or "overridden"
python scripts/omission_pilot.py record --kind human \
  --draft data/enrichment/omission-pilot-v1/human-draft.jsonl --name human-judgments.jsonl
python scripts/omission_pilot.py aggregate --human human-judgments.jsonl \
  --name aggregates-human.json
```

`record` refuses records for items outside the frozen sample, a changed facet or stratum,
an unknown decision, a model name on a human review, a missing status check on labeled
items, or a guide version other than the pilot's. `aggregate` refuses judgments recorded
against a different sample hash, and a human judgment replaces the model's for that item.
Existing files are never overwritten; each run writes a new file.

Every `--name`, `--judgments` and `--human` value is a plain file name inside
`omission-pilot-v1/`: an absolute path, a separator, `..`, or a link at the destination
is refused, and so is a pilot directory that is itself a link (the data root may be
reached through one). Files are created exclusively, owner-only, relative to the pilot
directory opened without following links, and never through a final link. `packet`
first re-checks the approved results digest, then checks each sampled item's remark
against its frozen source-text hash (the result record's `input_hash`, which that digest
covers); a missing or changed remark refuses the whole packet before anything is
written, naming only item ids and positions. These checks were added in review after the
sample was drawn; the frozen sample, manifest and review files are unchanged.
