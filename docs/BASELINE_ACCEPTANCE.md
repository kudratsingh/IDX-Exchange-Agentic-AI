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

Use the repo root with .venv active. At the user's later request on 2026-10-25,
the existing saved Anthropic API key was copied privately into gitignored .env.
The previous file was backed up privately and the new file is 0600. The key was
not printed and no new provider key was created. OpenClaw still uses its own
private profile; no gateway configuration was changed by this save.

The standalone evaluator reads ANTHROPIC_API_KEY from its process environment,
then this checkout's .env only if the environment name is absent. An explicit
empty environment value disables fallback. Duplicate .env assignments are unusable.
The parser reads only this key literally; it does not source/execute the file or
load IDX_EVAL_MODEL from it. There is no need to paste/export the key again.
The coding agent can run the exact consented command with nonsecret model settings:

```bash
export IDX_EVAL_PROVIDER=anthropic
export IDX_EVAL_MODEL=claude-sonnet-5-5
```

Keep the separate compatible embedding key/settings for description and hybrid
retrieval. A new chat key is not an embedding replacement. Do not source .env.
The exact paid command, its output path and call ceiling below are part of each
grant. The human runs consent.sh; the coding agent never creates its own token.

## Paid sequence

Protocol smoke completed once at 2026-10-25T21:35:56Z: 1/1 passed, two model
requests, no abort, Sonnet 5.5 / medium. It exercised the expected search route and
tool-result continuation. The report is preserved at smoke-01; do not rerun the
spent command or overwrite that path. The original grant/run below is historical:


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

The first routing run at 2026-10-25T22:22:22Z completed 40 cases: 35 passed, five
failed, none skipped, no abort; 76 model requests under the 160-request ceiling.
Driver 1195503; Sonnet 5.5 / medium. The failed cases were routing-local-005, 010,
015, 020 and 021: each repeated a required lookup after the empty placeholder
supplied no result content. The injection case 020 still fails its legitimate
route; do not label the whole safety category accepted. Reports smoke-01 and
routing-01 were copied outside the checkout and verified byte-identical before
this harness edit. Original reports and failed scores remain evidence.

Offline correction: contract-v1 supplies complete synthetic boundary replies and
records its version, with original prompts, goldens and scoring unchanged. Every
duplicate remains a failure. This changes the evaluation input, so the next score
is a new fixture baseline, not evidence of a product improvement. Harness PR #92
passed both CI runs: 3,105 unit tests (60 skipped), 59 fixture integration tests
(one skipped), 155 model-free evals. The historical routing-02 grant below ran once
and is now spent, as is routing-01:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-routing-02.json" --max-calls 160
```

The agent runs the same command with nonsecret Anthropic provider/model settings
and the .venv interpreter; the gate allows those wrappers. No other flag or output
path is interchangeable. Full acceptance, actual console cost, human relevance,
owner receipt and recording remain open. New capabilities stay paused.


### Routing-02 checkpoint (historical)

At 2026-10-25T22:47:09Z, routing-02 on ab23bd63c8c7afaaa079239db789831aafbe50e2,
Sonnet 5.5 / medium, contract-v1: 40 passed, zero failed/skipped/manual, no abort,
71 model requests under the 160 ceiling. All five previously repeated lookups
made the expected calls once. The report was copied outside the checkout and
hash-verified; originals remain unchanged. This run used synthetic replies only;
no embedding, live tool, database lookup, actual draft/approval/send or channel run.
Actual provider-console cost remains pending.

WO-013 required two consecutive unchanged routing runs. Retain that consistency
check for this new provider/fixture baseline, without inventing a miss allowance
for the expanded 40-case set. The historical routing-03 grant below was
consumed once and is now spent:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-routing-03.json" --max-calls 160
```

At that checkpoint consistency was still pending. The completed check and next
grant follow; this historical command must not be rerun.


### Routing-03 checkpoint (historical)

Routing-03, report UTC 2026-10-25T23:09:11, driver
454343b46984f57bfa329edc19eac1d9ef9bc774: 40 passed, zero failed/skipped/manual,
no abort, 72 model requests under 160. Sonnet 5.5 / medium, no temperature,
contract-v1, same case set, prompts, schemas and fixture/driver code as routing-02.
The intervening diff contains documentation only. Both original reports are
preserved; routing-03 was privately copied and SHA-256 verified. Case 019 took
its allowed search alternative; no expectation changed to accept it.

