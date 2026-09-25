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
| Time windows | Counted back from the data's as-of dates | The sold data covers 2026-03-18 to 2026-09-17 (as-of 2026-09-17); the active data is as of 2026-09-18 |
| Sale-to-list unit | Ratio (1.03) with the plain reading alongside | Sources disagree on unit and name; both agents must say the same number |
| Comps | Closed sales from `california_sold` only, after every WO-008 exclusion: the subject's city, widened to its five-digit ZIP (a `PostalCode` prefix match) only when the city has fewer than 5, and no further; the same `PropertySubType`; `LivingArea` from 0.8 to 1.2 times the subject's and `BedroomsTotal` within 1 of the subject's (floored at 0), both inclusive; the six months counted back from the sold as-of date; a minimum of 5 comps, below which the price check says so and gives no number; bathrooms never used. The result is one fixed-shape fact: the subject's list price per sqft against the comps' median price per sqft, a whole percent rounded half-even once (WO-011) | The tables define bathrooms differently; the sold table has no county column (`CountyOrParish` is on the active table only), so the county step decided on 2026-09-24 does not exist and the widening stops at the ZIP. A fixed sentence keeps the check a fact, never a valuation or advice |
| Semantic search | Hard filters (city, price, beds, subtype, stored beside each vector in the index) applied in memory; cosine ranking over the rows left; the top candidates (at most 200) re-checked in SQL with the same filters and the active-status rule, which has the last word. No FULLTEXT stage (now an extension gate). Cold start at most 5 seconds (WO-010, ADR-0007) | At about 55,000 rows one cosine pass is a single matrix-vector product, so a candidate stage buys nothing; a SQL pre-filter that returned every matching key would break the 50-row cap; the SQL re-check drops listings whose price or status changed after the build. Decided 2026-09-24, replacing "SQL filter, then FULLTEXT candidates, then one vector pass" |
| Embedding route | OpenAI `text-embedding-3-small` for the listing remarks (embedded once, offline, into an index kept under the gitignored `data/` folder) and for each query's text, with emails, phone numbers, and links replaced by placeholders before either is embedded (the database untouched); 1,536 dimensions, kept after the spike measured a 0.40-second cold start against the 5-second limit that would have called for 512; the one-time full build runs only under a human `paid` token for that run (WO-010, ADR-0007) | The route the handbook prescribes; the `openai` package and `OPENAI_API_KEY` are already in the Week 0 setup. Estimate: about 55,000 listings at roughly 300 tokens each, about 17 million tokens, in the order of $0.35 at the known price (checked against the provider's current price page before the run), then fractions of a cent per query. The actual cost is read from the provider console after the run, never computed from a price. Decided 2026-09-24, with no local-model comparison |
| Gateway chat model | `openai/gpt-5.6-terra` as the `idx` agent's primary model (a live OpenClaw setting, `openclaw models set`; not in our config template), with the agent-runtime setting copied to the new model entry by hand; OpenClaw's own utility model stays its provider default (`gpt-5.6-luna`); `gpt-6-astra` stays available and one command puts it back | The Week 0 setup left OpenClaw's default, `gpt-6-astra`; the provider's usage page on 2026-09-24 showed $4.27 for one day of demos, all astra, 90% of it prompt-cache writes and reads. Jaeger traces of one eight-turn session showed a 37,000-token fixed prefix (OpenClaw's bootstrap plus skills and tool schemas) replayed with the whole session on every turn, growing to 51,571 tokens by turn eight. Terra's list prices are one fifth of astra's on every line (input, cached, cache write, output). The routing job is small (pick one of five tools, fill a schema, relay a message our code wrote), so a mid-tier model is tried first; the five-message smoke set and the phrasing cases are the check; a prefix audit is the other lever. Decided 2026-09-24 |
| RAG chunking | Per field for the Trestle doc, per section for the Primer, exact-name lookup first, a schema-summary chunk per table, a glossary chunk | Fits the actual sources and the required questions |
| Email | State machine keyed by a stored draft id | Makes the guarantee enforceable in code |
| Memory | Session-scoped state, one session per sender | Meets the requirement with low privacy cost |
| Reviewer | CI plus a recorded weekly demo; a model review of a change only on request | No colleague; per-change model review is an unbounded recurring cost |
| Evals | Versioned cases in the repo from WO-004; `ci` suite on every push | Objective regression testing |
| Routing | The model chooses among skills; each skill names one typed MCP tool (ADR-0003) | OpenClaw's native routing; our code owns everything below the tool boundary; a router behind one tool adds a model call |
| Tool invocation | Python MCP server over stdio, `mcp.servers.idx`, tools named `idx__<tool>` (ADR-0003) | Typed, testable without OpenClaw, shell tool denied by config |
| Session owner | OpenClaw keeps the per-sender transcript (`session.dmScope: per-channel-peer`); our `memory/` keeps filters, result keys, and approvals keyed by a hashed sender id (ADR-0003) | OpenClaw memory does not enforce policy; ours must |
| Query parsing | The model fills the typed `search_listings` schema (`PropertySearchFilters`); code validates it strictly (city in `valid_values`, known subtype, sane ranges) and on a missing or invalid value returns a structured needs-clarification result (field, reason, suggested follow-up question) instead of guessing; no regex parser; the result carries the accepted filters, which the `property-search` skill shows on request. The 10 parser queries are `local` evals; the validator's unit tests run in CI (WO-004) | The model already reads the message to pick the tool, so a second parser duplicates it and misses phrasing; correctness lives in the deterministic validator; echoing the filters keeps parsing demonstrable on its own. Decided 2026-09-23 |
| Active status, exclusions, deny-list | `StandardStatus = 'Active'` defines active (every active row has it and `L_Status` agrees); exclude sold rows dated after the active as-of date, sold rows closing before their contract date, prices under 25,000 and areas under 200 sqft; no deny-list candidate column exists, the list stays in code; agent-contact columns are named in `columns.py` and never returned (`docs/data/schema_notes.md`) | Decided from the 2026-09-23 profiling run; the sold table has no status column |

## Pending
| Decision | Decided by | When |
|---|---|---|
| Saved searches and alerts | human: **yes** (2026-09-24). Its own work order, sequenced after the email approval gate (Week 11), since alerts go out through that gate; needs an email per sender, a record that outlives the session, and a scheduled job, each with its own safety note | Week 4, decided |
| Demo length, handbook version, table refresh, spend cap, allowed services | coordinator | first meeting |

## Extension gates (add only with evidence)
| Extension | Add only if |
|---|---|
| Deterministic pre-parser in front of the model | the local parsing evals show the model misfilling fields that simple rules would get right |
| Local embedding model in place of the paid route | the embedding spend, read from the provider console, becomes a problem (gated 2026-09-24; no local-versus-paid comparison was run) |
| FULLTEXT candidate stage, or hybrid lexical + vector retrieval | vector-only ranking misses exact terms in the judged queries or in use (taken out of the decided semantic-search flow 2026-09-24; the FULLTEXT index on `L_Remarks` makes it cheap to add) |
| Reranker | top-k has the right items in the wrong order |
| Prior-sale lookup, mortgage payment tool | the baseline is complete and Weeks 6-7 landed on time |
| Persistent memory, cache, queue, deployment | a measured requirement, not a wish |

## ADR process
One file per decision that affects more than one component: `adrs/NNNN-short-name.md`,
from `adrs/0000-template.md`. Record the alternatives and what would reverse the decision.
