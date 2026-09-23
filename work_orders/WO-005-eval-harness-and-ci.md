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
not started
