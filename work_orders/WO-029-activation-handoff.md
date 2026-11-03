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
