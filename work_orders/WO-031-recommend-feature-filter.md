# WO-031 — Feature filter on recommend ("like this but with solar")

**Driver:** agent (owner reviews the PR and runs any live check)
**Depends on:** WO-024 (PR #149, merged), WO-023 (PR #142, `FeatureAccess`), WO-021
(`features` on `search_listings`, its validator and fail-closed rules), WO-011 (`recommend`)
**Estimated effort:** planning input only, not a commitment

## Objective
`recommend` accepts an optional `features` argument. When it is given, only candidates
whose effective status is `present` for every named feature can be recommended. The
semantic order among the candidates that pass is unchanged, and so are the price checks.

## Why
The owner decided on 2026-11-03 (`docs/RECOMMEND_FEATURES_DECISION.md`, decision 3) that
a user-stated preference such as "like this but with solar" should be a hard filter,
not a boost. Search already filters on the same features, so recommend should reuse that
validator and `enrichment.access` instead of a second set of rules.

## Inputs
`domain/models.py` (`RecommendRequest`; the `features` validator on
`PropertySearchFilters`, `MAX_FEATURES`, `ELIGIBLE_FACETS`), `enrichment/access.py`
(`FeatureAccess.bind`, readiness, freshness, `LIMITATION`), the recommend path and the
search feature path (`_feature_scope`, `_feature_status`, `_feature_refusal`) in
`mcp_server/server.py`, `channels/format.py`, `skills/recommend/SKILL.md`,
`docs/CONTRACTS.md` (**FeatureFilter**, **SharedFeatures**), `tests/test_mcp_recommend.py`
and `tests/test_recommend_explanations.py` (harness), `evals/cases/recommendations.yaml`.

## In scope
1. An optional `features: list[str]` on `RecommendRequest` and the `recommend` tool,
   validated by the same rules as search (eligible names only, case and space folded,
   deduplicated, sorted, at most `MAX_FEATURES`). The validator is shared, not copied.
2. With `features` set, the candidate pool is restricted to keys `FeatureAccess.bind`
   returns, applied as a hard filter alongside city, subtype and price band, before the
   SQL re-check. The semantic order among the passing candidates is unchanged.
3. Fail closed exactly as search does: an unconfigured, missing, malformed, stale or
   too-broad store recommends nothing on features and returns a clear refusal with the
   offer to recommend without them; a candidate changed since the snapshot is left out
   and counted.
4. A `FeatureFilter` on `RecommendationResult` (same shape and limitation as search),
   left out of the payload when `features` is not given.
5. The skill: pass `features` only when the user names a feature; never infer one; say
   when no similar home has it; never claim a home lacks a feature.
6. Eval cases for the new argument (routing and the refusal wording), as a new version of
   the recommendation cases only if any existing pinned order changes (it should not).

## Out of scope
- Any boost, weight or re-ranking (decision 1: the order never changes for features).
- Changing the subject's own features or requiring the subject to have them.
- Area facets as filters beyond what search already allows; any store, builder, overlay
  or eligibility change; saved recommendations or alerts on features.
- Installing, enabling or live-checking anything.

## Files expected to change
`src/idx_agent/domain/models.py`, `src/idx_agent/mcp_server/server.py` (recommend path),
`src/idx_agent/channels/format.py`, `skills/recommend/SKILL.md`, `docs/CONTRACTS.md`
(`RecommendRequest` and `RecommendationResult` entries), `evals/cases/recommendations.yaml`
(new cases only), `tests/test_recommend_feature_filter.py` (new), this file.

## Interfaces and contracts
`RecommendRequest.features: tuple[str, ...] | None`, left out when unset.
`RecommendationResult.feature_filter: FeatureFilter | None`, left out when unset. Without
`features`, the payload, reply, SQL and log line are byte-identical to today. The log line
adds counts only (matched keys, left-out keys, the store's reason); never a key or a
feature name tied to a listing.

## Implementation requirements
1. Without `features`, nothing changes: the store is not opened for filtering (the
   WO-024 explanation switch keeps its own rule), and existing tests and digests pass.
2. Validation goes through the one shared validator; an unknown name or too many gives a
   Clarification, never a schema error.
3. Filtering happens before ranking is cut to `k`, so up to `k` passing candidates are
   returned when they exist; the semantic order among them is unchanged.
4. Only `present` matches. Planned, uncertain, historical, stated-absent and
   contradictory never match.
5. Fail closed through `FeatureAccess` with the same reasons as search; no copy of its
   freshness or validation rules.
6. Price checks run on the returned recommendations exactly as today.

## Safety requirements
No remark text read or returned; the store is read through `FeatureAccess` only; listing
keys and per-listing features never logged; the private store never committed; tests and
docs use invented examples only. SELECT-only, parameterized SQL, the 50-row limit and the
column allowlist are unchanged.

## Tests required
`tests/test_recommend_feature_filter.py`: argument absent is byte-identical (payload,
reply, log line); validator shared with search (same accepted and refused inputs);
present-only matching; non-present statuses never match; order among passing candidates
equals the unfiltered order restricted to them; fewer than `k` passing; none passing;
changed candidates left out and counted; unconfigured, missing, malformed, stale and
too-broad stores refused; `k` 0 with features; price checks unchanged; explanations and
filter together; the log line carries counts only.

## Acceptance criteria
- Without `features`, `recommend` is unchanged (tested, including the WO-029 cross-feature
  digests if that PR has merged).
- With `features`, only candidates with every named feature present and unchanged since the
  snapshot are recommended, in their unfiltered relative order, with the limitation shown.
- Every failure mode refuses rather than recommending without the filter.
- Ruff clean; full offline suite and CI green; new eval cases pass model-free.

## Verification commands
```
ruff check . && ruff format --check .
MYSQL_HOST= pytest -q
pytest -q tests/test_recommend_feature_filter.py tests/test_mcp_recommend.py \
  tests/test_recommend_explanations.py tests/test_mcp_search_features.py
```

## Deliverables
The optional argument, its fail-closed path, the contract entries, skill guidance, tests
and model-free eval cases. No activation.

## Stop conditions
- Filtering would need a rule that differs from `FeatureAccess` or the search validator.
- Any change would alter order among passing candidates or the price checks.
- The 200-candidate semantic pool is too small for common requests to return results;
  stop and report counts before widening it (a widening is an owner decision).
- Any need for a paid call, extraction or store rebuild.

## Status
2026-11-03: drafted, not approved to build. Drafted from the owner decision of
2026-11-03 (`docs/RECOMMEND_FEATURES_DECISION.md`, decision 3). Nothing is built.
