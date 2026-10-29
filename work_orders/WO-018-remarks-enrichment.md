# WO-018 — Public-remarks enrichment

User direction recorded 2026-10-25: begin the combined plans in the revised order.
Remarks enrichment comes before the remaining WO-017 executor work. WO-017 Phase A
is retained. Activate this implementation only after the current WO-015 closeout
lands; it does not require waiting for human-dependent live acceptance.

## Goal

Create a versioned, inspectable property-fact enrichment path from public remarks,
so later search, cards, reports and alerts can use supported facts rather than
uncontrolled text guesses. Missing/negated/uncertain statements cannot become
positive hard constraints. This WO does not promise a fully labeled extraction
model, a production accuracy number or new search filters from a schema alone.

## Phase A: key-free foundation

Own: src/idx_agent/enrichment/__init__.py, vocabulary.py, normalize.py;
src/idx_agent/domain/enrichment.py (boundary models stay in domain per repo rules);
tests/test_enrichment_vocabulary.py and test_enrichment_normalize.py; this WO,
docs/ENRICHMENT_DESIGN.md, the enrichment section in docs/CONTRACTS.md, a README
navigation link and an append-only evidence entry. Use standard library and existing Pydantic only.
Implement eight fixed facet groups and bounded versioned normalization, with
invented adversarial examples. Do not load real remarks, infer contact facts,
re-embed, call providers, change the live index, add SQL columns, register a tool
or modify hard search filters. Normalized text is still untrusted text.

Abbreviation expansion must preserve negation, uncertainty, punctuation and numbers.
Only known unambiguous contexts expand. Record whether text changed and the
normalizer version; retain original input outside public fixtures when an approved
future ingestion job runs. Bounded input fails closed rather than silently truncates.
The normalizer is not a contact redactor or a semantic extractor.

## Later phases and dependencies

B: define annotation rules, provenance spans, polarity/status, dev/test split and
reviewed synthetic cases. Human labeling of a permissioned real sample is required
before reporting real extraction quality. Check claims against each feed's field
definitions; do not compare bathroom counts between the tables.
C: extraction, deal-signal candidates, summaries and discrepancy checks, with
per-facet/negation/uncertainty metrics and error review. Choose deterministic/model
paths from evidence; model calls require a separate command-bound budget.
D: explicit schema/SQL/index/card/report integration for accepted facets, then a
versioned rebuild with preserved previous index and live acceptance. No deployment
before query/index normalization compatibility is demonstrated.

## Acceptance for Phase A

- All eight groups and allowed values have unique identifiers; unknown facets fail.
- Pure bounded normalization is deterministic and idempotent, preserves numbers and
  negation, resists partial-word/ambiguous expansions, and carries a stable version.
- Tests cover empty/oversize/non-string input, mixed casing, punctuation and examples
  outside the intended domain. No fabricated precision/recall or live-data claim.
- Existing retrieval/query behavior is unchanged; focused tests, lint, content gates
  and CI pass. Self-review the diff and update this Status with measured evidence.

## Stop conditions

New dependency/service, a protected enforcement edit, private source access, paid
extraction/re-embedding, unresolved labels, unsupported field semantics, or a change
to the existing hard-filter contract. Record the decision needed, not a fallback
that silently weakens evidence or privacy rules.

## Status

The user paused capabilities on 2026-10-25, then directed resumption after the
WO-019 model-side change merged in PR #102. Baseline items that remain open are
not implied complete. The merged enrichment foundation remains unused at runtime.

2026-10-25: Phase A implemented on its isolated branch after WO-015 closeout
merged. Boundary models live in domain/ to follow the existing repository convention.
The first 30 foundation/length tests passed (0.57 s); a wider run covering the new
boundary and existing index/query/RAG behavior passed 186 tests (1.37 s). Ruff
passed after formatting. CI/integration is still required before this phase lands.
No real remarks, provider, SQL query or embedding job was used; no runtime is wired.
The overall WO remains open through labeling, extraction, integration and acceptance.
Next: an approved annotation specification and dev/test sample, then extraction.
No accuracy or new user-facing filter is claimed from this preparation alone.

