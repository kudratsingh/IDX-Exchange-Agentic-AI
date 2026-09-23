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
not started
