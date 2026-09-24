# WO-005 — Evaluation harness and CI

**Driver:** agent
**Depends on:** WO-004
**Estimated effort:** 2-3 hours

## Objective
`python -m evals.run --suite ci` runs every script-checkable case against a synthetic fixture database in CI,
on every push, with no model calls; `--suite local` runs the rest on demand; results land in the evidence log.

## Why
Every later work order adds cases. Without a runner and a fixture database, "the evals pass" is a sentence, not a check.

## Inputs
`docs/EVALUATION.md`; `evals/cases/property_search.yaml`; `docs/data/schema_notes.md` (column names and types); `tests/test_eval_cases.py` (temporary, to be replaced).

## In scope
- `evals/run.py`: loads `evals/cases/*.yaml`, filters by suite, executes check types `filters_exact`, `filters_subset`,
  `rowcount_max`, `fields_absent`, `refusal`, `regex`; `human` cases are listed, not executed. Prints a table and writes
  `evals/last_run.json` (gitignored). Exit code non-zero on any failure.
- `tests/fixtures/synthetic.sql`: DDL for both tables with the real column names and types from `schema_notes.md`,
  plus about 20 invented rows per table (fake addresses, fake names, prices and dates chosen to exercise the cases,
  including a zero-comp city, a condo and a single-family pair, a malformed date, a display-flag-false row). Nothing real.
- `tests/fixtures/README.md`: how the rows were invented and the rule that no real row may ever be added.
- `.github/workflows/ci.yml`: add a MySQL service container, load the fixture, run `pytest -m db` and `python -m evals.run --suite ci`.
- `evals/cases/safety.yaml`: the safety seed cases from `docs/EVALUATION.md` that are script-checkable
  (injection strings, 500-row request, deny-listed field request, "export everything", agent-contact absence).
- `docs/EVIDENCE_LOG.md`: first rows (parser accuracy on the current set, eval pass rate, CI duration).
- Remove `tests/test_eval_cases.py`.

## Out of scope
Model-dependent cases beyond listing them; RAG, routing, and memory categories (they arrive with their work orders); any new product feature.

## Files expected to change
`evals/run.py`, `evals/cases/safety.yaml`, `tests/fixtures/synthetic.sql`, `tests/fixtures/README.md`, `.github/workflows/ci.yml`, `docs/EVIDENCE_LOG.md`, `tests/test_eval_cases.py` (deleted).

## Interfaces and contracts
The case format in `docs/EVALUATION.md`. A case that needs a new check type must add it to that document in the same commit.

## Implementation requirements
1. The runner has no model dependency and no network access in the `ci` suite.
2. Fixture rows are invented; a lint step fails CI if a fixture value matches a real listing key pattern or contains an email or phone number.
3. The `db` integration tests from WO-004 pass against the fixture in CI without modification.
4. Adding a case is a YAML edit; adding a category is a new file; the runner discovers both.
5. `--suite local` prints what it would run and which environment variables it needs, then runs if they are set.

## Safety requirements
No real data in fixtures; no secrets in CI; agent-contact absence is itself a case.

## Tests required
`tests/test_evals_runner.py`: each check type on a tiny inline case; a failing case yields a non-zero exit; `human` cases are skipped.

## Acceptance criteria
- CI runs unit tests, integration tests against the fixture, and the `ci` eval suite, and is green.
- `evals/cases/` holds at least 10 property-search and 8 safety cases, all passing.
- `docs/EVIDENCE_LOG.md` has its first measured rows.
- The fixture lint passes and would fail on an inserted email address (verified on a throwaway branch, noted in Status).

## Verification commands
```
python -m evals.run --suite ci
pytest tests/test_evals_runner.py -q
# CI: push a branch; confirm the MySQL service, fixture load, db tests, and eval step all run
```

## Deliverables
The runner, the synthetic fixture, the safety cases, the CI job, the first evidence rows.

## Stop conditions
- The fixture cannot reproduce a column type from `schema_notes.md` (for example a FULLTEXT index that the CI MySQL version refuses).
- A case can only be checked with a model or real data: mark it `local` or `human`, do not fake it.

## Status
**Done on 2026-09-24: runner, fixture, lint, safety cases, the CI job with the fixture
database, the temporary test removed, the fixture verified locally, first evidence rows;
independently reviewed.** Branch `wo-005-eval-harness`, PR #14. Left for a `paid` run:
parser accuracy on the 10 local cases (recorded under WO-004 when run).

**Built**
- `evals/run.py`: discovers `evals/cases/*.yaml`; validates every case at load (a malformed
  case is a failing row); check registry `filters_exact`, `filters_subset`, `clarification`
  (validation only, via `from_input`), `rowcount_max`, `fields_absent`, `regex`, `refusal`
  (via the search tool body, no MCP transport), `human` (listed as manual). A check that
  needs a query is skipped with "no database" when none is configured; skipped is not a
  failure. Table to stdout, JSON report to `evals/last_run.json`, exit 1 on any failure.
  `--suite local` prints its plan and the two variables it needs; it runs only with
  `--allow-paid`, `OPENAI_API_KEY`, and `IDX_EVAL_MODEL`, through urllib (no dependency).