2026-10-26: Phase B draft started with a proposed annotation specification and
26 wholly invented cases split evenly into development and holdout sets. The
examples cover all eight facet groups, independent polarity and time, original
Unicode offsets, negation, ambiguity and contradictions. Thirty-two focused tests
passed with no provider, database or real remarks. The specification and real-data
sampling procedure still require human review; no extraction accuracy is claimed.

Independent review of the synthetic examples found one person-versus-style
ambiguity and one proposal/current-negation ambiguity. The style example now names
a home, and the proposed ADU has separate planned affirmation and current
negation with explicit guidance. The expanded annotation/foundation/fixture
suite passed 53 tests; this validates the fixtures, not an extractor.

2026-10-27: the draft now includes a bounded synthetic annotation model and
pure exact-match counts, with per-facet and polarity breakdowns. A source marker
is self-declared and is not provenance enforcement. The helpers do not extract
facts or access a database, provider, session or runtime index. Independent
review found no concrete defects; 58 focused tests passed. Real-data labels,
reviewed sampling, and extraction-quality evidence remain open.

The expanded annotation, index, query and retrieval regression passed 214 tests
with MYSQL_HOST empty. These are synthetic/model-free checks; no live data, feed
sampling, model call or runtime integration was involved.

Synthetic scoring now also aggregates one split across complete matching case
sets, preserving per-facet and polarity counts. It rejects missing, extra,
duplicate and cross-split cases. Independent review found no concrete defect;
the expanded synthetic/index/query/retrieval suite passed 216 tests. This does
not authorize or measure real-data extraction.

A reviewable pilot proposal now lists the source, access, in-place review,
splitting, labeling and low-sample decisions needed before real remarks can be
used. It performs no sampling and grants no access or export authority.

A synthetic-only split planner demonstrates a 50-input-row cap, grouping before
splitting, reproducible seed ordering, and a maximum of 30 invented groups.
Independent review found no concrete defect; the expanded regression passed 220
tests. It cannot select real listings or certify source provenance.

### 2026-10-27 — Synthetic-only extractor experiment

On a separate branch stacked on the annotation draft, a deliberately narrow rule
prototype reads invented text in memory and returns candidate spans only. It is
not connected to the live agent or authorized for real remarks. It emits only
explicit affirmative/current candidates and abstains on a fixed set of cues;
that list is incomplete and does not enforce privacy or factual correctness.
Independent review found and corrected cross-clause retractions, ambiguous feature
suffixes, and preference-versus-property style examples. The reproducible check
uses only the visible development fixture: 5 exact matches out of 5 candidates
against 18 labeled mentions in 13 cases. These rules were developed with that
fixture; no held-out or real-data accuracy is claimed. The broader synthetic,
annotation, sampling, index, query and retrieval suite passed 244 tests. No real
remarks, model/provider call, database query, index rebuild or deployment occurred.

The synthetic experiment was extended with a few fully bounded negated, uncertain,
planned and historical templates; unfamiliar cue-bearing input still abstains.
Independent review found no concrete issue in the bounded cases. The visible
development set now yields 12 exact matches from 12 predictions against 18 labels;
the rules were developed using that set, and no held-out or real-data accuracy is
claimed. The broader offline regression passed 257 tests. No real data or provider
was used.

An unconnected alignment helper maps normalized spans back to original source
intervals, refusing partial abbreviation expansions. Synthetic tests cover
Unicode, repeated replacements, numeric backreferences and cross-expansion spans.
Independent review found no concrete offset or privacy defect; per-span mapping
currently scans the bounded output and needs performance evidence before bulk use.
The expanded offline suite passed 269 checks. No index or production normalizer
behavior changed.

