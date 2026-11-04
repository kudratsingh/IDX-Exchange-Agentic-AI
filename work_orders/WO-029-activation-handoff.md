# WO-029 — Activation, verification and rollback handoff for Phase 1 and Phase 2

**Driver:** agent drafts and finalizes. The owner merges, installs, enables and runs every
live check.
**Depends on:**
- #142 (WO-023 shared enrichment access);
- #143 (WO-022 acceptance matrix);
- #144 (WO-026), #145 (WO-028);
- #146 (WO-027 analysis integration);
- WO-024 (recommendation explanations), WO-025 (saved feature searches), WO-030 (chart
  delivery).

This work order is finalized last.
**Estimated effort:** planning input only, not a commitment

## Objective
One operator document, `docs/ACTIVATION_HANDOFF.md`, gives a separate, attributable
procedure for each capability:
1. feature search;
2. card badges;
3. recommendation explanations;
4. saved feature searches;
5. bounded analysis, with 5b chart delivery.

Each procedure covers the state ladder, prerequisites, operator commands, offline
acceptance, the smallest live check, failure handling and rollback with a residue check.
The release order is: #142 before its consumers, Phase 1 accepted before Phase 2, one
switch per restart.

## Why
The two existing handoffs (`RELEASE_WO021_SEARCH.md`, `RELEASE_WO017_ANALYSIS.md`) each
cover one feature. Neither says how the features are sequenced, how a failure is
attributed when several switches exist, or how to undo each step without touching the
others.

## Inputs
- `docs/START_HERE.md`, `docs/STATUS.md`, `docs/RELEASE_WO021_SEARCH.md`,
  `docs/RELEASE_WO017_ANALYSIS.md`, `docs/DEMO_RUNBOOK.md`, `docs/BASELINE_ACCEPTANCE.md`.
- `scripts/install.sh`, `scripts/openclaw_merge_config.py`,
  `scripts/install_runtime_policy.py`, `scripts/demo_preflight.py`,
  `scripts/refresh_preflight.py`, `.env.example`.
