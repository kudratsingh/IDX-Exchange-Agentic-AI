# WO-003 — Core domain contracts

**Driver:** agent
**Depends on:** WO-002 (`docs/data/schema_notes.md`, `valid_values.py`, `columns.py`)
**Estimated effort:** 2 hours

## Objective
The typed objects from `docs/CONTRACTS.md` exist as Pydantic models with validation, plus the canonical
field map, so the data layer and every later component talk through models, not dictionaries.

## Why
One person with coding agents produces components at different times. Without shared types, each one
invents its own representation and the seams break during integration.

## Inputs
`docs/CONTRACTS.md`; `docs/data/schema_notes.md`; `src/idx_agent/domain/valid_values.py`; `src/idx_agent/safety/columns.py`.

## In scope
- `src/idx_agent/domain/models.py`: `PropertySearchFilters`, `SoftPreferences`, `Listing`, `SoldComp`, `MarketStats`
  (with `MonthRow`), `Recommendation`, `RetrievedChunk`, `AgentResult[T]`, `UserSession`, `PendingAction`, `ToolError`.
  `SavedSearch` is deferred: leave a comment, no class.
- Validation: city normalized and checked against `valid_values`; subtype checked; price and range rules; `limit` 1-50;
  `Listing` rejects any deny-listed or agent-contact field name at construction.
- `src/idx_agent/domain/fieldmap.py`: the canonical map from `schema_notes.md` as data: for each canonical field,
  the rets_property column, the california_sold column (or None), a type coercion, and a note.
  Helper: `to_listing(row: dict) -> Listing` and `to_sold_comp(row: dict) -> SoldComp`, coercing doubles to ints
  and text dates to `date`, and dropping anything not in the map.
- `src/idx_agent/domain/asof.py`: `AsOf(sold: date, active: date)` value object; no database access here.

## Out of scope
Any SQL, any tool, any parser, any analytics math, the MCP server.

## Files expected to change
`src/idx_agent/domain/models.py`, `src/idx_agent/domain/fieldmap.py`, `src/idx_agent/domain/asof.py`, `tests/test_domain_*.py`.

## Interfaces and contracts
Exactly the fields in `docs/CONTRACTS.md`. If a field must change, update that file in the same commit and say why in Status.

## Implementation requirements
1. Every model is immutable after construction (`frozen=True`) except `UserSession`.
2. `AgentResult` is generic and serializes to JSON without custom code.
3. `to_listing` never emits a field outside `Listing`; unknown keys are ignored, not errors.
4. `Listing.remarks` is excluded from `repr` and from any `model_dump(mode="log")` helper used by logging.
5. `ToolError.detail` is excluded from channel-facing serialization.

## Safety requirements
Deny-listed and agent-contact fields cannot enter a `Listing`; `remarks` never reaches logs; `ToolError.detail` never reaches a user.

## Tests required
`tests/test_domain_models.py` (25+ cases): valid construction for each model; invalid city, subtype, price range,
limit 0 and 51; `Listing` with an agent email raises; `remarks` absent from repr; `AgentResult` round-trips JSON.
`tests/test_fieldmap.py`: a synthetic rets row and a synthetic sold row (made-up values) map to models with correct
coercions; a text date `2024-03-05` becomes a `date`; a double `3.0` becomes `3`.

## Acceptance criteria
- All models in `docs/CONTRACTS.md` exist and are importable from `idx_agent.domain`.
- Tests above pass; `ruff check` clean; CI green.
- No test fixture contains a real row (values are invented).

## Verification commands
```
pytest tests/test_domain_models.py tests/test_fieldmap.py -q
ruff check src tests
python -c "from idx_agent.domain import models, fieldmap, asof; print('ok')"
```

## Deliverables
The three modules and their tests.

## Stop conditions
- `schema_notes.md` lacks a valid-value set a validator needs.
- A contract field cannot be satisfied by any column in either table.

## Status
**Done on 2026-09-23** after an independent review; PR into `main` from
`wo-003-domain-contracts`. Full suite after the review fixes: 544 passed, 1 skipped (db).
Full suite after the Clarification addition below: 568 passed, 1 skipped (db); ruff clean.

**Clarification result (added 2026-09-23 on the human's parsing decision)**
- Parsing is the model filling the `search_listings` schema (PropertySearchFilters); code
  validates strictly. Every filter field is optional, city included; no check was relaxed.
- New frozen `Clarification(field, reason, question, options=None)`. `question` names the
  field and never repeats the user's value; `options` is set only for small sets (the
  subtypes, or the supported filter names for an unknown key), never the city list.
- New `PropertySearchFilters.from_input(raw) -> PropertySearchFilters | Clarification`: the
  first validation error becomes the Clarification; neither city nor postal code gives
  `missing_location`. Bad user data never raises; a non-mapping input raises TypeError.
- The filter validators now raise stable error codes (`unknown_city`, `unknown_subtype`,
  `not_half_step`, `min_above_max`) with the same messages, so the mapping to a reason does
  not depend on message text. An unknown key that is not plain snake_case is reported as
  field `unknown`, so free text in a key is not repeated back.
- `docs/CONTRACTS.md` records the optional fields, the Clarification model and reason codes,
  and that `search_listings` returns results plus the accepted filters, or a Clarification.
- Tests: 24 new cases in `tests/test_domain_models.py` (valid mapping, unknown city without
  echo, unknown subtype with options, min above max, limit 0 and 51, no location, unknown
  key, free-text key, per-reason mapping, frozen and JSON round trips).

