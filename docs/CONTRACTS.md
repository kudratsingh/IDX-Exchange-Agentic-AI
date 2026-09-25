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
`invalid_value`; `recommend` adds `missing_listing` and `no_session`) · `question: str` (plain
language; names the field, never repeats the user's value) ·
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
Figures and readings (WO-008): with `low_sample=True` (fewer than 5 sales) or a `sample_count` of 0,
every figure and reading may be None and `sample_count` keeps the real count. Otherwise
`median_close_price`, `sale_to_list_ratio`, and `sale_to_list_reading` are required, and `dom_band` and
`market_lean` are required exactly when `median_dom` is set. `median_dom` and `median_price_per_sqft`
each need at least 10 usable values (`METRIC_MIN_SAMPLE`, decided 2026-09-24): fewer than 10 sales with
days on market leaves `median_dom`, `dom_band`, and `market_lean` None, and fewer than 10 with 200 sqft or
more leaves `median_price_per_sqft` None; the card then says "not available (fewer than 10 sales with a
usable value)". `MIN_SAMPLE` (5) still governs the sample as a whole.
`mean_close_price` is not computed (None). Prices and price per sqft are whole dollars rounded half-even
once, after the median; the ratio is rounded half-even to 3 decimals; `median_dom` may end in .5.
`exclusions_applied` holds one `"rule: count"` entry per exclusion rule, zero counts included.
`after_active_asof` and `unreadable_close_date` are counted for the place and subtype whatever
the window; the other rules count only sales inside it. Built by `domain/market.py` `build_market_stats`.

