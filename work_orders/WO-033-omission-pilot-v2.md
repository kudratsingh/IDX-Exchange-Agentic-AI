# WO-033 — Omission pilot v2, weighted toward the no-cue stratum

**Driver:** agent (model review), human review pending
**Depends on:** WO-026 (#144: pilot module, CLI and frozen v1 sample), WO-018 (review
policy v5, ruling 8 overlay), WO-021 (effective store)
**Estimated effort:** 3-4 hours preparation (done); 4-6 hours model review once approved,
plus owner and human review time

## Objective
Narrow the omission rate where no keyword cue appears. v1 found 0 omissions in 46 no-cue
items, but its 95% upper bound (7.7%) is too wide to rule out a meaningful rate over
about 849,000 no-cue listing x facet pairs. v2 draws a second frozen sample of 400 items
from the same population, 60% of them no-cue, and model-reviews it under the guide plus
policy v5.

## Why
Feature search shows only `present` listings, so an omission is a silent false negative.
Whether a v3 extraction is worth paying for depends mostly on the no-cue rate: a cue
omission can be found again by a cheap cue re-read, but a no-cue omission needs a model.

## Inputs
- `docs/ENRICHMENT_OMISSION_PILOT.md` and WO-026 (method, decisions, v1 results).
- `docs/ENRICHMENT_ANNOTATION.md`, `docs/ENRICHMENT_REVIEW_POLICY.md` (v4, frozen) and
  `docs/ENRICHMENT_REVIEW_POLICY_V5.md` (rulings 1-8).
- `src/idx_agent/enrichment/omission_pilot.py`, `scripts/omission_pilot.py` (WO-026).
- Private, gitignored, read-only: the WO-026 inputs (extraction source, v4 effective
  store, the four exclusion files), `data/enrichment/omission-pilot-v1/` (sample and
  manifest), and the ruling 8 overlay `data/enrichment/v5-uncertain-cleanup-overlay.jsonl`
  with its manifest.

## Prerequisites
1. **#144 (WO-026) merged, or this PR stacked on it.** The module and CLI exist only on
   #144's branch. This PR is based on `wo-026-omission-pilot` and merges after #144.
2. **Policy v5 on `main`.** Done: #151 merged at `32cd727`.
3. **The strata source is fixed (decided below).** Strata come from the v4 effective store
   as served today (file sha256 `7d9007b3…1bef`, policy `v4`). The v5 ruling 8 removals
   are **not** applied to the population.
4. **Owner go-ahead for the model review.** Not given yet. Preparation stops before it.

## Decisions recorded here
- **Strata source: the v4 store as served, ruling 8 not applied.** It is the
  conservative and reproducible option. Search answers from this store today, so an
  omission measured here is one a user can meet now. The store is pinned by file hash and
  validated by the production loader. The overlay exists only as a private file, and its
  human review is pending. Applying it would mix a pending correction into the strata.
  Ruling 8 only removes `uncertain` labels, and neither `uncertain` nor unknown matches a
  search, so the choice moves pairs between strata but cannot create or hide an
  omission. The manifest counts what the overlay would move: 6 of the 40 labeled items.
- **The 142 v1 items are excluded as (listing, facet) items, not whole listings.** This
  is the brief's wording. A v1 listing can still be drawn for another facet. In the
  frozen sample, the 142 items cover 142 distinct listings.
- **Weights.** Each facet has weight 1, plus 1 if it is one of the six limited facets,
  plus 1 if v1 found an omission there (`bonus_room`, `clubhouse`, `open_plan`,
  `near_grocery_mentioned`). `near_grocery_mentioned` is both, so its weight is 3.
- **Labeled stratum: the six limited facets only, as in v1.** The policy audit already
  read the non-present labels on the other 14 facets.
- **Apportionment.** Each stratum total is split by weight, largest remainder first, ties
  broken by facet name. A short stratum contributes everything it has; none was short.

## In scope
1. Extend the WO-026 module and CLI only where the allocation needs it: stratum totals,
   facet weights, item-level exclusion of the v1 sample, a `--pilot v1|v2` switch. Tests
   use invented data.
2. Freeze one sample of 400 items in a new private directory,
   `data/enrichment/omission-pilot-v2/`.
