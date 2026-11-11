# WO-034 — Extraction v3 research candidate (policy v5 in the prompt, evidence spans)

**Driver:** agent; the owner grants each paid token and reviews each phase's PR
**Depends on:** WO-018 (v2 and v2.1 contracts, scorer, dev and held-out splits);
`docs/ENRICHMENT_REVIEW_POLICY_V5.md` (PR #151, merged at `32cd727`; rulings 9 to 15
added by #158, merged at `9cff4bf`)
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
- **Also in scope (owner decisions 2, 3 and 5, 2026-11-04):**
  - **The subtype mapper** (decision 5): one pure function applied identically to v1, v2
    and v3 predictions before `score_v2`, which preserves raw claims and conflict flags
    and never gives a subtype-derived condominium label a quote or offset. Requirements,
    design options, synthetic acceptance tests and the `score_v2` input contract are in
    `docs/ENRICHMENT_EXTRACTION_V3.md`, "Phase B requirement: the subtype
    representation". Phase B resolves the representation **before the freeze**.
  - **The Phase D command** (decisions 2 and 3): one command that runs frozen production
    v2 and frozen v3 on the 150 held-out remarks under one shared budget of 600 paid
    calls (150 initial requests per configuration, retries from the same 600, initial
    requests reserved), stops and marks the run incomplete on exhaustion, verifies every
    sealed hash first, shows no intermediate prediction or score, and scores and releases
    only after both configurations are complete (contract doc, "The Phase D command
    contract").
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
     proves one spent call per attempt, the Phase C ceiling of 300 and the Phase D
     shared budget: 150 initial requests per configuration always sent; retries only
     from the calls left beyond the unsent initial requests; at 600 the run stops,
     records `exhausted` (an incomplete run, final), computes no score and prints no
     prediction, and the exhausted ledger refuses every further call; a resume after a
     provider or auth failure (owner decision, 2026-11-04, final; see "Decided"), after
     an interrupted invocation whose run state validates (owner decision 2, 2026-11-04;
     corrupt or unverifiable state stops the run, final), or after a `token_cap` or
     `token_refused` stop (owner decisions, 2026-11-05, open question 1) needs a new
     command-bound token per invocation capped at the remaining allowance, draws on the
     same ledger with no reset of budget or attempt counts, reuses completed
     checkpoints without resending, keeps interrupted or ambiguous requests counted,
     and can never exceed 600; an exhausted or failed run refuses a resume. A remark
     that fails all three attempts (owner decisions, 2026-11-05, item 2) is a failed
     request: the run goes on, the remark is scored as an empty prediction for that
     configuration and the count is reported; a third failed request in either
     configuration stops the run `failed`, final, with nothing released.
  6. The Phase D command prints, before release, only calls used, calls left and cases
     complete per configuration; scoring runs only when both configurations are
     complete; a mutation of any sealed input (either configuration, the revised gold,
     the mapper, the scorer, the command) stops it before a token is used.
  7. The subtype mapper's acceptance tests in the contract doc pass, including the
     proof that `score_v2` rejects a spanless condominium annotation.
  8. Fail-before/pass-after for any behavior fix; ruff, full suite, CI.
- **Stop conditions:** any change to the scorer or the gold; any new dependency or
  service; a needed change to the frozen contract (that means a new freeze, in its own PR).

### C. Paid, dev only
- **Run:** the 100 dev remarks, one `paid` token bound to the exact command, call ceiling
  300, standard Messages API (not batches), the frozen request settings
  (`claude-sonnet-5-5`).
- **Prerequisites** (owner decision, 2026-11-03; detail in
  `docs/ENRICHMENT_EXTRACTION_V3.md`, "Phase C prerequisites"):
  1. The list of dev items where a v5 ruling changes the gold answer. **Done
     2026-11-03** (model review, private file, SHA-256 `984aa72e…ddf7dd4`): 6 proposed
     changes in 6 items (ruling 3: 1, ruling 6: 1, ruling 7: 4; all additions), 6
     borderline rows with no change proposed, and none for rulings 1, 2, 5 and 8.
     **Round three:** a new versioned private list, `…-v2.jsonl` (SHA-256
     `0ae62271…de7ac507`), adds `conflict_flag`; 1 row carries
     `ruling4_subtype_conflict` (see "Ruling 4 conflicts" below).
     **Rulings 9 to 15 (2026-11-04):** the same screen, policy only (no predictions of
     any contract opened), into a new cumulative list `…-v3.jsonl` (SHA-256
     `ac586374…fbf10de3`, manifest `a9ce10d3…2c8200c3b`): 1 proposed change (ruling
     9, a removal), 1 borderline row (ruling 12), none for rulings 10, 11, 13, 14 and 15.
     **Cumulative: 7 proposed changes in 7 items (6 additions, 1 removal), 7 borderline
     rows.** Version 3 is the current list.
  2. The owner applies the 7 proposed changes and decides the 7 borderline rows by
     ruling number, by hand, into a new versioned gold file, following "Dev gold relabel
     procedure" below. `labels.json` is not modified.
  3. The saved v2 Sonnet dev predictions (saved: one private file, 100 of 100 dev rows)
     are rescored against the revised gold with the existing scorer and no provider
     call, using the exact command in the contract doc. That command is **unmapped**:
     its F1 is recorded as a **reference figure only**, not the comparator. Against the
     current gold it reproduces 94.69%; that was a reproducibility check, not a result.
     - **3a, the Phase C comparator** (one definition, the contract doc's "Scoring
       plan"): the same saved v2 Sonnet dev predictions, passed through the identical
       Phase B subtype mapping that is applied to v3, scored with `score_v2` over the 20
       facets, `["overall"].f1`, unrounded, against the same revised dev gold (by
       SHA-256), no provider call (owner decisions: "rescore the saved v2 predictions
       against the revised gold with no provider call, so v3 and v2 are compared against
       the same gold"; "`score_v2` over the 20 facets, unrounded, applied identically to
       v1, v2 and v3"; "apply the identical mapping to v1, v2 and v3"). It is computed
       once the Phase B mapper is merged and recorded, aggregates only, before the Phase
       C paid call.
  4. Steps 2 and 3 (excluding 3a, which follows Phase B) are **on `main`** (recorded in a
     merged PR) before the Phase C token is granted (owner decision, 2026-11-03, round
     three).
  5. Phase B merged; the comparator (3a) recorded; the freeze verified at run time (the
     ruling 9 "Market" question is decided: version 4, recorded 2026-11-04 before any
     paid call, see "Decided"); the owner's token.
- **Report** (aggregate only, `docs/ENRICHMENT_V3_DEV_RESULTS.md`): v3's 20-facet micro
  F1 (the metric defined for Phase D) against the revised gold, after the Phase B
  subtype mapping, compared with **the Phase C comparator** (prerequisite 3a);
  per-facet deltas against the comparator's per-facet entries; beside them, labelled as
  references and not comparators, the unmapped rescore of the saved v2 predictions
  (prerequisite 3) and **94.69%, the historical v2 Sonnet dev score** (October gold);
  the number of claims the mapper removed per contract, by polarity. v2.1 Sonnet has no dev score; the only v2.1 run was Haiku
  at 89.66%. Also span-quality rate (all decisions, matched decisions, by facet), tokens
  per remark (uncached, cache write, cache read, output), requests, retries, missing tool
  calls and remarks with validation misses, and the revised gold's SHA-256. Cost comes
  from the provider console only.
- **After the run:** prompt edits are allowed on dev evidence only, each with its reason.
  Any edit needs a new freeze (version 5 of the freeze file, since version 4 records
  the ruling 9 named-chain clarification; recorded hashes, test updated) in its own PR
  before the Phase D lock.
  A rerun on dev after an edit needs a new token. After C clears, the lock fixes the
  prompt, parser and mapping before the held-out gold is screened.
- **Stop conditions:** v3 dev F1 (mapped, unrounded) below the Phase C comparator
  (prerequisite 3a; report and stop before D); a provider or auth failure, or private results that
  cannot be persisted; any new dependency or service.

### D. Paid, held-out
- **Owner decisions (WO-034 final, 2026-11-04), recorded verbatim in substance:**
  1. Production v2 has no held-out score. Facet eligibility comes from v1's held-out
     results; v2 was evaluated on dev only. 88.2% is v1's historical all-field result
     against the original frozen gold, `labels.json`, SHA-256
     `6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7`.
  2. Phase D is **one command with one shared budget of 600 calls**: 300 initial
     requests, 150 per configuration (frozen production v2, frozen v3). Retries draw on
     the same 600. Exhausting the budget stops the run and marks it incomplete; the
     ceiling is never expanded, silently or otherwise.
  3. Both configurations, the revised held-out gold, the mapper and the scorer are
     **sealed before execution**. No agent or human inspects intermediate predictions or
     scores. Machine parsing, checkpointing and scoring are permitted. Results are
     released only after both configurations are complete and scored.
  4. `score_v2` over the 20 facets, unrounded, applied identically to v1, v2 and v3.
     **v3 passes only if it meets or exceeds v2** and every eligible facet keeps the
     stated support (at least 10) and F1 (at least 0.80) requirements. Rescored v1 is
     historical reference only.
  5. Phase B resolves the subtype representation before the freeze (see Phase B and the
     contract doc).
- **What this supersedes.** The round-three plan rescored "the saved v2.1 held-out
  predictions" to set a gate; the check of 2026-11-03 found none were saved (the only
  saved held-out predictions are v1's 150 records). **Under decisions 2 and 4 the v2
  baseline is produced by frozen production v2 inside the same sealed Phase D run**, so
  no saved v2 or v2.1 predictions are needed; **this resolves the "no saved v2.1
  predictions" blocker**, and decision 4 settles which scorer applies. The earlier call
  ceiling of 450 is replaced by the shared 600.
- **Order** (Phase D acceptance, owner): after C clears, **lock** the candidate prompt,
  parser and mapping (`docs/ENRICHMENT_V3_D_LOCK.json`, its own PR) **before** screening
  held-out gold; then identify held-out gold changes **from approved policy rulings
  only**, without consulting candidate predictions (no v3, v2 or saved v1 output, no
  score); the owner relabels ("Held-out gold relabel procedure" below); then the **final
  freeze** (`docs/ENRICHMENT_V3_D_FREEZE.json`, contract doc "What the final freeze
  seals") is recorded before the separately authorized, **single Phase D attempt**.
  Held-out observations must not drive candidate changes.
- **Run:** the one Phase D command, one `paid` token bound to it, standard Messages API
  for both configurations (owner decision, 2026-11-04, final), shared budget 600
  (contract doc, "The Phase D command contract").
- **Prerequisites:** C's dev F1 at or above the Phase C comparator (Phase C,
  prerequisite 3a); the lock merged; the held-out screen and the owner's
  relabel done; the final freeze merged and verified by the command before any token is
  spent; the owner's scoring-contract decisions (a) to (d), given on 2026-11-04 (contract
  doc, "Owner decisions, 2026-11-04 (final)"); then the owner's token.
- **Metric and pass rule:** decision 4, defined exactly in the contract doc ("The metric
  and the pass rule"): micro F1 over the 20 facets, (case, facet, polarity) groups with
  polarity-aware overlap, temporality ignored, no numeric fields,
  `score_v2(...)["overall"].f1`, after the subtype mapping, unrounded; v3 against v2 from
  the same run; per facet, v3's gold support at least 10 and F1 at least 0.80. **The
  primary score (the gate comparison and the per-facet checks) is computed on the 149
  non-excluded held-out cases; the full-150 score is a diagnostic** from the same
  outputs (owner decision 1 of 2026-11-04, exposure; "Held-out exposure and scoring
  procedure" below).
- **Held-out exposure and scoring procedure (owner decision 1, 2026-11-04).** The first
  400 characters of one held-out remark entered the tool/conversation record on
  2026-11-04 (Status, 2026-11-04, owner acceptance check 1, and the incident correction).
  No evaluation ran, so **it consumes no Phase D attempt**. The exposed case was
  identified privately (by its id only) and is excluded from the primary score:
  - **Exclusion file** (private, owner-only, mode 600):
    `data/enrichment/v3-heldout-exclusions-v1.json`, SHA-256
    `2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0`; 1 excluded case,
    split `test`, `primary_n` 149, `diagnostic_n` 150. The tracked files record only its
    hash and counts, never the case id.
  - **Requests unchanged:** 150 per configuration, 300 initial requests, the shared 600.
    The excluded case is still sent to both configurations.
  - **Primary score:** the gate comparison (v3 against production v2) and the per-facet
    support and F1 checks use the **149** non-excluded cases.
  - **Diagnostic:** the full-150 score from the same outputs, reported beside the
    primary score, never used for the pass rule.
  - **Sealed:** the exclusion file and this procedure are sealed in the Phase D freeze
    (contract doc, "What the final freeze seals"), before the run.
  - **Preserved:** `splits.json`, `sample.jsonl`, `labels.json` and the revised held-out
    gold keep all 150 cases; the exclusion is applied only at scoring.
  - **No candidate change may be informed by the exposure.**
- **Report** (`docs/ENRICHMENT_V3_HELDOUT_RESULTS.md`, after release only): v3 and
  production v2 primary F1 (149 cases) from the run, pass or fail, each facet against
  the per-facet rule; the full-150 diagnostic for both from the same outputs, and the
  exclusion of one exposed case (owner decision 1, 2026-11-04);
  beside them, as references only, rescored v1, 88.2% (v1's historical all-field result,
  original frozen gold `6aab5483…f250ebde7`; the original integration gate in
  `ENRICHMENT_SCORING_V1` is 85%) and 92.4% (v1 pooled over the 20 facets); span quality,
  calls used of 600, retries, tokens per remark, and the number of failed requests
  (remarks that failed all three attempts, scored as empty predictions) per
  configuration (owner decision, 2026-11-05).
- **No tuning, one attempt.** Nothing is tuned against Phase D results. Once any Phase D
  score is released, no further run on these 150 remarks. An incomplete run releases
  nothing. **An exhausted budget ends the run** (decision 2): it is marked incomplete
  (the ledger is written `exhausted`), nothing is completed under the same token, freeze
  or budget, and the ceiling is never expanded; any completion would be a **new run,
  separately authorized by the owner, on a new held-out set**, under the one-attempt
  rule. A run stopped before the budget is spent may be resumed only under the owner's
  resume rules ("Decided" below; contract doc, "The Phase D command contract"). The rule
  of 2026-11-04 covered a provider or auth failure; decision 2 of the 2026-11-04
  decisions on interrupted runs widens it to any interrupted run whose sealed inputs,
  ledger and checkpoints validate (next paragraph), and the owner decisions of
  2026-11-05 add `token_cap` and `token_refused` stops (the paragraph after). Every
  resume needs a new human-issued, command-bound `paid` token per resumed invocation,
  capped at the remaining allowance; the same sealed run and cumulative 600-call
  ledger, with no reset of budget or attempt counts; completed checkpoints reused
  without resending; interrupted or ambiguous requests counted; retries under the
  frozen limits; nothing released before both configurations complete; the failure and
  the resume logged in `docs/EVIDENCE_LOG.md`. An exhausted run stays final, and so
  does a run written `failed` (more than two failed requests in either configuration,
  2026-11-05).
- **Interrupted runs, the 600th attempt and the early token check (owner decisions 2
  to 4, 2026-11-04; recorded verbatim under "Decided" below).** An interrupted run
  (not only one stopped by a provider or auth failure) may resume only if the sealed
  inputs, the durable ledger and the checkpoints validate, calls remain, and no results
  have been released. Each invocation needs a fresh token capped at the remaining
  allowance. Completed requests are not resent; ambiguous attempts stay counted.
  **Corrupt or unverifiable state stops the run.** A failed or interrupted **600th
  attempt counts as exhausted**: the incomplete run is final, and failed requests do not
  refund allowance. The read-only early token check goes through the existing consent
  reader; the authoritative validation and spend stay before any provider access; the
  consent mechanism is not modified and no token contents are logged.
- **Token stops, settled runs and failed requests (owner decisions, 2026-11-05;
  recorded verbatim under "Decided" below).** A stop because the token's ceiling ran out
  (`token_cap`) or because the token was refused mid-run (`token_refused`) may resume
  under decision 2's conditions, with a fresh token capped at the calls left; the
  600-call ledger bounds spend, not the token. A run found complete after settling is
  scored and released with no new token; a run written `exhausted` or `failed` stays
  final. **A remark that fails all three attempts does not end the run:** it is recorded
  as a failed request, scored as an empty prediction for that configuration, and the
  count is reported. **More than two such cases in either configuration make the run
  final and failed.** This replaces the earlier handling, under which one remark failing
  all three attempts ended the run as `failed`.
- **Second use of the held-out set.** This is the second time the 150 held-out remarks
  are scored; v1 was the first, on 2026-10-28. The report must say so, and so must a
  WO-018 Status entry written in WO-018's own file. Any further iteration after D needs
  a fresh held-out sample.
- **Stop conditions:** any wish to edit the prompt, rules, parser, mapping or scoring
  from held-out results; an incomplete run or invalid predictions (no pass); any
  inspection of intermediate predictions or scores; any new dependency or service.

### E. The full-run decision (owner decision, 2026-11-03)
- **In scope:** first, a store-level comparison on the scored samples (100 dev, 150
  held-out): v3's frozen decisions against what the store holds for the same listings
  (the v2 extraction as corrected under v4, and the v5 overlay), aggregate counts per
  facet and polarity, no model call. Then the owner's full-run decision. E may compare
  frozen evaluation outputs; it must not reopen the held-out set for tuning.
- **The batch:** a full run needs its own separate `paid` token, bound to the batch
  command, with its own ceiling, granted after Phase E and separately from the C and D
  tokens. Cost comes from the provider console.
- **Prerequisites:** D reported.
- **Stop conditions:** any prompt, rule, parser or scoring change prompted by held-out
  results; any paid call without its own token; any store build or replacement.

## Ruling 4 conflicts (owner decision, 2026-11-03, round three)
When a remark makes a direct "condo" claim about the home but the subtype column
disagrees, **the subtype column decides**: the gold carries no `condominium` label for
that case, and the case gets the conflict flag `ruling4_subtype_conflict`. The flag is
recorded in a new versioned private list beside the first, which is unchanged:
`v3-dev-v5-relabel-candidates-v2.jsonl` (SHA-256
`0ae62271b10c7071800db98090cdc49314b1b0d64ba7d024972d0c54de7ac507`) and its manifest
`v3-dev-v5-relabel-candidates-v2-manifest.json` (SHA-256
`db3c85289586119070f8837dda8c7e2b0feb6ffde52855ed53e8b7c642bd0edb`). **Count on dev: 1**
(the borderline ruling 4 row; every dev gold `condominium` label and every unlabeled
non-condominium dev remark with condo wording was checked against the subtype). The v3
request carries no subtype, so on such a case v3 will still record the direct claim and
score a false positive against the revised gold; changing that would be a Phase B
mapping design or a new request freeze, and neither is proposed. The held-out screen
applies the same rule and flag. **Owner decision 5 (2026-11-04)** replaces "neither is
proposed": Phase B resolves the representation before the freeze, preserving raw claims
and flags and applying one mapping identically to v1, v2 and v3; the proposed option and
the points that need a scoring-contract decision are in the contract doc ("Phase B
requirement: the subtype representation").

## Dev gold relabel procedure (owner step, before Phase C)
All private files are in the main checkout's `data/enrichment/`, owner-only (mode 600).
Nothing below is run by the agent except where it says so; no file below is edited in
place.

1. **Files.**
   - **Existing gold, unchanged:** `data/enrichment/labels.json`, SHA-256
     `6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7` (both splits; it
     stays the original frozen gold and is never edited).
   - **Relabel lists, all versions** (each with its manifest; none is modified):
     | Version | List, SHA-256 | Manifest, SHA-256 | Covers |
     |---|---|---|---|
     | 1 | `v3-dev-v5-relabel-candidates.jsonl`, `984aa72e0e702861858928a6d3858bb22fd5a2a63d8d465da7a10a1e2ddf7dd4` | `v3-dev-v5-relabel-candidates-manifest.json`, `9cf864ef9906dd85516c881a4c0bf2a04f017d0e81e609a752ab7f3174cb0a3d` | rulings 1 to 8 |
     | 2 | `v3-dev-v5-relabel-candidates-v2.jsonl`, `0ae62271b10c7071800db98090cdc49314b1b0d64ba7d024972d0c54de7ac507` | `v3-dev-v5-relabel-candidates-v2-manifest.json`, `db3c85289586119070f8837dda8c7e2b0feb6ffde52855ed53e8b7c642bd0edb` | rulings 1 to 8, plus `conflict_flag` |
     | **3 (current)** | `v3-dev-v5-relabel-candidates-v3.jsonl`, `ac586374005f57b53e758db08ed61ee34ccc3d1f0db36b1a833086fabbf10de3` | `v3-dev-v5-relabel-candidates-v3-manifest.json`, `a9ce10d3e3f7f8ce12e2a5b2d8dfb7aeef9505cf2523906e157428a2c8200c3b` | rulings 1 to 15 (the 12 rows of version 2 byte for byte, plus 2) |
     **Use version 3 only.** It is cumulative, so versions 1 and 2 are not applied again.
   - **Version 3 is current, not stale (re-checked 2026-11-04 against the version 4
     ruling 9 clarification).** The clarification (a named grocery chain counts whatever
     words its name contains, "Market" included; the market rules apply only to an
     unnamed or unknown place) was issued after the version 3 list was written, so its one
     ruling 9 row was re-checked on 2026-11-04, policy only: that row and that one dev
     item's remark were the inputs (no prediction of any contract, no score, no held-out
     gold; one incidental held-out exposure is disclosed in Status, 2026-11-04, owner
     acceptance check 1, and played no part in the check), and the list's SHA-256 was
     confirmed as
     `ac586374005f57b53e758db08ed61ee34ccc3d1f0db36b1a833086fabbf10de3`. The place the
     remark names is not a recognisable grocery chain and the remark does not say it sells
     food or groceries, so it remains an unknown place, the market rule applies, and the
     row's recommendation (**remove** the affirmed `near_grocery_mentioned` label, medium
     confidence) **still holds**. Therefore: the version 3 list (`ac586374…fbf10de3`) is
     applied as it is; no version 4 list exists or is needed; the editing instructions in
     step 3 are unchanged; and the expected validation counts in step 4 are unchanged,
     for both owner choices on the ruling 9 row:
     - **Ruling 9 removal accepted:** `rows_changed` at least 8;
       `-location_views.near_grocery_mentioned.affirmed` 1; outcome `9.change.removed` 1.
     - **Ruling 9 removal rejected** (the label stays): `rows_changed` at least 7; no
       `-location_views.near_grocery_mentioned.affirmed` key in `annotation_delta`;
       outcome `9.change.unchanged` 1.
     - **In both:** the six other proposed changes and the ruling 4 removal as listed in
       step 4 (`3.change.added` 1, `6.change.added` 1, `7.change.added` 4,
       `4.borderline_no_change.removed` 1).
     The recommendation is the agent's policy reading, not an owner review; the owner may
     still reject it (if the owner knows the place to be a grocer or grocery chain).
   - **Full dev re-screen for the clarification (owner decision 5, 2026-11-04): no
     change.** One policy-only screen of all 100 dev remarks for the ruling 9
     named-chain clarification, before the owner's relabel (model review; inputs: the
     dev remarks, the dev rows of `labels.json`, the version 3 list's grocery rows and
     `docs/ENRICHMENT_REVIEW_POLICY_V5.md` at `229fdd74…dbf0e7f8`; no prediction of any
     contract, no score, no held-out remark or gold). It found **no dev remark naming a
     grocery chain with "Market" in its name that lacks a gold label**; the one ruling 9
     row still holds; every gold `near_grocery_mentioned` label on dev is supported as
     it stands. **No recommendation changed, so no addendum was written** and the
     version 3 list (`ac586374…fbf10de3`) stays current. The editing instructions in
     step 3 and the expected validation counts in step 4 (both sets above) are
     **unchanged**; there is no addendum whose recommendations the owner would need to
     apply instead. These are model judgments, `human_review: pending`; the relabel and
     every human-pass judgment stay the owner's (decision 6).
   - **New gold, created by the owner:** `data/enrichment/labels-v5-dev.json`, mode 600.
     Never overwrite an existing file of that name; a second attempt gets a new name
     (`labels-v5-dev-2.json`) and the check is run on it.
   - **Changelog manifest, written by the check in step 4:**
     `data/enrichment/labels-v5-dev-manifest.json`, mode 600, created once (the command
     refuses to overwrite).
2. **Full copy, not a delta.** Start from a byte copy of `labels.json` (`cp -p` then
   `chmod 600`) and edit only dev rows. Why: `score_v2` and `_read_private` take one
   complete label file (`version`, `dataset_id`, a row for every case of the split), so
   a full copy is scored by the existing, unchanged commands and is pinned by one
   SHA-256; a delta file would need new merge code in the scoring path before anything
   could be scored. The delta is still recorded: the check derives it mechanically and
   writes it into the changelog manifest. Same shape as `labels.json`: `{"version": 1,
   "dataset_id": "remarks-20261027-v1", "labels": [...]}`, all 250 rows in the same order,
   each `{"id", "annotations"}`. Held-out (test) rows stay byte-identical in content.
3. **Edits, by ruling number, from the version 3 list** (14 rows; nothing else changes):
   - **Proposed changes (`disposition: "change"`, 7 rows):**
     - ruling 3 (1 row, `stainless_appliances`), ruling 6 (1 row, `clubhouse`), ruling 7
       (4 rows, `bonus_room`): **add** one annotation to that item with the row's
       `proposed_gold` fields (`kind`, `group`, `value`, `polarity`, `temporality`,
       `start`, `end`) plus `quote`, which is the remark's characters from `start` to
       `end` exactly;
     - ruling 9 (1 row, `near_grocery_mentioned`): **remove** the annotation listed under
       `current_gold` (same item, facet, `start`, `end`, `polarity`, `temporality`).
       Checked on 2026-11-04 against the version 4 clarification (a named grocery chain
       counts whatever its name contains; the market rules apply only to unnamed or
       unknown places): the proposal still holds, because the place is named but not a
       recognisable grocery chain, and the remark does not say it sells food. The owner
       may reject it (if the owner knows the place to be a grocer or grocery chain); the
       check then reports it `unchanged`.
   - **Borderline rows (`disposition: "borderline_no_change"`, 7 rows):**
     - ruling 4 (1 row, `conflict_flag: "ruling4_subtype_conflict"`): decided by the
       round-three ruling 4 decision: **remove** the `condominium` annotation under
       `current_gold`;
     - ruling 6 (3 rows, `clubhouse`) and ruling 7 (2 rows, `bonus_room`): the owner
       **adds** a label (a span of the owner's choosing, with its exact quote) or leaves
       the row as it is;
     - ruling 12 (1 row, `single_level`): the owner **removes both** annotations listed
       under `current_gold` (removing one would leave the group in place) or leaves both.
4. **Validate and write the changelog.** From the main checkout root (a checkout of
   `main`, so `src/` is the unchanged scorer), run once with `MANIFEST=` empty to check,
   then once with `MANIFEST=labels-v5-dev-manifest.json` to write the changelog. It
   prints only counts, facet names, outcome tallies by ruling and hashes. It checks the
   base gold and list hashes, the header and row order, that no row of the other split
   changed, that every changed (item, facet) pair is in the list, that every added quote
   equals the remark at its offsets, and that `score_v2` accepts the file (no invalid
   span, no duplicate annotation). The manifest records the base gold, list and new
   gold hashes, the counts, and one outcome per list row (`added`, `removed`,
   `replaced` or `unchanged`), which is the record of the owner's decision on each row.
```
PRIVATE=<main checkout>/data/enrichment SPLIT=dev GOLD=labels-v5-dev.json \
LIST=v3-dev-v5-relabel-candidates-v3.jsonl \
LIST_SHA256=ac586374005f57b53e758db08ed61ee34ccc3d1f0db36b1a833086fabbf10de3 \
MANIFEST= PYTHONPATH=src:. .venv/bin/python - <<'EOF'
import datetime, hashlib, json, os
from collections import Counter
from pathlib import Path
from scripts.score_enrichment_private import _read_private, _sample_jsonl
from idx_agent.enrichment.v2 import score_v2
E = os.environ
P, SPLIT, NEW, LIST, OUT = Path(E["PRIVATE"]), E["SPLIT"], E["GOLD"], E["LIST"], E.get("MANIFEST")
sha = lambda name: hashlib.sha256((P / name).read_bytes()).hexdigest()
assert SPLIT in {"dev", "test"} and NEW != "labels.json"
assert sha("labels.json") == (
    "6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7")
assert sha(LIST) == E["LIST_SHA256"], "not the recorded relabel list"
old, new = _read_private(P, "labels.json"), _read_private(P, NEW)
assert {k: new[k] for k in ("version", "dataset_id")} == {
    k: old[k] for k in ("version", "dataset_id")}
assert [r["id"] for r in new["labels"]] == [r["id"] for r in old["labels"]]
sample = _sample_jsonl(P, SPLIT)
text = {c["id"]: c["text"] for c in sample["cases"] if c["split"] == SPLIT}
rows = [json.loads(x) for x in (P / LIST).read_text(encoding="utf-8").splitlines()]
listed = {(r["item_id"], r["facet"]) for r in rows}
dump = lambda x: json.dumps(x, sort_keys=True)
name = lambda x: f'{x.get("group")}.{x.get("value")}'
seen, delta, changed = set(), Counter(), 0
for a, b in zip(old["labels"], new["labels"]):
    if a["id"] not in text:
        assert a == b, "a row of the other split changed"
        continue
    before, after = Counter(map(dump, a["annotations"])), Counter(map(dump, b["annotations"]))
    changed += before != after
    for diff, sign in ((after - before, "+"), (before - after, "-")):
        for k, n in diff.items():
            x = json.loads(k)
            assert (a["id"], name(x)) in listed, "a change outside the relabel list"
            if sign == "+":
                assert text[a["id"]][x["start"]:x["end"]] == x["quote"], "quote mismatch"
            seen.add((a["id"], name(x), sign))
            delta[f"{sign}{name(x)}.{x.get('polarity')}"] += n
check = score_v2(sample, new, new, SPLIT)["overall"]
assert check.expected == check.predicted == check.correct, "scorer rejects the file"
def outcome(r):
    signs = frozenset(s for s in "+-" if (r["item_id"], r["facet"], s) in seen)
    return {frozenset(): "unchanged", frozenset("+"): "added",
            frozenset("-"): "removed"}.get(signs, "replaced")
by_ruling = Counter(f'{r["v5_ruling"]}.{r["disposition"]}.{outcome(r)}' for r in rows)
report = {"split": SPLIT, "rows_changed": changed, "annotation_delta": dict(sorted(delta.items())),
          "outcomes": dict(sorted(by_ruling.items())), "gold_groups": check.expected,
          "sha256": sha(NEW)}
if OUT:
    manifest = {"created": datetime.date.today().isoformat(), "work_order": "WO-034",
                "base": {"file": "labels.json", "sha256": sha("labels.json")},
                "list": {"file": LIST, "sha256": sha(LIST)},
                "gold": {"file": NEW, "sha256": sha(NEW)}, **report,
                "rows": [{k: r[k] for k in ("item_id", "v5_ruling", "facet", "disposition",
                          "conflict_flag")} | {"outcome": outcome(r)} for r in rows]}
    fd = os.open(P / OUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    report["manifest_sha256"] = sha(OUT)
print(json.dumps(report, sort_keys=True))
EOF
```
   Expected, for both owner choices on the ruling 9 row (the other six proposed
   changes and the ruling 4 removal applied in both; unchanged by the version 4 ruling 9
   clarification, re-checked 2026-11-04, see step 1):
   - **Ruling 9 removal accepted:** `rows_changed` at least 8;
     `-location_views.near_grocery_mentioned.affirmed` 1; outcome `9.change.removed` 1.
   - **Ruling 9 removal rejected** (the label stays): `rows_changed` at least 7; no
     `-location_views.near_grocery_mentioned.affirmed` key in `annotation_delta`;
     outcome `9.change.unchanged` 1.
   - **In both:** `annotation_delta` with
     `+interior_systems.stainless_appliances.affirmed` 1,
     `+community_amenities.clubhouse.affirmed` at least 1,
     `+rooms_layout.bonus_room.affirmed` at least 4,
     `-property_type.condominium.affirmed` 1, and `-rooms_layout.single_level.affirmed`
     absent or 2; outcomes `3.change.added` 1, `6.change.added` 1, `7.change.added` 4 and
     `4.borderline_no_change.removed` 1.
   "At least" leaves room for the borderline additions the owner chooses (ruling 6 and
   7 rows, and ruling 12, which changes one more row if both labels are removed). The
   counts assume the seven proposed-change items and the ruling 4 item are distinct, as
   the version 3 list records. Checked on 2026-11-04 by the agent: with the
   `labels.json` guard lifted and `GOLD=labels.json` (dev only) it printed 0 rows changed,
   every outcome `unchanged`, 342 gold groups and the old hash; on invented private
   files (250 synthetic cases) it accepted an add and a remove and wrote a mode-600
   manifest, refused to overwrite it, and rejected a change outside the list, a changed
   row of the other split, a quote mismatch and a duplicate annotation.
5. **Rescore** the saved v2 Sonnet dev predictions once with
   `GOLD=labels-v5-dev.json`, using the exact command in
   `docs/ENRICHMENT_EXTRACTION_V3.md` ("Phase C prerequisites", item 2): `score_v2`, no
   provider call, `predictions-dev-v2-sonnet.json` pinned at `53bfae92…bcd31d` and
   `src/idx_agent/enrichment/v2.py` at `5762b2b3…dca58d6d7d`. It prints aggregate counts
   per facet; against the current gold it reproduces 94.69%. This rescore is
   **unmapped** and is recorded as a **reference figure only**; the Phase C comparator
   is the mapped figure defined in Phase C, prerequisite 3a, computed once the Phase B
   mapper exists.
6. **Record.** In one PR to `main`, aggregates only: the revised gold's and the changelog
   manifest's SHA-256, the check's counts and outcome tallies, and the unmapped
   reference rescore of v2 Sonnet (overall expected / predicted / correct and unrounded
   F1 with the per-facet counts, labelled as the reference figure, not the comparator), in
   `docs/ENRICHMENT_EXTRACTION_V3.md` ("Phase C prerequisites"), a WO-034 Status entry
   and a `docs/EVIDENCE_LOG.md` entry. **That PR merged on `main` is the condition for the
   Phase C token.**

## Held-out gold relabel procedure (after Phase C and the lock, before the seal)
The same procedure on the test split, used only after Phase C clears and the lock
(`docs/ENRICHMENT_V3_D_LOCK.json`) is merged.

1. **Screen** (agent, policy only): v5 rulings 1 to 15 (ruling 9 with the owner's
   named-chain clarification of 2026-11-04) with the ruling 4 conflict rule,
   the 150 held-out remarks and the test rows of `labels.json`; no predictions of any
   contract and no score. It writes a new private list
   `data/enrichment/v3-heldout-v5-relabel-candidates.jsonl` and
   `v3-heldout-v5-relabel-candidates-manifest.json` (same fields as the dev list, mode
   600, never overwritten; a correction is a new `-v2` file). Tracked files get the counts
   by ruling only.
2. **New gold** (owner): `data/enrichment/labels-v5-heldout.json`, a full byte copy of
   `labels.json` with only test rows changed, for the same reason as on dev. Dev rows stay
   as in `labels.json`: Phase D scores only the test split.
3. **Edits** (owner): each proposed change and each borderline row by ruling number, as
   in dev step 3; the ruling 4 conflict rule and flag apply, under the polarity scope the
   owner decided on 2026-11-04 (decision (b): every condominium label that contradicts
   the subtype is removed with the flag, affirmed or uncertain when the subtype is not
   exactly `Condominium` and negated when it is; agreeing labels are kept).
4. **Validate and write the changelog:** the step 4 command with `SPLIT=test`,
   `GOLD=labels-v5-heldout.json`, `LIST=v3-heldout-v5-relabel-candidates.jsonl`,
   `LIST_SHA256=` that list's recorded hash, and then
   `MANIFEST=labels-v5-heldout-manifest.json`. It then asserts that no dev row changed.
5. **No rescoring step.** Nobody scores held-out predictions before the sealed run: the
   v2 baseline and the v1 reference are scored inside the Phase D command (decisions 2
   to 4). The revised held-out gold's SHA-256 goes into the final freeze.
6. **Record:** the list, manifest and revised gold hashes and the check's counts in the
   final-freeze PR.
7. **Exclusion (owner decision 1, 2026-11-04).** The screen and the revised gold cover
   all 150 held-out cases, the excluded one included, so the full-150 diagnostic is
   scored against the same revised gold. The exclusion file
   (`v3-heldout-exclusions-v1.json`, `2e60fd85…e8a8a0`) changes no gold, split or sample
   file; it is applied only at scoring and is sealed in the final freeze.

## Order of the paid tokens (owner decision, 2026-11-03, round three)
1. **Phase C:** only after the dev relabel and the dev rescoring are on `main`. The
   mapped Phase C comparator (prerequisite 3a) is also recorded, once Phase B exists,
   before the Phase C paid call.
2. **Phase D:** after Phase C clears and the Phase D freeze is recorded.
3. **Batch:** after Phase E, separately.

## Out of scope (all phases)
- A full or bulk run before Phase E's decision and its separate `paid` token. None is
  authorized now. The bulk estimate, about $105 via Message Batches at $1.91 per 1,000
  remarks (owner-supplied; no tracked file records that rate), is a planning input only;
  cost comes from the console.
- Any serving-store build or replacement, the v5 store migration (WO-035), installation,
  activation, live messages and live database writes.
- Changing the splits, the scorer, the v4 policy file or any earlier contract, freeze or
  result. The gold file `labels.json` is never modified; the owner's hand relabeling goes
  into a new versioned gold file.
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

## Phase B commands (dry runs and the comparator; none run on real files yet)
All from the main checkout root, a checkout of `main` with Phase B merged, so `src/` and
`scripts/` are the pinned files. None of them reads a key, consumes a token, opens the
network or writes a file. Each prints one JSON line of aggregates, or
`{"status": "refused", ...}` with a fixed-text reason.

- **Phase C comparator** (prerequisite 3a; after the owner's dev relabel, before the
  Phase C token; `<sha>` is the revised dev gold's SHA-256 from its changelog manifest):
  ```
  PYTHONPATH=src:. .venv/bin/python scripts/extract_enrichment_v3_dev.py \
    --gold labels-v5-dev.json --gold-sha256 <sha> --comparator
  ```
  It refuses `labels.json` by name and by hash (`6aab5483…f250ebde7`), a missing file,
  a hash other than `<sha>`, saved v2 predictions other than `53bfae92…bcd31d`, and a
  gold that the mapper would change (gold consistency check).
- **Phase C dry run** (same gold arguments; prints the exact command a Phase C token
  must be bound to, with ceiling 300):
  ```
  PYTHONPATH=src:. .venv/bin/python scripts/extract_enrichment_v3_dev.py \
    --gold labels-v5-dev.json --gold-sha256 <sha> --approved-provider-disclosure --dry-run
  ```
  The paid run is the same line without `--dry-run`. Its token must be bound to that
  line with `--max-calls 300` exactly; any other ceiling is refused before a call.
- **Phase D dry run** (after the lock, the held-out relabel and the final freeze;
  `<seal>` is the SHA-256 of `docs/ENRICHMENT_V3_D_FREEZE.json`):
  ```
  PYTHONPATH=src:. .venv/bin/python scripts/extract_enrichment_v3_heldout.py \
    --seal-sha256 <seal> --approved-provider-disclosure --dry-run
  ```
  It verifies every sealed input, the sealed command and the gold consistency check, and
  prints the ledger state: `not_started` with 600 calls left before the run, or after a
  stop the calls used and left, whether a resume is allowed (after an `auth_failure`,
  a `provider_failure`, an `interrupted` invocation, a `token_cap` or a
  `token_refused` stop, with validated run state and calls left), and
  `max_token_calls`, the largest ceiling a resume token may carry (the calls left; 0
  when no resume is allowed). The paid command is the same line without `--dry-run`;
  the first invocation's token must be bound to it with `--max-calls 600` exactly. A
  resume token may carry fewer calls than `max_token_calls`: if it runs out, the run
  stops `token_cap` and may resume again (owner decision, 2026-11-05).
- **Lock and final freeze content** (for their own PRs, later): `build_lock(root)` and
  `build_seal(root, private, gold_name)` in `scripts/extract_enrichment_v3_heldout.py`
  return the exact JSON each file must hold (formats in `docs/CONTRACTS.md`, "WO-034
  v3 private files and Phase D seal").

Today the Phase C commands refuse (the revised dev gold does not exist) and the Phase D
command refuses (`the Phase D final freeze is missing`).

## Waiting on the owner
Decided 2026-11-03: the baseline wording (94.69% is the historical v2 Sonnet dev score),
dev relabeling before C, the D freeze and gate metric, single use of the held-out set,
and Phase E's scope. Decided in round three (2026-11-03): the ruling 4 reading (the
subtype column decides; conflict flag, count 1 on dev), the doubt-wording scope (stays
on the six; "all 20" is a v6 candidate in the contract doc), the stainless reading
(accepted as frozen), the held-out v5 screen and relabel before the D freeze, and the
order of the paid tokens. Decided 2026-11-04: rulings 9 to 15 in the v3 guide with a
policy-only dev re-screen and one recorded re-freeze (done, version 3); the Phase D lock
after C; and the final decisions 1 to 5, which **close the former open items on the
held-out gate's predictions and scorer** (the v2 baseline comes from frozen production
v2 in the sealed run, scored with `score_v2`) and turn the ruling 4 v3-side question
into a Phase B requirement. The owner's final decisions of 2026-11-04 on the scoring
contract, the transport, the Phase D resume and ruling 9 are under "Decided" below.
Decided 2026-11-05 (under "Decided" below): the Phase D open questions 1 and 2 on token
stops and settled runs, and the five Phase B points "for the owner to confirm before the
lock" (items 1, 3, 4 and 5 confirmed as written; item 2 replaced by a new rule). Those
were raised on the Phase B branch (`wo-034-phase-b`, PR #164) and are not in the list
below.
Still open:
1. **Dev relabel** (owner step; the owner will do it from the version 3 candidate list,
   decision of 2026-11-04). Apply the 7 proposed changes and decide the 7 borderline rows
   by ruling number from the version 3 list into `labels-v5-dev.json`, validate and write
   the changelog, then rescore, per "Dev gold relabel procedure". The ruling 9 row was
   re-checked against the version 4 clarification (Status, 2026-11-04): its proposal
   still holds, and the owner decides it when relabelling. The full dev re-screen for
   the clarification (decision 5, 2026-11-04) changed no recommendation; no addendum
   exists, and the version 3 list stays the one to apply.
2. **Model.** The freeze fixes `claude-sonnet-5-5` with the v2 Sonnet settings (adaptive
   thinking, medium effort). Another model needs a new freeze.
3. **Span quality.** Reported, not gated. Whether it becomes a gate, and at what rate.
4. **Proposed facets and condominium.** See "Proposed new facets (owner decision)" in
   `docs/ENRICHMENT_EXTRACTION_V3.md`.
5. A paid token for each of C and D, and later a separate one for any batch. Paid runs
   stay paused.

The former item 6 (token cap and token refusal in Phase D; a run found complete after
settling) is closed by the owner's decisions of 2026-11-05 (open questions 1 and 2,
under "Decided") and built (Status, 2026-11-05).

### Decided
**2026-11-04 (owner decisions, final).** These close former open items 2, 3, 8 and 9;
the contract doc records them under "Owner decisions, 2026-11-04 (final)".
- **Scoring contract (former item 2).**
  - (a) **Option A is confirmed**: the mapper only removes contradicting remark-based
    condominium claims and never adds a subtype-derived label.
  - (b) **Remove with the flag** `ruling4_subtype_conflict` every condominium claim that
    contradicts the subtype: affirmed or uncertain when the subtype is not
    `Condominium`, negated when it is. Agreeing claims are kept. The same rule applies in
    the held-out relabel.
  - (c) **Exactly `Condominium`** is a condominium; every other or unseen value is not.
    The distinct subtype values are reported as counts after Phase D.
  - (d) A facet whose **revised held-out support falls below 10** is reported as **not
    evaluable**, left out of the per-facet check and kept in the micro F1. Its unchanged
    eligibility is historical status, never evidence that v3 validated that facet.
- **Transport (former item 3).** The standard Messages API for both configurations.
- **Phase D after a provider or auth failure with budget left (former item 8).** Every
  resumed invocation needs a new human-issued, command-bound `paid` token, capped at the
  remaining allowance. It reuses the same sealed run and the same cumulative 600-call
  ledger; neither the budget nor the attempt counts reset. Completed checkpoints are
  reused without resending. Interrupted or ambiguous requests stay counted, and retries
  follow the frozen limits. Nothing is released before both configurations complete. The
  failure and the resume go in `docs/EVIDENCE_LOG.md`. An exhausted run stays final.
- **Ruling 9 and grocery chains named "Market" (former item 9).** One expressly
  authorized extraction-contract re-freeze, version 4, limited to the grocery line: a
  named grocery chain counts whatever words its name contains, including "Market" and
  "Farmers Market"; the market rules apply only to unnamed or unknown places. Versions 1
  to 3 stay in the record; schema and request settings unchanged;
  `paid_calls_before_freeze` 0. **Done** (Status, 2026-11-04). The same clarification
  goes into ruling 9 of the v5 policy file through a one-line policy PR on branch
  `chore-policy-v5-ruling-9-named-chains`; this work order's version 4 PR should merge
  together with or after that PR. That PR merged as #162 (`main` `71fb39e`), and the
  version 4 policy pin now names the merged file (Status, 2026-11-04, policy pin
  correction).
- **Dev relabel.** The owner relabels from the version 3 candidate list per this work
  order (open item 1).

**2026-11-04 (owner decisions on the held-out exposure, resume, the 600th attempt, the
early token check, the dev re-screen and review roles).** Verbatim:

> 1. Held-out exposure: it does not consume a Phase D attempt, since no evaluation ran.
> Identify the exposed case privately and exclude it from the primary score, leaving
> 149 cases. Keep the planned 150 requests per configuration; report the full-150 score
> as a diagnostic from those same outputs. Freeze the exclusion and scoring procedure
> before D. Preserve the original split and gold files.
>
> Correct the incident wording: the snippet entered the tool/conversation record. Do
> not repeat its text. No candidate changes may be informed by that exposure.
>
> 2. Interrupted runs may resume if the sealed inputs, durable ledger and checkpoints
> validate, calls remain, and no results have been released. Each invocation requires a
> fresh token capped at the remaining allowance. Completed requests are not resent;
> ambiguous attempts remain counted. Corrupt or unverifiable state stops the run.
>
> 3. A failed or interrupted 600th attempt counts as exhausted. The incomplete run is
> final; failed requests do not refund allowance.
>
> 4. Approve the read-only early check through the existing consent reader. Keep the
> authoritative validation/spend before provider access. Do not modify the consent
> mechanism or log token contents.
>
> 5. Approve one policy-only screen of all 100 dev remarks for the Market-chain
> clarification, before my relabeling. Consult no predictions or held-out data.
> Preserve the v3 list; create a versioned addendum if recommendations change.
>
> 6. Dev gold edits and human-pass judgments remain mine. Keep model judgments marked
> human_review: pending.

How each is applied:
1. **Exposure and scoring procedure:** Phase D, "Held-out exposure and scoring
   procedure" (exclusion file `v3-heldout-exclusions-v1.json`, SHA-256
   `2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0`, primary 149,
   diagnostic 150, sealed in the Phase D freeze); contract doc, "What the final freeze
   seals" and "The metric and the pass rule". The incident wording is corrected by a new
   Status line and a new evidence log entry; earlier entries stay as written.
2. **Resume of an interrupted run:** Phase D above; contract doc, "The Phase D command
   contract". This widens the earlier provider/auth-failure resume rule to any
   interrupted run under the stated validation conditions.
3. **The 600th attempt:** a failed or interrupted 600th attempt exhausts the run; no
   refund for failed requests.
4. **Early token check:** approved as read-only through the existing consent reader;
   the authoritative validation and spend stay before provider access; no change to the
   consent mechanism; no token contents logged.
5. **Dev re-screen:** done once, policy only; no recommendation changed, no addendum,
   version 3 list unchanged ("Dev gold relabel procedure", step 1).
6. **Roles:** dev gold edits and human-pass judgments are the owner's; every model
   judgment stays `human_review: pending`.

**2026-11-05 (owner decisions on the Phase D open questions and the points before the
lock).** The questions were raised on the Phase B branch (`wo-034-phase-b`, PR #164):
open questions 1 and 2 are that branch's "Still open" item 6, and items 1 to 5 are the
PR's list "For the owner to confirm before the lock". Verbatim:

> - Open question 1: token_cap and token_refused stops may resume under decision
>   2's conditions, with a fresh token capped at the calls left. The 600-call
>   ledger bounds spend, not the token.
> - Open question 2: confirmed. A run found complete after settling is scored and
>   released with no new token. Exhausted or failed stays final.
> - Items 1, 3, 4 and 5 before the lock: confirmed as written.
> - Item 2: a remark that fails all three attempts does not end the run. Record
>   it as a failed request, score it as an empty prediction for that
>   configuration, and report the count. More than two such cases in either
>   configuration makes the run final and failed.

How each is applied:
1. **Open question 1, token stops.** A Phase D invocation that stops because its token's
   ceiling ran out (`token_cap`) or because its token was refused mid-run
   (`token_refused`, for example expired) is no longer final: it may resume under
   decision 2's conditions (the sealed inputs, the durable ledger and the checkpoints
   validate, calls remain, nothing has been released; corrupt or unverifiable state
   stops the run), with a fresh token capped at the calls left. The 600-call ledger
   bounds spend, not the token. This replaces the earlier advice that a resume token
   should carry exactly the `max_token_calls` the dry run prints, since a smaller token
   that runs out no longer ends the run. Phase D, "Token stops, settled runs and failed
   requests".
2. **Open question 2, settled runs.** Confirmed: a run found complete after a resumable
   stop, once the request left in flight is settled (its checkpoint verified), is scored
   and released with no new token and no provider call, as a complete ledger already
   was. A run written `exhausted` or `failed` stays final whatever settling finds.
3. **Items 1, 3, 4 and 5 before the lock, confirmed as written:**
   - **Item 1:** the first Phase D token carries exactly 600 calls; a resume is allowed
     after a provider or auth failure or an interrupted invocation, with calls left and
     validated run state. Its last clause (a token cap or a token refused mid-run leaves
     the run final) is superseded by open question 1 above.
   - **Item 3:** the seal hash goes on the command line, so the token binds it; the
     freeze file therefore cannot record the commit of its own PR.
   - **Item 4:** the Phase C token is exactly 300 calls.
   - **Item 5:** the Phase C report also computes the comparator (Phase C,
     prerequisite 3a) in-process.
4. **Item 2, replaced.** The earlier handling (a remark that fails all three attempts
   ends the run as `failed`, final) is replaced: such a remark does not end the run. It
   is recorded as a failed request, scored as an empty prediction for that
   configuration, and the count is reported (Phase D, "Report"). More than two such
   cases in either configuration make the run final and failed.
5. **Where the code lives.** The behaviour belongs to the Phase D command on the Phase B
   branch (PR #164); this entry records the decisions only. No code, freeze file, prompt,
   schema or request block changes here.

## Status
- **2026-11-03 — Phase A done in this PR** (branch `wo-034-extraction-v3`, from `main` at
  `32cd727`). Contract, freeze file and freeze test written. Frozen SHA-256:
  - prompt `2e5ad2d199ea563377f821d5b0564a43996d63d99d02613e35fae5d714b14ad7`
  - canonical schema `91bbeb567206700222ff2d5d88e1fd3fc719b6728e800b3598f293b6f01bcb67`
  - request settings `c8e5ef0c0759c9b606e795a99e99dfb3d5508dc2159596fca8a751f2b92dfb11`

  No v3 request has been sent, and no driver or provider code exists. No paid call,
  extraction, store build, install or activation. Phases B to E are planned, not started.
- **2026-11-03 — owner decisions on C, D and E applied (same PR).**
  - 94.69% is labelled everywhere as the historical v2 Sonnet dev score; v2.1 Sonnet has
    no dev score (the only v2.1 run was Haiku at 89.66%).
  - **Re-freeze, version 2,** before any paid call (`paid_calls_before_freeze` still 0).
    Prompt `2e5ad2d1…4b14ad7` became `c0dd6c74…6653cf0`; schema `91bbeb56…6f01bcb67` and
    request `c8e5ef0c…92dfb11` are unchanged. The doubt-wording rule now covers only the
    six ruling-8 facets, and the stainless kitchen exception is named on both lines.
    Three new freeze tests failed on the version 1 doc and pass on version 2.
  - **Dev v5 screen** (model review, read only): 6 proposed gold changes in 6 items, 6
    borderline rows; private list `984aa72e…ddf7dd4`, manifest `9cf864ef…74cb0a3d`.
    `labels.json` unchanged (`6aab5483…f250ebde7`; full hashes in the contract doc).
  - **v2 Sonnet dev predictions were saved** (one private file, 100 of 100 dev rows).
    Rescoring them with the existing scorer against the current gold reproduced 94.69%;
    the rescoring against the revised gold waits for the owner's relabel.
  - The Phase D freeze, gate metric and single-use rule, and Phase E as the full-run
    decision, are written into the phases above and the contract doc.
- **2026-11-03 — owner decisions, round three, recorded (same PR; docs only).**
  - **Ruling 4:** a direct condo claim against a disagreeing subtype column: the subtype
    column decides, with the conflict flag `ruling4_subtype_conflict`. New private list
    `v3-dev-v5-relabel-candidates-v2.jsonl` (`0ae62271…de7ac507`) and manifest
    (`db3c8528…642bd0edb`); the first list (`984aa72e…ddf7dd4`) and its manifest are
    unchanged. **Conflict count on dev: 1.**
  - **Doubt wording** stays on the six ruling-8 facets; "all 20" is recorded as a v6
    candidate in the contract doc. `docs/ENRICHMENT_REVIEW_POLICY_V5.md` is not edited.
  - **Stainless:** the owner accepted the frozen reading (generic "stainless appliances"
    counts; a bare "stainless kitchen" stays uncertain). Change-table row 8 is marked
    owner-accepted.
  - **Held-out gate:** replaced by a rescored figure on revised held-out gold, screened
    from the policy alone after Phase C and before the D freeze; 88.2% stays as the
    historical figure. **Check of saved predictions** (presence, counts and recorded
    settings only; no held-out remark or gold read): no v2.1 (or v2) held-out
    predictions were saved; the only saved held-out predictions are v1's, 150 records.
    The plan stops there for the owner; no held-out screen or rescoring was run.
  - **Tokens:** C after the dev relabel and rescoring are on `main`; D after C clears and
    the D freeze is recorded; the batch after E, separately.
  - **Dev gold:** the relabel procedure (file `labels-v5-dev.json`, format, a count-only
    check command tested against the unchanged gold, the rescoring command, where the
    result is recorded) is written above.
  - **Freeze unchanged at version 2.** No round-three decision touches a frozen block;
    the recomputed prompt, schema and request hashes equal the freeze file.
  - No paid or provider call, extraction, store build, install or activation.
- **2026-11-04 — rulings 9 to 15, re-freeze version 3 and the final decisions (same PR;
  docs and one test only).** Branch merged with `main` at `9cff4bf` (#158, #159) by a merge
  commit; `docs/EVIDENCE_LOG.md` keeps every entry byte for byte.
  - **Rulings 9 to 15 in the v3 guide,** in our own words, on six facet lines (grocery
    for 9 and 15, transit 10, garage 11, single level 12, stainless 13, bonus room 14);
    change-table rows 16 to 22.
  - **Re-freeze, version 3** (the one recorded re-freeze the owner authorized): prompt
    `c0dd6c74…6653cf0` became
    `da0c34a1dce2d745f175b5d40c7476fb7c473ca08dcfed84fd0693f94f2dd1e4`; schema and request
    unchanged; reason `rulings 9-15`; policy file `3432736f…9a75a99`;
    `paid_calls_before_freeze` 0. Two new freeze tests failed on the version 2 doc and
    pass on version 3.
  - **Policy-only dev re-screen for rulings 9 to 15** (model review; dev remarks, dev gold
    and the policy only; no predictions opened; no held-out remark or gold read): 1
    proposed change (ruling 9, removal), 1 borderline (ruling 12), 4 existing labels
    confirmed (ruling 11: 3, ruling 15: 1). New cumulative private list
    `v3-dev-v5-relabel-candidates-v3.jsonl` (`ac586374…fbf10de3`, 14 rows, the 12 earlier
    rows byte for byte) and manifest (`a9ce10d3…2c8200c3b`); earlier lists and
    `labels.json` unchanged. Cumulative: 7 proposed changes, 7 borderline rows.
  - **Final decisions 1 to 5** written into Phase B and D above and the contract doc;
    dated clarifying notes on 88.2% and on v2's missing held-out score added to five
    enrichment result docs without changing their earlier text. Decisions 2 and 4
    replace the saved-predictions gate and resolve the "no saved v2.1 predictions"
    blocker.
  - **`score_v2` input contract read for decision 5:** it requires a valid remark span
    on every annotation (one invalid span fails the whole score) and receives no subtype;
    four points need the owner's scoring-contract decision before the freeze (Waiting
    on the owner, item 2).
  - **Relabel procedures:** the dev procedure now names every private path and list
    version, the full-copy rule, each edit by ruling number, a changelog manifest and one
    validation command (run by the agent on the unchanged dev gold and on invented
    private files only); the held-out equivalent is written for use after C and the lock.
  - No paid or provider call, extraction phase, store build, manifest freeze, install or
    activation.
- **2026-11-04 — one Phase C comparator, wording fixes and two owner questions (same PR;
  docs only).** Branch merged with `main` at `88b4651` (#147, #148, #150) by a merge
  commit; `docs/EVIDENCE_LOG.md` unchanged by the merge, every entry kept.
  - **One comparator definition** in this file and the contract doc: the saved v2 Sonnet
    dev predictions after the identical Phase B subtype mapping applied to v3, scored
    with `score_v2` over the 20 facets, unrounded, against the revised dev gold, no
    provider call (Phase C, prerequisite 3a; contract doc, "Scoring plan"). The unmapped
    rescore command stays, labelled as a recorded reference figure only.
  - **Mapping scope corrected:** the unsupported "at most the one flagged condominium
    case" is replaced by what option A can change (any predicted condominium claim that
    contradicts the subtype, on any case, within the proposed polarity scope); the dev
    impact is stated as not yet measured.
  - **Relabel expected counts** are now given for both owner choices on the ruling 9 row
    (`rows_changed` at least 8 with the removal, at least 7 without).
  - **Exhaustion** ends a Phase D run with no completion under the same token, freeze or
    budget; any completion is a new, separately authorized run on a new held-out set.
    The provider/auth-failure resume is now an owner question (item 8).
  - **Owner question, ruling 9** (item 9): whether a version 4 re-freeze before Phase C
    should adjust the frozen "a market, named or not" reading for grocery chains named
    "Market". The frozen prompt, schema and request are unchanged (version 3).
  - No paid or provider call; no held-out read; no prediction opened.
- **2026-11-04 — re-freeze version 4 (ruling 9 named grocery chains) and the final
  owner decisions recorded** (branch `wo-034-v4-refreeze`, from `main` at `5504cd5`;
  docs, the freeze file and one test file).
  - **Re-freeze, version 4** (the one expressly authorized extraction-contract
    re-freeze, limited to the grocery line): the `near_grocery_mentioned` guide line now
    says that a named grocery chain counts whatever words its name contains, including
    "Market" and "Farmers Market", and that the market rules apply only to an unnamed or
    unknown place. No other prompt line, and nothing in the schema or request block,
    changed. Prompt `da0c34a1…f2dd1e4` became
    `c698f20cec949b8d19c6a1af7c10e7a4e11972143d1027b289131ad8e270155e`; schema
    `91bbeb56…6f01bcb67` and request `c8e5ef0c…92dfb11` unchanged; date 2026-11-04;
    reason `ruling 9 named grocery chains (owner-authorized)`; versions 1, 2 and 3 kept
    under `previous` (version 3 with its recorded date, hashes and reason);
    `paid_calls_before_freeze` 0. Contract doc: change-table row 23, "Freeze history".
  - **Freeze test pins version 4:** versions 1 to 3 preserved, the schema and request
    hashes equal their version 1 values, the grocery line's new wording and order, and
    putting the version 3 grocery line back restores the version 3 prompt hash exactly
    (so no other prompt change). On the version 3 doc and freeze file 3 of its 14 tests
    fail; all 14 pass on version 4.
  - **Final decisions recorded** in the contract doc ("Owner decisions, 2026-11-04
    (final)") and under "Decided" above: scoring contract (a) to (d), the standard
    Messages API for both configurations, and the Phase D resume rule. Former open items
    2, 3, 8 and 9 are removed from "Still open"; the Phase B, C and D text and the
    held-out relabel procedure now cite the decisions.
  - **Ruling 9 dev row, policy-only check** (only the version 3 list's one ruling 9 row
    and that one dev item's remark were read; list hash `ac586374…fbf10de3` confirmed;
    no prediction of any contract, no score, no held-out remark or gold): **the row's
    proposal (remove the affirmed label, medium confidence) still holds under the
    clarification.** The only grocery evidence is one named place whose name contains
    the word "Market"; it is not a recognisable grocery chain, and the remark does not say
    what it sells, so under version 4 it is an unknown place and the market rule applies.
    The owner decides the row when relabelling (it stays if the owner knows the place to
    be a grocer or grocery chain). No new list was written. Not checked: whether another
    dev remark names a grocery chain containing "Market" without a gold label; under
    version 3 such a mention raised no candidate.
  - **Owner acceptance check 1 (2026-11-04), docs only:** the dev relabel procedure
    (step 1) now states explicitly that the version 3 list (`ac586374…fbf10de3`) is not
    stale after the clarification, that the step 3 editing instructions and the step 4
    expected counts are unchanged, and repeats both count sets (ruling 9 removal accepted
    and rejected). The one ruling 9 row and its dev remark were re-read for this; the
    hash was confirmed again; the recommendation still holds. No list was written.
    **Disclosure:** while locating the dev remark, the agent printed the first 400
    characters of `data/enrichment/sample.jsonl` to learn its record format before
    applying the split filter; that first record is a **held-out (test) remark**, so a
    400-character prefix of one held-out remark was seen. No held-out gold, label,
    prediction or score was read, nothing from it was written anywhere, and it played no
    part in the ruling 9 check. The owner decides whether this affects the held-out set's
    single use (recorded in `docs/EVIDENCE_LOG.md`).
  - **Dependency:** the policy PR on branch `chore-policy-v5-ruling-9-named-chains` adds
    the same clarification to ruling 9 of `docs/ENRICHMENT_REVIEW_POLICY_V5.md`. This PR
    should merge together with or after it. The freeze file's policy pin stays the file on
    `main` at this freeze (`3432736f…9a75a99`), with a note that the policy PR changes it.
  - No paid or provider call, extraction, store build, private store-manifest freeze,
    install or activation; no held-out remark or gold read; no prediction opened.
- **2026-11-04 — Phase B, key-free driver, parser, span check, mapper and the Phase D
  command** (branch `wo-034-phase-b`, stacked on `wo-034-v4-refreeze` at `9245d3f`;
  code and synthetic tests, plus these docs). No real private file was opened: every
  test uses invented remarks, subtypes, gold and predictions in a temporary directory.
  - **New code.** `src/idx_agent/enrichment/v3.py` (freeze verification, request body,
    parser, span check, `map_subtype`, the pass rule); `scripts/enrichment_v3_io.py`
    (the subtype-keeping loader, revised-gold loader, private writes, the v2.1 retry
    gate and the standard Messages API transport over `urllib`, usage accounting);
    `scripts/extract_enrichment_v3_dev.py` (Phase C and the comparator);
    `scripts/extract_enrichment_v3_heldout.py` (the Phase D command, never run). No
    provider SDK and no new dependency. The scorer, the gold, the splits and every
    earlier contract and freeze file are unchanged.
  - **Acceptance checks.**
    1. Before a token, the drivers verify `docs/ENRICHMENT_V3_FREEZE.json` by its own
       SHA-256 (`4edd9237…bd56a89`), version 4, and the three recomputed block hashes;
       the Phase C driver also pins `v3.py`, the I/O module and the scorer path by
       bytes. Tests mutate the prompt, schema, request block, freeze file, `v3.py`, the
       I/O module and `v2.py`: each stops with no call and the token unspent.
    2. Quote over 80 characters, `occurrence` below 1 or not an integer, past the last
       appearance, an unfound quote, an empty quote, an unknown facet, polarity or
       time, a malformed decision, a duplicate and a missing or doubled tool call are
       each a miss with a sanitized `field`/`rule` diagnostic; processing continues.
    3. Span check on invented remarks: inside and overlapping (passes), inside and not
       overlapping, not found, wrong occurrence and wrong polarity (fail). Reported over
       all decisions, over decisions whose (case, facet, polarity) group has gold, and
       by facet; not a gate.
    4. The v1, v2 and v2.1 freeze and scorer files are byte-identical to `main`
       (`git diff origin/main` is empty for each of them; a test checks them against
       the hashes the earlier drivers pin).
    5. Fake transport (network blocked, no key read, no client): one spent call per
       attempt; Phase C ceiling 300 (a token of 299, 301 or 600 is refused, and the
       loop stops at the ceiling); Phase D 300 initial requests always sent first,
       alternating case by case, retries after them in a fixed case order; at 600 the
       run stops `exhausted`, scores nothing, prints no prediction and refuses any
       further invocation; a first token other than exactly 600 is refused before any
       call; resume only after an auth or provider failure, with a new token capped at
       the calls left (a larger cap is refused before any call), the same ledger, no
       reset, completed checkpoints not resent; a token cap, a token refused mid-run and
       an interrupted invocation (including a local error after a written checkpoint)
       leave the run final with every sent request counted and the next invocation
       refused before a token is spent; a remark that fails three attempts ends the
       run as final.
    6. While running, the Phase D command prints only calls used, calls left and cases
       complete per configuration; scoring runs only when both are complete; a mutation
       of the driver, the I/O module, `v3.py`, `v2.py`, the scorer, the scoring and
       contract docs, the lock, the revised gold, `sample.jsonl`, `splits.json`, the v1
       reference predictions or the mapper rule stops it before a token is used.
    7. The mapper tests cover every polarity against `Condominium`, another subtype, a
       case or spelling variant, an empty and an unseen value; raw claims are unchanged;
       nothing is added; v1, v2 and v3 shapes map identically; `score_v2` runs on mapped
       output and raises on a spanless condominium annotation; a contradicting gold
       label fails the gold consistency check.
    8. New behavior in new files: the three new test files (with their shared
       synthetic fixture module) fail at `9245d3f`, 3 collection errors because the
       modules do not exist, and pass here (104 tests). Ruff and the full suite pass on
       the Mac in both modes, and CI passes.
  - **Mapper identity** (sealed later in the Phase D freeze): code
    `14a79573…f94458e1` (source of `is_condominium_subtype` and `map_subtype`), rule
    JSON `008ae08f…980cda13`, facet map `6bc9c8b5…1e89e078`, field map
    `7801a507…75887160` (full values from `v3.mapper_hashes()`). Superseded by owner
    acceptance checks 3 and 4 below, which extend the code hash and add the constants.
  - **Choices made inside the owner's decisions, for the owner to confirm before the
    lock:** (1) superseded by the review fix below: resume only after a provider or
    auth failure, and the first token carries exactly 600. (2) A remark and
    configuration whose three attempts all fail ends the run as `failed` (final): no
    further attempt is allowed, so the run could never complete. (3) The Phase D seal hash is given on the
    command line, so the paid token binds it; the freeze records the command with a
    `{seal}` placeholder, and cannot record the commit of its own PR. (4) The Phase C
    token must carry exactly 300 calls. (5) The Phase C run also computes the comparator
    in the same process from the same pinned files and reports `phase_c_clears`.
  - No paid or provider call, key read, extraction, store build, private store-manifest
    freeze, install or activation; no held-out remark or gold read; no prediction
    opened.
- **2026-11-04 — Phase B review fix: the Phase D resume follows the owner's rule
  exactly (same PR).**
  - Found in review: the command accepted a first token below 600 and resumed after a
    token cap, a token refused mid-run and an interrupted invocation, so the one sealed
    run could be split across several invocations with no provider or auth failure.
  - Now: the first invocation's token must carry exactly 600 calls (refused before any
    call otherwise, as Phase C requires exactly 300). A resume is allowed only after an
    `auth_failure` or a `provider_failure` with calls left, under a new token capped at
    the calls left. `token_cap`, `token_refused` (for example an expired token) and an
    interrupted invocation (a ledger left `running`, including a local error after a
    written checkpoint) leave the run final; every sent request stays counted and the
    next invocation is refused before a token is spent. The dry run reports these as
    not resumable with `max_token_calls` 0. The unused in-flight reconciliation step and
    its `reconciled` evidence event were removed.
  - Consequences for the owner: a resume token smaller than the calls left ends the
    run if it runs out, so it should carry exactly the `max_token_calls` the dry run
    prints; a paid token's minutes must cover the whole run, because expiry mid-run is a
    `token_refused` stop and final. Whether an interrupted invocation (Ctrl-C, a crash,
    a local disk error) may be resumed is an owner question; until it is decided, it
    may not.
  - Tests: `tests/test_enrichment_v3_heldout.py` gives 13 failed, 29 passed against the
    driver at `40d436f` and 42 passed here.
- **2026-11-04 — owner acceptance checks 3 and 4 (same PR).** The stack was brought up
  to date first: `origin/wo-034-v4-refreeze` (`160f5c8`, acceptance check 1, docs only)
  merged into this branch (one conflict in `docs/EVIDENCE_LOG.md`, both entries kept).
  - **Check 3, found and fixed:** both paid paths read the key before the token was
    checked, and the Phase D first-token and resume-ceiling checks (and Phase C's
    300-call check) ran after `start_paid_run` had spent the token. A missing token or a
    wrong ceiling therefore read the key, and a wrong ceiling consumed the token and
    wrote the consent audit log. Now `paid_token_preflight` (read-only, through the
    token reader's own `paid_reason` and `paid_token_status`) checks the token and its
    ceiling first; the key is read and the token spent only after it passes, and the
    ceiling is checked again on the grant. Also found: with the lock missing and a
    freeze present, Phase D refused with a `FileNotFoundError` and no reason; it now
    checks the lock first and refuses "the Phase D lock is missing" before any private
    file is opened.
  - **Check 4, found and fixed (the reviewer's edge):** when the 600th call ended in an
    auth failure or a non-retryable provider error, the ledger stayed `stopped` and the
    dry run reported it resumable (with `max_token_calls` 0); interrupted on that call,
    it stayed `running`. Now a run with no calls left is written `exhausted` and the dry
    run reports any such ledger as `exhausted`, not resumable. An interrupt with calls
    left is now written `stopped`, `interrupted` with an evidence line (it was left
    `running`); still final.
  - **Also:** `phase_d_verdict` carries the decision (d) caveat (`not_evaluable_note`),
    and the mapper hash covers `map_payload`, `gold_consistency`, `CONDOMINIUM` and
    `CONFLICT_FLAG` as well. New mapper identity: code
    `a9a5fab65af53b687fad8193b3d2ceeaee0c33dfd280f5c941f29804dc73a41e`, constants
    `a0b23adc458a428d8845642c954c56a8d7ee0338511dcd236ac36ee9965b2c0b`; rule, facet and
    field maps unchanged. Phase C pins updated: `v3.py`
    `0ea76d5213b1b7b74f621828a98b56f732dc3ef24a0e2f90ee93dab43b5754c4`, I/O module
    `a186d8acf98b36a9abe2870715be22b41d8a13108dcf5a9caa16c1663aae2267`.
  - **Tests** (`tests/test_enrichment_v3_acceptance.py`, sentinels in
    `tests/enrichment_v3_guards.py`): every dry run (Phase C, Phase D, the comparator)
    and both preflights, and every failed local precondition (missing or mismatched
    freeze, missing gold, wrong-hash gold, original labels, seal mismatch, mutated lock,
    missing token, token for another command, first token of 599 or 601, Phase C tokens
    of 299 and 301, existing output, no disclosure flag, lock missing) run with key reads
    (any `*API_KEY*` variable, `.env`, `evals.run._local_setting`, `read_key`), the
    provider SDK module, the `httpx` clients, `urlopen`, `socket.socket` and
    `socket.create_connection` all turned into failing sentinels, and assert the
    consent directory and the private directory are unchanged byte for byte. The lock
    test makes the held-out remark, split, gold and v1 prediction files unreadable
    sentinels and asserts the refusal reason. Resume tests: three invocations (auth
    failure, provider failure, completion) count sends per item across invocations
    against the ledger, keep checkpoints byte for byte, and check the persisted totals
    only grow; fresh grants of 591 and 600 after 10 calls are refused with the token
    unspent, 590, 291 and 1 accepted; a 600th call that fails (auth, non-retryable) or
    is interrupted leaves the run `exhausted` and refuses a resume; no stop path
    (auth, provider, retry limit, exhaustion, token cap, interrupt) writes a
    prediction, mapping or result file or prints a score.
  - **Fail before, pass after:** the new and updated tests, run against the pre-fix
    head `630bf0c` in a detached scratch worktree, give 32 failed and 134 passed; all
    pass here. The two mapper-hash cases for `is_condominium_subtype` and
    `map_subtype`, and the dry-run and local-precondition sentinel tests, passed before
    too and pin existing behaviour.
  - **Open owner question (unchanged, conservative):** may an interrupted invocation
    (Ctrl-C, a crash, a local disk error) with calls left be resumed? The owner's rule
    names provider and auth failures only, and says interrupted requests "stay
    counted". Until the owner decides, an interrupted invocation is final.
  - No paid or provider call, key read, extraction, store build, private
    store-manifest freeze, install, activation or merge; no real private file,
    held-out remark, gold or prediction opened; `consent.sh` not run.

- **2026-11-04 — policy pin correction after #162 merged** (branch `wo-034-v4-refreeze`;
  `main` `71fb39e` merged in by merge commit; the freeze file, one test, docs).
  - The owner's order: "Finalize #162's policy bytes before finalizing either the
    store-manifest proposal or #163's policy hash. Reverify both against the merged
    policy." #162 is merged; `docs/ENRICHMENT_REVIEW_POLICY_V5.md` on `main` is
    `229fdd74eb280827a2cf799897c229c33330a97d4cd31c84122d2eb0dbf0e7f8`.
  - `docs/ENRICHMENT_V3_FREEZE.json`: version 4's policy pin changed from
    `3432736f…9a75a99` (the file before the ruling 9 named-chain clarification) to
    `229fdd74…dbf0e7f8`, with a note recording the correction. **Provenance only, not a
    re-freeze:** prompt `c698f20c…8e270155e`, schema `91bbeb56…6f01bcb67` and request
    `c8e5ef0c…92dfb11` unchanged; versions 1 to 3 unchanged; `paid_calls_before_freeze` 0.
  - New freeze test: the latest freeze version's policy pin equals the SHA-256 of
    `docs/ENRICHMENT_REVIEW_POLICY_V5.md`, and that file is the bytes #162 merged.
    **Fail-before/pass-after:** it fails on `160f5c8` (the file there is the pre-#162
    `3432736f…`, not the merged bytes) and on the merge of `main` before the fix (pin
    `3432736f…` against file `229fdd74…`); all 15 freeze tests pass after the fix.
  - The dependency note in the version 4 entry above is now resolved. The store-manifest
    proposal (WO-035) is not changed here; its reverification against the merged policy
    belongs to that work order.
  - No paid or provider call, key read, extraction, store build, install, activation or
    merge; no held-out remark or gold read; no prediction opened.
- **2026-11-04 — owner decisions 1 to 6 recorded; incident wording corrected; held-out
  exclusion written** (branch `wo-034-v4-refreeze`; docs, one test, one new private
  file).
  - **Incident wording, corrected.** The owner acceptance check 1 entry above says a
    400-character prefix of one held-out remark "was seen". More exactly, the first 400
    characters of that held-out remark **entered the tool/conversation record**. Its
    text is not repeated here or anywhere. No evaluation ran, so **it consumes no
    Phase D attempt**; the case is **excluded from the primary score**; **no candidate
    change may be informed by it**. The earlier entry stays as written.
  - **Exposed case identified privately, by id only.** A script parsed only the first
    line of `data/enrichment/sample.jsonl` and used only its `key` field (the field
    `scripts/score_enrichment_private.py` reads); it printed neither the id nor any
    other field, only the split, the test count, the file mode and the hash.
    `splits.json` confirms that id is a `test` case (150 test cases in all). No other
    held-out record, no gold label, prediction or score was opened.
  - **New private exclusion file**, `data/enrichment/v3-heldout-exclusions-v1.json`,
    mode 600, created once (exclusive create), SHA-256
    `2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0`: version 1, 1
    excluded case, split `test`, `primary_n` 149, `diagnostic_n` 150. Tracked files hold
    only the hash and counts. `splits.json`, `sample.jsonl` and `labels.json` unchanged.
  - **Scoring procedure** written into Phase D, the contract doc's seal table and pass
    rule: 150 requests per configuration unchanged; primary score on 149; full-150
    diagnostic from the same outputs; exclusion file and procedure sealed in the Phase D
    freeze.
  - **Decisions 2 to 4** recorded (interrupted-run resume; a failed or interrupted 600th
    attempt exhausts the run, no refund; the read-only early token check through the
    existing consent reader). Their code lives in the Phase B stream.
  - **Decision 5, dev re-screen:** all 100 dev remarks screened once, policy only (no
    prediction, no held-out data); no recommendation changed, so no addendum; version 3
    list `ac586374…fbf10de3`, its manifest and `labels.json` byte-unchanged; expected
    validation counts unchanged. Model judgments, `human_review: pending`.
  - **Decision 6** restated under "Decided".
  - New test: the contract doc's seal table names the exclusion file with its SHA-256,
    and the pass rule states the 149 primary and 150 diagnostic populations. It fails on
    `82f49f6` and passes after.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge; no prediction opened.
- **2026-11-04 — owner decisions 1 to 4 in the Phase B code; pending review fixes (a)
  to (d)** (branch `wo-034-phase-b`; code, synthetic tests, docs). The stack was brought
  up to date first: `origin/wo-034-v4-refreeze` at `0fb0414` merged in by merge commit
  (`8a98b00`; conflicts in `docs/EVIDENCE_LOG.md` and this file, both sides kept, this
  branch's entries first).
  - **Freeze re-pin (`1270fdf`).** The merged version 4 policy pin correction changed
    the bytes of `docs/ENRICHMENT_V3_FREEZE.json`, so `verify_contract` refused it.
    `FREEZE_FILE_SHA256` is now `9a04ca3e0dcc21ef4306065da97a48a4913e3f25483675045ca1ed1af77b5391`
    (prompt, schema and request hashes unchanged). At the merge the v3 suites gave 26
    failed and 71 errors; all pass after.
  - **Decision 2 and fixes (a) to (c) (`4c952e8`).** An interrupted invocation (an
    interrupt or a local error anywhere in the loop, the back-off sleep and the token
    spend included) is written `stopped`, `interrupted` with its stop in the run
    evidence, and may resume under a fresh token capped at the calls left only when the
    sealed inputs re-verify and the run state validates: the evidence has an `attempt`
    line per counted call and a `response` line with the response bytes' SHA-256 before
    each checkpoint; the ledger and the evidence must agree call by call; the ledger may
    never hold fewer attempts than the evidence proves (a); the stop must be recorded (b);
    each checkpoint must exist exactly for a completed request and hash to its line; no
    result may exist before completion. The request left in flight is settled: complete
    and never resent when its checkpoint verifies, otherwise a counted attempt retried
    within the frozen limits. Corrupt or unverifiable state (run files without a ledger,
    a truncated ledger or evidence, an unrecorded stop, a checkpoint mismatch, results
    before completion, a stray file) is reported by the dry run and, on a paid
    invocation, written to `v3-heldout/final.json` (reason only) before any key or token;
    every later invocation refuses. The first ledger is created exclusively, never over
    existing state. Checkpoints are written whole (temporary file, then a hard link).
  - **Fix (d).** A missing gold file refuses with an explicit reason in Phase D ("the
    revised held-out gold file is missing") and Phase C ("the revised gold file is
    missing").
  - **Decision 3.** A failed (retryable, auth) or interrupted 600th attempt leaves the
    run `exhausted` and final; the 600 calls stay counted, nothing is refunded.
  - **Decision 4.** The read-only early check (`paid_token_preflight`, through the
    existing consent reader) and the authoritative `start_paid_run` and spends before
    provider access are unchanged; `scripts/guards/` and the consent mechanism are not
    modified. New test: across an auth stop, an interrupt, a resume and a dry run, no
    token file line, expiry or grant time appears in stdout, stderr, the ledger, the
    evidence or any run file.
  - **Decision 1 (`34a4448`).** The final freeze seals `v3-heldout-exclusions-v1.json`
    by path and SHA-256, with its counts (`private_files.exclusions`); the driver pins
    `2e60fd85…e8a8a0`, and the file's content is validated (format, test split, ids in
    the held-out set, `primary_n`, `diagnostic_n`). The command refuses before a token
    when the seal does not record it, the file is missing or its SHA-256 differs. All 150
    cases are still requested by both configurations. After both complete, the verdict
    uses the 149 primary cases; the full-150 score from the same outputs is released
    beside it as `diagnostic_full_150`, with no `pass` field. No case id is printed or
    tracked; tests use an invented exclusion.
  - **Hidden files (`87dd0f5`).** A Finder `.DS_Store` or a temporary file left by a
    hard kill in the run directory is not run state and no longer makes the run final;
    symlinks and visible stray files still do.
  - **Fail before, pass after** (new and updated tests run against the previous head in
    a scratch export): the resume and validation tests 29 failed, 104 passed against
    `1270fdf`; the exclusion tests 1 failed and 18 errors against `4c952e8` (no
    exclusion pin); the hidden-file test 1 failed against `34a4448`; all pass here. The
    token-content and seal re-verification assertions pin existing behaviour (their tests
    fail before only because the old driver refuses an interrupted resume or has no final
    marker).
  - **Consequences for the owner:** a hard kill (SIGKILL, power loss) writes no stop, so
    the state is unverifiable and the run final; a visible stray file in the run
    directory makes the run final. Open owner question 6 ("Still open") replaces the
    former interrupted-invocation question.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge; no real private file, held-out remark, gold, prediction or
    score opened; the real exclusion file was not opened (its hash is the one recorded
    in the #163 stream).
- **2026-11-04 — review of `74fe559`: an interrupt while an invocation starts, and a
  stored exhaustion** (branch `wo-034-phase-b`; code, synthetic tests, docs).
  - **Confirmed, fixed (`b424e54`).** An interrupt after the ledger was saved with a new
    invocation and before its settlement and start lines were written left the ledger
    `running` with no matching evidence, so the run became final with no call made
    (on an initial or a resumed invocation). `Run.begin` now runs inside the
    interrupted path through `commit`: the save and its evidence lines are written
    together, a SIGINT in between is held until they are written, and after a local
    error past the save the remaining lines are still written, best effort. The first
    ledger is created whole (temporary file, fsync, hard link), so an interrupt
    mid-write leaves no ledger and the run has not started.
  - **Confirmed, fixed (`b424e54`; decision 3).** A run written `exhausted` after an
    interrupted 600th attempt whose checkpoint was already on disk was released on the
    next invocation, with no token, because settling marked the request done. A stored
    `exhausted` or `failed` status now stands whatever settling finds. An interrupt
    after both configurations are complete and saved writes the ledger `complete`, not
    `exhausted`.
  - **Not changed.** A resume token below the calls left, or a token refused mid-run,
    still ends the run when it stops on `token_cap` or `token_refused`. That is the
    owner's rule as recorded (Status, "Phase B review fix: the Phase D resume follows
    the owner's rule exactly": resume only after an auth or provider failure, and now
    an interrupt per decision 2; a token cap or refusal is final), and decision 2
    allows a token "capped at the remaining allowance", so neither the resumable stops
    nor the accepted ceilings are widened or narrowed here. Open owner question 6
    stands; until it is decided, a resume token should carry exactly the
    `max_token_calls` the dry run prints.
  - **Fail before, pass after:** six new tests in `tests/test_enrichment_v3_resume.py`
    fail against `74fe559` (interrupt before the initial start line, interrupt while a
    resume records its settlement, a real SIGINT while an invocation starts, an
    interrupt mid-way through the first ledger, an interrupted 600th attempt with its
    checkpoint, an interrupt after the 600th is marked done) and pass here.
  - No paid or provider call, key read, `consent.sh`, merge; no real private file,
    held-out remark, gold, prediction or score opened.
- **2026-11-05 — owner decisions on the Phase D open questions and the points before
  the lock recorded; `main` merged in** (branch `wo-034-v4-refreeze`; docs only).
  - `main` merged in twice by merge commits: `83ff9c5` (#165, #167, #168) at `610bfb0`,
    then `4ec99bd` (#169, which reached `main` after the first merge) at `930b549`.
    The only conflict each time was `docs/EVIDENCE_LOG.md`, both sides appending; it is
    resolved as `main`'s file byte for byte followed by this branch's entries byte for
    byte, so every entry is kept.
  - Recorded under "Decided", 2026-11-05, verbatim, with how each is applied: open
    question 1 (`token_cap` and `token_refused` stops may resume under decision 2's
    conditions with a fresh token capped at the calls left; the 600-call ledger bounds
    spend, not the token); open question 2 confirmed (a run found complete after
    settling is scored and released with no new token; exhausted or failed stays final);
    items 1, 3, 4 and 5 before the lock confirmed as written (the first Phase D token
    exactly 600; the seal hash on the command line; the Phase C token exactly 300; the
    Phase C report computes the comparator in-process), with item 1's token-stop clause
    superseded by open question 1; item 2 replaced (a remark that fails all three
    attempts is a failed request scored as an empty prediction for that configuration,
    its count reported; more than two in either configuration make the run final and
    failed).
  - Phase D gains a paragraph, "Token stops, settled runs and failed requests", and its
    Report line now includes the failed-request count per configuration. "Waiting on the
    owner" notes the 2026-11-05 decisions; its "Still open" items 1 to 5 on this branch
    are different items and are unchanged. The questions themselves were listed on the
    Phase B branch (PR #164, "Still open" item 6 and the PR's "before the lock" list);
    that branch removes its item 6 when it takes this one in, and its code carries the
    behaviour.
  - Freeze unchanged at version 4: prompt `c698f20c…8e270155e`, schema
    `91bbeb56…6f01bcb67`, request `c8e5ef0c…92dfb11`; `paid_calls_before_freeze` 0. The
    freeze test passes.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge of a PR; no held-out remark, gold, prediction or score opened.
- **2026-11-05 — owner decisions of 2026-11-05 in the Phase B code: token stops,
  settled runs, failed requests** (branch `wo-034-phase-b`; code, synthetic tests,
  docs). `origin/wo-034-v4-refreeze` at `b675463` merged in first by merge commit
  (`dd2bdd4`; one conflict, this file's progress log, both sides kept, this branch's
  2026-11-04 entries first). The merge brings `main` through #169 into this branch.
  - **Open question 1, token stops.** `token_cap` and `token_refused` join the
    resumable stops in `scripts/extract_enrichment_v3_heldout.py` (`RESUMABLE`). A
    resume runs only under decision 2's conditions, all unchanged: the sealed inputs
    re-verify, the ledger, the evidence and every checkpoint validate, calls remain,
    nothing is released; a fresh command-bound token, at most the calls left. A
    smaller token that runs out stops `token_cap` again, still resumable; the 600-call
    ledger bounds spend. Both stops come before a call is spent, so no call is counted
    for them. The first token still carries exactly 600.
  - **Open question 2, settled runs.** Kept as built: a run found complete after
    settling is scored and released with no token, key or provider call; a stored
    `exhausted` or `failed` stays final whatever settling finds. A new test pins the
    release after a settled checkpoint; it passes before and after (existing
    behaviour).
  - **Item 2, failed requests.** A remark whose three attempts all fail no longer ends
    the run: the ledger holds it `failed` (three attempts counted, no refund), the
    evidence gets a `failed_request` line, and the run goes on. At release it is scored
    as an empty prediction (`annotations: []`) by the same mapping and `score_v2`, in
    the primary and diagnostic scores, and each configuration's count is released as
    `failed_requests`. More than two in either configuration (`MAX_FAILED_REQUESTS` 2)
    stop the run `failed`, reason `failed_requests`, final, nothing released; the stop
    line carries the counts. When settling an interrupted third attempt finds the third
    such request, the command writes the ledger `failed` and a `final` evidence line
    with the counts, then refuses before any key or token. An auth or non-retryable
    error on a third attempt is a failed request too; when every other request is
    answered, the run is complete and released. A failed request whose line an
    interrupt prevented is recorded late; validation rejects a `failed_request` line
    that is duplicated or names a request not failed in the ledger, a `failed` item
    with fewer than three attempts, a `retry` item with none left, and a `final` line
    that does not match a `failed` ledger.
  - **Docs.** The contract doc ("Ledger rules as built", "Owner decisions of
    2026-11-05, as built", "The Phase D command contract", "The metric and the pass
    rule"; the frozen blocks unchanged, `verify_contract` passes), `docs/CONTRACTS.md`
    (ledger, evidence, validation, result), the Phase D dry-run note above, and
    "Still open" item 6 removed.
  - **Fail before, pass after:** the new and changed tests, copied into a scratch
    export of the merge `dd2bdd4`, give 25 failed and 137 passed across
    `tests/test_enrichment_v3_heldout.py`, `tests/test_enrichment_v3_resume.py` and
    `tests/test_enrichment_v3_acceptance.py`; all pass here. The two that pass before
    pin existing behaviour (the settled-complete release, and a failed 600th call with
    another request unanswered still exhausting the run).
  - **For the owner (one reading to confirm before the lock):** a failed 600th call
    (retryable, auth or non-retryable) that is the third attempt of the **last**
    unanswered request now completes the run, with that remark a failed request,
    because nothing is left to resume; decision 3 read alone ("a failed 600th attempt
    counts as exhausted") would make it exhausted and final. With any other request
    unanswered, a failed or interrupted 600th call still exhausts the run, and an
    interrupted 600th attempt is still exhausted whatever settling finds.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge; no real private file, held-out remark, gold, prediction or
    score opened.
- **2026-11-05 — review fix: a third attempt answered but never checkpointed**
  (branch `wo-034-phase-b`; code, one synthetic test, docs). The command records a
  `response` line before it writes the checkpoint. An interrupt between the two on a
  third attempt leaves the request in flight with three attempts and no checkpoint;
  settling rightly makes it a failed request. But the validator rejected any
  `failed_request` line whose third attempt had a `response` line, so once a resumed
  invocation had recorded that line the next load reported the run unverifiable and
  a paid invocation would have marked it final. The validator in
  `scripts/extract_enrichment_v3_heldout.py` (`_check_failures`) now allows that
  `response` line; a failed request must still hold three attempts, be `failed` in
  the ledger and have no checkpoint. `docs/CONTRACTS.md` updated to match.
  - **Fail before, pass after:** the new test in `tests/test_enrichment_v3_resume.py`
    (an interrupt on the third attempt's checkpoint write with another request still
    open, a resume interrupted in turn, then a dry run and a release) reports
    `unverifiable` before the fix and `complete`, then released with one failed
    request per configuration, after.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge; no real private file, held-out remark, gold, prediction or
    score opened.
- **2026-11-10 — `main` merged in again; two stale passages corrected** (branch
  `wo-034-v4-refreeze`; docs only). `main` `7a1fe36` merged in by the merge commit
  `f3f1211`. The only conflict was `docs/EVIDENCE_LOG.md`, both sides appending after
  the shared base; it is resolved as `main`'s file byte for byte followed by this
  branch's entries byte for byte, and `main`'s log is an exact byte prefix of the
  result. Phase B acceptance check 5 now says the exhausted run records `exhausted`
  (the command's status; it said `incomplete`) and adds the decision 2 and 2026-11-05
  resumes and the failed-request rule; the Phase D "No tuning, one attempt" paragraph
  now points to decision 2 and the 2026-11-05 decisions instead of the provider/auth
  rule alone. Both were checked against the Phase B code (PR #164) and "Decided";
  dated Status entries are unchanged. No paid or provider call, key read, extraction
  or merge of a PR; no held-out remark, gold, prediction or score opened.
- **2026-11-10 — contract doc made consistent with the last-unanswered-request reading**
  (branch `wo-034-phase-b`; docs only). `docs/ENRICHMENT_EXTRACTION_V3.md` stated in
  "Exhaustion whatever the last stop" and "The 600th attempt (decision 3)" that a failed
  600th call always leaves the run `exhausted`, while "Failed requests (item 2)" and the
  code (pinned by the 2026-11-10 test in `tests/test_enrichment_v3_heldout.py`) complete
  the run when that call is the third attempt of the last unanswered request. Both
  passages now name that one exception as built and awaiting the owner's confirmation
  before the lock; an interrupted 600th attempt is still `exhausted`. No code, prompt,
  schema or request block changed, so the freeze hashes are unchanged. No paid or
  provider call, key read, extraction or merge; no held-out remark, gold, prediction or
  score opened.
