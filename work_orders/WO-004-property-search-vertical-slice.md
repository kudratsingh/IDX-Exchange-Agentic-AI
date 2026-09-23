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
ADR-0002 (routing, tool route); `src/idx_agent/domain/`; `src/idx_agent/safety/columns.py`; `docs/data/schema_notes.md`; `docs/CONTRACTS.md` (`search_listings`).

## In scope
- `src/idx_agent/db/pool.py`: connection pool from environment; refuses a user name other than the reader.
- `src/idx_agent/db/asof.py`: reads both as-of dates once and caches them.
- `src/idx_agent/db/listings.py`: `search_active_listings(filters, asof) -> list[Listing]`: builds SQL from
  `PropertySearchFilters` using only allowlisted columns, parameters for every value, the status definition from
  `schema_notes.md`, `LIMIT`/`OFFSET` bound safely (if the driver rejects bound limits, see Stop conditions), max 50.
- `src/idx_agent/parser/rules.py`: deterministic parser v0: city, postal code, price bounds, beds, baths, sqft,
  subtype, pool, view, HOA. Returns `PropertySearchFilters` or a `ToolError(validation)` with a follow-up question.
  Must pass the seed cases in `docs/EVALUATION.md`.
- `src/idx_agent/mcp_server/server.py`: add `search_listings(filters) -> AgentResult[list[Listing]]`.
- `skills/property_search/SKILL.md`: how the model turns a request into a `search_listings` call and how it presents results.
  (If ADR-0002 chose our own router, the entry tool calls the parser and then the search.)
- `src/idx_agent/channels/format.py`: WhatsApp card: address (or city/ZIP when a display flag forbids the street),
  city, price, beds/baths, sqft, days on market with the as-of note, photo count. No agent fields, ever.
- `evals/cases/property_search.yaml`: the first 10 script-checkable cases (parser and SQL builder).
- README: the install section, so a grader can reproduce the slice.

## Out of scope
Market stats, semantic search, recommendations, RAG, email, multi-turn refinement beyond what OpenClaw's session gives for free, any second skill.

## Files expected to change
`src/idx_agent/db/*`, `src/idx_agent/parser/rules.py`, `src/idx_agent/mcp_server/server.py`, `src/idx_agent/channels/format.py`,
`skills/property_search/SKILL.md`, `evals/cases/property_search.yaml`, `tests/*`, `README.md`.

## Interfaces and contracts
`search_listings` per `docs/CONTRACTS.md`; `PropertySearchFilters` in, `AgentResult[list[Listing]]` out; every result carries `provenance.as_of`.

## Implementation requirements
1. The SQL builder accepts column names only from the allowlist and raises on anything else.
2. All user-derived values are parameters; the builder's output is testable as (sql, params) without a database.
3. `limit` above 50 is clamped to 50 and a warning is added to the result.
4. Pagination works: page 2 returns different rows than page 1 for the same filters.
5. Unknown city: the tool returns a validation error with a follow-up question; it never guesses.
6. The formatter is a pure function `Listing -> str` and never touches agent or deny-listed fields (it cannot: `Listing` has none).
7. Every tool call logs one structured line with trace id, tool, validated parameters, row count, duration; never remarks.

## Safety requirements
Parameterized SQL; allowlist; row cap; reader user; no agent contact in cards; remarks never logged; shell tool off (from WO-001).

## Tests required
Unit: parser (12+ cases including the three known-bug cases and an unknown city); SQL builder (params only, allowlist violation raises, clamp, pagination offsets); formatter (no agent field names appear, display-flag case).
Integration (`@pytest.mark.db`): the Pasadena query returns 1-5 listings with the expected shape; page 2 differs; a request for 500 returns 50.
Evals: the 10 cases in `evals/cases/property_search.yaml` pass with `python -m evals.run --suite ci` (the runner arrives in WO-005; until then a temporary `tests/test_eval_cases.py` executes them).
Manual: the WhatsApp flow, recorded in Status with the date and a redacted screenshot description.

## Acceptance criteria
- The Pasadena request over WhatsApp returns up to five correct cards with an as-of note.
- All unit and integration tests pass locally; CI green (unit tests; integration skipped without a database).
- The 10 eval cases pass.
- No card, log line, or fixture contains an agent name, email, or phone.

## Verification commands
```
pytest -q                                  # unit
MYSQL_HOST=localhost pytest -q -m db       # integration, local only
pytest tests/test_eval_cases.py -q
python -m idx_agent.mcp_server.server && ./scripts/install.sh
# then send the Pasadena request from the allowlisted number
```

## Deliverables
The data layer, parser v0, the search tool, the skill, the formatter, 10 eval cases, README install section.

## Stop conditions
- The driver rejects bound `LIMIT`/`OFFSET` parameters: use the documented workaround and note it; do not interpolate.
- The status definition or a needed column is missing from `schema_notes.md`.
- OpenClaw needs the shell tool to call the search: stop; that reverses ADR-0002.

## Status
not started
