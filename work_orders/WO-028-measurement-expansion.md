# WO-028 — Measurement expansion: more SQL-checked facts, a frozen set version, a fourth score

**Driver:** agent (human reviews the PR; no model run is part of this work order)
**Depends on:** WO-020 measurement (PRs #139, #140), WO-008 market analytics, WO-011
recommendations, WO-019 numeric post-check
**Estimated effort:** planning input only, not a commitment

## Objective
A second, separately versioned measurement set whose answers come from independent SQL
for the figures WO-020 left planned (card readings and monthly trend, the opt-in
extended figures, the comparable-sales price check), runnable model-free in CI, with a
fourth score that checks whether each figure stated in a final answer is supported, and
recorded synthetic transcripts that exercise multi-turn and failure behaviour in the
scorer. Set version 1 stays exactly as merged.

## Why
WO-020 checks tool envelopes against SQL truth for counts and five card figures only, and
scores route, arguments and envelope facts. That leaves most of what the market and
price-check tools report unmeasured, and it cannot say anything about the numbers in a
final reply: a right envelope with a wrong sentence, or a right sentence for the wrong
reason, looks the same as a correct answer.

## Inputs
`evals/truth/sql.py`, `evals/measurement.py`, `evals/run.py` (oracle mode, model leg,
report), `evals/cases/measurement.yaml` (set version 1, frozen), `tests/fixtures/
make_synthetic.py` (the committed fixture rows; read through the SQLite copy WO-020
built), CONTRACTS.md (MarketStats, MarketStatsRequest, CompEvidence, RecommendRequest,
the `get_market_stats` outcomes), WO-008 (labels, exclusions, month buckets, minimums),
ADDITIONAL_CAPABILITIES.md (extended figures and their floors), DECISIONS.md (time
windows), `src/idx_agent/email/verify.py` (the existing numeric post-check from WO-019),
docs/EVALUATION.md "Measurement cases".

## In scope
1. **Set version 2.** `evals/cases/measurement_v2.yaml`, category `measurement_v2`,
   check `measurement`, every case carrying `set_version: 2` and an id `meas2-NNN`;
   about 40 questions in our own words, tagged `dev`/`heldout` near 40/60, with its own
   split hash recorded in tests and reports. Version 1's file, cases, splits and hash
   (`d6c38c15…`) do not change; a test pins the file's bytes.
2. **Independent truth for new fact kinds,** hand-written SQL in `evals/truth/sql.py`
   from the documented definitions only (never copying `src/idx_agent/db/`), portable
   MySQL/SQLite, at most 50 rows per statement, importing nothing from `idx_agent` but
   `idx_agent.safety.columns` (the existing independence test covers the module):
   - card readings `dom_band`, `market_lean`, `sale_to_list_reading` (WO-008 thresholds)
     and the monthly `trend` (counts and 3-sale medians, every touched month);
   - extended figures behind `include_extended`: active inventory for the place and
     subtype, sold count, mean price (5 sales), mean DOM (10 usable), and monthly rows
     (count, partial flag, mean price, mean DOM, price and PPSF MoM/YoY changes on
     complete months);
   - the comparable-sales price check reported by `recommend` (`k: 0`, no index): level,
     comp count, median and middle-half price per sqft, signed whole-percent delta, and
     a verdict band (`above`, `below`, `at`, `insufficient`, `not_checkable`).
   A figure whose documented definition is ambiguous, or disagrees with the tool, is
   stopped: no truth, no case, the disagreement recorded in Status. Neither side is
   changed to make a case pass.
3. **Four separate scores.** Route, arguments, tool-result facts (as WO-020), and
   answer support: every number in a supplied final answer must match an expected fact
   or a tool-envelope value within the precision it is written in; unsupported figures
   are counted, and figures that only the truth supports are counted as `ungrounded`.
   The existing post-check tokenizer is reused, not rewritten. Reported as a separate
   table, never folded into the others.
4. **Recorded synthetic transcripts** in `evals/transcripts/measurement_synthetic.yaml`,
   each labelled `synthetic`, hand-written, never from or to a model: follow-up
   refinement that carries or drops arguments, wrong number in prose with the right
   tool result, right number on the wrong route, an unavailable tool relayed versus
   overclaimed, an extra call, a missing call, a wrong figure in the tool result, a
   price check, extended figures, and a turn with no final answer.
5. **Model-free CI path.** The new cases run in `evals.run --suite ci` oracle mode with
   the golden check (truth versus YAML golden, reported by case id and fact name, no row
   values) inside the existing `pytest -q`, `pytest -q -m db` and
   `evals.run --suite ci --require-database` steps. Reports carry one block per set:
   `measurement` (version 1) and `measurement_v2`, each with set version and split hash.
6. Docs: EVALUATION.md section, evals/README.md usage, this file's Status.

## Out of scope
Any model run (hosted, local or Ollama) and the `local` suite; any change to tools,
skills, prompts, `src/idx_agent/`, fixture rows, `.github/workflows/`, gates or guards;
cases for features not on `main` (WO-023 enrichment access, WO-025 saved feature
searches, WO-027 bounded-analysis routing); docs/STATUS.md and WO-020's Status (owned
elsewhere); LLM judges; wording, completeness or reasoning checks of prose.

