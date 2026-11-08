# Runbook: install and roll back the IDX WhatsApp channel (owned send path)

**Status:** DRAFT. Not run. Installation is PAUSED (WO-037, owner items 19 and 21).
**Host:** OpenClaw 2026.9.5, global npm install. Commands checked against its bundled CLI
docs, not executed. **Plugin:** `extensions/idx-whatsapp-channel/` (id
`idx-whatsapp-channel`, claims channel id `whatsapp`). **Decision record:** ADR-0016.

Markers used below: **BLOCKED** = cannot run until the named decision or PR lands.
**TO-CONFIRM** = key, flag or behaviour taken from docs or the trace, not yet observed on
the real host. **CODE ITEM** = a change the install PR must make in the plugin before
this runbook is valid.

The owner (operator) runs every command and sends every live message. The coding agent
never runs `openclaw`, `scripts/install.sh` or `consent.sh`, never reads `~/.openclaw`
or `.env`, and never sends a WhatsApp message.

## 1. Gate: all must be true before step 3

| # | Precondition | Today |
|---|---|---|
| G1 | Owner has approved the install in writing (lifting "keep installation paused"). | not met |
| G2 | The real-host replay test (`extensions/idx-whatsapp-channel/host-harness/run.mjs`) passes on the pinned host: a genuine turn delivers the exact stored card, and a dashboard request replaying both live WhatsApp IDs (run id and session key) can neither run the card tool nor suppress the genuine reply. | **not met.** Run 2026-11-07: card delivered and tool refused in every queue mode; the reply is suppressed when the replay uses `queueMode: "interrupt"` (host aborts the run). Owner decision pending (WO-037 item 22). |
| G3 | Transport and credential decision made (Baileys, Cloud API or other) and its transport PR merged. The skeleton ships `unavailableTransport`, which reports unconfigured and rejects every send. | **BLOCKED** |
| G4 | The install PR is merged into `main` with the CODE ITEMS below and green CI. | not started |
| G5 | `<REPO>` below is the main checkout on `main`, not a worktree. | — |

What is installable today: nothing on the live gateway. The plugin now loads, registers
its hook and dispatches turns on the real host (harness, 2026-11-07), but with
`unavailableTransport` the account reports unconfigured, the host never starts it, no
inbound arrives and nothing is sent: WhatsApp goes dark. Every step that needs a working
transport is marked BLOCKED.

Host facts from the harness run on 2026.9.5 that this runbook depends on:
- A plugin loaded only through `plugins.load.paths` has no install record and the gateway
  never starts it. It must be link-installed (3.2), which needs a `package.json` with an
  `openclaw.extensions` entry and `--accept-capabilities` (it declares a channel).
- Do NOT put `"whatsapp"` in `plugins.deny` when the stock WhatsApp plugin is not
  installed (it is an external package on this host): the host then resolves that id to
  the plugin that owns the `whatsapp` channel, which is ours, and leaves it out of startup.
  Use the allow-list form in 3.1 instead; the self-check accepts it.
- The host registers the plugin several times from separately loaded copies of the module
  and keeps every copy's hook; the plugin shares one ingress per process for that reason.

CODE ITEMS (C1 and C2 landed in the real-host PR; the rest remain):
- C1 DONE: `register(api)` adds `createBeforeToolCallHandler` with `api.on("before_tool_call")`
  and no matcher, and refuses to register when a host runtime is present without `api.on`.
- C2 DONE: `resolveRoute`/`runInbound` use `api.runtime.channel` (route resolution,
  `finalizeInboundContext`, `dispatchReplyWithBufferedBlockDispatcher`).
- C3 Enforce the DM policy and the owner allowlist inside the channel (the skeleton does
  not read `channels.whatsapp.dmPolicy`/`allowFrom`). Live smoke must not start without it.
- C4 Startup assertions: `session.dmScope` is `per-channel-peer`; the literal host name of
  every `CARD_TOOLS` tool is accepted by `isCardTool`; the queue-mode config of step 3.6.
- C5 The real-event capture of install prerequisite 6 (formats only, never values).
- C6 Decide `package.json` and the explicit enable entry (owner item 12). Required by the
  link install on this host; the harness has its own test-only one.
