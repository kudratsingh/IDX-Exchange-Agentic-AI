# WO-019 — Base-system acceptance on Sonnet / medium

Authorized 2026-10-25: the user asked to evaluate the existing assistant completely
before proceeding with the capability roadmap. New capabilities are paused. Existing
WO-017/018 foundations remain merged but are not wired into live tool behavior.

## Scope and frozen product

Product checkpoint: 8552f0a, with Sonnet 5.5 / medium configured in the private IDX
runtime. No new facet, analysis, ranking, tool/schema, prompt or filter integration.
Fix only evaluation compatibility/readiness before a paid run; preserve each failed
run and its reason. Product fixes discovered by evaluation get explicit scope and
fresh affected acceptance. Do not improve scores by changing expected results.

Own: evals/run.py and evals/routing_fixtures.py; tests/test_routing_fixtures.py,
tests/test_anthropic_evals.py and relevant runner regressions;
provider/evaluation docs; docs/BASELINE_ACCEPTANCE.md; current status/assignment
pointers; pause notes in WO-017/018; this WO and append-only EVIDENCE_LOG entries.
No guard/CI edit, provider key read/change, email approval, real send, model request
or public deployment is authorized by this preparation alone.

## Offline preparation

- Preserve existing run artifacts before modifying their producer. Use exclusive
  report creation for local runs and a distinct path per paid command.
- Translate explicit Anthropic effort to output_config.effort, omit unsupported
  sampling/OpenAI fields, and retain opaque thinking blocks in in-memory tool-loop
  history without putting them in reports, reply previews or logs.
- Apply medium to both single-tool and routing eval calls. Keep the existing OpenAI
  request contract unchanged. Malformed/truncated responses abort; no auto retry.
- Verify using stubbed documented response shapes, including continuation after a
  thinking/tool-use reply, invalid effort, hidden-only output and consent refusal.
- Run read-only preflight/probes, count selected cases/call ceilings and prepare
  exact commands. No placeholder key and no guessed cost or fabricated judgment.

## Paid and manual acceptance

Each actual provider run requires the human's exact command-bound grant. Start with
a small protocol smoke test, then the full routing/e2e and remaining local suites.
Report categories, skips, model/effort, product/driver revision, data/index dates,
call ceilings and actual console cost. Routing/e2e stubs prove route selection,
not actual listings or final answer truth; verify those through tool/DB checks and
UI/WhatsApp rehearsal. Human relevance marks, owner email approval/receipt, demo
recording/backup and personal reflection remain human evidence.

Acceptance is complete only when failures are triaged/fixed, the affected checks
are rerun under fresh grants, manual evidence is captured and STATUS.md identifies
an accepted base checkpoint. Resume the capability roadmap only afterward.

## Initial findings / Status

Latest 2026-10-25T23:39:43Z: behavior-01 completed with 36 passed, zero failed,
ten semantic-recall skips, no abort, on the real database. All 100 existing human
relevance cells are blank; SEMANTIC_REVIEW.md is the next no-cost operator step.
Routing consistency and context checks passed. Full relevance, runtime/manual,
email receipt, actual costs, recording and reflection remain open. New report
metadata records the admission counter; old reports are unchanged. Historical
findings follow.

Earlier smoke checkpoint (2026-10-25T21:35:56Z): the first human-granted
protocol smoke passed 1/1,
with two model requests under its four-request ceiling, Sonnet 5.5 / medium, driver
c3236b5. The expected search_listings route and city/max_price/min_beds subset
matched. The report is preserved privately at the documented smoke-01 path. No
abort/retry or real tool execution occurred. Full baseline acceptance and console
cost remain open; the next 40-case routing grant is separate. Earlier preparation
notes below are historical and do not negate this partial live result.

Active, offline preparation. The existing Anthropic adapter rejects medium effort
and thinking blocks; it must be fixed before a baseline paid run. First sandboxed
preflight: indexes/settings/tools passed, DB connection failed and the paid token
was expired; an unsandboxed read-only recheck is recorded separately. No paid run
has occurred under this WO. The historical eval output was copied and hash-verified
to a private temporary backup before producer changes.