## Files expected to change
`evals/cases/measurement_v2.yaml` (new), `evals/transcripts/measurement_synthetic.yaml`
(new), `evals/truth/sql.py`, `evals/measurement.py`, `evals/run.py`,
`tests/test_measurement_v2.py` (new), `tests/test_measurement.py` (filter its runner
check to set version 1), `docs/EVALUATION.md`, `evals/README.md`, this file.

## Interfaces and contracts
No tool signature or domain model changes. Case format: EVALUATION.md "Measurement
cases" plus `set_version`. `measurement.score_transcript` keeps its three-key result;
answer support is `measurement.answer_support` and a separate `support` record key.
`expected_facts(truth, family, args, kinds=None)` keeps version 1 on its original
statements.

## Implementation requirements
1. Version 1's file bytes and split hash are unchanged; version 2 has its own hash.
2. Every version 2 fact is computed by the truth SQL from the committed fixture
   (`python -m evals.measurement --write-goldens --set 2`), never typed.
3. A case asking for an extended figure must set `include_extended: true`, and that
   argument is then scored; otherwise it stays a presentation argument.
4. Answer support is "measured" only when a final answer is supplied; oracle runs and
   the model leg (200-character preview only) report it as not measured.
5. Every transcript is labelled `synthetic`; the loader refuses any other label.

## Safety requirements
Synthetic fixture only; no real rows in cases, transcripts or reports; parameterized
SQL over allowlisted columns, at most 50 rows; no paid or local model call; no edit to
enforcement files; no deletion of tracked files.

## Tests required
Version 2 goldens versus truth on SQLite; version 1 frozen (bytes, count, hash); case
shape refusals; label boundaries; month keys; complete-month comparison rule; envelope
extraction for card, extended and comp facts; argument rule for `include_extended`
and `k`; answer support on right, wrong, rounded, magnitude and message-sourced figures;
every synthetic transcript turn scored as written; per-set report blocks with their
hashes; the existing `db` oracle test runs both sets on the MySQL fixture.

## Acceptance criteria
- `python -m evals.run --suite ci --require-database` passes in CI with both sets.
- At least 40 version 2 cases, about 40/60 dev/held-out, split hash recorded.
- Version 1 unchanged (file bytes, 56 cases, `d6c38c15…`).
- Four scores reported separately; docs state that envelope scoring does not prove
  final prose and that answer support is measured only on supplied transcripts.
