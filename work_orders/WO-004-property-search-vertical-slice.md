# WO-004 — Property-search vertical slice

**Driver:** agent builds; human runs the WhatsApp test and records it.
**Depends on:** WO-001 (routing and tool route), WO-002 (allowlist, migration), WO-003 (models)
**Estimated effort:** 3-4 hours

## Objective
"Find 3-bedroom homes in Pasadena under $1.5M" sent over WhatsApp returns up to five listing cards from
`rets_property`, through a typed tool, with parameterized SQL, the column allowlist, the 50-row cap,
the as-of date, and no agent contact fields. Nothing else.

## Why
The first real product path. It exposes every seam at once: channel, routing, parser, model, tool, SQL, formatting.

## Inputs
ADR-0003 (routing, tool route); ADR-0004 (query parsing); `src/idx_agent/domain/`; `src/idx_agent/safety/columns.py`; `docs/data/schema_notes.md`; `docs/CONTRACTS.md` (`search_listings`).

## In scope
- `src/idx_agent/db/pool.py`: connection pool from environment; refuses a user name other than the reader.
- `src/idx_agent/db/asof.py`: reads both as-of dates once and caches them.
- `src/idx_agent/db/listings.py`: `search_active_listings(filters, asof) -> list[Listing]`: builds SQL from
  `PropertySearchFilters` using only allowlisted columns, parameters for every value, the status definition from
  `schema_notes.md`, `LIMIT`/`OFFSET` bound safely (if the driver rejects bound limits, see Stop conditions), max 50.
- Query parsing (decided 2026-09-23, `docs/DECISIONS.md`): the model is the parser. It fills the typed
  `search_listings` schema, which is `PropertySearchFilters`; there is no regex or rule parser.
- Validation of the filled filters is already in code from WO-003: `PropertySearchFilters.from_input(raw)`
  returns either the validated filters or a `Clarification(field, reason, question, options)` (city in the valid
  set, known subtype, five-digit postal code, sane ranges, min not above max, a location required). This WO
  wires it into the tool: a `Clarification` comes back as the tool's result, no query runs, and the skill asks the
  suggested question. Nothing guesses or silently drops a value. No separate parser module.
- `src/idx_agent/mcp_server/server.py`: add `search_listings(<filter fields>) -> AgentResult[SearchResult | Clarification]`. It validates
  first, then searches, and returns the accepted filter object alongside the results (an `applied_filters` field,
  added to `docs/CONTRACTS.md`), so the parsing step can be shown on its own.
- `skills/property-search/SKILL.md`: how the model turns a request into a `search_listings` call, how it asks the
  suggested follow-up question on a needs-clarification result, how it presents results, and how it shows the
  accepted filters when the user asks what was searched.
- `src/idx_agent/channels/format.py`: WhatsApp card: address (or city/ZIP when a display flag forbids the street),
  city, price, beds/baths, sqft, days on market with the as-of note, photo count. No agent fields, ever.
- `evals/cases/property_search.yaml`: the 10 parser test queries as `suite: local` cases (a model fills the
  schema, then the expected filters or the expected clarification are checked). The validator and SQL builder
  are covered by unit tests in CI.
- README: the install section, so a grader can reproduce the slice.

## Out of scope
Market stats, semantic search, recommendations, RAG, email, multi-turn refinement beyond what OpenClaw's session gives for free, any second skill.

## Files expected to change
`src/idx_agent/db/*`, `src/idx_agent/mcp_server/server.py`, `src/idx_agent/channels/format.py`,
`src/idx_agent/domain/*` (only if `applied_filters` needs a field), `docs/CONTRACTS.md`,
`skills/property-search/SKILL.md`, `evals/cases/property_search.yaml`, `tests/*`, `README.md`.

## Interfaces and contracts
`search_listings` per `docs/CONTRACTS.md`; the filter fields in, `AgentResult[SearchResult | Clarification]` out; every result carries `provenance.as_of`
and the accepted filters; a needs-clarification result carries the field, the reason, and a suggested follow-up question.

## Implementation requirements
1. The SQL builder accepts column names only from the allowlist and raises on anything else.
2. All user-derived values are parameters; the builder's output is testable as (sql, params) without a database.
3. `limit` above 50 is clamped to 50 and a warning is added to the result.
4. Pagination works: page 2 returns different rows than page 1 for the same filters.
5. Unknown city, unknown subtype, or an out-of-range value: the tool returns the needs-clarification result
   (field, reason, suggested follow-up question); it never guesses and never searches with the bad value.
   The same result covers a request with no usable constraint at all.