The synthetic extractor now uses the alignment helper for an explicit washer/
dryer claim, returning the original `W/D` span after normalization. Negative and
unrelated-subject examples still abstain; generic A/C is not promoted to central
air. Independent review found no concrete defect in the narrow path. The wider
offline suite passed 273 checks; the development count remains 12 of 18 labels.
No production extraction, real-data accuracy or index compatibility is implied.

2026-10-27: The human approved the annotation specification with numeric-total
rules and eight-group examples. The private labeling plan is 250 seeded,
subtype-stratified remarks (100 dev, 150 test), owner-labeled locally. Only
aggregate scores and counts leave data/enrichment/. Search integration requires
at least 85% F1 on structured facets on the held-out test set. Paid extraction
requires a separate token; no real-data scoring has occurred.

A local-only labeling viewer prototype is under development. It reads an owner-
selected sample JSON and writes a separately selected labels JSON, with no server,
model or network connection. It validates original Unicode code-point spans and
basic facet/numeric fields. The browser cannot prove the chosen file paths are in
`data/enrichment/`; the owner must choose the private directory. Synthetic tests
are not a real-data sample or evidence of labeling quality.

The viewer draft now has local styling and retains selected source spans while
fields are filled; changes require an explicit file save. A local headless Chrome
load and synthetic interaction smoke test passed. A pure aggregate scorer accepts
the viewer's annotation shape, rejects mismatched/incomplete datasets and returns
per-facet and numeric counts without source text. It has not been run on real
remarks. Exact span matching is a strict metric, and the meaning and aggregation
of the 85% structured-facet gate remain to be frozen before the held-out test.

The draft aggregate-only runner reads fixed private filenames and verifies 100
dev or 150 test cases and complete labels; tests use invented temporary data.
It produces no prediction file, sends nothing to a model and does not choose the
held-out gate. The viewer and runner still need interactive acceptance.

A pure, seeded subtype allocation helper now demonstrates the requested 100/150
split on invented group identifiers, with group deduplication and deterministic
largest-remainder allocation. It performs no database or file access. Access to
an eligible candidate population and compliant creation of the local 250-remark
sample remain unresolved under the existing query and bulk-export invariants.

A headless Chrome synthetic interaction exercised selecting Unicode text, adding
an annotation, navigating and saving via a stubbed picker. The synthetic desktop
layout was visually inspected. A real operating-system save dialog and private
sample have not been exercised. Scoring now includes unsupported allowed facets
with undefined precision/recall/F1 instead of silently omitting them.

The owner specified `rets_property.L_Remarks`, the existing SELECT-only embedding
reader in pages of at most 50, a 200-character minimum, and a private 250-row
JSONL containing only key, subtype and redacted remark. A separate private split
manifest supports the approved 100/150 labeling split. The JSONL viewer and
aggregate scorer passed invented-data checks; the live sample is not asserted
complete until the reader reports its count and fixed seed.

2026-10-27: the owner-authorized local database sample completed with 250 remarks,
fixed seed 20261027 and a 100/150 split. The redacted JSONL and split manifest
are private and owner-readable only. Structural checks passed; keys and remarks
were not logged. Human labeling and model evaluation have not yet occurred.

The draft synthetic extractor also has a narrow numeric experiment for the
visible invented counts-and-amounts examples. Those patterns were written against
those examples and are not evaluated or authorized for real remarks. The focused
synthetic and docstring tests passed; private labeling and held-out scoring remain.

2026-10-27: the owner reports all 250 labels complete and individually reviewed;
Claude Code (Opus) drafted suggestions and the owner corrected 24 cases. The
Sonnet extractor under test shares a model family, a possible source of bias.
The owner-approved pre-labeling disclosure does not authorize extraction. No
real-data scoring has occurred. The frozen evaluation definition is in
`docs/ENRICHMENT_SCORING_V1.md`; test remains held out until extractor freeze.

