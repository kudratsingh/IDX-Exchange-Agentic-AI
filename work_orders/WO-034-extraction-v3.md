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
- **Prerequisites** (owner decision, 2026-11-03; detail in
  `docs/ENRICHMENT_EXTRACTION_V3.md`, "Phase C prerequisites"):
  1. The list of dev items where a v5 ruling changes the gold answer. **Done
     2026-11-03** (model review, private file, SHA-256 `984aa72e…ddf7dd4`): 6 proposed
     changes in 6 items (ruling 3: 1, ruling 6: 1, ruling 7: 4; all additions), 6
     borderline rows with no change proposed, and none for rulings 1, 2, 5 and 8.
     **Round three:** a new versioned private list, `…-v2.jsonl` (SHA-256
     `0ae62271…de7ac507`), adds `conflict_flag`; 1 row carries
     `ruling4_subtype_conflict` (see "Ruling 4 conflicts" below).
  2. The owner applies all 6 proposed changes and decides the 6 borderline rows by
     ruling number, by hand, into a new versioned gold file, following "Dev gold relabel
     procedure" below. `labels.json` is not modified.
  3. The saved v2 Sonnet dev predictions (saved: one private file, 100 of 100 dev rows)
     are rescored against the revised gold with the existing scorer and no provider
     call, using the exact command in the contract doc. Against the current gold the
     command reproduces 94.69%; that was a reproducibility check, not a result.
  4. Steps 2 and 3 are **on `main`** (recorded in a merged PR) before the Phase C token
     is granted (owner decision, 2026-11-03, round three).
  5. Phase B merged; the freeze verified at run time; the owner's token.
- **Report** (aggregate only, `docs/ENRICHMENT_V3_DEV_RESULTS.md`): v3's 20-facet micro
  F1 (the metric defined for Phase D) against the revised gold, compared with the
  rescored v2 Sonnet figure on the same gold; per-facet deltas against that rescored
  column; **94.69%, the historical v2 Sonnet dev score** (October gold), shown beside
  them and labelled as such. v2.1 Sonnet has no dev score; the only v2.1 run was Haiku
  at 89.66%. Also span-quality rate (all decisions, matched decisions, by facet), tokens
  per remark (uncached, cache write, cache read, output), requests, retries, missing tool
  calls and remarks with validation misses, and the revised gold's SHA-256. Cost comes
  from the provider console only.
- **After the run:** prompt edits are allowed on dev evidence only, each with its reason.
  Any edit needs a new freeze (version 3 of the freeze file, recorded hashes, test
  updated) in its own PR before D. A rerun on dev after an edit needs a new token.
- **Stop conditions:** v3 dev F1 below the rescored v2 Sonnet figure on the same revised
  gold (report and stop before D); a provider or auth failure, or private results that
  cannot be persisted; any new dependency or service.

### D. Paid, held-out
- **Run:** the 150 held-out remarks, one `paid` token, call ceiling 450, standard API, the
  contract as frozen after C.
- **Held-out gate (owner decision, 2026-11-03, round three; detail in the contract doc,
  "The held-out gate").** In this order, after Phase C (so the held-out set stays
  untouched while the prompt may still change on dev evidence) and before the D freeze:
  1. Identify the held-out items a v5 ruling changes, **from the policy alone**, without
     consulting any candidate predictions (no v3 output, and not any saved held-out
     predictions). Private list and manifest; aggregates only in tracked files. The
     ruling 4 conflict rule and flag apply.
  2. The owner relabels them into a new versioned held-out gold file. The old gold stays.
  3. Rescore the saved held-out predictions the owner named ("the saved v2.1 held-out
     predictions") with the same scorer against the revised gold, no provider call.
     **That unrounded number is the gate;** Phase D must meet or exceed it. **88.2% stays
     as the historical figure.**
  4. Freeze gold, prompt, parser, mapping and scoring protocol. One attempt.
- **Check of the saved held-out predictions (2026-11-03; file presence, record counts and
  recorded settings only, no held-out remark or gold read):** **no saved v2.1 held-out
  predictions exist.** v2.1 never ran on held-out, and no v2 held-out output exists
  either. The only saved held-out predictions are v1's (150 records, written by
  `scripts/extract_enrichment_test.py`; recorded counts equal the published 88.2% run).
  **The plan stops here for the owner** (see "Waiting on the owner"): steps 1 to 4 are not
  started and the gate number does not exist.
