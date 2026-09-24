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
| WO-006 | Multi-turn memory | 4 | agent (human runs the WhatsApp test) | **active** (started 2026-09-24) |
| WO-007 | End-to-end tracing | 4 (chore, human ask) | agent (human runs one WhatsApp turn) | drafted |

Exactly one work order is active. Its Status section is the source of truth. The human
reviews each finished work order before the next one starts.

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
