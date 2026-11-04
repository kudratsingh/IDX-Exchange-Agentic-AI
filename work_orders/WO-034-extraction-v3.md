# WO-034 — Extraction v3 research candidate (policy v5 in the prompt, evidence spans)

**Driver:** agent; the owner grants each paid token and reviews each phase's PR
**Depends on:** WO-018 (v2 and v2.1 contracts, scorer, dev and held-out splits);
`docs/ENRICHMENT_REVIEW_POLICY_V5.md` (PR #151, merged at `32cd727`)
**Estimated effort:** planning input only, not a commitment

## Objective
A candidate extraction contract that writes review policy v5 into the prompt, returns an
evidence span for every facet decision as its own field, and can be scored against the
existing dev and held-out splits without touching the serving store.

## Why
The bulk store was extracted under v2, whose prompt carried one facet rule. The policy
audit and the v5 overlay later corrected the store by review. A prompt that carries the
policy from the start, with checkable evidence on every decision, may need less
correction later. That is a hypothesis, which this work order measures on dev and
held-out before anything else is decided.

## Inputs
`docs/ENRICHMENT_EXTRACTION_V2.md`, `docs/ENRICHMENT_EXTRACTION_V21.md`,
`docs/ENRICHMENT_V21_FREEZE.json`, `docs/ENRICHMENT_SCORING_V1.md`,
`docs/ENRICHMENT_REVIEW_POLICY.md` (v4, frozen), `docs/ENRICHMENT_REVIEW_POLICY_V5.md`,
`docs/ENRICHMENT_HELDOUT_RESULTS.md`, `docs/ENRICHMENT_V21_DEV_RESULTS.md`, WO-018 Status,
`src/idx_agent/enrichment/v2.py` and `v21.py`, `scripts/extract_enrichment_v21_dev.py`
(the retry gate, checkpoints and usage accounting that Phase B reuses).

## Phases (one PR each)

### A. Contract, docs only (this PR)
- **In scope:** this work order; `docs/ENRICHMENT_EXTRACTION_V3.md` (prompt, schema,
  request settings, rationale, changes from v2.1 with the v5 ruling each serves, facet
  set, proposed new facets for owner decision, scoring plan with the span-quality check);
  `docs/ENRICHMENT_V3_FREEZE.json`; `tests/test_enrichment_v3_freeze.py`, the only code.
- **Prerequisites:** #151 merged (it is).
- **Acceptance checks:**
  1. The facet set is exactly the 20 eligible facets. The test checks it against
     `V2_FACETS` and `ELIGIBLE_FACETS`, and checks that the prompt's guide has one line
     per facet.
  2. Every decision in the schema requires `evidence_span` (`quote`, `occurrence`).
  3. The schema fits strict tool use: every object closed and fully required, and no
     length or range keywords. The test walks the whole schema.
  4. The prompt, schema and request hashes are recorded in the freeze file before any
     paid call (`paid_calls_before_freeze: 0`), and the test recomputes all three from
     the doc. An edit inside any of the three blocks fails the suite; an edit outside them
     does not.
  5. The test imports no provider client (checked from its own source) and makes no
     network call.
  6. No dev or held-out remark text, quote, listing key or key material appears in any
     tracked file.
  7. Ruff and the full suite pass on the Mac and in CI.
- **Stop conditions:** any wish to add or drop a facet; any new dependency or service;
  any need for private data beyond the published aggregates.

### B. Key-free driver, parser and span check
- **In scope:** a v3 module and dev and held-out drivers that reuse the v2.1 retry gate
  (three attempts per remark, each spending one paid call), checkpoints, usage
  accounting and owner-only private output files under `data/enrichment/`. The parser
  converts decisions into the existing scorer's annotation shape, with offsets computed
  locally from the quote and occurrence. The scorer is unchanged
  (`ENRICHMENT_SCORING_V1`: polarity-aware overlap, exact numeric) and applies through
  `score_v2` to the 20 facets. A span-quality check: the span is inside the source
  remark, and it overlaps a gold span of the same case, facet and polarity. Synthetic
  tests only.
- **Prerequisites:** Phase A merged. No key, no paid token.
- **Acceptance checks:**
  1. Before it spends a token, the driver verifies `docs/ENRICHMENT_V3_FREEZE.json`,
     pinned by its own SHA-256, and the three block hashes. A synthetic mutation of the
     prompt, schema, request settings or v3 implementation stops before a token is used.
  2. A quote over 80 characters, an `occurrence` below 1 or past the last appearance, an
     unfound quote, a missing tool call and a malformed decision are each a validation
     miss with a sanitized field/rule diagnostic, and processing continues.
  3. The span check is tested on invented remarks: inside and overlapping, inside and not
     overlapping, not found, wrong occurrence.
  4. The v1, v2 and v2.1 freeze files and scorer files are byte-identical to `main`.
  5. A fake provider (monkeypatched transport, as in `tests/test_enrichment_v21.py`)
     proves one spent call per attempt and the ceiling checks of 300 and 450.
  6. Fail-before/pass-after for any behavior fix; ruff, full suite, CI.
- **Stop conditions:** any change to the scorer or the gold; any new dependency or
  service; a needed change to the frozen contract (that means a new freeze, in its own PR).

### C. Paid, dev only
- **Run:** the 100 dev remarks, one `paid` token bound to the exact command, call ceiling
  300, standard Messages API (not batches), the frozen request settings
  (`claude-sonnet-5-5`).
- **Prerequisites:** Phase B merged; the freeze verified at run time; the owner's token.
- **Report** (aggregate only, `docs/ENRICHMENT_V3_DEV_RESULTS.md`): 20-facet micro F1
  against Sonnet v2's **94.69%** dev (the figure the brief calls v2.1's dev), per-facet
  deltas against the v2 Sonnet column of `docs/ENRICHMENT_V21_DEV_RESULTS.md`,
  span-quality rate (all decisions, matched decisions, by facet), tokens per remark
  (uncached, cache write, cache read, output), requests, retries, missing tool calls and
  remarks with validation misses. Cost comes from the provider console only.