The dev-only Sonnet driver and scorer are prepared with synthetic provider stubs;
they have not read or sent the private sample. The driver requires explicit
provider disclosure and an exact-command paid token, spends at most 100 calls,
stops on the first error and writes only new private output files. The owner has
not yet approved extraction-time disclosure; no real-data scoring occurred.

An aggregate-only local validation confirmed 250 reviewed cases (100 dev, 150
test), matching dataset IDs and exact source spans, with 1,293 categorical and
378 numeric annotations. This checks file structure and offsets, not independent
semantic correctness. No extraction or real-data scoring was performed.

2026-10-27: the first separately authorized dev extraction stopped after one
request. The response reported 3,312 input and 1,309 output tokens. The old driver
had discarded the response and emitted no failure detail; there is no stored
response to diagnose or replay, and no real-data score was computed. Recovery
adds schema-constrained tool input, quote-to-source alignment and sanitized
field/rule diagnostics, with owner-only raw-response files for future failures.
Malformed annotations become misses and processing continues; API/auth failures
and local privacy/output failures stop. Synthetic replay checks do not replace
replay of the unavailable original response. No new provider call was made.

The owner selected automatic strict tool use and directed an explicit instruction
to always call the extraction tool. Completed and interrupted run summaries now
include the no-call count; no new paid request was made during offline testing.

The owner requested dev-only rescoring using categorical case/facet overlap and
exact numeric spans, while retaining exact results. The hybrid micro F1 on the
existing dev predictions is 87.1% (exact-span micro F1 47.7%). This is not a test
gate result; overlap ignores polarity and temporality. A dev-only aggregate
wording analysis and per-facet report are in `docs/ENRICHMENT_OVERLAP_DEV.md`;
five owner-viewable uncertain examples remain private. Generic shopping is now
explicitly excluded from the grocery facet. No new provider calls or held-out
scoring occurred.

The owner froze polarity-aware categorical overlap plus exact numeric-value
matching for the 85% held-out micro-F1 gate; uncertain stays in the gate and
repeat mentions are counted by case/facet/polarity. Existing dev predictions
rescore to 88.5% under this metric. This does not establish test performance.

The owner directed dev-only office and grocery prompt refinements, a compact
fixed prefix and prompt caching before one further 100-request dev run. The
fixed tool-and-system prefix measured 10,223 bytes before and 4,425 bytes after;
bytes are not token counts. The runner now separates uncached, cache-write,
cache-read and total input tokens and uses new run-specific private output
files. Synthetic tests passed; the revised prompt has not been sent to a provider.

2026-10-27: the revised-prompt dev2 run stopped on its third request after two
completed responses. Its driver retained those predictions only in memory; no
completed dev2 predictions or checkpoint were written, so they cannot be used
for a 98-case resume. No test extraction or scoring occurred. The replacement
runner retries connection failures, timeouts, HTTP 429 and 5xx at most three
attempts with exponential backoff, accounting for each attempt through the paid
gate. It stops on authentication and other HTTP errors. Private append-only
per-response checkpoints permit a subsequent interrupted run to resume only
when its model, prompt, schema and dev inputs match. Synthetic checks do not
establish a real-data result. A new run requires separate owner approval and its
own exact-command token; no additional provider calls have been made.
The run summary counts retries by error class for the current invocation; each
retry is counted only after the paid gate accepts its call.

2026-10-27 dev3: the approved 100-remark dev run completed in 100 requests,
with zero retries and zero missing tool calls. Seven responses had validation
misses. Input usage averaged 2,378.6 tokens per remark, above the owner's 2,000
target; output averaged 450.36. A variable-shadowing defect wrote incorrect
case identifiers in the original predictions. The 100 private response
checkpoints enabled offline reconstruction into a separate private file without
more provider calls. Under the frozen metric, reconstructed dev micro F1 is
89.3%; this is not the held-out gate. Aggregate per-facet and polarity results
are in `docs/ENRICHMENT_DEV3_RESULTS.md`. The identifier defect is fixed with a
regression assertion. The held-out split remains unscored and requires separate
approval; prompt cost optimization remains open.