6. The formatter is a pure function `Listing -> str` and never touches agent or deny-listed fields (it cannot: `Listing` has none).
7. Every tool call logs one structured line with trace id, tool, validated parameters, row count, duration; never remarks.
8. The result returns the accepted `PropertySearchFilters` as validated (city casing normalized), not the raw input.

## Safety requirements
Parameterized SQL; allowlist; row cap; reader user; no agent contact in cards; remarks never logged; shell tool off (from WO-001).

## Tests required
Unit (CI, no model): validator (12+ cases: unknown city, unknown subtype, city casing normalized, bad postal code,
min above max, beds and baths out of range, half-step baths, empty filters, each giving the right field and a
follow-up question); SQL builder (params only, allowlist violation raises, clamp, pagination offsets); the tool
returns `applied_filters`; formatter (no agent field names appear, display-flag case). A temporary
`tests/test_eval_cases.py` checks that the case file parses and that every expected filter object passes the
validator (no model call); the runner arrives in WO-005.
Integration (`@pytest.mark.db`): the Pasadena query returns 1-5 listings with the expected shape; page 2 differs; a request for 500 returns 50.
Evals (`local`, needs a model, so a human `paid` token per run): the 10 parser queries in
`evals/cases/property_search.yaml`, including the three known-bug cases ("homes in Oakland" leaves subtype empty,
"homes in Mountain View" leaves view empty, "without a pool" does not set pool) and an unknown city that must come
back as a clarification. How the run drives the model is recorded in Status with the result.
Manual: the WhatsApp flow, recorded in Status with the date and a redacted screenshot description.
Deferred until a dedicated number exists (deferred, not failed): an outside number gets no reply; two senders do
not share state. Both need a second phone; they run when the dedicated number is in place.

## Acceptance criteria
- The Pasadena request over WhatsApp returns up to five correct cards with an as-of note.
- All unit and integration tests pass locally; CI green (unit tests; integration skipped without a database).
- The 10 local parser eval cases pass in one recorded run (date and result in Status and `docs/EVIDENCE_LOG.md`).
- Asking "what did you search for" shows the accepted filters.
- No card, log line, or fixture contains an agent name, email, or phone.
- The two second-phone tests are marked deferred in Status; they do not block this work order.

## Verification commands
```
pytest -q                                  # unit
MYSQL_HOST=localhost pytest -q -m db       # integration, local only
pytest tests/test_eval_cases.py -q        # case file shape and expected filters, no model
# local parser evals: only with a human `paid` token for that run
python -m idx_agent.mcp_server.server && ./scripts/install.sh
# then send the Pasadena request from the allowlisted number
```

## Deliverables
The data layer, the filter validator, the search tool (with the accepted filters in its result), the skill,
the formatter, 10 local eval cases, README install section.

## Stop conditions
- The driver rejects bound `LIMIT`/`OFFSET` parameters: use the documented workaround and note it; do not interpolate.
- The status definition or a needed column is missing from `schema_notes.md`.
- OpenClaw needs the shell tool to call the search: stop; that reverses ADR-0003.

## Status
**Implemented on 2026-09-23; independently reviewed; awaiting CI, the owner-number WhatsApp
test, and the local parser eval run (needs a `paid` token).** Branch `wo-004-property-search`.

**Built**
- `db/pool.py`: `DbConfig.from_env()` (password out of repr), `database_configured()`,
  `connect()` refuses any user but `idx_reader` before pymysql is called; DictCursor,
  autocommit, connect/read timeouts, and a read-only session as a second guard.
- `db/asof.py`: active = latest `ModificationTimestamp` date; sold = latest close date not
  after the active date (drops the typo years); cached per process. Live values read:
  active 2026-09-18, sold 2026-09-17, matching WO-002.
- `db/listings.py`: `build_search_sql` is pure and testable as (sql, params). It selects
  exactly `listing_columns()` (every name through `check_column`), binds the status, adds
  one clause per set filter, orders by price then listing ids, binds LIMIT/OFFSET, and
  clamps a limit above 50 with a warning. `search_active_listings` maps rows with
  `to_listing`, skips invalid rows with a count and one warning, never logs a row.
