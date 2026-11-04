# WO-024 — Shared-feature explanations on recommendations

**Driver:** agent (owner reviews the PR)
**Depends on:** WO-023 (PR #142, `FeatureAccess`; this branch is stacked on it and
merges after it), WO-011 (`recommend`), WO-021 increment 2 and its recommendation
design (`docs/RECOMMEND_FEATURES_DECISION.md`, carried from `wo-021-recommend-design`)
**Estimated effort:** planning input only, not a commitment

## Objective
When the owner turns it on, a `recommend` reply can say which home features the
descriptions of the subject and each recommended listing both mention ("Both
descriptions mention: pool, solar"), with the snapshot date and the existing
limitation. Ranking, candidates and price checks stay exactly as they are.

## Why
Recommendations are ranked by description similarity, and users ask what two homes
have in common. The effective-facet store already answers that for present features.
Explaining with it is the lowest-risk use the decision record identified (decision 1:
a line only); re-ranking is a separate proposal.

## Inputs
`enrichment/access.py` (WO-023: readiness, `lookup`, `AREA_FACETS`, `ordered`,
`LIMITATION`), the recommend path in `mcp_server/server.py`, `channels/format.py`
(`format_recommendations`), `domain/models.py` (`RecommendationResult`),
`skills/recommend/SKILL.md`, `docs/RECOMMEND_FEATURES_DECISION.md`,
`tests/test_mcp_recommend.py` (invented hashing-index harness).

## In scope
1. `SharedFeatures` (`features: dict[int, list[str]]`, `snapshot_watermark`,
   `limitation`) on `RecommendationResult.shared_features`, left out of the payload when
   unset.
2. The switch `IDX_FEATURE_EXPLANATIONS` (on only when exactly `1`, no surrounding
   spaces) in the pool allowlist and `.env.example`.
3. After ranking, fetching and every price check, the server opens one `FeatureAccess`,
   checks readiness, looks up the subject and the recommended keys (at most 6, under
   the 50-key limit) for eligible home facets (`ELIGIBLE_FACETS` minus `AREA_FACETS`),
   and keeps features present on both, A-Z.
4. Reply: one `Both descriptions mention:` line before an explained card's
   `Price check:` line, and one note (snapshot date and the limitation) before the dates
   line, only when at least one card is explained.
5. Skill paragraph: keep the lines, never add a feature, never infer absence, never
   call it the reason a home was chosen.
6. The WO-021 re-ranking scaffold (`enrichment/recommend_features.py`, its tests and
   `scripts/eval_recommend_features.py`) is carried from `wo-021-recommend-design`,
   switched to the shared `present_in` and `AREA_FACETS`; `recommend` never calls it.

## Out of scope (non-goals)
- Any feature weight or re-ranking: weights stay zero and the order never changes. The
  weighting policy remains an owner proposal (decision record, decisions 2 and 5).
- Preference arguments ("like this but with solar") on `recommend`: a contract change
  left to the owner (decision 3).
- Store, builder, overlay, frozen-result or eligibility changes; new indexes; any live
  configuration, installation or activation.

## Files expected to change
`src/idx_agent/mcp_server/server.py` (recommend path only), `src/idx_agent/channels/format.py`,
`src/idx_agent/domain/models.py`, `src/idx_agent/db/pool.py`, `.env.example`,
`skills/recommend/SKILL.md`, `docs/CONTRACTS.md` (the new `SharedFeatures` entry only),
`docs/RECOMMEND_FEATURES_DECISION.md`, `src/idx_agent/enrichment/recommend_features.py`,
`scripts/eval_recommend_features.py`, `tests/test_recommend_explanations.py`,
`tests/test_recommend_features.py`, `tests/test_card_badges.py` (two review tests),
`tests/test_db_pool.py` (allowlist pin), this file.

## Interfaces and contracts
`RecommendationResult` gains the optional `shared_features`; with the switch off the
payload, reply, SQL and log line are byte-for-byte as before. The `recommend` log line
adds `shared_features` (count, the store's reason, or `error` with `shared_error`) and
`shared_left_out` (count of changed keys) only when the switch is on; never a key or a
feature name. See `docs/CONTRACTS.md`, **SharedFeatures**.

## Implementation requirements
1. Off unless exactly `1`; off never opens the store; `k` 0 never opens it.
2. Explanations run after ranking, fetching and price checks, and nothing before them
   depends on the result: order, scores, `score_components`, candidates, filters sent
   to the SQL re-check and price checks are identical on and off.
3. Only eligible `present` statuses on both listings; area facets left out. Planned,
   uncertain, historical, stated-absent and contradictory statuses give nothing.
4. Fail closed through `FeatureAccess`: an unconfigured, missing, malformed (including
   repeated rows) or stale store, a store with no active listings, a subject changed
   since the snapshot or never extracted, or any exception gives no explanations; a
   changed candidate loses only its own line. The store is always closed.

## Safety requirements
No remark text read or returned; the store is read through `FeatureAccess` only (no
copy of its rules); listing keys and per-listing features are never logged; the
private store is never committed; payloads and docs carry invented examples only.

## Tests required
`tests/test_recommend_explanations.py` (33 collected): off by default and exact-`1`
parsing; identical order, scores, candidates, SQL re-check filters and price checks on
and off; present-on-both home features only; never-extracted and unqualified
candidates and a never-extracted subject show nothing; repeated store rows refused;
features listed once each; unusable, stale and no-active stores; changed subject and
candidate; failure; `k` 0; store closed; payload shape off and on; rollback (switch
unset again gives a byte-identical envelope and log line); formatting with no
explained card; the log line; badge and explanation switches independent.
`tests/test_card_badges.py`: empty results with badges on, and the explanations switch
never turning badges on. `tests/test_recommend_features.py`: the carried scaffold.

## Acceptance criteria
- With the switch unset, `recommend`'s payload, reply, statements and log line are
  unchanged (tested, including rollback after it was on).
- With it on, only supported, fresh shared home features are shown, with attribution
  (snapshot date) and the existing limitation once.
- Ruff clean; full offline suite and CI green.

## Activation and rollback (owner step; not done here)
Activation: after #142 and this PR merge, set `IDX_FEATURE_EXPLANATIONS=1` in the
installation's `.env` with `IDX_ENRICHMENT_STORE` already pointing at the validated
store, then restart the tool server. Check: a `recommend` reply for a listing whose
store entry has present features shows `Both descriptions mention:` lines and one note
dated the store's snapshot; the order matches the same call with the switch off; no line
names `condominium` (excluded by the 2026-11-03 owner decision, like the two area facets).
Rollback: unset the variable (or set anything but `1`) and restart; replies return to
exactly the pre-WO-024 form. No data, schema or store change is involved either way.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
pytest -q tests/test_recommend_explanations.py tests/test_recommend_features.py \
  tests/test_card_badges.py tests/test_mcp_recommend.py tests/test_enrichment_access.py
```

## Stop conditions
- Explaining would need a rule that differs from `FeatureAccess` (stop; do not fork).
- Any change would alter order, candidates or price checks.

## Status
2026-11-02: built, in review (branch `wo-024-feature-explanations`, stacked on
`wo-023-enrichment-access` at `8475ab3`; depends on #142, merge after #142). Off by
default; nothing installed, enabled or merged.

The draft was committed as-is, then rebased onto the stabilised WO-023 API without
conflicts. Adaptations: the server uses `FeatureAccess.lookup` (and logs
`shared_left_out`); the switch is strict (exactly `1`, like `IDX_ANALYSIS_TOOL`;
`IDX_FEATURE_BADGES` still strips spaces, unchanged); the note is shown only when a card
is explained; two docstrings were shortened to the five-line rule (not allowlisted); the
pool allowlist pin includes the new name.

Review of the 19 draft tests (13 functions) added 14 collected tests (11 functions)
for constraints reaching SQL unchanged, never-extracted candidates and subject, repeated
store rows, single listing of features, payload shape, rollback, formatting without an
explained card, the log line and switch independence. Badge relay coverage
(`tests/test_card_badges.py`) already pinned requested-feature ordering, attribution,
the limitation once, and stale and unavailable stores; added empty results and switch
independence.

Verification (this Mac only; Docker is not running and Ollama is not installed, so
container tests skip; CI evidence is reported separately on the PR): `MYSQL_HOST=
pytest -q` 4,368 passed, 129 skipped (base `wo-023-enrichment-access` `8475ab3`: 4,320
passed, 129 skipped; main `5432dc2`: 4,269 passed, 129 skipped); `ruff check .` and
`ruff format --check .` clean. No paid call, eval suite, extraction or live data use.

Open owner decisions:
1. Whether `condominium` counts as a shareable home feature (included now; subtype is
   already a hard filter, so it can only repeat what the card says).
2. The wording "Both descriptions mention:" and the note text.
3. Decision record items 2, 3 and 5 (weights, preference arguments, eval re-versioning)
   remain separate proposals; none is selected here.

2026-11-03, owner decisions (branch `chore-owner-decisions-20261103`; recorded in
`docs/RECOMMEND_FEATURES_DECISION.md`, "Owner decisions, 2026-11-03"). This WO merged in
PR #149. The open decisions above are answered:
1. Features do not change the order; "line only" stands. The rerank scaffold on
   `wo-021-recommend-design` stays a documented experiment, with no PR.
2. Weights deferred; if reopened, rarity-weighted, median 0.01, cap 0.03, never uniform.
3. Preference arguments: wanted as a hard filter on `recommend`, drafted as WO-031 (not
   approved to build).
4. `condominium` no longer counts: `EXPLANATION_FACETS` is eligible facets minus the two
   area facets minus `condominium`. Regression tests: `condominium` is not in the set, and
   a shared present `condominium` gives no explanation entry while order is unchanged.
   Both failed on the pre-change code (the shared map held `condominium` for two cards)
   and pass after it. `docs/CONTRACTS.md` **SharedFeatures** and the activation check
   above are updated. Switch-off payloads stay byte-identical (existing tests pass).
5. No eval set re-versioning: the order does not change.
Open decision 2 above (the wording "Both descriptions mention:" and the note text) was not
part of these answers; it stays open and the text stays as built.
