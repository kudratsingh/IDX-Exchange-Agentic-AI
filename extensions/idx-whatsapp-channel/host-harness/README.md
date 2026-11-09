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

### Mode `cloud-api` (WO-039)
The plugin runs the PRODUCTION Cloud API wiring with no fake transport: the plugin config
carries an enabled `cloudApi` block, written by the runbook's own command (section 7.2,
`openclaw config set plugins.entries.idx-whatsapp-channel.config.cloudApi '<block>'
--strict-json --expect-current-absent`) through the pinned CLI in the sandbox, naming a synthetic owner credentials file (fresh random
values of plausible shape, written into `<run root>/owner-secrets/`, directory 700, file
600, removed after the run) and a free loopback port. The production reader, process
transport, listener and channel run as shipped; only the Graph API `fetch` is a fake inside
the plugin (`cloudApiDeps.fetch`), which records each request to `graph.jsonl` and answers
200 with `messages[0].id`. The harness reaches the plugin only through the listener, as the
owner's tunnel would, and signs with the synthetic app secret. Checks (pure, in
`checks.mjs`, offline-tested in `checks.test.mjs`; missing evidence or a timeout fails):
- **S** startup: `listener-started` logged, the port accepts, Meta's verification GET
  echoes the challenge, a signed statuses-only POST answers 200 (the account started),
  and no `cloud-api-refused` line appears anywhere in the run's audit log (from any
  register, in any module copy, at startup or later);
- **W** a signed genuine DM from the allowlisted 555 peer answers 200, its card call is
  admitted and the tool runs once;
- **G** exactly one Graph API request before the reload: the expected URL, the synthetic
  bearer, JSON, `redirect: "error"`, an abort signal, and a body exactly equal to the
  expected JSON whose text equals the server-approved reply and the renderer's reply;
- **U** an unsigned POST and a tampered one (signed, then changed) answer 401 and reach no
  model request, hook or tool;
- **N** a signed DM from a sender outside the allowlist answers 200 and then gets nothing;
- **R** a genuine turn is held live while a `channels.whatsapp` edit asks the host to
  restart the channel; the listener stops and binds again, nothing is sent while it is
  down, the next DM makes exactly one exact request, and the held turn's reply is named:
  `delivered-before-deferred-restart` (OpenClaw 2026.9.5 defers the restart until live
  turns end) or `voided-by-restart` (zero requests, withheld `untrusted-turn`); and the
  whole Graph API log before SIGTERM holds exactly the genuine send, the held turn's sends
  and the next turn's send, so an extra or duplicate send in any gap fails;
- **X** SIGTERM (the harness runs a foreground gateway, which drains for up to 315 s; a
  launchd service drains for 5 s, so this run does not measure that case): the gateway exits, the account stop reaches the plugin
  (`listener-stopped`), the port is released, and no Graph API request is made from the
  SIGTERM on.
Checks A and I run as in the other modes, with the Graph API requests as the outbound.
- **K** (both cloud modes) the runbook's `config set` exited 0, `config validate` passed and
  `config get` read the block back unchanged; the same command again was refused by
  `--expect-current-absent` with the file unchanged; three real sets (a `0.0.0.0` host, an
  extra key, a string `enabled`) were each refused by the plugin's strict schema with its own
  message and the file unchanged.

- **O** (both cloud modes) the runbook's owner checks, taken from the runbook between their
  `owner-check:` markers and run verbatim with `/bin/sh`, with an `openclaw` on PATH that is
  the pinned CLI against this run's sandboxed state. Mode `cloud-api`: over the genuine turn
  the 7.5 log check prints exactly `leaks: clean` and `failures: clean`; told to expect one
  inbound message too many it prints that `REVIEW` line and checks nothing; given a pattern
  that is in the log it reports the leak. Mode `cloud-api-rollback`: the 7.6 confirmation
  says `NOT CONFIRMED` (no `listener-stopped`, the port answered) while the listener runs,
  and only `rollback confirmed` after the edit.

### Mode `cloud-api-restart` (WO-040)
One genuine DM through the first gateway (one exact Graph API request), then SIGTERM and a
fresh gateway process on the same state, then the exact signed bytes of that DM again
(Meta's retry, its timestamp still inside the age limit), then a new DM. Check **E**: the
first gateway exited; its dedupe store is on disk next to the synthetic credentials file,
a mode-700 directory with a marker and no message id or marker text in any name or file; the fresh process became ready;
the retry answered 200 and was counted ignored (`webhook-accepted` delivered 0, ignored
1), reached no model request, made no Graph API request, and the first DM's card tool
ran and was hooked exactly
once in all; the new DM made exactly one more request with the exact expected body; no
`cloud-api-refused` or `dedupe-store-failed` line. Against main's in-memory dedupe this
mode fails E: the retry is counted delivered and starts a second turn (control run,
2026-11-08). Checks A, I and K run as in mode `cloud-api`.

### Mode `cloud-api-rollback` (runbook 7.6)
One gateway runs with the block from the runbook's command and delivers one genuine reply
through the fake Graph API. Then:
- **H** with a second genuine turn held live by the model, `config set
  ...cloudApi.enabled false --strict-json` on the running gateway (no restart): the host's
  hybrid reload stops the account (`listener-stopped`, then the port refuses), the held
  turn's reply is named (`delivered-before-deferred-stop`: once, exact, before the stop; or
  `voided-by-stop`: zero requests, withheld `untrusted-turn`), nothing reaches the Graph API
  from the stop on, a signed DM after the edit reaches no model, hook, tool or Graph API,
  the listener never starts again and the port still refuses at the end, and the whole
  Graph API log holds exactly the first genuine send and the held turn's;
- **F** the first gateway exited (a gateway that will not exit is killed and fails the run),
  and a fresh gateway process with `enabled` false registers, never logs
  `listener-started`, leaves the port refusing, logs no `cloud-api-refused` and sends nothing;
- **V** the second gateway exited; then `config unset ...cloudApi` exits 0, `config validate`
  passes, `config get` exits 1 with the CLI's own `Config path is valid but unset` message, and `plugins disable idx-whatsapp-channel` exits 0
  with `enabled` read back false.

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
  `../index.mjs`) with only the transport swapped for a fake loopback one (in mode
  `cloud-api`, only the Graph API `fetch`). Its manifest carries the production `cloudApi`
  schema block unchanged (pinned by CE-1). The production
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
Each mode takes about 20 to 25 seconds (`cloud-api` and `cloud-api-rollback` about a minute or two; `payloads` several minutes). Exit 0 only when every mode passes A, B and C.
Run output (logs, results) stays under `IDX_HARNESS_ROOT` and is never committed.

macOS only (`sandbox-exec`). Not part of CI: CI has no OpenClaw install.
