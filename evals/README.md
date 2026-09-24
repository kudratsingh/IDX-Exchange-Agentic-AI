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
python -m evals.run --suite ci --require-database --database-kind real   # real data
```

Options: `--suite ci|local|manual` (default `ci`), `--category NAME` and `--case ID`
(both repeatable), `--cases-dir PATH` (default `evals/cases`), `--out PATH` (default
`evals/last_run.json`), `--allow-paid` (local only), `--require-database` (a case that
would be skipped for "no database" fails instead; `CI=true` in the environment implies it),
`--database-kind fixture|real` (default `fixture`: every case runs; `real` skips the
fixture-only cases, below).

A selection that comes up empty is a failure, not a quiet green run: a `--case` or
`--category` that matches no case, or exists only in another suite (the detail names
which), a `--case` that `--category` leaves out, or a combination that selects nothing.

The runner prints one row per case (id, suite, check, result, detail), where result is
`pass`, `fail`, `skipped`, or `manual`, then a summary line. It writes a JSON report to
`--out` with the run time (UTC), suite, git commit, whether a database was configured,
the `database_kind`, whether one was required, every case's result, and the counts. The report is run
evidence, not source: never commit it. Exit code 1 when any case fails, a case file is
malformed, or the selection fails as above; else 0.

Cases that would run a query need a database. The runner uses the same settings as the
server (MYSQL_* in the environment, then `.env`); with none, those cases are `skipped`,
which is not a failure unless `--require-database` is given or `CI=true` is set. To run
without a database even when `.env` names one, set `MYSQL_HOST=` (empty) for the
command. In CI a MySQL service loaded with the synthetic fixture supplies the database,
and the workflow passes `--require-database`.

Fixture-only cases: a case whose expected numbers hold only for the synthetic fixture
rows (the exact market figures, the not-enough-comps counts) says `database: fixture`;
the default is `database: any`, and any other value is a load error. Against the real
database, run
`python -m evals.run --suite ci --require-database --database-kind real`: each
fixture-only case is `skipped` ("fixture-only case; real database run"), which is not a
failure even under `--require-database`, and every other case runs as usual.

## Suites
- `ci`: checked by code alone against the tool body. No model calls, no network. Runs on
  every push against the synthetic fixture database, so it stays fast and deterministic.
- `local`: needs a model (a case with `input`) or the real database. Run it before
  closing a work order and record the result.
- `manual`: needs WhatsApp or a person's judgment. The runner only lists these cases;
  run them at the weekly demo and write down what happened.

### The local suite is a paid run
Each local case with `input` sends one request to the OpenAI chat completions API with
only the case's own tool (`search_listings`, `get_market_stats`, or
`find_similar_listings`) at temperature 0 (so a
run repeats); the system prompt carries that tool's skill body (`property-search`,
`market-stats`, or `similar-listings`, frontmatter stripped), as the live gateway shows it to the model, so
choices such as "start over" or "homes is not a type" are tested the way they run in
production; the tool-call arguments are then checked like a `ci` case. A local
`find_similar_listings` case that reaches the tool also embeds its text with the
provider (one more paid call), including the judged cases, which have `input_filters`
and no model call.
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
`local` or `manual` only) and `input_filters` (the tool's raw arguments given straight to
the tool body; every `ci` case). Optional keys: `note`, `tool` (default
`search_listings`; `get_market_stats` for market cases, `find_similar_listings` for
semantic cases), `database` (`fixture` or `any`, above), `index_as_of` (below).
Validation checks use the named
tool's own `from_input`, and a check the tool does not support is a load error
(`turns` is search-only, `rowcount_max` is for search and similar listings,
`stats_exact` is market-only, `ranked_keys` and `recall_at_k` are similar-listings
only). A conversation uses `turns` instead; see "Conversations" below.

```yaml
- id: market-ci-013
  category: market_analytics
  suite: ci
  tool: get_market_stats
  input_filters: {city: Glendale, property_subtype: Condominium}
  expect: {stats: {property_subtype: Condominium, sample_count: 3, low_sample: true}}
  check: stats_exact