**Review outcome (no blockers; all should-fix items applied)**
- `ToolError.detail` is excluded from every dump (`Field(exclude=True)`), so it cannot
  cross the MCP boundary through the server's envelope; a test covers the health tool's
  failure path.
- Input values are hidden in validation errors for every model, including the six in
  `results.py`; `safe_errors()` returns the error list without inputs; the filter
  messages no longer echo the user's text.
- The remarks-leak test now puts the sentinel in `remarks`, so it fails if the config is
  removed; the `results.py` docstring recommends re-validation instead of `model_copy`.
- Cities keep their stored spelling (McFarland, Coto de Caza, McCloud, McKinleyville,
  McKittrick differ under title casing): the filter returns the spelling a query must match.
- Measured doubles (prices, living area, HOA fee) round half-even instead of failing:
  the sold table has 32 fractional close prices, 5 fractional list prices, and 2
  fractional living areas. Keys, bedrooms, year built, and days on market stay strict.
- The field map carries every row of the canonical map (contract dates, modification
  timestamp, lot size added) with a marker saying which model uses it; `sold=None` now
  means "no such column" only.
- Postal codes must be five digits or ZIP+4; text dates must start `YYYY-MM-DD`;
  non-finite numbers become None; a zero or missing coordinate nulls both coordinates;
  days on market is non-negative and year built at least 1800.
- `MarketStats` readings (dom band, sale-to-list ratio and reading, market lean) may be
  None only when `sample_count` is 0; recorded in `docs/CONTRACTS.md` with the optional
  Listing and SoldComp fields typed `str|None`.
- Tests: forbidden keys parametrized over the whole deny-list and agent-contact set for
  both models and both entry points; frozen checks assert `frozen_instance` for every
  frozen model; a recording mapping proves `to_listing`/`to_sold_comp` read exactly
  `listing_columns()`/`sold_columns()`; the always-true assertions were replaced.

**Built**
- `domain/models.py`: PropertySearchFilters, SoftPreferences, Listing, SoldComp, MonthRow,
  MarketStats (with Geography and StatsWindow), Recommendation (with CompEvidence),
  RetrievedChunk, UserSession; AgentResult, ToolError, PendingAction re-exported from
  `results.py`, not copied. SavedSearch is a comment only. `to_channel()` dumps a ToolError,
  or an AgentResult carrying one, without `detail`. `Listing.for_log()` drops `remarks`.
- `domain/fieldmap.py`: FIELD_MAP (canonical name, active column, sold column, reader, note,
  companion columns), `to_listing`, `to_sold_comp`, `listing_columns`, `sold_columns`
  (every name passes `check_column`).
- `domain/asof.py`: `AsOfDates(sold, active)`, frozen, with `window(months)` and
  `to_envelope()`. No database access.
- `domain/__init__.py` imports the three modules and re-exports the models.
- Tests: `tests/test_domain_models.py` and `tests/test_fieldmap.py`, invented rows only,
  plus a no-detail test in `tests/test_mcp_health.py`. Full suite: 544 passed, 1 skipped
  (db); ruff clean.

**Decisions**
- Requirement 1 applied to the existing `results.py` models too: all six are now frozen.
  The MCP server never assigns to them, so nothing else changed.
- The as-of value object is named `AsOfDates`, because `results.AsOf` (optional dates)
  already sits inside Provenance; two classes named AsOf would be easy to mix up.
- City and subtype value-set checks apply to PropertySearchFilters (user input) only.
  Listing and SoldComp keep the stored spelling, so a data refresh that adds a city or
  subtype does not break reads. Both still check shape: five-digit zip, non-negative
  prices and counts, coordinate ranges.
- Listing and SoldComp refuse deny-listed and agent-contact keys with a named reason
  before `extra="forbid"` runs; all frozen models hide input values in validation errors
  so remarks or a stray contact value cannot reach a logged error.
- `to_listing` and `to_sold_comp` read only mapped columns, so unknown, deny-listed, and
  contact keys in a raw row are dropped. Whole doubles become ints; a fractional double for
  an int field becomes None. Text dates read the first 10 characters. Zip keeps the first
  five digits, otherwise None. A coordinate of exactly 0 becomes None (section 12 counts
  those as missing). PhotoCount falls back to the L_Photos array length, then 0.
- UserSession requires a lowercase hex `sender_id` (16-128 chars), so a raw phone number
  cannot be stored as the key; assignments are validated.
- `docs/CONTRACTS.md` updated: MonthRow had no fields, so it now has month, sample_count,
  median_close_price; the braces in MarketStats and Recommendation are named models;
  AsOfDates and `to_channel()` are recorded.

**Open**
- `hoa_fee_monthly` is set only when AssociationFeeFrequency is Monthly. Of the 26,203
  active rows with a positive fee, 459 have no frequency and 1,649 are annual, quarterly,
  or semiannual; all of those give None for now. Converting them is a WO-004 choice.
- `address` is never blanked: the display-flag columns do not exist in either table
  (schema notes section 10-11).
- A sold row whose close date cannot be parsed fails validation. The data layer in
  WO-004 decides whether to skip such rows.
- `frozen=True` is shallow: list fields (photos, comps, months) stay mutable in place.
  Documented in `docs/CONTRACTS.md`; not changed, because no code mutates them.
