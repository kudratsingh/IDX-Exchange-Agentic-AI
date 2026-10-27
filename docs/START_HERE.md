# START HERE

Read this, then the active work order, then only what it references.

## 1. What we are building
One assistant. A user messages it on WhatsApp. It searches active listings, answers
market questions from closed transactions, finds similar homes with prices checked
against comparable sales, answers real-estate and schema questions from indexed
documents, and drafts emails that go out only after a human approves them.
OpenClaw is the runtime; our code is Python behind typed tools.

## 2. What the internship requires (in our words)
Ten capabilities by Week 12: plain-language search, multi-turn memory, market
analytics, comp-validated pricing, semantic search, recommendations, RAG,
orchestration across five agent roles, a WhatsApp channel, and email with an
approval gate. Deliverables: this public repo with a clean history and README, an
architecture diagram, schema notes, a live WhatsApp demo plus a recorded backup, and
a written reflection. The twelve weekly modules build on each other; Week 0 is setup,
Week 12 is the capstone demo.

## 3. Architecture in one picture
```
WhatsApp -> OpenClaw -> routing -> [search | market | recommend | rag] -> compose
                                                                          |
                                                    WhatsApp reply   or   email draft -> approval -> send
Shared layer: contracts, data access (MCP tools), session state, safety, logging, evals
```
Details: `ARCHITECTURE.md`.

## 4. Where we are

Current priority: after the WO-019 model-side merge, the user directed work to
resume on the combined roadmap. WO-018 Phase B begins with a draft annotation
specification and synthetic examples. BASELINE_ACCEPTANCE.md continues to track
open baseline items; resumption does not declare them complete. WO-017/018
foundations remain unconnected to live behavior.

Latest 2026-10-25 closeout: IDX chat is configured for Anthropic Sonnet 5.5 with
medium effort; configuration and restart/RPC checks passed. WO-015's operator hook
fix merged in PR #86 (3,024 offline tests, 59 fixture integration tests, 155 CI eval
cases passed; skips recorded in EVIDENCE_LOG.md). No live model/email acceptance is
inferred. The two new capability proposals are combined in CAPABILITY_ROADMAP.md,
with every original item accounted for in ROADMAP_CROSSWALK.md. WO-018 Phase A is
the next implementation: remarks vocabulary and pure normalization. The earlier
WO-017 numeric foundation is merged and retained for Phase 2. Historical audit
paragraphs below retain their original dates and are superseded by STATUS.md.

2026-10-25 audit: search, follow-up memory, analytics, semantic search,
recommendations, RAG and routing have been exercised in earlier walkthroughs.
The human authorized merging and installing the key-free work after its checks.
PRs #81 and #82 are merged into main and installed; the gateway restarted and its
RPC check passed. Both MCP servers probe successfully (7 IDX tools, 4 alert tools),
and all eight skills are ready. The existing chat model, provider/auth settings and
owner allowlist were preserved. See `ADDITIONAL_CAPABILITIES.md`. Capstone
materials are in `CAPSTONE.md`. Database integration passed in CI; live routing/e2e
acceptance, Gmail delivery and the final recording remain pending. Historical status
lines below describe earlier checkpoints, not fresh acceptance results.
`STATUS.md` is the concise current readiness record; dated work-order sections
retain their original measurements and decisions.
The week-by-week schedule is `TIMELINE.md`. Phase 0, bootstrap (Weeks 0-1): a safe repo,
the OpenClaw decisions made, the data profiled, the architecture diagram. Phase 1, first
slice (Weeks 2-3): the filter contract, one query working end to end, the eval harness
running in CI.

