# Current status and readiness

Last audited: 2026-10-26 UTC. This is the current checkpoint; dated work-order notes
and EVIDENCE_LOG.md retain the history behind it.

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