2026-10-28 owner decision: the input target is uncached provider input below
2,000 tokens per remark. Dev3 used 54,260 uncached input tokens / 100 = 542.6,
so it meets that target; total input including cache creation and reads was
2,378.6 per remark and remains reported separately. The 89.3% dev result is
accepted for proceeding; it does not establish the held-out gate.

Frozen before held-out extraction (SHA-256, raw file bytes except the canonical
schema):

- Model ID: `claude-sonnet-5-5`.
- Prompt `docs/ENRICHMENT_EXTRACTION_PROMPT.md`: `1d23e9ecd81d8ede5304d8a7ea9aadaa81850a77ff2eceece80c40b6b835fcd4`.
- Tool schema, JSON with sorted keys, compact separators and UTF-8: `feb5deb09af283f5d049536466a0b750323250a3b1626e6242fa6095363be779`.
- Extractor `src/idx_agent/enrichment/dev_extraction.py`: `e81900c2c707999d3b45f2fdbbd719b14912665f395cebe611fdc98f6e9ae32a`.
- Request builder `scripts/extract_enrichment_dev.py`: `ae4852c84a82b28473b37172087fc2f57b8f42887e689b7be79bdc40b298c089`.
- Vocabulary `src/idx_agent/enrichment/vocabulary.py`: `0f5f83a1c9291a842414364112e783d3ca757b86fe51fc8cae33a84ec2ebe1a5`.
- Scorer version: `ENRICHMENT_SCORING_V1`, polarity-aware categorical overlap
  and exact numeric value; `private_scoring.py` SHA-256 `21d429d637e75ddaabdb20f9ae1a15a5855c93f97f65ee9159ac6752242df30b`,
  scorer driver SHA-256 `ed8a0b7495941923a23a3b0e0cd9296bd28bd7a39b63bbee03f0d91aba95ab3a`.

The owner authorized one held-out extraction of 150 test remarks with its own
paid token, ceiling 450 calls. Only individual categorical facets with held-out
F1 of at least 80% may feed search and cards, subject to the existing 85%
overall structured micro-F1 gate. Unsupported facets do not qualify. No held-out
request or score has been made at freeze time.

2026-10-28: the approved held-out extraction completed all 150 remarks in 150
requests, with zero retries and zero missing tool calls. Nine remarks had 15
validation diagnostics. Frozen structured micro F1 was 88.2%, passing the 85%
overall gate. Of 47 categorical facets, 33 meet the owner's 80% per-facet rule,
11 fall below it, and three have no held-out gold support and are excluded.
Office scored 73.1% and is excluded. The aggregate-only report, including every
facet's precision, recall, F1 and support, is `docs/ENRICHMENT_HELDOUT_RESULTS.md`.
Uncached input averaged 525.06 tokens per remark, total input including cache
2,361.06, and output 427.12. Some passing facets have very small support; the
threshold alone does not establish robust generalization. No search or card
integration was made in this evaluation step. No prompt, rules or scoring
changes were made from test data.

2026-10-28 owner update: eligibility for downstream integration now requires
held-out F1 >= 80% **and** at least 10 gold examples. The 20 qualifying facets
are: clubhouse (17), community pool (32), fitness center (14), gated community
(16), ADU (14), garage (70), patio (41), pool (20), hardwood (17), solar (21),
stainless appliances (26), mountain view (16), near grocery (13), near transit
(13), water view (14), condominium (18), bonus room (19), open plan (38), single
level (17), and walk-in closet (35). The other 13 previously qualifying facets
fall below the support minimum. As-is (2), back on market (2), and price reduction
(6) remain ineligible as alert triggers. `WO-021` is a draft for review only.

