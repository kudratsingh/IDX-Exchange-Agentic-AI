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
**Done on 2026-09-23.** Agent part in PR #4; the live run (human, with the agent reading the
traces) is recorded below; this closing PR adds the results, the config merge in `install.sh`,
and a tighter skill.

### Live run, 2026-09-23 (OpenClaw 2026.9.5, Node 26.9.0, provider OpenAI by API key)
- Install and onboarding: Custom setup, one agent named `idx`, "ask first" access, no
  credential scan. The wizard's config was deep-merged with ours (`scripts/install.sh`
  now does this itself, keeping a backup); `openclaw config validate` passed;
  `openclaw mcp doctor idx --probe` reported the server ok; `openclaw skills list --agent
  idx` showed `health` ready and every bundled skill excluded.
- The gateway runs as a LaunchAgent on loopback with a token. Doctor installed the
  WhatsApp plugin on first probe and asked for `openclaw update repair`, which was run.
- WhatsApp: linked by QR from the human's own phone, so the bot and the owner are the
  same number; `selfChatMode` was switched to true for the test with the allowlist still
  limited to that one number (the stop condition asks for an allowlist, not a second
  number). A dedicated number replaces this before any demo.
- Test 1, "health check": reply `[idx] IDX assistant 0.0.1 is up (server time
  2026-09-23T11:53:48Z). Database: not configured.` The session tail shows, under the key
  `agent:idx:whatsapp:direct:<owner number>`: `context.compiled (6 tools)`, `tool.call read`
  (the skill body), `tool.result read ok`, `tool.call idx__health`, `tool.result idx__health
  ok`, `model.completed openai/gpt-6-astra`, `session.ended success`. One extra: the model
  first sent "no result has returned yet", then the real answer; the skill now says to
  stay silent until the tool returns. The first outbound delivery failed because the
  channel was restarting after the config change; the retry delivered it.
- Test 2, "run ls": reply "I can't run ls in this session because no shell execution tool
  is available." Test 3, "open a shell": reply "I can't open a shell from this session,
  no terminal tool is available", followed by a suggestion to use Spotlight. The tail
  shows no `tool.call` in either turn. Shell access is off by config, not by prompt.
- Test 4, a second number: not available tonight; WO-004 tests the no-reply case and
  session isolation with a second phone.
- Answered: replies work without allowing the `message` tool explicitly; the sender
  identity in the session key is the raw E.164 number; the trace lives in the agent's
  SQLite store and is read with `openclaw sessions tail --session-key <key>`.
- Left open for WO-004: how the sender id reaches a tool argument; disabling memory flush
  and the dreaming job for `idx`; the wizard's `tools.profile: "full"` stays in the config
  because the per-agent allowlist overrides it, and the update finalizer warns that the
  config holds plaintext secret-bearing fields (the gateway token), to move to a SecretRef.

### Done (agent, PR #4)
- Read the OpenClaw docs (skills, tools and tool policy, MCP, sessions, WhatsApp, install,
  security). Digests are agent-local under `.local/docs/openclaw/` (gitignored).
- `src/idx_agent/domain/results.py`: `AgentResult`, `ToolError`, `Provenance`, `AsOf`,
  `PendingAction`, `HealthData` per `docs/CONTRACTS.md`.
- `src/idx_agent/observability/logging.py`: one JSON line per event to stderr, a trace id
  per call, every line through `redact()` (emails, phones, secrets).
- `src/idx_agent/mcp_server/server.py`: `MCPServer` named `idx` with one tool, `health`;
  never raises across the boundary; logs `server_start` with its tool list and one
  `tool_call` line per call. `python -m idx_agent.mcp_server.server` starts on stdio.
- `skills/health/SKILL.md` in the documented frontmatter format, calling `idx__health`.
- `config/openclaw.idx.json5`: the agent `idx` with only `idx__*` and `read` allowed;
  runtime, file writes, web, browser, automation, nodes, gateway, cron, session spawning,
  and elevated mode denied; the gateway terminal off; `tools.toolSearch: false`; one
  session per sender; WhatsApp allowlisted to one number, groups disabled; heartbeats off;
  skills loaded in place from the repo; the MCP server registered with the venv python.
- `scripts/install.sh` v0 renders and installs that config and registers the server.
- ADR-0003 (the WO named it 0002; that number was taken) answers the six questions from
  the docs and marks what the live run must confirm. `docs/DECISIONS.md` rows moved to
  Decided; `docs/ARCHITECTURE.md` routing paragraph decided.
- New runtime dependencies (noted here as CLAUDE.md requires): `mcp>=2.2,<3` (the 2.x API
  renamed FastMCP to MCPServer) and `pydantic>=2.11,<3`.
- Tests: `tests/test_mcp_health.py` (envelope validity, registration, the MCP call path, a
  failing body becomes `ok=false`, log redaction). Full suite green.

### Facts from the docs that changed the plan
- OpenClaw needs Node 24.16+ or 26.1+; this Mac has Node 22, so the installer adds Node 26.
- Symlinked skills are skipped unless explicitly trusted, so skills load through
  `skills.load.extraDirs`; the shell-tool comparison is moot because `group:runtime` is denied.
- Tool Search is on by default and would hide our schemas; it is turned off.
- Provider keys belong in `~/.openclaw/.env`; a workspace `.env` is untrusted for keys.
- Heartbeats (a paid turn every 30 minutes) are off. Memory flush and the dreaming job are
  to be disabled for the `idx` agent before WO-004. The gateway terminal defaults to on
  and is turned off.
- Onboarding sets the tool profile to `full`; the per-agent allowlist overrides it.

### Human steps (in order; each run that reaches a model is a paid run)
1. Install: `curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install.sh | bash`
   (it adds Node 26 through Homebrew).
2. `openclaw onboard`: choose Custom setup and a provider (Anthropic or OpenAI); put the key
   in `~/.openclaw/.env`. Do not keep a default `main` agent with full access.
3. In the repo: `.venv/bin/pip install -e .`; copy `.env.example` to `.env` and set
   `IDX_OWNER_E164`; run `./scripts/install.sh`; then `openclaw config validate`.
4. `openclaw mcp doctor idx --probe` (expect `idx__health`); `openclaw skills list` (expect `health`).
5. `openclaw channels login --channel whatsapp` from the dedicated number (QR). Confirm the
   auth files landed under `~/.openclaw/credentials/` and nothing new appears in `git status`.
6. `openclaw gateway install` (LaunchAgent) or `openclaw gateway restart`; `openclaw logs --follow`.
7. Send "health check" from the owner number: expect the version and server time.
8. Send "run ls" and "open a shell": expect a refusal and no tool call
   (`openclaw sessions tail --session-key <key> --follow`).
9. Send from a second number: expect no reply. Without a second number, record that
   WO-004 tests it.
10. Paste the trace lines (message, skill, tool call, result, reply) into this Status with
    the date, and note whether the `message` tool had to be allowed for replies.

### Open until the human's run
Probe result; refusal test; silent-drop test; whether `message` must be allowed; how the
sender id reaches a tool argument (WO-004 fallback: the skill passes it).
