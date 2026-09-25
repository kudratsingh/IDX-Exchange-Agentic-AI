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
python -m evals.run --suite local --category routing   # prints the plan; no call
```

Options: `--suite ci|local|manual` (default `ci`), `--category NAME` and `--case ID`
(both repeatable), `--cases-dir PATH` (default `evals/cases`), `--out PATH` (default
`evals/last_run.json`), `--allow-paid` (local only), `--require-database` (a case that
would be skipped for "no database" fails instead; `CI=true` in the environment implies it),
`--database-kind fixture|real` (default `fixture`: every case runs; `real` skips the
fixture-only cases, below), `--skills-dir PATH` (routing cases only: the skills folder the
routing prompt reads, default the repo's `skills/`; see "Routing cases"),
`--no-temperature` and `--reasoning-effort VALUE` (routing cases only: leave
`temperature` out of, or add `reasoning_effort` to, every routing request).

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
only the case's own tool (`search_listings`, `get_market_stats`,
`find_similar_listings`, `recommend`, or `rag_answer`) at temperature 0 (so a
run repeats); the system prompt carries that tool's skill body (`property-search`,
`market-stats`, `similar-listings`, `recommend`, or `docs-qa`, frontmatter stripped), as the live gateway shows it to the model, so
choices such as "start over" or "homes is not a type" are tested the way they run in
production; the tool-call arguments are then checked like a `ci` case. A local
`find_similar_listings` case that reaches the tool also embeds its text with the
provider (one more paid call), including the judged cases, which have `input_filters`
and no model call; so does a local `rag_answer` case served a hybrid index (the
question is embedded). A local routing case (`route_exact`, below) is the exception to
"only the case's own tool": it sends every skill and all six tools, and up to 4 chat
requests per case, which the plan counts.
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
semantic cases, `recommend` for recommendation cases, `rag_answer` for document-answer
cases), `database` (`fixture` or `any`, above), `index_as_of` (below).
Validation checks use the named
tool's own `from_input`, and a check the tool does not support is a load error
(`turns` is search-only, `rowcount_max` is for search, similar listings, and recommend,
`stats_exact` is market-only, `ranked_keys` is for similar listings and recommend,
`recall_at_k` is similar-listings only, `price_check_exact` and `error_category` are
recommend only, `chunks_from` is rag_answer only). A conversation uses `turns`
instead; see "Conversations" below.

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
| `rowcount_max` | `max_rows` (1 to 50) | a search ran and returned at most that many listings (or a similar-listings search at most that many matches, or recommend at most that many recommendations) |
| `fields_absent` | `fields` (non-empty list) | none of the strings appears anywhere in the returned envelope; with valid input, the tool's query must have run (a SearchResult, MarketStats, SimilarResult, or RecommendationResult came back) |
| `regex` | `pattern` (must compile) | the pattern matches the envelope's message; with valid input, the tool's query must have run |
| `refusal` | optional `reason`, `category` | no query ran: valid filters fail at once; a Clarification passes unless a different `reason` is pinned; an error passes only when `category` names it; in the local suite, no tool call also passes |
| `stats_exact` | `stats` (MarketStats fields), optional `warning` | market only: every listed field equals the result's exactly (`trend` as the full list of month rows); `warning`, a regex, must match one of the warnings; needs a database |
| `ranked_keys` | `keys` (1 to 10 invented fixture keys), optional `warning` | similar listings and recommend: the matches' (or recommendations') listing keys equal `keys` in rank order, exactly; `warning`, a regex, must match one of the warnings; needs a database |
| `price_check_exact` | `subject` (CompEvidence fields), optional `ranks` (`{1: {...}}`) | recommend only: every listed field of the subject's price check equals the result's; with `ranks`, exactly that many recommendations came back (`{}` pins none) and each rank's listed fields match its check; needs a database |
| `error_category` | `category` | recommend only: the tool ran and answered with an error of that category (for example `not_found` for an unknown listing key); needs a database |
| `chunks_from` | `sources` (chunk ids `doc#key`), `top` (1 to 4), optional `exact` | rag_answer only: the answer was found and each listed id is among its first `top` chunks; with `exact: true` the first `top` ids equal `sources` in order; needs no database |
| `recall_at_k` | `query_id`, `k` (1 to 10), optional `none_relevant` | similar listings, local judged cases: recall@k and precision@k of the top k against the human's marks (the file `IDX_SEMANTIC_JUDGMENTS` names, under `data/`); skipped without the file or with no row marked relevant, unless `none_relevant: true` expects exactly that |
| `human` | free form | never run; listed as `manual` for a reviewer |
| `turns` | none; each turn has its own | every turn of a conversation passes, in order (below) |
| `route_exact` | `route` (0 to 3 tool names), optional `filters` (one mapping per step); or `route_any_of` (several such routes), optional `filters_any_of` (one `filters` list per option) | local routing cases, no `tool` key: the model, shown every skill and tool, called exactly those tools (or one option's) in that order (`[]`: none), and each non-empty subset of that route matches its step's arguments (below) |

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

## Recommendation cases
`evals/cases/recommendations.yaml` calls `recommend` (`recommend_result`). Its `ci`
cases that reach the tool get the same CI fixture index (the subject's stored vector
ranks its neighbours, so nothing is embedded) and are `database: fixture`. Each
`price_check_exact` literal (count, level, percentage, sentence) is worked out by hand
in a comment above its case, and `tests/test_recommend_cases.py` recomputes it with
`reference_price_check` over the generator's sold rows, and each `ranked_keys` list
with the hashing index. The five `local` cases are phrasing checks (paid).

```
python -m evals.run --suite ci --category recommendations --require-database
```

## Document-answer cases
`evals/cases/rag.yaml` calls `rag_answer` (`rag_result`). The tool reads a document
index and never the database, so its cases always run, with or without one. In the
`ci` suite the runner builds a fixture document index once per run, on the first case
that reaches the tool, with `tests/rag_fixture.py`: the invented, own-words corpus under
`tests/fixtures/docs/` plus the tracked schema notes and glossary, lexical route, in a
temporary directory; it points the tool at it through `IDX_RAG_INDEX_DIR` (with
`IDX_RAG_FLOOR_BM25` and `IDX_RAG_FLOOR_COSINE` set empty, so the fixture keeps its own
floors), and at the end of the run puts the settings back, calls `reset_rag_for_tests()`, and removes the
directory. No PDF is read and no provider is called. `tests/test_rag_cases.py`
recomputes every `chunks_from` literal from that corpus with the real chunker and
retrieval, so a literal and the code cannot drift apart. The five `local` cases are
phrasing checks against the real index the settings name (paid; see above).

```
python -m evals.run --suite ci --category rag      # no database needed
```

Filters compare after `model_dump(exclude_defaults=True)`, so an expected object lists
only what the request pins down; `pool: false` is a real value and is compared. Reason
codes are listed in `docs/CONTRACTS.md`. Adding a check type is one entry in the
`CHECKS` registry in `evals/run.py` plus its row in `docs/EVALUATION.md`, in the same
commit.

## Routing cases (`check: route_exact`)
`evals/cases/routing.yaml` (category `routing`, WO-013) checks which skill and tool the
model picks, and in what order, when it can see all of them. Each of its 24 `local`
cases gives the model a routing prompt (a short base prompt, then the MCP server's
`instructions` under the line "Tool server instructions:", as the live model always
sees them, then every skill in the
`idx` agent's skill list in `config/openclaw.idx.json5` as its name and description,
then every skill body without its frontmatter, in the config's order) and all six tool
schemas. Each tool call is answered with a fixed stub that holds no data, and the model
is called again until it replies with no tool call; still calling tools at the fourth
model call fails the case ("too many calls"). No tool body runs, no database is read,
nothing is embedded.

```yaml
- id: routing-local-010
  category: routing
  suite: local
  history:                      # optional: earlier turns, own words, fixture keys only
    - user: "Homes in Monrovia"
      tool_calls:               # optional, with tool_result: the call that answered
        - {name: search_listings, arguments: {city: Monrovia}}
      tool_result: "ok. Showing 2 active listings ... Listing 9130009 ..."
      assistant: "1. Listing 9130008, a house at $849,000 ..."
  input: "How is the market in Monrovia, and is the second one priced right?"
  expect:
    route: [get_market_stats, recommend]            # [] means no tool call
    filters: [{city: Monrovia}, {listing_key: 9130009, k: 0}]   # optional; {} skips a step
  check: route_exact
```

A routing case names no `tool` and is never `ci`. A `filters` item is compared as
`filters_subset` compares a case's filters (the step tool's validator, `sender_id`
dropped); search's `mode` is compared as sent, so "show me more" is `{mode: more}`, and
so is every argument of a search in `update` mode (a refinement carries its city over
in code). A case that accepts more than one route gives `route_any_of` (a list of
routes) and, optionally, `filters_any_of` (one `filters` list per option) instead of
`route` and `filters`; it passes when the calls equal any option. The injection case
with a real search inside is `route_any_of: [[], [search_listings]]`: the search is
allowed but not required, and a call the injected part caused fails. A history turn
with `tool_calls` (each `{name, arguments}`, invented, no `sender_id`) and `tool_result`
(own-words text) is sent as the model saw it live: the user message, the assistant's
call(s), one tool message per call holding `{"ok": true, "message": <the result text>}`
(matching ids), then the reply.
Numbers of six or more digits in `input` or `history` must be invented fixture keys;
write prices in text with commas. A `note` that starts with `row: <intent>` names the
`docs/ROUTING.md` row a case covers. Full rules and load errors: `docs/EVALUATION.md`,
"Routing cases". The one `manual` case holds the 12-message WhatsApp script.

The routing suite is a paid run, measured twice: once before the skill wording changes
(the baseline) and once after, each under its own human `paid` token. So the baseline
can be taken after the wording has changed on the branch, `--skills-dir` points the
routing prompt at another skills folder. It swaps only the skills: the server
`instructions` in the prompt always come from the working tree. The main checkout is `IDX-Exchange-Agentic-AI`
and each branch's worktree sits beside it under `../worktrees/<branch>`, so from a
worktree the unchanged skills on `main` are:

```
python -m evals.run --suite local --category routing --allow-paid \
  --no-temperature --reasoning-effort none \
  --skills-dir ../../IDX-Exchange-Agentic-AI/skills
```

The plan and the report (`skills_dir`) record the folder used. The gateway model,
`gpt-5.6-terra`, needs `--no-temperature --reasoning-effort none` on the
chat-completions endpoint the runner calls; with them the run is a proxy for the
gateway's own calls, which go to the responses endpoint. The plan prints the request
shape and the report records `temperature_omitted` and `reasoning_effort`. Nothing is
retried: an HTTP 400 fails its case with a short fragment of the provider's message
(the key masked).

Acceptance (the human's decision of 2026-09-25): at least 23 of 24 in two consecutive
runs, both with `--no-temperature --reasoning-effort none`, each under its own human
`paid` token; the one allowed miss is never a mixed-intent case. With `temperature`
refused, one run is not repeatable, so one good run is
not enough.

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
- Expected price checks (`price_check_exact`) are computed by hand from the invented
  fixture rows, with the arithmetic in a comment above the case, and
  `tests/test_recommend_cases.py` recomputes each one with the comps reference.
- When a number moves, log it in `docs/EVIDENCE_LOG.md`.
