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

Checks: **A** the genuine turn delivers exactly the stored card bytes to the peer;
**B** the replay does not execute the card tool; **C** the replay does not suppress the
genuine reply. Modes: `genuine-only`, `default` (no queue mode), `steer`, `followup`,
`collect`, `interrupt`.

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
  `../index.mjs`) with a fake loopback transport, a card resolver that reads the cards the
  fake MCP server stored, and an evidence wrapper that records each hook decision and the
  run id handed to and reported by the host. It has its own test-only `package.json`.
- `fake-model.mjs`, `fake-mcp-idx.mjs`, `cards.mjs`: the scripted model, MCP server and
  card bytes.
- `oc-cli.sh`: runs one OpenClaw CLI command against a run root with the same isolation.

## Run
```bash
IDX_HARNESS_ROOT=<scratch dir> node run.mjs genuine-only default steer followup collect interrupt
```
Each mode takes about 20 to 25 seconds. Exit 0 only when every mode passes A, B and C.
Run output (logs, results) stays under `IDX_HARNESS_ROOT` and is never committed.

macOS only (`sandbox-exec`). Not part of CI: CI has no OpenClaw install.