- **Prerequisites:** C's dev F1 at or above the rescored v2 Sonnet figure; steps 1 to 3
  above done and the gate number recorded; **the Phase D freeze**
  (`docs/ENRICHMENT_V3_D_FREEZE.json`: revised held-out gold, gate number, prompt,
  schema, request, parser, mapping and scoring protocol, each hashed as the contract
  doc's "Phase D" table says) merged and verified by the driver before any token is
  spent; then the owner's token, granted after C clears and the freeze is recorded.
- **Metric for the held-out gate** (exact definition in the contract doc): micro F1 over
  the 20 facets and all 150 cases, on (case, facet, polarity) groups with polarity-aware
  overlap per `ENRICHMENT_SCORING_V1`'s amendment, temporality ignored, no numeric
  fields (v3 extracts none), `2 TP / (2 TP + FP + FN)` = `score_v2(...)["overall"].f1`,
  passing when it meets or exceeds the gate number from step 3, unrounded (the bar was
  0.882 before round three). Per facet: that facet's `score_v2` entry, gold groups at
  least 10 and F1 at least 0.80, unrounded; an undefined F1 does not meet it.
- **Report** (`docs/ENRICHMENT_V3_HELDOUT_RESULTS.md`): that F1 against the gate number,
  with 88.2% beside it as the historical figure (v1's all-field held-out result; the
  original integration gate in `ENRICHMENT_SCORING_V1` is 85%), each facet against the
  per-facet rule, span quality and tokens per remark.
  As a diagnostic, report the 92.4% that v1 reached on the same 20 facets, pooled from
  its published per-facet counts.
- **No tuning, one attempt.** Nothing is tuned against Phase D results, and there is no
  repeated attempt on the same held-out set: once any v3 held-out score exists, no
  further v3 run on these 150 remarks. A run that stops before scoring goes to the owner,
  who decides whether its own checkpoints may be completed under the same token and
  freeze.
- **Second use of the held-out set.** This is the second time the 150 held-out remarks
  are scored; v1 was the first, on 2026-10-28. The report must say so, and so must a
  WO-018 Status entry written in WO-018's own file. Any further iteration after D needs
  a fresh held-out sample.
- **Stop conditions:** any wish to edit the prompt, rules or scoring from held-out
  results; incomplete or invalid predictions (the run cannot pass); any new dependency or
  service.

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
applies the same rule and flag.

## Dev gold relabel procedure (owner step, before Phase C)
1. **File.** Create `data/enrichment/labels-v5-dev.json` in the main checkout, owner-only
   (mode 600). Never edit `labels.json` (SHA-256 `6aab5483…f250ebde7`), and never
   overwrite an existing file of that name.
2. **Format.** The same shape as `labels.json`: `{"version": 1, "dataset_id":
   "remarks-20261027-v1", "labels": [...]}`, all 250 rows in the same order, each
   `{"id", "annotations"}`. Start from a full copy of `labels.json`. Only dev rows change;
   held-out (test) rows stay exactly as they are.
3. **Edits,** from `v3-dev-v5-relabel-candidates-v2.jsonl`:
   - the 6 rows with `disposition: "change"`: append one facet annotation to that item
     with the row's `proposed_gold` fields (`kind`, `group`, `value`, `polarity`,
     `temporality`, `start`, `end`) plus `quote`, which is the remark's characters from
     `start` to `end` exactly (gold annotations carry a quote; the list does not);
   - the 6 rows with `disposition: "borderline_no_change"`, by ruling number: **ruling 4**
     (1 row, `conflict_flag: "ruling4_subtype_conflict"`) is decided by the owner's
     ruling 4 decision: remove the `condominium` annotation listed under `current_gold`;
     **ruling 6** (3 rows, `clubhouse`) and **ruling 7** (2 rows, `bonus_room`): the
     owner adds a label or leaves the row as it is;
   - nothing else.
