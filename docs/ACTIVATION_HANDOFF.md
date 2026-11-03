# Activation handoff: Phase 1 enrichment features and Phase 2 bounded analysis

**FINAL (WO-029), 2026-11-02.** Written against `main` at `5432dc2` and finalized against
the combined branch `chore-phase-integration` (`d6f4759`), which merges, in release order,
#142, #143, #149 (WO-024), #150 (WO-025), #144, #145, #146 and #148 (WO-030). Every
expected output below was observed on that branch, offline, on the owner's Mac, unless it
is marked as an operator (M) or live (L) expectation. Section 11 has the combined results
and the merge and rebase order.

Nothing in this file has been run on the serving host. The agent did not install, enable,
restart or live-test anything. It sent no message, made no paid call and did not read
`.env` or `~/.openclaw`. All commands below are for the operator (the owner), run from the
serving checkout's root with `.venv` active. Lines that start with `!` are typed by the
human at the Claude Code prompt; in a plain terminal, drop the `!`. The agent never runs
`consent.sh`.

The per-feature handoffs stay the detailed sources:
- `docs/RELEASE_WO021_SEARCH.md` (feature search);
- `docs/RELEASE_WO017_ANALYSIS.md` (bounded analysis; rewritten by #146);
- `docs/CHART_DELIVERY.md` (chart delivery; added by #148);
- `docs/ALERTS.md` (saved searches; WO-025 section added by #150).

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

**Switches.** Each lives in `.env`, is listed in `IDX_SETTINGS`
(`src/idx_agent/db/pool.py`), and is on only for the value `1`:

| Switch | Capability | Read by | Notes |
|---|---|---|---|
| `IDX_FEATURE_BADGES` | 2 badges | `idx` tool server | Strips spaces: ` 1 ` is on (unchanged from main; decision list) |
| `IDX_FEATURE_EXPLANATIONS` | 3 explanations (WO-024) | `idx` tool server | Exactly `1`; ` 1 `, `1\n`, `01` are off |
| `IDX_FEATURE_SAVED_SEARCHES` | 4 saved feature searches (WO-025) | `idx_alerts` server and the alert job | Exactly `1` |
| `IDX_ANALYSIS_TOOL` | 5 bounded analysis (#146) | `install.sh` and the `idx` tool server, one rule (`analysis.tool.switch_state`) | Exactly `1`; `.env` decides; a contradicting process environment makes `install.sh` refuse and the server stay off and report it |
| `IDX_CHART_DELIVERY` | 5b charts (WO-030) | `idx` tool server; `install.sh` only reports it | Exactly `1`, and only with `IDX_ANALYSIS_TOOL=1` |

Settings that are not switches: `IDX_ENRICHMENT_STORE` (a path; empty means feature
search is off, and 2-4 need it too), `IDX_ANALYSIS_IMAGE` (the pinned worker digest) and
`IDX_CHART_DIR` (optional; an absolute path ending in `/idx-charts`; default
`~/.openclaw/workspace-idx/idx-charts`).

## 1. Current state (2026-11-02, never overstated)

| # | Capability | Merged | Installed | Enabled | Live-verified |
|---|---|---|---|---|---|
| 1 | Feature search | Yes: #134 `7f10734`, #135 `c8b897c`. Shared access in **#142, open** (`8475ab3`, CI green) | **No** at a main revision (see C2) | No: per STATUS.md, `IDX_ENRICHMENT_STORE` is not set. The agent did not read `.env` | No |
| 2 | Card badges | Yes, off: #136 `411a649`. Refactor in **#142, open** | No | No | No |
| 3 | Recommendation explanations | No: **#149, open** (`5f14980`, CI green), stacked on #142 | No | No | No |
| 4 | Saved feature searches | No: **#150, open** (`5272d0e`, CI green), stacked on #142 | No | No | No |
| 5 | Bounded analysis | Tool merged off: #138 `b318846`. Switch, skill and instructions in **#146, open** (`6df43c1`, **CI red**: see section 11) | No: worker image not built on the Mac (Docker is not running) | No | No |
| 5b | Chart delivery | No: **#148, open** (`e0a5e0d`, **CI red**: see section 11), stacked on #146 | No | No | No; WhatsApp delivery **unverified** |

Private store (metadata only, read 2026-11-02 by the agent in the main checkout):
- `data/enrichment/full/effective-facets-v1.sqlite3` exists, with mode `0600`;
- `StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  rules_version='2026-11-01.4', listing_count=54888)`.

That is the built store. It is not "configured": configured means set in the serving
`.env`, which the agent does not read.

## 2. Release order and gates

```
G0  merge #142 (shared FeatureAccess)                     owner merge approval
G0' merge #143 (docs only; any time, early is best)       owner merge approval
G1  retarget #149 to main, merge; retarget #150, merge     owner merge approval each
    (#144 and #145 may merge here too; independent)
G2  Phase 1 install, once, at one recorded revision        C1-C3; all switches still off
P1  enable and accept, one at a time, each with its own restart and live check:
      1 search -> 2 badges -> 3 explanations -> 4 saved feature searches
    stop at the first failure; roll back only that step
G3  Phase 1 accepted (all four recorded in EVIDENCE_LOG.md)
G4  rebase + merge #146 (WO-027), then rebase #148 onto main and merge
G5  Phase 2 install at a new recorded revision; Phase 1 switches unchanged
P2  5 bounded analysis -> 5b chart delivery, each with its own restart and live check
```

Rules:
- One switch changes per restart, and each restart is followed by its live check.
  Then a failure belongs to the last switch that changed.
- #146 and #148 are off by default and change no default surface (section 11), so
  merging them before G3 would not invalidate Phase 1. Keeping them after G3 is still the
  recommendation: the Phase 1 install revision then contains no Phase 2 code at all.
- Phase 1 acceptance is valid only while the C3 probes show the default surface:
  7 `idx` tools, 4 `idx_alerts` tools and 8 skills.
- Phase 2 starts only after G3. A Phase 2 failure must never be fixed by changing a
  Phase 1 switch, and the reverse holds too.
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
On 2026-11-02 it is clean but on branch `wo-021-recommend-design` (`74c98d1`). That is
`7f10734` plus two unmerged experiment commits, and it is 24 commits behind
`origin/main`. It lacks #135–#141. Any gateway restart would load that code.

The release revision for Phase 1 is the `main` merge commit recorded at G2 (after G0,
G0' and G1). The steps, under the default for decision D1 (switch in place; the branch is
committed and pushed, so nothing is lost):

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

- Confirmed on the combined branch: WO-024, WO-025 and WO-030 add no tool, no alert tool
  and no skill. With every switch unset, the `idx` tool list, every tool schema and
  description, the server instructions, the `idx_alerts` tool list and the default
  `install.sh` output (`openclaw.json`, the render, stdout) are byte-identical to `main`
  `5432dc2` (section 11). With `IDX_ANALYSIS_TOOL=1`: 8 tools and 9 skills, with or
  without `IDX_CHART_DELIVERY=1`.
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
- **Keep every switch in `.env` only.** For the tool servers the process environment
  beats `.env` (an exported value, even an empty one, wins). What each switch does when
  the two disagree, verified on the combined branch:
  - `IDX_ANALYSIS_TOOL`: `install.sh` refuses before writing anything, and the server
    registers nothing, keeps the base instructions and reports the problem in `health`
    and in its `server_start` log line (`analysis_switch_problem`).
  - `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS`, `IDX_FEATURE_SAVED_SEARCHES`:
    `install.sh` never reads them (its output is identical whatever their values), so
    only the running server's view matters, and the environment wins silently.
  - `IDX_CHART_DELIVERY`, `IDX_CHART_DIR`: **not detected.** `install.sh` reports the
    `.env` value; the server uses the environment's. `IDX_CHART_DELIVERY=` (empty) or
    `0` exported with `.env=1` means install says "on" and charts stay off; exported `1`
    with no `.env` line means install says nothing and charts are on. Open finding on
    #148 (section 11); pinned as a strict expected failure in
    `tests/test_phase_integration.py`.
- After each restart the probes are the truth: the tool count and skill count must agree
  (7/8, or 8/9 with analysis on), and `health` must carry no misconfiguration warning.

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
2. Rerun `install.sh` when a skill list depends on the switch (procedure 5); it is
   harmless for the others.
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

**State:** merged (#134, #135); shared access in #142 (open); not installed at a main
revision; not enabled; not live-verified.

**Prerequisites**
- #142 merged (G0). Search reads through `FeatureAccess.bind()` with no behavior change.
- C2 and C3 done at the release revision.
- Store built and valid. Run on the serving host:

  ```sh
  .venv/bin/python -c "from pathlib import Path; from idx_agent.enrichment.effective_store \
  import open_store; s = open_store(Path('data/enrichment/full/effective-facets-v1.sqlite3')\
  .resolve()); print(getattr(s, 'info', s))"
  # -> StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  #    rules_version='2026-11-01.4', listing_count=54888)
  ```

  Any `StoreUnavailable(reason=...)` stops this procedure. After #142 a store with a
  repeated `(listing, facet)` row is also refused (`malformed`). Rebuilding the store is
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
# combined branch d6f4759, Mac, 2026-11-02: 168 passed   (main 5432dc2 without the access file: 117)
.venv/bin/python -c "from idx_agent.db import pool; from idx_agent.enrichment.access import \
FeatureAccess; c = pool.connect(); a = FeatureAccess.configured(); r = a.readiness(c); \
print(r.status, r.reason, r.active, r.changed); a.close(); c.close()"
# -> usable None <active count> <changed count>   (M; prints counts only)
.venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena', 'features': ['solar']}); \
print(r.data.feature_filter.status, r.data.total_matches)"
# -> applied 14   (M; 2026-09-18 snapshot; a newer database differs)
```

On the combined branch, `tests/test_phase_integration.py` also shows that configuring the
store with every switch off changes only the feature-search reply; plain search,
recommend, saved searches, tools and instructions stay byte-identical.

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

Code rollback: revert #142 only after reverting its consumers (#150, #149), newest first,
then #135 and #134 if search itself must go, then C3.

## 5. Procedure 2: card badges

**State:** merged off (#136); refactored by #142 (open); not installed; not enabled; not
live-verified.

**Prerequisites**
- Procedure 1 accepted. Badges read the same store under the same rules.
- #142 merged.
- WO-024 does not change badge presentation (#149 only adds two badge tests: empty
  results, and the explanations switch never turning badges on). The behavior is the
  merged default: up to 3 per card, requested features first then A–Z, area facets shown,
  prefix `From description:`. Owner decision D2 may still change it; until then this is
  what the live check expects.

**Enable (M):** add `IDX_FEATURE_BADGES=1` to `.env`, then `openclaw gateway restart`.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_card_badges.py
# combined branch d6f4759, Mac: 43 passed   (main 5432dc2: 41)
IDX_FEATURE_BADGES=1 .venv/bin/python -c "from idx_agent.mcp_server import server as m; \
r = m.search_result({'city': 'Pasadena'}); b = r.data.card_badges; \
print(len(r.data.listings), len(b.badges) if b else 0, \
max((len(v) for v in b.badges.values()), default=0) if b else 0)"
# -> <cards> <badged cards, at most cards> <at most 3>   (M)
```

The same probe without the switch prints `<cards> 0 0`, with identical listings. Run
against the synthetic combined-branch world, it printed `5 3 3` on and `5 0 0` off.

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
badges off (verified on the combined branch: rollback returns every surface to the
switch-off state).

Residue: none (no files, no stored state). Check that
`grep -c '^IDX_FEATURE_BADGES=' .env` prints `0`.

## 6. Procedure 3: recommendation explanations (WO-024, #149)

**State:** not merged (#149 open, stacked on #142); not installed; not enabled; not
live-verified.

**Prerequisites**
- Procedures 1 and 2 accepted. Explanations need only `IDX_ENRICHMENT_STORE`; they do
  not need badges. #149 was tested with badges both on and off: its tests pin that
  neither switch turns the other on, and the combined tests run explanations alone and
  with every switch on. Leave badges as procedure 2 left them.
- #142 and #149 merged.
- Owner decision D3: #149 implements "explanation line only": ranking, scores,
  candidates, price checks and feature weights (zero) are unchanged and pinned by tests.
  Facets that count: home features present on both the subject and the card, area facets
  excluded (`EXPLANATION_FACETS = ELIGIBLE_FACETS - AREA_FACETS`); `condominium` is
  included (decision list).

**Enable (M):** add `IDX_FEATURE_EXPLANATIONS=1` to `.env`, then
`openclaw gateway restart`. The name is in `IDX_SETTINGS` and `.env.example`; it is read
with `db_pool.env_setting` and is on only for exactly `1`.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_recommend_explanations.py \
  tests/test_recommend_features.py tests/test_mcp_recommend.py
# combined branch d6f4759, Mac: 103 passed   (tests/test_recommend_explanations.py alone: 33)
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
never a key. On the synthetic combined-branch world it printed `2 True 0 0` for a
subject sharing nothing; `tests/test_phase_integration.py` covers a subject that shares
features.

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
result: recommendation replies are byte-for-byte as before; the combined tests show the
payload has no `shared_features` key and the log line no `shared_*` field. Residue: none
(no files, no stored state, no schema). Check that
`grep -c '^IDX_FEATURE_EXPLANATIONS=' .env` prints `0`.

## 7. Procedure 4: saved feature searches (WO-025, #150)

**State:** not merged (#150 open, stacked on #142); not installed; not enabled; not
live-verified. With the switch off, `save_search` still answers "Saved searches can't
include listing features yet. Should I save it without them?".

**Prerequisites**
- Procedures 1–3 accepted. #142 and #150 merged.
- Owner decision D4: #150's conservative defaults are in force (decision list): a
  separate switch; a save whose features cannot be checked is refused and nothing is
  stored; a feature search is checked only up to the snapshot day, so listings first
  listed after the snapshot wait for a store rebuild; unknown, never-extracted and
  changed listings never match.
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
skill is loaded in place, so the restart picks it up; `install.sh` output is identical
whatever this switch says. The alert job reads the same `.env`; if you run it from cron
or a LaunchAgent, do not export the switch there (C4).

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_saved_feature_searches.py tests/test_alerts.py
# combined branch d6f4759, Mac: 79 passed   (tests/test_saved_feature_searches.py alone: 53)
```

Observed on the combined branch with synthetic alert stores (never the live DB):
- a save with features, while on, answered `Saved search 1: Filters: city Glendale,
  features pool. Checked as of 2026-09-18. Alerts include only homes whose descriptions
  state every feature as of the 2026-09-18 listing-feature snapshot; a home not matched
  may still have them. …`;
- the list showed `1. Filters: city Glendale, features pool; checked 2026-09-18`, and,
  after the switch was turned off, `…; alerts paused: listing features are off`;
- a dry-run of the job over one plain and one feature search saved today printed
  `"checked": 2 … "skipped": 1, "unavailable": 0` (a search saved on the snapshot day
  has no new window yet);
- the read-only residue count below printed `1` for one feature search among two.

**Smallest live check (L).** `/new`, "Homes in Pasadena with solar panels.", then "Save
this search."
- Expect a confirmation that names the features and the snapshot sentence above.
- "list my saved searches" shows it with `features solar`.
- Then run, on the Mac (M), the job without drafting:
  `.venv/bin/python -m idx_agent.alerts.run --dry-run` and expect exit code 0 and a JSON
  line with `"failed": 0, "unavailable": 0`. Exit code 5 means a feature search was
  unavailable (its reason is in `unavailable_reasons`).
- Then delete it ("delete that saved search", confirm with the code), so no live row is
  left behind; the residue count prints `0`.
- No alert is sent; approval before any delivery is unchanged.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "Listing features can't be checked right now, so I can't save this search with them. Should I save it without them?" | Store unconfigured, missing, malformed, stale, too broad or failing at save time; nothing was stored | Procedure 1's checks |
| "Saved searches can't include listing features yet…" | The switch is off for `idx_alerts` | C4 checks; restart |
| Job exit code 5, `unavailable_reasons` such as `stale`, `missing`, `not_enabled`, `snapshot_behind` | That feature search was not checked: no draft, no "no new matches", its checked date and alerted keys unchanged; other searches ran | Fix the cause. `snapshot_behind` persists until the store is rebuilt (an operator task) |
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
   re-enabling resumes without losing matches. Verified on the combined branch, also
   with the store setting removed.
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

**State:** tool merged off (#138); switch, skill and instructions in #146 (open, CI red
on a test-isolation defect, section 11); not installed (worker image not built); not
enabled; not live-verified.

**Prerequisites**
- Phase 1 accepted (G3). #146 merged (G4) with CI green.
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
- Neither `IDX_ANALYSIS_TOOL` nor `IDX_ANALYSIS_IMAGE` is exported in the gateway's or
  the installing shell's environment (C4).

**Enable (M)**

```sh
# .env, one line each:
# IDX_ANALYSIS_IMAGE=sha256:<id>
# IDX_ANALYSIS_TOOL=1
./scripts/install.sh       # prints "rendered …/openclaw.analysis.json5 (bounded-analysis joins the idx skill list)"
                           # and "Bounded analysis is on (IDX_ANALYSIS_TOOL=1). After the restart above:"
openclaw config validate
openclaw gateway restart
openclaw mcp doctor idx --probe   # 8 tools, including idx__bounded_analysis
openclaw skills list              # 9, including bounded-analysis
```

If `install.sh` prints "IDX_ANALYSIS_IMAGE in .env is unset or not pinned by digest", fix
the pin before the restart. If it stops with "install.sh: Bounded analysis is
misconfigured: …", the environment contradicts `.env`: unset the exported variable and
run it again.

**Offline acceptance**

```sh
IDX_ANALYSIS_TOOL=1 .venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
'bounded_analysis' in s.server.instructions)"
# -> False False False   when .env does not also say 1 (the rule: .env decides)
# -> True True True      when .env has IDX_ANALYSIS_TOOL=1 and the variable is not exported
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_analysis_integration.py \
  tests/test_mcp_bounded_analysis.py tests/test_analysis_service.py \
  tests/test_skill_files.py tests/test_routing_contract.py tests/test_openclaw_merge_config.py \
  tests/test_analysis_switch_agreement.py
# combined branch d6f4759, Mac, no Docker or DB: 186 passed, 2 skipped (db)
```

Run the first probe without the `IDX_ANALYSIS_TOOL=1` prefix once `.env` carries the
switch: `True True True`.

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
| `health` says "Bounded analysis is misconfigured: …"; 7 tools with 9 skills | The switch differs between the gateway environment and `.env`; the server stays off by rule | Remove the exported variable. Keep the switch in `.env`. Reinstall and restart |
| "The analysis worker is busy; try again shortly." | Two analyses already running (`MAX_CONCURRENT = 2`) | Retry once. Do not raise limits in this step |
| Timeout or safety-refusal message | Worker limits doing their job | Record it. Do not raise limits in this step |
| Forecast or valuation wording, or a number not marked verified or trusted | Defect | Roll back. Report it |

**Rollback**

```sh
# remove the IDX_ANALYSIS_TOOL line from .env (do not append =0: the first line wins)
./scripts/install.sh          # prints "removed …/openclaw.analysis.json5 (bounded analysis is off; the 8-skill list is merged)"
openclaw gateway restart
openclaw mcp doctor idx --probe   # 7 tools
openclaw skills list              # 8 skills
```

Send `/new`.

Residue:
- After #146 (`6df43c1`), the rollback install removes `openclaw.analysis.json5`;
  `ls ~/.openclaw/openclaw.analysis.json5` must fail. The merged `openclaw.json` equals a
  default install (verified in a temp HOME on the combined branch, with every switch on
  then off).
- `IDX_ANALYSIS_IMAGE` may stay; nothing reads it while the switch is off.
- The Docker image stays.
- `openclaw.json.pre-idx.bak` was overwritten by the rollback install; use the C1 copy
  if needed.

Code rollback: revert #148 first if merged, then #146 (and #138 only if the tool itself
must go), then C3.

## 9. Procedure 5b: chart delivery (WO-030, #148)

**State:** not merged (#148 open, stacked on #146, CI red on a flaky test, section 11);
not installed; not enabled; **WhatsApp delivery unverified**. Nothing in this procedure
has been run against OpenClaw or WhatsApp.

Owner decision 2 (made): charts must actually reach the user on WhatsApp. The text-only
fallback is kept, but it does not complete this requirement.

**Delivery mechanism (from `docs/CHART_DELIVERY.md`).** With delivery on, the server
writes the checked PNG once, under a random 128-bit name, to
`~/.openclaw/workspace-idx/idx-charts/` (directory mode 700, file mode 600, at most
512 KiB, kept at most 300 s and 20 files), and `bounded_analysis` returns text only,
ending with one standalone `MEDIA:<absolute path>` line; the model receives no image.
OpenClaw parses that line from the agent's final reply, reads the file under the `idx`
agent's existing `read` permission and workspace root, and sends it only to the chat the
request came from.

**Prerequisites**
- Procedure 5 accepted. #148 rebased onto `main` after #146 and merged with CI green.
- **No tool-policy or config change.** There is no `config/openclaw.charts.json5`;
  `install.sh` renders and merges nothing for charts and only reports the state. The
  design depends on the current OpenClaw 2026.9.5 settings recorded read-only in WO-030:
  `idx` `tools.allow` includes `read`; `tools.fs.workspaceOnly = true`; block streaming
  and sandboxing unset (off). Re-check these after any OpenClaw upgrade (the final-reply
  `MEDIA:` syntax is "legacy, supported").
- Owner approval of the MEDIA-line path and of its residual risks (decision list).
- `IDX_CHART_DELIVERY` and `IDX_CHART_DIR` are not exported anywhere (C4: this conflict
  is not detected yet).

**Enable (M)**

```sh
# .env, one line (IDX_ANALYSIS_TOOL=1 and IDX_ANALYSIS_IMAGE already set):
# IDX_CHART_DELIVERY=1
./scripts/install.sh
# -> "Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to
#     /Users/<you>/.openclaw/workspace-idx/idx-charts"
#    "and attached to the reply by OpenClaw; no OpenClaw config was changed for it."
#    "WhatsApp delivery is unverified until the acceptance check in docs/CHART_DELIVERY.md passes."
#    openclaw.json unchanged compared with the procedure 5 install (no new keys)
openclaw gateway restart
openclaw mcp doctor idx --probe   # still 8 tools
openclaw skills list              # still 9
```

`install.sh` prints "IDX_CHART_DELIVERY=1 has no effect while IDX_ANALYSIS_TOOL is not 1."
when analysis is off, and "IDX_CHART_DIR must be an absolute path ending in /idx-charts
with no spaces; …" for a bad directory.

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_chart_delivery.py
# combined branch d6f4759, Mac: 67 passed (one test is flaky, see section 11)
.venv/bin/python -c "from idx_agent.analysis import delivery as d; from idx_agent.db import pool; \
print(d.enabled(pool.env_setting), d.chart_dir(pool.env_setting))"
# -> True /Users/<you>/.openclaw/workspace-idx/idx-charts   (analysis and delivery on)
# -> False …                                                 (either switch off)
```

The test file covers the writer (modes, `O_EXCL|O_NOFOLLOW`, symlinked directory
refused), PNG re-validation and the size cap, retention and pruning, one file and one
`MEDIA:` line per request, default-off parity with WO-027, and `install.sh` in temp homes.
On the combined branch the tool list, schemas and instructions with charts on equal
those with analysis alone.

**Smallest live check (L; one paid turn; `docs/CHART_DELIVERY.md` §7).**
1. Send: "Chart price against size in Pasadena."
2. Pass: within about a minute one WhatsApp image (the scatter chart) arrives in the same
   chat, whose caption or following text has the verified figures, the line
   "Chart: … follows as an image in this chat. If no image appears in this chat, the
   figures above are the whole result." and the caveats. No line starting `MEDIA:` is
   visible. Record the delay and the OpenClaw version.
3. On the Mac: `ls -l ~/.openclaw/workspace-idx/idx-charts` shows one
   `chart-<32 hex>.png`, mode `-rw-------`, and is empty again after five minutes and one
   more request (or after the prune command).
4. Send: "Send that chart again." Expect no second image of the same file.

No image means the requirement is **not met**, even though the text is whole.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| A visible `MEDIA:/...` line, no image | The model formatted the line; text is whole; delivery path not proven | Record it. Requirement not met. Roll back 5b only; 5 stays on |
| `⚠️ chart-….png: File not found` | Pruned or written elsewhere | Check `IDX_CHART_DIR`; roll back 5b if it repeats |
| `⚠️ chart-….png: Rejected…` or `Delivery failed` | OpenClaw refused the path | Check the workspace setting and that `read` is still allowed. Roll back 5b |
| `⚠️ Media failed.` | WhatsApp refused the send; text was delivered | Record it. Roll back 5b |
| "Chart: could not be prepared for this chat this time; the figures above are the whole result." | Server-side failure; the `chart_delivery` log line has the reason code | Fix the cause (for example `dir_invalid`). Roll back 5b if unclear |
| The reply says "attached" or "sent" but no image arrived | Wording defect | Roll back 5b |

**Rollback**

```sh
# remove the IDX_CHART_DELIVERY line from .env (do not append =0)
./scripts/install.sh            # no "Chart delivery" line
openclaw gateway restart
.venv/bin/python -m idx_agent.analysis.delivery prune --all
# -> "removed N chart file(s)"
```

Expected result: procedure 5 behavior; `bounded_analysis` returns WO-027's reply byte
for byte (charts as the text line). Residue: no config keys; the `idx-charts` directory
may remain empty (`ls ~/.openclaw/workspace-idx/idx-charts` lists nothing). Removing the
empty directory is optional and the owner's decision.

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
- The draft of this file (`5773504`) said an analysis rollback leaves
  `openclaw.analysis.json5` behind and that an exported `IDX_ANALYSIS_TOOL=1` registers
  the tool without the skill. Both were true of #146 at `6e877f3`; at `6df43c1` the
  render is removed and the contradiction is refused and reported.
- `docs/ALERTS.md` and WO-025 call saved feature searches "Phase 2" in places; in this
  file they are Phase 1 procedure 4 (they extend the enrichment features, not the
  analyst). The switch and its rollback are the same either way.

## 11. Combined acceptance before presenting for merge

**Branch.** `chore-phase-integration` at `d6f4759`, pushed for reference (no PR; not for
merge). It is `main` `5432dc2` plus, merged in this order: `wo-023-enrichment-access`
`8475ab3` (#142), `wo-022-readiness-reconcile` `674fb45` (#143),
`wo-024-feature-explanations` `5f14980` (#149), `wo-025-saved-feature-searches` `5272d0e`
(#150), `wo-026-omission-pilot` `5c29e45` (#144), `wo-028-measurement-v2` `76e3565`
(#145), `wo-027-analysis-integration` `6df43c1` (#146), `wo-030-chart-delivery`
`e0a5e0d` (#148), then two commits adding `tests/test_phase_integration.py`.

**Conflict map.** Six merges were clean, including #149 with #150 (both add to
`IDX_SETTINGS`, `tests/test_db_pool.py`, `.env.example` and `docs/CONTRACTS.md`). Two
needed hand resolution, both additive:

| Merge | File | Resolution | Who rebases |
|---|---|---|---|
| #146 after #149 | `src/idx_agent/channels/format.py` `__all__` | keep #146's `CHART_IMAGE_FALLBACK`, `CHART_NOT_ATTACHED_LINE` and #149's `SHARED_NOTE`, `SHARED_PREFIX` | #146, once #149 is on `main` (trivial) |
| #148 after #146 `6df43c1` and #149 | `src/idx_agent/db/pool.py`, `tests/test_db_pool.py` | keep `IDX_FEATURE_EXPLANATIONS` and add `IDX_CHART_DELIVERY`, `IDX_CHART_DIR` | #148 |
| same | `src/idx_agent/mcp_server/server.py` `main()` | call `_prune_charts_at_start()` and then #146's new `log_start()` (#148 was cut from #146 `6e877f3`, before `log_start` existed) | #148 must rebase onto #146's final head; not a one-line pick |

**Merge and rebase order.** #142 → #143 → retarget #149 to `main`, merge → retarget
#150, merge → #144 and #145 (either order; rerun `main` CI after whichever of #145 and
#146 lands second, since both edit `evals/run.py` and `docs/EVALUATION.md`) → Phase 1
install and acceptance → rebase #146 on `main` (the `format.py` line), fix its CI, merge
→ rebase #148 on `main` (the three files above), fix its CI and the two findings below,
merge → Phase 2.

**Lint.** `ruff check .`: all checks passed. `ruff format --check .`: 432 files already
formatted.

**Full offline suite, Mac** (`MYSQL_HOST=`, Docker and Ollama absent, so `container` and
`db` tests skip), three full runs:
- merges only (`6f8feb5`): 4,658 passed, 130 skipped;
- with the integration tests (`201f3e7`): 4,676 passed, 130 skipped, 3 xfailed, 1 failed
  (the flaky `tests/test_chart_delivery.py::test_two_sessions_never_see_each_others_chart`);
- final head `d6f4759`: **4,677 passed, 130 skipped, 3 xfailed**.

Repeated alone, the flaky test failed once in 3 to 8 runs. For comparison, `main`
`5432dc2`: 4,269 passed, 129 skipped.

**CI.** Kept separate from the Mac. PR heads: #142, #143, #144, #145, #149 and #150 green.
#146 `6df43c1` red: 2 failures in `tests/test_analysis_switch_agreement.py`
(`[env=None-dotenv='1']`, `[env='1'-dotenv='1']`) because CI exports
`IDX_ANALYSIS_IMAGE` and the test's runtime half reads it (reproduced on the Mac with
that variable exported; the test must unset it). #148 `e0a5e0d` red: the flaky test
above (`KeyError: 'delivery'`). The integration branch push runs inherit both.

**Cross-feature checks** (`tests/test_phase_integration.py`: 19 passed, 3 xfailed on the
Mac; synthetic store, the real listing SQL on SQLite, the WO-011 recommend harness, a
synthetic alert store, temp HOME installs; switches written to a temp `.env`):
- **(a) Default off.** With no switch and no store, the `idx` tool list and the digests
  of the tool listing, the instructions and the `idx_alerts` tool listing equal those
  pinned from `main` `5432dc2`. A cross-tree probe (outside pytest) compared 21 surfaces
  between `main` and the combined branch with trace ids and temp paths normalized: tool
  lists, schemas, descriptions, both servers' instructions, plain and paged search, a
  feature search with no store, `recommend` (k 5 and 2), saves with and without
  features, the list, and a default `install.sh` (config, render, stdout, files) were
  byte-identical. The alert job's draft subject and body were identical; its JSON summary
  gains `"unavailable": 0, "unavailable_reasons": []` (#150; additive).
- **(b) Each switch alone** changes only its own surface: badges → search replies;
  explanations → `recommend`; saved searches → the feature save and the list; analysis →
  tools and instructions; charts alone → nothing. Charts with analysis change only the
  delivery switch (same tools, schemas and instructions as analysis alone).
- **(c) All on.** One store feeds everything: a solar+pool search returns exactly the two
  listings with both present, badges list the requested features first, `recommend` for
  one of them explains the other with exactly `pool, solar` (a subset of its badges and
  of the store's present facets), and a saved solar search's alert draft lists exactly
  the listings a live solar search returns. With a stale and then a missing store:
  feature search answers stale/unavailable with no cards and no count; plain search still
  works without badges; `recommend` has no explanations; a feature save is refused; the
  alert job reports the feature search `unavailable` (`stale` / `missing`), leaves its
  checked date and alerted keys unchanged, drafts nothing for it (no "no new matches"),
  and still drafts the plain search. A mutation that ran unavailable feature searches
  without their features failed both cases.
- **(d) Rollback.** Every switch on, then turned off one at a time (charts, analysis,
  saved, explanations, badges), returns every surface to the all-off state. A feature
  search saved while on stays stored with its features, lists as paused, and every job
  run reports it `not_enabled` with no draft and no state change (also with the store
  setting removed). `install.sh` with every switch on and then off leaves no
  `openclaw.analysis.json5` and an `openclaw.json` equal to a default install.
- **(e) env versus `.env`.** `install.sh` output is identical whatever the three runtime
  switches say in `.env` or the environment. An analysis conflict stops `install.sh` and
  keeps the tool unregistered even with chart delivery requested. The chart switch
  disagreement (C4) is pinned as 3 strict expected failures.

**Findings for the owning PRs (not fixed here):**
1. #146: CI red on `6df43c1`; `_runtime` in `tests/test_analysis_switch_agreement.py`
   must unset `IDX_ANALYSIS_IMAGE` (or the conftest must), as the integration tests do.
2. #148: `test_two_sessions_never_see_each_others_chart` is flaky (Mac and CI). In the
   failing runs one of the two concurrent calls has `chart_status: "unavailable"`, so
   `data.chart.delivery` is missing; the shared fake worker is the likely cause. Fix
   before merge; a real concurrent-render race is not excluded until then.
3. #148: `IDX_CHART_DELIVERY`/`IDX_CHART_DIR` use env-wins at runtime but `install.sh`
   reports `.env` only; adopt #146's rule (`.env` decides, a contradiction is reported) or
   at least report the mismatch in `health`. Remove the xfail marker when fixed.
4. #148: must rebase onto #146's final head (`server.py` `main()`).
5. #150: the job summary gains two keys even with no feature search (documented in
   `docs/ALERTS.md`); harmless unless something parses the summary strictly.

**Not covered offline:** Docker isolation of the worker, the `db` integration tests (CI
runs them), the real store and database (the M probes above), OpenClaw's handling of the
`MEDIA:` line and WhatsApp delivery (L, unverified).

## Smallest operator checklist

1. Approve and merge #142, then #143; retarget and merge #149, then #150; merge #144 and
   #145 (CI green each time).
2. C1 backup; C2 serving checkout to `main` (decision D1); C3 install; record the revision.
3. Phase 1, one switch per restart, each with its live check and an EVIDENCE_LOG entry:
   `IDX_ENRICHMENT_STORE` → `IDX_FEATURE_BADGES=1` → `IDX_FEATURE_EXPLANATIONS=1` →
   `IDX_FEATURE_SAVED_SEARCHES=1` (save, list, `--dry-run`, delete).
4. After Phase 1 is accepted: #146 rebased and green, merge; #148 rebased, fixed and
   green, merge; C1–C3 at the new revision.
5. Phase 2: build and pin the worker, `IDX_ANALYSIS_TOOL=1` + `install.sh` + restart +
   live check; then `IDX_CHART_DELIVERY=1` + `install.sh` + restart + the one-turn chart
   check (paid grant). Roll back only the step that failed.

## Appendix A. Offline failure rehearsal (agent, 2026-11-02)

All runs were on the Mac, in temp directories under the session scratchpad, with
`env -i` (no inherited `IDX_*` or `MYSQL_*`). Nothing touched `~/.openclaw`, the real
`.env`, the live alerts DB, Docker or the gateway. No model was called. Items 1–7 were
run for the draft against `main` and the PR snapshots named; item 8 against the combined
branch.

1. **Switch values** (main `5432dc2`, `badges_enabled()` and `analysis.tool.enabled()`).
   - In `.env`: `1`, ` 1`, `1 ` and `"1"` are on. `true`, `TRUE`, `yes`, `on` and `0`
     are off. `1 # on` is off.
   - In the process environment: ` 1` turns badges on but analysis off.
2. **Conflicts** (main; before #146's rule).
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
7. **`install.sh` switch and rollback** (#146 at `6e877f3`). This used #146's script in a
   throwaway repo copy, with `HOME` and `OPENCLAW_STATE_DIR` in a temp directory, stub
   `openclaw` and `node`, and a seeded JSON config.
   - off: 8 skills; `true`: 8 skills;
   - `1`, unpinned or with a tag: 9 skills, plus the "not pinned by digest" warning;
   - `1` with a synthetic digest: 9 skills, no warning;
   - line removed: 8 skills, but `openclaw.analysis.json5` remained (fixed in `6df43c1`);
   - `.env` off with `IDX_ANALYSIS_TOOL=1` exported to the installer: 8 skills (refused
     since `6df43c1`);
   - `=1` then `=0`: 9 skills (first wins; rollback by appending fails);
   - edited to `0`: 8 skills.
   - The existing WhatsApp channel key survived every merge.
   - On a state directory with no prior config, the first run copies the JSON5 render as
     `openclaw.json` and a second run's merge then fails to parse it. The owner's config
     came from `openclaw onboard`, so this only matters for a from-scratch rehearsal;
     seed a JSON config first.
8. **Combined branch** (`d6f4759`): the probes quoted in procedures 2, 3, 4 and 5b were
   run against the synthetic world of `tests/test_phase_integration.py` (outputs quoted
   there); the cross-tree default-off probe and the integration tests are in section 11.

## Appendix B. Finalization record

Every draft placeholder, and where it is now settled:

| Former placeholder | Settled in |
|---|---|
| D1: bring the serving checkout to `main` | C2 (exact steps under the D1 default; D1 stays an owner decision) |
| Default tool, alert-tool and skill counts after WO-024, WO-025 and WO-030 | C3 (unchanged: 7, 4, 8; 8 and 9 with analysis) |
| Feature-search test count at the release revision | 4 (168 passed) |
| Badge presentation and badge test count | 5 (unchanged by WO-024; 43 passed) |
| Explanations: switch, prerequisites, tests, probe, live wording, failure text, residue | 6 |
| Saved feature searches: switch, schema, tests, live check, stale behavior, rollback, residue count | 7 |
| Analysis test count at the release revision | 8 (186 passed, 2 skipped) |
| Charts: mechanism, policy change (none), switch, install step, tests, wording, failures, rollback | 9 |
| Combined, cross-feature, default-off and rollback results; Mac vs CI | 11 |
