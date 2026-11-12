# Activation handoff: Phase 1 enrichment features and Phase 2 bounded analysis

**FINAL (WO-029), refreshed 2026-11-03 (owner decisions, round three).** Written against
`main` at `48b74ab` (after #142, #143, #146, #149, #151, #156, #144, #154, #145 and #152
merged). It was checked on the combined branch `chore-phase-integration-4`: `main`
`48b74ab` plus the heads of the open PRs as they were at 2026-11-04 07:45Z, merged with
merge commits in the approved order (D7): #148 `a5016be`, #150 `757c212`, #153
`68cbf24` and this PR, then #155 `8a7fc34` last with its planned fixture switch
(section 11). Every expected output below was observed on that branch, offline, on the
owner's Mac, unless it is marked as an operator (M) or live (L) expectation, or names
another revision. Earlier outputs that this round did not change were observed on
`chore-phase-integration-2` (`30ff289`) or `chore-phase-integration-3` (`1525494`, older
heads; section 11). A PR head that moves after this refresh is not covered by it.

**Update of 2026-11-04 (the chart trial's immediate rollback).** `main` has since moved
to `c62ca83` (#159, `README.md` only), merged into this branch; no step changes.
Procedure 5b (section 9) now quotes #148 `ef3bb25`'s one-shot trial verbatim
(`docs/CHART_DELIVERY.md` §7): enable, one trial turn, roll back at once after
completion or failure without waiting for the owner, verify that analysis and chart
delivery are off, record it; keeping delivery on needs the owner's later approval. The
merge order now says #147 merges before #155 (section 11). Since the combined branch,
#148 moved to `ef3bb25` (docs, the rollback script and its tests, a `main` merge), #150
to `926dabf` (a `main` merge and WO-025 docs) and #155 to `1409184` (a `main` merge and
#154's fixture adapted); the combined branch was not rebuilt for them (section 11).

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
  value that differs from `.env` (set against unset or empty, or another digest) is
  refused by `install.sh` and, as for a switch conflict, the server registers no
  `bounded_analysis` (7 tools, base instructions) and reports the problem in `health`
  and `server_start` (C4; owner decision 2026-11-03, #156 merged at `27c4ef1`). With
  #148 in, chart delivery stays off too, with no chart problem line of its own.
- `IDX_CHART_DIR`: optional; an absolute path ending in `/idx-charts`; default
  `~/.openclaw/workspace-idx/idx-charts`. An environment value that differs from `.env`
  is refused and reported, as for the switches (#148).

## 1. Current state (2026-11-03, never overstated)

| # | Capability | Merged | Installed | Enabled | Live-verified |
|---|---|---|---|---|---|
| 1 | Feature search | Yes: #134 `7f10734`, #135 `c8b897c`; shared access #142 `426e198` | **No** (the serving checkout is not on `main`; C2) | No: per STATUS.md, `IDX_ENRICHMENT_STORE` is not set. The agent did not read `.env` | No |
| 2 | Card badges | Yes, off: #136 `411a649`, refactored by #142 `426e198` | No | No | No |
| 3 | Recommendation explanations | Yes, off: #149 `8987003` | No | No | No |
| 4 | Saved feature searches | **No: #150 open**, head `926dabf`, base `main`, CI green | No | No | No |
| 5 | Bounded analysis | Yes, off: tool #138 `b318846`; switch, skill and instructions #146 `cbad756` | No: worker image not built on the Mac (Docker is not running) | No | No |
| 5b | Chart delivery | **No: #148 open**, head `ef3bb25`, base `main`, CI green; it has merged `main` `27c4ef1` (#156) and `48b74ab` itself and carries the `tool.py` resolution, so it merges cleanly (section 11) | No | No | No; WhatsApp delivery **UNVERIFIED** |

Not capabilities, but in the same release, merged in the D7 order: #144 (WO-026
omission pilot, `5daa7b5`), #154 (WO-033 pilot v2, `d92b11f`), #145 (WO-028 measurement
v2, `5a20be8`) and #152 (WO-032, closed as not applicable under D-032 option a;
documentation and a read-only preflight, `48b74ab`). #143 (the acceptance matrix) is
merged as `48a04b3`. `main` is `c62ca83` (#159, `README.md` only, on top of `48b74ab`,
after #151, the v5 rulings, and #156, an image conflict fails closed); `main` CI on
`c62ca83`: run `41805565257`, success (`48b74ab`: run `41785486554`, success). Still
open: #153 (WO-034 Phase A, `68cbf24`, CI green) and #155 (WO-035, the v5 store
migration that procedure 1 needs, `1409184`; it has merged `main` `48b74ab` and adapted
#154's fixture, and both its push and `pull_request` runs are green; it still adapts
#147's, #148's and #150's test files once they are on `main`, section 11), besides
#148, #150 and this PR. #157 (WO-033 model review) and #158 (v5 rulings 9-15) are also
open; they are not part of the D7 order in this file.

Private store (metadata only, read 2026-11-02 by the agent in the main checkout):
- `data/enrichment/full/effective-facets-v1.sqlite3` exists, with mode `0600`;
- `StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  rules_version='2026-11-01.4', listing_count=54888)`.

That is the built store. It is not "configured": configured means set in the serving
`.env`, which the agent does not read.

## 2. Release order and gates

```
G0  done: #142, #143, #146, #149, #151, #156 merged (main 27c4ef1, CI green)
G1  merge order approved (D7, 2026-11-03; section 11):     owner merge approval each
      #144 -> #154; #145, #148 (it already carries the
      tool.py resolution), #150, #152, #153 in any
      order; #147 before #155; #155 last, adapting fixtures
      done so far: #144, #154, #145, #152 (main 48b74ab)
G1b C1-C2, then freeze the v5 manifest and build the v5     owner; free, no token;
    store (procedure 1); open_store shows v5, 54,888       a refusal stops
G2  Phase 1 install, once, at one recorded main revision    C1-C3, then the C3a off
    (C3a: bounded_analysis absent, IDX_ANALYSIS_TOOL off,   probe; any other output
    IDX_CHART_DELIVERY off)                                 stops before P1
P1  enable and accept, one at a time, each with its own restart and live check:
      1 search -> 2 badges -> 3 explanations -> 4 saved feature searches
    stop at the first failure; roll back only that step
G3  Phase 1 accepted (all four recorded in EVIDENCE_LOG.md)
G4  #148 already merged at G1 (D7: #148 before #155)
G5  Phase 2 install at a new recorded revision; Phase 1 switches unchanged
P2  5 bounded analysis -> 5b chart delivery, each with its own restart and live check;
    5b is one separately authorized WhatsApp trial (D5) with the launchd prune job
    (D6), rolled back at once after the trial turn completes or fails, without
    waiting for the owner; keeping it on needs the owner's later approval
```

Rules:
- One switch changes per restart, and each restart is followed by its live check.
  Then a failure belongs to the last switch that changed.
- The Phase 1 install revision already holds #146's analysis code, off. Default-off
  identity with the pre-#146 surfaces is proven (section 11), so this does not affect
  Phase 1. #148 is also off by default and arms nothing while off. Merging it before G3
  does not invalidate Phase 1. The owner approved D7 on 2026-11-03: #148 merges before
  #155, so only #155 adapts the test fixtures. Phase 2 development and review continue
  in parallel; only Phase 2 *activation* waits for G3.
- Phase 1 acceptance is valid only while the C3 probes show the default surface
  (7 `idx` tools, 4 `idx_alerts` tools and 8 skills) and the C3a off probe prints
  `False False False None None`. Rerun C3a after every Phase 1 restart.
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

### C2. Put the serving checkout on the release revision (M; D1 approved, the owner's step)

The serving checkout is the main checkout: the venv's editable install points at its
`src/`, and `data/` (indexes, store, alerts DB, email store) resolves from its root.
On 2026-11-03 (read-only check) it is clean, on branch `wo-021-recommend-design` at
`74c98d1`, which is pushed. It is 45 commits behind `origin/main` and 2 ahead (two
unmerged recommendation-design commits). Any gateway restart would load that code.

The release revision for Phase 1 is the `main` merge commit recorded at G2 (after G1).
The owner approved D1 on 2026-11-03: switch the main checkout in place (the branch is
committed and pushed, so nothing is lost). The owner runs these steps; the agent never
touches the main checkout:

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
  add no tool, alert tool or skill (section 11). Since then two pins moved, each in its
  own PR: the tool-listing digest in P1-4 (owner-accepted 2026-11-05, EVIDENCE_LOG), and,
  in WO-042 (#189), the instructions digests, default `46dfa9cc…` -> `ba79956b…` and
  analysis `0bec5f33…` -> `20b53b5b…` (via `594b8468…` / `c426fe8a…` on the same
  branch). Cause: an agent change from the #189 review, not an owner instruction: the
  "can't help" sentence leaves out what the response policy's fixed lines answer (a
  transaction, a request to reach a person or the agent, an identity question). The
  WO-042 move was owner-accepted 2026-11-11. With `IDX_ANALYSIS_TOOL=1`: 8 tools and
  9 skills, with or without `IDX_CHART_DELIVERY=1`.
- `demo_preflight.py` does not check `IDX_ENRICHMENT_STORE` or any switch. The
  per-procedure checks below cover them.

### C3a. Phase 1 off probe: analysis and charts are off (M; gate G2, D7)

Run after the C3 restart and before procedure 1, then again after every Phase 1 restart,
from the serving checkout's root in the shell that ran `install.sh`. It prints booleans
and problem lines only, never a `.env` value.

```sh
env | grep -cE '^IDX_(ANALYSIS_TOOL|ANALYSIS_IMAGE|CHART_DELIVERY|CHART_DIR)='
# -> 0      (nothing exported in this shell)
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
s.configure_chart_delivery(), s.analysis_switch_problem(), s.chart_delivery_problem())"
# -> False False False None None
#    field 1: IDX_ANALYSIS_TOOL off (switch_state, install.sh's rule)
#    field 2: bounded_analysis not registered
#    field 3: IDX_CHART_DELIVERY off (chart_state)
#    fields 4-5: no analysis or chart misconfiguration
openclaw mcp doctor idx --probe | grep -c bounded_analysis    # -> 0 (and 7 tools)
openclaw skills list | grep -c bounded-analysis               # -> 0 (and 8 skills)
ls ~/.openclaw/openclaw.analysis.json5                        # -> No such file or directory
```

Observed offline on the combined branch (`env -i`, temp `HOME`, a temp `.env` in the
working directory; the `env` line and the last three lines are operator expectations):
`False False False
None None` with no switch line, and also with only `IDX_ANALYSIS_IMAGE` pinned or only
`IDX_CHART_DELIVERY=1` (delivery needs the analysis switch). Any other output stops
Phase 1 before its first switch:
- `True True False None None`: `IDX_ANALYSIS_TOOL=1` is in `.env`. Edit it out (C4),
  rerun `install.sh`, restart, rerun C3a.
- `True True True None None`: both analysis and chart delivery are on in `.env`. The
  same.
- `False False False Bounded analysis is misconfigured: …`: an export contradicts
  `.env` (C4). Unset it, rerun `install.sh`, restart.
- `False False False None Chart delivery is misconfigured: …` (observed with
  `IDX_CHART_DELIVERY=1` exported and no `.env` line): the same, for
  `IDX_CHART_DELIVERY` or `IDX_CHART_DIR`.

The probe imports the server in a throwaway process; with both switches off it arms
nothing and writes nothing. It checks `.env` and this shell. The two `openclaw` lines
check the server the gateway actually starts.

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
    whether or not the switch is also exported; set against unset or empty, or two
    digests): `install.sh` refuses the same way (exit 1, nothing written). The server
    fails closed exactly as for a switch conflict (owner decision 2026-11-03, #156
    merged at `27c4ef1`). It does not register `bounded_analysis` (7 tools) and keeps
    the base instructions. It reports the problem as the one `health` warning
    (appended to its message) and as `analysis_switch_problem` in `server_start`. No
    exported digest is ever run. Observed on `main` `27c4ef1` and again on the combined
    branch: `install.sh: Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE in the
    process environment differs from .env, so install.sh would check one worker image
    and the tool would run the other; the tool is not registered. Keep it in .env only
    (unset it in the environment), run scripts/install.sh, and restart the gateway.`
    The `health` message ends with that sentence, and `server_start` lists 7 tools,
    without `bounded_analysis`. The same for an exported empty value against a pinned
    `.env`, and with the switch exported too.
  - With #148 in, an image conflict also leaves chart delivery (5b) off, even with
    `IDX_CHART_DELIVERY=1` in `.env`: delivery needs the analysis switch on, so
    `chart_state` is off with no chart problem line, and the analysis problem is the
    report. Observed on the combined branch: `install.sh` printed only the analysis
    line above (exit 1, no state directory, no "Chart delivery" line);
    `configure_chart_delivery()` `False`, `chart_delivery_problem()` `None`, and
    `health` carried the one analysis warning.
  - A differing `IDX_ANALYSIS_IMAGE` while the switch is off everywhere is not a
    problem: install succeeds, nothing is registered and nothing is reported.
  - Pinned by `tests/test_phase_integration.py::test_a_switch_or_image_conflict_unregisters_and_reports`
    (#147, four cases) and by `tests/test_analysis_switch_agreement.py` (main, #156).
    The observed lines above come from offline runs on `main` `27c4ef1` and on the
    combined head `969b739` (`main` `48b74ab` changes none of `analysis/`, the server,
    `install.sh` or `pool.py` after `27c4ef1`), with `install.sh` in a temp `HOME` and
    state directory (stub
    `openclaw` and `node`), and an in-process start (`register_analysis_tool()` then
    `log_start()`, as `main()` does).
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
  An image conflict now shows like a switch conflict: 7 tools with the switch on in
  `.env` (skills as the last successful install left them), plus the `health` warning
  naming `IDX_ANALYSIS_IMAGE`.

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
  v4 store. The v5 rebuild is WO-035, the versioned v5 store migration (PR #155, branch
  `wo-035-v5-store-migration`, head `1409184` on 2026-11-04). The builder on
  `main` today checks only v4 inputs against the v4 freeze manifest and cannot produce a
  v5 store; do not run it expecting one. #151 (the v5 rulings,
  `docs/ENRICHMENT_REVIEW_POLICY_V5.md`) is already merged (`32cd727`). WO-032 is closed
  as not applicable (owner decision D-032, option a): there is no supplement
  extraction, no paid call and no token step, and the 321 description-less listings stay
  unknown by design. Steps, all on the serving checkout at `main` (C2) from its root:
  1. WO-035 is merged into `main` and the serving checkout is at that revision.
  2. Write a proposed v5 manifest to a path you choose, review it (names and hashes
     only), then freeze it by copying it to
     `data/enrichment/effective-store-v5-manifest.json`, beside the unchanged v4 manifest
     `data/enrichment/policy-audit-freeze-manifest.json`:
     `.venv/bin/python scripts/propose_enrichment_v5_manifest.py --output <your path>`.
     Any edit to `docs/ENRICHMENT_REVIEW_POLICY_V5.md` must land before the freeze.
  3. Dry run, then build, with WO-035's exact commands:
     `.venv/bin/python scripts/build_enrichment_effective_store.py --policy v5 --dry-run`
     (expect 54,888 listings), then
     `.venv/bin/python scripts/build_enrichment_effective_store.py --policy v5`.
     It writes `data/enrichment/full/effective-facets-v5.sqlite3`. The v4 store
     `data/enrichment/full/effective-facets-v1.sqlite3` is not touched and is kept.
  4. Verify with `open_store` on the v5 file (the store check below, with the v5 path):
     `StoreInfo` must show `policy_version='v5'` and `listing_count=54888`. WO-035's
     count hardening refuses any store carrying the approved digest with another count
     (`source_count_mismatch`), and a v5 store whose recorded manifests do not match
     (`provenance_mismatch`).
  5. On the rebuilt store and before the install, re-record the store info line and the
     Pasadena `solar` probe (`applied 14` on the v4 store). The ruling-8 overlay touches
     no solar label, so 14 is expected, but it must be observed, not assumed. Record the
     v5 `listing_count` and status counts in WO-021 Status.

  Any builder refusal, or any `StoreUnavailable` from the v5 file, stops this procedure:
  it is a stop condition, not a status note. Never edit a pinned input or a manifest to
  get past it. Rollback of the rebuild: point `IDX_ENRICHMENT_STORE` back at the kept v4
  store file (`data/enrichment/full/effective-facets-v1.sqlite3`) and restart; nothing is
  deleted.
- C2 and C3 done at the release revision.
- Store built and valid. Run on the serving host, with the v5 file from step 3 above:

  ```sh
  .venv/bin/python -c "from pathlib import Path; from idx_agent.enrichment.effective_store \
  import open_store; s = open_store(Path('data/enrichment/full/effective-facets-v5.sqlite3')\
  .resolve()); print(getattr(s, 'info', s))"
  # -> expect policy_version='v5' and listing_count=54888 (M; not yet observed;
  #    record the full line here once it is)
  # the kept v4 file (effective-facets-v1.sqlite3), observed 2026-11-02:
  # -> StoreInfo(source_watermark='2026-09-18 06:58:44', policy_version='v4',
  #    rules_version='2026-11-01.4', listing_count=54888)
  ```

  Any `StoreUnavailable(reason=...)` stops this procedure. A store with a repeated
  `(listing, facet)` row is refused (`malformed`). The v5 rebuild is WO-035 (above);
  `RELEASE_WO021_SEARCH.md` §1 rebuilds only the v4 store. Both are free, but need the
  frozen artifacts and the approved digest.
- Freshness. The snapshot is stale when more than 10% of active listings changed since
  `2026-09-18 06:58:44`, or have no change time (`enrichment.access.STALE_SHARE = 0.10`).
  The local database is a frozen 2026-09-18 snapshot, so it is fresh today. The optional
  inventory, from the main checkout, writes a private file under `data/`:
  `python scripts/refresh_preflight.py` (add `--overwrite` if the inventory exists).
  The recorded result is 54,885 unchanged, 321 never extracted, 3 ambiguous. The 321
  listings had no description to extract from; under D-032 (option a) they stay
  unknown by design in both the v4 and the v5 store, and no supplement is planned.
- Env: `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS`, `IDX_FEATURE_SAVED_SEARCHES`,
  `IDX_ANALYSIS_TOOL` and `IDX_CHART_DELIVERY` are absent from `.env` or set to anything
  but `1`.

**Enable (M)**

```sh
# add exactly one line to .env (relative paths resolve from the repository root),
# naming the rebuilt v5 store:
# IDX_ENRICHMENT_STORE=data/enrichment/full/effective-facets-v5.sqlite3
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
# -> applied 14   (M; v4 store, 2026-09-18 snapshot; a newer database differs;
#    re-record on the v5 store, 14 expected)
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
procedure is that script, with P1-4 as reworded by the owner on 2026-11-05:

| # | Message | Expected |
|---|---|---|
| P1-4 | Only homes whose listing descriptions say they have both a pool and solar panels. | `search_listings` with `mode: "update"` and `features: ["pool", "solar"]` (all required); city Pasadena and 3+ beds carried; no structured `pool`; feature line "Features matched from listing descriptions as of 2026-09-18: pool, solar."; the limitation whole; the relay check below passes |

The earlier P1-4 wording, "Any of those with a pool too?", failed on 2026-11-05 (trace
`8e84ac5c94834523`, `EVIDENCE_LOG.md`): a card number changed during relay, and the
skill sent "a pool" to the structured filter where the script expected features. That
result stays recorded as failed. An ordinary "with a pool" still uses `pool: true`.

**Relay check after each card turn (model-free).** The skills and the runtime policy
require a card tool's `message` verbatim; nothing in OpenClaw 2026.9.5 enforces it, and
a later correction in the same reply does not excuse a changed value. After each turn
that shows cards, export that turn's transcript records (the tool result naming the
trace id and the assistant reply after it, one JSON object per line) into the private
evidence folder, then run from the serving checkout:

```sh
.venv/bin/python -I scripts/check_relay.py --transcript <private file> --trace-id <trace> --require-exact
# -> status=pass reason=exact  exit 0: the reply is the message, unchanged
# -> require_exact=fail ...    exit 1 (after a status=pass reason=whole line): the turn
#                              FAILS once Layer 2 is installed (owner decision 2026-11-05)
# -> status=fail ...      exit 1: the turn FAILS (first_mismatch names card and unit)
# -> status=unavailable   exit 2: records missing or the blocks disagree; not a pass
```

Before Layer 2 is installed, run it without `--require-exact` (Layer 1's rule).

The line it prints has counts, card positions and units only. `--values` adds the
numbers; send that output only to the private folder. The check reads the named file
and nothing else. It is detection, not prevention.

This is Layer 1 of the owner's layered relay fix (decision of 2026-11-05): detection
after every card turn, and a changed number fails the turn even if the reply corrects
itself. The checker already fails a self-corrected reply. On the preserved P1-4 records
(a living area changed, then corrected in the same reply) it prints `status=fail
reason=changed`, first mismatch card 2 sqft. A reply that has the message whole plus a
corrected figure in added text fails with `extra_numbers`. So does a wrong card followed
by the whole message restated. `tests/test_relay_check.py` pins all three. Layer 2
(one copy of the card to the model, card as the whole reply) and Layer 3 (a card relay
guarantee) are later, separate work.

Layer 2 (branch `chore-card-relay-layer2`, not merged or installed): the card tools send
the model one copy of each result (integral numbers as integers, and the SDK text
block written in JavaScript's own number spelling, so OpenClaw drops the block that
duplicated it, 1e-6 included), and each card tool's `message` is the whole correct
reply, with nothing before or after it. After it is installed, a correct card turn
prints `reason=exact`. Layer 1's rule is unchanged: `reason=whole` (the message plus
digit-free text) still passes this check; only the paid `relay` case for reply shape 4
fails it (evals/README.md, "Layer 2"). Owner decisions of 2026-11-05: once
Layer 2 is installed, procedure 1 requires `reason=exact` on every card turn, checked
with `scripts/check_relay.py --require-exact`, so `reason=whole` fails procedure 1. The
order is Layer 2 first: #170 and Layer 2 merge, a fresh routing run and the relay
measurement (evals/README.md, "Layer 2") follow, then procedure 1 restarts from P1-0.

**Failure handling**

| What you see | Meaning | Action |
|---|---|---|
| "I can't filter by listing features right now…" | Store unavailable: unset, wrong path, missing, malformed, incomplete or replaced | Run the store check above. Fix `IDX_ENRICHMENT_STORE` (edit the line, never append) and restart |
| "The listing-feature data is out of date with the listings…" | Stale: more than 10% of active listings changed since the snapshot | Do not force it. The store needs a refresh, which is out of scope and paid. Roll back |
| A feature line without the limitation, or "doesn't have" wording | Model relay defect | Record it with the trace reference. Roll back if it repeats after one resend |
| `scripts/check_relay.py` prints `status=fail` (a card number, card or line changed, even if corrected later in the reply) | Model relay defect | The turn fails. Keep the trace reference and the private records; stop the session |
| `scripts/check_relay.py --require-exact` prints `require_exact=fail` (exit 1) | Text added around an unchanged card (`reason=whole`); with Layer 2 installed the card is the whole reply | The turn fails, as above |
| Badge lines appear | A badges switch is on somewhere (`.env` first-wins, or the process environment) | Run C4 checks. Restart |
| Ordinary searches change | Must not happen (acceptance A11) | Stop. Roll back the code (C6) and report |

**Rollback**
1. Remove the `IDX_ENRICHMENT_STORE` line, or leave it empty. To fall back from the v5
   store to v4 instead of turning the feature off, edit the line (never append) to the
   kept v4 file, `data/enrichment/full/effective-facets-v1.sqlite3`; it still opens under
   WO-035's checks (v4, 54,888 listings).
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
  A–Z, area facets shown, prefix `From description:`. The owner decided D2 on
  2026-11-03: keep this look. The live check expects exactly it.

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
# combined branch, Mac: 105 passed
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

**State:** not merged (#150 open, head `926dabf`, base `main`, CI green: runs
41800389697 push, 41800399923 pull_request; since `757c212` it adds only a `main` merge
and WO-025 docs, so this procedure is unchanged); not installed;
not enabled; not live-verified. With the switch off (and on `main` today), `save_search`
answers "Saved searches can't include listing features yet. Should I save it without
them?".

**Prerequisites**
- Procedures 1–3 accepted. #150 merged.
- Owner decision D4 (decided 2026-11-03: keep the conservative defaults): a separate
  switch; a save whose features cannot be checked is refused and nothing is stored; a
  feature search is checked only up to the snapshot day, so listings first listed after
  the snapshot wait for a store rebuild; unknown, never-extracted and changed listings
  never match. The deferral scope, the exit 0 under `deferred`, the in-place renewal of
  a lapsed search and the possible recount of an unshown overflow match stay as #150
  implements them (Decided list).
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
conflict left in its environment: the server would not register the tool (7 tools), and
`health` would report the image problem.

**Offline acceptance**

```sh
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
'bounded_analysis' in s.server.instructions)"
# -> True True True      with IDX_ANALYSIS_TOOL=1 in .env and nothing exported
# -> False False False   with the line absent, or with a contradicting
#                         IDX_ANALYSIS_TOOL export, or a differing IDX_ANALYSIS_IMAGE
#                         export (C4; #156)
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_analysis_integration.py \
  tests/test_mcp_bounded_analysis.py tests/test_analysis_service.py \
  tests/test_skill_files.py tests/test_routing_contract.py tests/test_openclaw_merge_config.py \
  tests/test_analysis_switch_agreement.py
