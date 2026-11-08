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

CODE ITEMS (C1 and C2 landed in the real-host PR; C3 and C6, and the owned card
resolver, landed with the owned-channel install items on 2026-11-07; the rest remain):
- C1 DONE: `register(api)` adds `createBeforeToolCallHandler` with `api.on("before_tool_call")`
  and no matcher, and refuses to register when a host runtime is present without `api.on`.
- C2 DONE: `resolveRoute`/`runInbound` use `api.runtime.channel` (route resolution,
  `finalizeInboundContext`, `dispatchReplyWithBufferedBlockDispatcher`).
- C3 DONE (2026-11-07): the channel drops every inbound whose sender is not on the
  allowlist before anything else (no reply, no `BUSY_TEXT`, no record, no route, no run;
  one `inbound-dropped` audit line with the reason only). Source:
  `channels.whatsapp.accounts.<id>.allowFrom` when present, else
  `channels.whatsapp.allowFrom`, compared in canonical form. Fail closed: `dmPolicy` must
  be exactly `"allowlist"`, and a missing, empty, non-array or malformed `allowFrom` (a
  `"*"`, a `@lid` id, the unreplaced `__OWNER_E164__` placeholder) drops everyone; at
  start the log says `allowlist-invalid` with the reason. TO-CONFIRM: that an edit under
  `channels.whatsapp` restarts the channel (the plugin declares
  `reload.configPrefixes: ["channels.whatsapp"]`); until confirmed, restart the gateway
  after changing the list.
- C4 Startup assertions: `session.dmScope` is `per-channel-peer`; the literal host name of
  every `CARD_TOOLS` tool is accepted by `isCardTool`; the queue-mode config of step 3.6.
- C5 The real-event capture of install prerequisite 6 (formats only, never values).
- C6 DONE (2026-11-07, owner item 12): `extensions/idx-whatsapp-channel/package.json`,
  name `idx-whatsapp-channel` (equal to the manifest id), private, no dependencies,
  `openclaw.extensions: ["./index.mjs"]`, `openclaw.compat` for 2026.9.5, and a `files`
  list of runtime files only. The explicit enable stays `openclaw plugins enable` (3.3).
  The harness keeps its own test-only package.
- C9b CONFIRMED on the pinned host (harness, 2026-11-08): the host cuts every tool
  result's text block at 8000 characters (`TOOL_RESULT_MAX_CHARS`, not configurable) and
  appends `\n…(truncated)…`; the full structured result rides in
  `result.details.structuredContent`, with `details.mcpServer` / `details.mcpTool` naming its
  source and key-like fields redacted to `***`. The channel releases the approved reply from
  those details only when they come from server `idx` and the same tool, and, when the text
  block is complete, only when both copies give the same approved reply; a cut text without
  details withholds. All 55 released payload cases (including a 25-listing search whose
  text was cut) and the 3 withheld ones passed on the real host. The text-only path requires
  the same `details.mcpServer` "idx" and `details.mcpTool` match (owner, 2026-11-08); missing
  or mismatched metadata withholds.
- C9 CONFIRMED on the pinned host (harness, 2026-11-08): `after_tool_call` fires on the
  bundled-MCP path, before the reply is delivered, with the same run id and `toolCallId`
  as `before_tool_call`. Its `result` is `{ content, details, terminate }` with ONE text
  block. That block is the host's labelled copy: `structuredContent:` plus a newline plus the
  key-sorted two-space JSON, which is also what the model sees. The renderer now accepts
  exactly that label (regression CR-RH). With it, the peer received exactly the rendered
  card bytes in both full harness runs. Any other shape still withholds the card
  (`unknown-token`).
