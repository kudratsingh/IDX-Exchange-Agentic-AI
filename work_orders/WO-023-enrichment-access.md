# WO-023 — Shared enrichment access for every feature consumer

**Driver:** agent (owner reviews the PR)
**Depends on:** WO-021 Phase 1 and increment 2 (merged: PRs #134-#136), ADR-0014
**Estimated effort:** planning input only, not a commitment

## Objective
One module, `src/idx_agent/enrichment/access.py`, owns how remark features are read:
eligibility, status, per-listing freshness, snapshot staleness, provenance and store
lifetime. Feature search and card badges use it now. Recommendation explanations
(WO-024) and saved feature searches (WO-025) build on it, so all four agree by
construction rather than by parallel copies.

## Why
WO-021 put the freshness cache, the stale threshold, the limitation text and the
present-only test in the MCP server, and the badge path repeated the status check. Two
more consumers are about to need the same rules, and a third copy would invite drift:
for example an alert counting a changed listing that search would leave out.

## Inputs
`enrichment/effective_store.py` (validated read-only store, ADR-0014),
`enrichment/effective.py` (`ELIGIBLE_FACETS`, `MATCHING_STATUS`), `db/listings.py`
(scope, changed-key and freshness SQL), the search and badge paths in
`mcp_server/server.py`, `tests/test_feature_search_acceptance.py` (invented universe),
`docs/CONTRACTS.md` WO-021 sections, `docs/RECOMMEND_FEATURES_DECISION.md` (branch
`wo-021-recommend-design`, for the consumer it must serve).

## In scope
1. `FeatureAccess`: a context manager that opens the configured store at most once,
   reports `Readiness` (`usable | unavailable | stale` with a fixed reason code, the
   store's provenance, active and changed counts) and always closes the store.
2. Shared reads: `scope(features)` (keys with every feature present; too broad is
   flagged, never bound), `present_features(keys, conn, facets)` (per-key present
   features, leaving out keys changed since the snapshot, undated or never extracted;
   at most 50 keys), `changed_keys`, `present_in`, `ordered` (requested first, then
   A-Z) and `AREA_FACETS` (the two facets describing surroundings, for consumers that
   choose to leave them out).
3. The freshness counts cache (60 s) and the 10% stale share move into the module and
   are shared by every consumer in a process.
4. Search and badges switch to the module with no behavior change. Server constants
   stay importable under their old names.

## Out of scope
New user-visible behavior, any change to the store format, builder, overlays, frozen
results or eligibility list, new indexes, recommendation ranking, saved-search
persistence (WO-025), and any deployment or live configuration.

## Files expected to change
`src/idx_agent/enrichment/access.py` (new), `src/idx_agent/mcp_server/server.py`,
`tests/test_enrichment_access.py` (new), three existing feature test files (patch
target for the clock only), `docs/CONTRACTS.md`, this file.

## Interfaces and contracts
No tool signature or payload changes. `FeatureFilter`, `CardBadges` and replies are
byte-for-byte as before.

## Implementation requirements
1. Only eligible `present` statuses qualify everywhere; every other status and a
   missing label give nothing.
2. A key with any row modified after the snapshot, or with no modification time, has
   no usable features in every consumer; duplicate rows of a key are judged together.
3. Stale and unavailable readiness block every read (`RuntimeError`), so a consumer
   cannot accidentally read features without checking.
4. The store is closed on success, refusal, exception and a failed connection.
5. A search without features (and badges off) never opens the store and issues the
   same statements as before.

## Safety requirements
Parameterized SQL with allowlisted columns; at most 50 keys per changed-key statement;
no remark text read or returned; listing keys and per-listing statuses never logged.

## Tests required
`tests/test_enrichment_access.py`: unavailable (unconfigured, missing, junk, source
mismatch after replacement), stale (above, at and with no active listings), readiness
once per access, present-only agreement with feature search for every facet and every
status, eligibility, area-facet exclusion, changed/undated/duplicate rows, key limits,
too-broad scope, store replacement during and after an access, closing on every path,
one store open per search with badges, and an ordinary search that never opens it.
All existing feature, badge and acceptance tests pass unchanged except the clock
patch target.

## Acceptance criteria
- Existing WO-021 tests pass with no assertion changes.
- New access tests pass; ruff clean; full offline suite and CI green.
- Real-data timing (local snapshot, real store) shows no regression for searches
  with or without features.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
pytest -q tests/test_enrichment_access.py tests/test_card_badges.py \
  tests/test_mcp_search_features.py tests/test_feature_search_acceptance.py
```

## Deliverables
The shared module, its tests, the refactored search and badge paths, the contract note.

## Stop conditions
- A consumer needs a rule that differs from the shared one (stop and ask; do not fork).
- Any change would alter a reply, payload or SQL of a search without features.

## Status
2026-11-02: built, in review (branch `wo-023-enrichment-access`). Search and badges now
read through `FeatureAccess`. 44 new tests; 128 existing feature, badge, acceptance
and store tests pass unchanged apart from the clock patch target.

Real-data timing (local listings snapshot, the real store; median of 7 warm runs;
main → this branch): Pasadena plain 10.2 → 11.7 ms, Los Angeles plain (20 rows) 28.5 →
27.6, Pasadena solar 69.9 → 72.9, Los Angeles solar 101.1 → 107.9, Los Angeles garage
152.6 → 158.2; badges on 10.4 → 11.0, 28.1 → 28.9, 68.9 → 72.9. Results and badge counts
are identical; differences are within run-to-run noise. Nothing was installed or enabled.

Finding (pre-existing, not changed): an active listing ID with two identical unchanged
rows is returned and counted twice, by an ordinary search and by a feature search
alike (the alert query already ranks duplicates). The local snapshot has three such
IDs. Deduplicating search results changes ordinary search and is left as an owner
decision.