- Ambiguous definitions stopped and recorded; CI green; human review of the PR.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
python -m evals.measurement              # both sets: goldens vs truth on SQLite
python -m evals.run --suite ci            # model-free; skips without a database
python -m evals.run --suite ci --category measurement_v2 --require-database  # CI
```

## Deliverables
Set version 2 with truth and goldens, the fourth score, the synthetic transcripts, the
per-set report blocks, and the docs.

## Stop conditions
- A fact's documented definition is ambiguous or disagrees with the tool: stop that kind.
- A question needs rows the fixture does not hold: leave the path unasserted and say so.
- Any wish to tune skills, prompts or tool text against held-out results.

## Later hooks (TODO, not built here)
- WO-023 enrichment access and WO-025 saved feature searches: once merged, feature
  filter counts can join a later set as `search` facts with truth from the effective
  facet store's documented semantics.
- WO-027 bounded-analysis routing: route and argument cases for `bounded_analysis`,
  with figure truth only where its documented worker output allows.
- Model leg: keep the full final reply (not the preview) in the measurement trace so
  answer support can be measured on real model transcripts under their own grant.

## Status
2026-11-03: review fix (agent), model-free; still in review.
- **Main merged:** `origin/main` at `cbad756` (#142, #143, #149, #146) merged into this
  branch as merge commit `c365964` (no rebase). No conflict; #146's `evals/run.py`
  (opt-in analysis tool) and `docs/EVALUATION.md` edits auto-merged.
- **Bug (PR #145 review):** answer support scaled `sale_to_list_ratio` to a percent for
  the SQL truth only. A tool returning 0.998 with an answer saying 99.8% scored
  `ungrounded=1` (and `supported=0` with no truth fact). **Fix:** one function,
  `support_forms`, used for both the truth and the tool results (question, call
  arguments, envelope facts, message text): every number, its magnitude, and a number
  under a `RATIO_FIELDS` key (`sale_to_list_ratio`) also times 100. The precision rule
  (`_supported`, half a unit of the last written place) is unchanged and shared. No other
  field is scaled.
- **Regressions** (`tests/test_measurement_v2.py`, invented figures, synthetic
  envelopes): the repro grounded (recorded and model-shaped envelopes; also supported
  with no truth fact); 99.8% backed only by the truth stays `ungrounded=1` (no call, and
  a call without the ratio); a percent-form tool figure (message "99.8%") grounds; near
  misses (0.997, 0.9974, 0.999, 0.9986 vs "99.8%"; 0.99806 vs "99.80%") stay ungrounded
  and are unsupported without truth; tool-vs-truth parity over nine (ratio, text) pairs;
  a price and a `*_pct` field are never scaled on either side.
- **Fail before / pass after:** tests committed first as `c77873a` (pre-fix code).
  `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
  tests/test_measurement_v2.py -k "ratio or percent or non_ratio"` → before: 7 failed,
  12 passed (`assert support["ungrounded"] == 0` → `assert 1 == 0` for the repro;
  `assert from_tool["supported"] == from_truth["supported"]` → `assert 0 == 1` for
  0.998/99.8%, 0.998/100%, 0.998/99.80%, 0.9975/99.8%, 1.012/101.2%); after the fix:
  19 passed. The truth-only, percent-form, near-miss and non-ratio tests passed before
  too: they guard behavior the fix must keep, not the defect.
- **Frozen sets:** `measurement.yaml` (sha256 `3e9025fd…`, split `d6c38c150259…`),
  `measurement_v2.yaml` (sha256 `42ddabee…`, split `32621eea38c5…`) and the
  synthetic transcripts are byte-identical before and after (checked with
  `shasum -a 256` and `git diff 76e3565`). Every recorded transcript turn's scores
  and support counts were dumped before and after the fix and are identical: no
  transcript states a ratio as a percent, so no expected score changed.
- **Mac verification (after fix):** full suite 4547 passed, 130 skipped (same with
  `IDX_ANALYSIS_IMAGE` exported; container tests skip, no Docker here); offline ci
  eval suite 251 cases: 84 pass, 0 fail, 167 skipped; ruff check and format clean.

2026-11-02: in review (agent), model-free.
- **Set version 2:** `evals/cases/measurement_v2.yaml`, 40 cases: 29 market (17 card
  readings and trend, 12 extended figures) and 11 comps; 16 dev and 24 held-out; split
  hash `32621eea38c5…`. Version 1 untouched: 56 cases, `d6c38c150259…`, file bytes
  pinned by a test.
- **New fact kinds with truth:** `dom_band`, `market_lean`, `sale_to_list_reading`,
  `trend`; `analytics_active_count`, `analytics_sold_count`,
  `analytics_mean_close_price`, `analytics_mean_dom`, `analytics_months`; `comp_level`,
  `comp_count`, `comp_median_ppsf`, `comp_range_low_ppsf`, `comp_range_high_ppsf`,
  `comp_delta_pct`, `comp_verdict` (verdicts above, below, at and insufficient occur).
  The version 1 median-DOM statement now also drops negative days, as WO-008
  requirement 7 says; no fixture row is negative, so no golden moved.
- **Stopped (definition ambiguous or in disagreement; neither side changed):**
  - extended mean price per sqft: the docs say "mean PPSF" without saying whether it is
    the mean of per-sale ratios or total price over total area;
  - extended monthly median PPSF: CONTRACTS.md rounds price-per-sqft medians to whole
    dollars, while the extended monthly rows carry two decimals (the PPSF changes use the
    unrounded median and are kept);
  - `exclusions_applied`: which rule a sale failing several exclusions is counted under
    is not documented;
  - subtype mix: exposed only in the card text, not a structured field.
  Interpretations recorded rather than stopped: active inventory is the active count for
  the same place and subtype (single-family by default), as for a search; comps collapse
  repeated keys over the place sample before the area and bed band (the contract's
  "after every WO-008 exclusion"); the delta uses the unrounded median. No fixture comp
  has an area under 200 sqft, so the price-per-sqft floor's effect on comps is untested.
- **Fixture limits:** no active listing is uncheckable, no city-level check is
  sufficient after widening, and the coverage holds no year-over-year pair; those paths
  have no case with a non-empty answer.
- **Fourth score:** `answer_support` reuses `idx_agent.email.verify`'s tokenizer;
  separate `answer_support` table in each report block; not measured in oracle runs or
  the model leg. 18 synthetic transcripts (20 turns) cover the required scenarios and
  two known limits (a true figure overclaimed after a failed call passes support and is
  flagged `ungrounded`; a reversed direction word passes because words are not checked).
- **Verification:** both sets' goldens equal the truth on the SQLite fixture. Against the
  local MySQL fixture (a stale copy: 52 sold rows, no San Gabriel group, versus 117 in
  `synthetic.sql`), every one of the 96 cases' tool envelopes matched the truth SQL on
  the same database; the 20 golden differences there are all San Gabriel / 91775 /
  91776 rows that copy lacks. CI loads the current fixture.
