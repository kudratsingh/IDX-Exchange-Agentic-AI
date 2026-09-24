# Contracts

Pydantic models in `src/idx_agent/domain/` and the MCP tool signatures. Anything that
crosses a boundary (parser -> tool, tool -> agent, agent -> channel) uses these and
nothing else. Exact fields may change; the boundary concepts do not. Changing a
contract means updating this file, the tests, and, if more than one component is
affected, an ADR.

## Domain models
**PropertySearchFilters** — validated hard constraints from user language.
`city: str|None` (in the valid city set, casing normalized) · `postal_code: str|None` (5 digits) ·
`min_price, max_price: int|None` (>= 0, min <= max) · `min_beds: int|None` (0-20) ·
`min_baths: float|None` (0-20, half steps) · `min_sqft: int|None` · `property_subtype: str|None`
(in the valid subtype set) · `pool, view: bool|None` · `max_hoa_monthly: int|None` ·
`page: int = 1` · `limit: int = 5` (1-50).
Unknown or out-of-range values raise a validation ToolError or produce a follow-up question. Never a guess.

**SoftPreferences** — `terms: list[str]`; free-text descriptors used only for semantic ranking, never in SQL.

**Listing** — canonical, RESO-named, no agent contact fields, no deny-listed fields.
`listing_key: int` · `listing_id: str` · `address: str|None` (blank if display flags forbid) ·
`city` · `postal_code` · `list_price: int` · `bedrooms: int|None` · `bathrooms: float|None` ·
`living_area: int|None` · `property_subtype` · `status` · `year_built: int|None` ·
`hoa_fee_monthly: int|None` · `days_on_market: int|None` (as of the data pull) · `photo_count: int` ·
`latitude, longitude: float|None` · `pool, view, fireplace: bool|None` · `remarks: str|None` (untrusted text; never logged).

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
| `health` | none | server time, version, as-of dates if the DB is reachable | WO-001 |
| `search_listings` | PropertySearchFilters | AgentResult[list[Listing]] | WO-004 |
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
