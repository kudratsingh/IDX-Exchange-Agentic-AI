# WO-008 — Market analytics

**Driver:** agent builds (including the spike against the local database); human runs the WhatsApp test and records it.
**Depends on:** WO-004 (tool pattern, pool, as-of dates, formatter), WO-005 (eval runner, fixture in CI), WO-006
(merged first, for the one memory-interaction test; if it has not merged, that test waits and Status says so)
**Estimated effort:** 4-5 hours (the spike is time-boxed to 1 hour of that)

## Objective
A WhatsApp question such as "how is the market in Pasadena" or "median condo price in Glendale over the
last 3 months" returns one market card built from `california_sold` through a typed tool,
`get_market_stats`. The card carries a `MarketStats`: the sample count, the median close price, the median
days on market, the sale-to-list ratio with its plain reading, and a per-month trend over the months the
data holds (about six). The window counts back from the sold as-of date, never from today. Every excluded
row is counted and disclosed. Below a minimum sample the answer is "not enough comps" with the count, never
a median of two sales. Nothing else.

## Why
Week 5 asks for market figures for any California city, and it is the first feature where the numbers are
computed rather than listed, so a wrong median or a window counted from today would look plausible and be
wrong. Putting the math, the window, the exclusions, and the labels in tested code, with every number
reproducible against the fixture, is what makes the answer trustworthy.

## Inputs
`docs/TIMELINE.md` (Week 5 line); `docs/CONTRACTS.md` (`MarketStats`, `MonthRow`, `Geography`, `StatsWindow`,
`AgentResult`, the `get_market_stats` row); `docs/DECISIONS.md` (Analytics: deterministic, subtype-aware,
single-family as the default benchmark, mix disclosed; Time windows; Sale-to-list unit; the exclusions row);
`docs/data/schema_notes.md` (the sold table's columns and types, the as-of rule, the exclusions, the 34
repeated `ListingKey`s, sections 3, 7, 8, 9, 13); `docs/EVALUATION.md` (market analytics category, seed cases
"a fixed as-of date gives exact aggregates" and "a zero-comp city returns not enough comps", case format,
check types); `docs/SAFETY_INVARIANTS.md`; `src/idx_agent/domain/models.py` (`MarketStats` and friends,
`PropertySearchFilters.from_input` as the validation pattern); `src/idx_agent/domain/asof.py`
(`AsOfDates.window`); `src/idx_agent/domain/valid_values.py` (city and subtype sets);
`src/idx_agent/safety/columns.py` (sold allowlist); `src/idx_agent/db/listings.py` and `db/asof.py` (pure builder
plus executor); `src/idx_agent/mcp_server/server.py` (`_guarded`, outcomes, log line);
`src/idx_agent/channels/format.py`; `skills/property-search/SKILL.md` (skill style); `tests/fixtures/`
(generator, README, the sold groups); `evals/run.py` and `evals/cases/property_search.yaml`; WO-004 and WO-006
Status sections.

## In scope
- **Early-start spike (first task, before any build code; 1 hour; result recorded in Status).** Against the
  local database as `idx_reader`, aggregates only, no rows printed or saved. A small read-only script,
  `scripts/market_spike.py`, prints the numbers so the run can be repeated. Measure:
  (a) per-city sample sizes over 1, 3, and 6 months counted back from the sold as-of date, for single-family
  only and for all subtypes, after the exclusions below; report the distribution (quantiles) and the share of
  cities with at least one sale that fall under 5 and under 10, not a per-city table;
  (b) whether a median computed in MySQL is exact and fast: `SELECT VERSION()`; the order-statistics method
  (`ROW_NUMBER()` and `COUNT()` window functions picking the one or two middle rows) against the
  `ORDER BY ... LIMIT 1 OFFSET k` method with a bound offset, on the 20 cities with the most sales; both must
  give the same middle values; time the full set of statements for the largest city at 6 months with and
  without a subtype, and read `EXPLAIN` for index use (`ix_sold_city`, `ix_sold_postal`, `ix_sold_close_date`);
  (c) how many sold `PostalCode` values are not exactly five digits;
  (d) how far the single-family median sits from the all-subtype median in the 20 largest cities, and how many
  cities have enough sales in total but too few single-family sales.
  **Decision rule, minimum sample.** `MIN_SAMPLE` is 5 and is never lowered (below five, one sale moves the
  median). Raise it to 10 only if, at the 6-month default, the share of cities with any single-family sale that
  reach 10 is within 5 points of the share that reach 5. The monthly minimum for showing a month's median is 3
  and is not tuned.
  **Decision rule, no subtype.** `DECISIONS.md` already sets single-family as the default benchmark with the
  mix disclosed; the spike confirms it. A request without a subtype aggregates `SingleFamilyResidence` only and
  discloses the other subtypes' sale counts. If (d) shows that more than a quarter of the cities with enough
  sales in total would get "not enough comps" under that default, stop and ask; a switch to all subtypes changes
  a decided row and needs the human.
  **Decision rule, median in SQL.** Both methods agree and the largest city's full statement set runs in under
  2 s locally: medians come from SQL order statistics (see requirement 3). Between 2 s and 10 s: stop and ask
  (a composite index is a migration). Over 10 s, or the methods disagree: see Stop conditions. No path pulls
  the sample's rows into the tool process.
  **Decision rule, postal code.** (c) is 0: match `PostalCode = %s`; otherwise the same five-digit prefix
  match as search.
