# Architecture (baseline)

Scope: what the twelve weeks require. Extensions are gated in `DECISIONS.md`, not designed here.

## 1. Request path
```
WhatsApp / user
      |
OpenClaw channel + runtime  (dedicated number, sender allowlist, one session per sender)
      |
session / memory  ----->  conversation context
      |
routing  (open until WO-001: model-chosen skills, or one entry tool -> our router)
      |
   +-----------------+-----------------+-----------------+
   |                 |                 |                 |
search            market          recommendation        rag
rets_property     california_sold  both tables          indexed docs
   +-----------------+-----------------+-----------------+
      |
response composition (provenance, as-of dates, warnings)
      |
WhatsApp reply            or          email draft -> stored pending record -> approval -> send
```

## 2. Components
**Channel.** OpenClaw links a dedicated WhatsApp number through WhatsApp Web, with a
sender allowlist. The channel is an adapter; no business logic lives in it.

**Runtime.** A skill is a folder with a `SKILL.md`: a one-line description the model
matches on, plus instructions. The model picks a skill, then acts through tools. Our
tools are exposed through an MCP server (working default; WO-001 confirms), with the
shell tool disabled for the user-facing agent. OpenClaw keeps its own sessions; which
state lives where is decided in WO-001.

**Routing.** Option A: the model chooses among skills. Option B: one entry tool hands
the message to our router in code. Recorded in `adrs/0002-routing-and-tool-route.md`.

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
- Observability, `src/idx_agent/observability/`: structured logs, trace id, tokens and cost per request.
- Evals, `evals/`: golden cases; script-checkable ones run in CI.

## 3. Data
- `rets_property`: active listings, 130+ columns. Core search fields use IDX legacy
  names (`L_City`, `L_Zip`, `L_SystemPrice`, `L_Keyword2` = beds, `LM_Dec_3` = baths,
  `LM_Int2_3` = sqft, `L_Type_` = subtype, `L_Remarks` with a FULLTEXT index,
  `L_Photos` JSON). Two status columns; profiling decides which defines "active".
- `california_sold`: closed transactions 2021-2025, RESO-style names (`ClosePrice`,
  `CloseDate`, `LivingArea`, `BedroomsTotal`, `PropertySubType`). Date columns are text;
  integer counts are stored as doubles. A migration adds real date columns and indexes.
- Join: `CAST(rets_property.L_ListingID AS UNSIGNED) = california_sold.ListingKey`;
  market-level joins on city or postal code.
- Two as-of dates: sold = `MAX(CloseDate)`, active = `MAX(ModificationTimestamp)`.
  Every time window counts back from these, never from today.
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
