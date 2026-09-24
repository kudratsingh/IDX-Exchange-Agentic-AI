# Evals

Golden cases that tell us whether a change made the assistant better or worse, and the
runner that checks them (`evals/run.py`, WO-005). The full plan (category sizes, metrics)
and the exact case format and check semantics are in `docs/EVALUATION.md`.

## How to run
From the repository root, after `pip install -e ".[dev]"`:

```
python -m evals.run --suite ci                  # every ci case; no model, no network
python -m evals.run --suite ci --category safety
python -m evals.run --suite ci --case search-ci-001 --case safety-004
python -m evals.run --suite manual              # lists the cases a person must check
python -m evals.run --suite ci --require-database   # as CI runs it: no skips allowed
```

Options: `--suite ci|local|manual` (default `ci`), `--category NAME` and `--case ID`
(both repeatable), `--cases-dir PATH` (default `evals/cases`), `--out PATH` (default
`evals/last_run.json`), `--allow-paid` (local only), `--require-database` (a case that
would be skipped for "no database" fails instead; `CI=true` in the environment implies it).

A selection that comes up empty is a failure, not a quiet green run: a `--case` or
`--category` that matches no case, or exists only in another suite (the detail names
which), a `--case` that `--category` leaves out, or a combination that selects nothing.

The runner prints one row per case (id, suite, check, result, detail), where result is
`pass`, `fail`, `skipped`, or `manual`, then a summary line. It writes a JSON report to
`--out` with the run time (UTC), suite, git commit, whether a database was configured,
whether one was required, every case's result, and the counts. The report is run
evidence, not source: never commit it. Exit code 1 when any case fails, a case file is
malformed, or the selection fails as above; else 0.

Cases that would run a query need a database. The runner uses the same settings as the
server (MYSQL_* in the environment, then `.env`); with none, those cases are `skipped`,
which is not a failure unless `--require-database` is given or `CI=true` is set. To run
without a database even when `.env` names one, set `MYSQL_HOST=` (empty) for the
command. In CI a MySQL service loaded with the synthetic fixture supplies the database,
and the workflow passes `--require-database`.

## Suites
- `ci`: checked by code alone against the tool body. No model calls, no network. Runs on
  every push against the synthetic fixture database, so it stays fast and deterministic.
- `local`: needs a model (a case with `input`) or the real database. Run it before
  closing a work order and record the result.
- `manual`: needs WhatsApp or a person's judgment. The runner only lists these cases;
  run them at the weekly demo and write down what happened.

### The local suite is a paid run
Each local case with `input` sends one request to the OpenAI chat completions API with
the `search_listings` tool; the tool-call arguments are then checked like a `ci` case.
Every such request costs money, so the runner calls the model only when all three hold:

- `OPENAI_API_KEY` is set,
- `IDX_EVAL_MODEL` names the model,
- `--allow-paid` is on the command line.

Otherwise `python -m evals.run --suite local` prints the cases it would run and which of
the three are missing, then exits without any call. Before a real run, a human grants a
`paid` consent token for that run (`docs/AGENT_RULES.md`); the agent's guard hook blocks
`--suite local` without one. Read the cost from the provider console afterwards, never
from an estimate, and log the outcome in `docs/EVIDENCE_LOG.md`.

## Where cases live
One YAML file per category under `evals/cases/`, for example
`evals/cases/property_search.yaml` and `evals/cases/safety.yaml`. A new case is a YAML
edit; a new category is a new file, and the runner finds both. Inside a file, group
cases by suite and put a comment above any case whose expected reading is not obvious.

## Case shape
```yaml
- id: search-ci-003           # unique across all files, prefixed by category
  category: property_search   # which area the case exercises
  suite: ci                   # ci | local | manual
  input_filters: {city: Oakland, property_subtype: House}
  expect: {clarification: {field: property_subtype, reason: unknown_subtype}}
  check: clarification        # how `expect` is compared with the actual result
```

A case has exactly one of `input` (the user's words; a model fills the tool schema, so
`local` or `manual` only) and `input_filters` (a raw filter mapping given straight to the
tool body; every `ci` case). Optional keys: `note`, `tool` (default `search_listings`).

## Check types
| Check | `expect` | Passes when |
|---|---|---|
| `filters_exact` | `filters` | the accepted filters equal `expect.filters`, nothing more or less |
| `filters_subset` | `filters` | every key in `expect.filters` is accepted with the same value |
| `clarification` | `clarification: {field, reason}` | validation asks back with that field and reason code |
| `rowcount_max` | `max_rows` (1 to 50) | a search ran and returned at most that many listings |
| `fields_absent` | `fields` (non-empty list) | none of the strings appears anywhere in the returned envelope; with valid filters, a search must have run |
| `regex` | `pattern` (must compile) | the pattern matches the envelope's message; with valid filters, a search must have run |
| `refusal` | optional `reason`, `category` | no query ran: valid filters fail at once; a Clarification passes unless a different `reason` is pinned; an error passes only when `category` names it; in the local suite, no tool call also passes |
| `human` | free form | never run; listed as `manual` for a reviewer |

An `expect` key the check does not use is a load error, and so is a value that breaks the
check's rules; the full list is in `docs/EVALUATION.md`.

Filters compare after `model_dump(exclude_defaults=True)`, so an expected object lists
only what the request pins down; `pool: false` is a real value and is compared. Reason
codes are listed in `docs/CONTRACTS.md`. Adding a check type is one entry in the
`CHECKS` registry in `evals/run.py` plus its row in `docs/EVALUATION.md`, in the same
commit.

## Rules
- Every work order after WO-004 adds cases for the area it touches and leaves the
  `ci` suite green.
- Cases use synthetic or placeholder values only: no real rows, no agent contact
  details, no copied reference text. Invented city names are fine for unknown-city cases.
- Deterministic facts (SQL results, arithmetic, approval state, retrieval hits) are
  checked by code, never by a model acting as judge.
- When a number moves, log it in `docs/EVIDENCE_LOG.md`.
