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
  instructions, runs the exported digest, and only warns. C4, the section 0 settings
  note, procedure 5 (install note, offline acceptance, failure table: now two rows) and
  the section 11 row were rewritten with the outputs observed offline on the combined
  branch: install in a temp `HOME` and state directory with stub `openclaw`/`node`, and
  an in-process start (`register_analysis_tool()` then `log_start()`).
- **Test** (`2998f43`): `test_a_switch_conflict_unregisters_but_an_image_conflict_only_warns`
  in `tests/test_phase_integration.py` (4 cases) replaces the switch-only conflict
  test. It pins existing `main` behavior (a docs fix, not a behavior fix), so it passes
  on `main` `cbad756`: 4 passed in a detached scratch worktree. To show that it would
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