- `mcp_server/server.py`: `search_listings` takes the filter fields as flat optional
  arguments (ADR-0004). Three outcomes: ok + `SearchResult(listings, applied_filters)`;
  ok + `Clarification` with the question as `message` and no query; ok=False + a `db`
  ToolError with a plain message (detail never leaves). One log line per call: trace id,
  validated filters, row count, duration; never remarks. The reply text is built by
  `channels.format`, so cards are deterministic and the model relays `message`.
- `channels/format.py`: `format_listing_card`, `format_search_reply` (at most 5 cards,
  "and N more"), `format_filters`; pure; remarks never read.
- `skills/property-search/SKILL.md` (hyphen: OpenClaw skill names allow only lowercase,
  digits, hyphens); config skill list `["health", "property-search"]`.
- `evals/cases/property_search.yaml`: 10 `local` parser cases and 3 `ci` validator cases;
  `tests/test_eval_cases.py` validates the file and the expected objects with no model.
  `docs/EVALUATION.md` records the format additions (`input_filters`, `clarification`).
- README install section; START_HERE table; CONTRACTS.md `SearchResult` and outcomes.
- Tests: 705 passed with `MYSQL_HOST=localhost` (698 unit + 7 db), invented rows only;
  ruff clean; the three content gates pass on every changed file.

**Review outcome (one blocker and five should-fix items, all applied)**
- Blocker: the MCP server process started by OpenClaw has no MYSQL_* variables, so it
  could never reach the database. `db/pool.py` now reads MYSQL_* from `<cwd>/.env` (else
  the repo root `.env`) as a fallback; the environment always wins. Verified live from a
  neutral directory: the Pasadena search returned five rows through the real code path.
- Remarks are dropped from the search payload (nothing in this slice uses them; they would
  otherwise reach the model and the transcript for up to 50 rows); a test proves a sentinel
  remark never leaves the server.
- Skipped rows were warned twice (db layer and server); the server's duplicate is gone.
- The reply renders every listing of the page (not the first five), the summary names the
  page, and `page` is bounded at 1000 so a huge offset is a Clarification, not a db error.
- An always-true `caplog` assertion in the SQL builder tests now checks captured stderr.
- Read timeout lowered to 15 s so connect plus read stays under the 30 s MCP request
  timeout; the integration as-of test asserts relationships instead of fixed dates.
- Recorded in `docs/CONTRACTS.md`: a `limit` above 50 is a Clarification at the tool
  boundary, so the SQL clamp is a second guard (WO requirement 3 read that way).

**Decisions**
- Postal code matches with `L_Zip LIKE '<five digits>%'`: the data holds 244 ZIP+4 values
  that equality would miss; the builder still requires five digits and the prefix keeps
  the index usable.
- Pool/view: True is `= '1'`; False is `COALESCE(col, '') <> '1'`, since empty and NULL
  both mean "not marked". "Without a pool" leaves the field unset (skill and eval case).
- HOA cap: rows with no fee pass; a fee passes only when its frequency is Monthly and at
  most the cap; other frequencies are not converted (WO-003 Open item stands).
- Ordering ties: three groups of rows share price and both listing ids; a full tiebreak
  needs the primary key `id`, which is not allowlisted. Left as is; noted for WO-005.
- `limit` above 50 is a Clarification at the model boundary (the schema rejects it) and a
  clamp with a warning below it; requirement 3 is met by the clamp for unvalidated input.
- The two second-phone tests stay deferred (not failed) until a dedicated number exists.

**Open (to record before Done)**
- WhatsApp test from the owner number: the Pasadena request, "what did you search for",
  and an unknown-city request. Date and a redacted description go here.
- The 10 local parser cases: one recorded run with a `paid` token; result here and in
  `docs/EVIDENCE_LOG.md` (WO-005 creates the file and the runner).
- How the sender id reaches a tool argument (ADR-0003 open item) is not needed by this
  WO; it moves to WO-006 (multi-turn memory).

Pre-work (2026-09-23, before the WO started):
- Parsing design decided (`docs/DECISIONS.md`, "Query parsing"): the model fills the `search_listings` schema, code
  validates strictly and returns a needs-clarification result instead of guessing, no regex parser. The scope,
  requirements, and tests above were rewritten to match; the 10 parser queries moved to the `local` suite.
- The second-phone tests (outside number gets no reply; two senders do not share state) are deferred until a
  dedicated number exists.
- Memory flush and dreaming are off in `config/openclaw.idx.json5`, as ADR-0003 required before this WO.