The full active-remarks batch runner is prepared, not run. It uses the frozen
model/request/parser, the existing SELECT-only active keyset reader in pages of
at most 50, and the embedder's full-text redaction. It writes an owner-only
SQLite facet table under `data/enrichment/full/`; per-record commits preserve
successful responses, with a durable checkpoint every 50. A resume validates the
completed prefix against the current source before sending another request, and
completion audits the entire source against the stored key/text digests and the
active timestamp watermark. A changing source stops the job; the maximum
modification timestamp is not a transactional snapshot, so changes that evade
both the watermark and the source audit cannot be ruled out. An interruption
after a provider response but before its commit can repeat that one paid call.
Raw error responses stay private; routine output is aggregate only. Each
invocation needs its own exact-command paid token, and a large build may require
multiple tokens because both call ceilings and token duration are bounded. The
owner will decide on a token after checking provider-console costs. No live batch
or data integration has been performed.

2026-10-28: the owner directed a 2,000-remark first tranche, at most 6,000
provider attempts, followed by a pause for validation-miss and provider-console
cost review. `--stop-after 2000` enforces the cumulative cap and preserves the
private table for a separately authorized continuation. Validation-miss rate
counts remarks with parser diagnostics; it does not measure semantic recall
without independent labels. A 40-remark keyword-selected, separately labeled
supplement for the three deal signals was also authorized; it excludes the
original 250 and remains private. Keyword selection is enriched, not a random
held-out estimate, and does not by itself change eligibility.

The authorized supplementary sample was created locally: 40 unique cases,
selected from keyword buckets as-is 14, back-on-market 13, price-reduction 13;
seed `deal-signals-20261028-v1`. All 40 are disjoint from the original 250,
viewer-compatible, redacted, and owner-only. Bucket membership is a selection
criterion, not a gold label. Owner labeling remains pending; the supplementary
sample is not a representative held-out estimate.

2026-10-28 cost decision: stop v1 full extraction and prepare a 20-facet v2.
The interrupted run retained 324 committed results, with 13 rows containing a
validation diagnostic. The owner directed retaining and tagging them v1, with
reuse deferred until the v2 model comparison; one in-flight call may have been
billed. No v1 restart or full-pass continuation is authorized. The owner
reported an Oct 28 provider-console total of $2.73 across dev1, dev2 partial,
dev3 and held-out; this is an owner-reported aggregate, not a measured full-run
cost.

V2 is scoped only to the 20 qualifying facets. Its draft prompt SHA-256 is
`e1ccb614145cca19f05b403d22a214ba597816049dc192aad057f9e60d25ba24`; its
canonical sorted-key compact-JSON tool schema SHA-256 is
`036155fd435c9ce61891a917252d8f68ee8a02fd9124e3bcf0d689e00cf47a03`.
The existing polarity-aware overlap scorer applies to the 20 facets only;
numeric fields and deal signals are outside the v2 comparison. These draft
hashes require final review and freeze before the held-out comparison.

The owner authorized a single 600-call-ceiling dev comparison of 100 remarks
per model, subject to a separate exact-command paid token, then a Haiku
held-out confirmation only if dev micro F1 is within three percentage points
of Sonnet. Held-out scoring must use the unchanged selected v2 contract, and
per-facet held-out F1 >= 80% and >= 10 gold examples remain required. The
separate 40-case deal-signal sample is not v2 training or held-out evaluation.
The 2,000-record bulk tranche must use Message Batches, followed by cost and
miss review before the remainder; no Message Batches submission is authorized
until the model decision and a separate paid token.

V2 work in progress: the two-model dev command uses the frozen v1 retry gate,
separate per-model usage and diagnostics, the 20-facet scorer, and a single
600-call token. The Haiku confirmation runner requires the dev criterion, its
own token and matching prompt/schema/implementation hashes. The batch path
plans up to 1,000 opaque-ID messages per request, records an uncertain state
before each non-idempotent submission, and reconciles unordered results before
committing private facets. Failed, canceled, expired, missing or duplicate
batch results stop for operator review rather than being silently dropped or
resubmitted. Continuation needs a separate explicit approval and paid token.
V1 reuse must be decided separately; the current batch command requires an
explicit decision not to reuse and does not alter the v1 table. Batch status
and result retrieval also require a command-bound token under repository rules.
Anthropic documents that batches may take up to 24 hours and cache hits are
best-effort: https://platform.claude.com/docs/en/build-with-claude/batch-processing.
All provider, dev, held-out and bulk behavior remains unproven until the
separately authorized runs. No v2 provider calls were made while building.

