# Activation handoff: Phase 1 enrichment features and Phase 2 bounded analysis

**DRAFT (WO-029).** Written 2026-11-02 against `main` at `5432dc2` and the open PRs
#142–#146. It is finalized last, after WO-024, WO-025 and WO-030 are complete and the
combined changes are tested. Every place that still depends on unfinished work is marked
**TO FINALIZE**. Do not run a step that carries that marker.

Nothing in this file has been run on the serving host. The agent did not install, enable,
restart or live-test anything. It sent no message, made no paid call and did not read
`.env` or `~/.openclaw`. All commands below are for the operator (the owner), run from the
serving checkout's root with `.venv` active. Lines that start with `!` are typed by the
human at the Claude Code prompt; in a plain terminal, drop the `!`. The agent never runs
`consent.sh`.

The per-feature handoffs stay the detailed sources:
- `docs/RELEASE_WO021_SEARCH.md` (feature search);
- `docs/RELEASE_WO017_ANALYSIS.md` (bounded analysis; rewritten by #146).

This file sets the order, the gates between steps, failure handling and rollback across
all six capabilities. Where it differs from those files, section 10 says how and why.

## 0. Terms

**State ladder.** These are the rungs of `docs/ACCEPTANCE_MATRIX.md` (#143). A rung is
claimed only with its evidence.

| Rung | Meaning | Evidence |
|---|---|---|
| Merged | On `main` with CI green | merge commit |
| Installed | The serving host runs that revision: checkout at the revision, `pip install -e`, `install.sh`, `openclaw gateway restart` | `git rev-parse HEAD` plus the probes in C3 |
| Enabled | The opt-in switch is on in the tool server's `.env` and, for a skill, in the installed skill list | the probes in each procedure |
| Live-verified | A consented model or WhatsApp acceptance is recorded | an entry in `docs/EVIDENCE_LOG.md` |

**Evidence tiers.**
- **O:** offline or CI. No model and no gateway; the agent can run it.
- **M:** the owner's Mac. It touches private data, Docker or the gateway, but calls no
  model. These are operator steps.
- **L:** live. Model or WhatsApp turns, under the owner's paid authorization.

**Switches.** These are on only when the value is exactly `1`:
- `IDX_FEATURE_BADGES`;
- `IDX_FEATURE_EXPLANATIONS` (WO-024);
- `IDX_ANALYSIS_TOOL`;
- `IDX_CHART_DELIVERY` (WO-030, proposed).

`IDX_ENRICHMENT_STORE` is a path, not a switch. Empty means feature search is off.

## 1. Current state (2026-11-02, never overstated)

| # | Capability | Merged | Installed | Enabled | Live-verified |
|---|---|---|---|---|---|
| 1 | Feature search | Yes: #134 `7f10734`, #135 `c8b897c`. Shared-access refactor in **#142, open** | **No** at a main revision (see C2) | No: per STATUS.md, `IDX_ENRICHMENT_STORE` is not set. The agent did not read `.env` | No |
| 2 | Card badges | Yes, off: #136 `411a649`. Refactor in **#142, open** | No | No | No |
| 3 | Recommendation explanations | No: WO-024 is in progress on `wo-024-feature-explanations` (stacked on #142, no PR yet) | No | No | No |
| 4 | Saved feature searches | No: WO-025 not yet on a branch. `save_search` refuses features | No | No | No |
| 5 | Bounded analysis | Tool merged off: #138 `b318846`. Routing, skill and instructions in **#146, open** | No: worker image not built on the Mac (Docker is not running) | No | No |
| 5b | Chart delivery | No: WO-030 is in progress on `wo-030-chart-delivery` (stacked on #146, no commits yet) | No | No | No |

Private store (metadata only, read 2026-11-02 by the agent in the main checkout):
- `data/enrichment/full/effective-facets-v1.sqlite3` exists, with mode `0600`;
- `StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  rules_version='2026-11-01.4', listing_count=54888)`.

That is the built store. It is not "configured": configured means set in the serving
`.env`, which the agent does not read.

## 2. Release order and gates

```
G0  review + merge #142 (shared FeatureAccess)       owner merge approval
G1  review + merge WO-024, then WO-025 (consumers)   owner merge approval each
G2  Phase 1 install, once, at one recorded revision  C1-C3; all switches still off
P1  enable and accept, one at a time, each with its own restart and live check:
      1 search -> 2 badges -> 3 explanations -> 4 saved feature searches
    stop at the first failure; roll back only that step
G3  Phase 1 accepted (all four recorded in EVIDENCE_LOG.md)
G4  review + merge #146 (WO-027), then WO-030          owner merge approval each
G5  Phase 2 install at a new recorded revision; Phase 1 switches unchanged
P2  5 bounded analysis -> 5b chart delivery, each with its own restart and live check
```

Rules:
- One switch changes per restart, and each restart is followed by its live check.
  Then a failure belongs to the last switch that changed.
- Phase 2 code may already be on `main` when Phase 1 is installed (#146 is off by
  default). Phase 1 acceptance is valid only while the C3 probes show the default
  Phase 2 surface: 7 `idx` tools, 4 `idx_alerts` tools and 8 skills.
- Phase 2 starts only after G3. A Phase 2 failure must never be fixed by changing a
  Phase 1 switch, and the reverse holds too.
- Merges, live activation and paid sessions each need the owner's own approval. This
  file grants none of them.

## 3. Common operator procedures

### C1. Before any change: record and back up (M)

```sh
git rev-parse HEAD                                   # record in the evidence entry
cp -p ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.pre-wo029-$(date +%Y%m%d%H%M)
grep -nE '^(export )?IDX_(ENRICHMENT_STORE|FEATURE_BADGES|FEATURE_EXPLANATIONS|ANALYSIS_TOOL|ANALYSIS_IMAGE|CHART_DELIVERY)=' .env
```

- `install.sh` keeps only one backup, `openclaw.json.pre-idx.bak`, and overwrites it on
  every run. After two installs it no longer holds the pre-activation config, so make
  the dated copy yourself before each phase.
- The `grep` prints only the six non-secret lines named. Never paste `.env` itself
  anywhere.

### C2. Put the serving checkout on the release revision (M; owner decision D1)

The serving checkout is the main checkout: the venv's editable install points at its
`src/`, and `data/` (indexes, store, alerts DB, email store) resolves from its root.
On 2026-11-02 it is clean but on branch `wo-021-recommend-design` (`74c98d1`). That is
`7f10734` plus two unmerged experiment commits, and it is 24 commits behind
`origin/main`. It lacks #135–#141. Any gateway restart would load that code.

**TO FINALIZE (D1):** how the serving checkout reaches `main`. The branch is committed
and pushed, so switching loses nothing. The draft default is:

```sh
git status --short                 # expect no output; stop if anything is listed
git switch main && git pull --ff-only
git rev-parse HEAD                 # expect the recorded release revision
```

Do not serve from a separate worktree: `data/` is relative to the repository root, so
the store, indexes and alerts DB would all be missing.

### C3. Install and probe (M)

```sh
.venv/bin/pip install -e ".[dev]"
./scripts/install.sh
openclaw config validate
openclaw gateway restart
openclaw mcp doctor idx --probe          # 7 tools while bounded analysis is off
openclaw mcp doctor idx_alerts --probe   # 4 tools; no send tool
openclaw skills list                     # 8 skills while bounded analysis is off
python scripts/demo_preflight.py --minutes 60   # all pass except paid_token before a grant
```

- `demo_preflight.py` does not check `IDX_ENRICHMENT_STORE` or any switch. The
  per-procedure offline checks below cover them.
- **TO FINALIZE (WO-024, WO-025, WO-030):** confirm that none of them changes the
  default tool count (7), alert-tool count (4) or skill count (8). If one does, update
  these numbers.

### C4. Editing `.env` safely (rehearsed; see Appendix A)

- One line per setting, `NAME=1`. Quotes and surrounding spaces are stripped in `.env`,
  but an inline comment makes the value invalid. `IDX_ANALYSIS_TOOL=1 # on` reads as
  off.
- **The first line for a name wins.** Appending `IDX_FEATURE_BADGES=0` below an existing
  `IDX_FEATURE_BADGES=1` leaves badges **on**. To turn a switch off, edit or remove the
  existing line, then check that `grep -c '^IDX_FEATURE_BADGES=' .env` prints `1` or
  `0`, never `2`.
- **The process environment beats `.env`** for the tool server. A switch exported in the
  gateway's environment (shell profile or LaunchAgent) overrides `.env`. WO-027's
  `install.sh` reads only `.env`, so an exported `IDX_ANALYSIS_TOOL=1` can register the
  tool while the skill stays unlisted. Keep every switch in `.env` only. After each
  restart the probes are the truth: the tool count and skill count must agree (7/8, or
  8/9 with analysis on).
- Spaces are handled differently in the process environment only: `IDX_FEATURE_BADGES=" 1"`
  counts as on, while `IDX_ANALYSIS_TOOL=" 1"` counts as off. Another reason to keep the
  switches in `.env`.

### C5. Live-check rules (L)

- A fresh session first: send `/new` from the owner phone.
- The owner authorizes the paid session. Chat-model costs come from the provider
  console.
- None of the Phase 1 or Phase 2 checks below calls `find_similar_listings` or a long
  document question, so the tool server needs no `paid` token. If you add such a
  message, mint the server token first, as in `docs/DEMO_RUNBOOK.md`:
  `! scripts/guards/consent.sh paid 60 --command "python -m idx_agent.mcp_server.server" --max-calls 5`
- Stop at the first mismatch and keep the reply's trace reference.
- Record outcomes in `docs/EVIDENCE_LOG.md` (owned by #143 until it merges). Use
  aggregates and card positions only: no listing numbers, addresses or remarks.
- End an unused paid token early with `! scripts/guards/consent.sh revoke paid`.

### C6. Rollback, common part

1. Edit the switch line (C4), then run `openclaw gateway restart`.
2. Rerun `install.sh` only if a skill list depends on the switch (procedure 5).
3. Send `/new`. Check the residue (each procedure lists its own).
4. To undo a code change, revert merge commits newest first with
   `git revert -m 1 <merge>`, then repeat C3.
5. Restoring the C1 config copy is the last resort, for a config the merge cannot fix:
   `cp -p ~/.openclaw/openclaw.json.pre-wo029-<stamp> ~/.openclaw/openclaw.json`, then
   restart.

Deleting any residue file is optional and is the owner's decision. The agent never
deletes; a `delete` grant would be needed for it to do so.

---

## 4. Procedure 1: remark-feature search

**State:** merged (#134, #135); refactored by #142 (open); not installed at a main
revision; not enabled; not live-verified.

**Prerequisites**
- #142 merged (G0). Search reads through `FeatureAccess` with no behavior change.
- C2 and C3 done at the release revision.
- Store built and valid. Run on the serving host:

  ```sh
  .venv/bin/python -c "from pathlib import Path; from idx_agent.enrichment.effective_store \
  import open_store; s = open_store(Path('data/enrichment/full/effective-facets-v1.sqlite3')\
  .resolve()); print(getattr(s, 'info', s))"
  # -> StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  #    rules_version='2026-11-01.4', listing_count=54888)
  ```

  Any `StoreUnavailable(reason=...)` stops this procedure. Rebuilding the store is
  `RELEASE_WO021_SEARCH.md` §1. It is free, but it needs the frozen artifacts and the
  approved digest.
- Freshness. The snapshot is stale when more than 10% of active listings changed since
  `2026-09-18 06:58:44`, or have no change time. The local database is a frozen
  2026-09-18 snapshot, so it is fresh today. The optional inventory, from the main
  checkout, writes a private file under `data/`:
  `python scripts/refresh_preflight.py` (add `--overwrite` if the inventory exists).
  The recorded result is 54,885 unchanged, 321 never extracted, 3 ambiguous.
- Env: `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS`, `IDX_ANALYSIS_TOOL` and
  `IDX_CHART_DELIVERY` are absent from `.env` or set to anything but `1`.

**Enable (M)**

```sh
# add exactly one line to .env (relative paths resolve from the repository root):
# IDX_ENRICHMENT_STORE=data/enrichment/full/effective-facets-v1.sqlite3
openclaw gateway restart
```

**Offline acceptance (O, then M)**

```sh
.venv/bin/python -m pytest -q tests/test_feature_search_acceptance.py \
  tests/test_mcp_search_features.py tests/test_enrichment_effective_store.py \
  tests/test_db_listings_features.py tests/test_feature_filter_models.py
# main 5432dc2, Mac, 2026-11-02: 117 passed
# TO FINALIZE: count at the release revision (after #142, which adds tests/test_enrichment_access.py)
.venv/bin/python -c "from idx_agent.db import pool; from idx_agent.enrichment.access import \
FeatureAccess; c = pool.connect(); a = FeatureAccess.configured(); r = a.readiness(c); \
print(r.status, r.reason, r.active, r.changed); a.close(); c.close()"
# -> usable None <active count> <changed count>   (needs #142; prints counts only)
.venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena', 'features': ['solar']}); \
print(r.data.feature_filter.status, r.data.total_matches)"
# -> applied 14   (2026-09-18 snapshot; a newer database differs)
```

**Smallest live check (L).** Send `/new`, then "Homes in Pasadena with solar panels."
- Expect a list of cards and a filters line with "features solar".
- Expect "Features matched from listing descriptions as of 2026-09-18: solar."
- Expect the limitation sentence, unedited, ending "…a missing feature is unknown, not
  absent."
- No card shows a `From description:` line (badges are still off), and no reply says a
  home "doesn't have" a feature.

The full script is `RELEASE_WO021_SEARCH.md` §7, steps 1–9. Phase 1 acceptance for this
procedure is that script.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "I can't filter by listing features right now…" | Store unavailable: unset, wrong path, missing, malformed, incomplete or replaced | Run the store check above. Fix `IDX_ENRICHMENT_STORE` (edit the line, never append) and restart |
| "The listing-feature data is out of date with the listings…" | Stale: more than 10% of active listings changed since the snapshot | Do not force it. The store needs a refresh, which is out of scope and paid. Roll back |
| A feature line without the limitation, or "doesn't have" wording | Model relay defect | Record it with the trace reference. Roll back if it repeats after one resend |
| Badge lines appear | A badges switch is on somewhere (`.env` first-wins, or the process environment) | Run C4 checks. Restart |
| Ordinary searches change | Must not happen (acceptance A11) | Stop. Roll back the code (C6) and report |

**Rollback**
1. Remove the `IDX_ENRICHMENT_STORE` line, or leave it empty.
2. Run `openclaw gateway restart` and send `/new`.

Expected result:
- A feature search answers the "can't filter" line and offers the same search without
  features.
- Searches without features are byte-for-byte unchanged and never open the store.

Residue: the private store stays in `data/` and is inert without the setting. Check with
`grep -c '^IDX_ENRICHMENT_STORE=' .env`, which should print `0`, or `1` with an empty
value.

Code rollback: revert #142 (when merged), then #135 and #134, newest first, then C3.

## 5. Procedure 2: card badges

**State:** merged off (#136); refactored by #142 (open); not installed; not enabled; not
live-verified.

**Prerequisites**
- Procedure 1 accepted. Badges read the same store under the same rules.
- #142 merged.
- Owner decisions D2 (cap, "+N more", order, area facets, wording) settled.
  **TO FINALIZE (WO-024 / D2):** whether WO-024 changes badge presentation. The draft
  assumes the current defaults: up to 3 per card, requested first then A–Z, area facets
  shown, prefix `From description:`.

**Enable (M):** add `IDX_FEATURE_BADGES=1` to `.env`, then `openclaw gateway restart`.

**Offline acceptance**

```sh
.venv/bin/python -m pytest -q tests/test_card_badges.py
# main 5432dc2, Mac: 41 passed. TO FINALIZE: count at the release revision
IDX_FEATURE_BADGES=1 .venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena'}); b = r.data.card_badges; \
print(len(r.data.listings), len(b.badges) if b else 0, \
max((len(v) for v in b.badges.values()), default=0) if b else 0)"
# -> <cards> <badged cards, at most cards> <at most 3>
```

The same probe without the switch prints `<cards> 0 0`, with identical listings.

The probe sets the switch in its own process only. It proves the code path, not the
gateway's state; the live check does that.

**Smallest live check (L).** Send `/new`, then "Homes in Pasadena under $1.5M" (no
feature).
- Most cards carry one `From description: …` line, after the pool/view line, with at most
  3 features.
- One reply note: `Card lines marked "From description:" are features matched from
  listing descriptions as of 2026-09-18.`, followed by the limitation, once.
- Card count, order and every other card fact are unchanged from a badges-off search.
- Then send "is the second one priced right?". The recommendation cards carry no badge
  line.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| No badge lines anywhere | Switch not effective (typo such as `true`, a second line, or an empty process-environment value), or the store is stale or unavailable | C4 checks. Run procedure 1's readiness command; with stale or unavailable, badges are silent by design |
| More than 3 badges, or a badge on an alert, email or recommend card | Defect | Roll back. Report it with the trace reference |
| Search results differ from badges-off | Must not happen | Stop. Roll back |

**Rollback:** edit `IDX_FEATURE_BADGES` to remove it (not append `=0`), then restart and
send `/new`.

Expected result: no `From description:` lines, and the payload is byte-for-byte as with
badges off.

Residue: none (no files). Check that `grep -c '^IDX_FEATURE_BADGES=' .env` prints `0`.

## 6. Procedure 3: recommendation explanations (WO-024)

**State:** not merged (WO-024 in progress, stacked on #142); not installed; not enabled;
not live-verified.

**Prerequisites**
- Procedures 1 and 2 accepted. Badges may stay on or be turned off first;
  **TO FINALIZE: say which combination WO-024 was tested with.**
- #142 and WO-024 merged.
- Owner decision D3 settled (P1-3 in the acceptance matrix): the explanation line only,
  ranking unchanged, and which facets count. **TO FINALIZE (WO-024).**

**Enable (M):** add `IDX_FEATURE_EXPLANATIONS=1` to `.env`, then restart.
**TO FINALIZE (WO-024):** confirm the switch name, that it is read through `IDX_SETTINGS`
in `src/idx_agent/db/pool.py`, and whether it needs `IDX_ENRICHMENT_STORE` only, or also
`IDX_FEATURE_BADGES`.

**Offline acceptance.** **TO FINALIZE (WO-024):** the exact test files and count, plus a
one-line probe like procedure 2's. The probe should print, for one `recommend` call, the
card count, the explained count and the maximum features per explanation. It must show
the ranking identical with the switch on and off.

**Smallest live check (L).** **TO FINALIZE (WO-024).** The draft shape: `/new`, a
Pasadena search, then "is the first one priced right?" or "homes like the first one".
- Expect the unchanged recommendation cards in the same order.
- Expect an explanation line (draft wording "Also mentions: …") only on cards whose
  features are present and unchanged.
- Expect the limitation once, and no "doesn't have" wording.

**Failure handling.** **TO FINALIZE (WO-024):** user-visible text for an unavailable or
stale store. The expected design, per WO-023, is no explanations and an unchanged
recommendation.

| What you see | Meaning | Action |
|---|---|---|
| Recommendation order differs from switch-off | Must not happen under D3 "line only" | Stop. Roll back |
| No explanation lines | Switch typo or second line, or store stale or unavailable | C4 checks; procedure 1's readiness command |

**Rollback:** remove the `IDX_FEATURE_EXPLANATIONS` line, restart, send `/new`. Expected
result: recommendation replies are byte-for-byte as before. Residue: none expected.
**TO FINALIZE (WO-024):** confirm no files and no stored state.

## 7. Procedure 4: saved feature searches (WO-025)

**State:** not built (WO-025 not yet on a branch); not merged; not installed; not
enabled; not live-verified. Today `save_search` answers "Saved searches can't include
listing features yet. Should I save it without them?", and the alert query refuses a
saved search with features.

**Prerequisites**
- Procedures 1–3 accepted. #142 and WO-025 merged.
- Owner decision D4 settled: what a saved feature search means as the snapshot ages,
  and whether feature alerts exist at all (P1-5, P1-6).
- **TO FINALIZE (WO-025):** whether the alerts SQLite schema changes. If it does, the
  migration on the live DB (`IDX_ALERTS_DB_PATH`, default `data/state/alerts.sqlite`) is
  a separate, owner-approved step with its own backup. Rehearse it on a synthetic copy
  only; this file never migrates the live DB.

**Enable (M).** **TO FINALIZE (WO-025):** whether WO-025 has its own switch. If not, the
feature is on whenever `IDX_ENRICHMENT_STORE` is set, which must be stated here. Then:
the install (C3), because the saved-searches skill text may change, and a restart.

**Offline acceptance.** **TO FINALIZE (WO-025):** test files and count, a synthetic-DB
round trip (save with features, list, delete), and the alert query on a synthetic copy.

**Smallest live check (L).** **TO FINALIZE (WO-025).** The draft shape: `/new`, "Homes in
Pasadena with solar panels.", then "Save this search."
- Expect a confirmation that names the features and the snapshot limitation.
- "list my saved searches" shows it with its features.
- Then delete it ("delete that saved search"), so no live row is left behind.
- No alert is sent; approval before any delivery is unchanged.

**Failure handling.** **TO FINALIZE (WO-025):** behavior when the store becomes
unavailable or stale after a feature search was saved.

**Rollback.** **TO FINALIZE (WO-025).** This is the one Phase 1 step with stored state.
- If saved searches with features exist when the code is reverted, the pre-WO-025 alert
  query raises on them by design ("saved-search alerts do not support listing
  features").
- The finalized rollback must say whether such rows are inert, or must be removed first.
  Removal is a deletion of owner data and needs the owner's decision.
- Residue check: a count of saved searches that carry features, run read-only. The exact
  command is to be finalized; it must print a count only.

---

## 8. Procedure 5: bounded analysis (Phase 2)

**State:** tool merged off (#138); routing, skill and instructions in #146 (open); not
installed (worker image not built); not enabled; not live-verified.

**Prerequisites**
- Phase 1 accepted (G3). #146 merged (G4).
- Docker Desktop running on the serving Mac. The image is built and pinned, and
  isolation is proven there (`RELEASE_WO017_ANALYSIS.md` §1):

  ```sh
  open -a Docker
  docker build --tag idx-analysis-worker:local docker/analysis-worker
  docker image inspect --format '{{.Id}}' idx-analysis-worker:local      # -> sha256:...
  IDX_ANALYSIS_IMAGE=sha256:<id> IDX_REQUIRE_CONTAINER=1 \
    .venv/bin/python -m pytest -m container -q tests/test_analysis_isolation.py \
    tests/test_analysis_render.py tests/test_analysis_executor.py   # all pass; a skip is a failure
  ```

- Owner decision 1 (made): the "can't help" line is unchanged, and the enabled
  instructions name `bounded_analysis` (section 10).

**Enable (M)**

```sh
# .env, one line each:
# IDX_ANALYSIS_IMAGE=sha256:<id>
# IDX_ANALYSIS_TOOL=1
./scripts/install.sh       # prints "Bounded analysis is on (IDX_ANALYSIS_TOOL=1)"
openclaw config validate
openclaw gateway restart
openclaw mcp doctor idx --probe   # 8 tools, including idx__bounded_analysis
openclaw skills list              # 9, including bounded-analysis
```

If `install.sh` prints "IDX_ANALYSIS_IMAGE in .env is unset or not pinned by digest", fix
the pin before the restart.

**Offline acceptance**

```sh
IDX_ANALYSIS_TOOL=1 .venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
'bounded_analysis' in s.server.instructions)"                       # True True True
.venv/bin/python -m pytest -q tests/test_analysis_integration.py \
  tests/test_mcp_bounded_analysis.py tests/test_analysis_service.py \
  tests/test_skill_files.py tests/test_routing_contract.py tests/test_openclaw_merge_config.py
# #146 head 6e877f3, Mac, no Docker or DB: 150 passed, 2 skipped (db). TO FINALIZE at the release revision
```

**Smallest live check (L).** Send `/new`, then "Is bigger always pricier in Glendale?"
- Expect "Bounded analysis of N sales in Glendale…", a correlation marked verified (or
  mismatched, with the trusted value), and caveats that this is a bounded sample.
- Expect no chart unless one was asked for.
- Then send "What will prices do next year in Pasadena?". Expect the unchanged one-line
  "I can't help with that…" reply and no tool call.

The full script is `RELEASE_WO017_ANALYSIS.md` §6 (as rewritten by #146), steps 2–7.
Step 1, the chart, belongs to 5b.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "Analysis is not available on this server right now (ref …)." | No pinned image, a tag instead of a digest, Docker not running, or the image missing from the engine | `docker image inspect` the pin. Start Docker. Never run code on the host |
| Probes disagree: 8 tools with 8 skills, or 7 tools with 9 skills | Switch differs between the gateway environment and `.env` (C4) | Remove the exported variable. Keep the switch in `.env`. Reinstall and restart |
| Rate-limit, timeout or safety-refusal message | Worker limits doing their job | Record it. Do not raise limits in this step |
| Forecast or valuation wording, or a number not marked verified or trusted | Defect | Roll back. Report it |

**Rollback**

```sh
# remove the IDX_ANALYSIS_TOOL line from .env (do not append =0: the first line wins)
./scripts/install.sh          # no "Bounded analysis is on" line; the 8-skill list returns
openclaw gateway restart
openclaw mcp doctor idx --probe   # 7 tools
openclaw skills list              # 8 skills
```

Send `/new`.

Residue:
- `~/.openclaw/openclaw.analysis.json5` stays in the state directory. It is inert:
  `install.sh` merges it only while the switch is on (rehearsed, Appendix A).
- `IDX_ANALYSIS_IMAGE` may stay; nothing reads it while the switch is off.
- The Docker image stays.
- `openclaw.json.pre-idx.bak` was overwritten by the rollback install; use the C1 copy
  if needed.

Code rollback: revert #146 (and #138 only if the tool itself must go), then C3.

## 9. Procedure 5b: chart delivery (WO-030)

**State:** not built (WO-030 in progress, stacked on #146); not merged; not installed;
not enabled; not live-verified.

Owner decision 2 (made): charts must actually reach the user on WhatsApp. The text-only
fallback is kept, but it does not complete this requirement. #146 records that OpenClaw
2026.9.5 does not relay MCP tool-result images to channels. WO-030 provides the delivery
path.

**Prerequisites**
- Procedure 5 accepted. WO-030 merged.
- **TO FINALIZE (WO-030):** any tool-policy or config change the delivery path needs
  (for example a skill or tool allow-list entry, or a media path), and its review.

**Enable (M).** **TO FINALIZE (WO-030):** `IDX_CHART_DELIVERY=1` (proposed name) in
`.env`. Also whether `install.sh` must rerun (a fragment or allow-list change), the
restart, and the probe output that shows it is on.

**Offline acceptance.** **TO FINALIZE (WO-030):** test files and count, and a probe that
shows a checked 960×600 PNG handed to the delivery path, with nothing on the host
filesystem outside the allowed location.

**Smallest live check (L).** Send `/new`, then "In Pasadena, chart sale price against
living area."
- Pass: one PNG arrives in the same chat, intact (it opens and is 960×600), with the
  text reply and its caveats. Record the delay.
- No PNG means the requirement is **not met**, even though the text is whole.
- **TO FINALIZE (WO-030):** the exact caption and confirmation wording.

**Failure handling.** **TO FINALIZE (WO-030).** At minimum:

| What you see | Meaning | Action |
|---|---|---|
| Text arrives, no image | Delivery path not active, or relay failed | Record it. Requirement not met. Roll back 5b only; 5 stays on |
| Image arrives corrupted or wrong size | Defect | Roll back 5b |
| The reply says "attached" or "sent" but no image arrived | Wording defect | Roll back 5b |

**Rollback.** **TO FINALIZE (WO-030):** remove the `IDX_CHART_DELIVERY` line, reinstall
if WO-030 adds a fragment, restart. Expected result: procedure 5 behavior with a
text-only chart line. Residue check for any delivered-media files or allow-list entries.

---

## 10. Departures from the earlier handoffs

- `RELEASE_WO017_ANALYSIS.md` §3, step 3 on main said to name `bounded_analysis` in the
  "can't help" line. That is not done, by owner decision 1. The line is copied verbatim
  in `config/IDX_RUNTIME.md` and the market-stats skill, and cannot vary with the switch
  without changing the default. The enabled instructions name the tool in their tool
  list instead (#146), and the routing rules stay consistent: the routing contract tests
  pin both states.
- `RELEASE_WO017_ANALYSIS.md` §3, steps 1–3 (hand edits to the skill list, routing table
  and pins) are replaced by #146's one switch plus `install.sh`.
- The old chart acceptance passed with text only. Under owner decision 2, image delivery
  (5b) is required.
- `RELEASE_WO021_SEARCH.md` §3.1 ("merge the reviewed PRs") is done for #134 and #135.
  This file adds #142 as a merge prerequisite and the serving-checkout step (C2).
- `RELEASE_WO021_SEARCH.md` §5 says to remove or empty the line. This file adds: edit,
  never append, because the first `.env` line wins.

## 11. Combined acceptance before presenting for merge (TO FINALIZE)

This runs after WO-024, WO-025 and WO-030 are complete, on an integration branch that
holds #142–#146 and those three. Its results replace these placeholders:
- the full offline suite count on the Mac, kept separate from CI counts. Docker and the
  fixture database are not available on the Mac, so `container` and `db` tests skip
  there and run in CI;
- cross-feature cases: feature search, then badges, then explanations on the same
  listings agree (same present-only, changed-listing and stale rules through
  `FeatureAccess`). A saved feature search matches what the live search returns for the
  same filters on the same snapshot;
- default-off: with every switch unset, the tool list, skill list, instructions, routing
  pins and every reply are unchanged from `main`;
- rollback: each switch off-after-on returns the default surface, and reverting each
  consumer leaves #142's behavior intact.

## Appendix A. Offline failure rehearsal (agent, 2026-11-02)

All runs were on the Mac, in temp directories under the session scratchpad, with
`env -i` (no inherited `IDX_*` or `MYSQL_*`). Nothing touched `~/.openclaw`, the real
`.env`, the live alerts DB, Docker or the gateway. No model was called.

1. **Switch values** (main `5432dc2`, `badges_enabled()` and `analysis.tool.enabled()`).
   - In `.env`: `1`, ` 1`, `1 ` and `"1"` are on. `true`, `TRUE`, `yes`, `on` and `0`
     are off. `1 # on` is off.
   - In the process environment: ` 1` turns badges on but analysis off.
2. **Conflicts.**
   - `.env=1` with environment `0` is off.
   - `.env=0` with environment `1` is on.
   - `.env=1` with an environment variable set but empty is off.
   - Two `.env` lines, `=1` then `=0`, stay **on** (the first wins).
3. **Store paths.** These are `open_store` reasons; #142's `FeatureAccess.readiness()`
   gives the same codes.
   - Unset: `not_configured`.
   - Missing file: `missing`.
   - Directory: `missing`.
   - Junk file: `malformed`.
   - Empty SQLite file: `malformed`.
   - Typo in a relative path: `missing`.
4. **Fail-closed behavior and staleness, existing tests** (main `5432dc2`):
   - the five feature-search files: 117 passed (including A5 unusable stores, A6 stale,
     A8 recovery, A10 save refusal);
   - `tests/test_card_badges.py`: 41 passed (off for `None`, `""`, `0`, `true`, `yes`,
     ` 2 `; silent on stale or unusable stores);
   - the four analysis files: 108 passed, 1 skipped.
   - On the #142 snapshot (`41d19c5`): the access, badge, search and acceptance files gave
     154 passed; `-k "stale or unavailable or missing or junk"` gave 6 passed.
5. **Tool surface.**
   - Main: switch unset or `true` gives 7 tools; `1` gives 8 tools.
   - #146 snapshot (`6e877f3`): the same, plus the instructions name the tool only when
     the switch is `1`.
6. **Unavailable worker** (#146 snapshot).
   - `test_no_docker_engine_is_unavailable_and_nothing_runs`,
     `test_an_image_missing_from_the_engine_is_unavailable` and
     `test_no_pinned_image_never_reads_or_runs[None|tag]` passed: 17 selected passed.
   - With no database configured, a direct call answers the database-not-configured
     error before any worker check, so the worker path was rehearsed only through the
     tests.
7. **`install.sh` switch and rollback.** This used #146's script in a throwaway repo
   copy, with `HOME` and `OPENCLAW_STATE_DIR` in a temp directory, stub `openclaw` and
   `node`, and a seeded JSON config.
   - off: 8 skills;
   - `true`: 8 skills;
   - `1`, unpinned: 9 skills, plus the "not pinned by digest" warning;
   - `1` with a tag instead of a digest: 9 skills, plus the warning;
   - `1` with a synthetic digest: 9 skills, no warning;
   - line removed: 8 skills, but `openclaw.analysis.json5` remains (inert residue);
   - `.env` off with `IDX_ANALYSIS_TOOL=1` exported to the installer: 8 skills (the
     installer reads `.env` only);
   - `=1` then `=0`: 9 skills (first wins; rollback by appending fails);
   - edited to `0`: 8 skills.
   - The existing WhatsApp channel key survived every merge.
   - A side observation: on a state directory with no prior config, the first run copies
     the JSON5 render as `openclaw.json`, and a second run's merge then fails to parse
     it. The owner's config came from `openclaw onboard`, so this only matters for a
     from-scratch rehearsal; seed a JSON config first.

## Appendix B. Placeholders to finalize

| Marker | Owner | Section |
|---|---|---|
| D1: bring the serving checkout to `main` | owner | C2 |
| Default tool, alert-tool and skill counts after WO-024, WO-025 and WO-030 | WO-024/025/030 | C3 |
| Feature-search test count at the release revision (after #142) | integration | 4 |
| Badge presentation after D2 and WO-024; badge test count | WO-024 / owner | 5 |
| Switch name, prerequisites, tests, probe, live wording, failure text and rollback residue for explanations | WO-024 | 6 |
| Switch (or none), schema migration, tests, live check, stale behavior and rollback of stored feature searches | WO-025 / owner D4 | 7 |
| Analysis test count at the release revision | integration | 8 |
| Delivery mechanism, policy change, switch, install step, tests, live wording, failure table and rollback for charts | WO-030 | 9 |
| Combined, cross-feature, default-off and rollback results; Mac vs CI counts | integration | 11 |
