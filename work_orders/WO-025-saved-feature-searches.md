# WO-025 — Saved feature searches

**Driver:** agent (owner reviews the PR; the owner activates)
**Depends on:** WO-023 shared enrichment access (PR #142, unmerged: this branch is
stacked on `wo-023-enrichment-access`; merge after #142), WO-009 saved searches and
alert drafts, WO-021 feature search
**Estimated effort:** planning input only, not a commitment

## Objective
A saved search may carry the same remark `features` as `search_listings`, and the
operator's alert job matches them through `enrichment.access.FeatureAccess` only. When
features cannot be checked, a feature search is explicitly unavailable for that run: it
is never run without its features, never claims "no new matches", and its alert state
does not move, so nothing is lost once enrichment is back.

## Why
WO-021 refused `save_search` with features because alerts could not apply them, so a
user who searched for "homes with solar in Pasadena" could not save that search. WO-023
gave every consumer one `bind(features, conn)` decision, so alerts can now use exactly
the rule search uses instead of a copy.

## Inputs
`alerts/{server,store,query,run,template}.py`, `domain/alerts.py`,
`enrichment/access.py` (WO-023 public API: `FeatureAccess`, `Binding`, `LIMITATION`),
`db/listings.py` (`_where`, `FeatureScope`), `domain/models.PropertySearchFilters`
(the `features` validator and `MAX_FEATURES`), `docs/ALERTS.md`, `docs/CONTRACTS.md`
(WO-009 and WO-021/WO-023 sections), `skills/saved-searches/SKILL.md`.

## In scope
1. Save: with the switch on, `save_search` validates `features` with the search
   validator (eligible facets, at most 5, deduplicated and sorted) and binds them once
   through `FeatureAccess.bind`. A usable binding saves the search with its features; an
   unusable, stale, too-broad or failing store refuses the save with a Clarification
   (nothing saved). With the switch off the WO-021 refusal is unchanged.
2. Persistence and reload: features live inside the stored filters JSON (no column
   change); list views and reloads return them; old rows without features load and run
   exactly as before.
3. Alert matching: a feature search binds its features through `FeatureAccess.bind` and
   its new-listing query adds the bound `FeatureScope` (keys with every feature present,
   and no row of the listing changed since the snapshot). Unknown, missing and changed
   listings never match.
4. Explicit unavailable outcome per run: switch off, store unconfigured, missing,
   malformed, stale, too broad, closed, any enrichment exception, or a snapshot that
   ends before the next window. No draft, no "no matches" outcome, checked date and keys
   unchanged; the job summary counts it and the exit code says so.
5. Snapshot horizon: a feature search is checked only up to the enrichment snapshot date
   (`min(active as-of, snapshot date)`), because listings first listed after the snapshot
   are not in the store (unknown, not absent). Its window moves only to that horizon, so
   those listings are still considered once the store is rebuilt. A new feature search
   starts at the same horizon.
6. Duplicates: saving a feature search equal to one of the same sender's saved searches
   (ignoring page and page size; features are order-insensitive) returns the existing
   search instead of a second copy. Duplicate listing rows and repeated matches are
   handled by the existing ranked query, alerted-key list and per-snapshot draft key.
7. Off switch `IDX_FEATURE_SAVED_SEARCHES` (on only when exactly `1`), in `IDX_SETTINGS`
   and `.env.example`.
8. Docs: `docs/ALERTS.md`, `docs/CONTRACTS.md`, the saved-searches skill body.

## Out of scope
A tool to edit a saved search in place (refining is a new save, optionally followed by
the existing confirmed delete), deal-signal alerts (stay disabled), any change to
`enrichment/access.py` or the store, feature search itself, badges, recommendation
explanations, scheduling, delivery, live migration, installation or activation.

## Files expected to change
`src/idx_agent/alerts/{server,store,query,run,template}.py`, `src/idx_agent/alerts/features.py` (new), `src/idx_agent/db/pool.py`
(one allowlist line), `.env.example` (own lines), `tests/test_saved_feature_searches.py`
(new), `tests/test_alerts.py` (only the WO-021 refusal test, now switch-dependent),
`skills/saved-searches/SKILL.md` (body only; the description and routing pins stay),
`docs/ALERTS.md`, `docs/CONTRACTS.md`, this file.

## Interfaces and contracts
No tool is added or renamed; tool descriptions are unchanged (routing pins hold).
`save_search` already accepts `features`. `SavedSearch.filters.features` and
`SavedSearchView.filters.features` carry them. `run_job` gains an optional
`bind_features` callable and an optional `feature_reader`; its summary gains
`unavailable` (count) and `unavailable_reasons` (sorted fixed codes). Exit code 5: no search failed, but one or more feature searches
were unavailable and left unchanged.

## Implementation requirements
1. One `FeatureAccess` per save call and per job run (a `with` block); featureless saves
   and featureless job runs never open the store.
2. A feature search is never queried without a scope; `matches_nothing` is a real "no
   listing has every feature" result and advances to the horizon without a query.
3. Any refusal or exception in the feature step is `unavailable` for that search only;
   other searches continue.
4. The alert draft for a feature search names the features, the snapshot date, the count
   of in-window listings left out because they changed since the snapshot, and the
   shared limitation text.
5. Retrying a run never creates a second draft for the same search and horizon.

## Safety requirements
No remark text read or returned; listing keys and per-listing statuses never logged;
parameterized SQL with allowlisted columns; no address crosses a tool; drafts only, no
send; the private alert store is untouched by tests (synthetic copies in tmp dirs).

## Tests required
`tests/test_saved_feature_searches.py`, no database and no real data: save validation
(switch, store states, too many and unknown features, duplicates, owner isolation),
persistence and reload round trip, refine-and-save flows, page normalization, the
feature alert query (scope SQL, window, keys, changed count), job outcomes (applied,
matches nothing, unavailable for every reason, exceptions, snapshot behind, horizon,
retry and idempotency, crash recovery, replay, dry run, rollback by switch and by
unconfigured store), compatibility on a synthetic production-shaped alert database
with legacy rows, and notification through the offline in-memory sink only.

## Acceptance criteria
- With the switch off: every reply, payload and SQL statement for featureless
  searches is unchanged (the job summary only gains `unavailable: 0` and
  `unavailable_reasons: []`); a feature save is refused as before.
- With the switch on and a usable store: a feature search saves, reloads and alerts only
  on listings with every feature present and unchanged since the snapshot.
- Every unusable state gives an explicit unavailable outcome with no draft and no state
  change; switching off later never broadens a saved feature search.
- Ruff clean; full offline suite passes; CI green.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
pytest -q tests/test_saved_feature_searches.py tests/test_alerts.py
```

## Activation and rollback
Activation (owner, after #142 and this PR merge, and after Phase 1 acceptance): set
`IDX_ENRICHMENT_STORE` (already required by feature search) and
`IDX_FEATURE_SAVED_SEARCHES=1` in `.env`, restart the gateway so `idx_alerts` reloads,
then save one feature search and run `python -m idx_agent.alerts.run --dry-run`.
Rollback: unset `IDX_FEATURE_SAVED_SEARCHES` (or the store). Existing feature searches
then report `unavailable` on every run and are never checked without their features;
they keep their window, so re-enabling resumes without losing matches. Rolling the code
back to before this work order is also closed: the old alert query refuses a saved
search that holds features (counted as failed). No schema change, so no data migration.

## Stop conditions
- The `FeatureAccess` API cannot express a rule this needs (list it as a blocker; never
  edit `wo-023-enrichment-access` or fork its logic).
- Any change would alter featureless saved-search behavior.

## Status
2026-11-02: built, in review (branch `wo-025-saved-feature-searches`, stacked on #142
head `8475ab3`; merge after #142). Uses only the public `enrichment.access` API
(`FeatureAccess.configured`, `bind`, `Binding.refused`/`matches_nothing`/`info`/`scope`,
`LIMITATION`); nothing in `wo-023-enrichment-access` was edited or copied, and the API
was sufficient.

Decisions taken (conservative defaults; the owner may revisit):
1. **Separate off switch** `IDX_FEATURE_SAVED_SEARCHES` (exactly `1`). Reusing only the
   store setting would have turned feature saves on wherever feature search is already
   configured, as soon as this merged, and rolling them back would also have disabled
   feature search. The switch keeps the merge inert and lets Phase 2 be activated and
   rolled back on its own.
2. **Refuse, do not store an unavailable search.** A save whose features cannot be
   checked returns a Clarification (`features_unavailable`) and stores nothing.
3. **Snapshot horizon.** Listings first listed after the enrichment snapshot are not in
   the store (WO-023 review note), so a feature search is checked only through the
   snapshot day; when the snapshot does not reach past `checked_as_of` the run is
   `unavailable` (`snapshot_behind`) rather than skipping those listings.
4. **No schema change.** Features already fit the stored filters JSON, so no migration
   exists; compatibility is tested on a synthetic production-shaped file (the WO-009
   schema, rows without a `features` key) with an idempotent schema re-run.
5. **Duplicate detection only for feature saves.** Plain duplicate saves still create a
   second copy (WO-009 behavior, pinned by existing tests); extending detection to plain
   saves is left to the owner.

Known limits (documented, not changed): a listing that changed after the snapshot is
left out (and counted in the draft) and is not re-offered after a rebuild once the
window has passed it; a crash between draft creation and the SQLite commit, followed by
a store rebuild that moves the horizon before the retry, could leave an orphan pending
draft beside the new one (the same class as WO-009's active-date change; both stay
drafts that the owner reviews, and removal expires them by prefix).

Verification (this Mac only; Docker and Ollama are not available, so container tests
skip; CI evidence is separate): `MYSQL_HOST= pytest -q` 4,374 passed, 129 skipped
(#142 head `8475ab3`: 4,320 passed, 129 skipped; +54 = 53 in
`tests/test_saved_feature_searches.py` and one allowlist case); `ruff check .` and
`ruff format --check .` clean. Routing pins unchanged (skill description and tool
descriptions untouched; only the skill body changed). No live database, store, gateway,
installation or `.env` was touched; nothing was enabled.
