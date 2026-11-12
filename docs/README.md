# docs/ index

Every doc in this folder, grouped by folder, with what it is for. Start with
[START_HERE.md](START_HERE.md), then [STATUS.md](STATUS.md) (the central plan). This index
was added on 2026-11-12 when 22 docs moved into folders (STATUS decision AG-A11). A doc
that names an old path still means the same file: the [old→new table](#moved-on-2026-11-12)
at the end gives each new path.

**Contents:** [Top level](#top-level) · [releases/](#releases) · [whatsapp/](#whatsapp) ·
[enrichment/](#enrichment) · [runbooks/](#runbooks) · [adrs/](#adrs) · [data/](#data) ·
[Pinned in place](#pinned-in-place) · [Moved on 2026-11-12](#moved-on-2026-11-12)

## Top level

**Entry points and plan**
- [START_HERE.md](START_HERE.md): orientation and reading order.
- [STATUS.md](STATUS.md): the central agreed plan, current state, decisions and doc map.
- [STATUS_HISTORY.md](STATUS_HISTORY.md): dated checkpoints moved verbatim from the plan docs.
- [CAPABILITY_ROADMAP.md](CAPABILITY_ROADMAP.md): capability detail per stage; roadmap phase scope.
- [AUTONOMY_LADDER.md](AUTONOMY_LADDER.md): the goal, the autonomy levels L0–L4 and the plan by level.
- [ROADMAP_CROSSWALK.md](ROADMAP_CROSSWALK.md): every proposal item mapped to a roadmap phase.
- [TIMELINE.md](TIMELINE.md): the original week-by-week course map (historical).
- [FEED_ACCESS_REQUEST.md](FEED_ACCESS_REQUEST.md): the draft MLS feed access request (not sent).

**Rules and safety**
- [AGENT_RULES.md](AGENT_RULES.md): the coding agent's conduct rules and consent tokens.
- [SAFETY_INVARIANTS.md](SAFETY_INVARIANTS.md): product safety rules every line of code keeps.

**Architecture, contracts and decisions**
- [ARCHITECTURE.md](ARCHITECTURE.md): the implemented architecture and request path.
- [CONTRACTS.md](CONTRACTS.md): domain models, tool signatures and the error envelope.
- [DECISIONS.md](DECISIONS.md): the cross-component decision log (ADRs are in [adrs/](#adrs)).
- [ROUTING.md](ROUTING.md): the routing contract table, message to skill to tool.
- [ANALYSIS_DESIGN.md](ANALYSIS_DESIGN.md): the WO-017 analysis design (superseded by ADR-0013).
- [RECOMMEND_FEATURES_DECISION.md](RECOMMEND_FEATURES_DECISION.md): the feature-aware recommendation decision draft.

**Evaluation and evidence**
- [EVALUATION.md](EVALUATION.md): eval case format, check types and measurement sets.
- [EVIDENCE_LOG.md](EVIDENCE_LOG.md): the append-only log of measured and recorded evidence.
- [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md): the finished semantic relevance review.

**Operations and feature guides**
- [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md): the end-to-end WhatsApp demo run.
- [TRACING.md](TRACING.md): following one WhatsApp message through the traces.
- [ALERTS.md](ALERTS.md): saved searches and new-listing alert drafts.
- [EMAIL.md](EMAIL.md): email drafts and market-report operations.

**Course close-out**
- [CAPSTONE.md](CAPSTONE.md): the capstone presentation and release handoff.
- [REFLECTION.md](REFLECTION.md): the engineering reflection draft.

**Enrichment files that stay at the top level** (each is pinned; see
[Pinned in place](#pinned-in-place)). The rest of the enrichment docs are in
[enrichment/](#enrichment).
- [ENRICHMENT_ANNOTATION.md](ENRICHMENT_ANNOTATION.md): remarks annotation spec v1 (owner-approved).
- [ENRICHMENT_SAMPLE_PROPOSAL.md](ENRICHMENT_SAMPLE_PROPOSAL.md): the approved private labeling plan.
- [ENRICHMENT_EXTRACTION_PROMPT.md](ENRICHMENT_EXTRACTION_PROMPT.md): the v1 extraction prompt.
- [ENRICHMENT_EXTRACTION_V2.md](ENRICHMENT_EXTRACTION_V2.md): the v2 extraction prompt.
- [ENRICHMENT_EXTRACTION_V21.md](ENRICHMENT_EXTRACTION_V21.md): the v2.1 extraction prompt.
- [ENRICHMENT_EXTRACTION_V3.md](ENRICHMENT_EXTRACTION_V3.md): the v3 candidate contract (WO-034).
- [ENRICHMENT_REVIEW_POLICY.md](ENRICHMENT_REVIEW_POLICY.md): review policy v4.
- [ENRICHMENT_REVIEW_POLICY_V5.md](ENRICHMENT_REVIEW_POLICY_V5.md): review policy v5 rulings.
- [ENRICHMENT_SCORING_V1.md](ENRICHMENT_SCORING_V1.md): the extraction scoring contract v1.
- `ENRICHMENT_V21_FREEZE.json` and `ENRICHMENT_V3_FREEZE.json`: the v2.1 and v3 freeze manifests.
- Reserved: `ENRICHMENT_V3_D_LOCK.json` and `ENRICHMENT_V3_D_FREEZE.json`, which WO-034
  Phase D code writes later at these exact paths (`scripts/extract_enrichment_v3_heldout.py`).

## releases/

Acceptance, release and activation handoff docs.
- [releases/ACTIVATION_HANDOFF.md](releases/ACTIVATION_HANDOFF.md): operator procedures for activation Phases 1 and 2 (stages S2, S3).
- [releases/ACCEPTANCE_MATRIX.md](releases/ACCEPTANCE_MATRIX.md): row-level acceptance for roadmap Phases 1 and 2, with a dated readiness update.
- [releases/RELEASE_WO021_SEARCH.md](releases/RELEASE_WO021_SEARCH.md): release handoff for remark-feature search.
- [releases/RELEASE_WO017_ANALYSIS.md](releases/RELEASE_WO017_ANALYSIS.md): release handoff for the bounded analysis tool.
- [releases/BASELINE_ACCEPTANCE.md](releases/BASELINE_ACCEPTANCE.md): WO-019 base-system acceptance (mostly historical).
- [releases/ADDITIONAL_CAPABILITIES.md](releases/ADDITIONAL_CAPABILITIES.md): the extra capabilities handoff of 2026-10-24 (historical).
- [releases/PROVIDER_HANDOFF.md](releases/PROVIDER_HANDOFF.md): the chat-provider change of 2026-10-25 (historical).

## whatsapp/

The chat channel: chart delivery and the transport research.
- [whatsapp/CHART_DELIVERY.md](whatsapp/CHART_DELIVERY.md): WO-030 chart delivery design, contract and trial.
- [whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md](whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md): Cloud API eligibility research and the open questions Q1–Q7.
- [whatsapp/WHATSAPP_TRANSPORT_RECOMMENDATION.md](whatsapp/WHATSAPP_TRANSPORT_RECOMMENDATION.md): the transport recommendation and smoke test.

The install runbook for the owned channel is in [runbooks/](#runbooks); it stays there because tests read it.

## enrichment/

Enrichment design and results records. They keep their `ENRICHMENT_` names. The results
docs are historical records; their text, including any old paths in it, is unchanged.
- [enrichment/ENRICHMENT_DESIGN.md](enrichment/ENRICHMENT_DESIGN.md): the WO-018 Phase A library boundary.
- [enrichment/ENRICHMENT_CARRIED_EVIDENCE.md](enrichment/ENRICHMENT_CARRIED_EVIDENCE.md): WO-018 evidence carried from PRs that never merged.
- [enrichment/ENRICHMENT_DEV_RESULTS.md](enrichment/ENRICHMENT_DEV_RESULTS.md): dev results carried from PR #116.
- [enrichment/ENRICHMENT_DEV3_RESULTS.md](enrichment/ENRICHMENT_DEV3_RESULTS.md): dev3 aggregate results.
- [enrichment/ENRICHMENT_HELDOUT_RESULTS.md](enrichment/ENRICHMENT_HELDOUT_RESULTS.md): v1 held-out results.
- [enrichment/ENRICHMENT_V2_DEV_RESULTS.md](enrichment/ENRICHMENT_V2_DEV_RESULTS.md): v2 dev results carried from PR #126.
- [enrichment/ENRICHMENT_V21_DEV_RESULTS.md](enrichment/ENRICHMENT_V21_DEV_RESULTS.md): v2.1 dev results.
- [enrichment/ENRICHMENT_OVERLAP_DEV.md](enrichment/ENRICHMENT_OVERLAP_DEV.md): the dev rescore under the overlap metric.
- [enrichment/ENRICHMENT_OMISSION_PILOT.md](enrichment/ENRICHMENT_OMISSION_PILOT.md): the omission-risk pilot (WO-026).
- [enrichment/ENRICHMENT_OMISSION_PILOT_V2.md](enrichment/ENRICHMENT_OMISSION_PILOT_V2.md): the omission-risk pilot v2 (WO-033).
- [enrichment/ENRICHMENT_REFRESH_PREFLIGHT.md](enrichment/ENRICHMENT_REFRESH_PREFLIGHT.md): the read-only store refresh preflight (WO-021).
- [enrichment/ENRICHMENT_SYNTHETIC_EXPERIMENT.md](enrichment/ENRICHMENT_SYNTHETIC_EXPERIMENT.md): the key-free synthetic extraction experiment.

## runbooks/

- [runbooks/WHATSAPP_CHANNEL_INSTALL.md](runbooks/WHATSAPP_CHANNEL_INSTALL.md): install, window plan, A2 and rollback for the owned WhatsApp channel.

## adrs/

Architecture decision records. Each keeps its own status line.
- [adrs/0000-template.md](adrs/0000-template.md): the ADR template.
- [adrs/0001-public-repo-boundaries.md](adrs/0001-public-repo-boundaries.md): public repo boundaries.
- [adrs/0002-agent-guardrails.md](adrs/0002-agent-guardrails.md): consent-token guardrails.
- [adrs/0003-routing-and-tool-route.md](adrs/0003-routing-and-tool-route.md): routing, the tool route and the session owner.
- [adrs/0004-query-parsing.md](adrs/0004-query-parsing.md): query parsing as a typed schema.
- [adrs/0005-sender-identity.md](adrs/0005-sender-identity.md): how the sender id reaches a tool.
- [adrs/0006-local-tracing.md](adrs/0006-local-tracing.md): local tracing with Jaeger.
- [adrs/0007-semantic-index.md](adrs/0007-semantic-index.md): the semantic index.
- [adrs/0008-saved-search-store.md](adrs/0008-saved-search-store.md): the saved-search store and draft alerts.
- [adrs/0009-rag-hybrid.md](adrs/0009-rag-hybrid.md): hybrid retrieval.
- [adrs/0011-email-approval-gate.md](adrs/0011-email-approval-gate.md): owner-only email previews.
- [adrs/0012-deterministic-card-relay.md](adrs/0012-deterministic-card-relay.md): the card relay boundary (blocked).
- [adrs/0013-analysis-worker-container.md](adrs/0013-analysis-worker-container.md): the analysis worker container and renderer.
- [adrs/0014-effective-facet-store.md](adrs/0014-effective-facet-store.md): the private effective-facet store.
- [adrs/0016-owned-whatsapp-send-path.md](adrs/0016-owned-whatsapp-send-path.md): the owned WhatsApp send path (proposed).
- [adrs/0017-cloud-api-transport-and-webhook-ingress.md](adrs/0017-cloud-api-transport-and-webhook-ingress.md): Cloud API transport and webhook ingress (proposed).

Numbers 0010 and 0015 are not on `main`.

## data/

Reference text indexed as retrieval sources. Not the private top-level `data/` folder.
- [data/schema_notes.md](data/schema_notes.md): the generated schema profile (written by `scripts/profile_data.py`).
- [data/glossary.md](data/glossary.md): the glossary.

## Pinned in place

These files did not move on 2026-11-12, because code, tests, freezes, protected files or
CLAUDE.md name them at their current path. Moving one needs its own reviewed change.

| File | Why it stays |
|---|---|
| `START_HERE.md`, `STATUS.md` | The front doors: CLAUDE.md:11 and AGENTS.md:4 |
| `AGENT_RULES.md` | Named in files the agent may not edit: `scripts/guards/guard.py:1`, `scripts/gates/protected_deletions.py:1,92`, `.claude/settings.json:18,29`; also CLAUDE.md:15 |
| `SAFETY_INVARIANTS.md` | CLAUDE.md:14; `src/idx_agent/safety/__init__.py:3` |
| `EVIDENCE_LOG.md` | The guard's evidence root (`scripts/guards/guard.py:50`); a `git mv` of it is refused; append-only |
| `ARCHITECTURE.md`, `CONTRACTS.md`, `DECISIONS.md`, `EVALUATION.md` | CLAUDE.md:17-18, plus code comments and `evals/run.py` |
| `ROUTING.md` | Read by `tests/test_routing_contract.py:39` |
| `DEMO_RUNBOOK.md` | Read by `tests/test_demo_runbook.py:15` |
| `ENRICHMENT_EXTRACTION_PROMPT.md` | Read by path and hash-pinned: `scripts/extract_enrichment_test.py:30,154`; also read by `extract_enrichment_dev.py:229` and `extract_enrichment_full.py:124` |
| `ENRICHMENT_EXTRACTION_V2.md` | Read and hash-pinned by `scripts/extract_enrichment_v2_dev.py:42,76`; also `v2_heldout.py:53`, `v2_batch.py:254`, `supplement.py:34`, and sealed by `extract_enrichment_v3_heldout.py:114` |
| `ENRICHMENT_EXTRACTION_V21.md` | Its path is a key in `ENRICHMENT_V21_FREEZE.json`; read by `scripts/extract_enrichment_v21_dev.py:129` |
| `ENRICHMENT_EXTRACTION_V3.md` | Named in `ENRICHMENT_V3_FREEZE.json` ("doc"); asserted by `tests/test_enrichment_v3_freeze.py:17,80`; sealed whole by `extract_enrichment_v3_heldout.py:115` |
| `ENRICHMENT_V21_FREEZE.json` | Read and byte-pinned by `scripts/extract_enrichment_v21_dev.py:36` |
| `ENRICHMENT_V3_FREEZE.json` | Read by `tests/test_enrichment_v3_freeze.py:18` and `src/idx_agent/enrichment/v3.py:19`; sealed by `extract_enrichment_v3_heldout.py:116` |
| `ENRICHMENT_REVIEW_POLICY.md` | Read by `scripts/build_enrichment_effective_store.py:42`, `validate_enrichment_review.py:304` and `finalize_enrichment_policy_audit.py:26`; its hash is in the private audit manifest |
| `ENRICHMENT_REVIEW_POLICY_V5.md` | Path and hash in `ENRICHMENT_V3_FREEZE.json`; read by `scripts/build_enrichment_effective_store.py:51` |
| `ENRICHMENT_SCORING_V1.md` | Hash-pinned by path in `scripts/extract_enrichment_v3_dev.py:60`; sealed by `extract_enrichment_v3_heldout.py:117`; read by three WO-034 tests |
| `ENRICHMENT_ANNOTATION.md` | The owner-approved spec v1; named by `src/idx_agent/enrichment/omission_pilot.py:24,99` |
| `ENRICHMENT_SAMPLE_PROPOSAL.md` | Linked from the approved annotation spec; keeping it here leaves that spec unedited |
| `ENRICHMENT_V3_D_LOCK.json`, `ENRICHMENT_V3_D_FREEZE.json` (reserved) | Written later at these paths by `scripts/extract_enrichment_v3_heldout.py:64-65` |
| `runbooks/`, `adrs/`, `data/` | Read by tests and the host harness (runbooks), named by CLAUDE.md:32 (adrs) and read as retrieval sources by `src/idx_agent/rag/sources.py` (data) |

The other top-level docs (planning, guides, course close-out) stay where they are for
now; nothing pins them, and grouping them is possible later work.

## Moved on 2026-11-12

Moved by `git mv` in PR #196 (AG-A11, stacked on #193), so `git log --follow` shows each
file's earlier history. Links and current pointers were updated. Historical records keep
the old path as written: EVIDENCE_LOG.md, STATUS_HISTORY.md, work orders, ADRs, the
frozen and sealed enrichment files, the moved enrichment results docs (not
ENRICHMENT_DESIGN.md), the original 2026-11-02 body of ACCEPTANCE_MATRIX.md, and in
ACTIVATION_HANDOFF.md its dated sections, verbatim quotes, `**Update of` paragraphs and
the few lines that cite a doc as it was at a commit or PR (listed one by one in
`PINNED` in `scripts/docs_relink.py`). Read their old paths through this table.

| Old path | New path |
|---|---|
| `docs/ACCEPTANCE_MATRIX.md` | `docs/releases/ACCEPTANCE_MATRIX.md` |
| `docs/ACTIVATION_HANDOFF.md` | `docs/releases/ACTIVATION_HANDOFF.md` |
| `docs/ADDITIONAL_CAPABILITIES.md` | `docs/releases/ADDITIONAL_CAPABILITIES.md` |
| `docs/BASELINE_ACCEPTANCE.md` | `docs/releases/BASELINE_ACCEPTANCE.md` |
| `docs/PROVIDER_HANDOFF.md` | `docs/releases/PROVIDER_HANDOFF.md` |
| `docs/RELEASE_WO017_ANALYSIS.md` | `docs/releases/RELEASE_WO017_ANALYSIS.md` |
| `docs/RELEASE_WO021_SEARCH.md` | `docs/releases/RELEASE_WO021_SEARCH.md` |
| `docs/CHART_DELIVERY.md` | `docs/whatsapp/CHART_DELIVERY.md` |
| `docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md` | `docs/whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md` |
| `docs/WHATSAPP_TRANSPORT_RECOMMENDATION.md` | `docs/whatsapp/WHATSAPP_TRANSPORT_RECOMMENDATION.md` |
| `docs/ENRICHMENT_DESIGN.md` | `docs/enrichment/ENRICHMENT_DESIGN.md` |
| `docs/ENRICHMENT_CARRIED_EVIDENCE.md` | `docs/enrichment/ENRICHMENT_CARRIED_EVIDENCE.md` |
| `docs/ENRICHMENT_DEV_RESULTS.md` | `docs/enrichment/ENRICHMENT_DEV_RESULTS.md` |
| `docs/ENRICHMENT_DEV3_RESULTS.md` | `docs/enrichment/ENRICHMENT_DEV3_RESULTS.md` |
| `docs/ENRICHMENT_HELDOUT_RESULTS.md` | `docs/enrichment/ENRICHMENT_HELDOUT_RESULTS.md` |
| `docs/ENRICHMENT_OMISSION_PILOT.md` | `docs/enrichment/ENRICHMENT_OMISSION_PILOT.md` |
| `docs/ENRICHMENT_OMISSION_PILOT_V2.md` | `docs/enrichment/ENRICHMENT_OMISSION_PILOT_V2.md` |
| `docs/ENRICHMENT_OVERLAP_DEV.md` | `docs/enrichment/ENRICHMENT_OVERLAP_DEV.md` |
| `docs/ENRICHMENT_REFRESH_PREFLIGHT.md` | `docs/enrichment/ENRICHMENT_REFRESH_PREFLIGHT.md` |
| `docs/ENRICHMENT_SYNTHETIC_EXPERIMENT.md` | `docs/enrichment/ENRICHMENT_SYNTHETIC_EXPERIMENT.md` |
| `docs/ENRICHMENT_V2_DEV_RESULTS.md` | `docs/enrichment/ENRICHMENT_V2_DEV_RESULTS.md` |
| `docs/ENRICHMENT_V21_DEV_RESULTS.md` | `docs/enrichment/ENRICHMENT_V21_DEV_RESULTS.md` |

`scripts/docs_relink.py` holds the same map and made the link and path updates; run it
with `--dry-run` to check that nothing is left to change.
