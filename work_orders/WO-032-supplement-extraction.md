# WO-032 — Supplement extraction for the never-extracted active listings

**Driver:** agent (owner grants any paid token and records console figures)
**Depends on:** WO-018 (frozen full run), WO-021 (effective store, refresh preflight)
**Estimated effort:** 3 hours key-free; no paid part (closed under D-032 option a)

## Objective
Give the 321 active listings that the refresh preflight classed `never_extracted`
(`docs/ENRICHMENT_REFRESH_PREFLIGHT.md`, 2026-11-02) facets from the same frozen contract
the full run used, appended as a tagged wave, or show why that cannot be done.

## Why
The effective store covers 54,888 of 55,209 active listing IDs. A refresh is only clean
when every active listing is either covered or known to need nothing.

## Inputs
- The preflight inventory `data/enrichment/refresh/preflight-inventory.jsonl` (private).
- The full-run results table `data/enrichment/full/active-facets-v2.sqlite3` (private):
  its recorded settings are model `claude-sonnet-5-5`, prompt SHA-256 `e1ccb614…5ba24`
  (`docs/ENRICHMENT_EXTRACTION_V2.md`), schema SHA-256 `036155fd…47a03`, version `v2`,
  watermark `2026-09-18 06:58:44`; 54,888 rows (324 `v1`, 54,564 `v2`), 55 batches
  complete, 13 verification rows all at that watermark.
- The full-run driver `scripts/extract_enrichment_v2_batch.py` and its checks:
  `verify_freeze` (frozen v1 files), `verify_v21_freeze` (`docs/ENRICHMENT_V21_FREEZE.json`,
  pinned SHA-256), the v2 prompt and canonical schema hashes, `contract_hashes` against the
  private dev record, and `sonnet_fallback_selected` (the v2.1 dev decision).
- `enrichment.full_batch.records` and `semantic.build_index.iter_pages`: the full run's
  source reader (active rows, 50-row keyset pages, newest row per ID, whole remark
  redacted, blank remarks skipped).
- `enrichment.source_check` and `enrichment.effective_store`: the approved results digest.

## Finding (2026-11-03): there is nothing to extract
All 321 `never_extracted` IDs are active in the source, each with one row at or before
the watermark, and **every one has a NULL `L_Remarks`** (321 null, 0 blank, 0 with text).
The full run's reader skips a listing without a remark, so it yields exactly 54,888
records, the same 54,888 the results table holds and that the run's completion audit
verified. That also matches the WO-010 profile (54,884 of 55,212 active rows with a
usable remark). The 321 were never extracted because there was no remark to send.

So the paid wave would have zero eligible requests. The frozen contract cannot be applied
to an empty remark: the request needs remark text, and every annotation must quote it.
Sending a placeholder would be a new contract, not the frozen one. Under the brief's stop
conditions and CLAUDE.md ("the work order is ambiguous about scope: ask"), the paid step,
the supplement digest constant and the supplement-dependent store rebuild stop here for
an owner decision.

## Owner decision D-032 (options as presented; option 1 chosen, see below)
1. **Close WO-032 as not applicable (recommended; chosen as option a).** The 321 stay outside the store.
   Feature search already treats an uncovered listing as unknown and never matches it on
   a feature, which is the correct reading of "no remark". No paid call, no store change.
2. **Cover them as "no remark" without extraction.** Record the 321 as covered listings
   with no facet statuses, so the preflight stops listing them. This is a change to store
   semantics (covered no longer means extracted), to `listing_count` (55,209) and to
   `open_store`'s count check. It needs its own work order; it is not extraction.
3. **Expect remarks from newer data.** If a newer snapshot carries remarks for these IDs,
   re-run the refresh preflight on it first. Those IDs would then be `new` or `changed`
   (rows after the watermark), and the supplement input set would be different.

## Decision D-032 (owner, 2026-11-03)
- **Chosen:** option (a), the first option above: close WO-032 as not applicable.
- **Effect:** the 321 description-less active listings stay outside the effective store
  and stay unknown for every feature. Feature search keeps treating them as uncovered,
  which is the right reading of a listing with no remark.
- **Not to be done:** no placeholder extraction, no paid call, no paid token or mint line,
  no supplement rows, no change to the results table, its digest constant or `open_store`.
- **Rationale:** the frozen contract needs remark text and a quote for every annotation,
  and all 321 have a NULL remark, so the paid wave has no eligible request. Covering them
  with a placeholder would be a new contract (option 2), not this work order.
- **Not decided here:** whether the read-only precondition module and dry-run script stay
  as a reusable preflight (see Status, open owner decision D-032b). Nothing is deleted.

## In scope (done in this PR, key-free)
- `src/idx_agent/enrichment/supplement.py`: pure precondition checks for a supplement
  wave: inventory parsing, the results table's contract, size, digest, verification and
  batch state, the input set (count 321, no result or input row), one pass over the
  source with the full run's reader (prefix unchanged, input set present, remark
  presence counted), the call plan and its ceiling (400 units, enforced in code).
