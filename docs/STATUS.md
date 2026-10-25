# Current status and readiness

Last audited: 2026-10-25. This is the current checkpoint; dated work-order notes
and EVIDENCE_LOG.md retain the history behind it.

**The core implementation is merged and installed. IDX chat is configured for
Anthropic Sonnet 5.5 with medium effort; fresh live acceptance and the capstone
submission are not complete.**

| Area | Verified state | Evidence |
|---|---|---|
| Feature implementation | Search/refinement, market statistics, semantic matching, comp checks, RAG, email approval/reports, saved-search alerts and extended metrics are merged | PRs #81 and #82; contracts and work-order Status sections |
| Local runtime | Gateway restarted and responds over RPC on loopback; eight ready skills, seven `idx` tools and four `idx_alerts` tools | PR #83 installation record; model-free stdio probes and health |
| Database | SELECT-only health OK; active snapshot 2026-09-18, sold snapshot 2026-09-17 | Installed health probe; schema notes |
| Automated verification | 2,971 offline tests passed locally; 60 skipped; fixture CI passed 59 integration tests, with one real-data-only test skipped; 155 model-free eval cases passed | EVIDENCE_LOG.md, implementation CI run 40127311485 |
| Listing index | Built and served; historical semantic phrasing and WhatsApp checks recorded | WO-010 build/run record; judged recall marks remain pending |
| Document index | Hybrid index built and served; decision-19 rebuild and five phrasing cases recorded | WO-012 final rebuild record; September 2026 evidence |
| Provider change | Human saved an Anthropic API-key profile; IDX now resolves to anthropic/claude-sonnet-5-5, medium effort; restart/RPC passed; no live model acceptance yet | PROVIDER_HANDOFF.md; 2026-10-25 closeout evidence |
| Email and alerts | Draft/approval/delivery code and local sink tested; installed alert dry-run created no drafts | EMAIL.md, ALERTS.md; exact-draft approval remains operator-only |
| Public repository | Code/docs only; no MLS rows, indexes, credentials or recordings included | Content gates and CI |
| Portfolio | IDX entry is architecture-only; portfolio repository is private, Pages absent and deployment workflow disabled | Portfolio source/deployment audit; no public relaunch authorized |

## Remaining acceptance

- Begin a fresh session on the configured Sonnet 5.5 / medium route. Chat model
  selection, private credential entry and restart are complete; separate compatible
  embedding credentials remain necessary and were not changed by this migration.
- Run fresh live routing/e2e and UI/WhatsApp checks on that setup, preserving each
  run and reading actual costs from the provider console. Earlier successful
  walkthroughs do not validate a different provider or the new email/alert routes.
- Complete human relevance marks before claiming judged semantic recall or choosing
  a no-match score threshold. Nearest matches are not a guarantee of relevance.
- Configure the owner recipient and operator email credentials locally if needed,
  then review/approve one exact draft and verify real delivery under its own grant.
  A terminal command cannot be approved by a model turn.
- WO-015's operator-command hook classification is implemented under the human's
  separate gates grant and passed focused offline tests; integration requires its
  green-CI PR. Approval remains human-only, no send/approval MCP tool is exposed,
  and delivery keeps the exact-command consent check. No real email was sent.
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
work order. WO-017 Phase A is the active implementation assignment: the offline
numeric analysis boundary and sandbox design. It does not register or install a
new tool. See CAPABILITY_ROADMAP.md for the newly authorized capability sequence.
The existing operational handoff still requires the provider and live acceptance. Do not infer permission for a
paid run, credential change, email approval or public portfolio launch from readiness.
