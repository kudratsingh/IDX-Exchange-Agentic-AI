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
   (basename and sha256 each) and the v5 manifest itself.
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
   labelled v5 without consistent v5 provenance, and a v4-labelled store claiming v5
   provenance.

## Safety requirements
- Fail closed: every new refusal is `unavailable` (SAFETY_INVARIANTS, WO-021 store rules).
- No listing text, keys or private contents in tracked files, output or logs. The builder
  and the proposal print aggregates, names and hashes only.
- The proposal and stores are written owner-only (mode 0600) with exclusive create for the
  proposal.

## Tests required
- `tests/test_enrichment_store_hardening.py`: approved digest with a smaller or larger
  count refused; the trusted count opens; a v5 label without v5 provenance and a v4 store
  claiming v5 provenance refused; production trusts exactly one read-only pair.
- `tests/test_enrichment_store_v5.py`: the v4 fingerprint and byte-identical rebuild; v4
  needs no v5 input; v5 work leaves the v4 policy, manifest and store unchanged; v5 applies
  ruling 8 on top of the v4 overlays; dry run writes nothing; no v4 path overwrite; drift of
  each of the 11 pinned inputs refused; manifest canonical form and provenance; every
  cleanup refusal; provenance tampering refused on open; v4 and v5 stores open side by side;
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
   Expect 54,888 listings and the removals in Status below.
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
- Re-observe the handoff's store info line (`policy_version` `v5`).

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
  With the four files switched, its full suite result is recorded in the PR.

Remaining owner decisions: approve the merge order; freeze the v5 manifest; run the
rebuild.
