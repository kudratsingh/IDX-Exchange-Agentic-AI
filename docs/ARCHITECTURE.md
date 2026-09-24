# Architecture (baseline)

Scope: what the twelve weeks require. Extensions are gated in `DECISIONS.md`, not designed here.

## 1. Request path
As decided in ADR-0003 and confirmed by the WO-001 live run. Solid nodes exist today;
the skills, tables, index, and email path marked "planned" arrive with their work orders.

```mermaid
flowchart TD
    U[User on WhatsApp<br/>owner number only] --> GW[OpenClaw gateway<br/>dmPolicy allowlist, groups off<br/>one session per sender: dmScope per-channel-peer]
    GW --> M[Model turn<br/>sees the idx agent's skill list, picks one,<br/>loads its SKILL.md with the read tool]
    M --> SK[SKILL.md instructions<br/>health, property-search, market-stats today;<br/>recommend, rag, email planned]
    SK --> MCP[MCP server idx over stdio<br/>src/idx_agent/mcp_server, tools idx__*<br/>policy: allow idx__* and read; runtime, fs writes, web, browser denied]
    MCP --> V[Validate inputs<br/>Pydantic contracts, src/idx_agent/domain]
    V --> SQL[Parameterized SQL<br/>column allowlist, at most 50 rows,<br/>SELECT-only reader user]
    SQL --> DB1[(rets_property<br/>active listings, as-of 2026-09-18)]
    SQL --> DB2[(california_sold<br/>closed sales, as-of 2026-09-17)]
    V --> RAG[(Indexed docs<br/>planned, WO for RAG)]
    DB1 --> R[AgentResult envelope<br/>data, provenance with as-of dates,<br/>warnings, trace id; error detail never leaves]
    DB2 --> R
    RAG --> R
    R --> M2[Model composes the reply<br/>retrieved text is data, never instructions]
    M2 --> W[WhatsApp reply]
    M2 --> D[draft_email tool, planned<br/>PendingAction stored by our code]
    D --> A{Human approval<br/>outside the model}
    A -->|approved| S[send_email tool]
    A -->|rejected| X[discarded]
```

Facts fixed by config, not by prompt: the tool policy, the sender allowlist, the session
scope, and the MCP launch are all in `config/openclaw.idx.json5`. Memory flush and the
dreaming job are off for this agent, so conversation facts are not copied into
workspace files. The model never touches the database; every arrow below the MCP node is
code with tests.

## 2. Components
**Channel.** OpenClaw links a dedicated WhatsApp number through WhatsApp Web, with a
sender allowlist. The channel is an adapter; no business logic lives in it.

**Runtime.** A skill is a folder with a `SKILL.md`: a one-line description the model
matches on, plus instructions. The model picks a skill, then acts through tools. Our
tools are exposed through an MCP server (working default; WO-001 confirms), with the
shell tool disabled for the user-facing agent. OpenClaw keeps its own sessions; which
state lives where is decided in WO-001.

**Routing.** The model chooses among skills (OpenClaw's native routing); each skill's
instructions name one typed MCP tool, and our code owns everything below that boundary.
A router behind a single entry tool was rejected as a second model call per message; it
returns only if the WO-004 routing evals demand it. Decided in
`adrs/0003-routing-and-tool-route.md`.

**The five agent roles** (functions in one codebase, not processes):

| Role | Owns | Tools | Data |
|---|---|---|---|
| search | filters -> bounded listing results, refinement | `search_listings` | rets_property |
| market | metrics by geography and subtype, trend, labels | `get_market_stats` | california_sold |
| recommendation | similar listings, comp-checked price | `find_similar_listings`, `recommend` | both |
| rag | grounded answers with sources | `rag_answer` | indexed docs |
| email | drafts; never sends on its own | `draft_email`, `send_email` (gated) | upstream results |

**Shared layer.**
- Contracts, `src/idx_agent/domain/`: the only way data crosses a boundary.
- Data access, `src/idx_agent/db/`: parameterized SQL, column allowlist, row cap, SELECT-only user, as-of dates.
- MCP server, `src/idx_agent/mcp_server/`: typed tools over data access and analytics.
- Session state, `src/idx_agent/memory/`: per-sender search state; saved searches only if the Week 4 decision says so.
- Safety, `src/idx_agent/safety/`: allow/deny lists, approval state machine, redaction.
- Observability, `src/idx_agent/observability/`: structured logs, trace id, tokens and cost per request; optional spans to a loopback Jaeger beside OpenClaw's, and a rotating log file (WO-007, `TRACING.md`, ADR-0006).
- Evals, `evals/`: golden cases; script-checkable ones run in CI.

## 3. Data
- `rets_property`: active listings, 130+ columns. Core search fields use IDX legacy
  names (`L_City`, `L_Zip`, `L_SystemPrice`, `L_Keyword2` = beds, `LM_Dec_3` = baths,
  `LM_Int2_3` = sqft, `L_Type_` = subtype, `L_Remarks` with a FULLTEXT index,
  `L_Photos` JSON). Two status columns that agree on every row; `StandardStatus =
  'Active'` is the rule (WO-002), and the whole table is active listings (55,212 rows).
- `california_sold`: closed transactions from 2026-03-18 to 2026-09-17 (98,552 rows, about
  six months, not multiple years), RESO-style names (`ClosePrice`, `CloseDate`,
  `LivingArea`, `BedroomsTotal`, `PropertySubType`). Date columns are text; integer
  counts are stored as doubles; the table ships with no index. The migration adds real
  date columns and indexes. Both tables use the same RESO subtype vocabulary.
- Join: `CAST(rets_property.L_ListingID AS UNSIGNED) = california_sold.ListingKey`;
  market-level joins on city or postal code.
- Two as-of dates: sold = the latest `CloseDate` that is not after the active as-of date
  (2026-09-17; four typo rows sit in 2028-2072 and are excluded), active =
  `MAX(ModificationTimestamp)` (2026-09-18). Every time window counts back from these,
  never from today.
- Canonical names are RESO. The map lives in `docs/data/schema_notes.md` (WO-002) and
  `src/idx_agent/domain/fieldmap.py` (WO-003).
- Bathrooms differ across tables (decimal vs integer count) and are never compared.
- Sensitive columns may exist among the undocumented ones; see the deny-list in
  `SAFETY_INVARIANTS.md`.

## 4. Where code lives vs where it runs
OpenClaw runs from its own install. Its workspace holds the active copies of our
`SKILL.md` files and its config. This repo holds `skills/` sources, the MCP server,
scripts, evals, and docs. `scripts/install.sh` links skills into the workspace and
registers the MCP server. OpenClaw's source is never vendored here.

## 5. Deliberately absent until evidence says otherwise
Vector database, reranker, model router with confidence, memory beyond sessions,
queues, deployment, fine-tuning. Gates are in `DECISIONS.md`.

## 6. Open points
Routing, tool route, and session ownership (WO-001). Saved searches (Week 4). Demo
length, handbook version, table refresh, spend cap (coordinator; tracked in `coordination/`).
