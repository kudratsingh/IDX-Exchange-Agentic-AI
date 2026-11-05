# Autonomy ladder

Owner decision, 2026-11-05. This page ranks every work order, roadmap phase and research
idea by the autonomy level it moves the system toward. STATUS.md stays the record of what
is true today; this page records where the work is going and in what order. It relaxes no
existing gate: communication, consent and deployment rules stay exactly as they are until
a separately approved work order changes them.

## The goal

An autonomous buyer's agent that works under a licensed human. The agent carries the
buyer's journey from first question to closing, and the human approves only the steps
that cannot be undone or that carry legal weight.

The license stays with the human: licensing law grants it to people, not software, and
the licensee answers for the work done under it. What a licensee may delegate depends on
the state's law and the brokerage's policy, which are the licensee's and the broker's
call; this page is not legal advice and claims no legal sufficiency for any gate. L4 is
bounded by that delegation, and the licensee keeps the duty to supervise. Full autonomy
with no human (L5) is not legally reachable; this project never builds toward it and
never claims it.

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
- Every outbound message passes a fair-housing check before it leaves. Today the only
  outbound path is the approved email; a dedicated check on it is not built yet and is
  required before any message to a third party.
- Licensed MLS data is read with a SELECT-only user, as now.
- A consent token is required for any paid call, any deletion and any gate change.
- EVIDENCE_LOG.md is append-only.

## Measures per level

A level is earned with numbers, not claimed by building it. For each level:
- **Autonomy rate (edit-free):** the share of journey steps the human did not change.
  An approval is not an edit: a step approved unchanged counts as edit-free and still
  counts as approved. The rate may never be raised by removing a required approval.
- **Approval load:** the approvals each journey stage needs, reported beside the rate.
- **Unauthorized actions:** steps taken without the required approval. Must be zero.
- **Verified-claim rate:** the share of factual claims that an independent check confirms.
- **Cost per journey stage:** spend to take one buyer through one stage.

None of these journey-level measures has been taken yet. Component measurements exist
(extraction development and held-out scores, the routing and CI evaluations, the WO-020
and WO-028 measurement sets); they are evidence toward a level, not journey measures.

## Where the system is

**L1 capabilities built; L1 acceptance pending.** The assistant answers, recommends,
checks prices against comps, analyses and drafts email behind the human approval gate.
L1 is complete only when activation Phase 1 (feature search, badges, explanations, saved
feature searches) and activation Phase 2 (bounded analysis, one chart trial), as defined
in ACTIVATION_HANDOFF.md, are live-verified. These activation phases are not the roadmap
phases numbered below. The evidence is the readiness ladder in STATUS.md, "Post-merge
readiness, 2026-11-02" (merged, installed, enabled, live-verified), which records these
capabilities as merged but not enabled or live-verified. Since then the activation
Phase 1 code was installed at `71fb39e` on 2026-11-05 with every switch still off; STATUS
records that with the Phase 1 acceptance. No feature is enabled or live-verified yet,
activation Phase 2 is not installed, and the core assistant's fresh live acceptance is
still open.

## Order of work, by level

**L1 close-out**
- Activation Phase 1 and activation Phase 2 (ACTIVATION_HANDOFF.md, ACCEPTANCE_MATRIX.md).
- WO-034 Phases C and D.

**L2**
- Transaction state machine and buyer profile (a new work order).
- Affordability search: the payment-budget half of roadmap Phase 3, taken forward now.
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

## Deferred because they move no level

- The remote HTTP listener and interoperable clients.
- Brokerage rankings.
- Voice delivery.
- Hosted operation, until L4 needs it.

Measurement and benchmark work continues, as the evidence that each level is earned and
not as a goal of its own.

## How to use this page

Every new work order names, in its first section, the level it moves toward
(work_orders/TEMPLATE.md). A work order that moves no level carries an owner note saying
why it exists (CAPABILITY_ROADMAP.md, "Work-order and decision rules").
