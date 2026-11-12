# Combined capability roadmap

> **This doc:** for each STATUS stage and track, its capabilities, work orders and PRs,
> acceptance criteria and gates; the durable scope of roadmap Phases 0–12; the work-order
> rules.
> **Not here:** the order of work, current state, next actions and decisions
> ([STATUS](STATUS.md#agreed-plan)); level definitions and the per-level plan
> ([ladder](AUTONOMY_LADDER.md#plan-by-level)); dated checkpoints
> ([STATUS_HISTORY part 2](STATUS_HISTORY.md#part-2)).
> **Read with:** [STATUS](STATUS.md), [ROADMAP_CROSSWALK](ROADMAP_CROSSWALK.md),
> [ACTIVATION_HANDOFF](ACTIVATION_HANDOFF.md), [ACCEPTANCE_MATRIX](ACCEPTANCE_MATRIX.md).
>
> **Contents:** [Phase outcomes and prerequisites](#phase-outcomes-and-prerequisites) ·
> [Detail by stage](#detail-by-stage) ([S0](#detail-s0) · [S1](#detail-s1) · [S2](#detail-s2) ·
> [S3](#detail-s3) · [S4](#detail-s4) · [S5](#detail-s5) · [S6](#detail-s6) ·
> [tracks](#detail-tracks)) ·
> [Scope by roadmap phase](#scope-by-roadmap-phase) ·
> [Work-order and decision rules](#work-order-and-decision-rules) ·
> [Presentation](#presentation-and-visualization-direction) · [History](#history)

This file holds capability detail per stage; the order of work is in
[STATUS](STATUS.md#agreed-plan). Since 2026-11-05 work is ranked by autonomy level
([ladder](AUTONOMY_LADDER.md)), so the stage order in STATUS, not the phase number, sets
the order of work.

Provenance: plan saved 2026-10-25 from the user's two proposals;
ROADMAP_CROSSWALK.md accounts for every proposed item. The user authorized
starting the work in order, with key-free preparation first and separately granted
live runs. Estimates in the proposals are planning inputs, not delivery promises.
Descriptions of peer projects have not been independently verified and are not
product-performance evidence. No source handbook or brochure text is reproduced.

## Phase outcomes and prerequisites

The outcome and required evidence of each roadmap phase, in phase-number order. Phase
numbers are scope numbers, never renumbered, and this table sets no order of work. The
order and all state are kept in STATUS only, and the stage and level of each phase are set
in STATUS, [How roadmap phases map onto stages](STATUS.md#how-roadmap-phases-map-onto-stages).
The fuller scope of each phase is under [Scope by roadmap phase](#scope-by-roadmap-phase).

| Phase | Outcome | Required evidence / prerequisites |
|---|---|---|
| 0 | Finish current acceptance | model/effort configured; guard CI/merge; consented routing/e2e; reviewed email receipt; relevance marks; cost record; demo/video/reflection |
| 1 | Enrich public remarks | eight facets, conservative abbreviation handling, attributed property facts, deal signals, bounded summaries, discrepancy flags; versioned extraction and a human-reviewed held-out set |
| 2 | Bounded Python analyst with charts | WO-017 isolation/deadline/output tests; container decision; code-owned projection; trusted figure checks; working image relay |
| 3 | Valuation and payment-budget search | data access/licensing decision; temporal model ladder and calibrated range; disclosed finance assumptions; separately approved rates source |
| 4 | Events worth drafting an alert for | real change history, viewed/favorite state, deterministic interruption policy, replay/idempotency and retained operator approval |
| 5 | Stronger measurement | independent SQL answer checks, held-out tool/argument/answer scores, local-model adapter, reproducible latency/retrieval benchmark and threat model |
| 6 | Compound planning and inference controls | visible bounded plans, progress, payload coverage checks, ambiguity experiments, bounded prefetch, optional budgeted verifier and selective schemas |
| 7 | Buyer workflow breadth | open-house schema/access, validated dates, destination/district filters, comparison sensitivity, explicit sorting and isolated favorites |
| 8 | Domain checks and answerability | labeled fairness/answerability evaluation, reason-coded limitations and an operator audit; no claim of legal certification or perfect real-world recall |
| 9 | Reusable MCP/API product | resources/prompts, client console, container packaging and authenticated/rate-limited HTTP with correct identity boundaries |
| 10 | Rich channel and transaction workflows | media, maps, private shortlist, official WhatsApp channel, interactive refinements, voice, per-user documents, handoff and scheduling, personalized brief/PDF |
| 11 | Feedback and routing research | consented feedback path, leakage-safe ranking, simulator with verifiable goals, routing training/distillation and held-out regression before any replacement |
| 12 | Refresh and hosting | coordinator feed access; versioned refresh; approved cloud account/services/budget controls; private hosted stores, scheduler/webhook, IaC/OIDC and recovery/device rehearsal |

Phase 5 is listed in the user's revised order, but a minimal evaluation set is a
prerequisite inside every earlier phase. Do not build unmeasured features while
waiting for the larger measurement project. The Phase 12 feed access request:
[Phase 12](#roadmap-phase-12).

## Detail by stage

One section per STATUS stage and track. Each opens with its link back to STATUS, where
its gate, exit and state live. The tables below map work orders to PRs only; whether each
is merged, installed or accepted is in STATUS.

<a id="detail-s0"></a>
### S0: Foundations and capstone close-out

Plan, gate and state: [STATUS S0](STATUS.md#stage-s0). Level: [L0](AUTONOMY_LADDER.md#level-l0)/[L1](AUTONOMY_LADDER.md#level-l1) baseline.

**Capabilities:** search and refinement, multi-turn memory, tracing, market statistics,
semantic search, recommendations with a comp check, document answers, routing across five
roles, email drafts behind the approval gate, saved searches and alerts; the code of
roadmap Phases 1, 2 and 5 (see S2, S3 and T2).

**Work orders and PRs**

| WO | PR |
|---|---|
| WO-000 to WO-013 | listed in [START_HERE §4](START_HERE.md#4-where-we-are) |
| WO-009 saved searches and alerts | #82 |
| WO-014 end to end, WO-016 capstone | — |
| WO-015 email approval gate and safety | #81, #86 |
| WO-019 base acceptance | — |

**Acceptance criteria:** a fresh core end-to-end acceptance on the configured route
(BASELINE_ACCEPTANCE.md, WO-019); the capstone items under [T4](#detail-t4).

**Gates:** consent tokens for paid runs and sends; the email approval gate.

**References:** [ARCHITECTURE](ARCHITECTURE.md), [CAPSTONE](CAPSTONE.md),
[BASELINE_ACCEPTANCE](BASELINE_ACCEPTANCE.md), [roadmap Phase 0](#roadmap-phase-0).

<a id="detail-s1"></a>
### S1: Owned WhatsApp channel and owner-only smoke test

Plan, gate and state: [STATUS S1](STATUS.md#stage-s1). Level: [L1](AUTONOMY_LADDER.md#level-l1).

**Capabilities:** a project-owned WhatsApp channel whose only send path verifies the
approved reply first; the Cloud API transport and signed webhook; persistent, bounded
inbound dedupe; install readiness; the window plan; clear AI disclosure and a digit-free
human referral (WO-042, brought live by the A2 owner step). This is roadmap Phase 10's
"official WhatsApp channel", pulled forward.

**Work orders and PRs**

| WO | PR |
|---|---|
| WO-037 owned channel (Path A) | #180, #181, #182, #183 |
| WO-038 Cloud API transport and webhook | #184 |
| WO-039 Cloud API wiring, off by default | #185, #186 |
| WO-040 persistent dedupe | #187 |
| WO-041 install readiness (runbook G4) | #190 |
| WO-043 window plan, A2, Cloudflare scope | #191 |
| WO-042 AI disclosure and human referral | #189 |

**Acceptance criteria:** A2 verified on stock; the five-message owner smoke test
(runbook 7.5) passes; rollback and stock restore verified (runbook 7.6). Transport and the
agreed window shape: [STATUS decisions C](STATUS.md#decisions-c).

**Gates:** runbook G1–G5; the section 7 written approval; T0; Q2, Q4 and Q6 answered;
the S1 safeguards. Which of these are met: [STATUS S1](STATUS.md#stage-s1).

**References:** [runbook](runbooks/WHATSAPP_CHANNEL_INSTALL.md) §1, §1b, §1c, §3, §7;
ADR-0016; ADR-0017; [eligibility](WHATSAPP_CLOUD_API_ELIGIBILITY.md).

<a id="detail-s2"></a>
### S2: Fresh activation Phase 1 acceptance

Plan, gate and state: [STATUS S2](STATUS.md#stage-s2). Level: [L1](AUTONOMY_LADDER.md#level-l1).

**Capabilities:** remark-feature search on the audited v5 store; card badges;
shared-feature explanations; saved feature searches; the relay checks (Layers 1–2).

**Work orders and PRs**

| WO | PR |
|---|---|
| WO-018 remarks enrichment | see WO-018 Status |
| WO-021 enrichment integration | #134, #135, #136, #137 |
| WO-023 enrichment access | #142 |
| WO-024 feature explanations | #149 |
| WO-025 saved feature searches | #150 |
| WO-035 v5 store | #155 |
| Relay Layers 1–2 | #169, #170, #172 |
| WO-031 recommend feature filter | — ([STATUS AG-F7](STATUS.md#decisions-f)) |

Other roadmap Phase 1 work, tracked as ACCEPTANCE_MATRIX rows P1-8 (omission audit) and
P1-9 (refresh preflight) but not part of S2 acceptance: the refresh preflight is #137,
under WO-021 above; the omission pilots are WO-026 (#144) and WO-033 (#154, #157).

**Acceptance criteria:** handoff G3, ACTIVATION_HANDOFF procedures 1–4 all recorded:
P1-0 onward in the order search → badges → explanations → saved feature searches
(ACCEPTANCE_MATRIX rows P1-1, P1-2, P1-3 and P1-5), one switch per restart, every card
turn `reason=exact`, and the server-approved reply reaching the user unchanged. Matrix
rows P1-4 (weighted rerank) and P1-7 (deal-signal alerts, ineligible) are not release
prerequisites ([STATUS AG-F7, AG-F10](STATUS.md#decisions-f)).

**Gates:** handoff G2 (install and the C3a off probe) and handoff G3 (activation Phase 1
accepted).

**References:** [ACTIVATION_HANDOFF](ACTIVATION_HANDOFF.md) procedures 1–4,
[ACCEPTANCE_MATRIX](ACCEPTANCE_MATRIX.md), [roadmap Phase 1](#roadmap-phase-1).

<a id="detail-s3"></a>
### S3: Activation Phase 2, bounded analysis then charts

Plan, gate and state: [STATUS S3](STATUS.md#stage-s3). Level: [L1](AUTONOMY_LADDER.md#level-l1).

**Capabilities:** the bounded analyst (`bounded_analysis`) in an isolated worker; chart
delivery with a one-shot trial and automatic rollback; a media path through the owned
send boundary (needed for chart acceptance).

**Work orders and PRs**

| WO | PR |
|---|---|
| WO-017 bounded analysis | #85, #138 |
| WO-027 analysis integration | #146, #156, #165 |
| WO-030 chart delivery and trial rollback | #148, #166 |
| Owned-channel media path | — |

**Acceptance criteria:** ACCEPTANCE_MATRIX rows P2-1 to P2-3; charts actually delivered
(the text fallback alone does not pass P2-3); the trial rolls back at once; the launchd
prune job installed with chart activation and removed on rollback.

**Gates:** handoff G5 (Phase 2 install) after handoff G3; ADR-0013 (accepted 2026-10-28);
procedure 5b; a separate approval for the media path on the owned channel.

**References:** [ANALYSIS_DESIGN](ANALYSIS_DESIGN.md), [CHART_DELIVERY](CHART_DELIVERY.md),
[roadmap Phase 2](#roadmap-phase-2), [presentation direction](#presentation-and-visualization-direction).

<a id="detail-s4"></a>
### S4: L2 buyer profile, transaction state and affordability search

Plan, gate and state: [STATUS S4](STATUS.md#stage-s4). Level: [L2](AUTONOMY_LADDER.md#level-l2).

**Capabilities:** a buyer profile and a transaction state machine with deadlines;
affordability search (the payment-budget half of Phase 3); a transaction document agent
for disclosures (Phase 10's per-user documents); the feed access request (Phase 12).

**Work orders and PRs**

| Item | WO / PR |
|---|---|
| Transaction state and buyer profile | — |
| Affordability search | — |
| Transaction document agent | — |
| Feed access request | FEED_ACCESS_REQUEST.md ([Phase 12](#roadmap-phase-12)) |

**Acceptance criteria:** affordability shows disclosed finance assumptions from a
separately approved rates source and never invents a live rate, qualification or
guaranteed affordability; the profile is built from thread content only; the ladder's
L2 measures.

**Gates:** before adding any buyer, code-enforced disclosure (WO-042 option 3b) built and
separate written owner approval; counsel's view on the hosted model (Q6).

**References:** [roadmap Phase 3](#roadmap-phase-3), [Phase 10](#roadmap-phase-10),
[Phase 12](#roadmap-phase-12), [eligibility](WHATSAPP_CLOUD_API_ELIGIBILITY.md).

<a id="detail-s5"></a>
### S5: L3 valuation, offer drafting, gated communication and showings

Plan, gate and state: [STATUS S5](STATUS.md#stage-s5). Level: [L3](AUTONOMY_LADDER.md#level-l3).

**Capabilities:** valuation (the Phase 3 valuation half); offer drafting on the standard
forms; gated multi-party communication, built on the email approval gate (WO-015);
showing scheduling with a confirmation the human reviews; handoff (Phase 10).

**Work orders and PRs:** none yet. The email approval gate (WO-015) is the foundation.

**Acceptance criteria:** a calibrated valuation range from the temporal model ladder; each
third-party action behind its own approval; the Phase 8 fair-housing evaluation passed on
the outbound path; the ladder's L3 measures.

**Gates:** a data access and licensing decision for valuation; the fair-housing check
built and accepted before any message beyond the user's own chat.

**References:** [roadmap Phase 3](#roadmap-phase-3), [Phase 8](#roadmap-phase-8),
[Phase 10](#roadmap-phase-10).

<a id="detail-s6"></a>
### S6: L4 event alerts and self-operation

Plan, gate and state: [STATUS S6](STATUS.md#stage-s6). Level: [L4](AUTONOMY_LADDER.md#level-l4).

**Capabilities:** event alert drafts (Phase 4); an autonomous refresh agent (Phase 12);
self-audit under a fixed budget; outcome feedback and the cost engine (Phase 11).

**Work orders and PRs:** none yet. The refresh preflight and the omission pilots are
roadmap Phase 1 work, listed under [S2](#detail-s2).

**Acceptance criteria:** Phase 4's real change history, viewed and favorite state,
deterministic interruption policy, replay and idempotency, and retained operator
approval; the ladder's L4 measures.

**Gates:** feed access and real change history; a hosting decision when L4 needs it.

**References:** [roadmap Phase 4](#roadmap-phase-4), [Phase 11](#roadmap-phase-11),
[Phase 12](#roadmap-phase-12).

<a id="detail-tracks"></a>
### Parallel tracks

<a id="detail-t1"></a>
#### T1: WO-034 extraction v3

Plan and state: [STATUS T1](STATUS.md#track-t1). Level: listed under L1 close-out.

| WO | PR |
|---|---|
| WO-034 Phase A | #153 |
| WO-034 v4 re-freeze | #163 |
| WO-034 Phase B | #164 |

Scope and phases: WO-034. Paid-token order, option (b) and the pause:
[STATUS decisions H](STATUS.md#decisions-h).

<a id="detail-t2"></a>
#### T2: Measurement

Plan and state: [STATUS T2](STATUS.md#track-t2). WO-020 (#139, #140) and WO-028 (#145).
Scope: [roadmap Phase 5](#roadmap-phase-5).

<a id="detail-t3"></a>
#### T3: Relay guarantee (WO-036)

Plan, state and the PRs involved: [STATUS T3](STATUS.md#track-t3). Capability: the
approved card reaches the user unchanged, checked model-free after every card turn (relay
Layers 1–2) and, on the owned channel, by the verified send boundary ([S1](#detail-s1)).
Acceptance: the S2 condition that the server-approved reply reaches the user unchanged
(handoff G3).

<a id="detail-t4"></a>
#### T4: Capstone close-out

Plan and state: [STATUS T4](STATUS.md#track-t4). Items: fresh core end-to-end; demo and
backup recording with private details redacted; the intern's own reflection; billing and
cost record from the console; rotating the intended old provider credential (not a key
still needed for embeddings; keep IDX_SENDER_KEY stable); the optional alert schedule after
manual rehearsal. Portfolio deployment stays disabled.

<a id="detail-t5"></a>
#### T5: L2 scoping and acceptance-evidence preparation

Plan and state: [STATUS T5](STATUS.md#track-t5). Draft the L2 work orders (each names its
level) and prepare the P1-0 evidence for S2.

## Scope by roadmap phase

The durable scope of each roadmap phase. Phase numbers are never renumbered. Each section
opens with its placement, repeated from the
[STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages) for navigation (the map is the
authority), and links to its capability detail here.

<a id="roadmap-phase-0"></a>
### Phase 0: finish current acceptance

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S0](STATUS.md#stage-s0), [T4](STATUS.md#track-t4). Detail: [S0](#detail-s0), [T4](#detail-t4).

The capstone's own acceptance: the configured model route, guarded CI, consented routing
and end-to-end runs, reviewed email receipt, relevance marks, a cost record, and the demo,
recording and reflection. The remaining items are in [T4](#detail-t4); the original
operator sequence is in [STATUS_HISTORY](STATUS_HISTORY.md#phase-0-operator-sequence).

<a id="roadmap-phase-1"></a>
### Phase 1: remarks enrichment

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S0](STATUS.md#stage-s0) (code), [S2](STATUS.md#stage-s2) (acceptance), [T1](STATUS.md#track-t1).
Detail and work orders: [S2](#detail-s2), [T1](#detail-t1).

Start with a frozen vocabulary, deterministic normalization and invented test cases.
Treat extracted facts as candidates with evidence and polarity, not new ground truth.
Handle negation, uncertainty, past/future claims and contradictions before a facet
can be used as a filter. A missing mention is unknown. Structured columns remain the
current source of hard constraints; a mismatch becomes a reviewed flag, not an
unannounced correction. No contact/private fields are extracted or logged.

Then define/label distinct dev and held-out sets with the human, measure each facet
and entity, implement offline extraction and summaries, and integrate only accepted
facets into query/ranking/card/report contracts. Any model extraction/summarization
run needs an explicit provider budget. Version normalizer, dataset, extractor and
index together; re-embedding requires a fresh run grant and preserves old artifacts.
No query-only normalization against an incompatible old index.

<a id="roadmap-phase-2"></a>
### Phase 2: bounded analyst with charts

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S0](STATUS.md#stage-s0) (code), [S3](STATUS.md#stage-s3). Detail: [S3](#detail-s3).

The analyst design is ANALYSIS_DESIGN.md. A 50-row exploratory sample is not an
area population statistic. Containers follow ADR-0013, accepted 2026-10-28;
there is no host-exec fallback. JSON shape alone does not verify a calculation.

<a id="roadmap-phase-3"></a>
### Phase 3: valuation and payment-budget search

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S4](STATUS.md#stage-s4) (payment-budget half), [S5](STATUS.md#stage-s5) (valuation half).
Detail: [S4](#detail-s4), [S5](#detail-s5).

For valuation, compare a simple baseline, tree, forest and boosting models using
newest-period holdout plus rolling validation. Fit imputers/outlier thresholds only
on training data. Report error by price band/type/place and calibrate prediction
ranges on held-out data. Attribution explains a fitted model, not causation. Do not
transfer training exclusions into existing market statistics without a separate
reviewed contract change. No comparison of bathroom values across the two feeds.
Offline training data access must be reviewed; runtime row caps and no-export rules
are not bypassed by a paginated training request. No accuracy is claimed in advance.

Payment search must show down payment, rate/date, term, tax, insurance and HOA
assumptions; no invented live rate, qualification or guaranteed affordability.

<a id="roadmap-phase-4"></a>
### Phase 4: events worth drafting an alert for

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S6](STATUS.md#stage-s6). Detail: [S6](#detail-s6).

Events need refreshed snapshots and replayable history. The current fixed snapshot
cannot establish a new price drop, a new market entry or a future prediction. Model
scores are not alert triggers until calibrated and evaluated; summaries never grant
permission to send a message or email.

<a id="roadmap-phase-5"></a>
### Phase 5: stronger measurement

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S0](STATUS.md#stage-s0) (code), [T2](STATUS.md#track-t2). Detail: [T2](#detail-t2).

Keep training, development and final evaluation separate. SQL truth checks must be
independent of the model and of the function under test. A local model avoids API
charges, not hardware/operating cost. Record selection accuracy separately from
argument validity, numeric correctness, source support and successful task completion.
Use p50/p95, cold/warm definitions and manifest row counts for retrieval benchmarks;
the proposed sub-100 ms target is a goal, not an observed result.

<a id="roadmap-phase-6"></a>
### Phase 6: compound planning and inference controls

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): unplaced; an [open question](AUTONOMY_LADDER.md#ideas-and-open-placement-questions).

A second model is a critique signal, not a fact authority. Prefetch needs a fixed
budget and cannot spend speculatively without consent. Elicitation/progress must be
proved against the actual MCP/OpenClaw/channel versions.

<a id="roadmap-phase-7"></a>
### Phase 7: buyer workflow breadth

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): unplaced; an [open question](AUTONOMY_LADDER.md#ideas-and-open-placement-questions).

Open houses and district
boundaries require confirmed schemas, time zones, access and freshness; do not infer
them from the two current tables. Place queries use explicit destinations/distances,
never demographic steering or school ratings. Favorites need the approved owner/
identity scope.

<a id="roadmap-phase-8"></a>
### Phase 8: domain checks and answerability

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S5](STATUS.md#stage-s5) (the fair-housing check before outbound only); the rest
unplaced. Detail: [S5](#detail-s5).

The suggested fairness recall/precision figures are evaluation targets on a defined,
reviewed dataset, not a legal guarantee. No protected enforcement change is implied.
Named brokerage rankings are blocked by the present no-office/contact-field rule.
Do not select office names because they are described as public; a separate human
invariant decision is required before implementing that item or an alternative.
Brokerage rankings are also deferred by the ladder (they move no level).

<a id="roadmap-phase-9"></a>
### Phase 9: reusable MCP/API product

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): deferred ([ladder](AUTONOMY_LADDER.md#deferred-because-they-move-no-level)).

Exposing HTTP requires new authentication, client isolation and rate
limits before any remote listener; approval and send stay out of MCP/HTTP tools.

<a id="roadmap-phase-10"></a>
### Phase 10: rich channel and transaction workflows

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)), by item: [S1](STATUS.md#stage-s1) (official channel), [S3](STATUS.md#stage-s3) (media),
[S4](STATUS.md#stage-s4) (per-user documents), [S5](STATUS.md#stage-s5) (handoff and scheduling); voice deferred; the
rest unplaced. Detail: [S1](#detail-s1), [S3](#detail-s3), [S4](#detail-s4), [S5](#detail-s5).

Verify official channel access and policy before interactive/voice delivery. Private
shortlist/document URLs require identity, expiry and isolation. Per-user document
reading must bound uploads, retain page provenance, treat text as untrusted and offer
operator-controlled retention. Showing/calendar actions need explicit reviewable
confirmation, not a fabricated booking. Photo processing requires source rights and
an approved one-time embedding/vision budget. Personal reports use saved user scope
and snapshot comparisons; no change narrative is invented from a static dataset.

<a id="roadmap-phase-11"></a>
### Phase 11: feedback and routing research

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S6](STATUS.md#stage-s6) (outcome feedback and the cost engine); the rest unplaced.
Detail: [S6](#detail-s6).

Feedback collection and model training need privacy/licensing decisions. Simulated
users do not stand in for human acceptance. A smaller router replaces the existing
route only after held-out parity and safety checks; reward optimization never trains
on final acceptance cases. No new services or training jobs are adopted by this plan.

<a id="roadmap-phase-12"></a>
### Phase 12: refresh and hosting

Placement ([STATUS map](STATUS.md#how-roadmap-phases-map-onto-stages)): [S4](STATUS.md#stage-s4) (the feed request), [S6](STATUS.md#stage-s6) (refresh); hosting
deferred until L4 needs it. Detail: [S4](#detail-s4), [S6](#detail-s6).

The coordinator feed access request is FEED_ACCESS_REQUEST.md, listed under L2; access is
never assumed, feed access is needed for S6, and sending the request needs owner approval.
Whether it has been sent, and when to send it:
[STATUS pending inputs](STATUS.md#pending-owner). Actual ingestion waits for access,
rights, schema and refresh semantics. Cloud architecture needs an explicit hosting
decision. Budget alarms are not a universal hard spending cap; distinguish
alerts, quotas and tested enforcement. Preserve SELECT-only MLS access, private
storage, operator secrets, owner isolation and immutable approval records. Rollout
requires infrastructure review, failure recovery, observability and a tested rollback.

## Work-order and decision rules

The roadmap is authorized direction, not blanket consent to spend, alter enforcement,
add services/dependencies, read unapproved private source material, contact people,
relax invariants or deploy publicly. Each WO names owned files, inputs, fixtures,
acceptance and stop conditions. Retain all run evidence; merge only on green CI.
STATUS.md is the central plan: every agreed decision or plan change is recorded there
(owner rule, 2026-11-11, [STATUS AG-A10](STATUS.md#decisions-a)). This file records
capability detail.

Every new work order names, in its first section, the autonomy level it moves toward
(`AUTONOMY_LADDER.md`), and links its STATUS stage. A work order that moves no level needs
an owner note saying why it exists. (Owner decision, 2026-11-05.)

## Presentation and visualization direction

The user requested a polished frontend and sophisticated, effective visualizations.
For the Phase 2 analyst and later reports, heat maps and shortlist surfaces, design
accessible responsive charts that communicate units, dates, uncertainty and source
context. Evaluate established visualization libraries such as D3 or Plotly for the
specific chart types; use 3D (such as Three.js) only when it improves the data's
interpretation and remains usable. Choose and document any dependency when its
phase is implemented. Local private labeling remains offline, without third-party
assets or network requests, and does not need a charting library.

Chart acceptance and the media path: [S3](#detail-s3).

## History

The roadmap's earlier "Current checkpoint", its "Historical checkpoint notes" and the
original "Phase 0: operator sequence" were moved verbatim to
[STATUS_HISTORY.md, part 2](STATUS_HISTORY.md#part-2) on 2026-11-11.