- C7 The operator interrupt residual (G2): owner decision, WO-037 item 22.
- C8 TO-CONFIRM (send-boundary review): whether the host's channel auto-enable can append
  "whatsapp" to an existing allow list once a stock package is installed. Until checked,
  C4's startup assertion must include "no plugin other than ours claims channel
  `whatsapp`".

Never link or install `extensions/idx-whatsapp-channel/host-harness/plugin/`: it is a
test-only build with an unauthenticated loopback inject port, and it logs synthetic text.
Residual recorded, not closed: any code in the gateway process can reach the plugin's
process-wide ingress through its well-known key; that is the in-process plugin trust
boundary.

## 2. Backup (operator runs; output stays outside the repo)

Snapshot through the CLI only. Nothing here is committed; the archive holds the owner
allowlist and possibly secrets, so the folder is private.

```bash
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/idx-openclaw-backups/whatsapp-channel-$TS"
mkdir -p -m 700 "$SNAP"
openclaw --version                                   > "$SNAP/version.txt"   # expect 2026.9.5
openclaw config file                                 > "$SNAP/config-path.txt"
openclaw config validate                                                       # must pass first
openclaw backup create --only-config --verify --output "$SNAP"                 # timestamped archive
for k in plugins.deny plugins.allow plugins.load.paths plugins.entries \
         session.dmScope messages.queue; do
  openclaw config get "$k" --json > "$SNAP/$k.json" 2>&1 || echo "unset" > "$SNAP/$k.unset"
done
openclaw plugins list --json                         > "$SNAP/plugins-list.json"
openclaw plugins inspect whatsapp --json             > "$SNAP/stock-whatsapp.json"
openclaw channels status --channel whatsapp --json   > "$SNAP/channels-status.json"
```

Write down, by hand, from those files: whether `whatsapp` (stock) was `enabled`; the exact
prior `plugins.deny` list (or unset); whether `plugins.allow` is set. The rollback needs
all three. TO-CONFIRM: `--only-config` copies the root file only, not `$include`
dependencies; if the live config uses includes, take a full `openclaw backup create
--verify --output "$SNAP"` as well.

## 3. Install (BLOCKED until G1-G5)

Stop the gateway first so no hot reload sees a half state (stock denied but ours not
loaded, or ours loaded before the deny, which its self-check refuses).

```bash
openclaw gateway stop
```

3.1 Keep the stock plugin out with an explicit allow list (the deny form blocks our own
plugin on this host, see above). First confirm the stock plugin is absent, then set the
allow list to every plugin id the snapshot shows as loaded, plus ours, and never
`whatsapp`. Use a conditional write so a changed list is never clobbered.
```bash
openclaw plugins inspect whatsapp                  # expect: not found (stock not installed)
# prior allow unset: list every currently loaded plugin id (from plugins-list.json) plus ours
openclaw config set plugins.allow '["<LOADED_IDS...>","idx-whatsapp-channel"]' --strict-json --expect-current-absent
```
If the snapshot shows the stock plugin installed, stop: the deny form with the stock
plugin present is untested on this host (TO-CONFIRM) and needs the harness first.

3.2 Link the plugin in place from the repo (no copy). `--force` confirms the local source
after review; it does not copy or overwrite the directory.
```bash
openclaw plugins install -l "<REPO>/extensions/idx-whatsapp-channel" --force --accept-capabilities
```
Needs the plugin's `package.json` (C6). If `plugins.allow` was already set in the
snapshot, 3.1 adds `idx-whatsapp-channel` to the recorded list instead.

3.3 Enable it.
```bash
openclaw plugins enable idx-whatsapp-channel
```

3.4 Session scope (already set by `scripts/install.sh`; check, set only if different).
```bash
openclaw config get session.dmScope                        # expect per-channel-peer
openclaw config set session.dmScope per-channel-peer       # only if it was not
```

3.5 `before_tool_call` handler: no command. The plugin registers it (CODE ITEM C1). Verified
in 3.7.