- **After the run:** prompt edits are allowed on dev evidence only, each with its reason.
  Any edit needs a new freeze (version 2 of the freeze file, recorded hashes, test
  updated) in its own PR before D. A rerun on dev after an edit needs a new token.
- **Stop conditions:** dev F1 below 94.69% (report and stop before D); a provider or auth
  failure, or private results that cannot be persisted; any new dependency or service.

### D. Paid, held-out
- **Run:** the 150 held-out remarks, one `paid` token, call ceiling 450, standard API, the
  contract as frozen after C.
- **Prerequisites:** C's dev F1 at or above 94.69%; the post-C freeze merged and
  verified; the owner's token.
- **Report** (`docs/ENRICHMENT_V3_HELDOUT_RESULTS.md`): micro F1 against the 88.2%
  held-out gate the brief sets (v1's held-out result; the original integration gate in
  `ENRICHMENT_SCORING_V1` is 85%), each facet against the owner's rule (F1 at least 80%
  and at least 10 gold examples), span quality and tokens per remark. As a diagnostic,
  report the 92.4% that v1 reached on the same 20 facets, pooled from its published
  per-facet counts.
- **Second use of the held-out set.** This is the second time the 150 held-out remarks
  are scored; v1 was the first, on 2026-10-28. The report must say so, and so must a
  WO-018 Status entry written in WO-018's own file. Any further iteration after D needs
  a fresh held-out sample.
- **Stop conditions:** any wish to edit the prompt, rules or scoring from held-out
  results; incomplete or invalid predictions (the run cannot pass); any new dependency or
  service.

### E. Diff-driven audit design, docs only
- **In scope:** a design for a diff-driven audit, docs only. The brief's detailed text for
  E was abbreviated in the instructions this PR was written from, so its scope is to be
  confirmed with the owner before E starts. Nothing in E runs a model or changes a store.
- **Prerequisites:** D reported; the owner's confirmation of E's scope.
- **Stop conditions:** anything that would need a paid call, an extraction or a store
  change.

## Out of scope (all phases)
- A full or bulk run. None is authorized. The bulk estimate, about $105 via Message
  Batches at $1.91 per 1,000 remarks (owner-supplied; no tracked file records that
  rate), is a planning input only.
- Any serving-store build or replacement, the v5 store migration (WO-035), installation,
  activation, live messages and live database writes.
- Changing the gold labels, the splits, the scorer, the v4 policy file or any earlier
  contract, freeze or result.
- Adding a facet. Proposals go to the owner.

## Safety requirements
Remarks are untrusted data: the prompt says so, and the parser treats them only as text.
No remark text, quote, prediction or listing key leaves `data/enrichment/`. Every paid
call needs a command-bound `paid` token and stays under its ceiling. Costs come from the
provider console, never from an estimate.

## Verification commands (Phase A)
```
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
MYSQL_HOST= IDX_ANALYSIS_IMAGE=sha256:<64 hex> .venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONPATH=src:. .venv/bin/python tests/test_enrichment_v3_freeze.py
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## Waiting on the owner
1. **Baseline wording.** Confirm that C compares with 94.69%, Sonnet's v2 dev score,
   which the brief calls v2.1's. The v2.1 prompt's only measured run was Haiku's 89.66%.
2. **Model.** The freeze fixes `claude-sonnet-5-5` with the v2 Sonnet settings (adaptive
   thinking, medium effort), so the comparison is like for like. Another model needs a
   new freeze.
3. **Gold predates v5.** v3 follows v5; the gold was reviewed before it. Where they differ
   (likeliest: ruling 8's unsupported uncertain labels, ruling 4's comparison-worded
   condominium labels), v3 can lose points. Whether to accept that as a known limitation
   or relabel is the owner's call; relabeling is not in this work order.
4. **Span quality.** Reported, not gated. Whether it becomes a gate, and at what rate.
5. **Proposed facets and condominium.** See "Proposed new facets (owner decision)" in
   `docs/ENRICHMENT_EXTRACTION_V3.md`.
6. **Phase E scope**, and a paid token for each of C and D.

## Status
- **2026-11-03 — Phase A done in this PR** (branch `wo-034-extraction-v3`, from `main` at
  `32cd727`). Contract, freeze file and freeze test written. Frozen SHA-256:
  - prompt `2e5ad2d199ea563377f821d5b0564a43996d63d99d02613e35fae5d714b14ad7`
  - canonical schema `91bbeb567206700222ff2d5d88e1fd3fc719b6728e800b3598f293b6f01bcb67`
  - request settings `c8e5ef0c0759c9b606e795a99e99dfb3d5508dc2159596fca8a751f2b92dfb11`

  No v3 request has been sent, and no driver or provider code exists. No paid call,
  extraction, store build, install or activation. Phases B to E are planned, not started.