- `scripts/extract_enrichment_supplement.py --dry-run`: runs every precondition with the
  full run's own check functions, reading the results table with SQLite `mode=ro`, and
  prints aggregates. Without `--dry-run` it refuses (exit 2): the paid path is not built,
  and under D-032 it will not be.
- Tests on synthetic data, and a fail-closed test for the existing digest check.

## Out of scope
- Any provider call, key read, paid token, `consent.sh` run or batch submission.
- The paid submit and collect steps, the supplement digest constant and its builder and
  `open_store` changes: not to be built under D-032 (design below kept as a record only).
- Rebuilding the effective store under any policy, editing WO-018/WO-021/WO-024/WO-026
  or the v5 overlay. The v5 store rebuild belongs to WO-035 (below).

## Files expected to change
`src/idx_agent/enrichment/supplement.py` (new), `scripts/extract_enrichment_supplement.py`
(new), `tests/test_enrichment_supplement.py` (new), one test appended to
`tests/test_enrichment_source_check.py`, this work order, one `docs/EVIDENCE_LOG.md` entry.

## Interfaces and contracts
No contract in `docs/CONTRACTS.md` changes. The results table, its digest constant
(`EXPECTED_RESULTS_DIGEST`), `verify_source` and `open_store` are unchanged.

## Implementation requirements
1. Preconditions run in this order and stop at the first failure, each with a fixed code:
   frozen v1 files; v2.1 freeze manifest; v2 prompt and schema; dev decision selects
   Sonnet (any failure: `freeze_hash_mismatch`); results table is the frozen full run
   (`full_run_contract_mismatch`, `results_row_count_mismatch`, `results_digest_mismatch`,
   `verification_watermark_mismatch`, `batches_not_complete`); input set count is 321
   (`input_set_count_mismatch`); no input already has a row (`input_set_overlaps`);
   watermark unchanged before and after the scan (`watermark_changed`); original source
   unchanged and every input present (`source_mismatch`); at least one eligible remark
   (`no_eligible_remarks`); planned units within 400 (`ceiling_exceeded`).
   Presence counts distinct IDs, and each ID's remark state is read from the row the
   full run's reader keeps (the first row of each run of equal keys). Older duplicate
   rows are counted as rows only, and an ID that comes back after another key is a
   `source_mismatch`, so a duplicate can never stand in for a missing input.
2. The dry run never reads a provider key, starts a paid run, builds a request or writes a
   file; the results table is opened read-only.
3. Output is aggregate counts and fixed names; no listing key or remark text.

## Safety requirements
Retrieved remarks are data and are never printed. The listings database is read with the
SELECT-only reader in 50-row pages. No data leaves `data/`; only counts and hashes are
recorded in tracked files.

## Tests required
`tests/test_enrichment_supplement.py`: ready when everything holds (3 eligible, 4 units);
remark-less listings refused with null and blank counts; a freeze-hash mismatch stops
before any source read; contract, watermark, facet, provenance, verification, batch-state
and row-count tampering each refused; an appended row refused; input-set count and
overlap refused; malformed inventory refused; a watermark change during the scan ends the
run; a changed original remark and a missing input are source mismatches; a missing
input is still a mismatch when another input has a duplicate row; remark counts follow the
newest row, not an older duplicate; an input that reappears out of order is a mismatch;
the 400 ceiling
holds in code; the script's dry run constructs no request, reads no key, starts no paid
run, leaves the table byte-identical and prints no key; without `--dry-run` it refuses;
a group- or world-readable private input is refused.
`tests/test_enrichment_source_check.py`: a complete, consistent row appended after the
certified ones is refused by the builder's check (digest), so an unapproved supplement
cannot be published today.

## Acceptance criteria
- Ruff clean; `MYSQL_HOST= .venv/bin/python -m pytest -q` passes; content gates and CI pass.
- The dry run on the real private inputs reports its result with aggregates only, and the
  private files' SHA-256 digests are identical before and after.
- Status edited only here; one EVIDENCE_LOG entry for the dry run.

## Verification commands
```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
# from the main checkout, once it is on main with this PR merged (decision D1):
.venv/bin/python -m scripts.extract_enrichment_supplement --dry-run
```

## Supplement digest design (record only; not to be built under D-032)
D-032 chose option (a), so no supplement row will be appended and nothing in this section
is to be built. It stays here as the design a future work order would start from if a
newer snapshot ever carries remarks for these IDs; that would need a new owner decision.
- **Today the source is already fail-closed.** `results_digest` covers every row in the
  table, so any appended row changes it and `verify_source` refuses; `open_store` refuses
  a store whose recorded digest is not the approved constant. The new source-check test
  proves the first. Nothing more is needed while no supplement row exists.