# combined branch, Mac, no Docker or DB: 218 passed, 2 skipped (db)
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
| `health` says "Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE in the process environment differs from .env…"; 7 tools (skills as the last successful install left them) | The worker digest differs between the gateway environment and `.env`; as for a switch conflict, the server does not register the tool and keeps the base instructions (#156). With #148 in, chart delivery is off too, with no chart line in `health` | Remove the exported `IDX_ANALYSIS_IMAGE`. Keep the pin in `.env`. Reinstall and restart |
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

**State:** not merged (#148 open, head `ef3bb25`, base `main`, CI green: runs
41804505220 push, 41804498076 pull_request). #148 has merged `main` itself twice:
`27c4ef1` (#156) as `3c84575`, so it carries the `tool.py` resolution, and `48b74ab`
as `58f7d61`, with no conflicts. Not installed; not enabled; **WhatsApp delivery
UNVERIFIED**. Nothing in this procedure has been run against OpenClaw or WhatsApp.

Owner decisions of 2026-11-03: D5 approves this chart path for **one** separately
authorized live WhatsApp trial, which still needs its own paid grant and activation
approval. D6 approves the launchd prune job for strict expiry as part of this activation,
installed by the owner as an operator step.

Owner requirement of 2026-11-04 for the trial, verbatim: "The procedure must roll back
immediately after completion or failure, without waiting for my reply. Record the
rollback and verify analysis/chart delivery are off. Keeping delivery enabled requires
my later approval." So the trial always ends with the rollback, whatever its result; a
pass does not keep delivery on. Keeping it on is a later, separate activation (#148 §7
step 9, quoted below).

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

**The 20-chart cap holds across `idx` server processes (#148, since `6a27dca`).** Each OpenClaw
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
- A bound that holds after SIGKILL needs the launchd prune job in
  `docs/CHART_DELIVERY.md` §5b (`config/chart-prune.launchd.plist.proposal`, every 60 s,
  at most 360 s while awake). D6 approved it on 2026-11-03 as part of this activation;
  the owner installs it (Enable, step 2, as in `docs/CHART_DELIVERY.md` §7). It is
  **not installed** yet, and nothing in the repository installs it.
- In the trial, the rollback's `prune --all` removes the trial's chart right after the
  turn, so none of these windows is reached there.

**Prerequisites**
- Procedure 5 accepted. #148 merged with CI green (G4); it brings
  `scripts/chart_trial_rollback.sh`, the trial's rollback.
- **No tool-policy or config change.** There is no `config/openclaw.charts.json5`;
  `install.sh` renders and merges nothing for charts and only reports the state. The
  design depends on the current OpenClaw 2026.9.5 settings recorded read-only in WO-030:
  `idx` `tools.allow` includes `read`; `tools.fs.workspaceOnly = true`; block streaming
  and sandboxing unset (off). Re-check these after any OpenClaw upgrade (the final-reply
  `MEDIA:` syntax is "legacy, supported").
- D5 approved (2026-11-03) for one trial: the MEDIA-line path, its residual windows (a
  re-send within 300 s while the server lives; until the next sweep after a SIGKILL,
  bounded by the prune job) and the clean-exit trade-off. Before the trial, the owner
  gives its **activation approval** and its **paid grant** (the trial turn is a paid
  model call; `docs/CHART_DELIVERY.md` §7, C5). Neither is given by this file or by D5.
- D6 approved (2026-11-03): the launchd prune job is installed in Enable step 2, after
  `install.sh` and before the restart that turns delivery on, and removed in the
  rollback. The order is #148's (`docs/CHART_DELIVERY.md` §7, steps 1-3): `.env` and
  `install.sh`, then the job (its install starts with a `prune` run that checks the
  directory `.env` names), then the restart.
- `IDX_ANALYSIS_TOOL`, `IDX_ANALYSIS_IMAGE`, `IDX_CHART_DELIVERY` and `IDX_CHART_DIR` are
  not exported anywhere (C4; a contradiction is refused and reported).
- **The rollback turns analysis off too.** It sets both `IDX_CHART_DELIVERY` and
  `IDX_ANALYSIS_TOOL` to `0`, so after the trial the gateway is in the Phase 1 state of
  the C3a off probe (`False False False None None`, 7 tools, 8 skills), and procedure 5
  is off as well. Turning analysis back on, with or without charts, is not part of the
  trial: it is a new activation with the owner's approval (with charts, #148 §7 step 9).

**Enable (M; only inside the authorized trial; #148 §7 steps 1-3)**

The steps and their order are #148's (`docs/CHART_DELIVERY.md` §7 at `ef3bb25`, quoted
in full below); the step 2 commands are its §5b blocks, copied verbatim here ("section
7" in them is `docs/CHART_DELIVERY.md`'s). If §5b or
§7 on `main` ever differs from this file, `docs/CHART_DELIVERY.md` is the source. If any
expectation in steps 1-3 is not met, stop enabling: the trial result is `aborted`; go
straight to step 6, the rollback. Nothing is fixed and retried inside the trial.

Step 1, the switch, from the serving checkout's root on `main` with #148 merged: in
`.env`, edit the `IDX_CHART_DELIVERY` line to read `IDX_CHART_DELIVERY=1` (add the one
line if there is none; `IDX_ANALYSIS_TOOL=1` and `IDX_ANALYSIS_IMAGE` are already set by
procedure 5), then run `scripts/install.sh`. Expect the "Chart delivery is on" lines
below and `openclaw.json` unchanged compared with the Phase 1 install (no new keys).

Observed `install.sh` output (temp HOME, combined branch; `scripts/install.sh` is the
same at `ef3bb25`), after the analysis lines:

```
Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to <HOME>/.openclaw/workspace-idx/idx-charts
and attached to the reply by OpenClaw; no OpenClaw config was changed for it.
WhatsApp delivery is unverified until the acceptance check in docs/CHART_DELIVERY.md passes.
To turn it off: remove IDX_CHART_DELIVERY from .env, restart the gateway, then
  <python> -m idx_agent.analysis.delivery prune --all
```

The last two lines are `install.sh`'s general advice; in the trial the rollback is
step 6 (the script), which edits the line to `=0` instead. With analysis off it prints
`IDX_CHART_DELIVERY=1 has no effect while IDX_ANALYSIS_TOOL is not 1.`, and for a bad
directory `IDX_CHART_DIR must be an absolute path ending in /idx-charts with no spaces;
…`. `openclaw.json` gains no key for charts.

Step 2, the launchd prune job (D6). Install (`docs/CHART_DELIVERY.md` §5b), in a shell
whose working directory is the serving checkout, on `main`, with step 1 done:

```sh
REPO="$(git rev-parse --show-toplevel)"
LABEL=local.idx-exchange.chart-prune
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
test "$(git -C "$REPO" branch --show-current)" = main && test -x "$REPO/.venv/bin/python"
#   expect: exit status 0 (else stop: wrong checkout or no venv)
(cd "$REPO" && .venv/bin/python -m idx_agent.analysis.delivery prune)
#   expect: "removed N chart file(s)" (N may be 0); "nothing pruned" means stop and fix .env
test ! -e "$PLIST"
#   expect: exit status 0 (else it is already installed: verify or uninstall first)
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO__|$REPO|g" "$REPO/config/chart-prune.launchd.plist.proposal" > "$PLIST"
chmod 644 "$PLIST"
plutil -lint "$PLIST"
#   expect: "<PLIST>: OK" (a repo path with "|" or "&" fails here; stop)
grep -c __REPO__ "$PLIST"
#   expect: 0
launchctl bootstrap "gui/$(id -u)" "$PLIST"
#   expect: no output, exit status 0
```

Verify (wait 5 s after the bootstrap; RunAtLoad starts one run at once):

```sh
launchctl print "gui/$(id -u)/local.idx-exchange.chart-prune" \
  | grep -E 'path =|run interval|runs =|last exit code'
#   expect: "path = /Users/<you>/Library/LaunchAgents/local.idx-exchange.chart-prune.plist"
#   expect: "run interval = 60 seconds"
#   expect: "runs = 1" or more, rising by one a minute while awake
#   expect: "last exit code = 0"
```

`last exit code = (never exited)` right after the bootstrap is not a failure: launchd
prints it until the first run has ended, and that run (Python start plus one directory
listing) normally ends within a few seconds. Wait 5 s and run the verify again. If it
still says `(never exited)`, or `runs = 0`, 65 s after the bootstrap (one 60 s interval
plus that margin), the job is not running: treat it as a failed step 2 of section 7,
which ends the trial (`aborted`) with the rollback. `last exit code = 1` means its
`prune` refused (the directory `.env` names is misnamed or unlistable): the same.

Any of these, or verify output other than the four expected lines, is `aborted`: do not
restart; go to step 6, whose script removes the job (the guarded §5b uninstall, under
Rollback below).

The job runs `<repo>/.venv/bin/python -m idx_agent.analysis.delivery prune` every 60 s
from the repository directory (so `.env` names the directory), with no environment of
its own and never `--all`; it deletes only expired chart names in that one directory.
Observed offline at the combined head `969b739` (#148 `a5016be`'s template and
module, unchanged at `ef3bb25`; nothing loaded): the template rendered into a scratch
directory standing in for `~/Library/LaunchAgents` gave `test ! -e` exit 0 before the
render, `plutil -lint` `<PLIST>: OK`, `grep -c __REPO__` `0`, mode `-rw-r--r--` after
`chmod 644`, label `local.idx-exchange.chart-prune` and `StartInterval` 60. The `prune`
line, run from the repository in `env -i` with a temp `HOME` and no chart directory,
printed `removed 0 chart file(s)` with exit 0 and created nothing. The branch/venv
precheck, `mkdir`, `launchctl` and verify lines are operator expectations.

Step 3, the restart:

```sh
openclaw gateway restart
openclaw mcp doctor idx --probe   # expect: 8 tools, including idx__bounded_analysis
openclaw skills list              # expect: 9, including bounded-analysis
```

**Offline acceptance**

```sh
MYSQL_HOST= .venv/bin/python -m pytest -q tests/test_chart_trial_rollback.py \
  tests/test_chart_delivery.py tests/test_phase_integration_charts.py
# #148 ef3bb25, Mac: 138 passed (9 + 113 + 16)
.venv/bin/python -c "from idx_agent.mcp_server import server as s; s.register_analysis_tool(); \
print(s.configure_chart_delivery(), s.chart_delivery_problem())"
# -> True None     (analysis and delivery on in .env, nothing exported)
# -> False None    (either switch off)
# -> False <problem>   (a contradicting export; the same text health shows)
```

The 138 were run on 2026-11-04 from a `git archive` of `ef3bb25` with `PYTHONPATH=src`
(so the archive's code, not the main checkout's, was imported). The 113 + 16 are the 129
of the combined branch; the 9 are #148's new rollback-script tests, which run the script
in a throwaway repository with a temp `HOME` and stub `openclaw`, `node` and
`launchctl`.

### The one-shot live trial, quoted from #148 (L; D5)

Quoted verbatim from `docs/CHART_DELIVERY.md` §7 at #148 `ef3bb25` (re-read from
`origin/wo-030-chart-delivery` on 2026-11-04), everything after its heading line "## 7.
The one-shot live trial: enable, one turn, record, roll back at once (not executed)".
Section numbers inside the quote (5a, 5b, 7) are `docs/CHART_DELIVERY.md`'s; "this PR"
is #148; "Phase 1" there is procedure 5 here (WO-027, bounded analysis), and "the Phase
1 off probe" is C3a.

**Superseded for the rollback (2026-11-04, WO-030 follow-up):** the trial is now armed
before step 1 and rolled back by a watchdog without waiting for any reply
(`scripts/chart_trial_armed.sh`; `docs/CHART_DELIVERY.md` §7, "The trial approval
authorizes arming and the rollback" and step 0a). No consent token (owner, 2026-11-05):
the owner's trial approval authorizes arming and the rollback together, `arm` records it
(`--approval`), and the rollback never depends on a token; the `delete` grant an earlier
revision of §7 required was never needed by the trial's software (the rollback removes
only files the trial creates: the generated charts, and the 5b prune job's plist after
unloading it) and was there only for the agent deletion rule, which is unchanged pending
the owner's decision. The quote below is kept as the record of #148; where it says to
run step 6 by hand, the current §7 governs. The trial stays paused until that change is
merged and its offline demonstration has passed. Also superseded there: a `pass` comes
only from the tool server's chart_delivery line signed with the armed trial's key (step
1 is `scripts/chart_trial_armed.sh enable`); "no reply within 2 minutes of sending" is
the watchdog's countdown from `scripts/chart_trial_armed.sh sent`; after any rollback a
tombstone refuses re-activation and a re-enable is rolled back again; and the rows below
that name a manual `pass`/`fail` rollback are run by the watchdog instead.

<!-- BEGIN verbatim #148 docs/CHART_DELIVERY.md section 7 at ef3bb25 -->
Phase 2 is tried **after** Phase 1 (WO-027) has been installed and accepted, as its own
step, so a failure is attributable to chart delivery alone. D5 (2026-11-03) approves
this path for **one** live WhatsApp trial; the trial needs its own `paid` grant (the
trial turn is a paid model call) and the owner's activation approval. Nothing here has
been run.

Owner requirement (2026-11-04): "The procedure must roll back immediately after
completion or failure, without waiting for my reply. Record the rollback and verify
analysis/chart delivery are off. Keeping delivery enabled requires my later approval."
So the trial is one sequence with no pause for review:

**enable (1-3) -> one trial turn (4) -> record the observed result (5) -> roll back (6)
-> verify off (7) -> write the record (8).**

- The rollback starts as soon as the trial turn has **completed** (a reply arrived) or
  **failed** (no reply within 2 minutes of sending, or any of steps 1-3 failed). The
  operator does not wait for the owner's reply, review or approval, and a pass does not
  keep delivery on.
- The rollback turns **both** switches off: `IDX_CHART_DELIVERY` and
  `IDX_ANALYSIS_TOOL`, so the gateway is back to the 7-tool, 8-skill state of the Phase
  1 off probe (#147, C3a).
- Keeping delivery enabled is **not part of the trial**: it is step 9, a later and
  separate owner decision on the recorded result.

### Step 0. Before anything

The owner has recorded the trial's activation approval and its `paid` grant, Phase 1 is
accepted, and nothing exports `IDX_ANALYSIS_TOOL`, `IDX_ANALYSIS_IMAGE`,
`IDX_CHART_DELIVERY` or `IDX_CHART_DIR` in the shell or the gateway's environment
(they live in `.env` only). Work in the main checkout on `main` after this PR merges.
Note the start time (UTC) and `openclaw --version`.

### Steps 1-3. Enable

```sh
# 1. In .env, edit the IDX_CHART_DELIVERY line to read IDX_CHART_DELIVERY=1 (add the
#    one line if there is none; IDX_ANALYSIS_TOOL=1 and IDX_ANALYSIS_IMAGE are already
#    set by Phase 1), then:
scripts/install.sh
#    expect: "Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to
#             /Users/<you>/.openclaw/workspace-idx/idx-charts"
#    expect: openclaw.json unchanged compared with the Phase 1 install (no new keys)
# 2. Install the launchd prune job (D6): the install and verify commands of section 5b,
#    including its "(never exited)" re-check.
# 3. Restart the gateway:
openclaw gateway restart
openclaw mcp doctor idx --probe   # expect: 8 tools, including idx__bounded_analysis
openclaw skills list              # expect: 9, including bounded-analysis
```

If any expectation in steps 1-3 is not met, stop enabling: the trial result is
`aborted`; go straight to step 6.

### Step 4. The one trial turn

From the owner's number, send `/new`, then one message: "Chart price against size in
Pasadena." Watch the chat for at most 2 minutes from sending. Send nothing else; in
particular no "send that chart again" (a second paid turn). Expiry and the no-resend
rule are pinned offline (section 5a), and step 6 removes the chart at once.

### Step 5. Record the observed result (a scratch note; under a minute)

Write down, before doing anything else: the send time and the reply time (UTC); whether
one WhatsApp image (the scatter chart) arrived; whether the caption or the text after
it has the verified figures, the line "Chart: ... follows as an image in this chat. If
no image appears in this chat, the figures above are the whole result." and the
caveats; whether any line starting `MEDIA:` is visible; any `⚠️` line, verbatim; and
the output of:

```sh
ls -l ~/.openclaw/workspace-idx/idx-charts
#   expect: one chart-<32 hex>.png, mode -rw-------
```

**Pass** when one image arrived with that caption line, no `MEDIA:` line and no `⚠️`
line were visible, and `ls` showed the one chart with mode `-rw-------`. Anything else
is **fail**; a step 1-3 failure is **aborted**. The table below says what each failure
means; whatever it shows, go on to step 6 at once.

| Seen | Meaning |
|---|---|
| A visible `MEDIA:idx-charts/...` line, no image | The model formatted the line; text is whole. Delivery path not proven. |
| `⚠️ chart-....png: File not found` | The file was pruned or written elsewhere; check `IDX_CHART_DIR`. |
| `⚠️ chart-....png: Rejected...` or `Delivery failed` | OpenClaw refused the path; check the workspace setting and that `read` is still allowed. |
| `⚠️ Media failed.` | WhatsApp refused the send; text was delivered. |
| "Chart: could not be prepared for this chat" | Server-side failure; the `chart_delivery` log line has the reason code. |
| A text-only reply with WO-027's caption and no image, and `health` says "Chart delivery is misconfigured" | The gateway's environment contradicts `.env` on `IDX_CHART_DELIVERY` or `IDX_CHART_DIR`. |
| No analysis at all, and `health` says "Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE ..." (no chart line) | The gateway's `IDX_ANALYSIS_IMAGE` differs from `.env`: the tool is not registered (#156), so charts are off with it. |
| The reply says "attached" or "sent" but no image arrived | Wording defect. |
| No reply within 2 minutes | Fail; the cause is investigated after the rollback, from the logs. |

The fixes these rows point to are made after the rollback, never during the trial;
trying again is a new trial and needs a new authorization.

### Step 6. Roll back, now

```sh
scripts/chart_trial_rollback.sh pass      # or: fail, aborted (the step 5 result)
```

It runs these, in order, each one even when an earlier one failed, and reports each
(the manual equivalent, if the script cannot run, is the same commands by hand):

1. `.env`: every `IDX_ANALYSIS_TOOL=` and `IDX_CHART_DELIVERY=` line (an `export`
   line too) is **edited in place** to `=0`. Appending a line does not work: the first
   line for a key wins (`dotenv_values`). Other lines and the file mode are kept. By
   hand: change those lines in an editor, then
   `grep -nE '^[[:space:]]*(export[[:space:]]+)?IDX_(ANALYSIS_TOOL|CHART_DELIVERY)[[:space:]]*=' .env`
   must show only lines ending in `=0`.
2. `scripts/install.sh` (expect: exit 0, no "Bounded analysis is on" and no "Chart
   delivery is on" line; it removes `~/.openclaw/openclaw.analysis.json5`).
3. `openclaw gateway restart`.
4. `.venv/bin/python -m idx_agent.analysis.delivery prune --all` (expect: "removed N
   chart file(s)"; only our chart and temp names; the lock file stays).
5. The launchd prune job, guarded (the section 5b uninstall): `launchctl bootout` only
   if `launchctl print` finds the job, `rm` of the plist only if it exists. Neither
   present is reported as "not installed", not as an error (for example when step 2
   never ran).

### Step 7. Verify that analysis and chart delivery are off

The script then checks, and prints, each of these; by hand they are:

```sh
.venv/bin/python -c "from idx_agent.analysis import delivery; \
from idx_agent.db.pool import dotenv_values as v; d = v(); \
print(d.get('IDX_ANALYSIS_TOOL') == '1', d.get(delivery.SWITCH) == '1')"
#   -> False False            (IDX_ANALYSIS_TOOL and IDX_CHART_DELIVERY off in .env)
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
s.configure_chart_delivery(), s.analysis_switch_problem(), s.chart_delivery_problem()); \
h = s.health_result(); print(h.warnings, 'analysis' in h.message.lower(), \
'chart' in h.message.lower())"
#   -> False False False None None   (bounded_analysis absent; chart_state off)
#   -> [] False False                (health: no analysis or chart line)
openclaw mcp doctor idx --probe | grep -c bounded_analysis   # -> 0 (7 tools)
openclaw skills list | grep -c bounded-analysis              # -> 0 (8 skills)
ls ~/.openclaw/openclaw.analysis.json5                       # -> No such file or directory
launchctl print "gui/$(id -u)/local.idx-exchange.chart-prune"
#   -> "Could not find service ..." and a non-zero exit status
ls ~/.openclaw/workspace-idx/idx-charts                      # -> nothing listed
```

The script ends with its record block. A complete rollback looks like this (the job
was installed; for a job never installed the launchd line reads `not installed`):

```text
chart trial rollback record (WO-030, D5)
  trial result: pass
  rollback started: <UTC>  finished: <UTC>
  step .env: IDX_ANALYSIS_TOOL 1 line(s) set to 0, IDX_CHART_DELIVERY 1 line(s) set to 0
  step install.sh: ok
  step gateway restart: ok
  step prune --all: removed 1 chart file(s)
  step launchd prune job: booted out, plist removed
  verify .env: IDX_ANALYSIS_TOOL off, IDX_CHART_DELIVERY off
  verify server: bounded_analysis absent (not listed), chart_state off, problems None / None
  verify health: 0 warning(s), no analysis/chart line
  verify chart files: 0
  verify mcp doctor: bounded_analysis listed 0 time(s)
  verify skills: bounded-analysis listed 0 time(s)
  verify analysis fragment: absent
  verify launchctl: Could not find service
ROLLBACK DONE: analysis off, chart delivery off
```

Exit status 0 only with `ROLLBACK DONE`. Otherwise the last line is `ROLLBACK
INCOMPLETE: <the failed steps and checks>` and the exit status is 1: fix what it names
(for example an exported switch, which makes `install.sh` refuse) and run the script
again with the same result word. It is safe to repeat: a rerun edits the same lines to
the same value, prunes nothing more and reports the job as not installed. Do not turn
anything back on to get past a failure.

Offline evidence (`tests/test_chart_trial_rollback.py`, 7 test functions, 9 collected
cases): the script, copied
into a throwaway repository with a temp `HOME` and state directory and stub
`openclaw`, `node` and `launchctl` that answer from the files the steps change, prints
exactly the block above (installed and never-installed job), edits every switch line in
place (an `export` line and a repeated key included) and keeps the file mode, keeps
going after a failed gateway restart and reports `ROLLBACK INCOMPLETE: gateway
restart`, does not report off while a shell still exports `IDX_ANALYSIS_TOOL=1`,
changes nothing for a bad argument, and never bootstraps or loads anything.

### Step 8. Write the record

After `ROLLBACK DONE` (or, if it stays incomplete, with what is still on), append one
entry to `docs/EVIDENCE_LOG.md` (append-only) and one dated entry to WO-030's Status,
aggregates only (no phone number, no chat text beyond the fixed request):

```text
- <date>, WO-030: one-shot live WhatsApp chart trial (D5). Activation approval and paid
  grant: <where they are recorded>. OpenClaw <version>.
  Trial: started <UTC>; trial turn sent <UTC>; reply <UTC or "none within 2 min">.
  Result: <pass | fail | aborted at step N>. Image: <yes/no>. Caption line: <yes/no>.
  MEDIA line visible: <yes/no>. Warning line: <verbatim or none>.
  ls: <one chart-<hex>.png, -rw------- | other, as seen>.
  Rollback: run at once, without waiting for review; started <UTC>, finished <UTC>;
  <the script's record block, verbatim, or the manual step results>.
  State now: analysis off, chart delivery off. Keeping delivery enabled was not
  decided by the trial; it needs the owner's approval of this entry.
```

WhatsApp delivery is verified only by a recorded pass; a fail or an aborted trial
leaves it UNVERIFIED and the requirement not met, even though the text was whole.

### Step 9 (separate, not part of the trial). Keeping delivery enabled

Only after the owner has read the step 8 record of a **pass** and approved, in writing,
keeping chart delivery enabled, the operator repeats steps 1-3 (with `IDX_ANALYSIS_TOOL`
edited back to `=1` first) as a new activation and records it. No approval, or no reply,
means delivery stays off; a fail or an aborted trial cannot be approved into "on", only
into a new authorized trial.

Residue after the rollback: no config keys; the `idx-charts` directory with only the
empty lock file `.idx-charts.lock` (`ls` lists nothing; `ls -A` lists that one file).
Removing the directory is optional and the owner's decision.

<!-- END verbatim #148 docs/CHART_DELIVERY.md section 7 at ef3bb25 -->

### Failure handling (5b)

Every outcome leads to the same next step: step 6, the rollback, at once, then step 7.
Nobody waits for the owner's reply first, and no fix is tried inside the trial; a retry
is a new trial and needs a new authorization. The table above (step 5) says what a
failed trial turn means; this one covers the whole sequence.

| When | What you see | Result | Next |
|---|---|---|---|
| Step 1 | `install.sh` refuses (an exported switch, image or directory, C4), or prints no "Chart delivery is on" line, or `openclaw.json` gains a key | `aborted` | `scripts/chart_trial_rollback.sh aborted` |
| Step 2 | The verify does not show all four expected lines 65 s after the bootstrap (`path =` the LaunchAgents plist, `run interval = 60 seconds`, `runs =` 1 or more, `last exit code = 0`); or `last exit code = 1`; or "Could not find service"; or any install line fails | `aborted` (do not restart) | `scripts/chart_trial_rollback.sh aborted` (it removes the job, or reports "not installed") |
| Step 3 | The restart fails, or not 8 tools with `idx__bounded_analysis`, or not 9 skills with `bounded-analysis` | `aborted` | `scripts/chart_trial_rollback.sh aborted` |
| Step 4-5 | Any row of the step 5 table, any `⚠️` line, a visible `MEDIA:` line, no image, or no reply within 2 minutes of sending | `fail` | `scripts/chart_trial_rollback.sh fail` |
| Step 4-5 | One image with the caption line, no `MEDIA:` and no `⚠️` line, `ls` shows one `chart-<32 hex>.png` with mode `-rw-------` | `pass` | `scripts/chart_trial_rollback.sh pass`. A pass does not keep delivery on |
| Step 6 | Last line `ROLLBACK INCOMPLETE: <failed steps and checks>`, exit status 1 | rollback incomplete | Fix what it names (for example unset an exported switch, which makes `install.sh` refuse) and run the script again with the same result word. Never turn anything back on to get past it. If it stays incomplete, step 8 records what is still on |
| Step 6 | The script cannot run | — | The manual equivalent: step 6 parts 1-5 by hand (part 5 is the §5b uninstall below), then every step 7 check by hand |
| Step 7 | Any check differs from its expected line (for example `True` in the `.env` line, `bounded_analysis` listed by `mcp doctor`, a chart file left) | rollback incomplete | As for `ROLLBACK INCOMPLETE`: fix the named cause and rerun step 6 |
| After step 8 | The owner has not replied, or did not approve keeping delivery on | — | Nothing: delivery and analysis stay off. Only a written approval of a recorded **pass** leads to step 9 |

The causes the step 5 rows point to (`IDX_CHART_DIR`, the workspace setting, `read`
still allowed, the `chart_delivery` log line's reason code such as `dir_invalid`,
`dir_full`, `dir_busy`, `lock_unsafe` or `lock_unavailable`, an image conflict as in
procedure 5's failure rows) are investigated after the rollback, from the logs. For
`lock_unsafe`, inspect `ls -la ~/.openclaw/workspace-idx/idx-charts`.

### Rollback (5b)

The rollback is #148 §7 step 6, `scripts/chart_trial_rollback.sh <pass|fail|aborted>`,
followed by the step 7 checks the script runs and prints, both quoted above. Run it at
once after the trial turn completes (a reply arrived) or fails (no reply within 2
minutes, or a step 1-3 failure), without waiting for the owner. It replaces this
file's earlier 5b rollback, which removed only the delivery line and left analysis on.

Two differences from the other procedures in this file:
- `.env`: the script **edits** every `IDX_ANALYSIS_TOOL=` and `IDX_CHART_DELIVERY=` line
  (an `export` line too) in place to `=0`. C4 and procedure 5's rollback remove the line
  instead. Both leave the switch off: the first line for a key wins, and only the value
  `1` is on. Never append a `=0` line below an `=1` line.
- Both switches go off, so procedure 5 is rolled back with 5b (Prerequisites above).

Part 5 of step 6 is the §5b uninstall of the launchd prune job, verbatim (the script
runs the same guarded steps; by hand, run this block):

```sh
SERVICE="gui/$(id -u)/local.idx-exchange.chart-prune"
PLIST="$HOME/Library/LaunchAgents/local.idx-exchange.chart-prune.plist"
if launchctl print "$SERVICE" >/dev/null 2>&1; then
  launchctl bootout "$SERVICE" && echo "booted out"
else
  echo "not loaded"
fi
#   expect: "booted out" (installed) or "not loaded" (never installed)
if [ -e "$PLIST" ]; then rm "$PLIST" && echo "plist removed"; else echo "no plist"; fi
#   expect: "plist removed" (installed) or "no plist" (never installed)
#   "not loaded" and "no plist" together: the job was not installed; nothing to undo
launchctl print "$SERVICE"
#   expect: "Could not find service" and a non-zero exit status (in every case)
```

Expected result after step 7: the record block ends `ROLLBACK DONE: analysis off, chart
delivery off` and the script exits 0. The gateway is in the C3a state: the C3a probe
prints `False False False None None`, `openclaw mcp doctor idx --probe` lists 7 tools
and no `bounded_analysis`, `openclaw skills list` lists 8 skills, there is no
`~/.openclaw/openclaw.analysis.json5`, and `launchctl print` reports "Could not find
service". No expiry thread, exit hook or SIGTERM handler is armed with delivery off
(`tests/test_phase_integration_charts.py`). Residue: no config keys; the `idx-charts`
directory may remain, holding only the empty lock file: `ls
~/.openclaw/workspace-idx/idx-charts` lists nothing, and after any chart write `ls -A`
lists `.idx-charts.lock` (mode `-rw-------`, size 0), which `prune --all` keeps
(observed in a temp directory: the `--all` prune removed the one chart and left only
`.idx-charts.lock`). Removing the directory is optional and the owner's decision.

Then step 8, the record, in `docs/EVIDENCE_LOG.md` and WO-030's Status (template
quoted above). Keeping delivery on is step 9 only.

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
- Earlier versions of this file (up to `2d84ce1`) said an `IDX_ANALYSIS_IMAGE` conflict
  only warns: the server kept `bounded_analysis` and ran the exported digest. That is
  superseded by the owner decision of 2026-11-03 and #156 (`27c4ef1`): an image conflict
  fails closed like a switch conflict (C4, procedure 5).
- Up to #148 `6a27dca`, `docs/CHART_DELIVERY.md` §7 left delivery on after a pass and
  §5b called the launchd job a proposal. #148 `a5016be` records D5 (one trial, rolled
  back unless the owner approves the result) and D6 (the job installed by the owner as
  §7 step 2), and gives the job's full install, verify and uninstall. §9 now follows
  that §7 order and quotes those §5b blocks verbatim; no departure remains. Earlier
  versions of this file (up to `2c9d933`) had an older, shorter job install (no
  precheck, dry prune, `mkdir -p` or `chmod`) as step 1, before `install.sh`.
- #148 `a5016be`'s "rolled back unless the owner approves the result" is superseded by
  the owner requirement of 2026-11-04 and #148 `ef3bb25`: the trial rolls back at once
  after completion or failure, without waiting for the owner, turns `IDX_ANALYSIS_TOOL`
  off with `IDX_CHART_DELIVERY`, and has one trial turn (no "send that chart again").
  §9 quotes that §7 verbatim. One difference from this file's other rollbacks remains,
  stated in §9: the rollback script edits the switch lines to `=0` in place, where C4
  removes the line; both leave the switch off.

## 11. Combined acceptance before presenting for merge

**Branch.** `chore-phase-integration-4`, pushed for reference (no PR; not for merge),
built 2026-11-04 07:45Z from the heads current then. It is `main` `48b74ab` (which
already holds #144 `f85e35c`, #154 `65b53cc`, #145 `ee1c20f`, #152 `7c0fea7` and #156)
plus, with merge commits in the approved order (D7): #148 `a5016be`, #150 `757c212`,
#153 `68cbf24` and #147 `2c9d933` (this PR's head before this docs commit), giving
`969b739`. Then #155 `8a7fc34` last (`07f2060`), and one scratch commit with the fixture
switch #155 plans to make (below), giving `988a261`. This docs commit is merged after
them and changes no code.

**Not rebuilt for the heads of 2026-11-04.** #148 `ef3bb25`, #150 `926dabf` and #155
`1409184` moved after this branch was built. Against the combined heads they add: #148,
`docs/CHART_DELIVERY.md`, `scripts/chart_trial_rollback.sh`,
`tests/test_chart_trial_rollback.py` (7 test functions, 9 collected cases),
`scripts/README.md`, WO-030 and a merge
of `main` `48b74ab`; #150, a merge of `main` `48b74ab` and WO-025 docs; #155, a merge of
`main` `48b74ab` and the #154 fixture adaptation (the #154 part of its planned switch),
plus WO-035 docs. #155 records its own scratch merge with #147 `e93a5db`, #148
`a5016be`, #150 `926dabf` and #153 `68cbf24` (5,074 passed, 0 failed, 130 skipped in
both modes, after the rest of its adaptation). Each head's own CI is in the table
below. The combined counts in this section are those of `969b739` and `988a261`.

Superseded: `chore-phase-integration-3` (`1525494`, `88f8f12`) was built from older
heads (#148 `6a27dca`, #150 `290b494`, #153 `b4af2f3`, #155 `de6ee83`, #147 `5f61917`)
that had all moved before this file's `f0978c8` and `2c9d933` called them current. Its
results are kept in WO-029's Status as measured at those heads. Against them, the new
heads change code or tests only in #148: `tests/test_chart_switch_agreement.py` (+3
tests, an image conflict keeps charts off) and the comment in
`config/chart-prune.launchd.plist.proposal`; the rest is documentation. The earlier
branches `chore-phase-integration` (`d6f4759`) and `chore-phase-integration-2`
(`30ff289`) are superseded too and left as they were.

**Conflict map.** One, expected:
- `docs/EVIDENCE_LOG.md`, #153 against `main` (#152 is merged): both append an entry at
  the same place. The log is append-only, so both entries are kept, #152's first; every
  added line of each is present and `main`'s log is an unchanged prefix (0 removed lines
  against `main` and against #153). #153 does the same when it merges `main`.

`src/idx_agent/analysis/tool.py` no longer conflicts: #148 merged `main` `27c4ef1` itself
(`3c84575`) with the resolution prepared last round (#148's helpers and `KEEP_IN_DOTENV`,
#156's `IMAGE_DIFFERS`), and its file is byte-identical to the one on `969b739` and on
the old combined `1525494` (`git diff` empty for both). Every other merge was clean,
and #155 merged cleanly on top.

**Merge order (D7, approved as written on 2026-11-03).** WO-035 (#155) adds store-count
hardening: `open_store` refuses a store that carries the approved digest with any count
other than the trusted 54,888 (`source_count_mismatch`). The small synthetic stores that
#147, #148, #150 and #154 write in their tests carry that digest, so they stop opening
once #155 is on `main`. On `07f2060` (#155 merged, no switch) the five affected files
gave **49 failed, 85 passed, 7 errors** (#147's file among them), the same count WO-035
reports. The order:
1. #144, then #154 (stacked on #144's branch). Done: `5daa7b5`, `d92b11f`.
2. #145; #148; #150; #152; #153: in any order. #148 already carries the `tool.py`
   resolution. For #152 and #153, keep both `docs/EVIDENCE_LOG.md` entries (#152 is
   merged, so #153 keeps both when it merges `main`). Done: #145 `5a20be8`, #152
   `48b74ab`.
3. #147 (this PR) before #155, in any position among the step 2 PRs. #155 adapts
   #147's `tests/test_phase_integration.py` (its 6 store-writing tests) when it merges
   `main`, so #147 must already be on `main` then. Merged after #155, #147 would bring
   those 6 tests in unadapted, and they would fail on `main` (WO-035's count: #147 6,
   #148 2, #150 5 + 36). This corrects the earlier "#147 at any time".
4. #155 last. It merges `main` and switches the affected test files to
   `tests/synthetic_store.py` (`write_synthetic_store`; `trust_source` for #154's
   fixture), so only #155 adapts and every other PR stays green on its own CI. #154 is
   on `main`, so #155 has already merged `main` `48b74ab` (`35f042a`) and adapted
   #154's fixture (`8f6f678`); its `pull_request` run 41802740558 on `1409184` is green
   (4,781 passed, 74 skipped). Before that, run 41793753209 on `8a7fc34` failed with
   #154's 7 setup errors (4,774 passed, 74 skipped, all in
   `tests/test_enrichment_omission_pilot_v2.py`, `AttributeError` on the removed
   `EXPECTED_RESULTS_DIGEST`). The #147, #148 and #150 files are adapted when #155
   merges `main` after them.
5. C1–C2, the v5 manifest freeze and the v5 build (procedure 1), C3 and the C3a off
   probe, Phase 1 (G2–G3), then Phase 2.

Rerun `main` CI after each merge. WO-033's model review may start once #144 and #154
are merged (owner decision, 2026-11-03; both now are). It is #157; it is not part of
the D7 order and changes no step in this file.

**Lint (Mac).** `ruff check .`: all checks passed. `ruff format --check .`: 449 files
already formatted at `969b739`; all checks passed and 455 files already formatted at
`988a261`.

**Full offline suite, Mac** (`MYSQL_HOST=`; Docker and Ollama absent, so `container` and
`db` tests skip; the runs were sequential):
- `969b739` (before #155), `IDX_ANALYSIS_IMAGE` unset: **5,005 passed, 130 skipped**;
- the same, `IDX_ANALYSIS_IMAGE=sha256:a…` exported (as CI does): **5,005 passed, 130
  skipped**;
- `988a261` (with #155 and the fixture switch): **5,074 passed, 130 skipped**, with
  `IDX_ANALYSIS_IMAGE` unset and again exported;
- offline `ci` eval suite at `969b739` (`PYTHONPATH=src:. python -m evals.run --suite
  ci`, no database; without `PYTHONPATH` a worktree imports the main checkout's `src`
  through the editable install): 251 cases, 84 pass, 0 fail, 167 skipped (no database);
- every `tests/test_phase_integration*.py` together: **39 passed (17 in #147's file, 6
  in #150's, 16 in #148's)** at `969b739`, and 39 passed at `988a261`.
- Per procedure at `969b739`: search 168, badges 43, explanations 105, saved searches
  110 (78 in `tests/test_saved_feature_searches.py`), analysis 218 + 2 skipped (db),
  charts 129 (113 + 16). The same as at `1525494`.

No xfail, no expected-failure marker and no skip other than the POSIX guard for
`install.sh` (it runs on the Mac and CI). On `chore-phase-integration-3`, a pair of full
runs started in parallel each had one failure,
`test_how_the_process_ends_decides_what_happens_to_its_charts[sigint]` (#148): its
child process timed out after 30 s under the doubled load, and it passed 5 of 5 runs
alone. All runs above were sequential and had no failure.

**CI** (kept separate from the Mac; GitHub Actions, "commit gates" and "lint and tests").
Counts are the unit job (no database), then the fixture-database job, then the `ci`
evals:

| Head | Run ids | Result |
|---|---|---|
| `main` `27c4ef1` | 41783586545 (push) | success: 4,526 passed, 74 skipped; 73 passed, 1 skipped; 211 cases, 211 pass |
| `main` `5daa7b5` (#144), `d92b11f` (#154), `5a20be8` (#145) | 41785273066, 41785441491, 41785466370 (push) | success each |
| `main` `48b74ab` (#152) | 41785486554 (push) | success: 4,712 passed, 74 skipped; 73 passed, 1 skipped; 251 cases, 251 pass |
| `main` `c62ca83` (#159, `README.md` only) | 41805565257 (push) | success: 4,712 passed, 74 skipped; 73 passed, 1 skipped; 251 cases, 251 pass |
| #144 `f85e35c` (merged) | 41766553397 (push), 41766558067 (pull_request) | success: 4,569 passed, 74 skipped; 73 passed, 1 skipped; 211 pass |
| #154 `65b53cc` (merged) | 41782350746 (push), 41782353366 (pull_request) | success: 4,593 passed, 74 skipped; 73 passed, 1 skipped; 211 pass |
| #145 `ee1c20f` (merged) | 41607142180 (push), 41607149994 (pull_request) | success; `ci` evals 251 cases, 251 pass |
| #152 `7c0fea7` (merged) | 41774857439 (push), 41774860037 (pull_request) | success: 4,548 passed, 74 skipped; 73 passed, 1 skipped; 211 pass |
| #148 `ef3bb25` (current) | 41804505220 (push), 41804498076 (pull_request) | success: 4,957 passed, 74 skipped each; 73 passed, 1 skipped; 251 cases, 251 pass |
| #148 `a5016be` (combined branch) | 41787349942 (push), 41787352725 (pull_request) | success: push 4,762 passed, 74 skipped, `ci` evals 211 pass; pull_request (merged with `main`) 4,948 passed, 74 skipped, 251 pass; 73 passed, 1 skipped each |
| #150 `926dabf` (current) | 41800389697 (push), 41800399923 (pull_request) | success: 4,797 passed, 74 skipped each; 73 passed, 1 skipped; 251 pass |
| #150 `757c212` (combined branch) | 41785175637 (push), 41785183145 (pull_request) | success: 4,611 passed, 74 skipped; 73 passed, 1 skipped; 211 pass |
| #153 `68cbf24` | 41786205804 (push; GitHub shows no pull_request run for this head) | success: 4,586 passed, 74 skipped; 73 passed, 1 skipped; 211 pass |
| #155 `1409184` (current) | 41802732957 (push), 41802740558 (pull_request) | success: 4,781 passed, 74 skipped each; 73 passed, 1 skipped; 251 pass (it merged `main` and adapted #154's fixture) |
| #155 `8a7fc34` (combined branch) | 41793747773 (push), 41793753209 (pull_request) | push success: 4,595 passed, 74 skipped; 73 passed, 1 skipped; 211 pass. pull_request: failure, expected until #155 adapts: 4,774 passed, 74 skipped, 7 errors (#154's fixture) |
| #147 | in the PR (this branch's CI) | |
| `chore-phase-integration-4` `969b739` | 41795446978 (push) | success: 5,061 passed, 74 skipped; 73 passed, 1 skipped; `ci` evals 251 cases, 251 pass, 0 fail |
| `chore-phase-integration-4` `988a261` (with #155 and the fixture switch) | 41795976472 (push) | success: 5,130 passed, 74 skipped; 73 passed, 1 skipped; `ci` evals 251 cases, 251 pass, 0 fail |

CI's database job runs the `db` tests and the `ci` eval suite against the fixture
database; the Mac runs cannot, so their counts differ.

**Cross-feature checks**, each in a reviewable PR (synthetic store, the real listing SQL
on SQLite, the WO-011 recommend harness, synthetic alert stores, temp HOME installs;
switches written to a temp `.env`):

| Check | Where |
|---|---|
| Default off: `idx` tool list and the hashes of the tool listing and the instructions equal the pinned values (from `main` `cbad756`, since moved: tool listing in P1-4, owner-accepted; instructions in WO-042 #189, `46dfa9cc…` -> `ba79956b…`, owner-accepted 2026-11-11); no store opened; routing prompt without the analysis skill | `tests/test_phase_integration.py` (#147); `tests/test_phase_integration_charts.py` (#148, also: a fresh process arms no thread, handler or hook) |
| A configured store with every switch off changes only the feature-search reply | #147 |
| Each switch alone moves only its own surface: badges → search; explanations → recommend; analysis → tools, instructions, routing; saved → feature save and list; charts alone → nothing; charts with analysis → only the delivery state | #147; #150 (saved); #148 (charts) |
| All on: one store feeds search, badges, explanations and the saved alert; analysis registered beside them | #147; #150; #148 |
| Analyst routing: the routed `bounded_analysis` call with badges and explanations on returns the verified figure (inline PNG without delivery; a `MEDIA:` chart that expires while idle with delivery) | #147; #148 |
| Saved alerts: a changed listing is left out everywhere, counted `deferred`, then alerted once after a rebuild | #150 |
| Stale and missing store: feature search unavailable, plain search unbadged, no explanations, feature save refused, job reports `unavailable` and leaves the search untouched, plain search still drafts | #147; #150 |
| Rollback, every switch on then off one at a time, returns every surface to the off state; with the store removed too, main's hashes return | #147; #148; #150 (a feature search saved while on stays inert) |
| Install rollback in a temp HOME leaves no `openclaw.analysis.json5`, an `openclaw.json` equal to a default install, and the same state files plus `openclaw.json.pre-idx.bak` | #147; #148 |
| env vs `.env`: `IDX_ANALYSIS_TOOL` (install refuses; server registers nothing, base instructions, reports); `IDX_ANALYSIS_IMAGE` with the switch on (install refuses; server registers nothing, base instructions, reports, the same as a switch conflict; #156; with #148, chart delivery off and no chart line); `IDX_CHART_DELIVERY` and `IDX_CHART_DIR` (both refuse or report); badges and explanations never change the install | #147 (`test_a_switch_or_image_conflict_unregisters_and_reports`); #156; #148; `tests/test_analysis_switch_agreement.py` (main) |

`IDX_FEATURE_SAVED_SEARCHES` never changing the install was checked on the combined
branch with a scratch probe (3 cases passed); `install.sh` does not mention the name. It
is not pinned by a test in a PR.

**Not covered offline:** Docker isolation of the worker, the `db` integration tests (CI
runs them), the real store and database (the M probes above), the gateway's process
handling of the server (SIGKILL residual), OpenClaw's handling of the `MEDIA:` line and
WhatsApp delivery (L, unverified).

## Smallest operator checklist

1. Review and merge in the approved order (D7), CI green on `main` after each: #144,
   then #154; #145, #148 (it already carries the `tool.py` resolution), #150, #152 and
   #153 in any order (#153 keeps both `docs/EVIDENCE_LOG.md` entries when it merges
   `main`, #152's first); #147 among them, before #155 (#155 adapts #147's test
   file). Done: #144, #154, #145, #152 (`main` `48b74ab`, CI green; `main` is now
   `c62ca83` with #159).
2. Merge #155 (WO-035, v5 store migration) last, after #147, #148 and #150; it merges
   `main` and adapts their shared test fixtures itself (section 11).
3. C1 backup; C2 serving checkout to `main` (D1 approved; the owner's step).
4. v5 store (procedure 1, first prerequisite; free, no token): write and review the
   proposed v5 manifest, freeze it as `data/enrichment/effective-store-v5-manifest.json`
   beside the unchanged v4 manifest, run the `--policy v5 --dry-run` and then the
   `--policy v5` build from the serving checkout, check `open_store` shows
   `policy_version='v5'` and `listing_count=54888`, and re-record the store info line
   and the Pasadena `solar` probe. Stop on any builder refusal.
5. C3 install; record the revision. Expect 7 tools, 4 alert tools, 8 skills. Then the
   C3a off probe: `False False False None None`, and `0` from both `grep -c` lines
   (`bounded_analysis` absent, `IDX_ANALYSIS_TOOL` off, `IDX_CHART_DELIVERY` off).
   Anything else stops here.
6. Phase 1, one switch per restart, each with its live check, a C3a rerun and an
   EVIDENCE_LOG entry: `IDX_ENRICHMENT_STORE` (the v5 file) → `IDX_FEATURE_BADGES=1`
   (current look, D2) → `IDX_FEATURE_EXPLANATIONS=1` → `IDX_FEATURE_SAVED_SEARCHES=1`
   (conservative defaults, D4; save, list, `--dry-run`, delete).
7. After Phase 1 is accepted: C1–C3 at the Phase 2 revision.
8. Phase 2, procedure 5: build and pin the worker, `IDX_ANALYSIS_TOOL=1` + `install.sh`
   + restart + live check. Roll back only the step that failed.
9. Procedure 5b, one chart trial (D5), only after its own activation approval and paid
   grant, as #148's `docs/CHART_DELIVERY.md` §7 (quoted in §9), one sequence with no
   pause for review: (1) `IDX_CHART_DELIVERY=1` + `install.sh`; (2) install and verify
   the launchd prune job (D6; four expected `launchctl print` lines, re-checked 65 s
   after the bootstrap); (3) restart, 8 tools, 9 skills; any failure in 1-3 is
   `aborted` and goes straight to (6). (4) `/new` and the one trial turn, watched for at
   most 2 minutes; (5) note what was seen: `pass`, `fail` (including no reply in 2
   minutes) or `aborted`. (6) At once, whatever the result and without waiting for the
   owner: `scripts/chart_trial_rollback.sh <result>` (both switches edited to `=0`,
   `install.sh`, restart, `prune --all`, the guarded job uninstall). (7) Its checks must
   end `ROLLBACK DONE: analysis off, chart delivery off`, exit 0 (C3a state: 7 tools,
   8 skills, no job); otherwise fix what it names and rerun. (8) Record the trial and the
   rollback in `docs/EVIDENCE_LOG.md` and WO-030's Status.
10. Keeping delivery on (#148 §7 step 9) is not part of the trial: only after the owner
    has read a recorded **pass** and approved it in writing, as a new activation. No
    reply means it stays off.

## Owner decisions still open

- Each merge (in the D7 order), install, activation and paid live check, each with its
  own approval. None is granted by the decisions below.
- D5 follow-up: after the one chart trial and its immediate rollback, whether to turn
  chart delivery back on (#148 §7 step 9). Only a written approval of a recorded pass
  does; until then, or with no reply, analysis and chart delivery stay off.
- WO-035 leaves open whether to re-read under rulings 1-7 before the v5 build (WO-018
  Status); it does not change any step in this file.

## Decided (2026-11-03, owner decisions round three)

- **2026-11-04, chart trial rollback (owner requirement, verbatim):** "The procedure must
  roll back immediately after completion or failure, without waiting for my reply.
  Record the rollback and verify analysis/chart delivery are off. Keeping delivery
  enabled requires my later approval." #148 `ef3bb25` implements it in
  `docs/CHART_DELIVERY.md` §7 and `scripts/chart_trial_rollback.sh`; §9 quotes it.

- **D1 approved.** Switch the main checkout from `wo-021-recommend-design` to `main` in
  place. C2 is the owner's own step; the agent never touches the main checkout.
- **D2: keep the current badge look**: up to 3 per card, requested features first then
  A–Z, area facets shown, prefix `From description:` (procedure 2).
- **D4: keep the conservative saved-search defaults** as #150 implements them: a
  separate switch; uncheckable saves refused with nothing stored; checked only up to
  the snapshot day; deferral held by every changed listing in the window; a held date
  level with the active data exits 0 under `deferred`; lapsed searches renewed in place
  with no catch-up (a deferral held before the lapse is dropped); an unshown overflow
  match may be counted again in a later draft (procedure 4).
- **D5 approved for one trial.** The MEDIA-line chart path, its residual windows and
  the clean-exit trade-off are approved for one separately authorized live WhatsApp
  trial. The trial still needs its own paid grant and activation approval. The trial
  always ends with the immediate rollback (§9; the owner requirement of 2026-11-04
  below); keeping delivery enabled afterwards needs the owner's later approval.
- **D6 approved.** The launchd prune job for strict chart expiry is part of the Phase 2
  chart activation, installed by the owner as an operator step and removed with the
  rollback (§9, Enable step 2 and Rollback; `docs/CHART_DELIVERY.md` §5b and §7 on #148).
- **D7 approved as written.** The merge order in section 11, with #148 before #155. The
  Phase 1 probe must show the `bounded_analysis` tool absent, `IDX_ANALYSIS_TOOL` off
  and `IDX_CHART_DELIVERY` off (C3a, gate G2). The v5 manifest freeze and build follow
  procedure 1.
- Earlier, also on 2026-11-03: an `IDX_ANALYSIS_IMAGE` conflict fails closed (#156,
  merged at `27c4ef1`; C4). Decisions 1 and 2 (the "can't help" line; charts must reach
  WhatsApp) and D3 (explanation line only) were made before this file's final version
  (§6, §8, §9).

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
| D1: bring the serving checkout to `main` | C2 (D1 approved 2026-11-03; the owner's step) |
| Default tool, alert-tool and skill counts | C3 (7, 4, 8; 8 and 9 with analysis, with or without charts) |
| Per-procedure offline counts at the final heads | 4–9 (combined branch, 2026-11-03) |
| Saved-search deferral and lapse fixes | 7 |
| Chart switch agreement and expiry as proven | C4, 9 |
| Switch conflict and image conflict (both: tool not registered, reported in `health`; with #148, charts off too) | C4, 8, 9, 11 |
| Phase 1 off probe: `bounded_analysis` absent, `IDX_ANALYSIS_TOOL` and `IDX_CHART_DELIVERY` off (D7) | C3a, 2 (G2) |
| One chart trial with immediate rollback (D5); launchd prune job install and removal (D6) | 9 |
| Owner decisions of round three | Decided list |
| Combined, cross-feature, default-off and rollback results; Mac vs CI | 11 |

Follow-up refresh of 2026-11-03 (review of #150, #147 C4 and #148): C4, procedure 5 and
the failure tables cover an `IDX_ANALYSIS_TOOL` conflict and an `IDX_ANALYSIS_IMAGE`
conflict; since the owner decision of 2026-11-03 (#156) both leave the tool unregistered
and are reported, backed by `test_a_switch_or_image_conflict_unregisters_and_reports`
(this paragraph first recorded the image conflict as a warning only). Procedure 4 now
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

Refresh of 2026-11-03 (D-032 and WO-035): `main` `32cd727` merged into this branch.
Procedure 1's first prerequisite now points at WO-035 (#155) for the v5 store, with its
manifest freeze, `--policy v5` build, `open_store` check (`v5`, 54,888) and re-recorded
probes; the claim that the current builder produces a v5 store and every WO-032
extraction, paid or token step are removed, because WO-032 is closed as not applicable
(D-032 option a) and the 321 description-less listings stay unknown. The enable line
names the v5 file, the rollback can point back at the kept v4 file, the checklist is
renumbered, and section 11 gives WO-035's merge order.

Refresh of 2026-11-03 (owner decisions, round three; #156 merged at `27c4ef1`): `main`
`27c4ef1` merged into this branch with a merge commit. The conflict test is renamed to
`test_a_switch_or_image_conflict_unregisters_and_reports` and asserts the fail-closed
image conflict. Every warn-only, "still registers" and "exported digest" statement about
`IDX_ANALYSIS_IMAGE` (section 0, C4, procedure 5, the failure tables, section 11 and this
appendix) now states fail-closed behavior, re-observed offline on `main` and on the
combined branch, including that an image conflict leaves chart delivery off with no
chart line once #148 is in. New: the C3a off probe at G2 (D7); D1, D2, D4, D5, D6 and D7
moved to a dated Decided list; procedure 5b's launchd prune job (D6) and its one-shot
WhatsApp trial with immediate rollback (D5); the approved merge order; section 11
re-measured on `chore-phase-integration-3`.

Review fix of 2026-11-04 (round three, review of `2c9d933`): two findings confirmed.
(1) Procedure 5b copied #148 `6a27dca`'s shorter launchd job commands and installed the
job before `install.sh`; #148 `a5016be` (pushed before this file's `f0978c8`) has the
full §5b install (branch and venv precheck, dry `prune`, `test ! -e`, `mkdir -p`,
`chmod 644`, `grep -c __REPO__`), a four-line verify and an uninstall that ends with
"Could not find service", and installs the job as §7 step 2. §9's Enable, failure row
and Rollback and checklist step 9 now follow that order and quote those blocks
verbatim. (2) The "current" heads of #148, #150, #153 and #155 were stale, and #148 had
already merged `main` with the `tool.py` resolution. Section 1, G1, procedures 1, 4 and
5b, section 11 and the checklist now name `a5016be`, `757c212`, `68cbf24` and `8a7fc34`,
and section 11 was rebuilt and re-measured on `chore-phase-integration-4`; the
`chore-phase-integration-3` results are labelled as measured at the older heads.

Update of 2026-11-04 (the chart trial's immediate rollback; owner requirement of
2026-11-04): `main` `c62ca83` (#159, `README.md` only) merged into this branch.
Procedure 5b's trial is now #148 `ef3bb25`'s `docs/CHART_DELIVERY.md` §7, quoted
verbatim (checked by script against `origin/wo-030-chart-delivery`): one trial turn,
then the rollback at once after completion or failure without waiting for the owner,
with both `IDX_CHART_DELIVERY` and `IDX_ANALYSIS_TOOL` off, the step 7 checks and the
record; keeping delivery on is a later, separately approved step 9. The step 2 verify
now carries #148's "(never exited)" re-check, and the uninstall is #148's guarded block.
Removed as superseded: the second "Send that chart again" turn and the expiry wait, the
"roll back 5b only; 5 stays on" actions, the "fix and redo step 2" path, and every
"unless the owner approves keeping delivery on" (the trial now always rolls back). The
failure table, G1/P2, the checklist, the open decisions and D5 follow that. The merge
order now says #147 merges before #155, because #155 adapts #147's test file; "#147 at
any time" was wrong. Heads re-read with `gh`: #148 `ef3bb25`, #150 `926dabf`, #155
`1409184` (sections 1, 4, 7, 9 and 11).