Offline update: the unsandboxed preflight passed database/index/tools/settings/log
checks; only the expired paid token remains (7/8). Both installed MCP doctor probes
returned ok, and gateway RPC is healthy. Public case definitions select 111 local
cases, at most 303 chat plus 19 embedding calls; the separate protocol smoke ceiling
is four. See BASELINE_ACCEPTANCE.md for the split runs and explicit limits.

The updated adapter and runner/preflight/runbook regressions passed 386 tests in
6.81 s; Ruff passed after formatting and a line-length correction. Initial tests
caught ten failures: one malformed new test record and fixture helpers reusing a
report path. Fixture reports are now archived before a repeated fake invocation,
preserving the identical argv needed by token-consumption assertions. CLI existing-
report refusal and atomic exclusive local creation are separately tested. No token
assertion was relaxed, and no real report was overwritten. CI is still required.


Credential follow-up authorized by the user: they no longer had a copy of the key
and explicitly asked to save the existing key to .env. Installed OpenClaw metadata
confirmed one Anthropic API-key profile. A private local process used the installed
SDK in read-only/no-sync/no-keychain-prompt mode to copy that key directly into the
ignored .env, never into tool output or the coding-agent environment. The previous
file was backed up and byte-verified; new permissions 0600, one assignment and every
other setting line unchanged were verified. No provider API request, rotation,
gateway config update or key value is recorded here.

The evaluator now supports that explicit private .env fallback for Anthropic only;
process environment wins even when empty, ambiguous/missing/unreadable files fail
closed, and no model/settings or shell code is sourced from the file. Runtime DB/
tool-server setting allowlists are unchanged. Adapter/runner/length tests passed
349 tests in 10.29 s; full CI is required before the smoke. No paid run has started.


### 2026-10-25 — Routing-01 finding and contract fixture correction

The human-granted routing-01 command ran once on driver 1195503, Sonnet 5.5 /
medium, at 22:22:22Z: 35 pass, five fail, no skip/abort, 76 model requests. Cases
005/010/015/020/021 repeated expected lookups; their final previews described the
missing passages/figures/listings in the generic placeholder. This supports an
invalid-fixture diagnosis; it does not establish a passing model or live product.
Both original reports were copied outside the checkout and byte-verified before
editing the runner; neither report nor its score is changed.

The user agreed to the offline fix. contract-v1 uses actual tool names/arguments,
real boundary models and pure formatters to supply synthetic cards, market data,
sourced own-words reference passages, comp abstention and pending action views.
No case ID, expectation, real tool body, SQL, index, runtime store, approval or
send enters fixture generation. Structured prior search calls seed only isolated
filter state. Wrong routes and duplicate calls retain their original failure
semantics. Original prompts, schemas and goldens are unchanged. New report
metadata distinguishes this harness input; scores across versions must not be
claimed as a controlled product improvement. Fresh paid acceptance is separate.

Initial focused checks passed 368 tests. New duplicate/wrong-route regressions then
caught a test-only report-key mistake (the trace fields are flat, not nested);
that assertion was corrected without changing scoring or real run evidence.


Offline verification of contract-v1: the focused harness/provider/fixture/tracing
checks passed 422 tests in 10.86 s; docstring-length checks passed separately.
Ruff and diff whitespace checks passed. The first broad sandbox run had 3,098
passes, one new fixture failure (monthly analytics missing; corrected), and six
existing tracing failures from denied loopback bind. The focused rerun included
all seven affected checks with socket access. CI remains the full-suite and
synthetic-database acceptance before merge. No real provider call was made.


### 2026-10-25 — First passing contract-v1 routing run