- **If rows are ever appended:** sequences continue after 54,888; each new row gets a
  wave tag in a new `result_waves(sequence PRIMARY KEY, wave TEXT NOT NULL)` table, and no
  original row gets one. The original check is unchanged in value: the same
  `results-digest-v1` digest over sequences 1–54,888 must equal `EXPECTED_RESULTS_DIGEST`.
  A second constant `APPROVED_SUPPLEMENT_DIGEST`, `None` until the owner approves it, is a
  separately versioned digest (`supplement-results-digest-v1`, plus the wave tag) over the
  tagged rows only. The builder and `open_store` (via a new `supplement_digest` meta
  value) refuse when supplement rows exist and the constant is `None`, when it differs,
  when any later row lacks the tag, or when the original prefix differs. Adding the
  approved value is then a one-line, reviewable commit, taken from the source the owner
  approved and never computed by the builder. Tests to add with it: original-only source
  still accepted; supplement without an approved constant refused; with a synthetic
  approved constant accepted; tampered supplement refused; existing row modified refused;
  missing wave tag refused.
- **`open_store` row-count pin: deferred, needs owner acceptance under D-032.** Today
  `open_store` checks the recorded digest against the constant and that the listing count
  equals the recorded `source_rows`, but not that `source_rows` is 54,888, so a
  hand-written store that records the constant digest opens. Only the builder writes
  stores, and it records the constant only after `verify_source` passes, so this is not
  reachable through the supported path. A hard `source_rows == 54,888` pin is left out on
  purpose: the existing effective-store, feature-search, MCP, recommendation and preflight
  tests, and the new tests in open PRs #147, #148 and #150, all write small synthetic
  stores with the constant digest, and the pin would break them after merge. Under D-032
  this hardening no longer waits on a supplement: it moves to WO-035 (versioned v5 store
  migration), which validates the store's count against a trusted expected source count
  and updates the synthetic-store fixtures explicitly instead of weakening the
  production check. It is not built here.

## Later steps (moved out of this work order)
1. D-032 is decided (option a): this work order is closed and none of its paid or mint
   steps run.
2. Store rebuild under policy v5: **not done with today's builder.**
   `scripts/build_enrichment_effective_store.py` reads the frozen v4 policy and its
   manifest and does not apply the v5 rulings or the ruling 8 overlay, so running it
   would not produce a v5 store. The versioned v5 store migration (v4 policy and manifest
   unchanged and v4 still reproducible, a separate v5 manifest pinning every input, v5
   provenance and both manifests recorded in store metadata, and the store-count
   hardening above) is WO-035, drafted in parallel on branch `wo-035-v5-store-migration`.
   Any rebuild, and its counts in WO-021's Status, follow WO-035 and the owner's approval.
   Under D-032 the 321 stay outside, so the expected listing count stays 54,888.
3. Re-measuring the activation handoff probe (`docs/ACTIVATION_HANDOFF.md`, offline
   acceptance, "applied 14") on a rebuilt store follows WO-035, not this work order.

## Deliverables
The precondition module, the dry-run script, the tests, this work order and the evidence
entry. No paid call, no new private file, no store change.

## Stop conditions
Any source mismatch, freeze-hash mismatch, changed watermark or provider refusal ends a
run with no adaptation. An empty eligible set is a stop too: it is not resolved by
changing the input or the prompt.

## Status
closed: not applicable (D-032 option a) — 2026-11-03. The owner chose option (a): the 321
description-less listings stay unknown; no placeholder extraction, paid call, mint line or
supplement row. The paid path and the supplement digest design are not to be built, and
the v5 store rebuild moved to WO-035. Branch merged with `main` at `32cd727` (#151), both
evidence-log entries kept. Returned for review; not merged.

Open owner decision D-032b: keep or drop the key-free preflight. Recommendation: keep
`enrichment/supplement.py`, `scripts/extract_enrichment_supplement.py --dry-run` and their
tests as a reusable read-only preflight. They pin the finding (re-runnable, refuses with
`no_eligible_remarks` today) and would be the first check if a newer snapshot carried
remarks for these IDs; they make no call and write nothing. Dropping them would leave only
this work order, the evidence entries and the source-check test. Nothing is deleted
without that decision and a `delete` token.

Earlier (blocked, 2026-11-03): key-free part done; the paid step is not reachable. Review fix:
the presence check now counts distinct IDs and reads each ID's remark state from the row
the reader keeps (three regression tests). The dry run was re-run on the same inputs and
gave the same result, with 321 distinct IDs present, 321 rows and 0 reappeared. The dry run on
the real private inputs (read-only, from this worktree pointed at the main checkout's
`data/enrichment`) passed every precondition up to the input set and refused with
`no_eligible_remarks`: 321 never-extracted IDs, 0 already in results, 321 present in the
source, 321 with NULL remarks, 0 eligible; original source unchanged (54,888 rows, 324
`v1` and 54,564 `v2`), watermark unchanged before and after. Private file digests were
identical before and after. No paid token is requested and no mint line is issued, since
there is no paid command to bind. Waiting on the owner: decision D-032, then D1 (serving
checkout to `main`) before any run from the main checkout.
