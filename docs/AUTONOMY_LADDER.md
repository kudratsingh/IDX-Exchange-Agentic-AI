# Autonomy ladder

Owner decision, 2026-11-05. This page ranks every work order, roadmap phase and research
idea by the autonomy level it moves the system toward. This is the central autonomy
planning doc. The agreed general phases and current state are in
[STATUS](STATUS.md#agreed-plan); capability detail is in
[CAPABILITY_ROADMAP](CAPABILITY_ROADMAP.md#detail-by-stage). It relaxes no
existing gate: communication, consent and deployment rules stay exactly as they are until
a separately approved work order changes them.

> **This doc:** the goal; the five levels; the constants and measures; how levels map onto
> STATUS stages; the plan, gate and work items for each level; what is
> deferred; ideas and open placement questions.
> **Not here:** current readiness and decisions ([STATUS](STATUS.md#where-we-are-now));
> work orders, PRs and acceptance detail ([roadmap](CAPABILITY_ROADMAP.md#detail-by-stage));
> dated history ([STATUS_HISTORY part 3](STATUS_HISTORY.md#part-3)).
>
> **Contents:** [Goal](#the-goal) · [Levels](#the-five-levels) ·
> [Constants](#constants-at-every-level) · [Measures](#measures-per-level) ·
> [Levels and stages](#levels-and-stages) · [Plan by level](#plan-by-level)
> ([L0](#level-l0) · [L1](#level-l1) · [L2](#level-l2) · [L3](#level-l3) · [L4](#level-l4)) ·
> [Deferred](#deferred-because-they-move-no-level) ·
> [Ideas](#ideas-and-open-placement-questions) · [How to use](#how-to-use-this-page) ·
> [History](#history)

## The goal

An autonomous buyer's agent that works under a licensed human. The agent carries the
buyer's journey from first question to closing, and the human approves only the steps
that cannot be undone or that carry legal weight.

The license stays with the human: licensing law grants it to people, not software, and
the licensee answers for the work done under it. What a licensee may delegate depends on
the state's law and the brokerage's policy, which are the licensee's and the broker's
call; this page is not legal advice and claims no legal sufficiency for any gate. L4 is
bounded by that delegation, and the licensee keeps the duty to supervise. Full autonomy
with no human (L5) is treated as out of reach: as this project understands licensing
law, the license and the duty to supervise stay with a person. The project never builds
toward L5 and never claims it.

The self-improving, verifiable agent program (distilled extractor, grammar-constrained
router, calibrated cascade, RL from verifiable rewards, policy compilation, autonomous
refresh, self-audit) is the engine that makes the goal cheap enough to run and safe
enough to trust. It is a means to the goal, not a goal of its own.

## The five levels

| Level | The agent | The human |
|---|---|---|
| L0 | Answers questions over the listing, sales and document data | Asks, reads and acts alone |
| L1 | Recommends, alerts, analyses, and drafts messages that wait behind a gate | Sends every message and makes every decision |
| L2 | Keeps a buyer profile and a transaction state with deadlines, proposes the next step, checks affordability | Confirms each step before it happens |
| L3 | Contacts third parties, books showings, drafts offers on the standard forms, each action behind its own approval | Approves each action, one at a time |
| L4 | Runs the journey under a standing policy and operates itself: refresh, audit, rollback | Approves every irreversible or legal step, and anything the licensee may not delegate |

## Constants at every level

These do not loosen as the level rises. A work order that needs one relaxed stops and
asks (SAFETY_INVARIANTS.md).
- No client funds ever move through the agent: no deposits, earnest money, down payments
  or transfers. (Operating spend, such as model calls, happens only under consent tokens.)
- The human signs. The agent prepares; it never signs or binds anyone.
- No message leaves for anyone beyond the user's own chat (an email, or any third party)
  until a fair-housing check on that path is built and accepted. None exists yet; email
  today is drafted and goes out only after the owner's explicit approval.
- Licensed MLS data is read with a SELECT-only user, as now.
- A consent token is required for any paid call, any deletion and any gate change.
- EVIDENCE_LOG.md is append-only.

How the email line applies to owner-addressed, operator-approved email is an
[open question](#ideas-and-open-placement-questions); this page does not reinterpret it.

## Measures per level

A level is earned with numbers, not claimed by building it. For each level:
- **Autonomy rate (edit-free):** the share of journey steps the human did not change.
  An approval is not an edit: a step approved unchanged counts as edit-free and still
  counts as approved. The rate may never be raised by removing a required approval.
- **Approval load:** the approvals each journey stage needs, reported beside the rate.
- **Unauthorized actions:** steps taken without the required approval. Must be zero.
- **Verified-claim rate:** the share of factual claims that an independent check confirms.
- **Cost per journey stage:** spend to take one buyer through one stage.

Whether any journey measure has been taken: [STATUS](STATUS.md#where-we-are-now).
Component measurements (extraction development and held-out scores, the routing and CI
evaluations, the WO-020 and WO-028 measurement sets) are evidence toward a level, not
journey measures.

## Levels and stages

The stage column matches the Level column of the
[STATUS stage summary](STATUS.md#stage-summary); which roadmap phases each stage carries is
kept only in [STATUS](STATUS.md#how-roadmap-phases-map-onto-stages).

| Level | What earns it (gate) | STATUS stages | Measure focus |
|---|---|---|---|
| L0 | No gate defined by the 2026-11-05 decision (see [L0](#level-l0)) | [S0](STATUS.md#stage-s0) (L0/L1 baseline) | Verified-claim rate |
| L1 | Activation Phases 1 and 2 live-verified (ACTIVATION_HANDOFF) | [S0](STATUS.md#stage-s0) (baseline), [S1](STATUS.md#stage-s1) (prerequisite), [S2](STATUS.md#stage-s2), [S3](STATUS.md#stage-s3); track [T1](STATUS.md#track-t1) | Verified-claim rate; unauthorized actions |
| L2 | Profile, transaction state and affordability accepted with their measures | [S4](STATUS.md#stage-s4) | Autonomy rate; approval load |
| L3 | Each third-party action accepted behind its own approval | [S5](STATUS.md#stage-s5) | Unauthorized actions; approval load |
| L4 | The journey run under a standing policy, with self-operation | [S6](STATUS.md#stage-s6) | Cost per journey stage; all five |

The measure-focus column is a suggested emphasis, not an owner decision; every level
reports all five measures.
Current level: see [STATUS](STATUS.md#where-we-are-now).

## Plan by level

<a id="level-l0"></a>
### L0: answering

General phase: [STATUS S0](STATUS.md#stage-s0) · Capability detail: [roadmap S0](CAPABILITY_ROADMAP.md#detail-s0).

**Earned when:** the 2026-11-05 decision defines no L0 gate and lists no L0 work items.
Proposal, not agreed (see [open questions](#ideas-and-open-placement-questions)): fold L0
into the L1 gate through a fresh core acceptance.

**Work items:** none agreed at this level. The fresh core acceptance (releases/BASELINE_ACCEPTANCE.md,
WO-019) is S0 and track T4 work in STATUS; placing it under L0 is part of the proposal above.

**Prerequisites and constraints:** the constants above.

<a id="level-l1"></a>
### L1: recommend, alert, analyse, draft behind a gate

General phase: [STATUS S1](STATUS.md#stage-s1), [S2](STATUS.md#stage-s2), [S3](STATUS.md#stage-s3) ·
Capability detail: roadmap [S1](CAPABILITY_ROADMAP.md#detail-s1) ·
[S2](CAPABILITY_ROADMAP.md#detail-s2) · [S3](CAPABILITY_ROADMAP.md#detail-s3).

**Earned when:** activation Phase 1 (feature search, badges, explanations, saved feature
searches) and activation Phase 2 (bounded analysis, one chart trial), as defined in
releases/ACTIVATION_HANDOFF.md, are live-verified. Activation Phases 1 and 2 are the release steps
for the features built in roadmap Phases 1 and 2; roadmap phases are cited here by their
roadmap number.

**Work items (L1 close-out)**
- Activation Phases 1 and 2 (2026-11-05 decision), now run as stages S2 and S3 in the
  order the owner agreed on 2026-11-10/11 (STATUS AG-B3):
  - S1 first: the owned WhatsApp channel and the owner-only smoke test, with A2 (pulling
    main past #189 and installing the policy) as a separate owner step before the window.
  - S2: fresh activation Phase 1 acceptance from P1-0. The server-approved reply must reach
    the user unchanged (STATUS AG-F5).
  - S3: activation Phase 2, including a media path through the owned send boundary.
- WO-034 Phases B to D (track [T1](STATUS.md#track-t1)). Listed by the 2026-11-05 decision;
  not part of the L1 gate definition above.

Not placed: the relay guarantee work itself (track [T3](STATUS.md#track-t3), WO-036). A
proposal to list it here is in the [open questions](#ideas-and-open-placement-questions).

**Prerequisites and constraints:** outbound beyond the user's chat needs the fair-housing
check (constants). Each live or paid step keeps its own approval.

<a id="level-l2"></a>
### L2: buyer state and affordability

General phase: [STATUS S4](STATUS.md#stage-s4) · Capability detail: [roadmap](CAPABILITY_ROADMAP.md#detail-s4).

**Earned when:** the L2 work is accepted with the measures above.

**Work items**
- Transaction state machine and buyer profile (a new work order).
- Affordability search: the payment-budget half of roadmap Phase 3, taken forward now
  under that phase's existing prerequisites (disclosed finance assumptions, a separately
  approved rates source, no invented live rate).
- A transaction document agent for disclosures.
- The feed access request (FEED_ACCESS_REQUEST.md).

**Prerequisites and constraints.** From the platform terms as summarized in
[WHATSAPP_CLOUD_API_ELIGIBILITY](whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md) (requirements and
recommended actions there, not owner decisions):
- The channel is text-only and reply-only: no proactive sends (proactive sends are also
  withheld on this channel by STATUS AG-C11).
- The terms forbid training a shared model on WhatsApp data. The owner decision to exclude
  WhatsApp content from shared training and eval sets is still open (STATUS AG-D9).
- A buyer profile is built from thread content only, never from WhatsApp metadata beyond
  the thread.
- Counsel must confirm that the hosted model vendor's processing is allowed (Q6, pending).

From the owner's decisions in STATUS (AG-C8, AG-C9, AG-E3):
- Before adding buyers: persistent dedupe (done, #187), code-enforced disclosure (WO-042
  option 3b, not built) and separate written owner approval.

<a id="level-l3"></a>
### L3: third-party actions, each approved

General phase: [STATUS S5](STATUS.md#stage-s5) · Capability detail: [roadmap](CAPABILITY_ROADMAP.md#detail-s5).

**Earned when:** each third-party action is accepted behind its own approval, with the
measures above.

**Work items**
- Multi-party gated communication, built on the email approval gate.
- Showing scheduling with a confirmation the human reviews.
- Offer drafting from the standard forms, with roadmap Phase 3 valuation beneath it.

**Prerequisites and constraints:** the fair-housing check on the outbound path (roadmap
Phase 8) is built and accepted first; valuation needs a data access and licensing decision.

<a id="level-l4"></a>
### L4: standing policy and self-operation

General phase: [STATUS S6](STATUS.md#stage-s6) · Capability detail: [roadmap](CAPABILITY_ROADMAP.md#detail-s6).

**Earned when:** the journey runs under a standing policy with the measures above, and
the human still approves every irreversible or legal step.

**Work items**
- An autonomous refresh agent.
- Self-audit under a fixed budget.
- Outcome feedback.
- The cost engine: distilled extractor, constrained router, calibrated cascade, RL from
  verifiable rewards, policy compilation.
- Roadmap Phase 4 (events), which keeps its scope and waits for feed access and real
  change history.

**Prerequisites and constraints:** feed access; a hosting decision when L4 needs it.

## Deferred because they move no level

- The remote HTTP listener and interoperable clients.
- Brokerage rankings. They are also blocked by the present invariant (roadmap Phase 8).
- Voice delivery.
- Hosted operation, until L4 needs it. Hosting is part of roadmap Phase 12.

Measurement and benchmark work continues, as the evidence that each level is earned and
not as a goal of its own.

## Ideas and open placement questions

Every row is a **proposal, not agreed; owner to decide**. When the owner decides, record
it in STATUS first, then here.

| Question | Proposal (not agreed) | Notes |
|---|---|---|
| Where do roadmap Phases 6, 7, 8 and 11 sit? | Phase 6 near the L4 cost engine (selective schemas, verifier); Phase 7 split between the L2 profile (favorites) and L3 showings (open houses); Phase 8 as a whole at L3; Phase 11 at L4 | Today only Phase 8's fair-housing check and Phase 11's L4 items are placed |
| Deployment scope versus level | Treat owner-only versus allowlisted buyers as a separate axis from the level | WO-040 labels itself "L1 to L2" because it enables buyer rollout |
| Who is "the human" at L0/L1 when buyers chat directly? | Name the supervising licensee as the human for gated steps, and the buyer as the user | WO-042's referral line is the only rule so far |
| Does the constants' email line cover owner-addressed, operator-approved email? | State that exemption explicitly | Email has gone only to the owner's own inbox |
| When is the feed access request sent? | Send it during S4 so access exists by S6 | Its placement under L2 is agreed (2026-11-05); the timing is not, and sending needs owner approval (STATUS pending inputs) |
| Is there an L0 gate? | Fold L0 into the L1 gate through a fresh core acceptance (releases/BASELINE_ACCEPTANCE.md, WO-019) | The 2026-11-05 decision lists no L0 gate or work items |
| Where does the relay guarantee (T3, WO-036) sit? | Under L1 close-out, since its outcome is S2's acceptance condition (handoff G3) | STATUS T3 records it as not placed; #171 superseded, #179 on hold |

## How to use this page

Every new work order names, in its first section, the level it moves toward
(work_orders/TEMPLATE.md). A work order that moves no level carries an owner note saying
why it exists (CAPABILITY_ROADMAP.md, "Work-order and decision rules").
Record any level or plan change in STATUS first (owner rule, 2026-11-11), then detail it
here.

## History

The earlier "Where the system is" and "Order of work, by level" sections were moved
verbatim to [STATUS_HISTORY.md, part 3](STATUS_HISTORY.md#part-3) on 2026-11-11. The
2026-11-05 work items are carried forward in [Plan by level](#plan-by-level); anything
added since is either an owner decision cited from STATUS or marked as a proposal.
