# WO-020 — Stronger measurement: SQL-checked answers, a local-model adapter and latency

**Driver:** agent (human approves this draft, any local-model setup and every model run)
**Depends on:** WO-005 eval harness, WO-013 routing driver, WO-019 contract-v1 fixtures
**Estimated effort:** planning input only, not a commitment

## Objective
A held-out question set of at least 50 cases whose expected answers are computed by
independent SQL over the synthetic fixture, scored separately on tool choice,
arguments and answer, runnable model-free in CI and, under its own grant, against a
hosted or a local Ollama-compatible model; plus a reproducible latency benchmark.

## Why
Today's evidence mixes route checks against stubbed tool results with hand-valued
fixture figures, so a correct route with a wrong number, or a right number for the
wrong reason, is not separated. Phase 5 of the roadmap asks for independent answer
checks, held-out scoring and comparable latency before more features are measured
against them.

## Inputs
`evals/run.py` (suites, checks, consent-gated driver, routing contract-v1),
`evals/cases/*.yaml`, `docs/EVALUATION.md`, `tests/fixtures/make_synthetic.py` and
the fixture database CI loads, the MCP tool bodies in `src/idx_agent/mcp_server/`,
`src/idx_agent/safety/consent.py`, CAPABILITY_ROADMAP.md Phase 5,
ROADMAP_CROSSWALK.md items B10, B11, B13, B18.

## In scope
1. **Measurement set.** A new category `measurement` in
   `evals/cases/measurement.yaml`: at least 50 natural-language questions over the
   fixture covering search filters and counts, market figures (median price, DOM,
   sale-to-list, price per sqft, monthly counts, subtype mix), comps price checks,
   and comps price checks. Each case carries `input`, `expect.route`, `expect.args`
   and `expect.facts`. At least 50 cases have SQL-computed answer facts. No-tool,
   clarification and refusal cases may be added; they are scored only in model runs
   and do not count toward the 50.
2. **Independent SQL truth.** A truth module under `evals/truth/` with hand-written,
   parameterized SQL per fact kind, written from the documented definitions
   (CONTRACTS.md, DECISIONS.md, EVALUATION.md, ANALYSIS_DESIGN.md), not by calling or
   copying `src/idx_agent/db/`. It may import only `idx_agent.db.pool` (the
   SELECT-only connection) and `idx_agent.safety.columns`; as-of dates are recomputed
   in truth SQL. Medians and other aggregates are computed in SQL so that no
   statement returns more than 50 rows. A CI check recomputes every
   case's expected facts from the fixture and fails if the YAML golden and the truth
   SQL disagree, so goldens are neither hand-copied nor produced by the code under test.
3. **Splits.** Each case is tagged `dev` or `heldout` (roughly 40/60). Held-out cases
   are never used to edit skills, tool descriptions or prompts; the split file's hash
   is recorded in every report. A change that edits a held-out case starts a new set
   version.
