# Real-host replay harness (WO-037 installation prerequisite)

Test-only code. Nothing here is shipped, installed or configured outside a temporary
harness state. It runs the pinned OpenClaw build as a real gateway and drives the real
host dispatch path end to end.

## What it proves
For each queue mode, one fresh gateway:
1. a genuine WhatsApp DM from a synthetic 555 sender runs the card tool
   `idx__search_listings` (bundled MCP path);
2. while that run is held live, a dashboard operator client sends `chat.send` that replays
   both live WhatsApp IDs: the genuine run id as `idempotencyKey` and its session key;
3. the hold is released and the run(s) settle.

Checks, each with its own evidence; a timeout or a missing piece of evidence fails. The
rules live in the pure `checks.mjs`, unit-tested offline in `checks.test.mjs` (CI runs it):
- **L** the genuine WhatsApp turn was live when the replay was sent: the host's own
  terminal record of the genuine run (`agent.wait`, read after it settles) brackets the
  send time, `startedAt <= sentAt <= endedAt`; the fake model was still holding the
  genuine run's request; and the peer had received nothing yet. `agent.wait` with
  `timeoutMs: 0` answers "timeout" for a live run and for an id never issued alike, so that
  answer is never read as liveness. In `interrupt-roles` the record is read by an internal
  password client, because the dashboard role cannot see the WhatsApp run.
- **A** the genuine card call was admitted, the tool ran exactly once for it, and the peer
  received exactly the stored card bytes and nothing else.
- **B** zero replay tool executions, L, AND positive evidence the replay was stopped:
  either an explicit host rejection of the `chat.send`, or a recorded hook refusal of the
  replay's own card call whose run the host then reports terminal within the deadline. A
  replay that times out fails B even when its hook refusal is in the log, and a replay
  that never reaches a tool and is never rejected has no evidence and fails B.
- **C** L, and the genuine reply reached the peer and was not replaced by `SAFE_TEXT`. Each mode
  also reports `genuineReply`: `delivered`, `cancelled-by-interrupt` (the host reported it
  interrupted the genuine run and nothing reached the peer), `replaced-by-safe-text` or
  `missing`.

Modes: `genuine-only`, `default` (no queue mode), `steer`, `followup`, `collect`,
`interrupt`, `interrupt-fresh` (an interrupt with a new `idempotencyKey`, not a replay,
to show whether cancellation needs the live ids at all), and `interrupt-roles` (the
host-level control under test). In `interrupt-roles` the gateway uses trusted-proxy
identity auth and `gateway.roles` with a `dashboard` role: `sessions.others: "none"`,
scopes read and write, no admin. A same-host proxy is simulated with `allowLoopback` and a
TEST-NET forwarded address. The dashboard user, granted read and write through
`identityScopes`, sends the interrupt, `chat.abort` and `sessions.abort` (the last two with
the live run id). C then also requires all three to be rejected, and the same user to still
chat in a session of its own (positive control). `not-allowlisted`: a DM from a synthetic
sender outside `channels.whatsapp.allowFrom` must produce no reply, no model call and no
tool call (check D), and the allowlisted peer must still get its card. `payloads`: after
the genuine turn, one more genuine turn per committed payload case (listings with feature
caveats, over-cap, empty, unavailable, feature store unavailable, clarification, similar,
recommend, market, market low-sample); check P requires each to reach the peer as exactly
the renderer's reply and the host to hand the channel the payload's own labelled block
unchanged. Every mode also runs check I: the channel's reply instruction reached every
genuine WhatsApp model request and no dashboard model request (the plugin entry is granted
`hooks.allowConversationAccess`, which the host requires for `before_prompt_build`).

## Isolation
- The host package is used in place (`OPENCLAW_PKG`, default the global npm install). It
  is never copied into this repo.
- `env -i` with a temporary `HOME`, `OPENCLAW_HOME`, `OPENCLAW_STATE_DIR` and config path,
  run from an empty working directory.
- macOS `sandbox-exec` denies every read and write under `~/.openclaw` and all outbound
  network except loopback.
- The model is `fake-model.mjs` on loopback (scripted, no key checked). The `idx` MCP
  server is `fake-mcp-idx.mjs` (stdio, one synthetic card per call). No credentials, no
  paid calls, synthetic data only.
- The gateway token is a random loopback token generated per run.

## Files
- `run.mjs`: the runner. Writes the config, link-installs `plugin/` into the temporary
  state, starts the fake model and the sandboxed gateway, injects the DM, replays from an
  operator client, collects evidence and prints one JSON result per mode.
- `plugin/`: the harness plugin. It is the production entry (`createPluginEntry` in
  `../index.mjs`) with only the transport swapped for a fake loopback one. The production
  allowlist, card capture (`after_tool_call`), turn-bound card store and resolver are used
  as shipped. An evidence wrapper records each before and after hook event, the run id
  handed to and reported by the host, and the channel's audit lines. It has its own
  test-only `package.json`.
- `fake-model.mjs`, `fake-mcp-idx.mjs`: the scripted model, which answers a card turn with
  the channel's reply token `[[card:reply]]`, and the MCP server, which serves the four card
  tools with the committed real-server payloads (`../test-support/payloads/`, made by
  tests/test_whatsapp_reply_payloads.py from the real tool code on synthetic inputs) in the
  real wire shape (structured content plus one text block equal to
  `JSON.stringify(structuredContent, null, 2)`). The expected bytes in checks A and P come
  from the channel's own renderer applied to the payload, so they cover capture, the
  turn-bound reply store, the token and the transport end to end.
- `oc-cli.sh`: runs one OpenClaw CLI command against a run root with the same isolation.

## Run
```bash
IDX_HARNESS_ROOT=<scratch dir> node run.mjs genuine-only default steer followup collect interrupt
```
Each mode takes about 20 to 25 seconds. Exit 0 only when every mode passes A, B and C.
Run output (logs, results) stays under `IDX_HARNESS_ROOT` and is never committed.

macOS only (`sandbox-exec`). Not part of CI: CI has no OpenClaw install.
