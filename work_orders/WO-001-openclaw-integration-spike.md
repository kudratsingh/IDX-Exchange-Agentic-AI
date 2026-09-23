# WO-001 — OpenClaw integration spike

**Driver:** human. The agent scaffolds the MCP server and explains the OpenClaw docs; the human installs,
configures, runs, and reads the traces. This is the one place understanding matters more than output.
**Depends on:** WO-000
**Estimated effort:** 3-4 hours

## Objective
Answer six questions with one tiny working tool, and record the routing and tool-route decisions in an ADR.

1. Where does routing live: the model choosing among skills, or our router behind one entry tool?
2. How does OpenClaw invoke our Python: MCP server, plugin, or script via the shell tool?
3. Does a Python MCP server work cleanly, with the shell tool disabled for the agent?
4. Can shell access stay off for the user-facing agent, and is that enforced by config, not by prompt?
5. How is sender identity exposed, and can we get one session per sender?
6. What does a complete trace look like: message -> skill -> tool call -> result -> reply?

## Why
Everything else plugs into OpenClaw, and the handbook's picture of it does not match the docs. Getting this
wrong later means rebuilding the tool layer.

## Inputs
`docs/ARCHITECTURE.md` sections 2 and 4; `docs/CONTRACTS.md` (`health` tool, `AgentResult`);
the OpenClaw docs on skills, tool policy, MCP servers, sessions, and the WhatsApp channel.

## In scope
- A dedicated WhatsApp number linked to OpenClaw, with a sender allowlist containing only the human's number.
- `skills/health/SKILL.md`: one skill whose instructions call the `health` tool and reply with its result.
- `src/idx_agent/mcp_server/server.py` exposing one tool, `health`, returning an `AgentResult` with server time and package version (no database yet).
- The same tool reachable a second way (a script via the shell tool) only to compare, then removed.
- Tool policy: shell tool disabled for the user-facing agent; only our MCP tools allowed.
- Session config: one session per sender.
- `scripts/install.sh` v0: link `skills/` into the OpenClaw workspace and register the MCP server.
- `docs/adrs/0002-routing-and-tool-route.md` with the answers to all six questions and the decision.
- `docs/DECISIONS.md`: move the three pending rows to Decided.

## Out of scope
Any database tool, any real skill, the parser, sessions beyond the config check, embeddings, RAG.

## Files expected to change
`skills/health/SKILL.md`, `src/idx_agent/mcp_server/server.py`, `scripts/install.sh`,
`docs/adrs/0002-routing-and-tool-route.md`, `docs/DECISIONS.md`, `docs/ARCHITECTURE.md` (routing paragraph).

## Interfaces and contracts
`health` tool and `AgentResult` per `docs/CONTRACTS.md`.

## Implementation requirements
1. The MCP server starts with one command and logs a structured line per tool call with a trace id.
2. A WhatsApp message from the allowlisted number produces a reply that contains the tool's result.
3. A message from any other number produces no reply.
4. With the shell tool disabled, asking the bot to "run ls" or "open a shell" produces a refusal and no tool call.
5. Two test senders (if a second number is available) do not share session state; otherwise record how this will be tested in WO-004.
6. The ADR names the routing option, the tool route, and the session owner, with the reason and what would reverse each.

## Safety requirements
Shell tool unavailable to the user-facing agent; allowlist; secrets only in environment; nothing from the OpenClaw workspace committed.

## Tests required
`tests/test_mcp_health.py`: the tool returns a valid `AgentResult` (unit, no OpenClaw). The WhatsApp checks are manual; record them in Status with the date.

## Acceptance criteria
- Allowlisted message -> typed tool -> structured reply, with the shell tool off.
- Outside number -> no reply.
- Trace shows message, skill, tool call, result, reply.
- ADR-0002 written; DECISIONS.md updated; ARCHITECTURE.md routing paragraph no longer says "open".

## Verification commands
```
python -m idx_agent.mcp_server.server   # starts; logs its tool list
pytest tests/test_mcp_health.py
./scripts/install.sh                    # links skills, registers the server
# then: send "health check" from the allowlisted number; send from another number
```

## Deliverables
One working tool end to end, the install script v0, ADR-0002, updated decisions.

## Stop conditions
- OpenClaw cannot disable the shell tool for one agent by config -> record and ask; do not ship with it on.
- OpenClaw cannot load a Python MCP server -> record the error and the plugin route's cost; ask.
- WhatsApp linking fails or requires a number that is not dedicated -> stop; do not use a personal number without an allowlist.
- Any step would put OpenClaw state, auth files, or the workspace into the repo.

## Status
not started