3.6 Queue mode for WhatsApp sessions. **TO-CONFIRM, do not run until traced.** The host's
documented `messages.queue` modes are `steer` (default), `followup`, `collect` and
`interrupt`; precedence is per-session `/queue` override, then
`messages.queue.byChannel.<channel>`, then `messages.queue.mode`. None of the four is an
"off" switch: `followup` queues later turns, `collect` folds them, `steer` injects into the
active run, `interrupt` aborts it. The install PR must show which value (if any) keeps
follow-ups and folding from non-WhatsApp sources out of a WhatsApp session, whether
`byChannel` keys on the session's channel or the message's source, and whether a peer can
store a `/queue` override by text. Draft shape only:
```bash
openclaw config set messages.queue.byChannel.whatsapp '"<QUEUE_MODE_TBD>"' --strict-json --expect-current-absent
```
From WhatsApp itself nothing reaches an active run: an overlapping message gets `BUSY_TEXT`.

3.7 Start and verify.
```bash
openclaw config validate
openclaw gateway start
openclaw gateway status --require-rpc
openclaw plugins inspect idx-whatsapp-channel --runtime   # loaded; channel whatsapp; hook before_tool_call (C1)
openclaw plugins inspect whatsapp                         # stock: disabled or denied, not loaded
openclaw channels status --channel whatsapp --probe       # BLOCKED (G3): today "not configured / skipped"
openclaw mcp doctor idx --probe                           # unchanged tool count, idx__* names
openclaw logs --follow                                    # no "refusing to register"; no inbound-dropped
```
Any of these failing: run the full rollback (section 4), do not debug live.

## 3b. The real-host replay harness (G2; agent may run it, nothing live)

Runs the pinned host as a real gateway in a sandbox (temporary home, state and config;
`sandbox-exec` denies every read and write under `~/.openclaw` and all outbound network
except loopback), with a fake WhatsApp transport, a scripted loopback model and a fake
`idx` MCP server. Synthetic data only; no credentials, no paid calls.
```bash
IDX_HARNESS_ROOT=<scratch dir> node extensions/idx-whatsapp-channel/host-harness/run.mjs \
  genuine-only default steer followup collect interrupt
```
One JSON line per mode with checks A (exact card delivered), B (replay did not run the
tool) and C (replay did not suppress the genuine reply); exit 0 only when all pass.

## 4. Rollback (no consent token; never wait on one)

Rollback restores config the operator changed. It deletes nothing tracked and does not
touch WhatsApp auth state, so it needs no `delete`, `paid` or `gates` token and must never
be held for one.

**Fast rollback** (stop our send path at once; WhatsApp stays dark because the stock
plugin is still excluded by the allow list, which fails closed):
```bash
openclaw plugins disable idx-whatsapp-channel && openclaw gateway restart
```

**Full rollback**, reverse order of section 3, using the values recorded in section 2:
```bash
openclaw gateway stop
# R1 queue (3.6): undo only what was set
openclaw config unset messages.queue.byChannel.whatsapp            # if it was absent before
# R2 dmScope (3.4): leave per-channel-peer; it is the repo baseline. Revert only if the
#    snapshot shows another value AND the owner asks for it.
# R3 our plugin (3.3, 3.2)
openclaw plugins disable idx-whatsapp-channel
openclaw plugins uninstall idx-whatsapp-channel --keep-files        # drops the link; repo files stay
# R4 allow (only if 3.2 added our id to plugins.allow): set it back to the recorded list
# R5 allow (3.1): back to the recorded value
openclaw config unset plugins.allow                                 # if it was unset before
# or set it back to the recorded list with --expect-current-json of the list 3.1 wrote
# R6 stock plugin: ONLY if section 2 recorded it as enabled and it is not enabled now
openclaw plugins enable whatsapp
openclaw config validate
openclaw gateway start
```
Verify against the snapshot:
```bash
openclaw gateway status --require-rpc
openclaw plugins inspect whatsapp                       # same status as stock-whatsapp.json
openclaw plugins inspect idx-whatsapp-channel           # disabled or not found
openclaw channels status --channel whatsapp --probe     # same as channels-status.json
for k in plugins.deny plugins.allow plugins.load.paths session.dmScope messages.queue; do
  openclaw config get "$k" --json                       # compare with $SNAP/$k.json or .unset
done
```
TO-CONFIRM: `plugins uninstall` also removes that plugin's own allow/deny entries and
leaves an `enabled: false` marker; it should not touch the `whatsapp` deny, but compare
`plugins.deny` after R3. TO-CONFIRM: whether the stock linked device survives the outage
without a relink (`openclaw channels login --channel whatsapp`, owner only).