The human minted the exact routing-02 grant, 160-request ceiling; it was consumed
once. Private report base-sonnet-20261025-routing-02.json, UTC 22:47:09, driver
ab23bd63c8c7afaaa079239db789831aafbe50e2, Anthropic claude-sonnet-5-5, medium,
temperature omitted, routing_fixture_version=contract-v1: 40 pass, zero fail,
zero skipped/manual, aborted=null, database_configured=null. Summed model_calls
is 71. Cases 005/010/015/020/021 each made their expected lookup(s) once. Every
route/argument check passed, including mixed and refusal/injection routing rows;
this does not certify real final answers, runtime policy or channel behavior.

Only synthetic tool results ran: zero embedding, real tool/DB lookup, persisted
draft, approval or delivery. No automatic retry or second invocation. The new
report was copied outside the checkout and SHA-256 verified; older evidence is
unchanged. The temporary untimed caffeinate process for this run was stopped;
the user's existing timed keep-awake process was left alone. Actual cost remains
pending provider-console evidence. The prior 35/40 result is preserved; changing
fixtures prevents claiming a controlled product-improvement comparison.

Harness PR #92 passed both CI runs: measured from run 40241223345, 3,105 unit
tests (60 skipped), 59 fixture integration tests (one skipped), 155/155 model-free
evals. The next fresh grant is routing-03 for consistency with the same fixture,
model, prompts and medium effort. WO-013's two-run principle is retained without
inventing a miss allowance for the expanded case set. E2E/behavior, manual marks,
owner receipt, costs and recording still gate full acceptance and roadmap work.


### 2026-10-25 — Routing consistency: second consecutive 40/40

The human granted exactly routing-03 once, ceiling 160. The private report
base-sonnet-20261025-routing-03.json records UTC 23:09:11, driver
454343b46984f57bfa329edc19eac1d9ef9bc774, Anthropic claude-sonnet-5-5, medium,
temperature omitted, contract-v1: 40 pass, zero fail/skipped/manual, aborted=null,
database_configured=null. Model requests sum to 72. Routing-02's preserved report
independently records 40/40, 71 requests; both are read to establish consistency.
A git comparison between their revisions found no change in driver/fixtures,
cases, tool code, skills or config; the intervening commit updated docs only.

Case 019 differed within its existing allowed routes: routing-02 declined without
a tool; routing-03 declined the contact instruction and called search_listings
with city, the allowed legitimate search. Its preview shows the refusal and
synthetic cards. Other recorded call names/argument-key sets matched between
runs. No case/golden, prompt, scoring rule or call limit changed. These are two
consecutive passing routing checks, not proof of real final answers, channel
behavior, contact privacy or delivery. The original 35/40 placeholder report stays
in evidence; cross-fixture scores are not a controlled product comparison.

No embedding, real tool/DB lookup, persisted draft, approval or send occurred.
No retry or second invocation. The new original was copied outside the checkout
and SHA-256 verified. Its temporary untimed caffeinate was stopped independently
of the user's existing timed process. Costs remain pending provider-console
figures. Metadata-only case counting confirmed the next end_to_end grant selects
25 cases and a 100-chat-request ceiling; e2e-01's output path is unused. Behavior,
runtime/manual checks, relevance, receipt and recording still gate full baseline
acceptance; the capability roadmap stays paused.


### 2026-10-25 — Context routes pass; billing has not posted

The exact human-granted e2e-01 command ran once, capped at 100 requests. Private
report base-sonnet-20261025-e2e-01.json, UTC 23:17:15, driver
6b7bd527fb57b05a743658dba79ee98e38ecb54c, Anthropic claude-sonnet-5-5, medium,
temperature omitted, contract-v1: 25 pass, zero fail/skipped/manual, aborted=null,
database_configured=null. Summed model_calls is 44. The original was copied
outside the checkout and SHA-256 verified. No retry, embedding, real tool/DB call,
persisted draft, approval or send occurred in the routing run. Its temporary
untimed keep-awake process was stopped; existing timed processes were preserved.

