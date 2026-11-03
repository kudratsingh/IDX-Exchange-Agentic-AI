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
2. Shared reads: `bind(features, conn)` (readiness plus the one scope decision: a
   `Binding` that is `applied` with a `db_listings.FeatureScope` carrying the snapshot
   watermark, `applied` with no scope when nothing matches, or a refusal, `unavailable`
   including `too_broad` and `closed`, or `stale`; never widened),
   `lookup(keys, conn, facets)` and `present_features(keys, conn, facets)` (per-key
   present features, leaving out keys changed since the snapshot, undated or never
   extracted; `lookup` also returns the changed keys; at most 50 keys),
   `changed_keys`, `present_in`, `ordered` (requested first, then A-Z) and
   `AREA_FACETS` (the two facets describing surroundings, for consumers that choose to
   leave them out).
3. The freshness counts cache (60 s) and the 10% stale share move into the module and
   are shared by every consumer in a process.
4. Search and badges switch to the module with no behavior change. The stale share
   and freshness window exist only in the module (`STALE_SHARE`,
   `FRESHNESS_TTL_SECONDS`); the server keeps no copies that could be patched to no
   effect (review of #142). The limitation text stays importable as
   `FEATURE_LIMITATION`.

## Out of scope
New user-visible behavior, any change to the store format, builder, overlays, frozen
results or eligibility list, new indexes, recommendation ranking, saved-search
persistence (WO-025), and any deployment or live configuration.

## Files expected to change
`src/idx_agent/enrichment/access.py` (new), `src/idx_agent/mcp_server/server.py`,
`src/idx_agent/enrichment/effective_store.py` (distinct-facet matching and a
repeated-row validation check, from review),
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

2026-11-02, review fixes (two independent read-only reviews of head `41d19c5`). Each
candidate finding was first reproduced with a throwaway test against `41d19c5`; all six
reproduced, and each fix has a regression test that fails on `41d19c5`:
1. Confirmed, fixed: multi-feature matching counted rows, not facets, and validation
   never checked one row per (listing, facet), so a store built without the primary key
   could match a solar-only listing for solar + pool. `keys_with_all` now counts
   distinct facets and a store with repeated rows is `malformed` (unavailable). The
   normal builder declares the key, so built stores were not affected; the check scans
   the facets index once per validated file (about 26 ms on the local store; validation
   is cached by file identity), and the local store passes it.
2. Confirmed, fixed: the readiness-to-SQL-scope decision lived only in the server, so
   saved-search alerts (WO-025) would have had to copy it. New `bind(features, conn)`
   returns a `Binding`: `applied` with a `db_listings.FeatureScope` carrying the snapshot
   watermark, `applied` with no scope (nothing matches), or a refusal (`unavailable`
   with the store's reason, `too_broad` or `closed`; `stale`). The server now uses it.
3. Confirmed, fixed with 2: an empty `Scope` meant both "none" and "too broad".
   `Scope`/`scope()` are replaced by `Binding`, where too broad is a refusal
   (`refused`), distinct from `matches_nothing`.
4. Confirmed, fixed: the server's `FEATURE_STALE_SHARE` and `FRESHNESS_TTL_SECONDS`
   were copies nothing read, so patching them did nothing. They are removed; the knobs
   are `STALE_SHARE` and `FRESHNESS_TTL_SECONDS` in `enrichment.access` (no tracked code
   patched the old names; one test read the TTL and now reads it from the module).
5. Confirmed, fixed: the refactor dropped the `badges_left_out` log field. New
   `lookup(keys, conn, facets)` returns present features and the changed keys;
   `present_features` delegates to it and badges log `badges_left_out` again.
6. Confirmed, fixed: after `close()`, `readiness()` still said usable. A closed access
   now reports `unavailable`/`closed` (keeping the provenance it validated, which the
   refusal path reads), `bind` refuses and every read raises "closed".

Not changed (reviewer notes, not defects): there is no batching helper above 50 keys
(alert emails and recommendations stay far below it); a store key absent from the
listings database is treated as unchanged (harmless for keys taken from current rows;
a `FeatureScope` only matches existing rows anyway); listings first listed after the
snapshot are never in the store, so feature alerts cannot fire for them until a
rebuild (unknown, not absent; for WO-025 to state). `badges_enabled()` accepts " 1 "
(`.strip()`), unchanged from main and outside this work order.

Verification after the fixes (this Mac only; Docker and Ollama are not available, so
container tests skip; CI evidence is separate): `MYSQL_HOST= pytest -q` 4,320 passed,
129 skipped (main `5432dc2`: 4,269 passed, 129 skipped; 51 access tests, 7 of them new
in this round); `ruff check .` and `ruff format --check .` clean. Featureless search is
unchanged (it never opens the store). Not merged; nothing installed or enabled.