4. **Three separate scores.** Tool selection (exact route, order-aware), argument
   validity and match (through each tool's own validator, as `filters_subset` does),
   and answer correctness (each expected fact present with tolerance rules stated per
   fact kind). Reported per split and per category, never folded into one number.
   The split hash is SHA-256 over the sorted (case id, split) pairs.
   A wrong route scores zero on arguments and answer for that case.
5. **Model-free CI path.** Today a case has one suite and a `route_exact` case may
   not be `ci`. The loader is extended so a `measurement` case is admitted in both:
   under `ci` (oracle mode) its golden arguments go to the real tool bodies against
   the fixture and the envelope's figures are compared with the SQL truth; under
   `local` the model chooses. EVALUATION.md's case-format rules are amended to say so. This checks the
   tools, not a model. The scorer itself is tested on recorded synthetic model
   transcripts (right, wrong-route, wrong-argument, wrong-number, extra-call).
6. **Local-model adapter.** `IDX_EVAL_PROVIDER=ollama` speaks the Ollama-compatible
   chat API with tool calls over the standard library HTTP client already used by the
   driver. It needs `IDX_EVAL_MODEL` and `IDX_EVAL_BASE_URL` and no key; it accepts
   only a loopback base URL, sends no API key, and aborts the run
   on any unsupported reply shape, as the other providers do. CI exercises it only
   against an in-process stub server on 127.0.0.1; no model is downloaded or run in CI.
   The real local-model leg runs later on the owner's Mac, not in the cloud.
   **Human rule (2026-10-28): a free local model is not a paid call and needs no
   token, but in this phase it must only ever see synthetic data.** The runner
   enforces that before the first request and refuses the run otherwise:
   `--database-kind fixture` is required, and a probe of the configured database
   must find only invented keys (the fixture-lint pattern) and fixture-sized tables.
   Documents come only from the fixture document index the runner builds from
   `tests/fixtures/docs`, and listings only from the fixture index with the
   `test:hashing` embedder. Any real index directory or embedding key in the
   environment is refused, not ignored. Hosted providers keep the paid path unchanged.
7. **Latency benchmark.** `python -m evals.latency` times the tool bodies and the
   lexical (BM25) document retrieval against a stated database
   (`--database-kind fixture|real`); similar-listing timing uses the `test:hashing`
   embedder only, and any real-embedder timing is a separate paid run. It uses fixed
   warm-up and repetition counts and reports p50/p95/max per tool with cold and warm defined
   in the report, row-count manifest, Python/MySQL versions and git commit. A pytest
   test runs a smoke size that checks the report shape only; no speed threshold is asserted or
   claimed from CI runners.
8. Documentation: EVALUATION.md section, evals/README.md usage, append-only evidence.
9. No change to `.github/workflows/`: every new CI check runs inside the existing
   `pytest -q`, `pytest -q -m db` and `evals.run --suite ci --require-database` steps.

## Out of scope
B18's threat assessment (its latency part is in scope), EXPLAIN/index review (B31), contract-versus-close
timing definitions (B27), shadow intent classifier (B5), router training, LLM
judges for numeric facts, any change to tool behavior, skills or prompts to raise a
score, any new hosted service, and installing or running a local model on the
owner's machine (a human step).

## Files expected to change
`evals/cases/measurement.yaml`, `evals/truth/` (new), `evals/run.py` (category,
oracle mode, scorer, provider), `evals/latency.py` (new), `tests/test_measurement_*.py`,
`tests/fixtures/make_synthetic.py` and regenerated `synthetic.sql` only if a question
needs rows the fixture lacks (appended last, in a city no existing case uses, dated
before the current sold as-of so as-of dates and existing goldens do not move),
`docs/EVALUATION.md`, `evals/README.md`, append-only `docs/STATUS.md` and
`docs/EVIDENCE_LOG.md`, this file.

## Interfaces and contracts
Existing case format and check registry (EVALUATION.md "Case format"); routing
contract-v1 envelopes; the `paid` consent path in `safety/consent.py` for hosted
providers; tool argument models in `docs/CONTRACTS.md`. No tool signature changes.

## Implementation requirements
1. At least 50 measurement cases with SQL-computed facts, at least 30 of them
   held-out; each has a route, an argument expectation and at least one answer fact.
   Optional no-tool, clarification and refusal cases carry an expected code instead.
2. Truth code imports nothing from `idx_agent` except `idx_agent.db.pool` and
   `idx_agent.safety.columns`; a test fails the build if it does.
3. The CI golden check runs under `--require-database` against the fixture and
   reports every disagreement with case id and fact name, without row values.
4. Scores are computed from the run report, re-derivable offline, and the report
   carries set version, split hash, provider, model, driver commit and fixture kind.
5. The Ollama adapter rejects a non-loopback URL before any request, never reads a
   provider key, and maps tool calls to the same internal shape as the others.
6. Latency reports are written outside the repository by default and never committed.

## Safety requirements
No real rows in fixtures, cases or reports committed; SQL parameterized with
allowlisted columns and at most 50 rows; deny-listed and agent-contact fields never
selected; time windows from the as-of dates; no paid call without a run token. A
loopback local-model run needs no token (human rule, 2026-10-28) but is
synthetic-only and refused otherwise, as requirement 6 states; it still uses a call
ceiling. The coding agent's guard hook classifies any `--suite local` command line as
paid without knowing the provider, so an agent session still cannot start one
without a token; this WO does not edit the guard. The email approval path is not
exercised by the model scorer beyond existing refusals.

## Tests required
Truth-versus-golden CI check; oracle-mode tool checks; scorer unit tests on synthetic
transcripts; Ollama adapter against a loopback stub (tool call, plain answer,
malformed reply abort, non-loopback refusal); latency report shape; an import test
proving truth SQL independence.

## Acceptance criteria
- `python -m evals.run --suite ci --require-database` passes in CI with the new
  category, and no case in it needs a model or network beyond the fixture database.
- At least 50 measurement cases with SQL-checked goldens; the split is recorded.
- A pytest test that injects stubbed model transcripts (never `main()` with
  `--suite local`) shows the three scores separately in the report.
- The Ollama adapter passes its stub tests; no model runs in CI.
- `python -m evals.latency --database fixture` produces a complete report locally.
- Docs and evidence updated; CI green; human review of the PRs.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
pytest -q -m db                    # fixture database settings in the environment
python -m evals.run --suite ci --require-database
python -m evals.run --suite ci --category measurement --require-database
python -m evals.latency --database-kind fixture --repeat 20
```

## Deliverables
The measurement set and truth module, scorer and oracle mode, local-model adapter,
latency benchmark, docs; and, as human steps, any hosted or local model runs.

## Stop conditions
- A question needs data the fixture cannot represent in the way the real tables do.
- A truth definition disagrees with a documented tool definition: report the
  disagreement and ask which is right; do not change either to make a case pass.
- Any wish to tune prompts or skills against held-out results.

## Decisions (human, 2026-10-28)
1. Scope approved as drafted.
2. A free local model is not a paid call and needs no token; it sees only the
   synthetic fixture in this phase.
3. CI uses a stub of the Ollama API, no real model; the real local-model leg runs
   on the owner's Mac later.

## Status
2026-10-28: scope approved by the human with the local-model rule above. Not started:
implementation follows WO-017 steps 4-6, after this record merges (human merge order:
WO-017 PRs, then this one).

2026-10-27: drafted for approval, docs only.