```

## Check types
| Check | `expect` | Passes when |
|---|---|---|
| `filters_exact` | `filters` | the accepted filters equal `expect.filters`, nothing more or less |
| `filters_subset` | `filters` | every key in `expect.filters` is accepted with the same value |
| `clarification` | `clarification: {field, reason}` | validation asks back with that field and reason code |
| `rowcount_max` | `max_rows` (1 to 50) | a search ran and returned at most that many listings (or a similar-listings search at most that many matches) |
| `fields_absent` | `fields` (non-empty list) | none of the strings appears anywhere in the returned envelope; with valid input, the tool's query must have run (a SearchResult, MarketStats, or SimilarResult came back) |
| `regex` | `pattern` (must compile) | the pattern matches the envelope's message; with valid input, the tool's query must have run |
| `refusal` | optional `reason`, `category` | no query ran: valid filters fail at once; a Clarification passes unless a different `reason` is pinned; an error passes only when `category` names it; in the local suite, no tool call also passes |
| `stats_exact` | `stats` (MarketStats fields), optional `warning` | market only: every listed field equals the result's exactly (`trend` as the full list of month rows); `warning`, a regex, must match one of the warnings; needs a database |
| `ranked_keys` | `keys` (1 to 10 invented fixture keys), optional `warning` | similar listings only: the matches' listing keys equal `keys` in rank order, exactly; `warning`, a regex, must match one of the warnings; needs a database |
| `recall_at_k` | `query_id`, `k` (1 to 10), optional `none_relevant` | similar listings, local judged cases: recall@k and precision@k of the top k against the human's marks (the file `IDX_SEMANTIC_JUDGMENTS` names, under `data/`); skipped without the file or with no row marked relevant, unless `none_relevant: true` expects exactly that |
| `human` | free form | never run; listed as `manual` for a reviewer |
| `turns` | none; each turn has its own | every turn of a conversation passes, in order (below) |

An `expect` key the check does not use is a load error, and so is a value that breaks the
check's rules; the full list is in `docs/EVALUATION.md`.

## Similar-listing cases
`evals/cases/semantic_retrieval.yaml` calls `find_similar_listings` (`similar_result`).
In the `ci` suite the runner builds the CI fixture index once per run, on the first case
that reaches the tool, from the fixture generator's rows with the `test:hashing`
embedder, in a temporary directory; it points the tool at it through
`IDX_SEMANTIC_INDEX_DIR`, `IDX_EMBED_MODEL=test:hashing`, and `IDX_EMBED_DIMS`, and puts
those settings back at the end of the run. No provider is called and nothing is written
under `data/`. A case with `index_as_of: 2026-09-10` gets a copy of that index dated
2026-09-10, to test the stale-index warning. `tests/test_similar_cases.py` recomputes
every `ranked_keys` literal from the generator's rows.

The ten judged queries are `local` cases (`recall_at_k`, run once after the full
build under a human `paid` token, with `--database-kind real`); the human's marks sit in
a JSON file under `data/semantic/judging/` (written by `scripts/semantic_spike.py
--score`, keyed by case id), named by `IDX_SEMANTIC_JUDGMENTS`, so no real listing key
is ever tracked. Format and formulas: `docs/EVALUATION.md`, "Similar-listing
cases".

```
python -m evals.run --suite ci --category semantic_retrieval --require-database
```

Filters compare after `model_dump(exclude_defaults=True)`, so an expected object lists
only what the request pins down; `pool: false` is a real value and is compared. Reason
codes are listed in `docs/CONTRACTS.md`. Adding a check type is one entry in the
`CHECKS` registry in `evals/run.py` plus its row in `docs/EVALUATION.md`, in the same
commit.

## Conversations (`check: turns`)
Memory cases (`evals/cases/memory.yaml`) are conversations: a `turns` list whose turns
run in order against the tool body, one call each, so a turn sees the state the earlier
ones left. Each turn has `input_filters` (or `input` in a local case), `expect`, and
`check`, using the check types above; `mode` and `clear` go in `input_filters`. In a
turn, `filters_exact` compares the result's `applied_filters`, the merged filters the
search used. A turn may add `warning` (a regex one of the result's warnings must match).

```yaml
- id: memory-ci-007
  category: multi_turn_memory
  suite: ci
  check: turns
  turns:
    - input_filters: {city: Pasadena}
      expect: {filters: {city: Pasadena}}
      check: filters_exact
    - input_filters: {mode: more}
      expect: {filters: {city: Pasadena, page: 2}}
      check: filters_exact
```

Sender-label rule: senders are labels such as `sender-a` and `sender-b` (case-level
`sender_id`, or per turn), never ids. At run time the runner derives a fictional-range
id from each label (`1555010` plus 4 digits from a hash of the label) and never writes
it anywhere: not to a case, the report, or a log. A `sender_id` inside `input_filters`
is a load error in any case, single-call cases included. The runner sets IDX_SENDER_KEY
to a test value for the case unless a usable key is already set, and empties the session
store before and after each case; a tool module without `reset_store_for_tests` fails
the case. Every conversation needs a database (skipped without
one, failed under `--require-database`). In a local conversation, the model gets the
earlier turns (words and reply text) before each new message. Details:
`docs/EVALUATION.md`, "Multi-turn cases".

## Rules
- Every work order after WO-004 adds cases for the area it touches and leaves the
  `ci` suite green.
- Cases use synthetic or placeholder values only: no real rows, no agent contact
  details, no copied reference text. Invented city names are fine for unknown-city cases.
- Deterministic facts (SQL results, arithmetic, approval state, retrieval hits) are
  checked by code, never by a model acting as judge.
- Expected aggregates (`stats_exact`) are computed by hand from the invented fixture
  rows, with the arithmetic in a comment above the case, and a unit test
  (`tests/test_market_cases.py`) recomputes each one with the Python reference math.
- Expected ranked keys (`ranked_keys`) are invented fixture keys only, and a unit test
  (`tests/test_similar_cases.py`) recomputes each list with the hashing embedder.
- When a number moves, log it in `docs/EVIDENCE_LOG.md`.
