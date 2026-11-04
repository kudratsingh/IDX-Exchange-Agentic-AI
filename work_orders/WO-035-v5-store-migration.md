# WO-035 — Versioned v5 effective-store migration

**Driver:** agent (builder, manifest format, checks and tests); owner (freezes the v5
manifest and runs the rebuild)
**Depends on:** WO-021 (the effective store), WO-018 (review policy v5 and the ruling 8
overlay, PR #151)
**Estimated effort:** 6 hours (agent); the owner's freeze and rebuild take minutes

## Objective
The effective-store builder can build a store under review policy v5 (the v4 labels with
ruling 8's correction overlay on top), pinned by its own v5 manifest, while the v4 build,
the v4 policy file and the v4 freeze manifest stay exactly as they are.

## Why
Review policy v5 is approved (`docs/ENRICHMENT_REVIEW_POLICY_V5.md`), and WO-021 Status
(2026-11-03) requires the serving store to carry v5 before the Phase 1 install in the
activation handoff. Until this work order, the builder could only produce v4.

## Inputs
- `scripts/build_enrichment_effective_store.py` (`verify_manifest`, the build).
- `src/idx_agent/enrichment/effective_store.py` (`write_store`, `open_store`,
  `_validate`), `effective.py`, `source_check.py` (`EXPECTED_RESULTS_DIGEST`,
  `EXPECTED_ROWS`, `verify_source`), `access.py` (unchanged; it opens stores only through
  `open_store`).
- `docs/ENRICHMENT_REVIEW_POLICY.md` (v4, frozen) and `docs/ENRICHMENT_REVIEW_POLICY_V5.md`.
- Private, read only: the v4 freeze manifest (`data/enrichment/policy-audit-freeze-manifest.json`),
  the ruling 8 overlay and its manifest (`data/enrichment/v5-uncertain-cleanup-overlay.jsonl`,
  `data/enrichment/v5-uncertain-cleanup-manifest.json`), the results table and the v4
  store.

## In scope
1. **v4 preserved.** The v4 policy file and the v4 manifest file are never modified. The
   default build (`--policy v4`) reads the same inputs, checks the same manifest and writes
   the same meta. A test rebuilds a synthetic v4 store and pins its contents to a
   fingerprint taken from the builder before this work order.
2. **v5 build mode** (`--policy v5`). It reads the approved v5 policy file and ruling 8's
   overlay and applies the overlay on top of the v4 diagnostic and dataset overlays. The
   overlay may only remove `uncertain` labels on the six limited facets (condominium,
   garage, near_grocery_mentioned, near_transit_mentioned, single_level,
   stainless_appliances), and every record must agree with its manifest. Anything else is
   refused.
3. **A separate v5 manifest** pinning every input: the v4 policy file, the v5 policy
   file, `policy_rules.py` and the rules version, the v4 diagnostic and dataset packets,
   overlays and scope, the v4 manifest file itself, the ruling 8 overlay and its manifest,
   the approved results digest, the trusted source count and the source watermark.
   `scripts/propose_enrichment_v5_manifest.py` writes a proposal only to a path the owner
   chooses. It never writes over an existing file or a pinned input.
4. **v5 store meta.** `policy_version` is `v5`; `built_from` records both manifests
   (basename and sha256 each) and the v5 manifest itself; `policy_scope` states exactly
   `policy v5; rulings applied: 8 overlay only; rulings 1-7 not applied to stored labels`
   (owner decision, 2026-11-03). A v4 store has no `policy_scope`.
5. **Verification on open.** `open_store` and the builder check a v5 store's provenance
   and still open valid v4 stores.
6. **Store-count hardening** (owner item 3). The approved digest is paired with a trusted
   source count (54,888). The builder and `open_store` refuse a store carrying that digest
   with any other count. Test stores use a synthetic digest/count pair registered for one
   test only; the production check is not relaxed.

## Out of scope
- Building or replacing the serving store, writing any store outside test temp
  directories, installing, restarting, enabling or activating anything.
- Freezing the v5 manifest into `data/enrichment/` (the owner does that).
- Applying rulings 1 to 7 to stored labels. The re-read is a separate owner decision
  (WO-018 Status).
- Paid calls, extraction, the semantic audit, live database writes.
- Changing `access.py`, the search, badge, explanation or alert consumers.

## Files expected to change
- `scripts/build_enrichment_effective_store.py`: v4 path kept, `--policy`, `--v5-manifest`,
  `--data-root` and `--dry-run` added.
- `scripts/propose_enrichment_v5_manifest.py` (new).
- `src/idx_agent/enrichment/store_v5.py` (new): the cleanup checks, the v5 manifest format,
  `built_from` and the provenance check.
- `src/idx_agent/enrichment/effective.py`: `effective_labels` split out of `effective_rows`
  (same output).
- `src/idx_agent/enrichment/effective_store.py`: trusted count and v5 provenance in
  `_validate`.
- `src/idx_agent/enrichment/source_check.py`: `TRUSTED_SOURCES`, `trusted_source_rows`.
- `tests/synthetic_store.py` (new), `tests/conftest.py` (one fixture),
  `tests/test_enrichment_store_v5.py` and `tests/test_enrichment_store_hardening.py` (new),
  and the five test files on main that wrote small fake stores with the approved digest.
- `docs/CONTRACTS.md`, `docs/adrs/0014-effective-facet-store.md` (amendment),
  `work_orders/WO-021-enrichment-integration.md` (pointer), this file.

## Interfaces and contracts
`docs/CONTRACTS.md`, "Effective-facet store (WO-021, WO-035)". In short:
- `source_check.trusted_source_rows(digest) -> int | None`.
- `open_store` reasons gain `source_count_mismatch` and `provenance_mismatch`. Both are
  `unavailable`, so consumers fail closed as before.
- `store_v5.verify_v5_manifest`, `validate_cleanup`, `cleaned_rows`, `built_from`,
  `check_store_provenance`.

## Implementation requirements
1. The v4 build's output is unchanged for the same inputs (pinned fingerprint; a rebuild
   gives a byte-identical file).
2. A v5 build refuses unless the v4 manifest passes, the v5 manifest is canonical and every
   pinned hash matches, the v5 manifest's v4 entries equal the v4 manifest's, and its digest,
   count, watermark and rules version are the trusted ones.
3. A v5 build refuses any ruling 8 record that is not a v5 reading of a limited facet
   starting `uncertain`, that adds a label, removes a non-`uncertain` label or one of another
   facet, ends `present`, or disagrees with the v4 labels or its manifest's counts.
4. A v5 build never writes to the v4 store path and never takes the v4 manifest as its v5
   manifest. Its default output is `data/enrichment/full/effective-facets-v5.sqlite3`.
5. `open_store` refuses a store whose count differs from the trusted count, a store
   labelled v5 without consistent v5 provenance, a v4-labelled store claiming v5
   provenance, a v5 store whose `policy_scope` is missing or differs from the sentence
   above in any character, and a v4 store that has a `policy_scope`.

## Safety requirements
- Fail closed: every new refusal is `unavailable` (SAFETY_INVARIANTS, WO-021 store rules).
- No listing text, keys or private contents in tracked files, output or logs. The builder
  and the proposal print aggregates, names and hashes only.
- The proposal and stores are written owner-only (mode 0600) with exclusive create for the
  proposal.

## Tests required
- `tests/test_enrichment_store_hardening.py`: approved digest with a smaller or larger
  count refused; the trusted count opens; a v5 label without v5 provenance and a v4 store
  claiming v5 provenance refused; a v4 store stating the v5 scope refused; production
  trusts exactly one read-only pair.
- `tests/test_enrichment_store_v5.py`: the v4 fingerprint and byte-identical rebuild; v4
  needs no v5 input; v5 work leaves the v4 policy, manifest and store unchanged; v5 applies
  ruling 8 on top of the v4 overlays; dry run writes nothing; no v4 path overwrite; drift of
  each of the 11 pinned inputs refused; manifest canonical form and provenance; every
  cleanup refusal; provenance tampering refused on open; a v5 store states the exact
  policy scope and one without it (missing, empty, shortened, other rulings, trailing
  space, other case) is refused; v4 and v5 stores open side by side;
  the proposal is private, deterministic and never overwrites.
- Every existing test that wrote a fake store uses `tests/synthetic_store.py`.

## Acceptance criteria
- Fail before, pass after: the hardening tests fail on `32cd727` (five of six) and pass on
  this branch.
- The v4 fingerprint equals the one produced by the builder at `32cd727` on the same
  synthetic world.
- The read-only rehearsal against the real private inputs passes the real `verify_manifest`,
  reproduces the v4 statuses exactly, and computes the v5 removals; no store is written.
- Ruff and the full suite pass locally and in CI.

## Verification commands
```bash
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/ruff check . && .venv/bin/ruff format --check .
# Read-only rehearsal (writes only the proposal, to a path you choose):
.venv/bin/python scripts/propose_enrichment_v5_manifest.py --output /tmp/proposed-v5.json
.venv/bin/python scripts/build_enrichment_effective_store.py --dry-run
.venv/bin/python scripts/build_enrichment_effective_store.py --policy v5 --dry-run \
  --v5-manifest /tmp/proposed-v5.json
```

## Deliverables
The v5 build mode, the proposal command, the count and provenance checks, the shared
synthetic-store helper, the tests above and this work order. No store and no frozen v5
manifest.

## Stop conditions
- **A builder or proposal refusal on any branch is a stop condition**, not a status note.
  Fix the cause before the work goes on; never edit a pinned input or a manifest to make a
  check pass.
- The v4 manifest or the v4 policy file would have to change.
- The ruling 8 overlay would have to add a label, change a non-`uncertain` label, or touch
  a facet outside the six.
- The rehearsal's v4 statuses differ from the v4 store, or the v5 removals differ from the
  ruling 8 manifest.
- Anything would need a paid call, extraction, a live write or a store on the serving path.

## Activation (owner)
1. After this merges, on `main` and from the repository root, write a proposal and review
   it (names and hashes only):
   `.venv/bin/python scripts/propose_enrichment_v5_manifest.py --output <your path>`.
   The proposal pins the current bytes of `docs/ENRICHMENT_REVIEW_POLICY_V5.md`. Any edit
   to that file must land before the freeze; after it, the file is frozen like v4.
2. Freeze it by copying the reviewed proposal to
   `data/enrichment/effective-store-v5-manifest.json`. The v4 manifest stays beside it,
   unchanged.
3. Dry run: `.venv/bin/python scripts/build_enrichment_effective_store.py --policy v5 --dry-run`.
   Expect 54,888 listings, the removals in Status below and the `policy_scope` sentence.
4. Rebuild: `.venv/bin/python scripts/build_enrichment_effective_store.py --policy v5`.
   It writes `data/enrichment/full/effective-facets-v5.sqlite3` (0600). The v4 store is
   not touched.
5. Point `IDX_ENRICHMENT_STORE` at the v5 file only as part of the activation handoff's
   install step, not before.

## Rollback
Keep the v4 store file (`data/enrichment/full/effective-facets-v1.sqlite3`) and the v4
manifest. Switching back means setting `IDX_ENRICHMENT_STORE` to the v4 path. The v4 store
still opens under the new checks (54,888 rows with the approved digest). Nothing is
deleted.

## After the rebuild
- Record the v5 store's `listing_count` and status counts in WO-021 Status (WO-021's own
  file).