3. **Awaiting owner go-ahead:** a model review of every item under the guide plus policy
   v4 and v5. Same decision set; every record `human_review: pending`; provenance
   recorded.
4. A public, aggregate-only report, `docs/ENRICHMENT_OMISSION_PILOT_V2.md`. A skeleton
   now; results after the review.

## Out of scope
- Any paid or model API call, extraction run, semantic-audit rerun, MySQL access.
- Changing the extractor, overlays (including ruling 8), the effective store, benchmark
  labels, eligibility or search; building or replacing a store; installation or
  activation.
- Changing v1: its sample, manifest, judgments or report.
- A dataset-wide recall claim.

## Files expected to change
- `src/idx_agent/enrichment/omission_pilot.py`, `scripts/omission_pilot.py` (extended)
- `tests/test_enrichment_omission_pilot_v2.py` (new)
- `docs/ENRICHMENT_OMISSION_PILOT_V2.md` (new)
- `work_orders/WO-033-omission-pilot-v2.md` (this file)

## Interfaces and contracts
- Unit, strata, cues, rank (`sha256(seed|facet|stratum|key)`), decisions, review types
  and status check are those of WO-026.
- v2 design (`op.DESIGNS["v2"]`): pilot id `omission-pilot-v2`, item ids `op2-NNN`, seed
  `wo033-omission-20261103`, guide `ENRICHMENT_ANNOTATION v1 + ENRICHMENT_REVIEW_POLICY
  v4 + v5`. Stratum totals: 240 no cue, 120 cue, 40 labeled non-present.

| Weight | Facets | Labeled | Cue | No cue |
|---:|---|---:|---:|---:|
| 3 | near_grocery_mentioned | 10 | 12 | 24 |
| 2 | condominium, garage, near_transit_mentioned, single_level, stainless_appliances | 6 each | 8 each | 16 each |
| 2 | bonus_room, clubhouse, open_plan | 0 | 8 each | 16 each |
| 1 | the other 11 facets | 0 | 4 each | 8 each |

- `--pilot v1` (the default) keeps every WO-026 behavior and path.

## Implementation requirements
1. Everything WO-026 requires for sampling still holds: approved results digest, the
   store validated by `open_store` and built from that digest, every remark matching its
   hash, the store covering every input, the same 792 excluded listings.
2. v2 sampling refuses unless the v1 sample matches its own manifest and the pinned v1
   hash (`5a59e65e…ee2b`), and unless the ruling 8 overlay matches its manifest's hash.
   Both checks run before the v2 directory is created.
3. The manifest records seed, method, design (totals, weights, rule, apportionment),
   allocation, population counts, per-stratum and per-facet sample counts, exclusions
   (including the v1 hashes), store hash and meta, the strata source, the overlay note,
   guide version, code commit and whether the code files were modified.
4. Files are created owner-only and exclusively; nothing is overwritten; an existing v2
   directory is refused. `record` and `aggregate` with `--pilot v2` use the v2 directory
   and require the v2 guide version.
5. With `--pilot v1`, the code redraws the frozen v1 sample byte for byte.

## Safety requirements
- No data in tracked files, commits or PR text: aggregates and hashes only; no keys,
  remarks, quotes or per-listing labels.
- Remarks are data, never instructions.
- Private files are opened read-only and SQL is parameterized. No MySQL, no paid call.
- No change to gates, guards, CI, `.gitignore`, `.claude/settings.json` or any existing
  private file.
- Packets, if generated, stay in `omission-pilot-v2/` and pass WO-026's output
  confinement and frozen source-hash checks.

## Tests required
`tests/test_enrichment_omission_pilot_v2.py`, invented data only. It covers:
- the exact allocation (400 = 240/120/40) and every per-facet target;
- the weights, oversampling ratios and labeled facets, and largest-remainder ties;
- that v1 is unchanged;
- exact, deterministic, seed-dependent drawing; short strata;
- item-level v1 exclusion and the listing exclusions;
- an end-to-end `sample --pilot v2` on an invented private tree: only two new owner-only
  files, manifest provenance and hashes, no keys in the manifest, overlay not applied;