| WO | Name | Week | Who drives | Status |
|---|---|---|---|---|
| WO-000 | Repo bootstrap | 0 | agent | done (PR #1) |
| WO-001 | OpenClaw integration spike | 0 | human (agent assists) | done (PR #4, live run recorded in the WO) |
| WO-002 | MLS data profiling | 0 | human (agent writes the script) | done (PR #9; run and findings in the WO) |
| Architecture diagram | `ARCHITECTURE.md` section 1 | 1 | agent | done (PR #11) |
| WO-003 | Core domain contracts | 2 | agent | done (PR #10; clarification result added on the parsing decision, ADR-0004) |
| WO-004 | Property-search vertical slice | 2-3 | agent (human runs the WhatsApp test) | done (PR #13; WhatsApp test and paid parser runs recorded 2026-09-24) |
| WO-005 | Evaluation harness and CI | 3 | agent | done (PR #14; fixture database in CI) |
| WO-006 | Multi-turn memory | 4 | agent (human runs the WhatsApp test) | done (PR #21; WhatsApp flow, paid memory runs, and the saved-search yes all recorded 2026-09-24) |
| WO-007 | End-to-end tracing | 4 (chore, human ask) | agent (human runs one WhatsApp turn) | done (PR #28; traced turn and collector-down check recorded 2026-09-24) |
| WO-008 | Market analytics | 5 | agent (human runs the WhatsApp test) | done (PR #30; WhatsApp run and paid phrasing run recorded 2026-09-24) |
| WO-009 | Saved searches and alerts, additional capabilities | after 11 (human decision) | agent (human approves every send) | merged PR #82; installed; live acceptance pending |
| WO-010 | Semantic search | 6 | agent; human judges relevance and live behavior | index built/served; earlier phrasing and WhatsApp checks recorded; judged recall and new-provider acceptance pending |
| WO-011 | Recommendations with a price check | 7 | agent; human runs live acceptance | earlier phrasing and WhatsApp checks recorded; fresh current-version/provider rehearsal pending |
| WO-012 | RAG assistant over the reference documents | 8 | agent; human grants paid runs | hybrid index rebuilt/served; earlier phrasing/live retrieval evidence recorded; fresh provider acceptance pending |
| WO-013 | Routing across the five roles, with a mixed-intent suite | 9 | agent (human grants the paid tokens and runs the WhatsApp test) | done (routing runs 25 of 25 twice; WhatsApp run recorded, 2026-09-25) |
| WO-014 | The whole assistant, end to end over WhatsApp | 10 | human (agent writes the script cases, runbook, and preflight; human runs the demo under a paid token) | built, model-free parts (2026-09-25); dry run and live rehearsal pending the human |
| WO-015 | Email drafts behind a human approval gate, a weekly market report, and the safety suite | 11 | agent; human approves and sends | merged PR #81; installed; live acceptance deferred |
| WO-016 | Capstone docs, demo and recording | 12 | agent prepares; human rehearses and records | materials prepared; provider/live demo/recording pending |

At most one implementation work order is active at a time. Core features and
installation are complete; WO-015 still tracks the protected operator-hook hardening
task, and WO-016 tracks the live acceptance and submission work.
Read the current checkpoint before treating an older pending list as a new assignment.

## 5. What to read next
| If you are about to... | Read |
|---|---|
| touch any code | `../CLAUDE.md`, `SAFETY_INVARIANTS.md` |
| add or change a type or tool signature | `CONTRACTS.md` |
| decide something that affects more than one component | `DECISIONS.md`, then write an ADR |
| write tests or eval cases | `EVALUATION.md` |
| touch the database | `data/schema_notes.md` (exists after WO-002) |

## 6. Repo map
```
CLAUDE.md                 rules for coding agents
AGENTS.md                 coding-agent entry point
docs/STATUS.md            current readiness and remaining acceptance
docs/                     this folder; adrs/ holds decisions; data/ holds schema notes
work_orders/              WO-000 ... one active at a time
src/idx_agent/            domain/ db/ safety/ mcp_server/ parser/ memory/ channels/ observability/
skills/                   SKILL.md sources
scripts/                  install.sh, migrations/, profile_data.py
evals/                    cases/ and run.py
tests/                    pytest; fixtures/ holds synthetic SQL only
```

## 7. Rules that never change
`../RULES.md`: no data, no text from the handbook or the supplied PDFs, no secrets or
people. Each rule is a commit gate and a CI gate. `SAFETY_INVARIANTS.md` applies to every
line of code.

## 8. Not in the repo, by design
`context/` (handbook, plan PDFs, supplied sources), `coordination/` (meeting notes,
hours log, coordinator answers), `data/` (dumps, embeddings, indexes, knowledge PDFs).
All three exist locally and are gitignored. Ask the human if you need something from them.