The user asked actual spend. Read-only native Chrome inspection of the logged-in
provider cost page, filtered to October 25 UTC, showed no data, a 22:01 UTC data
cutoff, and a notice that recent usage may take hours to appear. Displayed zero
is not verified zero cost. No estimate is recorded, and unrelated account-month
spend is not attributed or published. Re-reading all five private run artifacts
sums 265 model requests: smoke 2, placeholder routing 76, contract routing 71 and
72, context 44. Counts do not establish billed dollars.

Separately, documented read-only preflight passed seven checks: package, seven
tools, database as-of dates, matching listing index (54,881 rows), hybrid docs
index (510 chunks, built 2026-09-26), four settings and writable log folder. Its
only failure was the tool-server token naming another command; no token was
granted or provider called by preflight. Data as-of remains active 2026-09-18,
sold 2026-09-17. Metadata-only counting from public cases and the runner's ceiling
rules confirms the next behavior selection: 46 cases, 43 chat + 19 embedding
requests at most. Output behavior-01 is unused; a fresh exact-command grant is
required. Human marks/skips, real behavior, runtime/channel, receipt, actual costs
and recording still gate full acceptance; capability work remains paused.


### 2026-10-25 — Behavior baseline, unjudged recall and receipt metadata

The exact human-granted behavior-01 command ran once under ceiling 62. Private
report base-sonnet-20261025-behavior-01.json records UTC 23:39:43, driver
e7c97cc09c370495f81a72989fed91c0a035dba2, Anthropic Sonnet 5.5 / medium, no
temperature, real database configured, no abort: 36 pass, zero fail, ten skipped.
Pass counts by category: market requests 5, memory conversations 5, property
requests 10, RAG 5, recommendation requests 5, safety refusals 2, descriptive
request parsing 4. All ten recall_at_k checks skipped because the human judgments
setting is unset. No skip is counted as passed. Four successful embedding HTTP
responses were visible in terminal output; the report does not contain an
aggregate provider-request receipt. The 62-call grant is a ceiling, not spend.

Scope was checked against the producer: filters_* validates request parsing; it
does not execute market, recommendation or descriptive-search facts/ranking.
Memory conversations execute search state; RAG checks retrieve real passages.
The earlier commentary overstated market calculations and was corrected. SQL/math
has separate fixture CI evidence; real final facts/relay still need manual checks.

The original report was privately copied and SHA-256 verified. The completed
run's untimed caffeinate was stopped, preserving other timed processes. The
documented model-free semantic scorer was run: ten existing sheets, ten unmarked
rows each, zero scored queries, no judgments file generated. Only its printed
numbers were inspected, not private candidate rows. Existing sheets can be marked
without another generation run; SEMANTIC_REVIEW.md maps the approved public
queries to their files. No relevance labels or quality scores were invented.

Before editing the report producer, seven existing JSON artifacts (runs plus
last_run) were copied outside the checkout and hash-verified. New report fields
paid_requests_counted and paid_request_ceiling copy this invocation's actual
admission budget. They include admitted attempts before transport and are not
billed dollars; missing/old receipts stay unknown, never backfilled. No provider
payload, prompt, schema, golden, scoring, retry, budget enforcement or product
behavior changed. Five regressions cover single-tool/routing counts, shared tool
admission, aborted attempts without retry and absent receipts despite a prior
active budget. The first focused run passed 378 tests but caught an overlong
new docstring; shortening it yielded 379/379 focused tests. No gate was relaxed.

Next: human marks all 100 existing cells, then the model-free scorer; after a
complete judgments file, a fresh targeted grant covers only ten recall cases
(ten embedding requests, zero chat). Full manual/runtime, receipt, actual provider
costs and recording remain. New capabilities stay paused.


Receipt-only change verification: 3,110 offline tests passed in 77.75 seconds,
with 60 database-marked tests deselected. Ruff check/format and diff whitespace
checks passed. All provider transports were stubbed; this added no paid run.
Full fixture integration and model-free CI remain required before merge.
