# Current status and readiness

Last audited: 2026-10-26 UTC. This is the current checkpoint; dated work-order notes
and EVIDENCE_LOG.md retain the history behind it.

**The core implementation is merged and installed. IDX chat is configured for
Anthropic Sonnet 5.5 with medium effort; fresh live acceptance and the capstone
submission are not complete. The browser rehearsal found one factual relay error,
two outside-role wording failures and unsupported draft-state claims. Owner email
approval and inbox receipt are now verified; response fixes need a fresh recheck.**

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
work order. User decision 2026-10-25: pause new capabilities and accept the base
assistant first. WO-019 is active; BASELINE_ACCEPTANCE.md is the frozen checklist.
WO-017/018 foundations are merged but unused by live behavior; their remaining
work is paused until baseline acceptance. The combined roadmap/crosswalk is retained.
Chat selection/restart is complete; paid and manual acceptance remain pending. Do not infer permission for a
paid run, credential change, email approval or public portfolio launch from readiness.
