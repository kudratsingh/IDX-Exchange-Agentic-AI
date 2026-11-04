# Activation handoff: Phase 1 enrichment features and Phase 2 bounded analysis

**FINAL (WO-029), refreshed 2026-11-03 (review follow-ups).** Written against `main` at
`cbad756` (after #142, #143, #149 and #146 merged). It was checked on the combined branch
`chore-phase-integration-2` (`30ff289`). That branch is `main` plus the current heads of
the open PRs, merged with merge commits: #150 `c40eadb`, #144 `9da8062`, #145 `ee1c20f`,
#148 `6a27dca`, then this PR. Every expected output below was observed on that branch,
offline, on the owner's Mac, unless it is marked as an operator (M) or live (L)
expectation. Section 11 has the combined results and the merge order.

Nothing in this file has been run on the serving host. The agent did not install, enable,
restart or live-test anything. It sent no message, made no paid call and did not read
`.env` or `~/.openclaw`. All commands below are for the operator (the owner), run from the
serving checkout's root with `.venv` active. Lines that start with `!` are typed by the
human at the Claude Code prompt; in a plain terminal, drop the `!`. The agent never runs
`consent.sh`.

The per-feature handoffs stay the detailed sources:
- `docs/RELEASE_WO021_SEARCH.md` (feature search);
- `docs/RELEASE_WO017_ANALYSIS.md` (bounded analysis, as rewritten by #146);
- `docs/CHART_DELIVERY.md` (chart delivery; added by #148, sections 5a and 5b for expiry);
- `docs/ALERTS.md` (saved searches; the WO-025 section is added by #150).

This file sets the order, the gates between steps, failure handling and rollback across
all six capabilities. Where it differs from those files, section 10 says how and why.

## 0. Terms

**State ladder.** These are the rungs of `docs/ACCEPTANCE_MATRIX.md` (#143, merged). A
rung is claimed only with its evidence.

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

**Switches.** Each lives in `.env`, is listed in `IDX_SETTINGS`
(`src/idx_agent/db/pool.py`), and is on only for the value `1`:

| Switch | Capability | Read by | Notes |
|---|---|---|---|
| `IDX_FEATURE_BADGES` | 2 badges | `idx` tool server | Strips spaces: ` 1 ` is on (unchanged from main; decision list) |
| `IDX_FEATURE_EXPLANATIONS` | 3 explanations (#149) | `idx` tool server | Exactly `1`; ` 1 `, `1\n`, `01` are off |
| `IDX_FEATURE_SAVED_SEARCHES` | 4 saved feature searches (#150) | `idx_alerts` server and the alert job | Exactly `1`. `install.sh` never reads it |
| `IDX_ANALYSIS_TOOL` | 5 bounded analysis (#146) | `install.sh` and the `idx` tool server, one rule (`analysis.tool.switch_state`) | Exactly `1`. `.env` decides. A contradicting process environment makes `install.sh` refuse and the server stay off and report it |
| `IDX_CHART_DELIVERY` | 5b charts (#148) | `install.sh` and the `idx` tool server, the same rule | Exactly `1`, and only with `IDX_ANALYSIS_TOOL=1`. A contradiction is refused by `install.sh` and reported by the server, which keeps delivery off |

Settings that are not switches:
- `IDX_ENRICHMENT_STORE`: a path. Empty means feature search is off, and 2-4 need it too.
- `IDX_ANALYSIS_IMAGE`: the pinned worker digest. With the switch on, an environment
  value that differs from `.env` is refused by `install.sh` and reported by the server
  as a warning. Unlike a switch conflict, the server still registers the tool, and the
  tool uses the exported digest (C4).
- `IDX_CHART_DIR`: optional; an absolute path ending in `/idx-charts`; default
  `~/.openclaw/workspace-idx/idx-charts`. An environment value that differs from `.env`
  is refused and reported, as for the switches (#148).

## 1. Current state (2026-11-03, never overstated)

| # | Capability | Merged | Installed | Enabled | Live-verified |
|---|---|---|---|---|---|
| 1 | Feature search | Yes: #134 `7f10734`, #135 `c8b897c`; shared access #142 `426e198` | **No** (the serving checkout is not on `main`; C2) | No: per STATUS.md, `IDX_ENRICHMENT_STORE` is not set. The agent did not read `.env` | No |
| 2 | Card badges | Yes, off: #136 `411a649`, refactored by #142 `426e198` | No | No | No |
| 3 | Recommendation explanations | Yes, off: #149 `8987003` | No | No | No |
| 4 | Saved feature searches | **No: #150 open**, head `c40eadb`, base `main`, CI green | No | No | No |
| 5 | Bounded analysis | Yes, off: tool #138 `b318846`; switch, skill and instructions #146 `cbad756` | No: worker image not built on the Mac (Docker is not running) | No | No |
| 5b | Chart delivery | **No: #148 open**, head `6a27dca`, base `main`, CI green | No | No | No; WhatsApp delivery **UNVERIFIED** |

Not capabilities, but open in the same release: #144 (WO-026 omission pilot, head
`9da8062`) and #145 (WO-028 measurement v2, head `ee1c20f`), both CI green. #143 (the
acceptance matrix) is merged as `48a04b3`. `main` CI on `cbad756`: run `41601867893`,
success.

Private store (metadata only, read 2026-11-02 by the agent in the main checkout):
- `data/enrichment/full/effective-facets-v1.sqlite3` exists, with mode `0600`;
- `StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  rules_version='2026-11-01.4', listing_count=54888)`.

That is the built store. It is not "configured": configured means set in the serving
`.env`, which the agent does not read.

## 2. Release order and gates

```
G0  done: #142, #143, #149, #146 merged (main cbad756, CI green)
G1  merge #150 (saved feature searches)                    owner merge approval
    merge #144, #145 and #147 (any order; independent)      owner merge approval each
G2  Phase 1 install, once, at one recorded main revision    C1-C3; all switches still off
P1  enable and accept, one at a time, each with its own restart and live check:
      1 search -> 2 badges -> 3 explanations -> 4 saved feature searches
    stop at the first failure; roll back only that step
G3  Phase 1 accepted (all four recorded in EVIDENCE_LOG.md)
G4  merge #148 (chart delivery), CI green on main after it
G5  Phase 2 install at a new recorded revision; Phase 1 switches unchanged
P2  5 bounded analysis -> 5b chart delivery, each with its own restart and live check
```

Rules:
- One switch changes per restart, and each restart is followed by its live check.
  Then a failure belongs to the last switch that changed.
- The Phase 1 install revision already holds #146's analysis code, off. Default-off
  identity with the pre-#146 surfaces is proven (section 11), so this does not affect
  Phase 1. #148 is also off by default and arms nothing while off. Merging it before G3
  would not invalidate Phase 1, but the recommendation is to merge it at G4, so the
  Phase 1 revision carries no chart code. Phase 2 development and review continue in
  parallel; only Phase 2 *activation* waits for G3.
- Phase 1 acceptance is valid only while the C3 probes show the default surface:
  7 `idx` tools, 4 `idx_alerts` tools and 8 skills.
- A Phase 2 failure must never be fixed by changing a Phase 1 switch, and the reverse
  holds too.
- Merges, live activation and paid sessions each need the owner's own approval. This
  file grants none of them.

## 3. Common operator procedures

### C1. Before any change: record and back up (M)

```sh
git rev-parse HEAD                                   # record in the evidence entry
cp -p ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.pre-wo029-$(date +%Y%m%d%H%M)
grep -nE '^(export )?IDX_(ENRICHMENT_STORE|FEATURE_BADGES|FEATURE_EXPLANATIONS|FEATURE_SAVED_SEARCHES|ANALYSIS_TOOL|ANALYSIS_IMAGE|CHART_DELIVERY|CHART_DIR)=' .env
```

- `install.sh` keeps only one backup, `openclaw.json.pre-idx.bak`, and overwrites it on
  every run. After two installs it no longer holds the pre-activation config, so make
  the dated copy yourself before each phase.
- The `grep` prints only the eight non-secret lines named. Never paste `.env` itself
  anywhere.

### C2. Put the serving checkout on the release revision (M; owner decision D1)

The serving checkout is the main checkout: the venv's editable install points at its
`src/`, and `data/` (indexes, store, alerts DB, email store) resolves from its root.
On 2026-11-03 (read-only check) it is clean, on branch `wo-021-recommend-design` at
`74c98d1`, which is pushed. It is 45 commits behind `origin/main` and 2 ahead (two
unmerged recommendation-design commits). Any gateway restart would load that code.

The release revision for Phase 1 is the `main` merge commit recorded at G2 (after G1).
The steps, under the default for decision D1 (switch in place; the branch is committed
and pushed, so nothing is lost):

```sh
git status --short                 # expect no output; stop if anything is listed
git branch -r --contains wo-021-recommend-design | grep -q origin/wo-021-recommend-design && echo pushed
                                   # expect: pushed
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

Observed `install.sh` output with every switch off (temp HOME, combined branch, seeded
JSON config): `rendered …/openclaw.idx.json5`, `installed …/openclaw.json`, `IDX
response policy installed.`, both servers registered, then the "Next, by hand" list
ending `# expects 7 tools …`, `# expects 4 saved-search tools; no send tool` and
`# expects 8, including email and saved-searches`. No analysis or chart line.

- With every switch unset, the `idx` tool list, every tool schema and description and the
  server instructions hash to the values pinned from `main` `cbad756`, and #150 and #148
  add no tool, alert tool or skill (section 11). With `IDX_ANALYSIS_TOOL=1`: 8 tools and
  9 skills, with or without `IDX_CHART_DELIVERY=1`.
- `demo_preflight.py` does not check `IDX_ENRICHMENT_STORE` or any switch. The
  per-procedure checks below cover them.

### C4. Editing `.env` safely (rehearsed; see Appendix A)

- One line per setting, `NAME=1`. Quotes and surrounding spaces are stripped in `.env`,
  but an inline comment makes the value invalid. `IDX_ANALYSIS_TOOL=1 # on` reads as
  off.
- **The first line for a name wins.** Appending `IDX_FEATURE_BADGES=0` below an existing
  `IDX_FEATURE_BADGES=1` leaves badges **on**. To turn a switch off, edit or remove the
  existing line, then check that `grep -c '^IDX_FEATURE_BADGES=' .env` prints `1` or
  `0`, never `2`.
- **Keep every switch in `.env` only.** What each switch does when the process
  environment disagrees with `.env`, verified on the combined branch:
  - `IDX_ANALYSIS_TOOL` (the switch itself): `install.sh` refuses before writing
    anything (exit 1, no state directory created). The server does not register
    `bounded_analysis` (7 tools), keeps the base instructions, and reports the problem
    as the one `health` warning (appended to its message) and as
    `analysis_switch_problem` in its `server_start` log line. Observed, `.env` `=1` and
    environment `0` (an empty value gives the same line; pinned on `main`):
    `install.sh: Bounded analysis is misconfigured: IDX_ANALYSIS_TOOL is 1 in .env but
    not in the process environment, so the bounded-analysis skill is installed and the
    tool is not registered. Keep it in .env only (unset it in the environment), run
    scripts/install.sh, and restart the gateway.` With no `.env` line and environment
    `1`, the same, but `…is 1 in the process environment but not in .env, so install.sh
    added no bounded-analysis skill and the tool is not registered. …`.
  - `IDX_ANALYSIS_IMAGE` (the worker digest, with `IDX_ANALYSIS_TOOL=1` in `.env`,
    whether or not the switch is also exported): `install.sh` refuses the same way
    (exit 1, nothing written). **The server still registers `bounded_analysis` (8
    tools) and the analysis instructions.** It reports the problem only as a warning,
    in `health` and in `server_start`. The tool then runs the *exported* digest, not
    the one `install.sh` checked, because the environment wins for that setting.
    Observed: `install.sh: Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE in the
    process environment differs from .env, so install.sh checked one worker image and
    the tool runs the other. Keep it in .env only (unset it in the environment), run
    scripts/install.sh, and restart the gateway.` The `health` message ends with that
    sentence, and `server_start` lists `bounded_analysis` among its tools.
  - A differing `IDX_ANALYSIS_IMAGE` while the switch is off everywhere is not a
    problem: install succeeds, nothing is registered and nothing is reported.
  - Pinned by `tests/test_phase_integration.py::test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`
    (#147, four cases) and by `tests/test_analysis_switch_agreement.py` (main). The
    observed lines above come from offline runs on the combined branch, with `install.sh`
    in a temp `HOME` and state directory (stub `openclaw` and `node`), and an in-process
    start (`register_analysis_tool()` then `log_start()`, as `main()` does).
  - `IDX_CHART_DELIVERY`, `IDX_CHART_DIR` (#148): the switch rule (delivery stays off).
    Observed:
    `install.sh: Chart delivery is misconfigured: IDX_CHART_DELIVERY is 1 in .env but
    not in the process environment, so chart delivery is off. …` (exit 1, nothing
    written). The server keeps delivery off, names the problem in `health`, and arms no
    expiry thread or signal handler. A differing `IDX_CHART_DIR` is refused and reported
    the same way.
  - `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS`, `IDX_FEATURE_SAVED_SEARCHES`:
    `install.sh` never reads them. Its config and stdout are identical whatever their
    values in `.env` or the environment. Only the running server's view matters, and
    there the environment wins silently.
- After each restart the probes are the truth: the tool count and skill count must agree
  (7/8, or 8/9 with analysis on), and `health` must carry no misconfiguration warning.
  Matching counts alone do not rule out an image conflict: it leaves 8 tools but still
  warns in `health`.

### C5. Live-check rules (L)

- A fresh session first: send `/new` from the owner phone.
- The owner authorizes the paid session. Chat-model costs come from the provider
  console.
- None of the Phase 1 or Phase 2 checks below calls `find_similar_listings` or a long
  document question, so the tool server needs no `paid` token. If you add such a
  message, mint the server token first, as in `docs/DEMO_RUNBOOK.md`:
  `! scripts/guards/consent.sh paid 60 --command "python -m idx_agent.mcp_server.server" --max-calls 5`
- Stop at the first mismatch and keep the reply's trace reference.
- Record outcomes in `docs/EVIDENCE_LOG.md`. Use aggregates and card positions only: no
  listing numbers, addresses or remarks.
- End an unused paid token early with `! scripts/guards/consent.sh revoke paid`.

### C6. Rollback, common part

1. Edit the switch line (C4), then run `openclaw gateway restart`.
2. Rerun `install.sh` when a skill list or a reported state depends on the switch
   (procedures 5 and 5b); it is harmless for the others.
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

**State:** merged (#134, #135; shared access #142); not installed; not enabled; not
live-verified.

**Prerequisites**
- **Store rebuilt under review policy v5 (M), before the install.** Do not install the
  v4 store. First merge #151 (the v5 rulings, `docs/ENRICHMENT_REVIEW_POLICY_V5.md`),
  then rebuild the effective store under v5 as a versioned migration (WO-021 Status,
  2026-11-03; the rebuild belongs to WO-032): the builder reads the v5 file and the
  ruling-8 correction overlay, and a new v5 manifest is created beside the unchanged v4
  manifest. Then, on the rebuilt store and before the install, re-record the store info
  line below (`policy_version` will be `v5`) and the Pasadena `solar` probe count
  (`applied 14` on the v4 store). The overlay touches no solar label, so 14 is expected,
  but it must be observed, not assumed. If the builder refuses, stop: a builder refusal
  is a stop condition, not a status note.
- C2 and C3 done at the release revision.
- Store built and valid. Run on the serving host:

  ```sh
  .venv/bin/python -c "from pathlib import Path; from idx_agent.enrichment.effective_store \
  import open_store; s = open_store(Path('data/enrichment/full/effective-facets-v1.sqlite3')\
  .resolve()); print(getattr(s, 'info', s))"
  # -> StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  #    rules_version='2026-11-01.4', listing_count=54888)
  ```

  Any `StoreUnavailable(reason=...)` stops this procedure. A store with a repeated
  `(listing, facet)` row is refused (`malformed`). Rebuilding the store is
  `RELEASE_WO021_SEARCH.md` §1. It is free, but it needs the frozen artifacts and the
  approved digest.
- Freshness. The snapshot is stale when more than 10% of active listings changed since
  `2026-09-18 06:58:44`, or have no change time (`enrichment.access.STALE_SHARE = 0.10`).
  The local database is a frozen 2026-09-18 snapshot, so it is fresh today. The optional
  inventory, from the main checkout, writes a private file under `data/`:
  `python scripts/refresh_preflight.py` (add `--overwrite` if the inventory exists).
  The recorded result is 54,885 unchanged, 321 never extracted, 3 ambiguous.
- Env: `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS`, `IDX_FEATURE_SAVED_SEARCHES`,
  `IDX_ANALYSIS_TOOL` and `IDX_CHART_DELIVERY` are absent from `.env` or set to anything
  but `1`.

**Enable (M)**

```sh
# add exactly one line to .env (relative paths resolve from the repository root):
# IDX_ENRICHMENT_STORE=data/enrichment/full/effective-facets-v1.sqlite3
openclaw gateway restart
```

**Offline acceptance (O, then M)**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_feature_search_acceptance.py \
  tests/test_mcp_search_features.py tests/test_enrichment_effective_store.py \
  tests/test_db_listings_features.py tests/test_feature_filter_models.py \
  tests/test_enrichment_access.py
# combined branch, Mac, 2026-11-03: 168 passed
.venv/bin/python -c "from idx_agent.db import pool; from idx_agent.enrichment.access import \
FeatureAccess; c = pool.connect(); a = FeatureAccess.configured(); r = a.readiness(c); \
print(r.status, r.reason, r.active, r.changed); a.close(); c.close()"
# -> usable None <active count> <changed count>   (M; prints counts only)
.venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena', 'features': ['solar']}); \
print(r.data.feature_filter.status, r.data.total_matches)"
# -> applied 14   (M; 2026-09-18 snapshot; a newer database differs)
```

`tests/test_phase_integration.py` (this PR) also shows that configuring the store with
every switch off changes only the feature-search reply; plain search, recommend, routing,
tools and instructions stay byte-identical.

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
- Badges, explanations and saved feature searches go quiet with it (they need the store);
  saved feature searches stay stored and report `unavailable` (procedure 4).

Residue: the private store stays in `data/` and is inert without the setting. Check with
`grep -c '^IDX_ENRICHMENT_STORE=' .env`, which should print `0`, or `1` with an empty
value.

Code rollback: revert #142 only after reverting its consumers (#150 if merged, then
#149), newest first, then #135 and #134 if search itself must go, then C3.

## 5. Procedure 2: card badges

**State:** merged off (#136, refactored by #142); not installed; not enabled; not
live-verified.

**Prerequisites**
- Procedure 1 accepted. Badges read the same store under the same rules.
- The behavior is the merged default: up to 3 per card, requested features first then
  A–Z, area facets shown, prefix `From description:`. Owner decision D2 may still change
  it; until then this is what the live check expects.

**Enable (M):** add `IDX_FEATURE_BADGES=1` to `.env`, then `openclaw gateway restart`.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_card_badges.py
# combined branch, Mac: 43 passed
IDX_FEATURE_BADGES=1 .venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena'}); b = r.data.card_badges; \
print(len(r.data.listings), len(b.badges) if b else 0, \
max((len(v) for v in b.badges.values()), default=0) if b else 0)"
# -> <cards> <badged cards, at most cards> <at most 3>   (M)
```

The same probe without the switch prints `<cards> 0 0`, with identical listings. Run
against the synthetic world of the integration tests, it printed `5 3 3` on and `5 0 0`
off (2026-11-02; the badge code is unchanged since).

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
  line (explanations are still off).

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| No badge lines anywhere | Switch not effective (typo such as `true`, a second line, or an empty process-environment value), or the store is stale or unavailable | C4 checks. Run procedure 1's readiness command; with stale or unavailable, badges are silent by design (the log line carries `badges=<reason>`) |
| More than 3 badges, or a badge on an alert, email or recommend card | Defect | Roll back. Report it with the trace reference |
| Search results differ from badges-off | Must not happen | Stop. Roll back |

**Rollback:** edit `IDX_FEATURE_BADGES` to remove it (not append `=0`), then restart and
send `/new`.

Expected result: no `From description:` lines, and the payload is byte-for-byte as with
badges off (`tests/test_phase_integration.py`: rollback returns every surface to the
switch-off state).

Residue: none (no files, no stored state). Check that
`grep -c '^IDX_FEATURE_BADGES=' .env` prints `0`.

## 6. Procedure 3: recommendation explanations (WO-024, #149)

**State:** merged off (#149 `8987003`); not installed; not enabled; not live-verified.

**Prerequisites**
- Procedures 1 and 2 accepted. Explanations need only `IDX_ENRICHMENT_STORE`; they do
  not need badges. Tests pin that neither switch turns the other on, and the combined
  tests run explanations alone and with every switch on. Leave badges as procedure 2
  left them.
- Owner decision D3 is implemented as "explanation line only": ranking, scores,
  candidates, price checks and feature weights (zero) are unchanged and pinned by tests.
  Facets that count: home features present on both the subject and the card, area facets
  excluded (`EXPLANATION_FACETS = ELIGIBLE_FACETS - AREA_FACETS`); `condominium` is
  included (decision list).

**Enable (M):** add `IDX_FEATURE_EXPLANATIONS=1` to `.env`, then
`openclaw gateway restart`.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_recommend_explanations.py \
  tests/test_recommend_features.py tests/test_mcp_recommend.py
# combined branch, Mac: 103 passed
.venv/bin/python - <<'PY'
import os
from idx_agent.mcp_server import server as m
k = m.search_result({"city": "Pasadena"}).data.listings[0].listing_key
def run(v):
    os.environ["IDX_FEATURE_EXPLANATIONS"] = v
    d = m.recommend(listing_key=k)["data"]
    return [r["listing"]["listing_key"] for r in d["recommendations"]], d.get("shared_features")
off, _ = run("0")
on, s = run("1")
f = s["features"] if s else {}
print(len(on), on == off, len(f), max((len(v) for v in f.values()), default=0))
PY
# -> <cards> True <explained cards, at most cards> <features on the longest line>   (M)
```

The second field must be `True` (same order on and off). The probe prints counts only,
never a key. `tests/test_phase_integration.py` covers a subject that shares features
(exactly `pool, solar` on one card and `hardwood` on another).

**Smallest live check (L).** Send `/new`, "Homes in Pasadena", then "is the first one
priced right?".
- Expect the recommendation cards in the same order as with the switch off.
- Expect a `Both descriptions mention: …` line only on cards whose features are present
  on both homes and unchanged since the snapshot.
- Expect one note, once: `Lines marked "Both descriptions mention:" name features found
  in the descriptions of both homes as of 2026-09-18; other shared features may go
  unlisted.` followed by the limitation. No note when no card is explained.
- No "doesn't have" wording.

**Failure handling.** With an unavailable or stale store, a changed or never-extracted
subject, or any error, the reply is the unchanged recommendation with no explanation
line and no note; there is no user-visible error. The `recommend` log line carries
`shared_features=<reason>` (or a count) and `shared_left_out=<count>`.

| What you see | Meaning | Action |
|---|---|---|
| Recommendation order differs from switch-off | Must not happen ("line only") | Stop. Roll back |
| No explanation lines | Switch typo, ` 1`, or second line; store stale or unavailable; subject changed since the snapshot | C4 checks; procedure 1's readiness command; the log field |
| A line on a card whose feature the subject lacks | Defect | Roll back. Report it with the trace reference |

**Rollback:** remove the `IDX_FEATURE_EXPLANATIONS` line, restart, send `/new`. Expected
result: recommendation replies are byte-for-byte as before; the payload has no
`shared_features` key. Residue: none (no files, no stored state, no schema). Check that
`grep -c '^IDX_FEATURE_EXPLANATIONS=' .env` prints `0`.

## 7. Procedure 4: saved feature searches (WO-025, #150)

**State:** not merged (#150 open, head `c40eadb`, base `main`, CI green: runs
41751749477 push, 41751755840 pull_request); not installed;
not enabled; not live-verified. With the switch off (and on `main` today), `save_search`
answers "Saved searches can't include listing features yet. Should I save it without
them?".

**Prerequisites**
- Procedures 1–3 accepted. #150 merged.
- Owner decision D4: #150's conservative defaults are in force (decision list): a
  separate switch; a save whose features cannot be checked is refused and nothing is
  stored; a feature search is checked only up to the snapshot day, so listings first
  listed after the snapshot wait for a store rebuild; unknown, never-extracted and
  changed listings never match.
- Review fixes in `7831158`, and the dry-run fix in `c40eadb` (`docs/ALERTS.md`):
  - **Changed listings are deferred, not skipped.** The job moves a feature search's
    checked date only to the day before the earliest listing in its window that changed
    after the snapshot, and counts the search under `deferred`. After a store rebuild
    that listing is checked and alerted once. One draft per search and horizon, and the
    alerted-key exclusion, are unchanged.
  - **A held date never hides a stale store.** While a deferral waits and the active
    data is past the snapshot day, the search is `unavailable` with `snapshot_behind`
    (exit 5), in the normal job and in `--dry-run` alike.
  - **Dry-run tells the same story.** `--dry-run` makes the job's decisions through a
    read-only (`mode=ro`) connection. It reports the same exit code, `checked`,
    `deferred`, `failed`, `skipped`, `unavailable` and `unavailable_reasons` (including
    `snapshot_behind` and the 500 alerted-key cap). It writes no draft, alert-log row,
    checked-date change or SQLite change (`drafts: 0`, `pending: []`). Two exceptions:
    it never reads the owner-recipient or approval-journal settings, so where the job
    refuses with exit 2 for those settings, the dry-run can exit 0; and it never takes
    the draft and journal step, so a failure there shows only in the job.
  - **Lapsed searches are renewed, not "already saved".** Saving an equal search after
    its 180-day lapse renews it in place ("Search N had lapsed, so I renewed it: …"),
    with a new 180 days, alerts from the save horizon onward, and earlier alerted
    listings still excluded.
- **No schema change.** Features fit the existing `filters` JSON; there is no migration
  and the live alerts DB (`IDX_ALERTS_DB_PATH`, default `data/state/alerts.sqlite`) is
  never altered by activation. Compatibility was tested on synthetic WO-009-shaped files
  only.

**Enable (M)**

```sh
# .env, one line (IDX_ENRICHMENT_STORE already set by procedure 1):
# IDX_FEATURE_SAVED_SEARCHES=1
openclaw gateway restart      # idx_alerts reloads; no install.sh rerun is needed
```

The saved-searches skill body changed in #150, but its description did not, and the
skill is loaded in place, so the restart picks it up. `install.sh` output is identical
whatever this switch says in `.env` or the environment (observed on the combined branch
for env `0`/`.env` `1`, env `1`/no line and env empty/`.env` `1`). The alert job reads
the same `.env`; if you run it from cron or a LaunchAgent, do not export the switch there
(C4).

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_saved_feature_searches.py \
  tests/test_alerts.py tests/test_phase_integration_saved_searches.py
# combined branch, Mac: 110 passed (78 of them in tests/test_saved_feature_searches.py)
```

Observed on synthetic alert stores (never the live DB):
- a save with features, while on, answered `Saved search 1: Filters: city Glendale,
  features pool. Checked as of 2026-09-18. Alerts include only homes whose descriptions
  state every feature as of the 2026-09-18 listing-feature snapshot; a home not matched
  may still have them. …`;
- the list showed `1. Filters: city Glendale, features pool; checked 2026-09-18`, and,
  after the switch was turned off, `…; alerts paused: listing features are off`;
- `tests/test_phase_integration_saved_searches.py` (#150): a changed listing is left out
  of search, badges, explanations and the alert, the summary counts the search
  `deferred`, and after a store rebuild the listing is alerted exactly once; a repeated
  run drafts nothing new.

**Smallest live check (L).** `/new`, "Homes in Pasadena with solar panels.", then "Save
this search."
- Expect a confirmation that names the features and the snapshot sentence above.
- "list my saved searches" shows it with `features solar`.
- Then run, on the Mac (M), the job without drafting:
  `.venv/bin/python -m idx_agent.alerts.run --dry-run`. It reports what the normal job
  would report for the same state, and writes nothing. Right after the live save, while
  the active data is level with the store's snapshot day, expect exit code 0 and
  `"failed": 0, "unavailable": 0`. `deferred` may be 1 or more if a changed listing is
  held. If the active data has already moved past the snapshot day, expect exit 5 with
  `"unavailable_reasons": ["snapshot_behind"]`, the same as the normal job. That search
  is then left out of `checked`. Exit 4 with `"failed": 1` means a search failed, for
  example at the 500 alerted-key cap. The dry-run output always has `"drafts": 0` and
  `"pending": []`. Observed on synthetic alert stores, combined branch (dry-run, then
  the job on the same state):
  - active level with the snapshot, deferral held: dry-run exit 0 `{"checked": 1,
    "deferred": 1, "drafts": 0, "failed": 0, "pending": [], "skipped": 0,
    "unavailable": 0, "unavailable_reasons": []}`; job exit 0, the same counts with
    `"drafts": 1` (a repeated run: both `"drafts": 0`);
  - active 2026-09-20, snapshot 2026-09-18, checked date held at 2026-09-14: dry-run
    and job both exit 5, `{"checked": 0, "deferred": 0, …, "unavailable": 1,
    "unavailable_reasons": ["snapshot_behind"]}`;
  - a search at the 500 alerted-key cap: both exit 4, `"checked": 1, "failed": 1`.
- Then delete it ("delete that saved search", confirm with the code), so no live row is
  left behind; the residue count prints `0`.
- No alert is sent; approval before any delivery is unchanged.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "Listing features can't be checked right now, so I can't save this search with them. Should I save it without them?" | Store unconfigured, missing, malformed, stale, too broad or failing at save time; nothing was stored | Procedure 1's checks |
| "Saved searches can't include listing features yet…" | The switch is off for `idx_alerts` | C4 checks; restart |
| Job or `--dry-run` exit code 5, `unavailable_reasons` such as `stale`, `missing`, `not_enabled`, `snapshot_behind` | That feature search was not checked: no draft, no "no new matches", its checked date and alerted keys unchanged; other searches ran. `--dry-run` shows the same code and reasons | Fix the cause. `snapshot_behind` persists until the store is rebuilt (an operator task), also while a deferral waits |
| Job or `--dry-run` exit code 4 with `"failed": 1` | A search failed, for example `alert_key_cap` at 500 alerted keys | Replace the search (delete and save it again) |
| `--dry-run` exit 0 but the job exits 2 ("Alert job refused: check the private store and owner email settings.") | Owner recipient or approval-journal settings are missing; the dry-run never reads them | Fix the email settings (`docs/EMAIL.md`) |
| `deferred` above 0 on every run for a long time | A changed listing keeps the checked date held until a rebuild covers it | Rebuild the store when convenient; nothing is lost meanwhile |
| A draft for a feature search lists a home without the feature | Defect | Roll back. Report it |

When the store becomes stale or missing after a feature search was saved, the combined
tests show: feature search answers stale/unavailable with no cards; saves with features
are refused; the job reports that search `unavailable` and leaves it untouched, and
never runs it without its features; plain saved searches still run and draft.

**Rollback**
1. Remove the `IDX_FEATURE_SAVED_SEARCHES` line, restart, send `/new`.
2. Expected result: saves with features are refused as before; existing feature searches
   stay stored, list with "alerts paused: listing features are off", and every job run
   reports them `unavailable` (`not_enabled`) with no draft; they keep their window, so
   re-enabling resumes without losing matches. Verified by
   `tests/test_phase_integration_saved_searches.py`, also with the store setting removed.
3. Code rollback (revert #150) is closed too: the pre-WO-025 alert query refuses a saved
   search with features (counted as failed, never broadened).

Residue: the stored feature searches are owner data. Removing them is the owner's choice
(the user's own "delete" or "stop alerts" in chat, or a `delete` grant for the agent).
Count them, read-only, without printing any row:

```sh
.venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("file:data/state/alerts.sqlite?mode=ro", uri=True)
q = "SELECT COUNT(*) FROM searches WHERE json_extract(filters, '$.features') IS NOT NULL"
print(c.execute(q).fetchone()[0])
PY
# -> 0 after the live check's delete; N = the feature searches still stored
```

(Use the `IDX_ALERTS_DB_PATH` value instead if it is set.)

---

## 8. Procedure 5: bounded analysis (Phase 2, #146)

**State:** merged off (tool #138; switch, skill and instructions #146 `cbad756`); not
installed (worker image not built); not enabled; not live-verified.

**Prerequisites**
- Phase 1 accepted (G3).
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

  This one-off run exports `IDX_ANALYSIS_IMAGE` for pytest only; never export it in the
  gateway's or the installing shell's environment (C4).
- Owner decision 1 (made): the "can't help" line is unchanged, and the enabled
  instructions name `bounded_analysis` (section 10).

**Enable (M)**

```sh
# .env, one line each:
# IDX_ANALYSIS_IMAGE=sha256:<id>
# IDX_ANALYSIS_TOOL=1
./scripts/install.sh
openclaw config validate
openclaw gateway restart
openclaw mcp doctor idx --probe   # 8 tools, including idx__bounded_analysis
openclaw skills list              # 9, including bounded-analysis
```

Observed `install.sh` output (temp HOME, combined branch): `rendered
…/openclaw.analysis.json5 (bounded-analysis joins the idx skill list)` and, at the end,
`Bounded analysis is on (IDX_ANALYSIS_TOOL=1). After the restart above:` with
`# expects 8 tools, including idx__bounded_analysis` and `# expects 9, including
bounded-analysis`. If it prints "IDX_ANALYSIS_IMAGE in .env is unset or not pinned by
digest", fix the pin before the restart. If it stops with "install.sh: Bounded analysis
is misconfigured: …", the environment contradicts `.env` on the switch or on the image:
unset the exported variable and run it again. Do not restart the gateway with an image
conflict left in its environment: the server would register the tool and run the
exported digest.

**Offline acceptance**

```sh
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
'bounded_analysis' in s.server.instructions)"
# -> True True True      with IDX_ANALYSIS_TOOL=1 in .env and nothing exported
# -> True True True      also with a differing IDX_ANALYSIS_IMAGE exported; the image
#                         problem is only a warning (health, server_start; see C4)
# -> False False False   with the line absent, or with a contradicting
#                         IDX_ANALYSIS_TOOL export (C4)
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_analysis_integration.py \
  tests/test_mcp_bounded_analysis.py tests/test_analysis_service.py \
  tests/test_skill_files.py tests/test_routing_contract.py tests/test_openclaw_merge_config.py \
  tests/test_analysis_switch_agreement.py
# combined branch, Mac, no Docker or DB: 212 passed, 2 skipped (db)
```

`tests/test_phase_integration.py` adds the cross-feature routing check: with badges and
explanations also on, the routed `bounded_analysis` call returns the verified figure and
the checked PNG inline, and the routing prompt gains only the `bounded-analysis` skill.

**Smallest live check (L).** Send `/new`, then "Is bigger always pricier in Glendale?"
- Expect "Bounded analysis of N sales in Glendale…", a correlation marked verified (or
  mismatched, with the trusted value), and caveats that this is a bounded sample.
- Expect no chart unless one was asked for.
- Then send "What will prices do next year in Pasadena?". Expect the unchanged one-line
  "I can't help with that…" reply and no tool call.

The full script is `RELEASE_WO017_ANALYSIS.md` §6, steps 2–7. Step 1, the chart, belongs
to 5b.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "Analysis is not available on this server right now (ref …)." | No pinned image, a tag instead of a digest, Docker not running, or the image missing from the engine | `docker image inspect` the pin. Start Docker. Never run code on the host |
| `health` says "Bounded analysis is misconfigured: IDX_ANALYSIS_TOOL is 1 …"; 7 tools (skills as the last successful install left them) | The switch differs between the gateway environment and `.env`; the server does not register the tool and keeps the base instructions | Remove the exported variable. Keep the switch in `.env`. Reinstall and restart |
| `health` says "Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE in the process environment differs from .env…"; still 8 tools | The worker digest differs; the tool **stays registered** with the analysis instructions and runs the exported digest, not the one `install.sh` checked | Remove the exported `IDX_ANALYSIS_IMAGE`. Keep the pin in `.env`. Reinstall and restart. Until then, treat its answers as unverified against the pinned image |
| "The analysis worker is busy; try again shortly." | Two analyses already running (`MAX_CONCURRENT = 2`) | Retry once. Do not raise limits in this step |
| Timeout or safety-refusal message | Worker limits doing their job | Record it. Do not raise limits in this step |
| Forecast or valuation wording, or a number not marked verified or trusted | Defect | Roll back. Report it |

**Rollback**

```sh
# remove the IDX_ANALYSIS_TOOL line from .env (do not append =0: the first line wins)
./scripts/install.sh          # observed: "removed …/openclaw.analysis.json5 (bounded analysis is off; the 8-skill list is merged)"
openclaw gateway restart
openclaw mcp doctor idx --probe   # 7 tools
openclaw skills list              # 8 skills
```

Send `/new`.

Residue (verified in a temp HOME on the combined branch, every switch on then off):
- `ls ~/.openclaw/openclaw.analysis.json5` must fail. The merged `openclaw.json` equals a
  default install, and the state directory holds the same files as a default install
  plus `install.sh`'s own `openclaw.json.pre-idx.bak`.
- `IDX_ANALYSIS_IMAGE` may stay; nothing reads it while the switch is off.
- The Docker image stays.
- `openclaw.json.pre-idx.bak` was overwritten by the rollback install; use the C1 copy
  if needed.

Code rollback: revert #148 first if merged, then #146 `cbad756` (and #138 only if the
tool itself must go), then C3.

## 9. Procedure 5b: chart delivery (WO-030, #148)

**State:** not merged (#148 open, head `6a27dca`, base `main`, CI green: runs
41753073725 push, 41753079210 pull_request); not installed;
not enabled; **WhatsApp delivery UNVERIFIED**. Nothing in this procedure has been run
against OpenClaw or WhatsApp.

Owner decision 2 (made): charts must actually reach the user on WhatsApp. The text-only
fallback is kept, but it does not complete this requirement.

**Delivery mechanism (`docs/CHART_DELIVERY.md` §3).** With delivery on, the server writes
the checked PNG once, under a random 128-bit name, to
`~/.openclaw/workspace-idx/idx-charts/` (directory mode 700, file mode 600, at most
512 KiB, at most 20 charts), and `bounded_analysis` returns text only, ending with one
standalone `MEDIA:<absolute path>` line; the model receives no image. OpenClaw parses
that line from the agent's final reply, reads the file under the `idx` agent's existing
`read` permission and workspace root, and sends it only to the chat the request came
from.

**The 20-chart cap holds across `idx` server processes (#148 `6a27dca`).** Each OpenClaw
chat session can run its own `idx` server, all writing into one directory. Every chart
write runs its sweep, count, write and rename under an exclusive `flock` on
`.idx-charts.lock` in that directory. The lock file is created on the first chart
write, is mode 600, size 0, is never written to, and no prune removes it. A writer
waits at most `LOCK_WAIT_SECONDS` (2 s) for the lock. After that the chart is refused
with `dir_busy` and the text answer stays whole. That wait is per writer: parallel
chart calls inside one server process queue first, so with a stuck holder the k-th of
them can wait up to k × 2 s, and each is still refused with its figures intact. A
lock left by a killed process is released by the kernel. The lock is advisory and
assumes a local file system, which the default directory under `~/.openclaw` is.
Observed on the combined branch (temp directory): with another process holding the
lock, a write was refused with `dir_busy` after 2.02 s, and only the lock file was
left in the directory.

**Expiry: what is proven, and what is not (`docs/CHART_DELIVERY.md` §5a).** The target
is 300 s (`TTL_SECONDS`). This is **not a strict expiry guarantee**:
- *Server alive, idle:* a daemon thread removes each chart at written + 300 s with no
  further request; waits are at most 15 s against wall-clock deadlines, so after the Mac
  wakes a due chart goes within 15 s. Proven by the idle-over-MCP reproduction and the
  real-thread tests in #148.
- *Clean end* (stdin closed, SIGTERM, SIGINT): the process removes every chart it wrote,
  at once. Proven with child processes (and the real server's clean exit codes).
- *SIGKILL, crash or power loss:* nothing runs. The charts stay readable until the next
  sweep (any `idx` server start once they are expired, any chart write, any live
  server's own deadline, or `prune`). **That residual is unbounded if no server starts
  again and nobody prunes.** OpenClaw's own shutdown ends with SIGKILL when the graceful
  steps take too long.
- *Wall clock stepped back:* the chart lives longer by that amount (deliberate; the
  monotonic clock stops during sleep).
- A bound that holds after SIGKILL needs the launchd prune job proposed in
  `docs/CHART_DELIVERY.md` §5b (`config/chart-prune.launchd.plist.proposal`, every 60 s,
  at most 360 s while awake). It is **not installed** and is an owner decision (D6).

**Prerequisites**
- Procedure 5 accepted. #148 merged with CI green (G4).
- **No tool-policy or config change.** There is no `config/openclaw.charts.json5`;
  `install.sh` renders and merges nothing for charts and only reports the state. The
  design depends on the current OpenClaw 2026.9.5 settings recorded read-only in WO-030:
  `idx` `tools.allow` includes `read`; `tools.fs.workspaceOnly = true`; block streaming
  and sandboxing unset (off). Re-check these after any OpenClaw upgrade (the final-reply
  `MEDIA:` syntax is "legacy, supported").
- Owner approval of the MEDIA-line path, its residual windows and the clean-exit
  trade-off (D5), and a decision on the launchd proposal (D6).
- `IDX_CHART_DELIVERY` and `IDX_CHART_DIR` are not exported anywhere (C4; a contradiction
  is refused and reported).

**Enable (M)**

```sh
# .env, one line (IDX_ANALYSIS_TOOL=1 and IDX_ANALYSIS_IMAGE already set):
# IDX_CHART_DELIVERY=1
./scripts/install.sh
openclaw gateway restart
openclaw mcp doctor idx --probe   # still 8 tools
openclaw skills list              # still 9
```

Observed `install.sh` output (temp HOME, combined branch), after the analysis lines:

```
Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to <HOME>/.openclaw/workspace-idx/idx-charts
and attached to the reply by OpenClaw; no OpenClaw config was changed for it.
WhatsApp delivery is unverified until the acceptance check in docs/CHART_DELIVERY.md passes.
To turn it off: remove IDX_CHART_DELIVERY from .env, restart the gateway, then
  <python> -m idx_agent.analysis.delivery prune --all
```

With analysis off it prints `IDX_CHART_DELIVERY=1 has no effect while IDX_ANALYSIS_TOOL
is not 1.`, and for a bad directory `IDX_CHART_DIR must be an absolute path ending in
/idx-charts with no spaces; …`. `openclaw.json` gains no key for charts.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_chart_delivery.py \
  tests/test_phase_integration_charts.py
# combined branch, Mac: 129 passed (113 + 16)
.venv/bin/python -c "from idx_agent.mcp_server import server as s; s.register_analysis_tool(); \
print(s.configure_chart_delivery(), s.chart_delivery_problem())"
# -> True None     (analysis and delivery on in .env, nothing exported)
# -> False None    (either switch off)
# -> False <problem>   (a contradicting export; the same text health shows)
```

**Smallest live check (L; one paid turn; `docs/CHART_DELIVERY.md` §7).**
1. Send: "Chart price against size in Pasadena."
2. Pass: within about a minute one WhatsApp image (the scatter chart) arrives in the same
   chat, whose caption or following text has the verified figures, the line
   "Chart: … follows as an image in this chat. If no image appears in this chat, the
   figures above are the whole result." and the caveats. No line starting `MEDIA:` is
   visible. Record the delay and the OpenClaw version.
3. On the Mac: `ls -l ~/.openclaw/workspace-idx/idx-charts` shows one
   `chart-<32 hex>.png`, mode `-rw-------`. `ls -la` also shows `.idx-charts.lock`
   (mode `-rw-------`, size 0), which stays. With no further request, it is gone within
   300 s + 15 s of the reply while the server lives (or at once after `prune --all`).
4. Send: "Send that chart again." Expect no second image of the same file once it has
   expired.

No image means the requirement is **not met**, even though the text is whole.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| A visible `MEDIA:/...` line, no image | The model formatted the line; text is whole; delivery path not proven | Record it. Requirement not met. Roll back 5b only; 5 stays on |
| `⚠️ chart-….png: File not found` | Expired, pruned, or written elsewhere | Check `IDX_CHART_DIR`; roll back 5b if it repeats |
| `⚠️ chart-….png: Rejected…` or `Delivery failed` | OpenClaw refused the path | Check the workspace setting and that `read` is still allowed. Roll back 5b |
| `⚠️ Media failed.` | WhatsApp refused the send; text was delivered | Record it. Roll back 5b |
| "Chart: could not be prepared for this chat this time; the figures above are the whole result." | Server-side failure; the `chart_delivery` log line has the reason code: for example `dir_invalid`, `dir_full` (20 charts already), `dir_busy` (another session held the admission lock longer than 2 s), `lock_unsafe` (`.idx-charts.lock` is a symlink, directory or FIFO, or a file this user can open but does not own) or `lock_unavailable` (the lock file cannot be opened, for example another user's file this user cannot read) | Fix the cause. For `lock_unsafe`, inspect `ls -la ~/.openclaw/workspace-idx/idx-charts`. A one-off `dir_busy` needs no action. Roll back 5b if unclear or repeated |
| `health` names a chart-delivery misconfiguration | Environment contradicts `.env` | Unset the export; reinstall; restart |
| A chart file older than 315 s while the server is alive | Expiry defect | Roll back 5b. Report it |
| The reply says "attached" or "sent" but no image arrived | Wording defect | Roll back 5b |

**Rollback**

```sh
# remove the IDX_CHART_DELIVERY line from .env (do not append =0)
./scripts/install.sh            # observed: no "Chart delivery" line
openclaw gateway restart
.venv/bin/python -m idx_agent.analysis.delivery prune --all
# -> "removed N chart file(s)"
```

Expected result: procedure 5 behavior; `bounded_analysis` returns WO-027's reply (charts
as an inline image plus the text line), and no expiry thread, exit hook or SIGTERM
handler is armed (`tests/test_phase_integration_charts.py`). Residue: no config keys;
the `idx-charts` directory may remain, either empty or holding only the empty lock
file. `ls ~/.openclaw/workspace-idx/idx-charts` lists nothing. After any chart write,
`ls -A` lists `.idx-charts.lock` (mode `-rw-------`, size 0); `prune --all` keeps it
(observed in a temp directory: the `--all` prune removed the one chart and left only
`.idx-charts.lock`). Removing the
directory is optional and the owner's decision. If
the launchd job was installed (D6), uninstall it as in `docs/CHART_DELIVERY.md` §5b.

---

## 10. Departures from the earlier handoffs

- `RELEASE_WO017_ANALYSIS.md` §3, step 3 on the old main said to name `bounded_analysis`
  in the "can't help" line. That is not done, by owner decision 1. The line is copied
  verbatim in `config/IDX_RUNTIME.md` and the market-stats skill, and cannot vary with
  the switch without changing the default. The enabled instructions name the tool in
  their tool list instead (#146), and the routing contract tests pin both states.
- `RELEASE_WO017_ANALYSIS.md` §3, steps 1–3 (hand edits to the skill list, routing table
  and pins) are replaced by #146's one switch plus `install.sh`.
- The old chart acceptance passed with text only. Under owner decision 2, image delivery
  (5b) is required.
- `RELEASE_WO021_SEARCH.md` §5 says to remove or empty the line. This file adds: edit,
  never append, because the first `.env` line wins.
- The 2026-11-02 version of this file said a chart switch contradiction goes unreported
  and that charts are "kept at most 300 s". Both are superseded by #148 `ad5e46c`: the
  contradiction is refused and reported, and expiry is stated exactly as proven (§9).
- `docs/ALERTS.md` and WO-025 call saved feature searches "Phase 2" in places; in this
  file they are Phase 1 procedure 4 (they extend the enrichment features, not the
  analyst). The switch and its rollback are the same either way.

## 11. Combined acceptance before presenting for merge

**Branch.** `chore-phase-integration-2` at `30ff289`, pushed for reference (no PR; not
for merge). It is `main` `cbad756` plus, merged in this order with merge commits:
`wo-025-saved-feature-searches` `7831158` (#150), `wo-026-omission-pilot` `9da8062`
(#144), `wo-028-measurement-v2` `ee1c20f` (#145), `wo-030-chart-delivery` `ad5e46c`
(#148), `wo-029-activation-handoff` `e500d18` and `d086502` (#147). Then, for the review
follow-ups, merged on top: `wo-025-saved-feature-searches` `c40eadb` (#150, dry-run
parity), `wo-030-chart-delivery` `6a27dca` (#148, the cap across processes), and
`wo-029-activation-handoff` `2998f43` (#147, the conflict test). The results below are
for `30ff289`. This docs commit is merged after it and changes no code. The earlier
scratch branch `chore-phase-integration` (`d6f4759`) is superseded and left as it was.

**Conflict map.** None. Every merge was clean, including #150 with #148 (both add to
`IDX_SETTINGS`, `tests/test_db_pool.py` and `.env.example`; git merged them), and the
three follow-up merges.

**Merge order for the remaining PRs.** #150 → #144 → #145 → #147 (these four in any
order; none conflicts with another) → Phase 1 install and acceptance (G2–G3) → #148 → Phase
2. Rerun `main` CI after each merge. #148 merging before #150, or the reverse, is also
clean.

**Lint (Mac).** `ruff check .`: all checks passed. `ruff format --check .`: 437
files already formatted.

**Full offline suite, Mac** (`MYSQL_HOST=`; Docker and Ollama absent, so `container` and
`db` tests skip):
- `30ff289`, `IDX_ANALYSIS_IMAGE` unset: **4,931 passed, 130 skipped** (4,910 before
  the follow-ups, plus 10 from #150, 9 from #148 and 2 from #147's conflict test, which
  went from 2 to 4 cases);
- the same, `IDX_ANALYSIS_IMAGE=sha256:b…` exported (as CI does): **4,931 passed, 130 skipped**;
- offline `ci` eval suite (`PYTHONPATH=src:. python -m evals.run --suite ci`, no database;
  without `PYTHONPATH` a worktree imports the main checkout's `src` through the editable
  install): 251 cases, 84 pass, 0 fail, 167 skipped (no database);
- every `tests/test_phase_integration*.py` together: **39 passed (17 in #147's file, 6 in #150's, 16 in #148's)**.
No xfail, no expected-failure marker and no skip other than the POSIX guard for
`install.sh` (it runs on the Mac and CI).

**CI** (kept separate from the Mac; GitHub Actions, "commit gates" and "lint and tests"):

| Head | Run ids | Result |
|---|---|---|
| `main` `cbad756` | 41601867893 (push) | success |
| #150 `c40eadb` | 41751749477 (push), 41751755840 (pull_request) | success: 4,603 passed, 74 skipped; fixture DB 73 passed, 1 skipped |
| #144 `9da8062` | 41606402211 (push), 41606407318 (pull_request) | success: 4,567 passed, 74 skipped; 73 passed, 1 skipped |
| #145 `ee1c20f` | 41607142180 (push), 41607149994 (pull_request) | success; `ci` evals 251 cases, 251 pass |
| #148 `6a27dca` | 41753073725 (push), 41753079210 (pull_request) | success: 4,751 passed, 74 skipped; 73 passed, 1 skipped |
| #147 `2998f43` (last code commit; the CI of this docs commit is in the PR) | 41756755164 (push), 41756760635 (pull_request) | success: 4,535 passed, 74 skipped; 73 passed, 1 skipped |
| `chore-phase-integration-2` `30ff289` | 41757498036 (push) | success: 4,987 passed, 74 skipped; fixture DB 73 passed, 1 skipped; `ci` evals 251 cases, 251 pass, 0 fail |

CI's database job runs the `db` tests and the `ci` eval suite against the fixture
database; the Mac runs cannot, so their counts differ.

**Cross-feature checks**, each in a reviewable PR (synthetic store, the real listing SQL
on SQLite, the WO-011 recommend harness, synthetic alert stores, temp HOME installs;
switches written to a temp `.env`):

| Check | Where |
|---|---|
| Default off: `idx` tool list and the hashes of the tool listing and the instructions equal those pinned from `main` `cbad756`; no store opened; routing prompt without the analysis skill | `tests/test_phase_integration.py` (#147); `tests/test_phase_integration_charts.py` (#148, also: a fresh process arms no thread, handler or hook) |
| A configured store with every switch off changes only the feature-search reply | #147 |
| Each switch alone moves only its own surface: badges → search; explanations → recommend; analysis → tools, instructions, routing; saved → feature save and list; charts alone → nothing; charts with analysis → only the delivery state | #147; #150 (saved); #148 (charts) |
| All on: one store feeds search, badges, explanations and the saved alert; analysis registered beside them | #147; #150; #148 |
| Analyst routing: the routed `bounded_analysis` call with badges and explanations on returns the verified figure (inline PNG without delivery; a `MEDIA:` chart that expires while idle with delivery) | #147; #148 |
| Saved alerts: a changed listing is left out everywhere, counted `deferred`, then alerted once after a rebuild | #150 |
| Stale and missing store: feature search unavailable, plain search unbadged, no explanations, feature save refused, job reports `unavailable` and leaves the search untouched, plain search still drafts | #147; #150 |
| Rollback, every switch on then off one at a time, returns every surface to the off state; with the store removed too, main's hashes return | #147; #148; #150 (a feature search saved while on stays inert) |
| Install rollback in a temp HOME leaves no `openclaw.analysis.json5`, an `openclaw.json` equal to a default install, and the same state files plus `openclaw.json.pre-idx.bak` | #147; #148 |
| env vs `.env`: `IDX_ANALYSIS_TOOL` (install refuses; server registers nothing, base instructions, reports); `IDX_ANALYSIS_IMAGE` with the switch on (install refuses; server **still registers** the tool and analysis instructions, and only warns in `health` and `server_start`); `IDX_CHART_DELIVERY` and `IDX_CHART_DIR` (both refuse or report); badges and explanations never change the install | #147 (`test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`); #148; `tests/test_analysis_switch_agreement.py` (main) |

`IDX_FEATURE_SAVED_SEARCHES` never changing the install was checked on the combined
branch with a scratch probe (3 cases passed); `install.sh` does not mention the name. It
is not pinned by a test in a PR.

**Not covered offline:** Docker isolation of the worker, the `db` integration tests (CI
runs them), the real store and database (the M probes above), the gateway's process
handling of the server (SIGKILL residual), OpenClaw's handling of the `MEDIA:` line and
WhatsApp delivery (L, unverified).

## Smallest operator checklist

1. Review and merge #150, #144, #145 and #147 (CI green on `main` after each).
2. C1 backup; C2 serving checkout to `main` (decision D1).
3. Merge #151 (policy v5) and WO-032; run WO-032's tokened supplement extraction and
   its store rebuild under v5 (versioned migration) from the serving checkout; re-record
   the store info line and the Pasadena `solar` probe on the rebuilt store (procedure 1).
   Stop if the builder refuses.
4. C3 install; record the revision. Expect 7 tools, 4 alert tools, 8 skills.
5. Phase 1, one switch per restart, each with its live check and an EVIDENCE_LOG entry:
   `IDX_ENRICHMENT_STORE` → `IDX_FEATURE_BADGES=1` → `IDX_FEATURE_EXPLANATIONS=1` →
   `IDX_FEATURE_SAVED_SEARCHES=1` (save, list, `--dry-run`, delete).
6. After Phase 1 is accepted: decide D5/D6, merge #148; C1–C3 at the new revision.
7. Phase 2: build and pin the worker, `IDX_ANALYSIS_TOOL=1` + `install.sh` + restart +
   live check; then `IDX_CHART_DELIVERY=1` + `install.sh` + restart + the one-turn chart
   check (paid grant). Roll back only the step that failed.

## Owner decisions still open

- **D1** Serving checkout: switch the main checkout from `wo-021-recommend-design` to
  `main` in place (C2).
- **D2** Badge presentation (count, order, area facets).
- **D4** Saved feature searches: keep the conservative defaults; deferral scope (every
  changed listing in the window holds the date, not only snapshot matches); a held date
  level with the active data exits 0 under `deferred` rather than 5; lapsed searches are
  renewed in place with no catch-up for the lapsed period (and a deferral held before the
  lapse is dropped); an unshown overflow match may be counted again in a later draft.
- **D5** Chart delivery: approve the MEDIA-line path and accept the residual windows (a
  re-send within 300 s while the server lives; until the next sweep after a SIGKILL) and
  the clean-exit trade-off (a reply dispatched after the process exited loses its image).
- **D6** Strict chart expiry: approve or decline the launchd prune job (`docs/CHART_DELIVERY.md`
  §5b). Until then the guarantee is §9 above.
- Each merge, install, activation and paid live check.

## Appendix A. Offline failure rehearsal (agent, 2026-11-02)

All runs were on the Mac, in temp directories under the session scratchpad, with
`env -i` (no inherited `IDX_*` or `MYSQL_*`). Nothing touched `~/.openclaw`, the real
`.env`, the live alerts DB, Docker or the gateway. No model was called. These ran against
the snapshots named (before the 2026-11-03 merges); the behavior they record is
unchanged on `main` `cbad756` except where noted.

1. **Switch values** (`badges_enabled()` and `analysis.tool.enabled()`).
   - In `.env`: `1`, ` 1`, `1 ` and `"1"` are on. `true`, `TRUE`, `yes`, `on` and `0`
     are off. `1 # on` is off.
   - In the process environment: ` 1` turns badges on but analysis off.
2. **Conflicts** (before #146's rule; now refused and reported for analysis and charts).
   - `.env=1` with environment `0` is off.
   - `.env=0` with environment `1` is on.
   - `.env=1` with an environment variable set but empty is off.
   - Two `.env` lines, `=1` then `=0`, stay **on** (the first wins).
3. **Store paths.** These are `open_store` reasons; `FeatureAccess.readiness()` gives the
   same codes.
   - Unset: `not_configured`.
   - Missing file, directory, or a typo in a relative path: `missing`.
   - Junk file or empty SQLite file: `malformed`.
4. **Fail-closed behavior and staleness**, existing tests: the feature-search files
   (A5 unusable stores, A6 stale, A8 recovery, A10 save refusal), `tests/test_card_badges.py`
   (off for `None`, `""`, `0`, `true`, `yes`, ` 2 `; silent on stale or unusable
   stores) and the analysis files all passed.
5. **Tool surface.** Switch unset or `true`: 7 tools; `1`: 8 tools, and the instructions
   name the tool only then.
6. **Unavailable worker.** No Docker engine, an image missing from the engine, and no
   pinned image (unset or a tag) each answer unavailable and run nothing.
7. **`install.sh` switch and rollback**, in a throwaway repo copy with `HOME` and
   `OPENCLAW_STATE_DIR` in a temp directory, stub `openclaw` and `node`, and a seeded
   JSON config: off and `true` give 8 skills; `1` gives 9; `=1` then `=0` gives 9 (first
   wins; rollback by appending fails); edited to `0`, 8. The existing WhatsApp channel
   key survived every merge. On a state directory with no prior config, the first run
   copies the JSON5 render as `openclaw.json` and a second run's merge then fails to
   parse it (re-observed 2026-11-03). The owner's config came from `openclaw onboard`, so
   this only matters for a from-scratch rehearsal; seed a JSON config first.

## Appendix B. Finalization record

| Item | Settled in |
|---|---|
| D1: bring the serving checkout to `main` | C2 (exact steps under the D1 default; D1 stays an owner decision) |
| Default tool, alert-tool and skill counts | C3 (7, 4, 8; 8 and 9 with analysis, with or without charts) |
| Per-procedure offline counts at the final heads | 4–9 (combined branch, 2026-11-03) |
| Saved-search deferral and lapse fixes | 7 |
| Chart switch agreement and expiry as proven | C4, 9 |
| Switch conflict (tool not registered) versus image conflict (tool registered, warning) | C4, 8, 11 |
| Combined, cross-feature, default-off and rollback results; Mac vs CI | 11 |

Follow-up refresh of 2026-11-03 (review of #150, #147 C4 and #148): C4, procedure 5 and
the failure tables now separate an `IDX_ANALYSIS_TOOL` conflict (tool not registered)
from an `IDX_ANALYSIS_IMAGE` conflict (tool registered, warning only), backed by
`test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`. Procedure 4 now
gives the dry-run parity outputs (#150 `c40eadb`), and procedure 5b the cap across
processes and the lock file (#148 `6a27dca`). Heads, CI runs and combined counts were
re-measured at `30ff289`. Removed as stale: the CI rows for #150 `7831158`, #148
`ad5e46c`, #147 `e500d18` and the combined `fb68ea5`.

Refresh of 2026-11-03: rewritten against `main` `cbad756` and the final heads of #150,
#144, #145 and #148. Removed: the CI-red claims for #146 and #148 (both fixed; #146
merged), the flaky-test note (#148's concurrent-sweep fix `34bf3d0`;
`test_two_sessions_never_see_each_others_chart` passed 20 of 20 repeated Mac runs at the
combined head), and the strict expected-failure markers for
the chart switch (#148 made `install.sh` and the server agree; the checks are real
assertions in `tests/test_phase_integration_charts.py`).