- `src/idx_agent/domain/models.py`: `MarketStatsRequest` with `from_input(raw)` returning the request or a
  `Clarification`, mirroring `PropertySearchFilters.from_input`: exactly one of `city` (in the valid city set,
  stored spelling returned) and `postal_code` (five digits); `property_subtype` in the valid subtype set;
  `months` a whole number from 1 to 24, default 6 when unset. The `MarketStats` validator is relaxed so figures
  and readings may be None whenever `low_sample` is true (today: only when the count is 0).
- `src/idx_agent/db/market.py`: `build_market_sql(request, window, as_of)` is pure and returns the statements
  as (sql, params) pairs; `fetch_market_aggregates(request, window, as_of, conn)` runs them and returns a
  `MarketAggregates` value (counts, the middle values per metric, month rows, subtype mix, exclusion counts).
  Only allowlisted columns, every value bound (city, ZIP, subtype, window dates, as-of dates, floors, offsets).
  Month buckets come from `close_date_d` (`DATE_FORMAT(close_date_d, '%Y-%m')`). The earliest valid close date
  is read once per process and cached next to the as-of dates, for the window fallback.
- Exclusions, applied in SQL and counted per request (same geography and subtype): close date after the active
  as-of date (the typo years); `close_date_d` NULL (unreadable close text); close date before
  `purchase_contract_date_d` (a NULL contract date is kept); `ClosePrice` or `ListPrice` under 25,000, which
  also removes zero and negative prices (the floor in `DECISIONS.md`); repeated `ListingKey`s inside the window
  sample collapsed to the latest close date (then the higher close price, then the higher list price, so the
  pick is fixed). `LivingArea` under 200 drops a sale from the price-per-sqft median only. Rows with a NULL
  subtype are never in a subtype sample and are shown as "unknown type" in the mix.
- `src/idx_agent/domain/market.py` (pure, no database): `median_from_middles`, `sale_to_list_reading`,
  `dom_band`, `market_lean`, `month_keys(window)`, and `build_market_stats(aggregates, request, window, as_of)`
  that turns the aggregates into a `MarketStats`, applies the minimum-sample rule, rounds, and writes the
  exclusion list. A reference `median(values)` over a plain list is here too, for the tests.
- Labels, fixed in this WO (a change is a human decision recorded in Status):
  - `dom_band` on the median days on market: `very_low` under 15, `low` 15 to under 30, `average` 30 to
    under 60, `high` 60 and over.
  - `sale_to_list_ratio`: the median of the per-sale ratios `ClosePrice / ListPrice` (final list price, not the
    original), rounded half-even to 3 decimals. `sale_to_list_reading` from that rounded ratio: the difference
    from 1 in whole percent, half-even; 0 reads "at asking", above "N% over asking", below "N% under asking".
  - `market_lean`, checked in this order on the rounded ratio and the median days on market: `seller` when the
    ratio is at least 1.000 and the median is under 30 days; else `buyer` when the ratio is under 0.980 or the
    median is 60 days or more; else `balanced`.
- `src/idx_agent/mcp_server/server.py`: `get_market_stats(city, postal_code, property_subtype, months)` as flat
  optional arguments (ADR-0004 style), body `market_result(raw, trace_id, log_fields)`, run through `_guarded`.
  Four outcomes (see Interfaces). The server `instructions` name the new tool.
