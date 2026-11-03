# Current status and readiness

Last audited: 2026-10-26 UTC. This is the current checkpoint; dated work-order notes
and EVIDENCE_LOG.md retain the history behind it.

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
| Feature-aware recommendations | No: unmerged branch `wo-021-recommend-design`, no PR; five owner decisions open | No | No | No |
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