- Re-measure the activation handoff's Pasadena `solar` probe on the rebuilt store. It was
  `applied 14` on v4. The rehearsal below expects no change, but the value must be
  observed, not assumed.
- Re-observe the handoff's store info line (`policy_version` `v5`) and the store's
  `policy_scope` meta (the sentence in In scope 4).

## Status
in progress — 2026-11-03 — implemented on `wo-035-v5-store-migration`, in review.

*Fail before, pass after.* `tests/test_enrichment_store_hardening.py` was run unchanged in
a detached scratch worktree of `32cd727` (the pre-fix `main`). Five tests fail there:
- a six-listing store with the approved digest opens;
- a store with one extra listing opens;
- a store labelled `v5` with v4 provenance opens;
- a v4 store claiming v5 provenance opens;
- the trusted-pair function is missing.
The control (the trusted count opens) passes on both. All six pass on this branch.

*v4 preserved.* The pre-fix builder at `32cd727` and this branch's v4 mode were run on the
same synthetic world. Both gave the same semantic fingerprint (`1aee8574…`, pinned in
`tests/test_enrichment_store_v5.py`), and the two store files were byte-identical.

*Read-only rehearsal (Mac, 2026-11-03).* The checkout under test supplied the tracked
policy and rules files; every private input was read in place in the main checkout. No
store was written anywhere, and the hashes of the v4 manifest, the v4 store and the ruling
8 overlay and manifest were the same before and after.
- The real `verify_manifest` passes with the real v4 manifest.
- The new `open_store` opens the real v4 store: `policy_version` `v4`, 54,888 listings.
- v4 dry run: 54,888 listings. Statuses are identical to the release handoff: present
  168,333, uncertain 5,358, planned 1,346, stated absent 312, historical 168,
  contradictory 10. The computed v4 rows equal the v4 store's rows for all 54,888
  listings.