- `src/idx_agent/channels/format.py`: `format_market_reply(stats, mix, as_of) -> str`, pure: the place and the
  subtype in words, the window and "sales to <sold as-of date>", the sample count, median price, median price per
  sqft, median days on market with its band, the ratio with its reading, the lean in words, the trend (one short
  line per month, months under the monthly minimum shown as "too few sales", the first and last month marked
  partial when the window cuts them), the exclusions line, and the other-subtypes line when a default subtype was
  used. The not-enough-comps reply names the count, the minimum, the window, and one widening step the tool can
  actually run (a longer window up to six months, or a subtype that has enough sales there); it never suggests
  another city.
- `skills/market-stats/SKILL.md` (hyphenated name) and `"market-stats"` in the `idx` agent's skill list in
  `config/openclaw.idx.json5`, with `tests/test_openclaw_merge_config.py` updated to the new list. The skill:
  when to use it (market, median or typical price, days on market, sale-to-list, "how is the market"), not for
  homes for sale; fill `city` or `postal_code`, `property_subtype` only when a type is named ("homes" and
  "houses" are not a type), `months` only when the user gives a period ("last quarter" is 3, "past year" is 12
  and the tool says what it used); a named year or date range is not converted, the skill states the data's
  coverage instead; relay `message` as it is; ask a Clarification's question; never add forecasts, advice, or
  facts that are not in the result.