- From open branches, read with `git show`:
  - `docs/ACCEPTANCE_MATRIX.md` (#143);
  - `work_orders/WO-023-enrichment-access.md` and `src/idx_agent/enrichment/access.py`
    (#142);
  - `work_orders/WO-027-analysis-integration.md`, `config/openclaw.analysis.json5`,
    `scripts/install.sh` and `docs/RELEASE_WO017_ANALYSIS.md` (#146).

## In scope
1. `docs/ACTIVATION_HANDOFF.md`: the six procedures, common operator steps, release
   gates, departures from the earlier handoffs, a combined-acceptance section, an
   offline rehearsal record and a placeholder table.
2. Offline failure rehearsal in temp directories:
   - a missing or invalid store;
   - switch typos;
   - conflicts between `.env` and the process environment;
   - an unavailable worker;
   - `install.sh` on and off in a throwaway home.
3. Finalization, after WO-024, WO-025 and WO-030 are complete: replace every **TO
   FINALIZE** marker with exact commands and the outputs observed on the combined
   branch.

## Out of scope
- Running any operator command: `install.sh` against the real home, `openclaw`, a gateway
  restart, `consent.sh`, Docker builds.
- Reading `.env`, `~/.openclaw`, credentials or session stores.
- Any paid call or live message. Any live-DB migration.
- Editing `docs/STATUS.md`, `docs/START_HERE.md`, `docs/CAPABILITY_ROADMAP.md` or
  `docs/EVIDENCE_LOG.md` (owned by #143).
- Editing the feature release handoffs (owned by their PRs).
- Code changes. Merging any PR.

## Files expected to change
`docs/ACTIVATION_HANDOFF.md` (new), this file.

## Interfaces and contracts
None changed. The procedures reference these, exactly as the code defines them:
- the switches `IDX_FEATURE_BADGES`, `IDX_FEATURE_EXPLANATIONS` (#149),
  `IDX_FEATURE_SAVED_SEARCHES` (#150), `IDX_ANALYSIS_TOOL` (#146) and
  `IDX_CHART_DELIVERY` (#148), and the settings `IDX_ENRICHMENT_STORE`,
  `IDX_ANALYSIS_IMAGE` and `IDX_CHART_DIR`;
- `FeatureAccess.readiness()` and `bind()` (#142);
- `register_analysis_tool()` and `analysis.tool.switch_state()` (#146);
- `python -m idx_agent.alerts.run --dry-run` and its exit code 5 (#150);
- `python -m idx_agent.analysis.delivery prune --all` (#148).

## Implementation requirements
1. Every capability has its own procedure with all seven parts.
2. Each current state is stated from evidence and never overstated: merged, installed,
   enabled and live-verified are separate claims.
3. Commands that only the operator may run are marked as operator steps. Consent-token
   commands use `! scripts/guards/consent.sh …`.
4. Rollback uses edits, not appended lines, because the first `.env` line wins. Each
   rollback names its residue and how to check it.
5. Unfinished parts are marked **TO FINALIZE**, never guessed.

## Safety requirements
- Public text holds aggregates only: no listing keys, addresses, remarks or phone
  numbers. Probes print counts or status codes.
- No relaxed invariant. Approval before delivery and the paid gate are unchanged.

## Tests required
None new (docs only). The rehearsal reuses existing tests and records their counts.

## Acceptance criteria
- Draft: both files exist. Each procedure has all seven parts or an explicit **TO
  FINALIZE** marker. The rehearsal record lists what ran and what it showed. Gates and
  ruff are clean, and the full offline suite is unchanged from `main`.
- Final:
  - no **TO FINALIZE** marker remains;
  - every expected output was observed on the combined branch;
  - Mac and CI evidence are stated separately.

## Verification commands
```sh
grep -n "TO FINALIZE" docs/ACTIVATION_HANDOFF.md      # draft: the list below; final: none
.venv/bin/python -m pytest -q
```

## Deliverables
The handoff document and this work order.

## Stop conditions
- A procedure would need a relaxed invariant, a live change by the agent, or a decision
  only the owner can make. Record it, keep the conservative default and continue.

## Status

2026-11-04 (round three, review fix of `2c9d933`): **ready for review**, not merged.
Two review findings reproduced and fixed; nothing installed, enabled, loaded, restarted
or live-tested, no paid call, no message, no `.env`, `~/.openclaw` or private file read.
- **D6 commands re-synced with #148.** #148 `a5016be` (pushed 06:42Z, before this
  branch's `f0978c8`) has a longer §5b install (branch/venv precheck, dry `prune`,
  `test ! -e`, `mkdir -p`, `chmod 644`, `grep -c __REPO__` = 0), a verify of `path =`,
  `run interval`, `runs =` and `last exit code = 0`, and an uninstall of bootout, `rm`,
  then `launchctl print` = "Could not find service"; its §7 installs the job as step 2,
  after `install.sh`. The handoff had copied `6a27dca`'s shorter blocks as step 1 (no
  `mkdir -p`). Procedure 5b's Enable (steps 1-3 in #148's order), failure row, Rollback
  and checklist step 9 now follow #148 and quote its §5b blocks verbatim, extracted from
  `a5016be` by script. Re-observed offline at the combined head with #148's template:
  render, `plutil -lint` OK, `grep -c __REPO__` 0, mode 644; the dry `prune` in
  `env -i` with a temp `HOME` printed `removed 0 chart file(s)`, exit 0. Nothing loaded.
- **Heads corrected.** #148 `a5016be`, #150 `757c212`, #153 `68cbf24` and #155
  `8a7fc34` replace the stale `6a27dca`, `290b494`, `b4af2f3` and `de6ee83` in
  section 1, G1, procedures 1, 4 and 5b, section 11 and the checklist. #148 already
  merged `main` `27c4ef1` (`3c84575`); its `tool.py` equals the old combined resolution
  (`git diff 1525494 a5016be -- src/idx_agent/analysis/tool.py` empty), so the "must
  merge `main` with the `tool.py` resolution" steps are gone. #157 is noted as not part
  of the D7 order.
- **Combined rebuilt** as `chore-phase-integration-4` (pushed, no PR): `main` `48b74ab`
  + #148 `a5016be`, #150 `757c212`, #153 `68cbf24` (EVIDENCE_LOG conflict with `main`,
  both entries kept), #147 `2c9d933` = `969b739`; then #155 `8a7fc34` (clean) =
  `07f2060` and the planned fixture switch = `988a261`. Mac at `969b739`: ruff clean
  (449 files); 5,005 passed, 130 skipped with `IDX_ANALYSIS_IMAGE` unset and exported;
  `tests/test_phase_integration*.py` 39 passed; `ci` evals 251 cases, 84 pass, 0 fail,
  167 skipped; per procedure 168, 43, 105, 110, 218 + 2 skipped, 129. At `07f2060` the
  five affected files: 49 failed, 85 passed, 7 errors. At `988a261`: ruff clean (455
  files); 5,074 passed, 130 skipped in both modes; `tests/test_phase_integration*.py` 39
  passed.
  CI: `969b739` 41795446978 (push) success, 5,061 passed, 74 skipped, fixture DB 73
  passed, 1 skipped, `ci` evals 251 pass; `988a261` 41795976472 (push) success, 5,130
  passed, 74 skipped, 73 passed, 1 skipped, 251 pass. #155's own `pull_request` run
  41793753209 fails with the 7 expected #154 setup errors until it merges `main` and
  adapts. The C3a probe outputs and the C4 image-conflict observations
  (`install.sh` line, 7 tools, base instructions, one `health` warning; with
  `IDX_CHART_DELIVERY=1`, charts off and no chart line) reproduced at `969b739`. The
  `chore-phase-integration-3` record below stays as measured at the older heads.

2026-11-03 (owner decisions, round three; #156 merged at `27c4ef1`): superseded in its
heads, the combined measurement's currency and the D6 command blocks by the entry
above. **ready for review**, not merged. `main` `27c4ef1` merged into this branch with a merge commit
(`2990acb`, clean). Still nothing installed, enabled, restarted or live-tested, no paid
call, no message, no `.env`, `~/.openclaw` or private file read; WhatsApp chart delivery
remains **UNVERIFIED**.
- **Test** (`5f61917`): `test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`
  is renamed `test_a_switch_or_image_conflict_unregisters_and_reports`. For all four
  cases it asserts that `install.sh` refuses before writing, the server registers no
  `bounded_analysis` (7 tools, base instructions), and the problem is the one `health`
  warning and the `server_start` `analysis_switch_problem`; the image cases must be
  `IMAGE_DIFFERS`. Fail before: the old test on the merged tree (main `27c4ef1` code)
  failed its 2 image cases (`assert False is ('image' == 'image')`). Pass after: 17
  passed in `tests/test_phase_integration.py`, with `IDX_ANALYSIS_IMAGE` unset and
  exported.
- **Handoff, fail-closed image conflict.** Section 0, C4, procedure 5 (install note,
  offline acceptance, failure row), section 11, section 10 and Appendix B now state
  that an `IDX_ANALYSIS_IMAGE` conflict fails closed like a switch conflict (#156).
  Re-observed offline on `main` `27c4ef1` (extracted tree, temp `HOME` and state
  directory, stub `openclaw`/`node`, in-process start): `install.sh` exit 1 with the new
  `IMAGE_DIFFERS` line and no state directory; 7 tools, base instructions, one `health`
  warning, `server_start` without `bounded_analysis`; the same for an exported empty
  value and with the switch exported too. On the combined branch with
  `IDX_CHART_DELIVERY=1` in `.env`: chart delivery off, `chart_delivery_problem()`
  `None`, only the analysis line reported.
- **Round-three decisions.** D7 approved: the merge order is recorded (#144 → #154;
  #145, #148 after it merges `main` with the `tool.py` resolution, #150, #152, #153 in
  any order, both `EVIDENCE_LOG.md` entries kept for #152/#153; #147 any time; #155
  last, adapting fixtures), and the new C3a off probe at gate G2 shows
  `bounded_analysis` absent, `IDX_ANALYSIS_TOOL` off and `IDX_CHART_DELIVERY` off
  (`False False False None None`, observed offline in temp directories, with the
  failing outputs it must stop on). D1 approved (C2 is the owner's step). D2: keep the
  current badge look. D4: keep the conservative defaults. D6 approved: the launchd
  prune job is installed by the owner in procedure 5b's Enable step 1 with the exact
  `docs/CHART_DELIVERY.md` §5b commands (the proposal rendered in scratch passes
  `plutil -lint`; nothing loaded) and removed in the rollback. D5 approved for one
  separately authorized WhatsApp trial: 5b's live check is now a one-shot trial that
  needs its own activation approval and paid grant and is rolled back at once unless
  the owner approves the result. Resolved decisions moved to a dated Decided list.
- **Combined** `chore-phase-integration-3` (pushed, no PR): `main` `27c4ef1` + #144
  `f85e35c`, #154 `65b53cc`, #145 `ee1c20f`, #148 `6a27dca`, #150 `290b494`, #152
  `7c0fea7`, #153 `b4af2f3`, #147 `5f61917` = `1525494`; conflicts only in `tool.py`
  (#148 vs #156, the prepared resolution) and `docs/EVIDENCE_LOG.md` (#152/#153, both
  kept). Mac: ruff clean (449 files); full suite 5,002 passed, 130 skipped, also with
  `IDX_ANALYSIS_IMAGE` exported; `tests/test_phase_integration*.py` 39 passed; `ci`
  evals 251 cases, 84 pass, 0 fail, 167 skipped. Per procedure: 168, 43, 105, 110,
  218 + 2 skipped, 129. CI 41786303812 (push) success: 5,058 passed, 74 skipped; fixture
  DB 73 passed, 1 skipped; `ci` evals 251 pass. Then #155 `de6ee83` (clean) and the
  planned fixture switch = `88f8f12`: before the switch the five affected files gave 49
  failed and 7 errors; after it, ruff clean (455 files), full suite 5,071 passed, 130
  skipped in both modes, `tests/test_phase_integration*.py` 39 passed. CI for
  `88f8f12`: 41789122009 (push) success, 5,127 passed, 74 skipped; fixture DB 73
  passed, 1 skipped; `ci` evals 251 pass.
- While this was in progress the owner merged #144, #154, #145 and #152 (`main`
  `48b74ab`); it was merged into this branch (`aa0a2f3`, clean) and the state rows,
  G1, section 11 and the checklist mark them done. Their heads were already in the
  combined branch.
- This branch, Mac, before that merge: ruff clean (422 files); full suite 4,487 passed,
  130 skipped, with `IDX_ANALYSIS_IMAGE` unset and again exported; after it, ruff clean
  (436 files), 4,673 passed, 130 skipped in both modes. This PR's CI is reported in
  the PR.

2026-11-03 (D-032 and WO-035): superseded by the entry above. **ready for review**, not
merged. `main` `32cd727` (#151) merged into this branch with a merge commit;
`docs/EVIDENCE_LOG.md` is identical to `main`'s (this branch never changed it). Still
nothing installed, enabled, restarted or live-tested, no paid call, no message, no
`.env`, `~/.openclaw` or private file read.
- **v5 rebuild prerequisite re-pointed.** Procedure 1's first prerequisite said the v5
  rebuild belongs to WO-032 and implied today's builder produces a v5 store. WO-032 is
  closed as not applicable (owner decision D-032, option a; the 321 description-less
  listings stay unknown by design), and the builder on `main` checks only v4 inputs. The
  prerequisite now names WO-035 (#155, `21e84ad`): WO-035 merged; the owner proposes,
  reviews and freezes the v5 manifest as `data/enrichment/effective-store-v5-manifest.json`
  beside the unchanged v4 manifest; runs `--policy v5 --dry-run` and then
  `scripts/build_enrichment_effective_store.py --policy v5` from the serving checkout;
  checks with `open_store` that `StoreInfo` shows `policy_version='v5'` and
  `listing_count=54888`; re-records the store info line and the Pasadena `solar` probe.
  A builder refusal stops. Rollback points `IDX_ENRICHMENT_STORE` back at the kept v4
  file. The enable line names the v5 file. Every WO-032 extraction, paid and token step
  is gone from the handoff and the smallest operator checklist (renumbered, 8 steps).
- **Merge order (section 2 and 11).** WO-035's count hardening makes the synthetic
  stores in `tests/test_phase_integration.py` (6 tests), #148's, #150's and #154's stop
  opening once #155 is on `main`. WO-035 plans that the other PRs merge first and #155
  then switches their tests to its helper, which is not on `main`. This PR's tests are
  therefore unchanged, and the handoff states the order: #144, #145, #147, #148, #150,
  #152 (any order), #154 after #144, then #155; #153 any time. Putting #148 before #155
  replaces the earlier advice to hold it for G4; holding it stays an owner choice (D7)
  and then needs the helper change in #148.
- New owner decision D7 (WO-035 merge order, v5 manifest freeze, v5 build).

2026-11-03 (review follow-ups): **ready for review**. Still nothing installed, enabled,
restarted or live-tested; no paid call, no message, no `.env` or `~/.openclaw` read, no
live alerts DB; WhatsApp chart delivery remains **UNVERIFIED**.
- **C4 corrected.** The handoff said an `IDX_ANALYSIS_TOOL` conflict and an
  `IDX_ANALYSIS_IMAGE` conflict both register nothing. From the code on `main`
  (`analysis.tool.switch_state`, `register_analysis_tool`, `install.sh` step 3c), only
  the switch conflict does that. `install.sh` refuses both before writing anything
  (exit 1, no state directory). For a switch conflict the server registers no
  `bounded_analysis`, keeps the base instructions, and reports
  `analysis_switch_problem` in `health` and `server_start`. For an image conflict
  (switch on in `.env`) the server still registers the tool and the analysis
  instructions, runs the exported digest, and only warns (superseded by #156, owner
  decision 2026-11-03: an image conflict now fails closed; see the round-three entry).
  C4, the section 0 settings
  note, procedure 5 (install note, offline acceptance, failure table: now two rows) and
  the section 11 row were rewritten with the outputs observed offline on the combined
  branch: install in a temp `HOME` and state directory with stub `openclaw`/`node`, and
  an in-process start (`register_analysis_tool()` then `log_start()`).
- **Test** (`2998f43`): `test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`
  in `tests/test_phase_integration.py` (4 cases) replaces the switch-only conflict
  test (renamed `test_a_switch_or_image_conflict_unregisters_and_reports` in `5f61917`
  after #156). It pins existing `main` behavior (a docs fix, not a behavior fix), so it
  passes on `main` `cbad756`: 4 passed in a detached scratch worktree. To show that it would
  have caught the old text: with `switch_state` changed in scratch to return off for
  an image conflict (the handoff's claim), 2 failed (`assert False is ('image' ==
  'image')`) and 2 passed.
- **Procedure 4** (#150 `c40eadb`): dry-run expectations follow the parity fix. Exit 0 is
  expected only while the active data is level with the snapshot. Exit 5
  `snapshot_behind` and exit 4 (key cap) appear in the dry-run as in the job. The
  exit-2 exception (recipient or journal settings are never read by a dry-run) is
  stated. These outputs were observed on synthetic stores on the combined branch.
- **Procedure 5b** (#148 `6a27dca`): the 20-chart cap now holds across `idx` processes
  (flock on `.idx-charts.lock`, 2 s wait per writer, then `dir_busy`). The in-process
  queueing caveat, the new reason codes, the lock file in `ls -la`, and a rollback
  residue of "empty, or only the lock file" are stated. Observed in a temp directory on
  the combined branch.
- Heads, CI and counts refreshed; stale CI rows removed (#150 `7831158`, #148
  `ad5e46c`, #147 `e500d18`, combined `fb68ea5`).
- Combined `chore-phase-integration-2` `30ff289` (merged `c40eadb`, `6a27dca`,
  `2998f43`; clean). Mac only: ruff clean (437 files); full suite 4,931 passed, 130
  skipped, also with `IDX_ANALYSIS_IMAGE` exported; `tests/test_phase_integration*.py`
  39 passed; offline `ci` evals 251 cases, 84 pass, 0 fail, 167 skipped (no database).
  Per procedure: 168, 43, 103, 110, 212 + 2 skipped, 129.
- CI (separate): #147 `2998f43` runs 41756755164 (push) and 41756760635
  (pull_request) success, 4,535 passed, 74 skipped, fixture DB 73 passed, 1 skipped.
  Combined `30ff289`: 41757498036 (push), success: 4,987 passed, 74 skipped; fixture DB 73 passed, 1 skipped; `ci` evals 251 cases, 251 pass, 0 fail. This docs commit's
  CI is reported in the PR.

2026-11-03 (refresh against the final heads): superseded by the entry above. `main` `cbad756`
(#142, #143, #149, #146 merged) was merged into this branch with a merge commit
(`06e4955`, no conflicts). Still nothing installed, enabled, restarted or live-tested;
no paid call, no message, no `.env` or `~/.openclaw` read; WhatsApp chart delivery
remains **UNVERIFIED**; Phase 1 acceptance comes before Phase 2 activation.

Scope addition, at the owner's request: `tests/test_phase_integration.py` (`e500d18`),
the cross-feature acceptance checks for the features on `main`, so they live in a
reviewable PR rather than only on a scratch branch. It is ported from
`chore-phase-integration` (`d6f4759`) and narrowed to search, badges, explanations,
analyst routing, default off (hashes pinned from `cbad756`), each switch alone, all on,
stale and missing store, rollback with a temp-HOME residue check, and env versus `.env`
for `IDX_ANALYSIS_TOOL`. 15 tests, no xfail, no skip beyond the POSIX guard. The
saved-alert and chart checks are in #150 (`tests/test_phase_integration_saved_searches.py`)
and #148 (`tests/test_phase_integration_charts.py`); both exist at those heads. These are
acceptance tests for already-merged code, not a fix, so there is no fail-before run: on
`main` they pass (Mac 15 passed, also with `IDX_ANALYSIS_IMAGE` exported; CI below).

Handoff rewritten against the final heads (#150 `7831158`, #144 `9da8062`, #145
`ee1c20f`, #148 `ad5e46c`): state ladder with today's state, activation commands with
`install.sh` outputs observed in temp HOMEs, rollback and residue, the saved-search
deferral and lapse fixes, chart switch agreement, the chart expiry guarantee exactly as
#148 proves it (no strict-expiry claim; the launchd proposal is an owner decision), merge
order, owner decisions, and the combined results. Removed: the CI-red claims for #146
and #148, the flaky-test note, and every expected-failure (xfail) reference.

Combined branch `chore-phase-integration-2` (`fb68ea5`, pushed, no PR): `origin/main`
plus #150, #144, #145, #148 and #147 merged in that order with merge commits; no
conflicts (all pairs also merge cleanly with `git merge-tree`).
- Mac (Docker, Ollama and the database absent): ruff clean (437 files); full
  suite 4,910 passed, 130 skipped; with `IDX_ANALYSIS_IMAGE` exported 4,910 passed, 130 skipped; offline `ci` evals
  251 cases, 84 pass, 0 fail, 167 skipped (no database); all `tests/test_phase_integration*.py` together 37 passed (15 in #147's file, 6 in #150's, 16 in #148's).
- Per procedure: search 168 passed; badges 43 passed; explanations 103 passed; saved
  searches 100 passed; analysis 212 passed, 2 skipped (db); charts 120 passed.
- CI: superseded; the current runs are in the entry above and handoff section 11.

The entries below are history; their CI, xfail and conflict statements are superseded
by this one.

2026-11-02 (final): **finalized, ready for review**. No **TO FINALIZE** marker remains in
`docs/ACTIVATION_HANDOFF.md`; Appendix B records where each one was settled. Still
nothing installed, enabled, restarted or live-tested; no paid call, no message, no
`.env` or `~/.openclaw` read; WhatsApp chart delivery remains **unverified**.

Combined testing (handoff section 11), on the local integration branch
`chore-phase-integration` (`d6f4759`, pushed for reference, no PR): `main` `5432dc2`
plus #142, #143, #149, #150, #144, #145, #146 and #148 merged in that order, plus
`tests/test_phase_integration.py`.
- Conflicts: two additive hand resolutions (`format.py` `__all__` for #146 after #149;
  `pool.py`, `tests/test_db_pool.py` and `server.py` `main()` for #148). #146 needs a
  trivial rebase after #149 lands; #148 must rebase onto #146's final head.
- Mac: ruff clean (432 files); full suite 4,677 passed, 130 skipped, 3 xfailed at
  `d6f4759` (container and db tests skip here). `main`: 4,269 passed, 129 skipped.
- Cross-feature tests: 19 passed, 3 strict xfails (the chart env/.env finding). A
  cross-tree probe showed every default-off surface byte-identical to `main` except two
  additive keys in the alert job summary (#150).
- CI (separate): PR heads #142, #143, #144, #145, #149, #150 green; #146 `6df43c1` red
  (test isolation: CI exports `IDX_ANALYSIS_IMAGE`); #148 `e0a5e0d` red (flaky
  concurrent-session test). The integration branch inherits both.
- Per-procedure offline counts on the combined branch: search 168, badges 43,
  explanations 103, saved searches 79, analysis 186 passed and 2 skipped, charts 67.

Findings for the owning PRs are listed in handoff section 11. Owner decisions are D1-D4,
the chart path approval and its residual risks, and each merge, activation and paid
check.

2026-11-02 (draft): **draft, in review**, on branch `wo-029-activation-handoff` from `main`
`5432dc2`. Nothing installed, enabled, restarted or live-tested. No paid call, no
message, no `.env` or `~/.openclaw` read.

Current state recorded in the handoff (section 1):
- All six capabilities are not installed at a main revision, not enabled and not
  live-verified.
- Search (#134, #135), badges (#136) and the analysis tool (#138) are merged.
- #142 and #146 are open.
- WO-024 and WO-030 are in progress; WO-025 is not yet on a branch.
- The private store exists in the main checkout with the approved metadata. Only
  `StoreInfo` was read.

Offline rehearsal (handoff Appendix A, Mac, temp dirs, `env -i`):
- Switch parsing: `true`, `yes`, `on`, `0` and `1 # on` are off.
- Precedence: the process environment beats `.env`. Within `.env`, the first line wins,
  so appending `=0` does not roll back.
- Store reasons: `not_configured`, `missing`, `malformed`.
- Existing tests:
  - main: 117 + 41 + 108 passed (1 skipped);
  - #142 snapshot: 154 passed;
  - #146 snapshot: 150 passed, 2 skipped (`db`); its unavailable-worker cases passed.
- #146 `install.sh` in a throwaway home: on, off and typo values each gave the expected
  skill list. Rollback left an inert `openclaw.analysis.json5`.

Findings for the owner (not changed here):
1. The serving checkout is on `wo-021-recommend-design` (`74c98d1`), 24 commits behind
   main, and the venv imports from it. Installing needs decision D1.
2. `.env` first-value-wins makes "append `=0`" a silent no-op rollback.
3. `install.sh` overwrites its single `.pre-idx.bak` on every run. The handoff adds a
   dated manual backup.
4. Process-environment whitespace is handled differently: badges strip it, analysis
   does not.
5. On an empty state directory, the second `install.sh` run fails to merge the JSON5
   copy left by the first. This does not affect the owner's onboarded config.

Placeholders at the draft stage: handoff Appendix B (all settled in the final version).

2026-11-03, after #151 (owner decisions, policy v5): procedure 1 gains a first
prerequisite. The store is rebuilt under review policy v5 as a versioned migration
(WO-032) before the Phase 1 install; the store info line and the Pasadena `solar` probe
are re-recorded on the rebuilt store, and a builder refusal stops the procedure. The
smallest operator checklist gains that step after C2 and before C3. Procedure 5b's
failure table now separates `lock_unsafe` (symlink, directory, FIFO, or a file this
user can open but does not own) from `lock_unavailable` (the lock cannot be opened),
per the #148 verifier. The expected `policy_version='v4'` and `applied 14` comments
stay until the rebuilt store is observed.