- v5 dry run, against a proposed manifest written under the session scratchpad: 54,888
  listings; 545 removals on 542 listings.
  - By facet: condominium 72, garage 412, near_grocery_mentioned 7,
    near_transit_mentioned 26, stainless_appliances 28, single_level 0. This matches the
    ruling 8 manifest.
  - Every change is `uncertain` to unknown; uncertain goes 5,358 to 4,813; every other
    status count is unchanged.
  - `present` stays 168,333 and solar `present` stays 8,164 listings.
- The proposed v5 manifest pins 11 inputs. It was written only under the session
  scratchpad (sha256 `c091cd46…`), not under `data/enrichment/`. The owner writes and
  freezes their own after merge (Activation).

*Cross-PR impact (scratch merges of this branch's first commit into each open PR, Mac).*
- PRs #147, #148 and #150 write small fake stores from `META` with the approved digest.
  Their stores no longer open once this lands:
  - #147: 6 tests in `tests/test_phase_integration.py`;
  - #148: 2 tests in `tests/test_phase_integration_charts.py`;
  - #150: 5 tests in `tests/test_phase_integration_saved_searches.py` and 36 in
    `tests/test_saved_feature_searches.py`.
- In each case the fix is the same small change: write the store with
  `tests.synthetic_store.write_synthetic_store`. With it, all four files pass (17, 16 and
  84 tests).
- `tests/test_chart_delivery.py` (#148) writes no store. Its one failure in the parallel
  run (`[sigint]`) passed when rerun alone (113 passed), so it was a timing flake under
  load, unrelated to this change.
- #144, #145 and #152: full suites pass with this branch merged in (4,574, 4,610 and
  4,553 passed).
- Recommended order: #144, #145, #147, #148, #150 and #152 first, in any order, then
  this PR. It merges `main` and switches the four files to the helper. That keeps every
  PR green on its own CI; only this PR adapts.
- A scratch merge of `main` with all six PRs and then this branch had no conflicts.
  With the four files switched, its full suite passes: 5,022 passed, 130 skipped (Mac).

*Policy scope in the v5 store meta (owner decision, 2026-11-03).* A v5 build now writes
meta `policy_scope` with exactly: policy v5; rulings applied: 8 overlay only; rulings 1-7
not applied to stored labels (`store_v5.POLICY_SCOPE`). `open_store` refuses a v5 store
whose scope is missing or differs in any character, and a v4 store that has any
`policy_scope` (`provenance_mismatch` in both cases). v4 stores are unchanged: no
`policy_scope`, and the v4 fingerprint is still `1aee8574…`.
- *Fail before, pass after.* The eight new tests were run on `21e84ad` (this branch before
  the change) and all eight failed there: the v5 build does not write the sentence; a v5
  store opens with the scope missing, empty, shortened, naming other rulings, with a
  trailing space or in another case; and a v4 store stating the scope opens. All eight
  pass after the change.
- *Proposal unchanged.* The scope is store meta, not a manifest field, and the change
  touches none of the 11 pinned inputs. A fresh proposal, written only under the session
  scratchpad from the real private inputs (read in place, read-only), has the same
  sha256 as before (`c091cd46…`). A read-only v5 dry run against it reports 54,888
  listings, the same 545 removals, uncertain 4,813, and the `policy_scope` sentence. No
  store was written. The hashes of the v4 manifest, the v4 store and the ruling 8 overlay
  and manifest were the same before and after.
- *The v5 manifest freeze is the owner's step.* Nothing on this branch freezes it. The
  proposal command writes a proposal only, to a path the owner chooses (Activation 1-2).

*#154 (`wo-033-omission-pilot-v2`, `c356c2a`, based on #144).* Its fixture in
`tests/test_enrichment_omission_pilot_v2.py` monkeypatches
`effective_store.EXPECTED_RESULTS_DIGEST`. This branch removed that attribute, so a
scratch merge of #144 (`f85e35c`), #154 and this branch gives 7 setup errors there (17
passed).
- A backward-compatible attribute was tried in scratch and rejected. The monkeypatch then
  succeeds but has no effect, because `open_store` trusts only `TRUSTED_SOURCES`. Three
  tests then fail on refused stores instead of erroring. The production count check is
  not relaxed for it.
