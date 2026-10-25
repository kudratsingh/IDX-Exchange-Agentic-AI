# Accept the base assistant before new capabilities

User decision, 2026-10-25: pause new capability implementation and evaluate the
base system completely first. WO-019 is active. Product source is frozen at
8552f0a; the evaluation-driver fix is recorded separately by each run's git commit.
WO-017/018 foundations are merged but unused by live search/tools. Do not roll them
back or connect them during baseline acceptance. The combined roadmap remains saved.

## Completed model-free preparation

- Sonnet 5.5 / medium is configured for IDX; private credential entry and restart
  are complete. Gateway RPC and both MCP probes passed on 2026-10-25.
- Preflight outside the sandbox passed seven of eight checks: database, both
  indexes, package, seven IDX tools, settings and log-folder readiness. Only the
  paid token failed (expired). The initial sandbox-only DB failure was not an outage.
- Data dates: active 2026-09-18, sold 2026-09-17; listing index 54,881 rows matching
  active as-of; hybrid docs index built 2026-09-26, 510 chunks.
- Fixture CI passed before this preparation: 3,053 offline tests (60 skipped),
  59 fixture integration tests (one skipped), and all 155 model-free eval cases.
  New evaluator tests and CI must pass before the first paid command below.
- Existing last-run evidence was copied and hash-verified outside the checkout
  before producer changes. Each new local run refuses an existing report path.

## Request contract

The standalone driver uses Anthropic Messages, with explicit native
`output_config.effort = medium` and adaptive thinking. Temperature and the OpenAI
`reasoning_effort` field are omitted. Opaque thinking/redacted blocks remain only in
memory for tool-loop continuation; reports/previews do not contain them. Medium
applies to single-tool cases as well as routing cases. `none` means native default,
not disabled thinking, and is not the chosen baseline setting. Invalid/unsupported
or truncated responses stop the run; no request is silently retried or reshaped.

References: [effort](https://platform.claude.com/docs/en/build-with-claude/effort),
[thinking and tool continuity](https://platform.claude.com/docs/en/build-with-claude/thinking).
These are request-shape sources, not evidence of a successful live run.

## Operator-only setup and gates

Use the repo root with .venv active. The eval driver reads the Anthropic key from
its own process environment. It does not copy OpenClaw's private profile. A key
export in your terminal does not appear in the coding agent's separate environment;
run the consented eval in that same terminal. Never paste a key into chat, shell
history, tracked files or a command-line argument. If needed, enter it at a silent
zsh prompt, then export it for this terminal session:

```zsh
export IDX_EVAL_PROVIDER=anthropic
export IDX_EVAL_MODEL=claude-sonnet-5-5
read -rs 'ANTHROPIC_API_KEY?Anthropic API key (hidden): '
export ANTHROPIC_API_KEY
print
```

Keep the separate compatible embedding key/settings for description and hybrid
retrieval. A new chat key is not an embedding replacement. Do not source .env.
The exact paid command, its output path and call ceiling below are part of each
grant. The human runs consent.sh; the coding agent never creates its own token.

## Paid sequence (not executed yet)

Start with a protocol smoke case that exercises the tool-result continuation.
After the human grants four requests for this exact command, run it once:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --case routing-local-002 --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-smoke-01.json" --max-calls 4
python -m evals.run --suite local --allow-paid --case routing-local-002 --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-smoke-01.json
```

Stop on a provider/driver error, preserve the report and fix offline. A new attempt
uses a new report path and its own exact-command grant. A successful smoke does not
replace the following full checks. Grant each row separately; do not mint all grants
in advance because there is one active paid token.

| Run | Selected coverage | Ceiling | New report path |
|---|---|---|---|
| routing | 40 cases, current skills and all tool schemas | 160 chat | evals/runs/base-sonnet-20261025-routing-01.json |
| end_to_end | 25 conversation/context routes | 100 chat | evals/runs/base-sonnet-20261025-e2e-01.json |
| behavior | 46 parser/memory/market/recommendation/safety/semantic/RAG cases | 43 chat + 19 embedding = 62 | evals/runs/base-sonnet-20261025-behavior-01.json |

Commands for those rows, each preceded by its own human-minted token with the exact
line and ceiling in the table:

```bash
python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-routing-01.json
python -m evals.run --suite local --allow-paid --category end_to_end --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-e2e-01.json
python -m evals.run --suite local --allow-paid --category property_search --category multi_turn_memory --category market_analytics --category recommendations --category safety --category semantic_retrieval --category rag --database-kind real --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-behavior-01.json
```

The definitions currently select 111 local cases total, at most 303 chat and 19
embedding calls (322), excluding the separate four-call smoke. These are ceilings,
not spend or expected actual calls. Recount if the case set or flags change.
Human-judged cases without marks may skip; preserve the reason and finish that
acceptance instead of counting the skip as a pass. Fixture CI uses its isolated
synthetic database; do not run fixture expectations against the real snapshot.

Routing and end-to-end checks use stub tool results. They test model selection and
arguments, not real final cards, true market answers, send behavior or WhatsApp.
Do not claim full end-to-end acceptance from these two routing reports alone.

## Runtime and human acceptance

1. Start a fresh session on Sonnet / medium. Follow DEMO_RUNBOOK.md and
   ADDITIONAL_CAPABILITIES.md for search/refinement/paging, comps, description
   matches, sources, mixed requests, drafts and saved searches. Tool-server paid
   consent for live embeddings is separate from direct eval commands.
2. Check actual database/math support and whole-message relay, scope isolation,
   outside-allowlist handling, tool/policy refusal, injection, email redirect and
   approval/send refusals. Record each observed reply and trace reference privately.
3. Human reviews semantic relevance. Provider routing success cannot certify recall.
4. Configure mail locally if needed; operator inspects and approves one exact draft,
   authorizes a single real send and confirms receipt. No automatic retry.
5. Capture actual provider usage/cost from both consoles, run dates and available
   token/cache measurements. Record unavailable attribution rather than estimate it.
6. Triage failures against frozen expectations. Fix the cause and rerun affected
   checks under fresh grants; preserve the original failed reports. Any accepted
   exception needs explicit human review. No unresolved safety/approval bypass.
7. Rehearse/record the demo and backup; review the final reflection. Record the
   accepted product/driver revisions and known limitations before resuming Phase 1.

## Status

Preparation active. No live baseline score, cost, human relevance judgment, owner
receipt or recording has been produced under WO-019. New capability work stays paused.
