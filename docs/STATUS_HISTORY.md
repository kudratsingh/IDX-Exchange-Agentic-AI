# Status history

Dated history moved verbatim on 2026-11-11 from STATUS.md, CAPABILITY_ROADMAP.md and
AUTONOMY_LADDER.md, when the three docs were reorganized (owner rule, 2026-11-11). The
current plan and state are in [STATUS.md](STATUS.md); nothing here is current readiness.

How to read this file:
- Each moved section keeps its original heading and text, in its original order. The only
  additions are the part headings, this preamble, the index and the italic labels set
  between sections.
- "Above", "below", "this checkpoint" and "the current checkpoint" inside a moved section
  refer to its original file at the time it was written, not to this file.
- Plain-text references to `docs/RELEASE_WO021_SEARCH.md` and `docs/RELEASE_WO017_ANALYSIS.md`
  in the superseded 2026-11-02 ladder carry a `docs/` prefix that was already wrong relative
  to STATUS.md's folder; they are kept as written.
- The two "WO-042" bullets in "Remaining acceptance" were added to that section on `main`
  by #189 (merge `e1ec3ab`, 2026-11-11) and are carried here verbatim with the rest of it.
- This file is history only. Do not edit the moved text; record any new decision or plan
  change in STATUS.md.

## Index