- The fix is two lines in the fixture: import `trust_source` from
  `tests/synthetic_store.py` and call `trust_source(digest, len(rows))` in place of the
  `effective_store` monkeypatch. With that change, the file passes (24 passed).
- Order: #154 merges after #144 and before this PR. This PR then merges `main` and adapts
  that fixture, together with the four files listed above.

*Combined scratch merge (current heads, Mac, 2026-11-03).* `main` (`32cd727`) with #144
`f85e35c`, #145 `ee1c20f`, #147 `2d84ce1`, #148 `6a27dca`, #150 `290b494`, #152 `0a02943`,
#153 `35eed29` and #154 `c356c2a`, then this branch (`a817dd8`, the policy-scope commit).
#156 is excluded because another workstream is still editing it.
- #155 merged with no conflict. One conflict between other PRs: #152 and #153 both append
  to `docs/EVIDENCE_LOG.md` at the same place. In scratch it was resolved by keeping both
  entries; this PR does not touch that file.
- Before adapting, the affected files gave 49 failures and 7 errors: #147 6, #148 2,
  #150 5 + 36, and #154's 7 setup errors.
- With the four files switched to `write_synthetic_store` and the #154 fixture adapted,
  the full suite passed: 5,062 passed, 130 skipped. It also passed with
  `IDX_ANALYSIS_IMAGE` set (5,062 passed, 130 skipped).
