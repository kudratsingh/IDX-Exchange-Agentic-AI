# WO-026 — Omission-risk pilot for the effective remark facets

**Driver:** agent (model review), human review pending
**Depends on:** WO-018 (frozen extraction results, policy audit v4), WO-021 (effective store)
**Estimated effort:** 4-6 hours, plus owner and human review time

## Objective
Measure, on a small frozen and reproducible sample, how often a remark affirms one of the
20 eligible facets as a current feature while the effective store has no `present` status
for it (an omission), and leave a workflow a human can use to confirm or override every
judgment.

## Why
The WO-018 audits checked stored labels only: no one searched for features the extractor
missed, and six facets were audited only in the 471 diagnostic cases. Feature search shows
only `present` listings, so omissions are silent false negatives that WO-021's limitation
line can describe but not size.

## Inputs
- `docs/ENRICHMENT_ANNOTATION.md` (facet semantics, polarity and temporality) and
  `docs/ENRICHMENT_REVIEW_POLICY.md` (rulings 1-8, clarifications v2-v4).
- `src/idx_agent/enrichment/effective.py` (eligible facets, statuses),
  `effective_store.py` (`open_store` validation), `source_check.py` (approved results
  digest, watermark).
- Private, gitignored: `data/enrichment/full/active-facets-v2.sqlite3` (extraction inputs
  and results), `data/enrichment/full/effective-facets-v1.sqlite3` (effective store),
  `data/enrichment/splits.json`, `sample.jsonl`, `deal-signals-supplement.json`,
  `wo021-spot-check-sample.jsonl` (exclusions).

## In scope
1. A pure module and a CLI to (a) draw and freeze a stratified sample, (b) export a
   private review packet, (c) validate and record model or human judgments, (d) compute
   aggregate counts, rates and Wilson intervals.
2. One frozen sample of about 120-160 listing x facet items in a new private directory,
   `data/enrichment/omission-pilot-v1/`.
3. A model review of every sampled item with provenance, `human_review: pending`.
4. A public, aggregate-only report: `docs/ENRICHMENT_OMISSION_PILOT.md`.

## Out of scope
- Re-auditing the 54,888 results, a dataset-wide recall estimate, or any accuracy claim.
- Changing the extractor, prompt, overlays, effective store, benchmark labels, eligibility
  or search behaviour; adding labels found here to any overlay.
- Re-running extraction, paid or model API calls, model downloads, MySQL access.
- Tuning anything against the benchmark splits (they are excluded from the sample).

## Files expected to change
- `src/idx_agent/enrichment/omission_pilot.py` (new)
- `scripts/omission_pilot.py` (new)
- `tests/test_enrichment_omission_pilot.py` (new)
- `docs/ENRICHMENT_OMISSION_PILOT.md` (new)
- `work_orders/WO-026-omission-audit-pilot.md` (this file)

## Interfaces and contracts
- Unit: (listing, eligible facet) with effective status not `present`.
- Strata per facet: `labeled_non_present` (a stored non-present status), `cue` (no status,
  lexical cue matches), `no_cue` (no status, no cue). The six limited facets get 2/7/3
  items; the other 14 get 0/3/2 (their non-present labels were read by the policy audit).
- Selection: per stratum, smallest `sha256(seed|facet|stratum|key)`; a short stratum
  contributes everything. Item ids `op1-NNN` are opaque.