- Fixture rows: the current sold rows come from the seeded draw, so their numbers are not hand-checkable. Add a
  hand-valued group to `tests/fixtures/make_synthetic.py` through a new `sold_exact(...)` helper (every value
  given, nothing drawn), appended after the existing groups so no earlier row changes: Monrovia (in the valid
  city set; add it to the generator's city table), about seven single-family sales across at least three
  calendar months (an odd count, one price tie, one sale on the sold as-of date, one on the first day of the
  1-month window and one the day before it, one fractional close price chosen so rounding before and after the
  median would differ), about four condominiums (an even count), and one row for each exclusion (close before
  contract, a repeated key with an earlier close, a close price under the floor, a typo-year close, a living area
  under 200 sqft); plus a city with three single-family sales (under the minimum). All values invented; the
  lint must pass; the fixture README's contents section is updated; `synthetic.sql` is regenerated, never
  hand-edited. The hand-computed expected numbers go into the case file with a comment saying how they were
  computed.
- Eval cases `evals/cases/market_stats.yaml`, category `market_analytics`. `ci` (about 14): exact aggregates for
  Monrovia single-family and condo against fixed numbers; the no-subtype default equals the single-family numbers
  and carries the mix line; the 1-month window keeps the first-day sale and drops the day-before sale; the trend
  rows exactly (months, counts, medians, a month with zero sales); the exclusion counts; Alhambra (zero comps)
  and the three-sale city return "not enough comps" with the right count; Glendale condo and single-family
  counts differ (subtype filter); an unknown city, `months: 0`, `months: 30`, and both city and ZIP each give the
  right Clarification; `months: 12` falls back to six months with a warning; no agent column, address, or
  listing key appears in the envelope. `local` (5 phrasing cases, a model fills the `get_market_stats` schema):
  "how is the market in Pasadena", "median condo price in Glendale over the last 3 months", "how fast are
  homes selling in 91101", "are townhouses in Irvine selling over asking", "single-family price trend in Burbank
  over the past six months"; "homes" leaves the subtype unset.
- `evals/run.py`, `docs/EVALUATION.md`, `evals/README.md`, `tests/test_evals_runner.py`: `get_market_stats` joins
  `TOOLS`; validation checks (`filters_exact`, `filters_subset`, `clarification`, `refusal`) dispatch to the
  tool's own `from_input`; `regex` and `fields_absent` accept the tool's own success type; a new check
  `stats_exact` (expect `stats`: a mapping of `MarketStats` fields, compared exactly, `trend` as a list; needs a
  database like `rowcount_max`); for this tool `input_filters` holds its arguments; the local driver sends only
  the case's tool and a system prompt for that tool. Documented in `docs/EVALUATION.md` in the same commit.
- Multi-turn memory: `get_market_stats` takes no sender id and never reads or writes the session store. A
  market question after a search leaves that sender's search state as it was, so "show me more" still pages the
  search. Market state across turns ("and for condos?") is out of scope.

## Out of scope
Forecasts or predictions of any kind; comp-validated pricing of a listing (Week 7); semantic search; charts,
images, or any attachment; anything that reads `rets_property` for market figures (the as-of dates query stays
as it is); per-sender market state or refinement; new indexes or migrations (a stop-and-ask); ZIP-to-city or
nearby-city widening; mean or percentile figures beyond those in `MarketStats`; converting named years or date
ranges into windows; changes to the search tool or skill beyond a test proving they are untouched.

## Files expected to change
`src/idx_agent/domain/models.py`, `src/idx_agent/domain/market.py` (new), `src/idx_agent/db/market.py` (new),
`src/idx_agent/db/asof.py` (only if the earliest close date is cached there), `src/idx_agent/mcp_server/server.py`,
`src/idx_agent/channels/format.py`, `skills/market-stats/SKILL.md` (new), `config/openclaw.idx.json5`,
`scripts/market_spike.py` (new), `tests/fixtures/make_synthetic.py`, `tests/fixtures/synthetic.sql`
(regenerated), `tests/fixtures/README.md`, `evals/cases/market_stats.yaml` (new), `evals/run.py`,
`evals/README.md`, `docs/EVALUATION.md`, `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md` (market-stats moves from
planned to present), `tests/test_market_math.py` (new), `tests/test_db_market.py` (new),
`tests/test_mcp_market.py` (new), `tests/test_domain_models.py`, `tests/test_format.py`,
`tests/test_db_integration.py`, `tests/test_evals_runner.py`, `tests/test_openclaw_merge_config.py`,
`tests/test_memory_store.py` or `tests/test_mcp_search.py` (the memory-interaction test), `README.md` (one
example line), `docs/EVIDENCE_LOG.md`, `docs/START_HERE.md` (the table row). An ADR only if the spike changes a
row in `DECISIONS.md`.

## Interfaces and contracts
```python
class MarketStatsRequest(_Frozen):                  # domain/models.py
    city: str | None = None
    postal_code: str | None = None
    property_subtype: str | None = None             # None -> SingleFamilyResidence, mix disclosed
    months: int = 6                                 # 1-24; 7-24 fall back to the data's coverage
    @classmethod
    def from_input(cls, raw: Mapping[str, object]) -> MarketStatsRequest | Clarification
    def geography(self) -> Geography

def build_market_sql(request: MarketStatsRequest, window: StatsWindow,
                     as_of: AsOfDates) -> MarketQuery          # pure; statements as (sql, params)
def fetch_market_aggregates(request: MarketStatsRequest, window: StatsWindow,
                            as_of: AsOfDates, conn: Any) -> MarketAggregates
def build_market_stats(aggregates: MarketAggregates, request: MarketStatsRequest,
                       window: StatsWindow, as_of: AsOfDates) -> MarketStats   # pure

def market_result(raw: Mapping[str, object], trace_id: str | None = None,
                  log_fields: dict[str, Any] | None = None) -> AgentResult[MarketStats | Clarification]
```
MCP tool: `get_market_stats(city=None, postal_code=None, property_subtype=None, months=None)` returns
`AgentResult[MarketStats | Clarification]`. Outcomes, all in one envelope:
- Stats: `ok=True`, `data` a `MarketStats` with `low_sample=False`, `message` the market card,
  `provenance.tables=["california_sold"]` with both as-of dates, exclusion and fallback notes in `warnings`.
- Not enough comps: `ok=True`, `data` a `MarketStats` with the real `sample_count`, `low_sample=True`, every
  figure and reading None, an empty trend, the exclusions still listed; `message` the not-enough-comps reply.
- Clarification: `ok=True`, `data` the `Clarification` (`missing_location`, `unknown_city`, `unknown_subtype`,
  `invalid_format`, `below_minimum`, `above_maximum`, or `invalid_value` for both city and ZIP), `message` its
  question; no query runs; as-of dates stay empty.
- Error: `ok=False`, a `ToolError` with category `db` (database missing or failing) or `internal`; `detail`
  never leaves the server.
`docs/CONTRACTS.md` gains `MarketStatsRequest`, the relaxed `MarketStats` rule, the flat arguments and the new
output type in the tools table, and these four outcomes, in the same commit as the code. `MonthRow`,
`Geography`, and `StatsWindow` stay as they are; the card derives partial months from the window.

## Implementation requirements
1. Every value in every statement is a bound parameter; column names pass `check_column("california_sold", ...)`;
   the builder's output is testable as (sql, params) without a database; an unknown column raises.
2. The window is `AsOfDates.window(months)`, which ends on the sold as-of date. Nothing in `domain/market.py`,
   `db/market.py`, or the tool body reads today's date. A window that would start before the earliest valid
   close date uses the data's full coverage instead, sets `window.months` to what was used, and says so in a
   warning.
3. Medians are exact, never approximated or sampled: SQL returns the one middle value (odd count) or the two
   middle values (even count) of each ordered sample, and `median_from_middles` averages two in `Decimal`.
   Prices and price per sqft are rounded half-even to whole dollars once, at the end, never per sale first.
   Median days on market may end in .5.
4. The aggregates cover the whole sample; no statement returns more than 50 rows (one summary row, at most 24
   month rows, at most 20 subtype rows, one exclusion-count row), and the executor raises if one does. No
   statement returns a listing key, an address, or any per-sale row.
5. `sample_count` is the number of sales after every exclusion. Under `MIN_SAMPLE` the result is the
   not-enough-comps outcome; at or above it, every figure and reading is filled. A month under the monthly
   minimum keeps its count and has `median_close_price=None`. The trend lists every calendar month the window
   touches, a month with no sales included, oldest first.
6. Each exclusion is counted; `exclusions_applied` holds one stable entry per rule with its count (for example
   `close_before_contract: 1`), and each non-zero count also appears in `warnings` in plain words.
7. Days on market is the stored `DaysOnMarket` (schema notes section 7: it differs from a derived value on
   about a third of rows); a NULL or negative value leaves that sale out of the days median only, and the count
   left out is disclosed.
8. A request without a subtype uses `SingleFamilyResidence` (per the spike's decision rule), sets
   `property_subtype` in the result to it, and the card lists the other subtypes' sale counts in the same window.
9. The labels follow the thresholds in In scope exactly; each boundary value has a unit test.
10. One log line per call, as in WO-004: trace id, tool, validated request, outcome (`stats`,
    `not_enough_comps`, `clarification`, `error`), sample count, exclusion counts, duration; never a row, an
    address, or a listing key.
11. Every expected number in the `ci` cases and the `db` tests is reproducible: it is computed by hand from the
    invented fixture values, written as a literal, and the same literal is checked by a unit test that runs the
    Python reference math over those values.
12. The tool never touches session state: it takes no sender id and does not import `idx_agent.memory`.

## Safety requirements
- Parameterized SQL only; the column allowlist; no `SELECT *`; the reader user through `pool.connect`;
  result sets under 50 rows by construction and by a check.
- No agent contact field is selected, logged, or returned: the builder names none, and a test asserts that no
  agent column from `columns.py` appears in any statement.
- No listing-level text in the payload or the log: no address, no listing key, no remarks (the sold table has
  none); `MarketStats` carries aggregates only.
- Time windows count back from the sold as-of date; the card and the payload carry `as_of`.
- Retrieved text is data: the tool acts on nothing it reads; the skill says so.
- The spike reads aggregates only as `idx_reader`; nothing from it is saved to a tracked file except the
  summary numbers written into Status.
- The local phrasing cases and the WhatsApp test are paid model turns: each run needs a human `paid` token.

## Tests required
Unit (CI, no model, no database):
- `MarketStatsRequest.from_input`: unknown city, unknown subtype, city casing normalized, bad ZIP, both city and
  ZIP, neither, `months` 0, 25, 2.5 and text, `months` unset gives 6; each Clarification has the right field and
  reason.
- SQL builder: params only (injection strings come back as parameters), allowlist violation raises, no agent
  column in any statement, window dates and floors bound, the postal-code form from the spike, month buckets on
  `close_date_d`, each exclusion clause present.
- Math on inline samples: median of odd and even counts, one value, all ties, two middles averaged in
  `Decimal`, rounding once at the end versus rounding first (the values differ); the ratio as close over list;
  the reading at 0, just over, and just under; `dom_band` at 14.5, 15, 29.5, 30, 59.5, 60; `market_lean` at
  each boundary and in the order given; the minimum-sample rule at 4, 5 (or the spike's value), and 0; month
  keys for a window that starts and ends mid-month; the six-month fallback.
- Tool: the four outcomes with a stubbed database; a Clarification runs no query; the log line carries no
  address or key (captured stderr); the payload JSON holds no agent field name; `format_market_reply` for stats
  and for not-enough-comps; a market call leaves a stored search session unchanged.
- The `MarketStats` validator: figures None allowed with `low_sample=True`, refused with `low_sample=False` and
  a positive count.
Integration (`@pytest.mark.db`, against the fixture): Monrovia single-family and condo aggregates equal the
fixed numbers; the 1-month window boundary; the trend rows; the exclusion counts; Alhambra returns zero comps;
the SQL order statistics match the Python reference over the fixture's own values; WO-004's `db` tests pass
unchanged.
Evals: the `ci` cases above pass with `--require-database`; the 5 `local` phrasing cases run once under a human
`paid` token, recorded in Status and `docs/EVIDENCE_LOG.md`.
Manual (human, owner number): "how is the market in Pasadena"; "median condo price in Glendale over the last 3
months"; a city the spike found under the minimum; an invented city; then a Pasadena search, a market question,
and "show me more", which must still page the search. Recorded in Status with the date and a redacted
description.

## Acceptance criteria
- The spike's numbers and the three decisions (minimum sample, no-subtype default, median in SQL) are in Status
  before any build commit.
- "How is the market in Pasadena" over WhatsApp returns one card with the sample count, median price, median
  days on market with its band, the sale-to-list ratio with its reading, the lean, a monthly trend, the
  exclusions line, and the sold as-of date.
- A request under the minimum returns "not enough comps" with the count and no figures; an unknown city returns
  the Clarification question; no query ran for it.
- Every `ci` case passes against the fixture, including exact aggregates, the window boundary, subtype
  filtering, and the zero-comp city; unit and `db` tests pass locally; CI is green.
- The local phrasing cases pass in one recorded run (date and result in Status and the evidence log).
- No statement result, log line, payload, or card holds an agent field, an address, or a listing key; the
  fixture lint passes on the new rows; no window is counted from today.
- `docs/CONTRACTS.md` matches the code; WO-004 and WO-006 tests pass unchanged.

## Verification commands
```
python scripts/market_spike.py                          # spike, local database, reader user, aggregates only
pytest -q tests/test_market_math.py tests/test_db_market.py tests/test_mcp_market.py
pytest -q                                               # unit
python tests/fixtures/make_synthetic.py && python scripts/fixture_lint.py tests/fixtures/synthetic.sql
MYSQL_HOST=localhost MYSQL_DATABASE=idx_fixture pytest -q -m db     # after loading the regenerated fixture
ruff check . && ruff format --check .
python -m evals.run --suite ci --category market_analytics --require-database
python -m evals.run --suite ci --require-database
# local phrasing cases: only with a human `paid` token for that run
# then, from the owner number, the manual flow above
```

## Deliverables
The spike script and its recorded result; `MarketStatsRequest`; the sold-table SQL builder and executor; the
pure market math and labels; the `get_market_stats` tool with four outcomes; the market card formatter; the
`market-stats` skill in the config list; the hand-valued fixture rows; about 14 `ci` and 5 `local` market cases
with the runner support; updated contracts, evaluation doc, and evidence log; one recorded WhatsApp run.

## Stop conditions
- The sold table lacks a column a metric needs, or a needed column is not in the allowlist.
- The fixture cannot reproduce the exact expected numbers (for example the generated date column or the double
  prices do not round-trip as the README describes).
- A median cannot be made exact within the request timeout on the real data (the two SQL methods disagree, or
  the largest city takes over 10 s), or it would need the sample's rows in the tool process; either touches the
  50-row invariant and needs the human.
- The spike argues against the single-family default, or the timing calls for a new index.
- A metric would need `rets_property`.
- The MySQL server lacks window functions and the bound-offset method is also unusable.

## Status
not started

Drafted 2026-09-24 (docs-only PR). Builds on WO-004's tool pattern and WO-005's runner and fixture; the one
memory-interaction test needs WO-006 merged. The label thresholds and the default window of six months are this
draft's proposals for the human to confirm at review.
