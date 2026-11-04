# WO-018 evidence carried from unmerged PRs

Historical record, added by WO-022 on 2026-11-02. Four WO-018 evidence-recording PRs
(#116, #126, #129, #132) were opened between 2026-10-27 and 2026-10-30 and never merged;
each now conflicts with main. WO-022 compared every fact in them with main
(`work_orders/WO-018-remarks-enrichment.md`, `docs/ENRICHMENT_*.md`,
`docs/EVIDENCE_LOG.md` and `git log -S` over main's history). Facts that main did not
already hold are carried here, or in the two result files named below, **verbatim** and
under their original dates. Nothing in them was recomputed, corrected or re-scored.

Rules for reading this file:
- Each quoted block is the PR's text exactly as written, after an attribution line.
- Later evidence on main takes precedence. Each section says what superseded its figures;
  the figures themselves are left as recorded.
- The PRs and their branches are left untouched and remain the original record. This file
  is a copy for main's history, not a replacement. Their disposition is in WO-022.
- Only aggregate counts appear. No remarks, listing keys, labels or predictions are
  recorded here or in the PRs.

| PR | Branch, head | Originally recorded | Unique content carried | Already on main |
|---|---|---|---|---|
| #116 (draft) | `wo-018-dev-evidence`, `aafb442` | 2026-10-27 | First dev run record (100 requests, 424,460 input and 43,522 output tokens, 11 diagnostics in 10 remarks); exact-span precision 47.5%, recall 47.9%; categorical 37.8%, numeric 84.6%, macro 40.0% over 47 classes; per-facet exact-span precision and recall; exact-span polarity table; ten largest disagreement buckets; its evidence-log line | Exact-span micro F1 47.7% and per-facet exact-span gold, predicted and F1 (`ENRICHMENT_OVERLAP_DEV.md`, EVIDENCE_LOG 2026-10-27) |
| #126 | `wo-018-v2-dev-results`, `11735ad` | 2026-10-28 | Haiku v2 dev micro F1 93.85% and per-facet scores; the 0.84-point gap; per-model token, validation-miss, missing-call and retry rows | Sonnet v2 94.69% and its per-facet column (`ENRICHMENT_V21_DEV_RESULTS.md`, WO-018 Status) |
| #129 | `wo-018-tranche1-results`, `5576b70` | 2026-10-29 | The first 2,000-row tranche: two batches (1,000 and 676 new requests), 1,676 successful, diagnostics 11 of 1,676 new (0.66%) and 24 of 2,000 (1.2%), tranche token usage | 324 reused v1 rows with 13 diagnostics (WO-018 Status, 2026-10-28 cost decision) |
| #132 | `wo-018-extraction-closeout`, `669a9f3` | 2026-10-29 | The dated completion statement; 471 diagnostic remarks as 0.858% of results; the post-8,000 token-based estimate $89.66469020 | 54,888 results, 324 v1 / 54,564 v2 provenance, all usage totals and the $130.34 / $40.68 / $89.66 console figures (WO-018 Status source-audit paragraph, commit `21ac352`, 2026-10-30) |

## PR #116: first development extraction (2026-10-27)

The full aggregate report from this PR is carried verbatim as
`docs/ENRICHMENT_DEV_RESULTS.md`, with its own attribution header.

**Superseded.** "Frozen exact-span micro F1" refers to the exact-span scorer in force
that day. Later on 2026-10-27 the owner froze polarity-aware categorical overlap plus
exact numeric values as the metric; the same predictions rescore to 88.5%
(`ENRICHMENT_OVERLAP_DEV.md`). Dev3 (89.3%) and the held-out run (88.2%, gate passed)
followed. The owner later reported an aggregate console total of $2.73 for dev1, the dev2
partial, dev3 and held-out together (WO-018 Status, 2026-10-28); no dev1-only cost exists.

**Clarification, 2026-11-04 (owner decision, WO-034).** 88.2% is v1's historical
all-field held-out result (structured micro F1 over 47 facets and four numeric fields)
against the original frozen gold `data/enrichment/labels.json`, SHA-256
`6aab5483839e534615e753d100a66acddd9b7a121f50c03e2ba85f4f250ebde7`. Production v2, the
contract the bulk store was extracted with, has no held-out score: v2 was evaluated on
dev only. Facet eligibility comes from v1's held-out results. The earlier text is
unchanged (`work_orders/WO-034-extraction-v3.md`).

Carried from PR #116, originally recorded 2026-10-27 (WO-018 Status paragraph):

2026-10-27: the separately approved dev-only run completed 100 requests, with
424,460 input and 43,522 output tokens and zero no-tool-call responses. Eleven
annotation diagnostics occurred in ten remarks. Frozen exact-span micro F1 was
47.7% on dev (numeric 84.6%, categorical 37.8%); this is not the 150-case test.
The detailed aggregate report is `docs/ENRICHMENT_DEV_RESULTS.md`. The owner-
reviewed labels were initially drafted by another model in the same family as
Sonnet, a possible shared-model bias. Provider-console cost remains unverified.
No test data was scored and no extraction prompt or rule was changed using test.

Carried from PR #116, originally recorded 2026-10-27 (EVIDENCE_LOG entry; also appended
to `docs/EVIDENCE_LOG.md` with this attribution):

- 2026-10-27, WO-018: authorized dev-only extraction completed 100 requests,
  424,460 input and 43,522 output tokens, zero no-tool-call responses; 11
  diagnostics across 10 remarks. Frozen exact-span structured micro F1 on dev
  was 47.7%; the held-out test was not scored. Only aggregate evidence is
  recorded; provider-console cost remains unverified.

## PR #126: v2 development comparison (2026-10-28)

The PR's aggregate report is carried verbatim as `docs/ENRICHMENT_V2_DEV_RESULTS.md`,
with its own attribution header.

**Superseded.** The statements that Haiku "meets the three-point dev rule" and that v1
reuse "remains undecided" were overtaken later on 2026-10-28 by the owner's v2.1
decision (WO-018 Status; commits `06ef6d2` and `bd79a26`). Haiku became eligible for
held-out confirmation only with dev F1 within three points of Sonnet **and** output
strictly below 400 tokens per remark. The Haiku v2.1 run scored 89.66% with 652.28
output tokens per remark, missing both, and the owner selected Sonnet for bulk
extraction with reuse of the 324 v1 records. No Haiku held-out confirmation ran.

Carried from PR #126, originally recorded 2026-10-28 (WO-018 Status paragraph):

2026-10-28: the approved 200-request v2 dev comparison completed, 100 per model,
with no retries or missing tool calls. Sonnet scored 94.69% and Haiku 93.85%
micro F1 on the 20 facets; Haiku is 0.84 percentage points lower and meets the
three-point dev rule. Sonnet had zero validation-miss remarks; Haiku had one.
Aggregate per-facet scores and token categories are recorded in
`docs/ENRICHMENT_V2_DEV_RESULTS.md`. Provider-console costs and separately
authorized Haiku held-out confirmation remain pending. The 324 v1 records are
preserved; their reuse remains undecided.

## PR #129: first 2,000-row tranche (2026-10-29)

**Superseded for totals.** These are the first tranche's figures only. The completed
extraction's totals (54,888 results, 471 diagnostic remarks, cumulative usage and the
console figures) are in WO-018 Status and in the PR #132 section below. The tranche
figures are not to be added to those totals; the completion totals already cover every
result.