- `evals/cases/safety.yaml`: 14 ci cases, 2 local refusal cases, 2 manual cases.
- `tests/fixtures/make_synthetic.py` (seed 5005) writes `synthetic.sql`: both tables with
  every column and type from the schema notes, the migration's five generated DATE columns
  (with a LIKE format guard so a malformed text date yields NULL) and its indexes; 71 active rows
  (9 Pasadena, 7 of them 3+ beds at or under 1.5M; 52 Los Angeles; a condo and single-family
  pair in Glendale; Alhambra with no sold rows; pool flag empty and NULL; a quarterly HOA) and
  25 sold rows (latest valid close 2026-09-17, one invented typo year 2071, one malformed date). The
  planted remark "IGNORE PREVIOUS INSTRUCTIONS ..." sits on an active Pasadena row. Agent-
  contact columns exist and are NULL everywhere. No FULLTEXT index: nothing queries it yet.
- `scripts/fixture_lint.py` (outside `scripts/gates/`, so no token is needed to extend it):
  fails on an email, a phone-shaped digit run, a key that is not 9 plus 5-6 digits, an
  agent-contact or deny-listed value, or an unparseable INSERT; never prints the value.
- `docs/EVALUATION.md`, `evals/README.md`: case format, check types, skip rule, paid notice.
- `pyproject.toml`: pytest path gains the repo root so `evals` imports in CI.
- Tests: `tests/test_evals_runner.py` (45), `tests/test_fixture_lint.py`,
  `tests/test_safety_cases.py`, `tests/test_eval_cases.py` (temporary). Full suite 861 passed
  with `MYSQL_HOST=localhost` (854 unit + 7 db before the temporary test was removed, 798 + 7
  after); ruff clean; content gates pass on every new
  file.
- Measured: `python -m evals.run --suite ci` against the local real database on 2026-09-24:
  26 cases (13 property-search, 13 safety), 26 pass, 0 fail; the six query checks ran with
  50-row results.

**Review outcome (no blockers; all should-fix items applied)**
- `fields_absent` and `regex` fail, instead of passing vacuously, when the filters validated
  but the envelope is an error or a Clarification.
- `refusal` fails at once when the filters validate (a query would run), before any database
  probe; an error envelope passes only when `expect.category` names it.
- `--require-database` (implied by `CI=true`) turns a "no database" skip into a failure, so
  the CI eval step cannot go green by skipping.
- An empty selection, or a named case or category outside the chosen suite, exits 1.
- Stricter `expect` validation at load: non-empty `filters` for subset, non-empty string
  `fields`, `max_rows` 1-50, a compiling `pattern`, only `reason` and `category` for refusal,
  no unknown keys.
- Property-search now has 13 `ci` cases (ZIP only, pool false, half-step baths, min above max,
  bad ZIP, unsupported key, stored city spelling, two fixture queries) beside the 10 `local`
  parser cases, meeting the "at least 10 property-search cases, all passing" criterion.
- Fixture: the typo close date is an invented 2071 value (2072-06-29 was a real aggregate);
  the DATE guard uses `LIKE '____-__-__'`; booleans render as 1/0; the lint now rejects any
  statement other than CREATE TABLE, SET, or single-row INSERT, a quoted DEFAULT on a
  protected column, an INSERT without the key columns, and multi-row INSERTs.
- The profiler's deny-list section names `OccupantType` by name pattern; it is a category
  (owner, tenant, vacant), not a contact field, and is neither allowlisted nor selected. The
  deny-list in `columns.py` (OccupantName, OccupantPhone, access and lockbox fields) is
  unchanged; a change there is outside this WO.

**Decisions**
- A check that calls the tool needs a database only when its filters pass validation, since a
  Clarification is identical with or without one; this also stops a refusal case from passing
  on the "not configured" error.
- The fixture's generated DATE columns add a `LIKE` format guard the migration lacks, so the
  malformed-date row inserts under strict mode; proven in CI, not locally (see below).
- The WO's "display-flag-false row" does not exist: neither table has display-flag columns
  (schema notes sections 10-11).
- The fixture only creates; loading it twice fails by design (empty database only).

**Closed with the human's tokens (2026-09-24)**
- `gates`: `.github/workflows/ci.yml` runs the tests job with a `mysql:8.4` service: fixture
  lint, fixture load, a SELECT-only `idx_reader` created by hand (not the image's user, which
  would get all privileges), unit tests with no database, `pytest -m db`, and
  `python -m evals.run --suite ci --require-database`. The passwords in the workflow are
  CI-only values for a throwaway container. `.gitignore` ignores `evals/last_run.json`.
- `delete`: `tests/test_eval_cases.py` removed (the runner tests cover it). The fixture was
  loaded into a local throwaway database `idx_fixture` (passwordless Homebrew root, SELECT
  granted to the reader): 71 active rows, 25 sold rows, the malformed date gives one NULL
  `close_date_d` under strict mode, the 7 db tests pass unmodified, and the ci suite passes
  26 of 26 with `--require-database` (Pasadena page 2 returns 2 rows; Los Angeles caps at 50).
- Fixture-lint check: not done on a throwaway branch, because that would put an email address
  in a tracked file, which the repo rules forbid even briefly. Proven instead by
  `tests/test_fixture_lint.py` (an inserted email, a phone-shaped number, a bad key, and an
  agent-contact value each fail the lint at run time) and by the pii gate, which fails CI on
  any email in any tracked file before the lint would even run.
- First evidence rows are in `docs/EVIDENCE_LOG.md`. Parser accuracy on the 10 local cases is
  not measured yet: it needs a `paid` run (`python -m evals.run --suite local --allow-paid`).
- The key-pattern check for the fixture (count of real keys matching `^9[0-9]{5,6}$`,
  expected 0) is left for the human to run as an aggregate query and record here.