| Date | Title (verbatim) | Original file and lines (at `e1ec3ab`) | Here |
|---|---|---|---|
| 2026-11-10 | Current checkpoint, 2026-11-10 | STATUS.md:3-46 | [link](#current-checkpoint-2026-11-10) |
| 2026-10-26 | Historical audit, 2026-10-26 | STATUS.md:48-77 | [link](#historical-audit-2026-10-26) |
| 2026-11-02 | Post-merge readiness, 2026-11-02 | STATUS.md:79-129 | [link](#post-merge-readiness-2026-11-02) |
| 2026-11-02 | Capability readiness ladder, 2026-11-02 | STATUS.md:131-155 | [link](#capability-readiness-ladder-2026-11-02) |
| about 2026-10-26 (undated) | Remaining acceptance | STATUS.md:157-208 | [link](#remaining-acceptance) |
| about 2026-10-26 (undated) | Reading order | STATUS.md:210-220 | [link](#reading-order) |
| 2026-10-26 | Deterministic relay compatibility, 2026-10-26 | STATUS.md:223-232 | [link](#deterministic-relay-compatibility-2026-10-26) |
| 2026-10-26 | Model-side preview check, 2026-10-26 | STATUS.md:234-244 | [link](#model-side-preview-check-2026-10-26) |
| 2026-10-27 | Phase 2 resumed, 2026-10-27 | STATUS.md:246-251 | [link](#phase-2-resumed-2026-10-27) |
| 2026-10-28 | Analysis worker decision, 2026-10-28 | STATUS.md:253-258 | [link](#analysis-worker-decision-2026-10-28) |
| 2026-10-27 | Phase 5 draft, 2026-10-27 | STATUS.md:260-263 | [link](#phase-5-draft-2026-10-27) |
| 2026-10-28 | Phase 2 code complete, 2026-10-28 | STATUS.md:265-270 | [link](#phase-2-code-complete-2026-10-28) |
| 2026-11-10 | Current checkpoint | CAPABILITY_ROADMAP.md:10-26 | [link](#current-checkpoint) |
| 2026-10-26 to 2026-11-05 | Historical checkpoint notes | CAPABILITY_ROADMAP.md:28-68 | [link](#historical-checkpoint-notes) |
| 2026-10-25 | Phase 0: operator sequence | CAPABILITY_ROADMAP.md:93-112 | [link](#phase-0-operator-sequence) |
| 2026-11-04/05 | Where the system is | AUTONOMY_LADDER.md:68-84 | [link](#where-the-system-is) |
| 2026-11-05 | Order of work, by level | AUTONOMY_LADDER.md:86-112 | [link](#order-of-work-by-level) |

<a id="part-1"></a>
# Part 1: moved from STATUS.md

_STATUS checkpoint as reconciled 2026-11-10 (superseded 2026-11-11 by STATUS.md "Where we are now")._

## Current checkpoint, 2026-11-10

Reconciled against `main` at `7a1fe36` (PR #187, persistent dedupe, merged) and the open PR list on 2026-11-10.
Runtime claims below use the last recorded installation and acceptance evidence,
not a new inspection of the live gateway. Dated sections below retain earlier states.

**We are completing Phase 1 activation at L1.** The audited feature store was built,
installed and enabled, but Phase 1 acceptance stopped on a factual copying error.
The replacement WhatsApp send path is merged and tested with a real-host harness;
live Cloud API setup and acceptance remain open. Phase 2 code is merged but not
live-accepted. Code completion does not mean either phase is accepted.

| Capability | Merged | Last recorded installation / enablement | Acceptance and remaining work |
|---|---|---|---|
| Core assistant and remark-feature search | Yes, including #134 and subsequent fixes | Serving revision `0b0c48c`; v5 store enabled, recorded 2026-11-06 | P1-1 to P1-3 passed exact relay; P1-4 failed when the model copied another card's year built. Session stopped; Phase 1 not accepted (#176) |
| Audited feature store | Original extraction and corrections merged; v5 builder #155 merged | 54,888-listing v5 store built and configured | Scope is exactly "policy v5; rulings applied: 8 overlay only; rulings 1-7 and 9-15 not applied to stored labels". It is not a full v5 re-read |
| Badges, shared-feature explanations and saved feature searches | Yes, including #149 and #150; recommendation order unchanged | Code present in the recorded serving revision; all three feature switches off | Enable and accept individually after the search/delivery prerequisite. Saved-search delivery retains human approval |
| Owned WhatsApp reply delivery and Cloud API transport | #180–#186 merged, default off | No live installation, credentials, number registration or webhook setup recorded | Pinned OpenClaw 2026.9.5 harness uses synthetic data and a fake Graph API. Complete owner prerequisites, five-message live smoke test, then fresh Phase 1 acceptance |
| Persistent inbound deduplication (WO-040) | #187 merged as `7a1fe36` | Not installed | The Cloud API path always uses the persistent store, so the separately approved owner-only smoke test uses it too. Adding any buyer still needs separate written owner approval |
| Bounded analysis and chart delivery | Worker, opt-in routing and chart-delivery code merged | Analysis and chart switches off in the last recorded probe | Phase 2 live acceptance pending. The new Cloud API channel is text-only; prove a compatible, verified media path before attempting its chart trial |
| Omission measurement | #144, #154 and #157 merged | Offline review evidence | Pilot v2 is inconclusive against the 1% no-cue threshold; human review remains separate. Do not claim complete feature recall |
| Extraction v3 (WO-034) | Phase A merged; #163 re-freeze and stacked #164 Phase B still open | No paid Phase C/D run recorded | Finish review, owner gold relabels, mapping/comparison and freezes before separately authorized paid runs |

### Execution order and parallel work

1. Complete the owner prerequisites in the [WhatsApp install runbook](runbooks/WHATSAPP_CHANNEL_INSTALL.md),
   including permissions, credentials and tunnel validation. Install and run the
   separately approved owner-only smoke test, then restart Phase 1 acceptance from P1-0.
   The server-approved reply must reach the user unchanged. A failure stops acceptance.
2. After Phase 1 is accepted, activate and accept bounded analysis. Chart acceptance
   additionally needs a media path through the owned send boundary and the approved
   one-shot trial with automatic rollback. Keeping charts enabled is a separate decision.
3. Next autonomy work is L2 buyer profile / transaction state and affordability search
   (the payment-budget half of roadmap Phase 3). Valuation supports L3 offer drafting;
   roadmap Phase 4 event alerts wait for feed access and actual change history.

In parallel, review the WO-041 install-readiness PR (runbook gate G4), finish the key-free WO-034 branches and owner relabels,
prepare acceptance evidence, and scope L2 work. These do not require a live install.
Paid runs, held-out access, outbound messages and activation retain their existing
approvals. #179 stays on hold; #171 is the superseded relay proposal, not the next
implementation assignment.

Detailed next actions are in the [dated acceptance update](releases/ACCEPTANCE_MATRIX.md#readiness-update-2026-11-10),
[activation handoff](releases/ACTIVATION_HANDOFF.md) and [autonomy ladder](AUTONOMY_LADDER.md).

## Historical audit, 2026-10-26

The audit and subsequent dated updates below are retained as recorded. The current
checkpoint above supersedes their readiness and next-work statements.

**Post-merge update, 2026-11-02 (WO-022):** PRs #134–#141 are merged, and nothing new is
installed, enabled or live-verified. See "Post-merge readiness, 2026-11-02" below and
`ACCEPTANCE_MATRIX.md`. The 2026-10-26 audit that follows is retained as written.

**The core implementation is merged and installed. IDX chat is configured for
Anthropic Sonnet 5.5 with medium effort; fresh live acceptance and the capstone
submission are not complete. The browser rehearsal found one factual relay error,
two outside-role wording failures and unsupported draft-state claims. Owner email
approval and inbox receipt are verified. Initial response rechecks passed, but a
later draft preview still changed a card field. Deterministic relay is blocked at
the approved single-hook API boundary; see ADR-0012.**

| Area | Verified state | Evidence |
|---|---|---|
| Feature implementation | Search/refinement, market statistics, semantic matching, comp checks, RAG, email approval/reports, saved-search alerts and extended metrics are merged | PRs #81 and #82; contracts and work-order Status sections |
| Local runtime | Gateway restarted and responds over RPC on loopback; eight ready skills, seven `idx` tools and four `idx_alerts` tools | PR #83 installation record; model-free stdio probes and health |
| Database | SELECT-only health OK; active snapshot 2026-09-18, sold snapshot 2026-09-17 | Installed health probe; schema notes |
| Automated verification | 3,123 offline tests passed, 60 skipped; prior fixture CI passed 59 integration tests (one skipped) and all 155 model-free evals | WO-019 response-policy tests; PR #92 fixture CI 40241223345; EVIDENCE_LOG.md |
| Listing index | Built and served; historical semantic phrasing and WhatsApp checks recorded | WO-010 build/run record; 100 supplied labels validated; current-service recall passed 10/10; SEMANTIC_REVIEW.md |
| Document index | Hybrid index built and served; decision-19 rebuild and five phrasing cases recorded | WO-012 final rebuild record; September 2026 evidence |
| Provider change | Human saved an Anthropic API-key profile; IDX now resolves to anthropic/claude-sonnet-5-5, medium effort; restart/RPC passed; direct routing consistency passed, runtime acceptance remains pending | PROVIDER_HANDOFF.md; 2026-10-25 closeout evidence |
| New-provider live baseline | Prior prompt checkpoint has passing evidence for all 111 local IDs; browser rehearsal found defects; new response policy needs fresh acceptance | WO-019; private baseline reports, latest recall-01 at 2026-10-26T02:36:31Z |
| Email and alerts | Owner reviewed and approved a corrected-recipient draft, sent it under an exact SMTP grant and confirmed inbox receipt; alert dry-run created no drafts | WO-019; private operator receipt and screenshot; approval remains operator-only |
| Public repository | Code/docs only; no MLS rows, indexes, credentials or recordings included | Content gates and CI |
| Portfolio | IDX entry is architecture-only; portfolio repository is private, Pages absent and deployment workflow disabled | Portfolio source/deployment audit; no public relaunch authorized |

## Post-merge readiness, 2026-11-02

Recorded by WO-022 after PRs #134–#141 merged. The merges happened on 2026-11-02 Pacific
time: #134 at 15:18 UTC, and #135–#141 between 02:30 and 02:47 UTC on 2026-11-03. Main CI
passed on the last merge (`5432dc2`, run 41568267014). This section supersedes the
2026-11-02 ladder below, which was written while #135–#141 were in review. That ladder
is kept as written.

Four rungs, each claimed only with its evidence:
- **Merged:** on `main` with CI green. A switch-guarded capability is in the code path
  but inert until enabled.
- **Installed:** the serving host runs that revision. That means `git pull`,
  `pip install -e ".[dev]"`, `./scripts/install.sh` and `openclaw gateway restart`,
  recorded with a probe.
- **Enabled:** the opt-in switch is on in the serving configuration. Today the switches
  are `IDX_ENRICHMENT_STORE`, `IDX_FEATURE_BADGES=1`, and `IDX_ANALYSIS_TOOL=1` with a
  pinned `IDX_ANALYSIS_IMAGE` in the tool server's `.env`. For a skill, its name must
  also be in the `idx` agent's skill list.
- **Live-verified:** a consented model or WhatsApp acceptance is recorded in
  EVIDENCE_LOG.md.

No installation, restart, `.env` change or live run has been recorded since the
2026-10-26 audit. WO-022 made none and made no paid call. A line-count check of the main
checkout's `.env` on 2026-11-02 found no non-empty `IDX_ENRICHMENT_STORE` and no
`IDX_FEATURE_BADGES=1` or `IDX_ANALYSIS_TOOL=1` line; no values were read.

| Capability | Merged | Installed | Enabled | Live-verified |
|---|---|---|---|---|
| Core assistant | Yes (PRs #81, #82 and earlier) | Yes, per the 2026-10-26 audit | n/a (no switch) | Partly; fresh acceptance open (audit above) |
| Remark-feature search (WO-021) | Yes: #134 `7f10734`, #135 `c8b897c` | No: no install recorded after the merges | No: `IDX_ENRICHMENT_STORE` is unset. The private store was built 2026-11-02 in the main checkout's gitignored `data/` (WO-021) but is not configured | No |
| Card badges (WO-021) | Yes, off by default: #136 `411a649` | No | No: `IDX_FEATURE_BADGES` unset; it also needs the store | No |
| Refresh preflight (WO-021) | Yes: #137 `d7df1e7` (offline script; local run 2026-11-02) | n/a | n/a | n/a |
| Feature-aware recommendations | Shared-feature lines only: #149 (WO-024), off by default. Owner decisions 2026-11-03 (#151): features never change the order; the rerank scaffold on `wo-021-recommend-design` stays an experiment; a feature filter on `recommend` is WO-031, drafted, not approved | No | No: `IDX_FEATURE_EXPLANATIONS` unset | No |
| Saved feature searches and feature alerts | No: both refuse features by design | No | No | No |
| Deal-signal alerts | No: ineligible (gold support 2, 2 and 6, below 10) | No | No | No |
| Bounded analyst `bounded_analysis` (WO-017 Phase C) | Yes, off by default: #138 `b318846` | No: worker image not built on the Mac (Docker not running) | No: `IDX_ANALYSIS_TOOL` unset, image unpinned, skill not in the agent's list, routing row pending | No: image relay unproven |
| Measurement (WO-020) | Yes: #139 `516764e`, #140 `aed1eaa` | n/a (eval tooling) | n/a | No model run (local or hosted) |
| Readiness ladder doc | Yes: #141 `5432dc2` | n/a | n/a | n/a |

Next steps, owners and required evidence per capability: `ACCEPTANCE_MATRIX.md`. The
work in parallel is WO-023 to WO-029: shared enrichment access, badge and explanation
presentation, saved feature searches, the omission-audit pilot, analyst routing and
channel, measurement expansion, and the activation handoff. It is planned or in
progress and not on main. The recommendation experiments stay on their branch.

Records now stale, left as written:
- the "in review" wording in the WO-017, WO-020 and WO-021 Status sections, which are
  edited only in their own files;
- the ladder below;
- CAPABILITY_ROADMAP.md's first 2026-11-02 update.
WO-022 ("Records found stale") lists each one.

## Capability readiness ladder, 2026-11-02

_Superseded by "Post-merge readiness, 2026-11-02" above; kept as written._

Each capability is placed on four separate rungs:
- **Built:** code and tests exist (merged, or in an open PR).
- **Integrated:** a registered tool or skill reaches it in the repository's default
  configuration.
- **Installed:** the owner's gateway runs it (settings, `install.sh`, restart).
- **Live-verified:** a consented model or WhatsApp acceptance is recorded.

A rung is claimed only with its evidence. Nothing below was installed, restarted or
live-tested in this session, and no paid call was made.

| Capability | Built | Integrated | Installed | Live-verified |
|---|---|---|---|---|
| Core assistant (search, market, similar, recommend, documents, email preview, saved-search alerts) | Yes, merged | Yes | Yes, per the 2026-10-26 audit above | Partly: browser rehearsal defects and fresh acceptance still open (above) |
| Remark-feature search (WO-021 Phase 1) | Yes: PR #134 merged (`7f10734`); offline acceptance fixes in PR #135 | Yes, in code: `features` on `search_listings` | No: `IDX_ENRICHMENT_STORE` is not set on the gateway | No: human script in `docs/RELEASE_WO021_SEARCH.md` |
| Card badges (WO-021 increment 2) | In review: PR #136 (stacked on #135) | No: off unless `IDX_FEATURE_BADGES=1` | No | No |
| Enrichment refresh preflight (WO-021) | In review: PR #137 (offline script) | Not a runtime feature | n/a | n/a |
| Feature-aware recommendations (WO-021 deliverable 3) | Experimental scaffold on branch `wo-021-recommend-design` (no PR); weights not approved | No: `recommend` ranking unchanged | No | No |
| Saved feature searches | Not started: `save_search` refuses features by default | No | No | No |
| Deal-signal alerts (WO-021 deliverable 4) | Not built: disabled by decision | No | No | No |
| Bounded analyst with charts (WO-017) | Service merged (Phase B); typed tool in review in PR #138 | No: registered only with `IDX_ANALYSIS_TOOL=1`; skill not in the agent's list | No: worker image not built on the Mac (Docker is not running) | No: image relay unproven; steps in `docs/RELEASE_WO017_ANALYSIS.md` |
| Measurement (WO-020) | In review: PR #139 (set, truth, oracle, scores) and PR #140 (local-model adapter, model leg, latency; stacked) | Eval tooling, not a runtime feature | n/a | No model run yet: local Ollama run and hosted runs are human steps |

_Undated in the original; records the late-October state (about 2026-10-26). Superseded._

## Remaining acceptance

- Begin a fresh session on the configured Sonnet 5.5 / medium route. Chat model
  selection, private credential entry and restart are complete; separate compatible
  embedding credentials remain necessary and were not changed by this migration.
- Automated local coverage is complete at its defined scope: 40 routing cases
  passed twice, 25 context routes passed, 36 behavior checks passed and the ten
  formerly skipped recall cases passed in a separate run. All 111 unique local
  IDs have passing evidence; original failed/skipped reports remain unchanged.
  Current-service recall@5 is 81.25% over eight nonempty judged queries; precision
  is 64% over all ten (80% over nonempty queries). These pool-based metrics are
  measurements, not an invented quality threshold or proof of runtime abstention.
  The 25-message browser rehearsal is complete with failures preserved: September
  Glendale townhouse median was changed from 774,999 to 870,000, forecast/pizza
  replies missed exact wording, and draft-state narration contradicted the journal.
  The response policy fix needs fresh affected runtime and routing checks. WhatsApp
  channel policy still needs its own evidence; browser checks do not establish it.
- WO-042 note: the coverage record above (40 routing cases, 111 unique local IDs)
  describes the case set as it was when those runs were made. WO-042 (#189)
  adds three routing cases with no tool call, `routing-local-043` (a transaction),
  `routing-local-044` ("are you a bot?") and `routing-local-045` (a request for a real
  person), so the routing selection with the analysis switch off is now 43 cases, under
  a 172-call paid ceiling. None of the three has ever run, and #189 also changes the
  server instructions the routing prompt carries, so local routing coverage is not
  complete for the current case set until a new paid routing run under a human `paid`
  token.
- WO-042 owner gates (decision of 2026-11-11, requirements, not done): the 172-call
  routing eval needs its own separate paid approval and is not authorized now; a
  code-enforced disclosure (research option 3b) is required before any buyer is added.
  Neither delays the owner-only smoke test, which still needs its own written approval.
- Billing remains unverified: the provider console has not posted this date's
  usage yet. A displayed zero with no data is not a confirmed zero charge.
- Human relevance labels and current-service recall verification are complete.
  No no-match score threshold was chosen; nearest matches remain no guarantee of
  relevance. Review the measured weaknesses before any future ranking change.
- Owner email acceptance completed 2026-10-26 UTC: the operator corrected a
  recipient typo, rejected the old draft, reviewed and approved its replacement,
  sent it under the exact SMTP grant and confirmed inbox receipt of all three
  selected listings. Raw previews, addresses and screenshots remain private.
  A terminal command cannot be approved by a model turn.
- WO-015's operator-command hook classification is complete and merged in PR #86
  under the human's gates grant. Approval remains human-only, no send/approval MCP
  tool is exposed, and delivery keeps the exact-command consent check. Real owner
  email acceptance is now recorded above; the earlier closeout sent no real email.
- Rehearse and record the final demo and backup; finish the intern's personal
  reflection with their own observations. No final recording or personal experience
  is invented in the repository.
- Install the optional alert schedule only after its manual rehearsal. It is not
  installed by this application or by the documentation audit.

The current sold data has about six months of coverage. Full-year and year-over-year
figures require additional history; changing an API key does not supply it.

_Undated in the original; records the late-October state (about 2026-10-26). Superseded by the STATUS.md doc map and the START_HERE.md reading order._

## Reading order

Users and reviewers: README.md → this checkpoint → CAPSTONE.md / EMAIL.md / ALERTS.md.
Coding agents: AGENTS.md → CLAUDE.md → START_HERE.md → this checkpoint and the relevant
work order. User decision 2026-10-26: after the WO-019 model-side merge, move on to the
combined roadmap. WO-018 Phase B has started with a draft synthetic annotation
specification. BASELINE_ACCEPTANCE.md remains the record of any open baseline
items; those items are not implied complete. WO-017/018 foundations remain
unused by live behavior. The combined roadmap/crosswalk is retained.
Chat selection/restart is complete; paid and manual acceptance remain pending. Do not infer permission for a
paid run, credential change, email approval or public portfolio launch from readiness.

_The six dated notes below were the end of STATUS.md, in this order._

## Deterministic relay compatibility, 2026-10-26

The authorized two-hook candidate remains uninstalled. Ten TypeScript synthetic
unit/delivery checks passed, and 375 free offline routing/fixture/runner checks
passed. A separate probe using the installed host hook runner and browser live-text
handler demonstrated an unchanged 960-sqft WhatsApp stub block but a visible
1,240-sqft browser rewrite with no outgoing-hook invocation. This is a browser-gate
failure, not full acceptance. No real WhatsApp turn, provider request, live config
or session write, tool-policy change or extension activation occurred. The ADR
records the first TypeScript/gateway-privilege boundary and the unresolved host seam.

## Model-side preview check, 2026-10-26

The human cancelled the deterministic relay and prohibited installation. The
cancelled branch is retained; the staged host/package were removed. The card
skills and Python numeric post-check passed 440 targeted offline tests. The five
skills are installed; the verifier remains a separate offline check.
Draft storage and approval remain deterministic; model output is checked only
when both complete texts are available and is not enforced. Stock OpenClaw's
documented tool-choice controls do not establish selective forced WhatsApp MCP
calls. A separately tokened WhatsApp turn showed the correct 960-square-foot value;
the pasted final reply does not prove byte identity or exclude earlier streaming.

## Phase 2 resumed, 2026-10-27

WO-017 (bounded analysis) is resumable: its pause depended on WO-019, which has
merged. Container-free steps start now; the Docker worker and chart renderer wait
for the human's decision on ADR-0013 (proposed). No analysis tool is registered.
WO-018 continues separately.

## Analysis worker decision, 2026-10-28

The human accepted ADR-0013: a Docker worker with a pinned image, no network, a
read-only root, resource limits, a 30-second deadline and output caps, given only
the bounded sample file; charts render to PNG inside the worker from trusted chart
data. One CI step is pending the human's `gates` token. No analysis tool is registered.

## Phase 5 draft, 2026-10-27

WO-020 (stronger measurement) is drafted for the human's approval, docs only.
Nothing is built until the scope is approved; WO-017 remains the active work order.

## Phase 2 code complete, 2026-10-28

WO-017's bounded analyst is built end to end and tested against the synthetic
fixture and a real container engine, but it is not registered or reachable from
chat. Remaining steps are the human's: build the worker image on the owner machine,
decide tool registration, and prove the WhatsApp image relay. WO-020 is not started.

<a id="part-2"></a>
# Part 2: moved from CAPABILITY_ROADMAP.md

_The roadmap's own checkpoint, reconciled 2026-11-10; superseded 2026-11-11 by STATUS.md._

## Current checkpoint

**2026-11-10 reconciliation.** We are completing L1 / Phase 1 activation. The v5
feature store has a recorded build and installation, but the latest Phase 1 session
failed at P1-4 on factual relay. The owned WhatsApp reply path and Cloud API wiring
(#180–#186) are merged and default off; owner setup, live smoke and fresh Phase 1
acceptance remain. Phase 2 code is merged, with live analysis and chart acceptance
still pending. The new Cloud API path is text-only, so charts also need compatible
verified media delivery. See [STATUS.md](STATUS.md#current-checkpoint-2026-11-10).

Order of execution is live send-path setup and Phase 1 acceptance, then Phase 2
activation, then L2 buyer state/profile and affordability search. Affordability is
the payment-budget half of Phase 3; its valuation half supports L3 offer drafting.
Phase 4 event alerts follow feed access and real history. WO-034 key-free work,
owner gold relabels, measurement and #187 dedupe review can proceed in parallel;
paid extraction/evaluation needs its existing separate authorization. #163 and
stacked #164 remain open. #179 is on hold.

### Historical checkpoint notes

The resume assignments and installation statements below describe their recorded
dates. They are superseded by the current checkpoint above; phase scopes remain.

**Resume Phase 1:** on 2026-10-26 the user directed work to move on after the
WO-019 model-side change merged. WO-018 Phase B starts with synthetic annotation
work. BASELINE_ACCEPTANCE.md continues to track open baseline evidence; resuming
the roadmap does not declare the remaining items complete.

- The existing assistant, email-preview path and saved-search code are merged and
  installed. Fresh live acceptance, owner email, judging and capstone evidence remain.
- The human privately configured Anthropic; IDX resolves to Sonnet 5.5 with medium
  effort. Restart and RPC checks passed, but no live model acceptance is claimed.
- WO-015's operator hook closeout merged in PR #86 after all CI checks passed.
- WO-017 Phase A is merged in PR #85: numeric data boundary, tests and sandbox design.
  It is preparation, not a callable execution tool. The revised order puts remarks
  enrichment before the remaining sandbox work; that foundation is retained.
- WO-018 is the next capability work order. Only one implementation WO is active.
  Existing closeout is not erased or silently declared complete by the new roadmap.

**2026-11-02 update.** Phase 1 (remarks enrichment) feature search is merged
(PR #134) with offline acceptance in review (#135). Badges (#136) and the refresh
preflight (#137) are built and off or offline. Phase 2's analyst tool is built behind
an off switch (#138). Phase 5 measurement is in review (#139, #140). Nothing new is
installed or live-verified. STATUS.md's readiness ladder separates built, integrated,
installed and live-verified for each capability.

**2026-11-02 post-merge update (WO-022).** PRs #135–#141 are now merged as well; the
"in review" wording above is kept as written. Nothing new is installed, enabled or
live-verified. STATUS.md's "Post-merge readiness, 2026-11-02" separates merged,
installed, enabled and live-verified. `ACCEPTANCE_MATRIX.md` lists, per Phase 1 and
Phase 2 capability, the remaining work order, operator actions, owner decisions and
acceptance evidence. WO-023 to WO-029 are planned or in progress and not on main.

**2026-11-05 owner decision (autonomy ladder).** Work is now ranked by the autonomy level
it moves toward (`AUTONOMY_LADDER.md`). Phase 3 is kept: its valuation half is the base for
offer drafting (L3), and its payment-budget half is taken forward now as affordability
search (L2), under Phase 3's existing prerequisites. Phase 4 (events) keeps its scope
and follows feed access. The phase text below is unchanged; the ladder does not relax any
communication, consent or deployment gate.

_The original Phase 0 operator sequence (plan of 2026-10-25). Steps 2, 3 and 6 were done by 2026-11-05; the open items are listed under STATUS.md stage S0 and track T4._

## Phase 0: operator sequence

1. Completed: private Anthropic profile, Sonnet 5.5 / medium route, validated config
   and definition-preserving restart. Separate embedding configuration is retained.
2. Finish the granted WO-015 hook change, required CI and merge; verify the installed
   policy surface still has no approval/send tool. Never run approval as the agent.
3. Begin a fresh chat. Match the live eval driver to the selected model/request
   contract before spending; each live run needs its exact command and call ceiling.
4. Rehearse search, condo refinement, paging, comps, descriptions, cited answers,
   mixed requests, drafts, saved searches, refusals and injection cases. Preserve
   failures and successful outputs as separate runs; costs come from the console.
5. Human reviews semantic relevance; no synthetic relevance marks replace that step.
6. Configure recipient/mail credentials privately, inspect the exact draft, approve
   in the operator terminal and authorize one send. Confirm receipt; never retry an
   uncertain send automatically. The sink is not evidence of real delivery.
7. Rehearse and record the demo and backup, redact private details, and finish the
   intern's reflection. Rotate the intended old provider credential after the checks;
   do not invalidate a key still required for embeddings. Keep IDX_SENDER_KEY stable.
8. Alert scheduling is optional and follows manual rehearsal. Portfolio deployment
   remains disabled; this plan grants no public launch.

<a id="part-3"></a>
# Part 3: moved from AUTONOMY_LADDER.md

_Written 2026-11-04/05 (PR #167); superseded 2026-11-11. Current state: STATUS.md; the per-level plan: AUTONOMY_LADDER.md "Plan by level"._

## Where the system is

**L1 capabilities built; L1 acceptance pending.** The assistant answers, recommends,
checks prices against comps, analyses and drafts email behind the human approval gate.
L1 is complete only when activation Phase 1 (feature search, badges, explanations, saved
feature searches) and activation Phase 2 (bounded analysis, one chart trial), as defined
in ACTIVATION_HANDOFF.md, are live-verified. Activation Phases 1 and 2 are the release
steps for the features built in roadmap Phases 1 and 2; roadmap phases are cited below by
their roadmap number. The evidence is the readiness ladder in STATUS.md, "Post-merge
readiness, 2026-11-02" (merged, installed, enabled, live-verified): it records feature
search, badges, explanations and bounded analysis as merged and none of them installed,
enabled or live-verified. Saved feature searches (#150) and chart delivery (#148) merged
after that table; see ACTIVATION_HANDOFF.md. The 2026-11-05 install of the activation
Phase 1 code, with every switch off, is recorded in EVIDENCE_LOG.md (staged install entry,
PR #168); STATUS will record it with the Phase 1 acceptance. No feature is enabled or
live-verified yet, activation Phase 2 is not installed, and the core assistant's fresh
live acceptance is still open.

## Order of work, by level

**L1 close-out**
- Activation Phase 1 and activation Phase 2 (ACTIVATION_HANDOFF.md, ACCEPTANCE_MATRIX.md).
- WO-034 Phases B to D (Phase B is in review as #164).

**L2**
- Transaction state machine and buyer profile (a new work order).
- Affordability search: the payment-budget half of roadmap Phase 3, taken forward now
  under that phase's existing prerequisites (disclosed finance assumptions, a separately
  approved rates source, no invented live rate).
- A transaction document agent for disclosures.
- The feed access request (FEED_ACCESS_REQUEST.md).

**L3**
- Multi-party gated communication, built on the email approval gate.
- Showing scheduling with a confirmation the human reviews.
- Offer drafting from the standard forms, with roadmap Phase 3 valuation beneath it.

**L4**
- An autonomous refresh agent.
- Self-audit under a fixed budget.
- Outcome feedback.
- The cost engine: distilled extractor, constrained router, calibrated cascade, RL from
  verifiable rewards, policy compilation.

Roadmap Phase 4 (events) keeps its scope and waits for feed access and real change history.