- This branch alone: 4,533 passed, 130 skipped, both with and without
  `IDX_ANALYSIS_IMAGE`.
- Recommended order (kept): #144, then #154; #145, #147, #148, #150, #152 and #153 in any
  order; then this PR last. Each PR stays green on its own CI, and only this PR adapts:
  it merges `main`, then switches the four store-writing test files and the #154
  fixture to the helper.

Remaining owner decisions: approve the merge order; freeze the v5 manifest (the owner's
step); run the rebuild.

*Owner decisions, round three (2026-11-03).* **D7 approved as written.** #148 merges
before #155, and #155 merges last. When it merges `main` after the others, it adapts
the store-writing tests of #147 (`tests/test_phase_integration.py`), #148
(`tests/test_phase_integration_charts.py`) and #150
(`tests/test_phase_integration_saved_searches.py`, `tests/test_saved_feature_searches.py`)
to `write_synthetic_store`, and the #154 fixture
(`tests/test_enrichment_omission_pilot_v2.py`) to `trust_source`, using the saved
adaptation patch (5 files, 10 insertions, 5 deletions; the change described above). **The
v5 manifest freeze stays the owner's step**; nothing on this branch freezes it.
- `origin/main` `27c4ef1` (#156) merged in by merge commit `c64731d`, no conflicts. This
  branch: 4,539 passed, 130 skipped, both with and without `IDX_ANALYSIS_IMAGE`.
- Since then `main` moved to `48b74ab` (#144, #154, #145 and #152 merged). With #154 on
  `main`, this branch merged with `main` gives the 7 known setup errors in the #154
  fixture (17 passed, 7 errors), so the pull-request CI run is expected to show them
  until this branch merges `main` again and applies the #154 part of the adaptation.
  That merge was not made here; it waits for the merge order above.
- *Combined scratch merge (Mac; superseded by the re-run below: #148 and #153 had
  already moved past the heads named here).* `main` `48b74ab` (includes #144
  `f85e35c`, #145 `ee1c20f`, #152 `7c0fea7`, #154 `65b53cc`), then #147 `2d84ce1`, #148
  `6a27dca`, #150 `757c212`, #153 `b4af2f3`, #154's later docs commit `95f3d2f`, then this
  branch (`c64731d`).
  - Conflicts between other PRs, resolved in scratch only: #148 against `main` in
    `src/idx_agent/analysis/tool.py` (#148's helpers kept with #156's fail-closed image
    rule and message); #153 against `main` in `docs/EVIDENCE_LOG.md` (both entries
    kept). This branch merged with no conflict.
  - Before adapting: 51 failed, 7 errors. 49 failures and the 7 errors are this PR's
    known store-writing impact (#147 6, #148 2, #150 5 + 36, #154 7 errors).
  - After the adaptation patch: 5,069 passed, 2 failed, 130 skipped, the same with
    `IDX_ANALYSIS_IMAGE` set. The 2 failures are #147's
    `test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns[image]` and
    `[image-switch-in-both]`, which still expect the image conflict to warn only. They
    fail the same way on `main` + #147 alone (2 failed, 15 passed), so they come from
    #156, not this PR; #147 updates them.
- *Correction, combined scratch merge re-run (Mac, 2026-11-03).* The run above named
  #148 `6a27dca` and #153 `b4af2f3` as current heads; both had newer heads before it was
  recorded. Re-run with the heads checked right before the run: `main` `48b74ab`, then
  #147 `f0978c8`, #148 `a5016be`, #150 `757c212`, #153 `68cbf24`, #154's docs commit
  `95f3d2f`, then this branch (`4034eef`), then the saved adaptation patch.
  - #148 now merges with no conflict (`a5016be` merged `27c4ef1` itself), so the
    `src/idx_agent/analysis/tool.py` conflict noted above no longer applies. #153 still
    conflicts with `main` in `docs/EVIDENCE_LOG.md` (both appended entries kept, scratch
    only). This branch merged with no conflict; the patch applied cleanly.
  - Result: 5,074 passed, 0 failed, 130 skipped, the same with `IDX_ANALYSIS_IMAGE` set;
    ruff clean. #147's `f0978c8` updates its two image-conflict tests to the fail-closed
    rule, so the 2 failures recorded above are gone.
  - #147 then moved to `2c9d933` (it merges `main` `48b74ab` and adds docs only).
    Merging `2c9d933` on top gives the same result: 5,074 passed, 0 failed,
    130 skipped in both modes; ruff clean.

Remaining owner steps: freeze the v5 manifest; run the rebuild.
