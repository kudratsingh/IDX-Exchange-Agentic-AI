# Release handoff: remark-feature search (WO-021 Phase 1)

What ships: the `features` filter on `search_listings` (PR #134, merged as `7f10734`)
and the acceptance fixes in PR #135. Card badges (PR #136) stay off and are not part of
this release. Nothing here has been deployed; every step below is for the owner to run.

## 1. Build the private store

Run from the repository root on the host that serves the tool. Nothing is paid; the
builder reads only the frozen local artifacts.

```bash
.venv/bin/python scripts/build_enrichment_effective_store.py
# -> {"listings": 54888, "statuses": {"contradictory": 10, "historical": 168,
#     "planned": 1346, "present": 168333, "stated_absent": 312, "uncertain": 5358}}
```

The builder refuses unless all of these match:
- every frozen artifact matches `data/enrichment/policy-audit-freeze-manifest.json`;
- the results table hashes to the approved digest
  `46cd0a6be8cece97e09d3865ee87aae80c17fe2b16e4aaaa1412f87649209815`;
- the source watermark is `2026-09-18 06:58:44`.

It writes `data/enrichment/full/effective-facets-v1.sqlite3` with mode 0600, under the
gitignored `data/`. To check the result:

```bash
.venv/bin/python -c "from pathlib import Path; from idx_agent.enrichment.effective_store \
import open_store; s = open_store(Path('data/enrichment/full/effective-facets-v1.sqlite3')\
.resolve()); print(getattr(s, 'info', s))"
# -> StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
#    rules_version='2026-11-01.4', listing_count=54888)
```

Anything else printed (a `StoreUnavailable` reason) means the store must not be
configured.

## 2. Configure

Add one line to the server's `.env`. The tool server reads `.env` when the gateway
starts it.

```
IDX_ENRICHMENT_STORE=data/enrichment/full/effective-facets-v1.sqlite3
```

A relative path resolves from the repository root. Leave `IDX_FEATURE_BADGES` unset.
No other setting changes.

## 3. Install

1. Merge the reviewed PRs, then `git pull` on the serving host.
2. Run `.venv/bin/pip install -e ".[dev]"`. No dependency changed, so this only refreshes
   the editable install.
3. Run `./scripts/install.sh`. The skills load in place, and the property-search and
   saved-searches skills changed.
4. Run `openclaw gateway restart`. This starts a fresh tool server that reads the new
   setting. Use a fresh WhatsApp session afterwards, as in `docs/DEMO_RUNBOOK.md`.

## 4. Verify offline, before any message is sent

```bash
.venv/bin/python -m pytest -q tests/test_feature_search_acceptance.py \
  tests/test_mcp_search_features.py tests/test_enrichment_effective_store.py \
  tests/test_db_listings_features.py tests/test_feature_filter_models.py
.venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena', 'features': ['solar']}); \
print(r.data.feature_filter.status, r.data.total_matches)"
# -> applied 14   (on the 2026-09-18 local snapshot; a newer database differs)
```

If the status prints `stale`, more than 10% of active listings changed since
2026-09-18, and the store needs a refresh (not in this release). If it prints
`unavailable`, step 1 or 2 is wrong.

## 5. Disable enrichment, keep ordinary search

1. Remove the `IDX_ENRICHMENT_STORE` line from `.env`, or leave it empty.
2. Run `openclaw gateway restart`.

Feature searches then answer "I can't filter by listing features right now…" and offer
the same search without features. Every search without features runs exactly as before:
it never opens the store, and its SQL and payload are unchanged (acceptance row A11). No
data or session needs to be removed.

## 6. Roll back the code

Revert the merge commits of #135 and #134 (`git revert -m 1 <merge>` for each, newest
first), then run steps 3.2–3.4. The private store can stay where it is; nothing reads it
without the setting.

## 7. Human acceptance script (owner phone, fresh session; not run by the agent)

Each step lists what to send and what to expect. Stop at the first mismatch and keep
the trace reference from the reply.

1. **"Homes in Pasadena with solar panels."**
   - A list of listings, and a filters line with "features solar".
   - A line saying "Features matched from listing descriptions as of 2026-09-18: solar."
   - The limitation sentence, ending "…a missing feature is unknown, not absent."
2. **"Only ones with at least 3 bedrooms."** The same feature line, now with 3+ beds. The
   solar filter is kept.
3. **"Show me more."** Page 2 of the same feature search, or "That was the last page"
   when there are 5 or fewer matches.
4. **"Any of those with a pool too?"** Features "pool, solar". All features are required.
5. **"Forget the features, just Pasadena 3+ beds."** No feature line. Ordinary results.
6. **"Homes in Pasadena with a jacuzzi."** A question listing the supported features. No
   search is run.
7. **Refusal.**
   - Owner action: empty `IDX_ENRICHMENT_STORE`, then `openclaw gateway restart`.
   - Send "Homes in Irvine with a clubhouse." Expected: "I can't filter by listing
     features right now… Want me to search the same area without the features?"
   - Send "Under 1.5M." Expected: refused again, with the features kept.
   - Send "Yes, search without the features." Expected: ordinary Irvine results under
     $1.5M.
   - Restore the setting and restart.
8. **"Save this search: Pasadena with solar."** Expected: "Saved searches can't include
   listing features yet. Should I save it without them?" Nothing is saved unless the
   owner agrees.
9. **Limitation check.** In every reply with a feature line, the limitation sentence is
   present and unedited, and no reply says a home "doesn't have" a feature.

Steps 1–9 call the model and so need a human `paid` token for that session. Record the
outcomes in `docs/EVIDENCE_LOG.md`.