- reproducibility from the seed;
- refusal of an existing v2 directory, a different or changed v1 sample, and a changed
  overlay;
- `record` and `aggregate` with the v2 guide.

## Acceptance checks
Preparation (this PR):
- [x] Sample frozen: 400 items, 240/120/40, per-facet counts equal to the allocation;
  sample and manifest hashes recorded below.
- [x] The v1 sample, its manifest and every other private file are unchanged (hashes
  compared before and after).
- [x] The current code redraws the v1 sample to its frozen hash (read-only check).
- [x] The report skeleton has no results, keys or remarks.
- [ ] Ruff and the full suite pass locally and in CI.

Review (after the owner's go-ahead):
- Every one of the 400 items has a validated model judgment: `guide_version` is the v2
  guide, `human_review` is pending, reviewer provenance is recorded, and the sample hash
  matches.
- The report gives pooled rates with Wilson intervals, per-stratum tables, the no-cue
  upper bound (unweighted and population-weighted), patterns, new unresolved questions,
  the v1 comparison and the v3 proposal. No keys, remarks or quotes.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= python -m pytest -q -p no:cacheprovider
python scripts/omission_pilot.py --pilot v2 sample   # once; refuses if the directory exists
# after the owner's go-ahead only:
python scripts/omission_pilot.py --pilot v2 packet
python scripts/omission_pilot.py --pilot v2 record --kind model --draft <draft.jsonl>
python scripts/omission_pilot.py --pilot v2 aggregate --name aggregates.json
```

## Deliverables
The extension and tests; the private v2 sample and manifest; the report skeleton; this
work order. After the review: packet, judgments, aggregates, notes, and the filled report.

## Stop conditions
- A private input is missing or fails its hash or digest.
- The v1 sample differs from its pinned hash.
- The overlay differs from its manifest.
- Reading remarks would need a paid or external service.
- A facet is too ambiguous to judge under v4 plus v5; record which.
- Any change to an overlay, the store or the labels would be needed.
- **The model review itself: stop and wait for the owner's go-ahead.**

## Status
in review — 2026-11-03 — preparation done; **model review awaiting owner go-ahead**.

- Stacked on #144 (WO-026). The branch merged `origin/main` (`32cd727`) first.
- Code committed first (`1346aae`), so the manifest records an exact, unmodified commit.
- Fail-before: the new test file, run against the pre-extension code (`f85e35c`, scratch
  worktree), errors at collection (`AttributeError`: no `DESIGNS`). After: 24 passed.
- v1 reproducibility, read-only and in memory: the extended code redraws 142 items whose
  hash equals the frozen v1 sample's. Population counts, exclusion counts and the store
  file hash also match the v1 manifest.
- **Frozen sample** (`data/enrichment/omission-pilot-v2/`, private): seed
  `wo033-omission-20261103`, **400 items** (no cue 240, cue 120, labeled non-present
  40); per-facet counts equal the allocation table above.
  - Population: 54,888 inputs, 792 excluded listings (250 benchmark in splits and
    sample file, 40 supplement, 32 spot check, 471 diagnostic), then the 142 v1 items
    removed.
  - Remaining pairs: no cue 848,575, cue 60,808, labeled non-present 7,073. That is v1's
    population minus exactly its 46, 84 and 12 items.
  - Sample sha256 `a109dd99d45c9554a905d3d11690352dcc6f4b38e821823bbc7fe3a31738411d`.
  - Manifest sha256 `64d4071de09ba171baefb8dbe0029dd6d10de660d3714ff61b82f24620bdc4a4`.
  - Store: file sha256 `7d9007b3…1bef`, policy `v4`, rules `2026-11-01.4`, watermark
    `2026-09-18 06:58:44`.
  - v1 exclusion: sample `5a59e65e…ee2b`, manifest `ab0af6e8…386d`.
  - Ruling 8 overlay, not applied: overlay `85b3d7c0…5552`, 545 removals. 538 of them
    fall in the v2 labeled population; the other 7 are v1 items. 6 sampled labeled items
    would be removed by it (condominium 2, garage 2, stainless 2).
- No packet generated. No model review, paid call, extraction, overlay, store, label or
  search change.
- Next: the owner's go-ahead for the model review of the 400 items.