Carried from PR #129, originally recorded 2026-10-29 (WO-018 Status paragraph):

2026-10-29: the approved first 2,000-row tranche was submitted in two Sonnet
Message Batches (1,000 and 676 new requests) with 324 previously approved v1
rows reused. Both batches ended with all 1,676 requests successful; no errored,
canceled or expired requests. Collection checked the source and verified the
tranche. Eleven of 1,676 new v2 rows had validation diagnostics (0.66%); 13 of
324 reused v1 rows had diagnostics. Across the 2,000 rows, 24 had diagnostics
(1.2%). These are parser-validation miss rates, not semantic recall. New v2
usage: 820,062 uncached input, 4,404 cache-write, 1,840,872 cache-read, and
392,248 output tokens. No provider-console cost was available to the agent.
The remaining bulk work stays paused for the owner's cost/miss review and
separate approval and token.

## PR #132: completed extraction (2026-10-29)

**Mostly already on main.** WO-018's source-audit paragraph (added 2026-10-30, commit
`21ac352`) records the same 54,888 results, 324 v1 and 54,564 v2 provenance, the same
usage totals and the same console figures, and states that the console delta is neither
a token-derived estimate nor an extraction-only bill. Unique to this PR: the dated
completion statement, the 0.858% rate (471 of 54,888), and the token-based estimate of
$89.66469020. The estimate and the console delta are different measures that happen to
round to the same dollars; neither is a measured extraction cost. The 471 diagnostic
remarks later received private dispositions in the diagnostic review (WO-018 Status,
2026-10-30 onward).

Carried from PR #132, originally recorded 2026-10-29 (WO-018 Status paragraph):

2026-10-29 completion: the bulk store contains 54,888 inputs and 54,888
results; the full source and hash verification passed. All provider batches
completed with no recorded failed items. Provenance is 324 reused v1 results
and 54,564 v2 results. Across all results, 471 remarks (0.858%) had parser
validation diagnostics; these diagnostics do not measure semantic accuracy.
Recorded usage: 29,096,292 uncached input, 50,280 cache-write input,
60,619,548 cache-read input, and 14,390,947 output tokens. The owner reported
the monthly console total as $130.34, versus the $40.68 baseline: a $89.66
delta for that console scope, which can include other activity. The post-8,000
token-based estimate was $89.66469020. No integration is authorized by this
completion record.
