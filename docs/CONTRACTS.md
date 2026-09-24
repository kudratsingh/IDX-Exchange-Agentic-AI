# Contracts

Pydantic models in `src/idx_agent/domain/` and the MCP tool signatures. Anything that
crosses a boundary (parser -> tool, tool -> agent, agent -> channel) uses these and
nothing else. Exact fields may change; the boundary concepts do not. Changing a
contract means updating this file, the tests, and, if more than one component is
affected, an ADR.

## Domain models
**PropertySearchFilters** — validated hard constraints from user language. The model fills
this schema as the `search_listings` arguments; code validates it strictly. Every field is
optional (None or a default), city included.
`city: str|None` (in the valid city set, casing normalized, stored spelling returned) ·
`postal_code: str|None` (5 digits) ·
`min_price, max_price: int|None` (>= 0, min <= max) · `min_beds: int|None` (0-20) ·
`min_baths: float|None` (0-20, half steps) · `min_sqft: int|None` · `property_subtype: str|None`
(in the valid subtype set) · `pool, view: bool|None` · `max_hoa_monthly: int|None` ·
`page: int = 1` (>= 1) · `limit: int = 5` (1-50).
`PropertySearchFilters.from_input(raw)` returns the filters or a Clarification and never raises
on bad user data. The first validation error becomes the Clarification; a search with neither
`city` nor `postal_code` gets reason `missing_location`. Never a guess.

**Clarification** — a follow-up question returned instead of a search.
`field: str` (the filter name; `unknown` when the key is not a plain snake_case name) ·
`reason: str` (stable code: `missing_location`, `unknown_city`, `unknown_subtype`, `min_above_max`,
`not_half_step`, `below_minimum`, `above_maximum`, `invalid_format`, `unsupported_filter`,
`invalid_value`) · `question: str` (plain language; names the field, never repeats the user's value) ·
`options: list[str]|None` (only for small sets: the subtypes, or the supported filter names; never the city list).

**SoftPreferences** — `terms: list[str]`; free-text descriptors used only for semantic ranking, never in SQL.

**Listing** — canonical, RESO-named, no agent contact fields, no deny-listed fields.
`listing_key: int` · `listing_id: str` · `address: str|None` (blank if display flags forbid) ·
`city` · `postal_code` · `list_price: int` · `bedrooms: int|None` · `bathrooms: float|None` ·
`living_area: int|None` · `property_subtype` · `status` · `year_built: int|None` ·
`hoa_fee_monthly: int|None` · `days_on_market: int|None` (as of the data pull) · `photo_count: int` ·
`latitude, longitude: float|None` · `pool, view, fireplace: bool|None` · `remarks: str|None` (untrusted text; never logged).

**SearchResult** (WO-004) — what `search_listings` puts in `AgentResult.data` when a search ran.
`listings: list[Listing]` (at most 50) · `applied_filters: PropertySearchFilters` (the validated
object the query used, city in its stored spelling; never the raw arguments; after a
follow-up, the merged object) · `total_matches: int|None` (WO-006: every match, not just the
page; set whenever it is known, on any page; None only if the count could not be read) ·
`narrowing_question: str|None` (WO-006: set on page 1 only, when `total_matches` is above 50).

**SoldComp** — `listing_key` · `address` · `city` · `postal_code` · `close_date: date` · `close_price: int` ·
`list_price: int|None` · `original_list_price: int|None` · `days_on_market: int|None` · `bedrooms: int|None` ·
`living_area: int|None` · `property_subtype` · `year_built: int|None`.

**MarketStats** — `geography: {city|postal_code}` · `property_subtype` · `window: {start, end, months}` ·
`as_of: date` · `sample_count: int` · `low_sample: bool` · `median_close_price` · `mean_close_price` ·
`median_price_per_sqft` · `median_dom` · `dom_band: very_low|low|average|high` ·
`sale_to_list_ratio: float` (e.g. 1.03) · `sale_to_list_reading: str` ("3% over asking") ·
`market_lean: seller|buyer|balanced` · `trend: list[MonthRow]` · `exclusions_applied: list[str]`.
The braces are models: `Geography` (exactly one of `city`, `postal_code`) and `StatsWindow`
(`start <= end`; the window may not end after `as_of`). The four price and day figures are
`float|None`. **MonthRow** (defined in WO-003) — `month: str` ("YYYY-MM") · `sample_count: int` ·
`median_close_price: float|None`.

**Recommendation** — `listing: Listing` · `score_total: float` · `score_components: dict[str, float]`
(price, beds, city, sqft, semantic) · `comp_evidence: {count, window_months, subtype, comp_price_estimate|None,
delta_pct|None, sufficient: bool}` · `explanation: str`. `comp_evidence` is the `CompEvidence` model;
`score_components` keys must come from the five names above.

**RetrievedChunk** — `text` · `source_doc` · `section_or_field` · `page: int|None` · `score: float`.

**AgentResult[T]** — the envelope every tool returns.
`ok: bool` · `data: T|list[T]|None` · `message: str|None` · `warnings: list[str]` ·
`provenance: {tables, as_of: {sold, active}, tool, trace_id}` · `pending_action: PendingAction|None` ·
`error: ToolError|None`.

**AsOfDates** (`domain/asof.py`) — `sold: date` · `active: date`; `window(months)` counts back
from `sold`. The `as_of` inside `provenance` is the separate `AsOf` in `results.py` (dates optional
until the database is wired in); `AsOfDates.to_envelope()` converts one to the other.

**UserSession** — `sender_id: str` (hashed: lowercase hex, 16-128 chars) · `filters: PropertySearchFilters|None` ·
`last_result_keys: list[int]` · `step: int` · `pending_approval_id: str|None` · `updated_at`.

**PendingAction** — `id: str` · `kind: email` · `recipient` · `subject` · `body` · `created_at` ·
`state: pending|approved|sent|rejected|expired`. Approval binds to this exact record.

**SavedSearch** (deferred; only if the Week 4 decision says yes) — `sender_id` · `filters` · `email` · `last_alert_at`.

**ToolError** — `category: validation|not_found|db|provider|timeout|rate_limit|safety_refusal|internal` ·
`message: str` (safe, user-facing) · `detail: str|None` (internal; never sent to the channel) · `trace_id`.
`models.to_channel()` serializes a ToolError, or an AgentResult carrying one, without `detail`.

## MCP tools
| Tool | Input | Output | Phase |
|---|---|---|---|
| `health` | none | server time, version, process start time (UTC) and pid, as-of dates if the DB is reachable | WO-001, WO-006 |
| `search_listings` | PropertySearchFilters fields as flat optional arguments; `sender_id`, `mode`, `clear` (WO-006) | AgentResult[SearchResult \| Clarification] | WO-004, WO-006 |
| `get_market_stats` | geography, property_subtype, months | AgentResult[MarketStats] | Week 5 |
| `find_similar_listings` | text, optional filters, k | AgentResult[list[Listing]] | Week 6 |
| `recommend` | listing_key, k | AgentResult[list[Recommendation]] | Week 7 |
| `rag_answer` | question | AgentResult[{answer, chunks}] | Week 8 |
| `draft_email` | kind, recipient, payload | AgentResult[PendingAction] | Week 11 |
| `send_email` | pending_action_id, approval | AgentResult[SendReceipt] | Week 11 |

Rules: every tool returns an AgentResult and never raises across the MCP boundary; every
result carries both as-of dates and a trace id; the row cap and the column allowlist are
applied inside the tool, not by the caller; `send_email` refuses anything that is not a
stored, approved PendingAction.

`search_listings` has five outcomes, all in one AgentResult envelope:
- Search ran: `ok=True`, `data` is a SearchResult (listings plus `applied_filters`),
  `provenance.tables=["rets_property"]` with both as-of dates, database warnings in `warnings`,
  and `message` holding the formatted reply (one card per listing of the page). Listings in
  the payload carry no remarks. A `limit` above 50 or a `page` above 1000 is a Clarification
  at this boundary (the schema bound), so the 50-row clamp in the SQL builder is a second
  guard, not a path the tool reaches.
- Filters unusable: `ok=True`, `data` is the Clarification from
  `PropertySearchFilters.from_input`, `message` is its question. A Clarification is not an
  error, and no query runs (as-of dates stay empty because the database was not read).
- Database missing or failing: `ok=False`, `error` is a ToolError with category `db`; any
  unexpected failure is category `internal`. `detail` never leaves the server.
- Cleared (WO-006): `mode="reset"` with no filter arguments. `ok=True`, `data=None`,
  `message` is "Cleared your search. What would you like to look for?"; no query runs.
- Last page (WO-006): `mode="more"` when the next page has no rows (the stored page was
  the last). `ok=True`, `data=None`, `message` is "That was the last page. Change a filter
  or start over to search again."; provenance names the table and as-of dates (the query
  ran), and the stored state is left as it was.

