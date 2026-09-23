# Evals

Golden cases that tell us whether a change made the assistant better or worse.
The cases start arriving in WO-004; the runner (`evals/run.py`) lands in WO-005.
The full plan, including category sizes and metrics, is in `docs/EVALUATION.md`.

## Where cases live
One YAML file per category under `evals/cases/`, for example
`evals/cases/property_search.yaml`. Each file is a list of cases.

## Case shape
```yaml
- id: search-003              # unique, stable, prefixed by category
  category: property_search   # which area the case exercises
  suite: ci                   # ci | local | manual
  input: "3 bedroom homes in Pasadena under $1.5M"
  expect: {filters: {city: Pasadena, min_beds: 3, max_price: 1500000}}
  check: filters_exact        # how `expect` is compared with the actual result
```

## Suites
- `ci`: checked by a script alone. No model calls. Runs on every push against the
  synthetic fixture database, so it must stay fast and deterministic.
- `local`: needs a model or the real database. Run it before closing a work order
  and record the result.
- `manual`: needs WhatsApp or a person's judgment. Run it at the weekly demo and
  write down what happened.

## Check types
| Check | Passes when |
|---|---|
| `filters_exact` | the parsed filters equal `expect.filters`, nothing more or less |
| `filters_subset` | every key in `expect.filters` is present with the same value |
| `rowcount_max` | the result has no more rows than the stated maximum |
| `fields_absent` | none of the listed fields appear anywhere in the output |
| `refusal` | the assistant declines and makes no tool call |
| `regex` | the reply matches the given pattern |
| `human` | a reviewer marks it pass or fail; usually a `manual` case |

## Rules
- Every work order after WO-004 adds cases for the area it touches and leaves the
  `ci` suite green.
- Cases use synthetic or placeholder values only: no real rows, no agent contact
  details, no copied reference text.
- Deterministic facts (SQL results, arithmetic, approval state, retrieval hits) are
  checked by code, never by a model acting as judge.
- When a number moves, log it in `docs/EVIDENCE_LOG.md`.
