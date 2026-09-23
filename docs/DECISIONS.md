# Decisions

## Decided
| Decision | Choice | Why |
|---|---|---|
| Format | Individual capstone in this public repo; code and docs in, data out | Required by the internship; the history is graded |
| Language | Python for all our code; TypeScript only if OpenClaw forces it | One import root; analytics and embeddings are Python anyway |
| Tool exposure | Python MCP server as the working default | Typed, testable without OpenClaw, shell tool can stay off. WO-001 confirms |
| Agent vs tool | Agents only for distinct reasoning; deterministic work is a tool | Testable, cheap |
| Data model | RESO-named canonical models at the DB boundary, explicit column allowlist | Stops legacy names spreading; keeps sensitive fields out |
| Analytics | Deterministic SQL/Python, subtype-aware, single-family as the default benchmark, mix disclosed | A mixed-type median moves with the mix |
| Time windows | Counted back from the data's as-of dates | The sold data ends in 2025 |
| Sale-to-list unit | Ratio (1.03) with the plain reading alongside | Sources disagree on unit and name; both agents must say the same number |
| Comps | Same subtype, same city (widen if too few), sqft within 20%, beds within 1, minimum count; never baths across tables | The tables define bathrooms differently |
| Semantic search | SQL filter, then FULLTEXT candidates, then one vector similarity pass | The only fast option at full size |
| RAG chunking | Per field for the Trestle doc, per section for the Primer, exact-name lookup first, a schema-summary chunk per table, a glossary chunk | Fits the actual sources and the required questions |
| Email | State machine keyed by a stored draft id | Makes the guarantee enforceable in code |
| Memory | Session-scoped state, one session per sender | Meets the requirement with low privacy cost |
| Reviewer | CI plus a recorded weekly demo; a model review of a change only on request | No colleague; per-change model review is an unbounded recurring cost |
| Evals | Versioned cases in the repo from WO-004; `ci` suite on every push | Objective regression testing |
| Routing | The model chooses among skills; each skill names one typed MCP tool (ADR-0003) | OpenClaw's native routing; our code owns everything below the tool boundary; a router behind one tool adds a model call |
| Tool invocation | Python MCP server over stdio, `mcp.servers.idx`, tools named `idx__<tool>` (ADR-0003) | Typed, testable without OpenClaw, shell tool denied by config |
| Session owner | OpenClaw keeps the per-sender transcript (`session.dmScope: per-channel-peer`); our `memory/` keeps filters, result keys, and approvals keyed by a hashed sender id (ADR-0003) | OpenClaw memory does not enforce policy; ours must |

## Pending
| Decision | Decided by | When |
|---|---|---|
| Which status column defines "active"; exclusion rules; deny-list contents | WO-002 profiling | Week 0 |
| Saved searches and alerts | human | Week 4 |
| Demo length, handbook version, table refresh, spend cap, allowed services | coordinator | first meeting |

## Extension gates (add only with evidence)
| Extension | Add only if |
|---|---|
| Model-based filter extraction | parser evals show material misses on realistic queries |
| Hybrid lexical + vector retrieval | vector-only misses exact terms (the FULLTEXT index makes this cheap) |
| Reranker | top-k has the right items in the wrong order |
| Prior-sale lookup, mortgage payment tool | the baseline is complete and Weeks 6-7 landed on time |
| Persistent memory, cache, queue, deployment | a measured requirement, not a wish |

## ADR process
One file per decision that affects more than one component: `adrs/NNNN-short-name.md`,
from `adrs/0000-template.md`. Record the alternatives and what would reverse the decision.