Review follow-up: the first-tranche 2,000-row guard now applies only when
staging a new store. A synthetic CLI regression covers retrying a failed item
after extension to 4,000 rows; it does not make provider calls.

Review correction: checking only first-time staging allowed a short initial
tranche to bypass the 2,000-row requirement on restart. Every submission now
requires at least 2,000 staged rows; a synthetic two-invocation regression
proves no requests are sent from a 1,500-row initial store. Later-tranche
retry coverage remains in place. No provider calls were made.

V2.1 owner decision: Haiku thinking is disabled; quote length at most 80 is
instructed in the prompt and enforced locally as a validation miss. Anthropic
strict tool schemas do not support `maxLength`, so the v2.1 schema retains the
v2 schema without a provider-side length constraint. Frozen SHA-256: prompt
`7548bfb1590249ef6015ffe62b947e209d84f5a986b9d9f995b0ccb2caa4e1de`,
canonical schema `036155fd435c9ce61891a917252d8f68ee8a02fd9124e3bcf0d689e00cf47a03`,
implementation `62d74e5c4772e74f80f0f1bfc329ff41620d12ec85ba087fb9b64104988e383c`,
dev driver `45a366b5d0385accbd19d8225b519d8279879dfe7cb873ddcae71c5a053e32b7`.
One Haiku dev run of 100 remarks requires its own 300-call token. Haiku is
eligible for held-out confirmation only if dev F1 is no more than three points
below Sonnet's 94.69% and output averages strictly below 400 tokens per remark;
otherwise the owner selected Sonnet and reuse of the 324 v1 records. No v2.1
provider calls or held-out scoring were made during implementation.

Review follow-up: the pinned external freeze manifest
`docs/ENRICHMENT_V21_FREEZE.json` (SHA-256
`b59c6690fe135b52aa1428d12b2a71480e4387589758e9c8433512aebae7b907`)
now verifies v2.1 and v2 implementations, the original parser/scorer and
request dependencies, prompt and schema before starting a paid run. The v2
implementation SHA-256 is
`5762b2b3fac28e42b19af56f5ebb35c7cfdd56e50ded72a1eacbc6dca58d6d7d`.
This supersedes the earlier driver hash; the updated driver SHA-256 is
`5fe60c63c60088fa3952806f9998321bb043f83cd4e098f9f07ec79093c181e3`.
Synthetic mutations of either v2.1 or v2 stop before the token is consumed.

V2.1 dev decision: the authorized 100-remark Haiku run produced 89.66% micro
F1, 5.03 points below Sonnet's 94.69%, and 652.28 output tokens per remark.
Both owner thresholds failed. Thinking tokens were zero; there were 13 remarks
with validation misses, no missing tool calls, and no retries. The owner-selected
fallback is Sonnet bulk with reuse of the 324 v1 rows. Aggregate per-facet
results are in `docs/ENRICHMENT_V21_DEV_RESULTS.md`; cost remains the provider
console's figure. No held-out evaluation or bulk call followed this decision.

The Sonnet batch path now checks the frozen v2.1 dev decision instead of the
earlier v2-only Haiku comparison. It requires explicitly selected v1 reuse,
reads the 324 tagged v1 results without modifying that table, verifies each
prepared-remark digest against the current source, retains only the 20 v2
facets, and marks their v1 provenance. Reused rows are excluded from batch
requests; usage and validation counts are reported separately by origin. Any
missing v1 row or source mismatch stops before submission. This is key-free
implementation and synthetic validation; no bulk batch was submitted.

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