- C10 DONE OFFLINE, TO-CONFIRM on the pinned host (complete reply token, 2026-11-08): the
  instruction is wired from the plugin, not the skills. A `before_prompt_build` hook adds
  one rule to the system prompt of a WhatsApp run the channel issued only (a stored, live
  turn on its own session key, whether or not the host has confirmed the run yet; the
  instruction grants nothing, release still needs the confirmed run): after any listing or
  market tool the whole reply is exactly `[[card:reply]]`. That one token releases the
  complete reply of every card call of the turn, in call order, caveats, empty results and
  errors included; per-listing tokens release nothing. Since the approved reply
  passthrough (2026-11-08, flagged for owner confirmation) each call's part is the
  server's own approved reply, byte for byte: the envelope's `message` (written in code by
  `channels/format.py`), or the server's error sentence for an `ok: false` result, and
  only under the four exact host names `idx__search_listings`,
  `idx__find_similar_listings`, `idx__recommend`, `idx__get_market_stats`. A
  clarification's `data.options` follow its question after "Options: ", exactly as the
  server lists them. The peer gets only those bytes: the model's spaces and newlines
  around the token are dropped, and any other character beside it withholds the reply.
  A failed call with no server text gets a fixed line of ours. The reply is withheld
  when a message holds a control, bidi or other format character (one soft hyphen in a
  stored address withholds the whole page), when the result is of an unknown shape or
  the tool name is foreign or suffixed, and when the joined reply runs over 4000
  characters. There is no chunker, so the peer gets `SAFE_TEXT` for a search page of more
  than about 19 to 25 cards, for an extended market window past about 15 months, or for
  a multi-call turn that adds up past the limit. Skill text is unchanged. Install
  needs `plugins.entries.idx-whatsapp-channel.hooks.allowConversationAccess: true` (a
  non-bundled plugin's `before_prompt_build` is gated on it, docs/plugins/hooks.md:125-134)
  and `allowPromptInjection` not `false` (step 3.2). CONFIRMED on the pinned host
  (harness, 2026-11-08): with the grant the hook fires for the WhatsApp run, but about 24 ms
  BEFORE `onAgentRunStart`, so the instruction is gated on an issued (not yet confirmed)
  run (`issuedRun`); every genuine WhatsApp model request carried it, no dashboard request
  did, and all ten real-server payload cases of that run reached the peer as exactly the
  rendered reply (own-wording renderer; the passthrough, its 55 released payload cases
  and its 3 withheld ones are offline-tested only, so the payload sweep is to be rerun on
  the pinned host). The
  strict inbound allowlist (C3) is unchanged.
- C7 DECIDED (WO-037 item 22): the host-level control is required, see 3.6b. Shared-token,
  password and admin holders can still cancel a live reply; that availability risk is
  accepted only for the owner.
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
         session.dmScope messages.queue channels.whatsapp; do
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

3.2 Set the inbound allowlist (C3), then link the production package in place from the
repo (no copy). The plugin's channel schema is strict, so first make `channels.whatsapp`
hold only the keys it accepts (`enabled`, `dmPolicy`, `allowFrom`, `accounts.<id>` with
`enabled`/`dmPolicy`/`allowFrom`, `groupPolicy: "disabled"`, `configWrites: false`,
`selfChatMode`); note any other key from the snapshot and unset it.
```bash
openclaw config get channels.whatsapp --json                           # compare with the snapshot
openclaw config set channels.whatsapp.dmPolicy '"allowlist"' --strict-json
openclaw config set channels.whatsapp.allowFrom '["<OWNER_E164>"]' --strict-json
openclaw plugins install -l "<REPO>/extensions/idx-whatsapp-channel" --force --accept-capabilities
openclaw config set plugins.entries.idx-whatsapp-channel.hooks.allowConversationAccess true --strict-json   # C10 prompt hook
openclaw config get plugins.entries.idx-whatsapp-channel.hooks --json  # allowPromptInjection must not be false
openclaw config validate                                               # must pass with our schema loaded
```
`--force` confirms the local source after review; it does not copy or overwrite the
directory. The link uses the production `package.json` (C6, `openclaw.extensions:
["./index.mjs"]`); never link `host-harness/plugin/`. If `plugins.allow` was already set
in the snapshot, 3.1 adds `idx-whatsapp-channel` to the recorded list instead.

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

3.6b Host-level control for dashboard users (required by item 22). Owner runs the audit
first; nothing here prints a secret (`config get` is redacted). Do NOT run
`openclaw gateway auth-token --show`.
```bash
openclaw config get gateway.auth --json          # mode; token/password set (redacted); allowTailscale; trustedProxy
openclaw config get gateway.bind --json; openclaw config get gateway.tailscale --json
openclaw config get gateway.trustedProxies --json; openclaw config get gateway.roles --json
openclaw devices list --json                      # every paired device and its approved scopes
openclaw security audit --json
```
If any person other than the owner can reach the dashboard (a paired device that is not
the owner's, Tailscale Serve, a proxy), they must authenticate by identity (trusted proxy
or Tailscale) and fall under a role without admin that cannot see sessions it did not
create; the shared token or password stays with the owner only:
```bash
openclaw config set gateway.roles '{"default":"dashboard","definitions":{"dashboard":{"sessions":{"others":"none"},"agents":["main"],"scopes":["operator.read","operator.write"]}}}' --strict-json --expect-current-absent
```
TO-CONFIRM for the live layout: the identity source (trusted proxy or Tailscale) and its
`identityScopes`; with roles set, device-token or bootstrap-token operator logins without a
verified identity are rejected, so the owner's own access path must be checked before
restart. The harness mode `interrupt-roles` is the proof on the pinned host.

3.7 Start and verify.
```bash
openclaw config validate
openclaw gateway start
openclaw gateway status --require-rpc
openclaw plugins inspect idx-whatsapp-channel --runtime   # loaded; channel whatsapp; hooks before_tool_call and after_tool_call (C1, C9)
openclaw plugins inspect whatsapp                         # stock: disabled or denied, not loaded
openclaw channels status --channel whatsapp --probe       # BLOCKED (G3): today "not configured / skipped"
openclaw mcp doctor idx --probe                           # unchanged tool count, idx__* names
openclaw logs --follow                                    # no "refusing to register"; no "allowlist-invalid"
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
# R5b channels.whatsapp (3.2): set back any key 3.2 unset or changed, from
#     $SNAP/channels.whatsapp.json (the allowlist values stay outside the repo)
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

## 5. Live smoke test (BLOCKED until G3; C2 and C3 are done; owner sends, agent never sends)

Setup: the owner sends from `<OWNER_TEST_NUMBER>` (on the allowlist) to `<BOT_NUMBER>` and
keeps `openclaw logs --follow` open in another terminal. Use synthetic content only (555
numbers such as `+1 555 0100`, no real addresses or names). Wait for each reply before the
next step except in S4.

| # | Owner sends | Expected | Audit line (`idx-whatsapp-channel.outbound`) |
|---|---|---|---|
| S1 | "hi" | One greeting, released unchanged. | `outcome: "sent"`, `rule: "no-figures"`, `boundToTurn: true` |
| S2 | "What did homes in `<TEST_CITY>` sell for last quarter?" (no figures) | Exactly `SAFE_TEXT`: "I couldn't send that reply safely. Please ask again." (A digit-free clarification may release instead; then name the city again.) | `outcome: "safe-text"`, reason `unverified-figures` or `card-turn-requires-tokens` |
| S3 | "Show me three-bedroom listings under nine hundred thousand" | The server's approved reply for that turn's card calls (each call's `message` as the dashboard shows it: header, every listing card, the filters line, every caveat), byte-for-byte, in call order, released through `[[card:reply]]`, with nothing before or after it. If the server asks a clarification, its options follow the question after "Options: ". A reply over 4000 characters is withheld (`SAFE_TEXT`), not cut: about 19 or more full cards in one page do that, so keep the default page size. **TO-CONFIRM (C10):** if the instruction hook did not reach the run, expect `SAFE_TEXT`. | `rule: "card"`; otherwise reason `unknown-token` or `card-turn-requires-tokens` |
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