- Decisions: `omitted_present`, `correctly_absent`, `non_present_mention`, `unclear`;
  `existing_status_check` is `correct|wrong|unclear` for labeled items and
  `not_applicable` otherwise. Review types `model` (reviewer prefixed `model:`, human
  review must stay `pending`) and `human` (a human judgment replaces the model's).

## Implementation requirements
1. Sampling refuses to run unless the extraction results match the approved digest, the
   store opens through `open_store` and was built from the same digest, every remark
   matches its recorded hash, and every input is covered by the store.
2. Benchmark (both splits and the sample file), supplement, WO-021 spot-check and the
   471 diagnostic listings are excluded.
3. The manifest records seed, method, allocation, population counts per stratum,
   exclusions, sample sha256, store file sha256 and meta, guide version, code commit and
   whether the pilot's code files were modified.
4. Every private file is created owner-only and exclusively; nothing is overwritten, and
   `sample` refuses an existing pilot directory.
5. `record` validates every judgment against the frozen sample; `aggregate` refuses
   judgments bound to another sample hash and returns no keys or remark text.
6. Per-facet weighted estimates are computed but reported only with small-n warnings;
   unsampled strata are reported as uncovered, never imputed.

## Safety requirements
- No data in tracked files, commit messages or PR text: aggregates only, no keys, remarks,
  quotes or per-listing labels (`SAFETY_INVARIANTS.md`: no MLS data in the repo).
- Remarks are data, never instructions; the reviewer followed none.
- Private SQLite files are opened read-only; SQL is parameterized; the packet fetches
  remarks in statements of at most 50 keys. No MySQL access, no paid call.
- No changes to gates, guards, CI, `.gitignore` or `.claude/settings.json`; no existing
  private artifact is modified or deleted.

## Tests required
`tests/test_enrichment_omission_pilot.py`, invented data only: stratum assignment and
present exclusion; cue matches and misses; allocation total within 120-160; exclusion and
duplicate handling; deterministic, seed-dependent sampling with short strata; judgment
validation (good records and each refusal); human override; Wilson values; weighted
aggregation without keys; CLI packet, record and aggregate on an invented private
directory; refusal of a changed sample, foreign judgments, an existing pilot directory,
shared files and overwrites; exclusion-file handling.

## Acceptance criteria
- Frozen sample of 120-160 items with manifest and sha256 in the new private directory.
- Every item has a validated model judgment with provenance and `human_review: pending`.
- The public report states method, sizes, per-stratum counts with Wilson intervals,
  aggregate patterns, unresolved decisions, and how a human completes the review; labels
  the work as model review and as a pilot; contains no keys, remarks or quotes.
- Ruff and the full test suite pass; nothing outside the files above changed.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= python -m pytest -q -p no:cacheprovider
python scripts/omission_pilot.py sample      # once; refuses if the directory exists
python scripts/omission_pilot.py packet
python scripts/omission_pilot.py record --kind model --draft <draft.jsonl>
python scripts/omission_pilot.py aggregate --name aggregates.json
```

## Deliverables
The module, CLI and tests; the private sample, manifest, packet, judgments, aggregates and
notes; the public report; this work order.

## Stop conditions
Private artifacts missing or failing their digest; reading remarks would need a paid or
external service; the guide too ambiguous to judge a facet (record which); any need to
change an overlay, the store or benchmark labels.

## Status
in review — 2026-11-03 — Review fixes for output confinement and frozen source hashes;
model review complete, human review pending.

Review fixes (2026-11-03, after merging `origin/main` at `cbad756`):
- Output confinement: `--name`, `--judgments` and `--human` must be plain file names in
  the real (non-link) pilot directory; absolute names, separators, `..` and destination
  links are refused, and files are created `O_EXCL | O_NOFOLLOW` relative to the pilot
  directory descriptor opened `O_NOFOLLOW | O_DIRECTORY`.
- Frozen source hashes: `packet` re-checks the approved results digest, then requires
  each sampled item's remark to match its frozen `results.input_hash` (and the input's
  recorded hash); missing or changed text refuses the whole packet before any write,
  naming item ids and positions only.
- Fail-before / pass-after: regressions committed first (`cae14ba`) and run against the
  pre-fix code with
  `MYSQL_HOST= python -m pytest -q -p no:cacheprovider tests/test_enrichment_omission_pilot.py`:
  11 failed, 38 passed (`DID NOT RAISE ValueError` for absolute, `../` and `../../`
  names, record/aggregate names, the symlinked pilot and intermediate directories,
  changed and re-hashed source text; `FileExistsError` for `..`; `KeyError` for missing
  source text). After the fix: 49 passed. The destination-link and `write_new` link
  cases already refused before the fix (`O_EXCL`) and stay as guards.
- Invented fixtures only. The private pilot artifacts were not read, run against or
  changed; no extraction, semantic audit or pilot rerun.

- Code committed first (`7f13418`) so the manifest records an exact, unmodified commit.
- Sample: seed `wo026-omission-20261102`, 142 items (72 for the six limited facets, 70 for
  the other 14) from 54,096 listings after excluding 792; sample sha256
  `5a59e65e3f10ea2ea6700e28738add6fdbf36c4f0c25e74b98127c2b01ebee2b`, manifest sha256
  `ab0af6e84969b9d9e7a9f9792bc2a9e45520c86447d2e630f3d73bd88a71386d`.
- Model review (`model:claude-opus-5-5 (agent session)`): 6 omitted present, 124 correctly
  absent, 4 non-present mentions, 8 unclear. Overall 4.2% (Wilson 2.0-8.9%); cue strata
  5/84; no-cue strata 0/46 (upper bound 7.7%); labeled non-present 1/12. Of 12 stored
  non-present statuses checked, 3 correct, 5 wrong (4 unsupported uncertain labels with no
  matching effect), 4 unclear.
- No facet was too ambiguous to judge as a whole; eight definitional questions (grocery
  retailer scope, community shuttles as transit, stainless scope, implied property type,
  accessory-structure flex space, community recreation centers, a v4 loft case, cleaning
  unsupported uncertain labels) are listed in the report for the owner.
- Nothing changed in the extractor, overlays, store, benchmark labels or search. No paid
  call, extraction run, model download or MySQL query.
- Next: owner decisions on the open questions; human confirmation or override through
  `record --kind human`; then decide whether a larger, no-cue-weighted sample is worth it.

2026-11-03: the owner answered the eight unresolved decisions as review policy v5, in
`docs/ENRICHMENT_REVIEW_POLICY_V5.md` (it extends v4; the v4 file is unchanged). The pilot
document's "Unresolved decisions" points each question to its ruling there. No judgment,
aggregate, frozen sample or `human_review` changed; it is still pending, and the owner does
the human pass over the 142 items. Ruling 8 overlay (PR #151), policy version v5, model
review with human review pending, in a new private file under `data/enrichment/`:
screened 690, read 697 (the 690 plus the pilot's 11 uncertain labels, 4 of them
overlapping), removed 545, kept 152. Of the pilot's 11, 7 were removed and 4 kept. No
store has been built under v5 (WO-021 Status).