**MarketStatsRequest** (WO-008) — the validated `get_market_stats` arguments.
`city: str|None` (in the valid city set, stored spelling returned) · `postal_code: str|None` (5 digits) ·
exactly one of the two · `property_subtype: str|None` (in the valid subtype set; None means the
`SingleFamilyResidence` benchmark with the other subtypes' counts disclosed) · `months: int = 6` (1-24;
a window reaching past the data's coverage falls back to the coverage, with a warning) ·
`geography() -> Geography`. `MarketStatsRequest.from_input(raw)` returns the request or a Clarification
and never raises on bad user data; None arguments count as unset. Field errors come first; then neither
location is `missing_location` and both is `invalid_value` (field `city`). A boolean, fraction, or
non-numeric text `months` is `invalid_value`; 0 is `below_minimum`; above 24 is `above_maximum`.

**Recommendation** — `listing: Listing` · `score_total: float` · `score_components: dict[str, float]`
(price, beds, city, sqft, semantic) · `comp_evidence: CompEvidence` · `explanation: str`.
`score_components` keys must come from the five names above. In `recommend` (WO-011) `score_total`
is the cosine similarity rounded to 4 decimals, `score_components` is `{"semantic": <same value>}`
(city, subtype, and price are hard filters, not scores), and `explanation` is one fixed sentence
built from the hard filters only, never from remarks.

**CompEvidence** (extended in WO-011) — a listing's price check against comparable closed sales.
`count: int` (comps at the level used) · `window_months: int` (6) · `subtype: str|None` ·
`comp_price_estimate: int|None` (always None: the subject is never valued; any value is refused) ·
`delta_pct: float|None` (whole percent, signed; None unless sufficient) · `sufficient: bool`
(`count >= 5` and the listing is checkable) · `level: postal_code|city|None` (None when the
listing cannot be checked) · `area: str|None` ("ZIP <ZIP>" at the ZIP level, the city name at the
city level) · `widened_from: str|None` ("ZIP <ZIP>", exactly when `level` is `city`: the ZIP was
tried first and had too few) · `median_price_per_sqft: int|None` (whole dollars, half-even; None
unless sufficient) · `range_low_price_per_sqft: int|None` and `range_high_price_per_sqft:
int|None` (the middle half's two ends, whole dollars, half-even each; None unless sufficient; low
<= high) · `sentence: str` · `range_sentence: str|None` (None unless sufficient). The comps are
sales in the subject's five-digit ZIP (a `PostalCode` prefix match), widened to its city only when
the ZIP has fewer than 5 (and no further; a city still under 5 is reported with its count as
found), of the same `PropertySubType`, with `LivingArea` from 0.8 to 1.2 times the subject's and
`BedroomsTotal` within 1 of the subject's (floored at 0), both inclusive, in `AsOfDates.window(6)`,
after every WO-008 exclusion; bathrooms are never compared. At most two comps statements per
listing. `delta_pct` is (list price / living area) / median price per sqft - 1, times 100, in
Decimal, rounded half-even once at the end; the median comes from the SQL middle rows. **The middle
half:** with the comps' per-sale `close_price / living_area` sorted ascending v[1..n] and `k = n //
4`, it runs from v[k + 1] to v[n - k] (n 5: ranks 2 and 4; n 6: 2 and 5; n 8: 3 and 6; n 25: 7 and
19). Both ends are single order statistics, no interpolation, read in SQL from the same ordered
sample as the median (`rn = FLOOR(n / 4) + 1` and `rn = n - FLOOR(n / 4)`, every number bound) as a
close price and an area, divided in Decimal. Built only by `domain/comps.py` `price_check`.
**Sentences** (the only shapes; `price_check_sentence` writes the main sentence and its companion
`range_sentence` the second one, and nothing else says anything about price):
- ZIP level: "Listed N% above the median price per square foot of C comparable sales in ZIP <ZIP>
  over the last six months." ("below" when negative; N printed without a sign.)
- At the median (rounds to 0): "Listed at the median price per square foot of C comparable sales in
  <area> over the last six months." (with the city level's suffix at the city level)
- City level, after widening: the same shapes with "<City>" as the area and " (widened from ZIP
  <ZIP>, which had too few)." in place of the final period.
- The middle half, after any sufficient check: "The middle half of those sales ran from $602 to
  $700 per square foot." (whole dollars with thousands separators).
- Below the minimum (at either level): "Not enough comparable sales to check the price." No digit,
  and no range sentence.
- Not checkable (no city, five-digit ZIP, subtype, living area of at least 200 sqft, or bed count,
  or a list price under 25,000): "The price cannot be checked: this listing is missing its size,
  bedroom count, or type." No digit, and no range sentence.
A reply carries a check as one line: the sentence, then a space and the range sentence when there
is one. No sentence holds a word that reads as advice, a forecast, or a valuation
(`FORBIDDEN_WORDS`), outside its place names: a real city can hold one ("Fair Oaks"), so the check
replaces the area and the widened-from ZIP, as written, with a placeholder first
(`contains_forbidden(text, exempt=place_names(evidence))`).

**SimilarListingsRequest** (WO-010) — the validated `find_similar_listings` arguments.
`text: str` (whitespace collapsed; at least 2 words and 8 letters; at most 500 characters) ·
`k: int = 5` (1-10) · `city: str|None` (in the valid city set, stored spelling returned) ·
`max_price: int|None` (>= 0) · `min_beds: int|None` (0-20) · `property_subtype: str|None` (in the
valid subtype set). No location is required. `hard_filters() -> PropertySearchFilters` holds only
the four filters (page and limit at their defaults). `SimilarListingsRequest.from_input(raw)`
returns the request or a Clarification and never raises on bad user data; None arguments count
as unset. A missing, short, or non-text `text` is field `text`, `below_minimum`; over 500
characters is `above_maximum`; `k` 0 is `below_minimum`, 11 `above_maximum`, a fraction, boolean,
or text `invalid_value`; a bad city or subtype gives `unknown_city` or `unknown_subtype`; an
unknown argument `unsupported_filter`. The question never repeats the user's text.
`SoftPreferences` is unchanged: `text` is its one-string form.

**SimilarMatch** (WO-010) — `rank: int` (1-based, in ranked order) · `score: float` (cosine
similarity, rounded to 4 decimals; not a probability, so never shown on a card) · `listing:
Listing` (`remarks` is always None: dropped when the match is built).

**SimilarResult** (WO-010) — what `find_similar_listings` puts in `AgentResult.data` when a
ranking ran. `matches: list[SimilarMatch]` (at most k, ranked 1..n in list order) ·
`applied_filters: PropertySearchFilters` (the hard filters; never the text) · `k: int` ·
`rows_ranked: int` (index rows left after the in-memory filter mask) · `index_as_of: date` (the
active as-of date the index was built at) · `model: str` (e.g.
`"openai:text-embedding-3-small@1536"`). A match carries no text, so it is not a RetrievedChunk.

**RecommendRequest** (WO-011) — the validated `recommend` arguments. `listing_key: int|None` (>= 1) ·
`k: int = 5` (0-5; 0 is the price check alone) · `sender_id: str|None` · `position: int|None` (>= 1,
1-based into the sender's `last_result_keys`; needs `sender_id`). `resolved_by` is `key` whenever a
key is given, else `position`; with both, the key wins and `input_warnings()` returns one warning.
`RecommendRequest.from_input(raw)` returns the request or a Clarification and never raises on bad user
data; None arguments count as unset. Field errors come first: `k` -1 is `below_minimum`, 6
`above_maximum`, a fraction, boolean, or text `invalid_value`; a key or position of 0 is
`below_minimum`; an unknown argument `unsupported_filter`. Then neither a key nor a position is
`missing_listing` (field `listing_key`: "Which listing do you mean? Send its listing number or pick
one from a search."), and a position without a sender id is `no_session` (field `position`: "I no
longer have that result. Which listing do you mean?"), the question the tool also uses when the
session is missing or the position is past its end (`RecommendRequest.clarification`).

**RecommendationResult** (WO-011) — what `recommend` puts in `AgentResult.data` once the subject was
found. `subject: Listing` · `subject_check: CompEvidence` · `recommendations: list[Recommendation]`
(at most k, so at most 5, in rank order) · `k: int` (0-5) · `index_as_of: date|None` (None when k is
0) · `comps_window: StatsWindow` (`AsOfDates.window(6)`; every check's `window_months` matches it).
No listing in it carries remarks: they are dropped when the result is built.

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
| `get_market_stats` | `city`, `postal_code`, `property_subtype`, `months` as flat optional arguments (MarketStatsRequest fields); no sender id | AgentResult[MarketStats \| Clarification] | WO-008 |
| `find_similar_listings` | `text`, `k`, `city`, `max_price`, `min_beds`, `property_subtype` as flat optional arguments (SimilarListingsRequest fields); no sender id | AgentResult[SimilarResult \| Clarification] | WO-010 |
| `recommend` | `listing_key`, `k`, `sender_id`, `position` as flat optional arguments (RecommendRequest fields) | AgentResult[RecommendationResult \| Clarification] | WO-011 |
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

`get_market_stats` (WO-008) has four outcomes, all in one AgentResult envelope:
- Stats: `ok=True`, `data` is a MarketStats with `low_sample=False`, price, ratio and
  reading set; days on market and price per square foot as in the MarketStats rule above
  (None when fewer than 10 sales have a usable value), `message` is the market card (place and subtype, the window and "sales to"
  the sold as-of date, count, medians, ratio and reading, lean, monthly trend, the
  exclusions line, and the other subtypes' counts when no subtype was given),
  `provenance.tables=["california_sold"]` with both as-of dates. `warnings` hold the window
  fallback note (below) and each non-zero exclusion count in plain words.
- Not enough comps: fewer than 5 sales after the exclusions. `ok=True`, `data` is a
  MarketStats with the real `sample_count`, `low_sample=True`, every figure and reading
  None, an empty trend, and `exclusions_applied` still filled; `message` names the count,
  the minimum, the window, and one widening step the tool can run (a window of up to six
  months, else a subtype with at least 5 sales there), never another city. Provenance as
  for Stats.
- Clarification: `ok=True`, `data` is the Clarification from
  `MarketStatsRequest.from_input` (`missing_location`, `unknown_city`, `unknown_subtype`,
  `invalid_format`, `below_minimum`, `above_maximum`, or `invalid_value` when both city and
  ZIP are given), `message` is its question. No query runs; as-of dates stay empty.
- Error: `ok=False`, a ToolError with category `db` (database not configured or failing)
  or `internal` (a statement over the 50-row cap, with its own message, or any unexpected
  failure). `detail` never leaves the server.

The window is `AsOfDates.window(months)`, ending on the sold as-of date. When it would
start before the earliest valid close date, the data's full coverage is used instead
(`window.start` = that date, `window.months` = the months it covers) and `warnings` says so.
The tool takes no sender id and never reads or writes the session store, so a market
question between two search turns leaves the search state (and "more") as it was. The
log line holds the outcome, the validated request, the months used, the sample count, and
the exclusion counts; never a row, an address, or a listing key.

`find_similar_listings` (WO-010) has four outcomes, all in one AgentResult envelope:
- Matches: `ok=True`, `data` is a SimilarResult with 1 to k matches in rank order,
  `message` is the reply (a header with the filters in words and the active as-of date,
  then each card under its rank line, "Match 1 of 5"; no score), and
  `provenance.tables=["rets_property"]` with both as-of dates. `warnings` hold the
  stale-index note (the index's active as-of date differs from the database's: listings
  added since are not ranked), the fewer-than-k note (naming one filter to drop), and the
  dropped-candidates note (ranked listings SQL no longer returned as active and matching,
  or returned in a row that failed validation), whichever apply; the
  same texts appear in `message`, except the dropped note.
- No match: `ok=True`, `data` is a SimilarResult with no matches (the filters left no
  index row, or SQL dropped every candidate); `message` says so and names a filter to
  drop. Provenance as for Matches.
- Clarification: `ok=True`, `data` is the Clarification from
  `SimilarListingsRequest.from_input`, `message` is its question; nothing is embedded and
  no query runs, so the as-of dates stay empty. A text under 20 characters once prepared
  (with any embedder; no provider call is made) or one that embeds to an unusable vector
  (for the test embedder, no a-z/0-9 word) is also field `text`, `below_minimum`, "Please
  describe the home in a few more words."
- Error: `ok=False`, a ToolError with category `not_found` (no usable index: the
  `semantic` extra missing, `IDX_SEMANTIC_INDEX_DIR` unset, or the index failing a load
  check; message "Similar-listing search is not set up on this server yet."), `provider`
  (the key missing, no `paid` consent, or the embedding call failing or timing out),
  `db` (the database not configured or failing), or `internal` (a statement over 50 rows,
  more than k matches, or anything unexpected). `detail` never leaves the server.

Ranking: the user's text is prepared by the build's own rule (`prepare_text`: whitespace
collapsed; links, emails, and phones masked unless `IDX_EMBED_REDACT` is off; the
20-character floor) and embedded once; the index rows are masked in memory by the
hard filters (from the values stored beside each vector at build time), ranked by cosine
similarity (float32, rounded to 6 decimals, then listing key ascending), and up to 200
ranked keys are fetched in batches of at most 50 through `build_candidate_sql` (the
search WHERE plus `L_ListingID IN (...)`, `LIMIT 50`), stopping once k listings are in
hand. SQL decides; rank order is kept. The index loads once per process on the first
call; the `semantic` package, NumPy, and `openai` are imported only then. The tool takes
no sender id and never reads or writes the session store. The log line holds the outcome,
k, the hard filters, the text's word and character counts, rows ranked, keys fetched,
dropped (and, of those, `skipped` rows that failed validation), matches, the index as-of
date, the model and dimension; never the text, a
vector, a remark, a listing key, or an address.

`recommend` (WO-011) has four outcomes, all in one AgentResult envelope:
- Recommendations: `ok=True`, `data` is a RecommendationResult with the subject's check and 1 to
  k recommendations in rank order, `message` is the reply ("Similar to <the subject card's first
  line>:" and the subject's "Price check:" line; each card under its rank line, "Similar 1 of 5",
  followed by its "Price check:" line (each check line is the sentence and, when the check is
  sufficient, the range sentence after one space); the fewer-than-k and stale-index lines when
  they apply;
  then "Closed sales to <sold as-of>; listings as of <active as-of>."; no score, no remark, no
  reason a listing matched), and `provenance.tables=["rets_property", "california_sold"]` with both
  as-of dates. `warnings` hold the key-wins note, the stale-index note, the fewer-than-k note
  ("Only 2 of the 5 similar listings asked for came back."), and the dropped-candidates note,
  whichever apply.
- No similar listing: `ok=True`, `data` is a RecommendationResult with the subject's check and no
  recommendations (`k` was 0, the mask left nothing, SQL dropped every candidate, or the subject has
  no vector in the index, which adds the warning "This listing is not in the description index, so
  no similar listing could be ranked for it."). `message` is the subject's check line alone (its
  sentence and, when sufficient, its range sentence, on one line) when `k` is 0, else that line
  and "No similar active listing was found in the same city and type, listed close to its price."
  Provenance as for Recommendations.
- Clarification: `ok=True`, `data` is the Clarification from `RecommendRequest.from_input`
  (`missing_listing`, `below_minimum`, `above_maximum`, `invalid_value`, `unsupported_filter`,
  `no_session`), or `no_session` from the tool when the sender has no stored result or the position
  is past its end; `message` is its question. No index is loaded and no query runs; as-of dates
  stay empty.
- Error: `ok=False`, a ToolError with category `not_found` (the key is not an active listing: "That
  listing is not among the current active listings."; or `k` above 0 with no usable index:
  "Similar-listing search is not set up on this server yet.", checked before any query), `db` (the
  database not configured or failing), or `internal` (a statement over 50 rows, more than k
  recommendations, more than 12 comps statements, or anything unexpected). `detail` never leaves
  the server.

Flow: validate; resolve the subject (the key when given; else `position` into the sender's
`last_result_keys`, the sender id hashed with `memory.sender_key` as search does, read once and
never written; without a position the store is not touched); fetch the subject through
`fetch_candidates` with no hard filter and that one key (the active-status rule applies); run its
price check (the ZIP comps statement and, below 5, the city statement). When `k` is above 0: read
the subject's own vector from the index by key (binary search; nothing is embedded, no provider is
called, no embedder is built), mask the index to the subject's city and subtype and the price band
(`ceil(0.75 x price)` to `floor(1.25 x price)`, inclusive, from Decimal), drop the subject's row,
rank by WO-010's rule (float32, 6 decimals, then key), fetch up to 200 ranked keys 50 per statement
through `fetch_candidates` with the same four filters applied again in SQL until k survive, and run
each recommended listing's price check. At most 12 comps statements per call. With `k` 0 the index
is never loaded, so the price check works on a server with no index. Listings in the payload carry
`remarks=None`. The log line holds the outcome (`recommendations`, `no_similar`, `clarification`,
`error`), k, `resolved_by` (`key` or `position`), the subject's comps `level` and count (`comps`),
`recommendations` returned, `keys_fetched`, `dropped`, `skipped`, the index as-of date, and
`stale_index`; never a listing key, an address, a remark, a sentence, or the sender id.
