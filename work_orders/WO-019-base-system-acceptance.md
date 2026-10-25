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

Latest 2026-10-25T21:35:56Z: the first human-granted protocol smoke passed 1/1,
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
