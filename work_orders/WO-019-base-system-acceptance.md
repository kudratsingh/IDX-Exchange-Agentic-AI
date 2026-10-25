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

Own: evals/run.py; tests/test_anthropic_evals.py and relevant runner regressions;
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