4. **Check** (prints only counts, facet names and the hash), from a checkout of `main`:
```
PRIVATE=<main checkout>/data/enrichment GOLD=labels-v5-dev.json \
PYTHONPATH=src:. .venv/bin/python - <<'EOF'
import hashlib, json, os
from collections import Counter
from pathlib import Path
from scripts.score_enrichment_private import _read_private, _sample_jsonl
P, NEW = Path(os.environ["PRIVATE"]), os.environ["GOLD"]
assert hashlib.sha256((P / "labels.json").read_bytes()).hexdigest() == (
    "6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7")
old, new = _read_private(P, "labels.json"), _read_private(P, NEW)
assert {k: new[k] for k in ("version", "dataset_id")} == {
    k: old[k] for k in ("version", "dataset_id")}
assert [r["id"] for r in new["labels"]] == [r["id"] for r in old["labels"]]
text = {c["id"]: c["text"] for c in _sample_jsonl(P, "dev")["cases"] if c["split"] == "dev"}
rows, delta = 0, Counter()
for a, b in zip(old["labels"], new["labels"]):
    if a["id"] not in text:
        assert a == b, "a held-out row changed"
        continue
    dump = lambda x: json.dumps(x, sort_keys=True)
    before, after = Counter(map(dump, a["annotations"])), Counter(map(dump, b["annotations"]))
    rows += before != after
    for diff, sign in ((after - before, "+"), (before - after, "-")):
        for k, n in diff.items():
            x = json.loads(k)
            if sign == "+":
                assert text[a["id"]][x["start"]:x["end"]] == x["quote"], "quote mismatch"
            delta[f'{sign}{x.get("group")}.{x.get("value")}.{x.get("polarity")}'] += n
print(json.dumps({"dev_rows_changed": rows, "annotation_delta": dict(sorted(delta.items())),
                  "sha256": hashlib.sha256((P / NEW).read_bytes()).hexdigest()}))
EOF
```
   Expected with all 6 changes and the ruling 4 removal: at least 7 dev rows changed;
   `+interior_systems.stainless_appliances.affirmed` 1, `+community_amenities.clubhouse.affirmed`
   at least 1, `+rooms_layout.bonus_room.affirmed` at least 4,
   `-property_type.condominium.affirmed` 1. (Run with `GOLD=labels.json` it prints 0 rows
   changed and the old hash; that was checked on 2026-11-03.)
5. **Rescore.** Run the rescoring command in `docs/ENRICHMENT_EXTRACTION_V3.md` ("Phase C
   prerequisites", item 2) once, with `GOLD=labels-v5-dev.json`. No provider call.
6. **Record.** In one PR to `main`, aggregates only: the revised gold's SHA-256, the check
   output's counts, and the rescored v2 Sonnet overall expected / predicted / correct and
   unrounded F1 with the per-facet counts, in `docs/ENRICHMENT_EXTRACTION_V3.md` ("Phase C
   prerequisites"), a WO-034 Status entry and an `docs/EVIDENCE_LOG.md` entry. That PR
   merged is the condition for the Phase C token.

## Order of the paid tokens (owner decision, 2026-11-03, round three)
1. **Phase C:** only after the dev relabel and the dev rescoring are on `main`.
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

## Waiting on the owner
Decided 2026-11-03: the baseline wording (94.69% is the historical v2 Sonnet dev score),
dev relabeling before C, the D freeze and gate metric, single use of the held-out set,
and Phase E's scope. Decided in round three (2026-11-03): the ruling 4 reading (the
subtype column decides; conflict flag, count 1 on dev), the doubt-wording scope (stays
on the six; "all 20" is a v6 candidate in the contract doc), the stainless reading
(accepted as frozen), the held-out v5 screen and relabel before the D freeze with a
rescored gate, and the order of the paid tokens. Still open:
1. **Dev relabel** (owner step). Apply the 6 proposed changes and decide the 6
   borderline rows by ruling number into `labels-v5-dev.json`, then rescore, per "Dev
   gold relabel procedure".
2. **The held-out gate's predictions.** The decision names "the saved v2.1 held-out
   predictions"; none were saved. The only saved held-out predictions are v1's (150
   records). Which predictions define the gate, or another gate?
3. **The gate's scorer.** 88.2% came from the v1 all-field structured scorer; the Phase D
   metric is `score_v2` over the 20 facets. Which one "the same scorer" means sets the
   gate number.
4. **Ruling 4 on the v3 side.** The v3 request carries no subtype, so a direct condo
   claim on a conflict case scores as a false positive. Accept that, or decide a Phase B
   mapping rule (which would sit in the D freeze).
5. **Model.** The freeze fixes `claude-sonnet-5-5` with the v2 Sonnet settings (adaptive
   thinking, medium effort). Another model needs a new freeze.
6. **Span quality.** Reported, not gated. Whether it becomes a gate, and at what rate.
7. **Proposed facets and condominium.** See "Proposed new facets (owner decision)" in
   `docs/ENRICHMENT_EXTRACTION_V3.md`.
8. A paid token for each of C and D, and later a separate one for any batch.

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