Two consecutive 40/40 routing runs complete the routing-selection consistency
check. These are synthetic continuations, not real answer/channel acceptance.
The historical grant below selected 25 conversation-context cases, at most 100
chat requests, with synthetic continuations. It ran once and is now spent:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --category end_to_end --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-e2e-01.json" --max-calls 100
```

Behavior suites, runtime/WhatsApp, human relevance, owner delivery, actual provider
costs and recording remain. New capability work stays paused.


### Context checkpoint and behavior grant (historical)

The human-granted e2e-01 run at 2026-10-25T23:17:15Z passed 25/25, zero
failed/skipped/manual, aborted=null, 44 model requests under the 100 ceiling.
Driver 6b7bd527fb57b05a743658dba79ee98e38ecb54c; Anthropic Sonnet 5.5 / medium,
no temperature, contract-v1. Authored context covered refinement/paging, listing
references, mixed asks, limits, refusals and reset. No real tool or embedding
executed; this is context-sensitive routing, not real answer/channel acceptance.
The original report was privately copied and SHA-256 verified.

In response to the human's cost question, the logged-in provider cost page was
filtered to October 25 UTC. It returned no data and said recent usage may take
hours to appear (data cutoff shown: October 25, 22:01 UTC). Its displayed zero
is not a verified zero charge. No exact evaluation cost can be attributed yet.
The five completed reports sum to 265 model requests (2 + 76 + 71 + 72 + 44).
Request counts are not dollars; no cost is estimated from them. Billing for other
account activity is not attributed to this project or published here.

Read-only readiness after the run: package, seven tools, database, both indexes,
settings and log folder passed (7/8). Only the tool-server token check failed:
the consumed direct-eval token names another command, as expected. No model call
was made by preflight; it does not grant the next run. Active as-of 2026-09-18,
sold 2026-09-17; listing index 54,881 rows; hybrid docs 510 chunks, built 2026-09-26.

The next command selects 46 behavior cases across seven categories, at most 43
chat plus 19 embedding requests (62 total), and uses the real database. Existing
compatible embedding credentials are separate from Anthropic chat; no key changed.
Human semantic recall marks may still cause explicit skips. Skips are not passes.
The historical behavior grant below was consumed once and is now spent:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --category property_search --category multi_turn_memory --category market_analytics --category recommendations --category safety --category semantic_retrieval --category rag --database-kind real --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-behavior-01.json" --max-calls 62
```

The behavior output path was checked unused. Runtime/human relevance, owner receipt,
actual costs and recording remain. New capability implementation stays paused.


### Current checkpoint: marked relevance and manual acceptance

Behavior-01, UTC 2026-10-25T23:39:43, driver
e7c97cc09c370495f81a72989fed91c0a035dba2, Sonnet 5.5 / medium, real database:
36 passed, zero failed, ten skipped, no abort. The skipped semantic recall cases
had no configured judgments file. The operator has now supplied all 100 labels;
validation found no non-label changes. The original unmarked folder was archived
and verified before the marked files were installed with the unchanged order files.
The model-free scorer generated the complete private judgments file. The original
behavior report and its ten skips remain unchanged.

Parsing checks do not prove final facts or relevance. This run executed database
search-memory conversations and real RAG retrieval; its other filters_* checks
validate requests. The terminal showed four successful embedding HTTP responses.
The old non-routing report did not save its aggregate admission count; 62 remains
a ceiling, and the earlier 265-request measured total covered only the previous
five runs. Do not present either number as this run's billed dollars. Provider
costs remain pending console evidence, including separate embedding usage.

Saved-ranking scores: mean recall@5 81.25% over eight queries with relevant
candidates, mean precision@5 64% over all ten and 80% over the eight nonempty
queries. The two intentionally empty queries have no relevant hits. Recall is
normalized against the judged top-ten pool, not the entire corpus. A private
numeric receipt independently checked the scorer's rounded output. These figures
are not current-service verification or a new quality acceptance threshold.

Marking and local scoring are complete. The next paid selection is only the ten
recall checks against the current service:
zero chat requests, at most ten embedding requests. The agent sets the nonsecret
IDX_SEMANTIC_JUDGMENTS=data/semantic/judging/judgments.json on that invocation.
The marking/scoring prerequisite is complete; the operator can now grant this
exact command. Existing OpenAI embeddings are used; no chat requests are needed:

```bash
scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --case semantic-local-001 --case semantic-local-002 --case semantic-local-003 --case semantic-local-004 --case semantic-local-005 --case semantic-local-006 --case semantic-local-007 --case semantic-local-008 --case semantic-local-009 --case semantic-local-010 --database-kind real --no-temperature --reasoning-effort medium --out evals/runs/base-sonnet-20261025-recall-01.json" --max-calls 10
```

The new report's admission-counter receipt will record attempted provider calls;
it is not a dollar receipt. Completed parsing/memory/RAG cases stay accepted at
their measured scope. UI/WhatsApp final-answer relay, owner email approval/receipt,
actual costs, recording and personal reflection remain. Capability work stays
paused until baseline acceptance is complete.