Last resort, whole-file restore: `openclaw backup restore "$SNAP/<archive>.tar.gz" --target
"$SNAP/restored"` (fresh directory, never in place), then with the gateway stopped copy the
restored config file over the path in `config-path.txt`, run `openclaw config validate`,
start. TO-CONFIRM that `backup restore` accepts an `--only-config` archive.

## 5. Live smoke test (BLOCKED until G3, C2, C3; owner sends, agent never sends)

Setup: the owner sends from `<OWNER_TEST_NUMBER>` (on the allowlist) to `<BOT_NUMBER>` and
keeps `openclaw logs --follow` open in another terminal. Use synthetic content only (555
numbers such as `+1 555 0100`, no real addresses or names). Wait for each reply before the
next step except in S4.

| # | Owner sends | Expected | Audit line (`idx-whatsapp-channel.outbound`) |
|---|---|---|---|
| S1 | "hi" | One greeting, released unchanged. | `outcome: "sent"`, `rule: "no-figures"`, `boundToTurn: true` |
| S2 | "What did homes in `<TEST_CITY>` sell for last quarter?" (no figures) | Exactly `SAFE_TEXT`: "I couldn't send that reply safely. Please ask again." (A digit-free clarification may release instead; then name the city again.) | `outcome: "safe-text"`, reason `unverified-figures` or `card-turn-requires-tokens` |
| S3 | "Show me three-bedroom listings under nine hundred thousand" | **BLOCKED (#179 card resolver).** Target: a card token resolved to the exact card bytes, byte-for-byte equal to the tool's card. Today: `SAFE_TEXT` (null resolver). | target `rule: "card"`; today reason `unknown-token` or `card-without-trusted-call` |
| S4 | A slow request, then within two seconds "are you there?" | Second message gets exactly `BUSY_TEXT` ("I'm still working on your last message. Please send this one again after I reply."); the first still gets its own reply. | one `outcome: "busy"` |
| S5 | "Is 3 or 4 bedrooms better for a family?" | A reply whose only figures are 3 and 4 is released; any other figure gives `SAFE_TEXT`. | `rule: "user-figures"` or `safe-text` |
| S6 | — (owner checks logs) | No audit or ingress line carries message text, the peer number, a session key or a run id. | grep below returns nothing |

S6 check, operator side (placeholders, not real values):
```bash
openclaw logs | grep 'idx-whatsapp-channel' | grep -E '<OWNER_TEST_NUMBER_DIGITS>|are you there|bedrooms|agent:' \
  && echo "LEAK: abort" || echo "clean"
```
Not part of live smoke: the dashboard-replay check (a dashboard request reusing live
WhatsApp IDs). It runs offline and in the host harness only (G2), never against a live
WhatsApp session.

## 6. Abort criteria: any one triggers the fast rollback at once, then the full one

- A released reply carries a figure that is neither in the owner's message nor in
  resolved card bytes, or card bytes differ from the tool's card.
- Two replies to one message, or any reply in the stock plugin's style (stock not denied).
- Any reply to a number not on the allowlist, or any message the owner did not trigger
  (a proactive send got through; it must be withheld `no-turn-handle`).
- `refusing to register`, plugin status `error`, or `before_tool_call` missing from
  `plugins inspect --runtime`.
- S1 gets `SAFE_TEXT` (`unbound-turn`: the host did not confirm the issued run id).
- S4 overlap is processed as a turn, or no `BUSY_TEXT` arrives.
- Any log line with message text, a peer number, a session key or a run id.
- `gateway status --require-rpc` fails, or the `idx` MCP probe changes.

Record the outcome (pass, fail or aborted, and which step) in `docs/EVIDENCE_LOG.md`
under WO-037, formats only, no numbers or message text.