Follow-up arguments (WO-006), all optional:
- `sender_id: str|None`: hashed with `memory.sender_key` (HMAC-SHA256 under
  `IDX_SENDER_KEY`); only the hash keys the in-process session store, and only its first
  8 characters reach the log. No id, no key configured, or an id that does not normalize:
  the call is stateless and, when a sender or a mode other than `replace` was given,
  `warnings` has "no session: sender id missing or no key configured". Without
  `sender_id` and with the default mode the tool behaves exactly as in WO-004.
- `mode: replace|update|more|reset` (default `replace`). `replace`: the arguments alone.
  `update`: the stored filters, overwritten by the arguments given, minus the names in
  `clear`, page back to 1 (a new city drops the stored ZIP and the reverse); with nothing
  stored it is a `replace` and `warnings` has "no earlier search was found". `more`: the
  stored filters with `page + 1` (other arguments ignored, with a warning); with nothing
  stored, the `missing_location` Clarification. `reset` with no filter arguments: drops the
  stored state and returns the Cleared outcome. `reset` with filters: validates and searches
  with the arguments alone, and replaces the stored state only once that search has run; a
  Clarification or an error leaves the earlier state as it was.
- `clear: list[str]|None`: filter names to unset in an `update`; a name that is not a
  filter is the `unsupported_filter` Clarification.
Every merged object goes through `PropertySearchFilters.from_input`, so a merged conflict is
a Clarification. The store is written only after a search runs with `ok=True`: the
accepted filters (page included) and the listing keys of the page, never listing text. An
empty page past page 1 is never stored. Calls for one sender key run one at a time (a
per-key lock from reading the state to writing it), so a reset is never undone by a search
already in flight; calls without a key take no lock.

Over-cap rule (human decision 2026-09-24): `total_matches` comes from the page when the page
is short, else from one `SELECT COUNT(*)` with the search's WHERE and params;
`total_matches` is set whenever it is known, on every page. When it is above 50,
`narrowing_question` is "That is more than I can show at once. A budget or a home type to
narrow it?" and the same text is the last line of `message`, on page 1 only (later pages
of the same search keep `total_matches` but do not repeat the question). A failed count
leaves `total_matches` None and the page is still returned.
