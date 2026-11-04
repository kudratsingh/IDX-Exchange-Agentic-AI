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
4. **Owner go-ahead for the model review.** Given 2026-11-03: the review may start once
   #144 and #154 are merged. #144 merged at `5daa7b5`; #154 is not merged, so the review
   has not started.

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
  plus 1 if it is one of the four facets the owner named from v1's omission patterns
  (`bonus_room`, `clubhouse`, `open_plan`, `near_grocery_mentioned`).
  `near_grocery_mentioned` is both, so its weight is 3. v1 also recorded single
  omissions in `stainless_appliances` (cue) and `condominium` (labeled). The owner did
  not name them, and both are already oversampled as limited facets (weight 2), so they
  get no third point. The frozen manifest's `weight_rule` string reads "+1 facet with a
  v1 omission"; it means these four owner-named facets. The allocation and the frozen
  sample are unchanged by this wording.
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
3. **After #144 and #154 merge (owner go-ahead, 2026-11-03):** a model review of every
   item under the guide plus policy v4 and v5. Same decision set; every record
   `human_review: pending`; provenance recorded.
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
| 2 | bonus_room, clubhouse, open_plan (owner-named) | 0 | 8 each | 16 each |
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

Review (once #144 and #154 are merged):
- [x] Every one of the 400 items has a validated model judgment: `guide_version` is the v2
  guide, `human_review` is pending, reviewer provenance is recorded, and the sample hash
  matches.
- [x] The report gives pooled rates with Wilson intervals, per-stratum tables, the no-cue
  upper bound (unweighted, and population-weighted with the Wilson interval on the Kish
  effective sample size defined in the report), patterns, new unresolved questions,
  the v1 comparison and the reading against the accepted 1% threshold. No keys,
  remarks or quotes.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= python -m pytest -q -p no:cacheprovider
python scripts/omission_pilot.py --pilot v2 sample   # once; refuses if the directory exists
# only once #144 and #154 are merged:
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
- **The model review itself: do not start it before #144 and #154 are both merged.**

## Status
in review — 2026-11-04 — **model review done; uncovered-population fix in; result
inconclusive and published as the v2 result; human packet ready; human review
pending**. (Earlier: preparation done, review approved to start once #144 and #154
merged; model review done 2026-11-03.)

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
- Verifier low findings resolved, docs and comments only (2026-11-03):
  - The weight rule now reads "the four facets the owner named from v1's omission
    patterns". v1 also recorded single omissions in stainless_appliances and
    condominium; both are already oversampled as limited facets. The change is a code
    comment, a docstring and two test comments. The module's AST without docstrings is
    unchanged, so behavior is too. The module file hash now differs from the manifest's
    `code_sha256`, which records commit `1346aae` at sampling.
  - The report fixes the weighted interval before the review: Wilson on the Kish
    effective sample size, n_eff = (sum w)² / sum w², with weights from the manifest's
    per-facet no-cue populations. n_eff = 207.0, deff 1.16. Corrected planning values:
    0 omissions gives at most 1.8% (not 1.6%). Ruling 1% out needs about 442 no-cue
    items, or v1 + v2 plus about 149. The v3 threshold is still a proposal for the owner.
  - The allocation and the frozen sample are unchanged. The sample and manifest hashes
    (v1 and v2) were re-checked after the edit and match.
- Next: the owner's go-ahead for the model review of the 400 items.

2026-11-03 (owner decisions, round three), docs only:
- **Accepted, no longer proposals:** the 1% population-weighted no-cue threshold and the
  interval method, the 95% Wilson interval on the Kish effective sample size
  (n_eff = 207.0 for v2 alone, 253.1 pooled with v1). The reading rule is unchanged:
  lower bound at or above 1% justifies a v3 extraction on omission grounds, upper bound
  below 1% does not, otherwise inconclusive. The report's section is now "Decision".
- **Model review:** may start once #144 and #154 are both merged. #144 merged at
  `5daa7b5` (this PR's base is now `main`); #154 is not merged, so the review has not
  started; no packet generated, no model or paid call.
- Unchanged: the sample, manifest, allocation, weights and code. Nothing was merged,
  paid for, installed or activated.
- Next: after #154 merges, the model review of the 400 items.

2026-11-03 (model review, follow-up branch `wo-033-model-review` from `main` `48b74ab`):
- **Carried commit.** `95f3d2f`, the post-merge commit of #154 recording the accepted
  threshold and interval method, was cherry-picked as `5887caa` with `-x`.
- **Start condition met.** #144 and #154 are both merged into `main` (`48b74ab`).
- **Review.** All 400 items have a validated model judgment. The CLI made the packet,
  which was split into 8 shards of 50 and read by separate Claude agent sessions
  against a private rubric. The rubric covers the guide, v4, v5 rulings 1-8 and the
  three approved decisions:
  - stainless: generic "stainless appliances" counts as present, a bare stainless
    kitchen stays uncertain;
  - condo: ruling 4 as approved, never inferred from comparison wording;
  - doubt wording: the restriction applies to the six limited facets only.
- **Second read and adjudication.**
  - The second read covered 71 items: all 31 omissions or unclear calls, plus a seeded
    random 40.
  - It agreed on 66 (93.0%): 40 of 40 random items and 26 of 31 targeted ones.
  - All 5 disagreements were adjudicated. The first read was upheld once and the second
    read adopted four times. One adjudicated item is a no-cue omission.
  - Every final record keeps its provenance: first reader, second reader if any, an
    adjudicated flag, and `human_review: pending`.
- **Recorded** with `record --kind model` (400 of 400) and aggregated with `aggregate`.
  Both ran with `--data-root` set to the main checkout's data. All private files are
  new and owner-only:
  - `judgments.jsonl` `4d0d5653…1159`;
  - `aggregates.json` `bb14a396…fcbe3`;
  - `review/adjudication.jsonl` `e8e27e35…3894`.
- **Code.** `omission_pilot.weighted_rate` is new: a population-weighted rate with a
  Wilson interval on the Kish n_eff.
  - `aggregate` now adds `weighted_by_stratum`, with each stratum's rate both as
    recorded and with unclear items counted as omitted.
  - Three new tests on invented data. One pins a hand-computed example: p_w 0.075,
    n_eff 16, deff 1.25, interval 0.01515-0.29942.
  - The CLI test checks the new field.
  - `aggregates.json` was written before a docstring-only shortening of the function.
- **Results** (aggregates only; details in `docs/ENRICHMENT_OMISSION_PILOT_V2.md`):
  - Pooled: 21/400 omitted, 5.25% (3.5-7.9%). No cue 2/240, 0.83% (0.23-2.99%). Cue
    14/120, 11.7% (7.1-18.6%). Labeled 5/40, 12.5% (5.5-26.1%).
  - **Weighted no cue: p_w 0.56%, 95% 0.11-2.81%, n_eff 207.0, deff 1.16.**
  - Pooled with v1: 0.50% (0.10-2.37%), n_eff 253.1.
  - 8 unclear: 3 cue, 5 labeled, 0 no-cue.
  - 28 of 40 existing statuses wrong, 27 of them `uncertain`.
- **Conclusiveness under the accepted 1% rule: inconclusive.** The lower bound (0.11%)
  is below 1% and the upper bound (2.81%) above it. The same holds in every sensitivity
  case and pooled with v1. This is a finding for the owner, not a decision.
- **Open:**
  - the owner's human review;
  - the condo subtype check, which needs MySQL and is out of scope here: 2 flagged
    items, neither no-cue;
  - seven new questions, listed in the report.
- Unchanged:
  - the hashes of the v2 sample and manifest, every v1 file, the ruling 8 overlay and
    its manifest, the source and store DBs, and the shard packets and rubric, checked
    before and after;
  - every overlay, store, label and search.
- Not done: no paid or provider call, extraction, MySQL access, store build, install,
  activation or merge.

2026-11-04 (owner decisions; uncovered-population fix, r2), branch `wo-033-model-review`:
- **Base.** `origin/main` is still `48b74ab`, so no merge was needed.
- **Uncovered-population bug, owner-reported: fixed.** Tests were committed first
  (`1ea89fb`) and failed before the fix: uncovered population reported as 0, 50 and 10
  where 100, 200 and 15 were due; no refusal of orphan items. The fix is `02c2e64`.
  - Defect: `weighted_rate` summed the uncovered population over the facets that had a
    cell, and `aggregate` built its population map from sampled facets only. A facet
    with population but no cell, or no sampled item, vanished from both the covered and
    the uncovered figures. Items with no population were dropped from n silently.
  - Now: the estimate, n, N_covered, n_eff and the Wilson interval use the covered facets
    only. Every uncovered facet is listed with its N, plus `population`,
    `covered_share`, `covered_facets` and `basis`, never imputed. A zero-covered result
    is explicit. Bad counts and orphan items are refused.
  - The hypothesis did not hold for v2. The v2 allocation gives every facet no-cue items
    (24, 16 or 8). The 14 non-limited facets have 0 items in the labeled stratum only,
    by design, and that stratum's 5,222 uncovered pairs were already reported. **No
    published figure changed**, and a hand recomputation from the manifest matches.
  - Re-run into a new private file, `aggregates-r2.json` (`bf3f15cb…a468`).
    `aggregates.json` is untouched. It and the human packet were written at `003f290`.
    A later docstring-only shortening leaves both modules' AST, without docstrings,
    unchanged.
  - Coverage: no cue 848,575 of 848,575 (100%, 20 of 20 facets); cue 60,808 of 60,808
    (100%); labeled 1,851 of 7,073 (26.2%, 6 limited facets; no weighted labeled figure
    is published).
- **Result, published per the owner:** weighted no cue **0.56%, 95% 0.11-2.81%**, n_eff
  207.03, deff 1.159, covering 100% of the no-cue population.
  - Conclusiveness under the accepted 1% rule: **inconclusive, unchanged** by the fix.
  - Pooling with v1 is a sensitivity line only: 0.50% (0.10-2.37%), n_eff 253.1, also
    100% covered.
  - No additional sample before WO-034 Phase D.
- **Rough-guide projection corrected** (low verifier note). It now holds the estimate
  fixed and says so.
  - n_eff 1,945 at 0.558% (about 2,255 items at deff 1.159), and 1,522 at 0.50% (about
    1,764, or about 1,720 at the pooled deff 1.130).
  - At those sizes, if the true rate equals the observed one, the bound clears 1% only
    about half the time. The figures are a rough guide, not a power calculation and not
    a plan.
- **Judgments preserved and pinned.** `judgments.jsonl` (`4d0d5653…1159`) is unchanged.
  - Rubric `review/rubric-v2.md`, sha256
    `a5090f620a9e1293849c021b057c90d0436288ff2b8e33df64aeb069ce8a1720`.
  - Policy `docs/ENRICHMENT_REVIEW_POLICY_V5.md`, rulings 1-8, at commit `1fe7eb3` (the
    last change to that file; `main` `48b74ab`), file sha256 `5c449d08…74af1`.
  - **The judgments predate rulings 9-15.** Rulings 9-15 are not applied to them.
  - Human overrides are versioned separately, never edited in place:
    `judgments-human-r1.jsonl` (`record --kind human --name ...`), then
    `aggregates-human-r1.json` (`aggregate --human ... --name ...`), then r2 and so on.
    The format is in the report. A `policy_commit` field is expected but not yet
    enforced.
- **Human packet** (new `human-packet` subcommand, `003f290`, tested on invented data).
  New private file `human/human-packet-r1.jsonl` (`b310b740…87ff`), owner-only.
  - Union: 21 omissions, 8 unclear and 5 adjudicated items. That is 34 before
    deduplication and **31 unique**.
  - Plus **20** seeded random agreed items from outside the union. Seed
    `wo033-human-20261104`, ranked by sha256(seed|item_id). "Agreed" means not
    adjudicated, with a second read equal to the final decision and status check. The
    pool was 40 items, so no fallback was used.
  - **Packet size: 51.**
- **Condo subtype check: owner-run step, after D1. Not run here.** It is a read-only
  select of the allowlisted `rets_property.L_Type_`, by `L_ListingID`, for the 2 items
  flagged `condo_subtype_unchecked`.
  - It goes through `idx_agent.db.pool.connect` (reader user, read-only session), with
    names checked by `check_column`, bound `%s` values and `LIMIT 50`.
  - It prints item ids and subtypes only, no key. No paid call.
  - It was dry-run here with a stub connection only: the SQL text was built, with two
    bound text parameters, and no database was reached. From the main checkout:

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path

from idx_agent.db.pool import connect
from idx_agent.safety.columns import check_column

pilot = Path("data/enrichment/omission-pilot-v2")


def rows(name):
    with (pilot / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


flagged = {
    r["item_id"]
    for r in rows("judgments.jsonl")
    if "condo_subtype_unchecked" in r["flags"]
}
keys = {i["item_id"]: i["listing_key"] for i in rows("sample.jsonl") if i["item_id"] in flagged}
assert len(keys) == 2, "expected the 2 flagged condominium items"
key_col = check_column("rets_property", "L_ListingID")
type_col = check_column("rets_property", "L_Type_")
marks = ", ".join(["%s"] * len(keys))
sql = (
    f"SELECT {key_col}, {type_col} FROM rets_property "
    f"WHERE {key_col} IN ({marks}) LIMIT 50"
)
conn = connect()
try:
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(keys.values()))
        found = cursor.fetchall()
finally:
    conn.close()
subtypes = {}
for row in found:
    subtypes.setdefault(str(row[key_col]), []).append(row[type_col])
for item_id, key in sorted(keys.items()):
    print(item_id, subtypes.get(key, []))
PY
```

- Unchanged, hashes checked before and after: the v2 sample and manifest, every v1 file,
  `judgments.jsonl`, `aggregates.json`, the review shards, the rubric, second read and
  adjudication, the ruling 8 overlay and its manifest, and the source and store DBs.
- Low note on `5887caa`, the cherry-pick of `95f3d2f`: its message does not end with
  the Co-Authored-By line. The line is present, but `-x` appended the
  "(cherry picked from ...)" line after it. The commit is not rewritten (no force push).
- Not done: no paid or provider call, MySQL query, extraction, store build, install,
  activation or merge. The policy file, #147, #148, #150, #153 and #155 were not touched.
- Next: the owner's human pass on the 51-item packet; the condo subtype check after D1.

2026-11-04 (condo subtype check, after D1): the owner reported D1 done (the main checkout
on `main` at `9cff4bf`) and approved the check. The read-only select in the Status entry
above ran once from the main checkout through `idx_agent.db.pool.connect`, with the
allowlisted `L_ListingID` and `L_Type_`, bound values and `LIMIT 50`. It returned one
subtype per item and printed item ids and subtypes only. Result, under ruling 4 (the
subtype column decides): the cue omission has a condominium subtype, so it stands; the
labeled item judged correct has a townhouse subtype, so its non-present status stands.
The condo flag no longer affects any figure, and no judgment or aggregate file was
changed. No paid call.
