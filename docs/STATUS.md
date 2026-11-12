# Status and agreed plan

**This is the central plan; record every agreed decision or plan change here.** (Owner rule, 2026-11-11.)
Capability detail for each stage is in [CAPABILITY_ROADMAP.md](CAPABILITY_ROADMAP.md#detail-by-stage).
Autonomy planning is in [AUTONOMY_LADDER.md](AUTONOMY_LADDER.md). Dated history is in [STATUS_HISTORY.md](STATUS_HISTORY.md).

> **This doc:** where we are now; every agreed general phase (stages S0–S6, tracks T1–T5) in
> order, with its gate, exit and state; the decision register; pending owner inputs; open PRs
> and next actions; the naming key and the doc map.
> **Not here:** capabilities, work orders and acceptance criteria per stage
> ([roadmap](CAPABILITY_ROADMAP.md#detail-by-stage)); level definitions, measures and autonomy
> ideas ([ladder](AUTONOMY_LADDER.md)); dated history ([STATUS_HISTORY](STATUS_HISTORY.md)).
> **Read with:** [START_HERE](START_HERE.md), [ACTIVATION_HANDOFF](releases/ACTIVATION_HANDOFF.md),
> [ACCEPTANCE_MATRIX](releases/ACCEPTANCE_MATRIX.md), the [WhatsApp runbook](runbooks/WHATSAPP_CHANNEL_INSTALL.md).
>
> **Contents:** [Where we are now](#where-we-are-now) ·
> [Agreed plan](#agreed-plan) ([stages](#stage-summary), [tracks](#parallel-tracks),
> [roadmap map](#how-roadmap-phases-map-onto-stages), [deferred](#deferred)) ·
> [Decisions](#decisions) · [Pending owner inputs](#pending-owner) ·
> [Open PRs and next actions](#next-actions) · [Naming key](#naming-key) ·
> [Doc map](#doc-map) · [History](#history)

<a id="current-checkpoint-2026-11-10"></a>
## Where we are now

Checkpoint 2026-11-11. Reconciled against `main` at `8d24fc1` (merge of #164, after #189
at `e1ec3ab` and #163 at `ff12a71`) and the open-PR list from `gh` on that date. Runtime claims use the last recorded evidence; this
checkpoint made no new live inspection.

- **Current stage:** [S1](#stage-s1), not started. Its code is merged and default off; it
  waits on owner inputs ([pending](#pending-owner)).
- **Level:** L1 capabilities built; L1 not accepted ([ladder](AUTONOMY_LADDER.md#level-l1)).
- **Journey measures** ([ladder](AUTONOMY_LADDER.md#measures-per-level)): none taken yet;
  only component measurements exist.
- **Words:** "activation Phase 1/2" are the ACTIVATION_HANDOFF release steps (stages S2 and
  S3), not roadmap phases. "Script step P1-4" is the acceptance-script step. See the
  [naming key](#naming-key).

| Capability | Merged | Last recorded install / enablement | Acceptance and what remains |
|---|---|---|---|
| Core assistant and remark-feature search | Yes, including #134 and later fixes | Serving revision `0b0c48c`; v5 store enabled, recorded 2026-11-06 | Core path: the 2026-11-05 live check at `71fb39e` verified health, search, draft, the owner's terminal approval, one send and inbox receipt. Similar listings, recommend, document answers and mixed messages were not exercised ([EVIDENCE_LOG](EVIDENCE_LOG.md), 2026-11-05 live check). Remark-feature search: script steps P1-1 to P1-3 passed exact relay; script step P1-4 failed when the model copied another card's year built. Activation Phase 1 not accepted (#176) |
| Audited feature store | Original extraction and corrections; v5 builder #155 | 54,888-listing v5 store built and configured | Scope is exactly "policy v5; rulings applied: 8 overlay only; rulings 1-7 and 9-15 not applied to stored labels". It is not a full v5 re-read |
| Badges, shared-feature explanations, saved feature searches | Yes, including #149 and #150; recommendation order unchanged | Code present in the serving revision; all three switches off | Enable and accept one at a time in S2. Saved-search delivery keeps human approval |
| Owned WhatsApp reply delivery and Cloud API transport | #180–#187, #190 (install readiness), #191 (window plan) and #189 (WO-042 disclosure and referral, `e1ec3ab`), default off. Merging #189 alone changes nothing on the gateway; it takes effect when the serving checkout is pulled (A2), and no A2 is recorded | No live install, credentials, number, webhook or tunnel recorded | Runbook G2 and G3 met; runbook G4 met by the #190 merge. Runbook G1, the section 7 approval, T0, Q2, Q4 and Q6 pending. Then A2 and the five-message smoke test ([S1](#stage-s1)) |
| Persistent inbound dedupe (WO-040) | #187, `7a1fe36` | Not installed | The Cloud API path always uses it, so the owner-only smoke test does too. Adding any buyer still needs separate written owner approval and code-enforced disclosure |
| Bounded analysis and chart delivery | Worker, opt-in routing and chart-delivery code | Analysis and chart switches off in the last recorded probe | Activation Phase 2 pending ([S3](#stage-s3)). The channel is text-only, so charts need a media path through the owned send boundary |
| Omission measurement | #144, #154, #157 | Offline review evidence | Pilot v2 inconclusive against the 1% no-cue threshold. Do not claim complete feature recall |
| Extraction v3 (WO-034) | Phase A (#153), #163 v4 re-freeze (`ff12a71`) and #164 Phase B (`8d24fc1`) merged | No paid Phase C/D run recorded | Paid runs paused ([T1](#track-t1)) |

Activation Phase 1 and Phase 2 are not accepted; code completion is not acceptance.
The 2026-11-06 provider-console readings differ (US$11.37 versus US$11.26) and the
difference is unexplained; it stays as recorded in [EVIDENCE_LOG](EVIDENCE_LOG.md)
(entry "2026-11-06, Phase 1 paid session under script r6").

<a id="agreed-plan"></a>
## Agreed plan: the general phases

The agreed general phases are **stages S0–S6**, run in order, plus **parallel tracks
T1–T5** that need no live install. Work is ranked by autonomy level (owner decision
2026-11-05); roadmap phase numbers name scope, not order. A stage starts only when its
"starts when" holds, and every live or paid step inside it keeps its own approval.

<a id="stage-summary"></a>
### Stage summary

| Stage | Name | Starts when | Done when | State | Level | Detail |
|---|---|---|---|---|---|---|
| [S0](#stage-s0) | Foundations and capstone close-out | Started (weeks 0–12) | Fresh core acceptance and the capstone items recorded ([T4](#track-t4)) | Foundations built; close-out open | L0/L1 baseline | [roadmap](CAPABILITY_ROADMAP.md#detail-s0) · [ladder](AUTONOMY_LADDER.md#level-l0) |
| [S1](#stage-s1) | Owned WhatsApp channel and owner-only smoke test | Owner approvals and safeguards in place; A2 done | Five-message smoke test passes; rollback and restore verified | Not started; code merged, default off | L1 prerequisite | [roadmap](CAPABILITY_ROADMAP.md#detail-s1) · [ladder](AUTONOMY_LADDER.md#level-l1) |
| [S2](#stage-s2) | Fresh activation Phase 1 acceptance | S1 done | P1-0 onward passes; the approved reply reaches the user unchanged (handoff G3) | Not started; earlier sessions stopped at script step P1-4 | L1 | [roadmap](CAPABILITY_ROADMAP.md#detail-s2) · [ladder](AUTONOMY_LADDER.md#level-l1) |
| [S3](#stage-s3) | Activation Phase 2, bounded analysis then charts | S2 accepted | Analysis accepted; chart trial passes on an owned media path; L1 complete | Not started; code merged, switches off | L1 (completes it) | [roadmap](CAPABILITY_ROADMAP.md#detail-s3) · [ladder](AUTONOMY_LADDER.md#level-l1) |
| [S4](#stage-s4) | L2 buyer profile, transaction state and affordability search | L1 accepted, plus approved new work orders | The ladder's L2 gate, earned with its measures | Not started; no work order | L2 | [roadmap](CAPABILITY_ROADMAP.md#detail-s4) · [ladder](AUTONOMY_LADDER.md#level-l2) |
| [S5](#stage-s5) | L3 valuation, offer drafting, gated communication and showings | S4 done; data-access decision; fair-housing check built | The ladder's L3 gate | Not started | L3 | [roadmap](CAPABILITY_ROADMAP.md#detail-s5) · [ladder](AUTONOMY_LADDER.md#level-l3) |
| [S6](#stage-s6) | L4 event alerts and self-operation | S5 done; feed access and real change history | The ladder's L4 gate | Not started; blocked on feed access | L4 | [roadmap](CAPABILITY_ROADMAP.md#detail-s6) · [ladder](AUTONOMY_LADDER.md#level-l4) |

Which roadmap phases each stage carries: [How roadmap phases map onto stages](#how-roadmap-phases-map-onto-stages).

<a id="stage-s0"></a>
### S0: Foundations and capstone close-out

The internship build (WO-000 to WO-019) plus the code of roadmap Phases 1, 2 and 5. The
foundations are merged and installed; the capstone close-out runs as [track T4](#track-t4).
- **Starts when:** started; this is the base every later stage uses.
- **Done when:** a fresh core end-to-end acceptance and the capstone items (T4) are recorded.
- **State:** foundations built. Part of the core path was live-verified on 2026-11-05;
  the full fresh acceptance and the capstone items are open.
- **Detail:** [roadmap S0](CAPABILITY_ROADMAP.md#detail-s0) · [ladder L0](AUTONOMY_LADDER.md#level-l0)

<a id="stage-s1"></a>
### S1: Owned WhatsApp channel and owner-only smoke test

The project-owned channel (verifier at the send boundary) on the Cloud API, installed for
one owner-only window. A2, the #189 go-live, is a separate short owner step before the
window ([runbook §1c](runbooks/WHATSAPP_CHANNEL_INSTALL.md)).
- **Starts when:** all of these hold: runbook G1 and the section 7 written approval are
  given and T0 is chosen; Q2, Q4 and Q6 are answered; the self opt-in record, the profile
  contact route and the interim privacy-policy URL exist; the dashboard access check result
  is reported; A2 has been carried out (it needs #189, which is merged at `e1ec3ab`).
- **Done when:** the five-message smoke test (runbook 7.5) passes and the rollback and stock
  restore are verified.
- **State:** not started. #180–#187, #189, #190 and #191 merged, default off. No A2 is recorded.
- **Agreed shape (planning, not approval):** Cloudflare named tunnel; stock exclusion route
  (b); queue option 1; no reboot or logout; no `gateway stop --disable`; window decisions
  A–E; Cloudflare scoped to the webhook host and path (register group C,
  [AG-C14 to AG-C24](#decisions-c)).
- **Detail:** [roadmap S1](CAPABILITY_ROADMAP.md#detail-s1) · runbook §1, §1b, §1c, §7 ·
  WO-041 · WO-043

<a id="stage-s2"></a>
### S2: Fresh activation Phase 1 acceptance

Restart activation Phase 1 from P1-0 through the owned send path, one switch per restart.
- **Starts when:** S1 is done.
- **Done when:** P1-0 onward passes in the order search, badges, explanations, saved
  feature searches, and every server-approved reply reaches the user unchanged. That is
  handoff G3. A failure stops acceptance and rolls back only that step.
- **State:** not started. Two earlier sessions stopped at script step P1-4 on the relay.
  Any new paid session needs its own approval (the r6 approval has expired).
- **Detail:** [roadmap S2](CAPABILITY_ROADMAP.md#detail-s2) · ACTIVATION_HANDOFF procedures 1–4

<a id="stage-s3"></a>
### S3: Activation Phase 2, bounded analysis then charts

Bounded analysis first, then one chart trial.
- **Starts when:** S2 is accepted (handoff G3).
- **Done when:** analysis is accepted, and the one-shot chart trial passes and rolls back
  automatically. That completes L1. Keeping charts on is a separate owner decision.
- **Media path:** charts need a media path through the owned send boundary. D5 approved the
  stock MEDIA-line path, which no longer matches the owned channel; a fresh owner decision
  is likely needed (conflict X1).
- **State:** not started; code merged, switches off.
- **Detail:** [roadmap S3](CAPABILITY_ROADMAP.md#detail-s3) · ACTIVATION_HANDOFF procedures 5 and 5b

<a id="stage-s4"></a>
### S4: L2 buyer profile, transaction state and affordability search

A buyer profile and transaction state with deadlines, affordability search, a transaction
document agent, and the feed access request.
- **Starts when:** L1 is accepted and a new work order is approved for each item.
- **Before adding any buyer:** separate written owner approval, and code-enforced
  disclosure (WO-042 option 3b) built. Counsel must confirm the hosted model's processing
  is allowed (Q6).
- **Done when:** the ladder's L2 gate is earned with its measures.
- **State:** not started; no work order exists. The feed request is drafted, not sent.
- **Detail:** [roadmap S4](CAPABILITY_ROADMAP.md#detail-s4) · [ladder L2](AUTONOMY_LADDER.md#level-l2)

<a id="stage-s5"></a>
### S5: L3 valuation, offer drafting, gated communication and showings

Valuation and offer drafting on the standard forms, gated multi-party communication and
showing scheduling, each action behind its own approval.
- **Starts when:** S4 is done. Valuation needs a data access and licensing decision. The
  fair-housing check on the outbound path must be built and accepted first.
- **Done when:** the ladder's L3 gate is earned.
- **State:** not started.
- **Detail:** [roadmap S5](CAPABILITY_ROADMAP.md#detail-s5) · [ladder L3](AUTONOMY_LADDER.md#level-l3)

<a id="stage-s6"></a>
### S6: L4 event alerts and self-operation

Event alerts, plus refresh, self-audit, outcome feedback and the cost engine.
- **Starts when:** S5 is done, and feed access and real change history exist.
- **Done when:** the ladder's L4 gate is earned.
- **State:** not started; blocked on feed access.
- **Detail:** [roadmap S6](CAPABILITY_ROADMAP.md#detail-s6) · [ladder L4](AUTONOMY_LADDER.md#level-l4)

<a id="parallel-tracks"></a>
### Parallel tracks

None of these needs a live install. Paid runs, held-out access and outbound messages keep
their own approvals.

| Track | Work | Roadmap / level | State and notes | Detail |
|---|---|---|---|---|
| <a id="track-t1"></a>T1 | WO-034 extraction v3 | Roadmap 1; listed by the ladder under L1 close-out | #163 (`ff12a71`) and #164 (`8d24fc1`) merged; Phase C needs the owner's dev relabel and a paid token. Paid runs paused; no held-out inspection | [roadmap T1](CAPABILITY_ROADMAP.md#detail-t1) |
| <a id="track-t2"></a>T2 | Measurement | Roadmap 5; evidence for every level | WO-020 and WO-028 merged; no local or hosted model run of the set | [roadmap T2](CAPABILITY_ROADMAP.md#detail-t2) |
| <a id="track-t3"></a>T3 | Relay guarantee (WO-036) | Not placed at a level (a ladder [proposal](AUTONOMY_LADDER.md#ideas-and-open-placement-questions) puts it under L1 close-out). Its outcome, the approved reply reaching the user unchanged, is S2's acceptance condition (AG-F5) | Layers 1–2 merged (#169, #170, #172). The owned channel's verified send boundary (S1) is the current route. #171 is the superseded proposal; #179 stays on hold | [roadmap T3](CAPABILITY_ROADMAP.md#detail-t3) |
| <a id="track-t4"></a>T4 | Capstone close-out | Roadmap 0 | Open: fresh core end-to-end, demo and recording, backup, reflection, billing and cost record, credential rotation, optional alert schedule | [roadmap T4](CAPABILITY_ROADMAP.md#detail-t4) |
| <a id="track-t5"></a>T5 | L2 scoping and acceptance-evidence preparation | — | Draft L2 work orders with a level line; prepare P1-0 evidence | [roadmap T5](CAPABILITY_ROADMAP.md#detail-t5) |

### How roadmap phases map onto stages

| Roadmap phase | Stage(s) | Level | Note |
|---|---|---|---|
| [0 Finish current acceptance](CAPABILITY_ROADMAP.md#roadmap-phase-0) | [S0](#stage-s0), [T4](#track-t4) | L0/L1 baseline | Capstone; open items in T4 |
| [1 Remarks enrichment](CAPABILITY_ROADMAP.md#roadmap-phase-1) | [S0](#stage-s0) (code), [S2](#stage-s2) (acceptance), [T1](#track-t1) | L0/L1 | WO-034 runs as T1 |
| [2 Bounded analyst with charts](CAPABILITY_ROADMAP.md#roadmap-phase-2) | [S0](#stage-s0) (code), [S3](#stage-s3) | L1 | Charts need the owned media path |
| [3 Valuation and payment-budget search](CAPABILITY_ROADMAP.md#roadmap-phase-3) | [S4](#stage-s4) (payment-budget half), [S5](#stage-s5) (valuation half) | L2 / L3 | Split decided 2026-11-05 |
| [4 Event alert drafts](CAPABILITY_ROADMAP.md#roadmap-phase-4) | [S6](#stage-s6) | L4 | Waits for feed access and real change history |
| [5 Stronger measurement](CAPABILITY_ROADMAP.md#roadmap-phase-5) | [S0](#stage-s0) (code), [T2](#track-t2) | evidence for every level | A minimal eval set is part of every phase |
| [6 Compound planning and inference controls](CAPABILITY_ROADMAP.md#roadmap-phase-6) | unplaced (owner to place) | — | Candidates in the ladder's [open questions](AUTONOMY_LADDER.md#ideas-and-open-placement-questions) |
| [7 Buyer workflow breadth](CAPABILITY_ROADMAP.md#roadmap-phase-7) | unplaced (owner to place) | — | Same |
| [8 Domain checks and answerability](CAPABILITY_ROADMAP.md#roadmap-phase-8) | [S5](#stage-s5) (fair-housing check before outbound only); rest unplaced | L3 prerequisite | Same |
| [9 Reusable MCP/API product](CAPABILITY_ROADMAP.md#roadmap-phase-9) | deferred | moves no level | Ladder: deferred |
| [10 Rich channel and transaction workflows](CAPABILITY_ROADMAP.md#roadmap-phase-10) | [S1](#stage-s1) (official channel), [S3](#stage-s3) (media), [S4](#stage-s4) (per-user documents), [S5](#stage-s5) (handoff, scheduling) | L1–L3 | Voice deferred; maps, private shortlist, interactive refinements and the personal brief are unplaced |
| [11 Feedback and routing research](CAPABILITY_ROADMAP.md#roadmap-phase-11) | [S6](#stage-s6) (outcome feedback and the cost engine the ladder names); rest unplaced | L4 | Same |
| [12 Refresh and hosting](CAPABILITY_ROADMAP.md#roadmap-phase-12) | [S4](#stage-s4) (feed request; sending needs owner approval), [S6](#stage-s6) (refresh) | L2 / L4 | Hosting deferred until L4 needs it |

<a id="deferred"></a>
### Deferred

Four items are deferred because they move no level (AG-B5): the list is in the ladder,
[Deferred because they move no level](AUTONOMY_LADDER.md#deferred-because-they-move-no-level).

<a id="decisions"></a>
## Agreed decisions and constraints

Every decision the owner has given that still shapes the plan. Status words: **decided**;
**decided (branch only)**, recorded only on an open PR; **decided (planning only)**, not an
approval; **agreed owner request**, work the owner asked for that is not done yet;
**superseded**; **pending owner**, not given. "Session" means the owner in the
working session of 2026-11-10/11. None of these is a live approval.

<a id="decisions-a"></a>
### A. Roles, working rules and the goal

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-A1 | The agent does key-free work (workflows, agents, PRs) and reports PR heads and CI. The owner merges, mints consent tokens, edits `.env`, sends every live message and approves every paid or live step | 2026-11-11 | decided | Session; releases/ACTIVATION_HANDOFF.md:155-156 |
| AG-A2 | Rollback never depends on a consent token | standing | decided | Session; runbook §4 |
| AG-A3 | Preserve history; no force pushes | standing | decided | Session; AGENT_RULES.md |
| AG-A4 | Goal: an autonomous buyer's agent under a licensed human. Rank work by L0–L4; L5 is never built or claimed | 2026-11-05 | decided | Session; AUTONOMY_LADDER.md |
| AG-A5 | Every new work order names its autonomy level; one that moves no level needs an owner note | 2026-11-05 | decided | CAPABILITY_ROADMAP.md "Work-order and decision rules" |
| AG-A6 | The constants at every level (no client funds, the human signs, no outbound beyond the user's chat before a fair-housing check, SELECT-only MLS, consent tokens, append-only evidence log) | 2026-11-05 | decided | AUTONOMY_LADDER.md "Constants at every level" |
| AG-A7 | Release order: foundation first, then stacked consumers, then combined testing, then Phase 1 before Phase 2, so a failure traces to its step | 2026-11-02 | decided | Session (owner memory; no repo line) |
| AG-A8 | The roadmap is direction, not consent: spending, enforcement changes, new services, contacting people and deployment each need their own approval | 2026-10-25 | decided | CAPABILITY_ROADMAP.md "Work-order and decision rules" |
| AG-A9 | One switch per restart, each followed by its live check; a Phase 2 failure is never fixed by changing a Phase 1 switch, or the reverse | 2026-11-03 | decided | releases/ACTIVATION_HANDOFF.md §2 |
| AG-A10 | Planning-docs rule. The owner, quoted: "status md should contain the overall plan of everything we have discussed and agreed to (save that as a rule), it should have all general phases we have agreed to mapped out, and then capabilities can have more detail on each of the phases with an explicit link to status md and then autonomy ladder can be the central autonomy planning doc where its ideas and phases are in detail and linked to status md with general phase descriptions". So STATUS.md holds the agreed plan and every general phase, and every agreed decision or plan change is recorded here; CAPABILITY_ROADMAP.md gives per-phase detail and links here; AUTONOMY_LADDER.md is the central autonomy planning doc and links here | 2026-11-11 | decided | Session (owner rule) |
| AG-A11 | Docs folder reorganization. The owner, quoted: "and the docs folder is getting very large, it needs more organization now". The design is prepared (an index plus folders; pinned and frozen files stay where they are). The move happens in its own PR after this one (#192). 2026-11-12: that PR is #196, open, stacked on #193; 22 docs move into `releases/`, `whatsapp/` and `enrichment/`, and [docs/README.md](README.md) indexes every folder, the pinned files and the old→new paths | 2026-11-11 | agreed owner request; the move is in review, not merged | owner, this session |

<a id="decisions-b"></a>
### B. Phase order

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-B1 | Combined roadmap Phases 0–12; key-free preparation first, live runs granted separately | 2026-10-25 | decided; order since ranked by level (AG-B2, AG-B3) | CAPABILITY_ROADMAP.md preamble |
| AG-B2 | Roadmap Phase 3 kept: valuation half beneath L3 offer drafting; payment-budget half now as L2 affordability search. Phase 4 keeps its scope and follows feed access | 2026-11-05 | decided | AUTONOMY_LADDER.md; EVIDENCE_LOG 2026-11-05 ladder entry |
| AG-B3 | Sequence: owner-only smoke test → fresh Phase 1 acceptance from P1-0 → Phase 2 (analysis, then charts) → L2 profile, state and affordability → L3 valuation and offer drafting → L4 event alerts after feed access and real change history. These are stages S1–S6 | 2026-11-10/11 | decided | Session |
| AG-B4 | The ladder's work list per level as written on 2026-11-05 (L1 close-out: activation Phases 1 and 2, WO-034 B–D; L2, L3 and L4 items). Items added to the ladder since are marked there as proposals | 2026-11-05 | decided | [STATUS_HISTORY "Order of work, by level"](STATUS_HISTORY.md#order-of-work-by-level) |
| AG-B5 | Deferred, moving no level: remote HTTP listener and clients, brokerage rankings, voice, hosting until L4 | 2026-11-05 | decided | AUTONOMY_LADDER.md |
| AG-B6 | Parallel without a live install: WO-034 key-free work, owner relabels, acceptance-evidence preparation, L2 scoping | 2026-11-10 | decided | Session; tracks T1–T5 |

<a id="decisions-c"></a>
### C. WhatsApp channel and the owner-only smoke test

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-C1 | Path A: a project-owned channel with the verifier at the send boundary; paths B and C rejected | 2026-11-06 | decided in practice (built, #180–#183); ADR-0016 still proposed | ADR-0016 |
| AG-C2 | Cloud API adapter prepared offline; credentials and the live smoke wait for separate approval after brokerage, IDX and hosted-model confirmation | 2026-11-08 | decided | WO-038 |
| AG-C3 | WO-038 lifecycle fix: refuse sends while stopped; void old turns across a restart | 2026-11-08 | decided | WO-038 |
| AG-C4 | Owner-only credentials file outside the repo and `~/.openclaw`; separate loopback listener; tunnel limited to the webhook path | 2026-11-08 | decided | WO-038 |
| AG-C5 | Send failures logged privately; oversized inbound dropped; 1 MiB body limit; 30-minute age limit | 2026-11-08 | decided | WO-038 |
| AG-C6 | Cloud API wiring off by default, proven offline with synthetic credentials and a fake Graph API; live setup needs separate approval | 2026-11-08 | decided | WO-039 |
| AG-C7 | In-memory dedupe accepted for the smoke test | 2026-11-08 | **superseded** by AG-C8 | WO-038 (conflict X6) |
| AG-C8 | Persistent dedupe required before adding buyers (the requirement, 2026-11-08, restated for WO-040); built and merged in #187 on 2026-11-10; the Cloud API path always uses it | 2026-11-08 | decided | WO-038; WO-039; WO-040 |
| AG-C9 | Adding any buyer needs separate written owner approval; until then the allowlist holds the owner's test number only | 2026-11-09 | decided (no buyer approved) | Session; runbook §7 |
| AG-C10 | Card turns marked from the trusted tool-call event; channel-minted handle required (decisions 16, 17) | 2026-11-06 | decided | EVIDENCE_LOG 2026-11-06 |
| AG-C11 | Proactive sends (item 18: message tool, cron, alerts) stay withheld on this channel | 2026-11-07 | decided (deferred) | ADR-0016 |
| AG-C12 | Run binding (decision 19); tied refusals withhold their own turn (decision 21) | 2026-11-07 | decided | ADR-0016 |
| AG-C13 | Item 22: the four routine choices; admin cancellation an accepted availability risk; host-level control 3.6b if dashboard users have admin | 2026-11-07 | decided | WO-037; runbook §1 G2 |
| AG-C14 | Tunnel: Cloudflare named tunnel; Tailscale Funnel stays the documented alternative | 2026-11-10 | decided | Session; WO-041 |
| AG-C15 | Runbook G4 not waived: the install PR had to resolve it. #190 merged, so G4 is met | 2026-11-10 | decided | WO-041; gh |
| AG-C16 | Stock exclusion route (b): keep stock installed, `openclaw plugins disable whatsapp`, then the allowlist; uninstall (a) stays documented | 2026-11-11 | decided | Session; WO-041 |
| AG-C17 | Queue option 1: no queue config write and no dashboard sends into the WhatsApp session | 2026-11-10/11 | decided | Session; WO-041 |
| AG-C18 | No reboot or logout in the window; skip `gateway stop --disable` | 2026-11-11 | decided | Session; WO-041 |
| AG-C19 | Window decision A: 3h15m window; start rollback when M5 passes or an abort criterion is met, by T0+1:44 at the latest; confirm the listener is stopped and stop the tunnel before restoring stock; revoke the token at once if shutdown is unconfirmed; clean up after stock is verified | 2026-11-11 | decided (planning only, not approval) | Session; WO-043; runbook §1b |
| AG-C20 | Window decision B: menu-bar reset once the build is confirmed to send nothing | 2026-11-11 | decided (planning only) | Same |
| AG-C21 | Window decision C: keep #189 and its policy after the stock restore; if A2 fails, restore checkout, policy and config together | 2026-11-11 | decided (planning only) | Same |
| AG-C22 | Window decision D: A2 kept separate, with a local config compare that prints key paths only | 2026-11-11 | decided (planning only) | Same |
| AG-C23 | Window decision E: the tested rollback sequence; decision A's cleanup timing is the only change | 2026-11-11 | decided (planning only) | Same |
| AG-C24 | Cloudflare changes scoped to the webhook host and path (a host-scoped HTTP-to-HTTPS redirect rule replaces the zone-wide toggle); zone-wide settings listed separately for owner review | 2026-11-11 | decided (planning only) | Session; WO-043 |
| AG-C25 | **Live approval (runbook G1 plus the section 7 written approval) and the choice of T0** | — | **pending owner (not given)** | Session; WO-043; runbook §1, §7 |
| AG-C26 | #179 (token relay prototype) stays on hold | 2026-11-07 onward | decided | Session; WO-037 |
| AG-C27 | #171 is the superseded relay proposal, not the next assignment | — | superseded proposal | Session |
| AG-C28 | Cloud API is the working transport for the owner-only smoke test. ADR-0017 remains proposed; no acceptance is recorded | 2026-11-08 onward | working plan | WO-038 to WO-043 (conflict X3) |

<a id="decisions-d"></a>
### D. Confirmations and compliance

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-D1 | Q2 brokerage policy | — | **pending owner** | Session; eligibility §4; runbook §7 |
| AG-D2 | Q4 MLS/IDX display rules | — | **pending owner** | Same |
| AG-D3 | Q6 hosted-model vendor and counsel's view on data sharing | — | **pending owner** | Same |
| AG-D4 | Q1 business ownership, Q3 identity text and Q7 retention are folded into the brokerage confirmation and stay open | 2026-11-10 | decided (folding); the questions are pending | Session; WO-042 (merged in #189) |
| AG-D5 | Q5: use clear AI disclosure; the legal question stays with counsel | 2026-11-10 | decided | Session; WO-042 (merged in #189) |
| AG-D6 | No blanket waivers. The owner-only test still needs a self opt-in record, a profile contact route and an interim privacy-policy URL | 2026-11-10/11 | decided; the items are not done | Session (conflict X4) |
| AG-D7 | Buyer onboarding (opt-in, notices) deferred to rollout | 2026-11-10/11 | decided | Session |
| AG-D8 | Dashboard access check result (runbook 3.6b audit) | — | **pending** (not reported) | Session; runbook §3 |
| AG-D9 | Exclude WhatsApp content from shared training and eval sets; keep the assistant business-scoped | — | listed as an owner item; **not decided** | Eligibility §2 |

<a id="decisions-e"></a>
### E. #189 / WO-042 disclosure and referral

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-E1 | The disclosure and referral wording are approved, the referral line stays as written, and the digest changes are approved | 2026-11-11 | decided | Session; WO-042 (merged in #189); EVIDENCE_LOG 2026-11-11 |
| AG-E2 | The 172-call routing eval (43 cases with the analysis switch off) needs its own paid approval and token | 2026-11-11 | decided as a requirement; the eval is **pending owner** | Same |
| AG-E3 | Code-enforced disclosure (option 3b) required before adding buyers; not built | 2026-11-11 | decided | Same |
| AG-E4 | Neither AG-E2 nor AG-E3 delays the owner-only smoke test | 2026-11-11 | decided | Same |
| AG-E5 | Go-live is coupled: pulling main past #189 and installing the policy are one owner step (A2: stop, pull, install.sh, restart, fresh session) | 2026-11-11 | decided | Same; runbook §1c |
| AG-E6 | #189 merged into `main` at `e1ec3ab` on 2026-11-11. The merge gives no live approval, and alone changes nothing on the gateway until the serving checkout is pulled. No A2 is recorded; it stays an owner step | 2026-11-11 | merged; A2 **pending owner** | gh; runbook §1c |

<a id="decisions-f"></a>
### F. Activation Phase 1 (stage S2)

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-F1 | Handoff D1 (main checkout to `main` in place), D2 (badge look), D3 (explanation line only, order unchanged), D4 (conservative saved-search defaults), D7 (merge order and the C3a off probe) | 2026-11-03 | decided (D7 executed) | releases/ACTIVATION_HANDOFF.md "Decided (2026-11-03 …)" |
| AG-F2 | Order: search → badges → explanations → saved feature searches; stop at the first failure and roll back only that step | 2026-11-03 | decided | releases/ACTIVATION_HANDOFF.md §2 |
| AG-F3 | Relay Layer 1 (model-free check after every card turn; a changed number fails the turn) and Layer 2 first (`reason=exact` required; measurement cap 160 calls) | 2026-11-05 | decided | releases/ACTIVATION_HANDOFF.md §4; EVIDENCE_LOG 2026-11-05 |
| AG-F4 | Script step P1-4 reworded (pool and solar, from the description); procedure 1 re-runs from P1-0 | 2026-11-05 | decided | EVIDENCE_LOG 2026-11-05 |
| AG-F5 | Fresh acceptance from P1-0 after the smoke test; the server-approved reply must reach the user unchanged; a failure stops acceptance | 2026-11-10 | decided | Session |
| AG-F6 | The r6 session approval (3 h, 24 turns, US$10 cap) has expired and authorizes no new run | 2026-11-06 | decided (expired) | EVIDENCE_LOG 2026-11-06 |
| AG-F7 | Matrix row P1-4 (weighted rerank) is not a release prerequisite; rerank preference recorded; WO-031 drafted, not approved to build | 2026-11-03 | decided | releases/ACCEPTANCE_MATRIX.md; RECOMMEND_FEATURES_DECISION.md |
| AG-F8 | v5 store scope sentence as quoted above; the rulings 1-7 re-read is deferred until after WO-034 Phase D and is **pending owner** | 2026-11-03/04 | decided (deferral) | WO-021 |
| AG-F9 | WO-032 closed as not applicable (D-032 option (a)); the read-only preflight kept | 2026-11-03 | decided | WO-032 |
| AG-F10 | Deal-signal alerts stay ineligible (support below 10); omission pilot threshold of 1% accepted, v2 inconclusive | 2026-10-28 / 2026-11-04 | decided | releases/ACCEPTANCE_MATRIX.md; WO-033 |

<a id="decisions-g"></a>
### G. Activation Phase 2 (stage S3)

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-G1 | ADR-0013: Docker worker (pinned image, no network, read-only root, limits, 30 s deadline); charts render as PNG inside it | 2026-10-28 | decided (accepted) | ADR-0013 |
| AG-G2 | Decision 1: the "can't help" line unchanged; naming `bounded_analysis` accepted | 2026-11-02 | decided | WO-027 |
| AG-G3 | Decision 2: charts must be delivered; the text fallback alone does not pass P2-3 | 2026-11-02 | decided | WO-027 |
| AG-G4 | An image conflict fails closed (#156) | 2026-11-03 | decided | WO-027 |
| AG-G5 | The isolation test judges interfaces by state (Docker option A) | 2026-11-04 | decided | WO-027 |
| AG-G6 | D5: one separately authorized chart trial on the stock MEDIA-line path, with immediate rollback. It does not cover the owned channel (conflict X1) | 2026-11-03 | decided for the stock path only | releases/ACTIVATION_HANDOFF.md "Decided (2026-11-03 …)" |
| AG-G7 | D6: the launchd prune job is part of chart activation and is removed on rollback | 2026-11-03 | decided | Same |
| AG-G8 | Chart-trial rollback runs at once on completion or failure, without waiting; then verify analysis and charts are off | 2026-11-04 | decided | Same |
| AG-G9 | Phase 2 waits for Phase 1 acceptance (handoff G3); charts also need a media path through the owned send boundary | 2026-11-10 | decided | Session |
| AG-G10 | D5 follow-up: keep charts on after the trial | — | **pending owner** | releases/ACTIVATION_HANDOFF.md |

<a id="decisions-h"></a>
### H. WO-034 extraction v3 (track T1)

| Id | Decision | Date | Status | Source |
|---|---|---|---|---|
| AG-H1 | Baseline wording (94.69% is historical v2 dev), dev relabel before C, D freeze and gate, held-out set used once, Phase E scope; ruling 4 (subtype column decides) | 2026-11-03 | decided | WO-034 |
| AG-H2 | Paid-token order: C after the dev relabel and rescore are on main; D after C clears and the freeze; batch after E | 2026-11-03 | decided | WO-034 |
| AG-H3 | Final D decisions 1–5: one command, shared 600-call budget, sealed inputs, `score_v2` over 20 facets, v3 must meet or beat v2, support ≥10 and F1 ≥0.80 | 2026-11-04 | decided | WO-034 |
| AG-H4 | Phase E: a store-level comparison, then the owner's full-run decision under its own token | 2026-11-03 | decided | WO-034 |
| AG-H5 | Scoring points, transport, resume rule, ruling 9 v4 re-freeze; held-out exposure; failed-remark rules | 2026-11-04/05 | decided; merged in #163 and #164 | WO-034 on `main` |
| AG-H6 | Option (b): a failed or interrupted 600th call is exhausted and final, including on the last unanswered request; built on #164 | 2026-11-11 | decided; merged in #164 (`8d24fc1`) | Session; WO-034 on `main` |
| AG-H7 | Paid runs stay paused; no held-out inspection. Dev gold edits and human-pass judgments belong to the owner; model judgments stay `human_review: pending` | 2026-11-04 / 2026-11-11 | decided | Session; WO-034 on `main` |
| AG-H8 | The $10 figure is a plan number, never a cost | 2026-11-11 | decided | Session (no repo record) |
| AG-H9 | Still open: dev relabel, model, span-quality gate, proposed facets, each paid token. The bulk estimate (about $105) is a planning input, not authorized | — | **pending owner** | WO-034 |

<a id="decisions-i"></a>
### I. Earlier foundations

| Id | Decision | Status | Source |
|---|---|---|---|
| AG-I1 | The foundation decisions (comps rule, semantic search, routing, email gate and others). ADR statuses as each file states them: 0001 to 0007, 0009, 0013 and 0014 accepted; 0008 has no status line; 0011 implemented offline (2026-10-24); ADR-0012 compatibility-blocked (deterministic relay cancelled 2026-10-26); the WO-018 token target and budget | decided, in force | [DECISIONS.md](DECISIONS.md), [adrs/](adrs/), WO-018, [STATUS_HISTORY](STATUS_HISTORY.md#model-side-preview-check-2026-10-26) |

### Known conflicts in other docs

Each named source now carries a short dated note (2026-11-11) pointing to the agreed
position below; what the source recorded is kept, except runbook §7 (X4), a live
procedure, whose waiver sentence was replaced and whose dated note gives the earlier
wording. X1 still needs an owner decision.
Renumbered X1–X6 on 2026-11-11 (they were X3–X8; no X1 or X2 existed). The EVIDENCE_LOG
entry for `8d24fc1` says "X7", which is X5 here.

| Id | Conflict | Where | Agreed position |
|---|---|---|---|
| X1 | D5 approved the stock MEDIA-line chart path; the owned Cloud API channel is text-only | ACTIVATION_HANDOFF D5 | D5 does not cover the owned path; a media path and likely a fresh owner decision are needed |
| X2 | `plugins.deny: ["whatsapp"]` named as the stock exclusion | ADR-0016:20; WO-037:26 | Route (b), disable plus allowlist (AG-C16); the runbook forbids the deny when stock is absent |
| X3 | The A/B transport choice shown as open | Eligibility §5; WHATSAPP_TRANSPORT_RECOMMENDATION | Cloud API is the working transport (AG-C28); ADR-0017 not accepted |
| X4 | The runbook lets the owner waive Q1/Q3/Q5/Q7, opt-in, escalation and privacy policy for the owner-only test | Runbook §7 | No blanket waivers (AG-D6); none is waived |
| X5 | Provider-failure resume shown as open | WO-034 on main before #163/#164 | Resolved: #163 and #164 merged the decisions (AG-H5, AG-H6) |
| X6 | In-memory dedupe accepted for the smoke test | WO-038 | Superseded by WO-040 (AG-C8) |

<a id="pending-owner"></a>
## Pending owner inputs

None of these is given. Never record one as given until the owner gives it.

| Input | Blocks | Where recorded |
|---|---|---|
| Runbook G1 (written install approval) and the section 7 written approval | S1 | Runbook §1, §7; AG-C25 |
| T0 (the window start) | S1 | Runbook §1b |
| Q2 brokerage, Q4 MLS/IDX, Q6 hosted model and counsel; Q1, Q3, Q7 (folded into Q2) | S1 | Eligibility §4; AG-D1 to AG-D4 |
| Counsel's view on Q5 (AI disclosure is decided) | buyer rollout | AG-D5 |
| Dashboard access check result | S1 | Runbook 3.6b; AG-D8 |
| Self opt-in record, profile contact route, interim privacy-policy URL | S1 | AG-D6 |
| A2: pull the serving checkout past #189 and install the policy, as one owner step | S1 | AG-E5, AG-E6; runbook §1c |
| The 172-call routing eval (paid) | buyer rollout | AG-E2 |
| WO-034 paid tokens C, D and batch; the dev relabel; model; span gate; facets | T1 | AG-H2, AG-H9 |
| The rulings 1-7 re-read | after WO-034 Phase D | AG-F8 |
| Any new activation Phase 1 or Phase 2 paid session | S2, S3 | AG-F6 |
| Chart-trial grant, keeping charts on, and a D5-style decision for the owned media path | S3 | AG-G6, AG-G10 |
| Adding any buyer | S4 and rollout | AG-C9 |
| WO-031 build approval | none (not a release prerequisite) | AG-F7 |
| Sending the feed access request | S4, S6 | [FEED_ACCESS_REQUEST.md](FEED_ACCESS_REQUEST.md) |
| Placement of roadmap Phases 6, 7, 8 (beyond the fair-housing check) and 11 (beyond L4) | later stages | [Ladder open questions](AUTONOMY_LADDER.md#ideas-and-open-placement-questions) |

<a id="next-actions"></a>
## Open PRs and next actions

Open PRs on 2026-11-11 (`gh pr list`; heads change, so check `gh` for the current one). #189 (`e1ec3ab`), #163 (`ff12a71`) and #164 (`8d24fc1`) are merged and no longer open:

| PR | Base | Head | What it is | Waiting on |
|---|---|---|---|---|
| #179 | `main` | `ec92b00` | WO-036 token relay prototype | On hold (AG-C26) |
| #171 | `main` | `ac99755` | WO-036 Layer 3 proposal | Superseded (AG-C27) |

**Owner actions** (next first):
1. A2, when the owner chooses: pull main past #189 and install the policy as one owner
   step (runbook §1c). None is recorded.
2. Answer Q2, Q4 and Q6, and put the S1 safeguards in place (opt-in record, contact route,
   privacy-policy URL); report the dashboard access check.
3. Give or withhold runbook G1 and the section 7 approval, and choose T0.
4. Make the WO-034 dev gold relabels (Phase C prerequisite).

**Agent actions** (key-free; report heads and CI):
1. The `docs/` folder reorganization (AG-A11: index plus folders; pinned and frozen
   files stay) is PR #196, in review and not merged (2026-11-12), stacked on #193; #192
   has merged (`fa567f7`). The index is [docs/README.md](README.md).
2. WO-034 key-free work (T1).
3. Prepare the P1-0 evidence for S2 (T5).
4. Draft L2 work orders, each with a level line (T5).
5. Done (2026-11-11, the stale-text follow-up PR stacked on #192): the runbook §1 gate
   table (G4 met; G1 and G5 pending), the WO-041 Status (merged as `fb3293f`), README
   (#187 merged as `7a1fe36`), CLAUDE.md's active-assignment line (points here),
   ACTIVATION_HANDOFF §1, ACCEPTANCE_MATRIX's owned-send-path rows, TIMELINE's
   post-capstone section, WO-022's pointer (now to
   [STATUS_HISTORY](STATUS_HISTORY.md#capability-readiness-ladder-2026-11-02)), and a dated
   note at each source of conflicts X1–X6 (runbook §7 now says no blanket waivers). X1
   still needs an owner decision.

## Naming key

| Word | Meaning | Where defined |
|---|---|---|
| Stage S0–S6, track T1–T5 | The agreed general phases (this doc) | [Agreed plan](#agreed-plan) |
| Roadmap Phase 0–12 | Scope numbers. Never renumbered; they name scope, not order | [CAPABILITY_ROADMAP](CAPABILITY_ROADMAP.md#scope-by-roadmap-phase); ROADMAP_CROSSWALK |
| Activation Phase 1, Phase 2 | Release steps for the roadmap Phase 1 and 2 features (stages S2 and S3) | ACTIVATION_HANDOFF |
| Level L0–L4 | Autonomy levels | [AUTONOMY_LADDER](AUTONOMY_LADDER.md#the-five-levels) |
| WO sub-phases | Phases inside one work order, such as WO-034 Phases A–E | each work order |
| "Phase 0 bootstrap", "Phase 1 first slice" | The original weekly internship plan (history) | START_HERE §4; TIMELINE |
| Handoff G0–G5 | ACTIVATION_HANDOFF release gates (for example handoff G3 = activation Phase 1 accepted) | ACTIVATION_HANDOFF §2 |
| Runbook G1–G5 | WhatsApp install gates (for example runbook G4 = the install PR merged) | Runbook §1 |
| Script step P1-4 | Step 4 of the activation Phase 1 acceptance run (pool and solar search) | ACTIVATION_HANDOFF procedure 1; EVIDENCE_LOG |
| Matrix row P1-4 | Weighted feature rerank of recommend (not a release prerequisite) | ACCEPTANCE_MATRIX |
| WO-036 | The card-relay work (#171, #179). Branch `wo-036-whatsapp-channel-skeleton` actually carried WO-037 (#180, #181) | gh |
| AG-xN, Xn | Decision ids (groups A–I) and conflict ids (X1–X6) in this doc. Not the handoff's D1–D7 or C1–C6 | [Decisions](#decisions) |
| T0 | The start of the owner-only window: the section 3 `gateway stop`, chosen by the owner. A time, not a track (tracks are T1–T5) | Runbook §1b |
| A2 | The #189 go-live: pull the serving checkout past #189 and install its policy, as one owner step before the window. Not decision group A (AG-A*), not window decision A, not the runbook's pre-stage phases A-0, A-1 and A-3, and not ROADMAP_CROSSWALK item A2 (event alert drafting) | Runbook §1c; AG-E5 |
| Window decisions A–E | The five owner planning decisions for the window, recorded as AG-C19 to AG-C23. Not decision groups A–I of this register | WO-043; runbook §1b |
| Q1–Q7 | The open eligibility questions for the owner, brokerage or MLS (for example Q2 brokerage policy, Q6 hosted model) | [Eligibility §4](whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md#4-open-questions-only-the-owner-brokerage-or-mls-can-answer) |
| M1–M5 | The five messages of the owner smoke test | Runbook 7.5 |

## Doc map

| Doc | Responsibility | When to read |
|---|---|---|
| [START_HERE](START_HERE.md) | Entry point and reading order | First |
| [docs index](README.md) | Every docs/ folder and doc, the files pinned in place and why, and the old→new paths of the 2026-11-12 moves (AG-A11) | To find a doc, or an old path |
| STATUS (this doc) | The central agreed plan and current state | Before any work |
| [STATUS_HISTORY](STATUS_HISTORY.md) | Dated checkpoints and notes, moved verbatim | For how a decision came about |
| [CAPABILITY_ROADMAP](CAPABILITY_ROADMAP.md) | Capability detail per stage; durable scope of roadmap Phases 0–12 | When working on a stage |
| [ROADMAP_CROSSWALK](ROADMAP_CROSSWALK.md) | Every proposal item mapped to a roadmap phase | When checking scope coverage |
| [AUTONOMY_LADDER](AUTONOMY_LADDER.md) | The goal, levels, constants, measures, per-level plan and ideas | When ranking or scoping work |
| [ACTIVATION_HANDOFF](releases/ACTIVATION_HANDOFF.md) | Operator procedures for activation Phases 1 and 2 | In S2 and S3 |
| [ACCEPTANCE_MATRIX](releases/ACCEPTANCE_MATRIX.md) | Row-level acceptance for roadmap Phases 1 and 2 | In S2 and S3 |
| [WhatsApp runbook](runbooks/WHATSAPP_CHANNEL_INSTALL.md) | Install, window plan, A2 and rollback for the owned channel | In S1 |
| [EVIDENCE_LOG](EVIDENCE_LOG.md) | Measured and recorded evidence; append-only | For proof of any claim |
| [DECISIONS](DECISIONS.md) and [adrs/](adrs/) | Architecture decisions | Before a cross-component change |
| [TIMELINE](TIMELINE.md) | The original weekly map (historical) | For the internship record |

## History

Dated sections that used to live in STATUS.md, CAPABILITY_ROADMAP.md and
AUTONOMY_LADDER.md were moved verbatim to [STATUS_HISTORY.md](STATUS_HISTORY.md) on
2026-11-11. Every moved title, with its date, original file and link, is in the
[STATUS_HISTORY index](STATUS_HISTORY.md#index).
