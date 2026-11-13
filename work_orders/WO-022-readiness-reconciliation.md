# WO-022 — Readiness reconciliation after the 2026-11-02 merges

**Driver:** agent (human reviews the PR and decides each historical PR's disposition)
**Depends on:** WO-017 Phase C, WO-018, WO-020, WO-021 (PRs #134–#141, all merged)
**Estimated effort:** 3–4 hours, documentation only

## Objective
Make the repository's readiness records match what is actually true after PRs #134–#141
merged. The records should separate **merged**, **installed**, **enabled** and
**live-verified**, carry the unique evidence of four unmerged WO-018 evidence PRs onto
main, and give a concrete acceptance matrix for Phase 1 (remarks enrichment) and Phase 2
(bounded analysis).

## Why
STATUS.md's ladder was written while #135–#141 were in review, and its "Built" and
"Integrated" rungs do not say whether an opt-in switch is on. A reader could take
"merged" for "available". Four WO-018 PRs hold run evidence that main never received,
and one place should say what each remaining capability needs, from whom and with what
proof.

## Inputs
- `docs/STATUS.md`, `docs/CAPABILITY_ROADMAP.md`, `docs/START_HERE.md`,
  `docs/EVIDENCE_LOG.md`.
- `docs/RELEASE_WO021_SEARCH.md`, `docs/RELEASE_WO017_ANALYSIS.md`,
  `docs/ENRICHMENT_REFRESH_PREFLIGHT.md`, `docs/ENRICHMENT_*.md`.
- `work_orders/WO-017-bounded-analysis.md`, `WO-018-remarks-enrichment.md`,
  `WO-020-measurement.md`, `WO-021-enrichment-integration.md`.
- The switches in code: `IDX_ENRICHMENT_STORE` (`enrichment/effective_store.py`),
  `IDX_FEATURE_BADGES` (`mcp_server/server.py`), `IDX_ANALYSIS_TOOL`
  (`analysis/tool.py`), `IDX_ANALYSIS_IMAGE` (`domain/analysis_worker.py`). Also the
  `idx` skills list in `config/openclaw.idx.json5` and the pending row in
  `docs/ROUTING.md`.
- `git show origin/wo-021-recommend-design:docs/RECOMMEND_FEATURES_DECISION.md`, from an
  unmerged branch with no PR.
- PRs #116, #126, #129 and #132 (`gh pr view`, `gh pr diff`), and `git log -S` over
  main.

## In scope
1. This work order.
2. A dated post-merge section in STATUS.md with the four rungs. Short pointers in
   CAPABILITY_ROADMAP.md's checkpoint and START_HERE.md's "where we are". No older dated
   text is deleted or reworded. The superseded STATUS ladder gets one added line saying
   so.
3. Carry the unique content of PRs #116, #126, #129 and #132 onto main:
   - verbatim, under the original date and with an attribution line;
   - in historical files whose headers mark what later evidence superseded;
   - their original figures are not altered.
4. `docs/ACCEPTANCE_MATRIX.md`.
5. Append-only EVIDENCE_LOG entries: the carried #116 entry and this reconciliation.

## Out of scope
- Any code, test, skill, config, eval case, gate, guard, CI or `.gitignore` change.
- Editing another work order's Status section. WO-017, WO-020 and WO-021 still say "in
  review"; the stale list below records that.
- Closing, merging, commenting on, labelling or modifying PRs #116, #126, #129 and #132
  or their branches.
- Installing, enabling, restarting, or any model, paid or WhatsApp run.
- The work of WO-023 to WO-029 (planned, this queue): shared enrichment access, badge and
  recommendation-explanation presentation, saved feature searches, the omission-audit
  pilot, analyst routing and channel integration, measurement expansion, and the
  activation handoff.
- Merging the recommendation experiments on `wo-021-recommend-design`.

## Files expected to change
- `work_orders/WO-022-readiness-reconciliation.md` (new).
- `docs/ACCEPTANCE_MATRIX.md` (new).
- `docs/ENRICHMENT_CARRIED_EVIDENCE.md` (new).
- `docs/ENRICHMENT_DEV_RESULTS.md` (new; verbatim from PR #116 under a header).
- `docs/ENRICHMENT_V2_DEV_RESULTS.md` (new; verbatim from PR #126 under a header).
- `docs/STATUS.md`, `docs/CAPABILITY_ROADMAP.md`, `docs/START_HERE.md` (additions only).
- `docs/EVIDENCE_LOG.md` (append only).

## Interfaces and contracts
None change. The rung definitions are documentation and add no runtime switch.

## Implementation requirements
1. **Enabled** means the opt-in switch is on in the serving configuration:
   - `IDX_ENRICHMENT_STORE` set;
   - `IDX_FEATURE_BADGES=1`;
   - `IDX_ANALYSIS_TOOL=1` with a pinned `IDX_ANALYSIS_IMAGE`;
   - for a skill, its name in the agent's skills list.
2. No rung is claimed without evidence. As of 2026-11-02, no new capability is installed,
   enabled or live-verified.
3. Every carried block passes two checks:
   - it is byte-identical to the PR's added text (checked by a containment test during
     authoring);
   - it is preceded by "Carried from PR #N, originally recorded YYYY-MM-DD".
4. Superseded figures are labelled as superseded and never edited.
5. Each acceptance-matrix claim names its source on main, or names the branch for
   unmerged work.
6. Public text holds aggregates only: no listing keys, remarks, labels, predictions or
   private file contents.

## Safety requirements
- No data in the repository (rule 1).
- No handbook text (rule 2).
- No people or contact details (rule 3).
- No deletion, spending or gate edits (rule 4).
- EVIDENCE_LOG stays append-only (AGENT_RULES §6).
- The private store and `.env` were checked only for existence and line counts; no
  values or rows were read.

## Tests required
None new; this is documentation only. Run the doc-reading tests and the full offline
suite to show nothing regressed.

## Acceptance criteria
- STATUS.md has a dated post-merge section with the four rungs, and its earlier text is
  intact.
- CAPABILITY_ROADMAP.md and START_HERE.md point to it without losing older dated text.
- Every unique fact from #116, #126, #129 and #132 is on main, verbatim and attributed,
  and each superseded figure is labelled.
- `docs/ACCEPTANCE_MATRIX.md` covers every capability listed in the task, with merged
  state, remaining implementation (owner WO), operator actions, owner decisions and the
  evidence tier.
- EVIDENCE_LOG is only appended to.
- Content gates, Ruff and the full offline suite pass. CI is green on the PR.

## Verification commands
```
git diff --stat origin/main...HEAD          # docs/ and work_orders/ only
git diff origin/main...HEAD -- docs/EVIDENCE_LOG.md | grep '^-[^-]'   # expect nothing
ruff check . && ruff format --check .
MYSQL_HOST= .venv/bin/python -m pytest -q -x -p no:cacheprovider
```

## Deliverables
- The files above.
- A disposition recommendation for each historical PR (below).
- A PR into main, left unmerged.

## Stop conditions
- A historical PR's figure contradicts main in a way that is not a supersession: record
  both, flag it, and do not choose.
- Any rung would need evidence that only a live or paid step can produce.
- A required edit falls inside another work order's Status section.

## Historical PR reconciliation (inspected 2026-11-02)

All four are open, unmerged, conflicting with main, and touch only documentation. None of
their head commits is contained in main, and `git log -S` finds none of their unique
figures in main's history.

| PR | What it records | Already on main | Unique, now carried | Recommendation |
|---|---|---|---|---|
| #116 (draft), `wo-018-dev-evidence` @ `aafb442`, 2026-10-27 | First dev extraction under exact-span scoring | 47.7% exact-span micro F1, per-facet exact-span gold, predicted and F1 (`ENRICHMENT_OVERLAP_DEV.md`, EVIDENCE_LOG) | Run record (100 requests; 424,460 in and 43,522 out tokens; 11 diagnostics in 10 remarks); exact precision and recall; categorical and numeric splits; macro F1; per-facet precision and recall; polarity table; disagreement buckets; evidence-log line | **Close as superseded after this PR merges.** Unique content is carried verbatim in `docs/ENRICHMENT_DEV_RESULTS.md` and in `docs/ENRICHMENT_CARRIED_EVIDENCE.md` § PR #116, plus an appended EVIDENCE_LOG line. Keep the branch |
| #126, `wo-018-v2-dev-results` @ `11735ad`, 2026-10-28 | Sonnet versus Haiku v2 dev comparison | Sonnet v2 94.69% and its per-facet column (`ENRICHMENT_V21_DEV_RESULTS.md`, identical values) | Haiku v2 93.85% and per-facet scores; the 0.84-point gap; token and miss rows for both models | **Close as superseded after this PR merges.** Carried in `docs/ENRICHMENT_V2_DEV_RESULTS.md` and `ENRICHMENT_CARRIED_EVIDENCE.md` § PR #126. Its "meets the three-point rule" was overtaken by the v2.1 decision. Keep the branch |
| #129, `wo-018-tranche1-results` @ `5576b70`, 2026-10-29 | First 2,000-row Message Batches tranche | Only the 324 v1 rows and their 13 diagnostics | The whole tranche record: 1,000 + 676 requests, all 1,676 successful; 0.66% and 1.2% diagnostic rates; tranche usage | **Close as superseded after this PR merges.** Carried in `ENRICHMENT_CARRIED_EVIDENCE.md` § PR #129. The completion totals cover these rows. Keep the branch |
| #132, `wo-018-extraction-closeout` @ `669a9f3`, 2026-10-29 | Completed extraction | Results, provenance, usage totals and console figures (WO-018 source-audit paragraph, `21ac352`, 2026-10-30) | Dated completion statement; 0.858% (471 of 54,888); token-based estimate $89.66469020 | **Close as superseded after this PR merges.** The remainder is carried in `ENRICHMENT_CARRIED_EVIDENCE.md` § PR #132. Keep the branch |

No PR needs to stay open. Each records past runs whose unique facts are now on main.
Merging any of them would conflict and would put "current" wording ("remains undecided",
"stays paused") into WO-018's Status long after it stopped being true. Closing is the
owner's action. A closing comment linking this PR is enough, and the branches stay as the
original record (closing a PR does not delete its branch).

No contradiction was found that is not a supersession. One coincidence is labelled in the
carried file: #132's token-based estimate ($89.66469020) and the console delta ($89.66)
round to the same dollars but are different measures.

## Records found stale (not edited here)
- `work_orders/WO-021-enrichment-integration.md`:
  - the header says offline acceptance is "in review" (#135 is merged);
  - "Increment 2: card badges (built 2026-11-02, off by default, in review)" (#136 is
    merged).
- `work_orders/WO-017-bounded-analysis.md` Status 2026-11-02: "in review" (#138 is
  merged).
- `work_orders/WO-020-measurement.md` Status 2026-11-02: increments 1 and 2 "in review"
  (#139 and #140 are merged).
- `docs/RELEASE_WO021_SEARCH.md` step 3.1, "Merge the reviewed PRs": done; the rest of
  the handoff still applies.
- STATUS.md "Capability readiness ladder, 2026-11-02": "in review" for #135–#141. It now
  carries a superseded line and stays as written.
  (Note 2026-11-11: that section, and the "Post-merge readiness, 2026-11-02" section this
  work order added, are now in
  [STATUS_HISTORY](../docs/STATUS_HISTORY.md#capability-readiness-ladder-2026-11-02),
  moved verbatim when STATUS.md became the central plan.)
- CAPABILITY_ROADMAP.md, first 2026-11-02 update: "#135 in review", "#139, #140 in
  review". A post-merge paragraph follows it.
- START_HERE.md §4: its newest dated paragraph was from 2026-10-25/26. A 2026-11-02
  pointer now leads the section.

The work-order Status fixes belong in each WO's own file, by its owner or under the WO
that next touches it (WO-023 to WO-029, planned).

## Status
2026-11-02: done on branch `wo-022-readiness-reconcile`; PR open for review, not merged.

- **STATUS.md:** post-merge section with merged, installed, enabled and live-verified.
  The superseded ladder is marked and the 2026-10-26 audit is untouched.
- **Pointers:** short pointers added to CAPABILITY_ROADMAP.md and START_HERE.md.
- **Acceptance matrix:** `docs/ACCEPTANCE_MATRIX.md` has 14 rows, with operator steps
  taken from the two release handoffs and the five recommendation decisions from the
  branch record.
- **Carried evidence:** the four historical PRs' unique evidence is in
  `docs/ENRICHMENT_CARRIED_EVIDENCE.md`, `docs/ENRICHMENT_DEV_RESULTS.md` and
  `docs/ENRICHMENT_V2_DEV_RESULTS.md`. Each carried block was checked byte-for-byte
  against the PR text.
- **EVIDENCE_LOG:** two entries appended.
- **Not changed:** no code, gate, config or other WO's Status. No paid call, install,
  restart or `.env` change.
- **Readiness checks** (existence and line counts only, no values or rows read):
  - the effective store file exists in the main checkout's gitignored `data/`, dated
    2026-11-02;
  - the main checkout's `.env` has no non-empty `IDX_ENRICHMENT_STORE` and no
    `IDX_FEATURE_BADGES=1` or `IDX_ANALYSIS_TOOL=1` line.
- **Not verified here:**
  - whether the running gateway process has the same environment as that `.env`;
  - whether the main checkout is exactly the revision the gateway serves.
  Both need the owner's probe.
- **Combined review (2026-11-02, before merge):** reviewed against open PRs #142, #144,
  #145 and #146. The acceptance matrix's P2 step 4 and turn-off line had prescribed a hand
  edit of the `idx` skill list and template, which #146 replaces with an install-time
  merge from the `.env` switch. Following the old step after #146 landed would have made
  the skill always on and broken #146's fragment test. Both now point to #146, as does
  the "Enabled" definition. Also added: WO-030 for chart delivery, both owner decisions of
  2026-11-02, and a change-log map of each open PR to the rows it moves. No claim moved
  up a rung, and STATUS.md is unchanged.
- **Verification:** Ruff clean (no Python touched). The full offline suite
  (`MYSQL_HOST= … pytest -q -x -p no:cacheprovider`) is recorded in the EVIDENCE_LOG
  entry for this WO.
