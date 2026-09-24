# Evals

Golden cases that tell us whether a change made the assistant better or worse.
The first cases arrived in WO-004 (`cases/property_search.yaml`); the runner
(`evals/run.py`) lands in WO-005. The full plan, including category sizes and metrics,
is in `docs/EVALUATION.md`.

## Where cases live
One YAML file per category under `evals/cases/`, for example
`evals/cases/property_search.yaml`. Each file is a list of cases, grouped by suite
inside the file (the `local` cases first, then the `ci` ones), with a comment above
any case whose expected reading is not obvious.

## Case shape
```yaml
- id: search-003              # unique, stable, prefixed by category
  category: property_search   # which area the case exercises
  suite: ci                   # ci | local | manual
  input: "3 bedroom homes in Pasadena under $1.5M"
  expect: {filters: {city: Pasadena, min_beds: 3, max_price: 1500000}}
  check: filters_exact        # how `expect` is compared with the actual result
```

### Additions used by `property_search.yaml` (recorded in `docs/EVALUATION.md`)
- `input_filters`: a raw filter mapping in place of `input`, for `ci` cases that need
  no model. It is passed straight to `PropertySearchFilters.from_input`, and the outcome
  is compared with `expect`. A `local` case has `input` (the user's words); a `ci` case in
  this file has `input_filters`.
- `expect: {clarification: {field: city, reason: unknown_city}}`: the request must come
  back as a `Clarification` with that field and reason code (codes are listed in
  `docs/CONTRACTS.md`), and no search runs.
- Check type `clarification`: passes when the outcome is a `Clarification` whose `field`
  and `reason` equal the expected ones. The question text is not compared.
- Filter comparison: the accepted filters are compared after
  `model_dump(exclude_defaults=True)`, so unset fields, `None`, and the default `page`
  and `limit` are left out. An expected object lists only what the request pins down;
  `pool: false` is a real value and would be compared.

## Suites
- `ci`: checked by a script alone. No model calls. Runs on every push against the
  synthetic fixture database, so it must stay fast and deterministic.
- `local`: needs a model or the real database. Run it before closing a work order
  and record the result. A run that calls a model is a paid run: it needs a human
  `paid` consent token for that run (`docs/AGENT_RULES.md`), and its cost is read from
  the provider console.
- `manual`: needs WhatsApp or a person's judgment. Run it at the weekly demo and
  write down what happened.

The ten parser queries in `property_search.yaml` are `local`: a model fills the
`search_listings` schema from `input`, `from_input` validates it, and the outcome is
checked against `expect` (ADR-0004). The validator itself is covered in CI by unit tests
and by the `ci` cases in the same file.

## Check types
| Check | Passes when |
|---|---|
| `filters_exact` | the parsed filters equal `expect.filters`, nothing more or less |
| `filters_subset` | every key in `expect.filters` is present with the same value |
| `clarification` | the result is a Clarification with the expected `field` and `reason` |
| `rowcount_max` | the result has no more rows than the stated maximum |
| `fields_absent` | none of the listed fields appear anywhere in the output |
| `refusal` | the assistant declines and makes no tool call |
| `regex` | the reply matches the given pattern |
| `human` | a reviewer marks it pass or fail; usually a `manual` case |

## Until the runner exists (WO-004 to WO-005)
`tests/test_eval_cases.py` is a temporary pytest module that makes no model call:

```
pytest tests/test_eval_cases.py -q
```

It checks that the case file parses, that every case has the required keys and a known
suite and check, that every expected filter object passes `from_input` unchanged (so an
expectation can never be one the validator would refuse), that every expected
clarification uses a documented reason code, and that each `ci` case gives its expected
outcome. It runs with the rest of `pytest -q`, so it is part of CI. It reads YAML with
PyYAML, which the `dev` extra installs through pre-commit; no dependency was added.
WO-005 replaces it with `evals/run.py`, which also drives the `local` suite behind the
`paid` consent check.

## Rules
- Every work order after WO-004 adds cases for the area it touches and leaves the
  `ci` suite green.
- Cases use synthetic or placeholder values only: no real rows, no agent contact
  details, no copied reference text. Invented city names are fine for unknown-city cases.
- Deterministic facts (SQL results, arithmetic, approval state, retrieval hits) are
  checked by code, never by a model acting as judge.
- When a number moves, log it in `docs/EVIDENCE_LOG.md`.
