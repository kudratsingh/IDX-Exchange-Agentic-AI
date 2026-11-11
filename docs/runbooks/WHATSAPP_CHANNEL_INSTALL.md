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
| G3 | Transport and credential decision made (Baileys, Cloud API or other) and its transport PR merged. Without the plugin's `cloudApi` block the entry ships `unavailableTransport`, which reports unconfigured and rejects every send. | **BLOCKED.** Cloud API transport merged (WO-038, #184); its wiring, off by default, is WO-039; live setup waits for separate written approval (section 7). |
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
- Any plugin line (the plugin's JSON lines) with message text, a peer number, a session key
  or a run id. The host's own routing and diagnostic lines carry peers, message ids, session
  keys and run ids by design; they are not an abort, and the 7.5 leak check reads only lines
  that name `idx-whatsapp-channel`.
- `gateway status --require-rpc` fails, or the `idx` MCP probe changes.

Record the outcome (pass, fail or aborted, and which step) in `docs/EVIDENCE_LOG.md`
under WO-037, formats only, no numbers or message text.

## 7. Cloud API send path (BLOCKED until separate written owner approval; WO-039)

**Live setup requires separate written owner approval.** That covers the credentials,
the number, the tunnel, the webhook subscription, every live send and the smoke test
below. Nothing in this section is approved by the merge of WO-039, which only wired the
code, off by default, and proved it offline and on the pinned host with synthetic
credentials and a fake Graph API.

**Adding any buyer to the allowlist requires separate written owner approval.** Bounded
persistent dedupe (WO-040) was the precondition for that; until the owner approves a
buyer, the effective allowlist holds `<OWNER_TEST_NUMBER>` only. The effective
list is `channels.whatsapp.accounts.default.allowFrom` when that key exists (it never
falls back to the channel-wide list then), else `channels.whatsapp.allowFrom` (section 1,
C3). Check both before every step of this section:
```bash
openclaw config get channels.whatsapp.allowFrom --json            # ["<OWNER_TEST_NUMBER>"]
openclaw config get channels.whatsapp.accounts.default.allowFrom --json   # not found, or ["<OWNER_TEST_NUMBER>"]
```
Duplicate deliveries are recognised across restarts (WO-040). The gateway keeps a small
store, the directory `cloud-api-dedupe.v1/`, inside the same owner-only directory as the
credentials file. It creates the store itself on the first enabled start (mode 700) and,
before a message from an allowlisted sender starts a turn, creates one marker file for it
there (mode 600); messages from anyone else never touch it (the channel drops them, so no
turn can follow), so strangers cannot fill it. A marker is named by a keyed hash of the
message id (the key is derived from the business phone-number id, so every gateway
process for the number names it alike) and holds Meta's timestamp: never an id, a number
or a text. It is created with an exclusive create, which the file system grants to exactly
one process, so an old and a new gateway process overlapping during a restart can never
both handle a message; there is no lock and no salt file to go wrong. Markers are kept for
24 hours, far longer than the webhook's 35-minute acceptance window (the 30-minute age
limit plus 5 minutes of clock margin), so a wall-clock jump cannot make it forget a
message that could still be retried. At most 4096 markers; when full, a marker is removed
early only when a Meta timestamp shows it can no longer be accepted, never on our clock
alone, and that timestamp is written to the store first (the eviction watermark, in its
`.evicted/` subdirectory): every gateway process then treats any message older than it,
less the 35-minute window, as already seen, so a clock that moves back cannot let a retry
of an evicted message through an older or a newer process. A full store or one that
cannot be written answers Meta with 503 (Meta retries) and logs `dedupe-store-failed` with
the reason, and nothing starts. Finder's `.DS_Store` and other
dot-files in the store are ignored; any other file there refuses the store at the next
start (`dedupe-unexpected-file`). A store that fails its owner-only checks refuses the
whole Cloud API at register (`cloud-api-refused`, reason `dedupe-<reason>`) and is never
rewritten: look at it and fix the cause (a mode, an owner, a stray file) rather than
remove it; if it must go, follow the removal rule below. The store belongs to the
credentials file's directory: if the credentials file moves, move the store directory with
it, gateway stopped. Removing the store forgets its markers and its eviction watermark
(`.evicted/`), so a retry Meta still holds could start a second turn, the more so if the
gateway clock later steps back. Remove it only with the webhook unsubscribed, or after 24
quiet hours (the marker retention) with the gateway clock confirmed correct.

The owner runs every step and sends every message. The coding agent never creates, reads
or deletes the credentials file, never sees a value, never runs the tunnel or the Meta
console, and never sends.

Preconditions: G1, G2, G4 and G5 of section 1; G3 is now the WO-039 wiring merged on
`main`; eligibility questions Q2 (brokerage), Q4 (MLS and IDX display) and Q6 (hosted-model
data handling) answered in `docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md`; the separate written
approval above; section 2 backup taken, plus
`openclaw config get plugins.entries.idx-whatsapp-channel --json > "$SNAP/plugin-entry.json"`;
and the config reload mode is the default, which the fast rollback (7.6) relies on:
```bash
openclaw config get gateway.reload.mode
```
It prints `hybrid` (go on), or exits 1 with `Config path is valid but unset:
gateway.reload.mode. The runtime default applies ...` (go on: the default is `hybrid`), or
prints `off` (stop here). The unset case exits non-zero by design, so read the words, not
the exit status.

Host facts from the harness on 2026.9.5 (WO-039 mode `cloud-api`) and from that
version's bundled docs:
- the host accepts the `cloudApi` block under `plugins.entries.idx-whatsapp-channel.config`
  and validates it against the plugin's strict schema;
- the listener binds only when the account starts and is released when it stops;
- a stop (SIGTERM, `gateway stop`, `gateway restart`) first drains live work, so a reply
  already being written can still go out before the account stops. The drain budget
  depends on the supervisor (OpenClaw docs, restart and supervision): up to 315 seconds
  for a foreground gateway or systemd with a long stop timeout, 75 seconds under systemd's
  default 90-second timeout, and only 5 seconds under launchd on macOS. The harness ran a
  foreground gateway and measured that case only. Under launchd a turn still running
  about 5 seconds after the stop is cut off: either it never finishes, or its late reply
  reaches a stopped account and is withheld, never sent (proven offline only, CE-8);
- an edit under `channels.whatsapp` restarts the channel only after live turns finish;
- the transport keeps the credentials it was built from for the life of the gateway
  process. A changed credentials file takes effect only in a fresh process: use
  `openclaw gateway stop`, then `openclaw gateway start`. A hot reload, `SIGUSR1` or
  `/restart` stays inside the running process, and plain `openclaw gateway restart`
  normally goes through the service manager but can fall back to an in-process restart
  (OpenClaw docs). Inside the same process a register that finds other values in the file
  is refused `credentials-changed` and the channel goes unconfigured (fail closed, never
  the old values); if that line appears, stop and start the gateway;
- the host's plugin logger takes strings only; the plugin sends its fixed fields as one
  JSON line, so lines appear as `[plugins] {"component":"idx-whatsapp-channel...",...}`.

### 7.1 Credentials file (owner only)
One JSON file, created by the owner on the gateway machine:
- outside the repo and outside `~/.openclaw` (for example `$HOME/idx-owner-secrets/`);
- the directory owned by the gateway's user, mode 700; the file owned by that user, mode
  600 (or 400); a regular file, not a symlink and not hard-linked; on macOS no ACL on the
  file or the directory (`ls -led` shows no numbered entries);
- the gateway makes one directory there, its dedupe store `cloud-api-dedupe.v1/` (section
  7, store paragraph), so the directory must stay writable by the gateway's user; nothing
  else may write to it;
- exactly six keys, each a non-empty string, nothing else (no `accountId`):
  `accessToken` (the system-user token), `appSecret` (the Meta app secret),
  `graphApiVersion` (`vNN.N`), `phoneNumberId` (the business number's id),
  `verifyToken` (16 to 256 printable characters, no spaces, chosen by the owner and
  different from the two secrets) and `webhookPath` (absolute, 1 to 8 plain segments, for
  example `/<RANDOM_SEGMENT>/whatsapp`).

Never paste a value into chat, a ticket, a commit, a shell command or shell history. Type
the values in a local editor:
```bash
umask 077
mkdir -p "$HOME/idx-owner-secrets" && chmod 700 "$HOME/idx-owner-secrets"
"${EDITOR:-vi}" "$HOME/idx-owner-secrets/cloud-api.json"
chmod 600 "$HOME/idx-owner-secrets/cloud-api.json"
ls -led "$HOME/idx-owner-secrets" "$HOME/idx-owner-secrets/cloud-api.json"   # owner only, no ACL lines
```
Shape only (placeholders, never real values in any tracked file):
```json
{ "accessToken": "<ACCESS_TOKEN>", "appSecret": "<APP_SECRET>", "graphApiVersion": "<vNN.N>",
  "phoneNumberId": "<PHONE_NUMBER_ID>", "verifyToken": "<VERIFY_TOKEN>", "webhookPath": "<WEBHOOK_PATH>" }
```

### 7.2 Enable the `cloudApi` block
The block names the file and the loopback port; it never holds a secret.
```bash
openclaw gateway stop
openclaw config set plugins.entries.idx-whatsapp-channel.config.cloudApi \
  '{"enabled":true,"credentialsFile":"<ABSOLUTE_PATH_TO_cloud-api.json>","listen":{"host":"127.0.0.1","port":<OWNER_PORT>}}' \
  --strict-json --expect-current-absent
openclaw config validate
openclaw gateway start
openclaw logs --follow        # expect listener-started; there must be no cloud-api-refused line
openclaw channels status --channel whatsapp --probe
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:<OWNER_PORT>/"    # 404: only the webhook path is served
```
`<OWNER_PORT>` is an unused port from 1024 to 65535; the host is `127.0.0.1` or `::1`
only.

Verified on 2026.9.5, offline (2026-11-08; harness modes `cloud-api` and
`cloud-api-rollback`, check K, with a synthetic file and port in a sandboxed temporary
state): this exact `config set` exits 0 and prints `Updated
plugins.entries.idx-whatsapp-channel.config.cloudApi`; `config validate` passes; `config get
... --json` reads the block back unchanged; and a gateway started from that config passes
every Cloud API check (S, W, G, U, N, R, X). The host checks the plugin's strict schema at
`config set`: a listener host of `0.0.0.0`, an extra key and a string `"true"` for
`enabled`, each tried as a real set, exit 1 with the schema's own message and leave the
file byte for byte unchanged. Run a second time, the command is refused
by `--expect-current-absent` (exit 1, file unchanged), so a repeated paste cannot overwrite
a live block; the message it prints ("The config file changed while this command was
writing ...") is the host's generic wording for that refusal, so check the current block
with `config get` instead of re-running. The CLI also says the change "will apply without
restarting the gateway": on a running gateway it would be hot-applied in the running
process, which is why the gateway is stopped first and the block is first read by a fresh
process.

A `cloud-api-refused` line means the channel registered unconfigured and sends nothing
(fail closed). Its reason names the problem without any value: `bad-config` (the block's
shape), `credentials-<reason>` (for example `credentials-permissions-too-open`,
`credentials-inside-repo`, `credentials-wrong-keys`, `credentials-acl-present`),
`dedupe-<reason>` (the dedupe store next to the credentials file: for example
`dedupe-permissions-too-open`, `dedupe-unexpected-file`, `dedupe-unwritable`, `dedupe-unsafe-watermark`;
see the store paragraph in section 7), `implausible-credentials`, `config-mismatch` (another plugin copy in the same process was
built from a different file or port: restart the gateway), `credentials-changed` (the file
now holds other values than the ones the running transport was built from, for example
after a rotation followed by an in-process reload: stop and start the gateway process).
Fix, then restart.

### 7.3 Tunnel restricted to the webhook path (owner-run)
Meta needs a public HTTPS URL with a valid, not self-signed certificate. Whatever the
product, the tunnel:
- targets `http://127.0.0.1:<OWNER_PORT>` only, never the gateway port;
- forwards `<WEBHOOK_PATH>` with its path, query and body unchanged, and answers 404 at
  the tunnel for every path outside it;
- keeps access logs private; the verify token appears in the GET query once, at
  subscription, so rotate it afterwards if those logs are kept: edit the file, then a full
  process restart (`openclaw gateway stop`, then `openclaw gateway start`), then re-verify
  in Meta. A hot reload or `SIGUSR1` is not enough; it is refused `credentials-changed`.

The listener is the second layer for both products below: it serves the exact raw path
only, so every encoded, dot-segment, sub-path or trailing-slash variant a tunnel can
forward gets the listener's 404 and every other method its 405 (proven offline,
`cloud-api-wiring.test.mjs` CW-11, with those exact request targets). Choose
`<RANDOM_SEGMENT>` from `[A-Za-z0-9_-]` only, so it needs no regex escaping, and the verify
token from `[A-Za-z0-9._~-]`, so no proxy re-encodes the query.

How this was verified (2026-11-08): neither tunnel binary is installed on this machine and
none was run. The rules and expected outputs below come from reading each product's source
at its latest release tag and its official docs, then an independent adversarial re-read
of the same sources that corrected several details. The owner's offline checks below are
the confirmation on the owner's own build; any output that differs means stop and report.

**Recommended: Cloudflare Tunnel, named and locally managed (`cloudflared` 2026.10.7).**
Its ingress `path` is a Go regular expression that matches anywhere in the path unless
anchored, so the anchors `^...$` are required; the matched path, query and body are
forwarded unchanged; the last rule must be a catch-all. `<CONFIG_PATH>` (mode 600):
```yaml
tunnel: <TUNNEL_UUID>
credentials-file: <CREDENTIALS_FILE_PATH>
no-autoupdate: true
loglevel: info                       # never debug: debug lines carry request paths
metrics: 127.0.0.1:<METRICS_PORT>
management-diagnostics: false
ingress:
  - hostname: <PUBLIC_HOST>
    path: '^/<RANDOM_SEGMENT>/whatsapp$'
    service: http://127.0.0.1:<OWNER_PORT>
  - service: http_status:404
```
Leave `originRequest` unset. A misspelled key inside a rule (for example `pathh:`) is only a
warning and leaves a hostname-only rule that forwards every path; a misspelled top-level
key is not reported at all, so copy the keys exactly. Never add `cloudflared tunnel route
ip` routes to this tunnel (private-network routing bypasses ingress rules), and never
migrate it to a dashboard-managed tunnel (pushed dashboard config replaces this ingress).
The local metrics port serves the ingress (with the path) to local users, so run it on a
host with no other users. A locally managed tunnel still uploads its ingress to the
Cloudflare account, so only the owner should hold tunnel access there. Turn on Always Use
HTTPS for the zone: the rule ignores the scheme. A `<PUBLIC_HOST>` deeper than one level
below the zone needs its own edge certificate, or Meta's verification fails.

Owner offline checks (they parse the config file only; always pass `--config`; quote every
URL):
```bash
cloudflared --version                                                   # 2026.10.7
cloudflared tunnel --config <CONFIG_PATH> ingress validate; echo "exit=$?"
#   Validating rules from  <CONFIG_PATH>
#   OK
#   exit=0            any "unused keys" warning instead of OK is a failure: fix the key
cloudflared tunnel --config <CONFIG_PATH> ingress rule 'https://<PUBLIC_HOST><WEBHOOK_PATH>'
#   Using rules from <CONFIG_PATH>
#   Matched rule #0
#   <TAB>hostname: <PUBLIC_HOST>
#   <TAB>path: ^/<RANDOM_SEGMENT>/whatsapp$
#   <TAB>service: http://127.0.0.1:<OWNER_PORT>
```
(`<TAB>` is one tab character.)
The same `Matched rule #0` for `'https://<PUBLIC_HOST><WEBHOOK_PATH>?hub.mode=subscribe&hub.challenge=1'`
(only the path is matched). Each of these must print `Matched rule #1` and
`service: http_status:404`: `'https://<PUBLIC_HOST>/'`, `'https://<PUBLIC_HOST><WEBHOOK_PATH>/'`,
`'https://<PUBLIC_HOST><WEBHOOK_PATH>x'`, `'https://<PUBLIC_HOST><WEBHOOK_PATH>/extra'`,
`'https://<PUBLIC_HOST>/prefix<WEBHOOK_PATH>'`, `'https://<PUBLIC_HOST>/a/..<WEBHOOK_PATH>'`,
`'https://<PUBLIC_HOST><WEBHOOK_PATH>%0A'` and `'https://<OTHER_HOST><WEBHOOK_PATH>'`. Two print
`Matched rule #0` by design, because the rule matches the decoded path while the raw one
is forwarded: `'https://<PUBLIC_HOST>/<RANDOM_SEGMENT>/whatsap%70'` and
`'https://<PUBLIC_HOST>/<RANDOM_SEGMENT>%2Fwhatsapp'`; the listener answers both with 404
(CW-11). If the webhook URL prints `Matched rule #1` instead of `#0`, the index is 1-based
in that build: stop and report before going on.

**Alternative: Tailscale Funnel (`tailscale` 1.104.5).** It is weaker here: a `--set-path`
mount forwards the whole subtree under `<WEBHOOK_PATH>` (the listener 404s it, CW-11),
strips the mount from the path (so the target must repeat it), copies the client's `Host`
header unchecked, and by default uploads a log line naming the full target path. Required
first: run `tailscaled` with `--no-logs-no-support` (not available in the macOS App Store
or Standalone app). Then, with nothing else served on port 443 (`tailscale funnel status
--json` prints `{}`, or no `<PUBLIC_HOST>:443`, no `"443"` under `TCP` and no `Foreground`):
```bash
sudo tailscale funnel --bg --https=443 --set-path=<WEBHOOK_PATH> http://127.0.0.1:<OWNER_PORT><WEBHOOK_PATH>
tailscale funnel status --json   # exactly one Handlers key, <WEBHOOK_PATH>, proxying to the same path
```
No trailing slash on either side. `<PUBLIC_HOST>` is `<MACHINE>.<TAILNET>.ts.net`.

Check from outside the machine (either product), after the approved live start:
`curl -s -o /dev/null -w '%{http_code}\n' 'https://<PUBLIC_HOST>/'` answers 404;
`curl -s -o /dev/null -w '%{http_code}\n' -X PUT 'https://<PUBLIC_HOST><WEBHOOK_PATH>'` answers
405 (from the listener); an unsigned POST to `https://<PUBLIC_HOST><WEBHOOK_PATH>` answers 401.
Cloudflare also: the `cloudflared tunnel --config <CONFIG_PATH> run <TUNNEL_NAME>` output
shows `Registered tunnel connection` lines and no `Updated to new configuration` line (that
line means the tunnel is dashboard-managed and this ingress is not what routes: stop the
tunnel and roll back); and plain HTTP,
`curl -s -o /dev/null -w '%{http_code}\n' 'http://<PUBLIC_HOST><WEBHOOK_PATH>'`, answers 301 or
308 (Always Use HTTPS), never anything from the listener. Tailscale also: after the start,
`tailscale funnel status --json` has exactly one `Handlers` key and no `Foreground` key.

### 7.4 Meta webhook subscription and verify
In the Meta app dashboard, WhatsApp configuration: callback URL
`https://<PUBLIC_HOST><WEBHOOK_PATH>`, verify token `<VERIFY_TOKEN>` (typed from the file,
never pasted into chat), then verify and save. Meta sends one GET; the log shows
`webhook-verified` (a `webhook-verify-refused` means the token or path differs: stop and
fix). Subscribe to the `messages` field only. Status updates then show as
`webhook-accepted` lines with `delivered: 0`.

### 7.5 Five-message owner smoke test (Cloud API)
The owner sends every message, from `<OWNER_TEST_NUMBER>` (the only `allowFrom` entry) to
`<BOT_NUMBER>`, with `openclaw logs --follow` open. Synthetic content only (no real
addresses or names). Wait for each reply before the next message, except M4 and M5. Lines
below are the plugin's JSON lines.

| # | Owner sends | Expected | Abort and roll back if |
|---|---|---|---|
| M1 | "hi" | One greeting within about a minute. `webhook-accepted` with `delivered: 1`; outbound `outcome: "sent"`, `rule: "no-figures"`, `boundToTurn: true`; no `send-failed`. | No reply, `SAFE_TEXT` (`unbound-turn`), two replies, `send-failed` or `send-failed-async`. |
| M2 | "What did homes in `<TEST_CITY>` sell for last quarter?" | The server's approved market reply exactly (`rule: "card"`), or `SAFE_TEXT`, or a digit-free clarification. | Any released figure that is neither the owner's nor in the server's approved reply. |
| M3 | "Show me three-bedroom listings under nine hundred thousand" | The server's approved reply for the turn's card calls, byte for byte, as the dashboard shows it (`rule: "card"`). Over 4000 characters it is `SAFE_TEXT` instead, never cut. | Different bytes, any other figure, or a reply cut short. |
| M4 | A slow request (M3's text again) | Its own reply, usually after M5's busy reply. | M4 lost, or replied twice. |
| M5 | "are you there?" within two seconds of M4 | Exactly `BUSY_TEXT`; one outbound `outcome: "busy"`. | M5 handled as a turn, or no `BUSY_TEXT`. |

Before M1, in the terminal where the checks will run, record the start time:
```bash
SMOKE_START="$(date +%Y-%m-%dT%H:%M:%S)"
```
Then, with no message, one log check prints two verdicts. It prints `leaks: clean` and
`failures: clean` only when all of these hold; otherwise it prints a `REVIEW:` line for
each problem and `not checked` for both verdicts:
- the log read itself succeeded (`openclaw logs` exits non-zero on any error, for example a
  `--limit` above 5000 or a `--max-bytes` above 1000000, and then prints no log lines);
- the read reaches back past `SMOKE_START` (one read returns at most the last 5000 lines,
  so a busy log could cut the start of the test off);
- since `SMOKE_START` the log holds exactly the smoke test's events: 5 inbound messages
  (the sum of `delivered` over the plugin's `webhook-accepted` lines; M4 and M5 may arrive
  as one line with `delivered: 2`), 4 replies (outbound `outcome` `sent` or `safe-text`:
  M1, M2, M3, M4) and 1 busy reply (M5).
Then, over every line since the start that names `idx-whatsapp-channel`, the leak verdict
looks for anything the owner sent or any identifier (the match ignores case, so "Are you
there?" counts), and the failure verdict for any line at level `warn` or `error` and any
refusal, failure, drop, handler error or withheld send by name. The owner types the leak placeholders locally, in the terminal only (never pasted
into chat or a ticket), and clears that history line afterwards:
```bash
SMOKE_EXPECT_IN=5 SMOKE_EXPECT_REPLY=4 SMOKE_EXPECT_BUSY=1
SMOKE_LEAK_RE='<OWNER_TEST_NUMBER_DIGITS>|<PHONE_NUMBER_ID>|<WEBHOOK_PATH>|wamid\.|agent:|are you there|sell for last quarter|three-bedroom|nine hundred|<TEST_CITY>'
```
<!-- owner-check:smoke-log:begin -->
```sh
(
  umask 077
  log="$(mktemp)" && sel="$(mktemp)" || exit 1
  ok=yes
  say() { echo "REVIEW: $1"; ok=no; }
  [ -n "${SMOKE_START:-}" ] || say "SMOKE_START is not set"
  [ -n "${SMOKE_LEAK_RE:-}" ] || say "SMOKE_LEAK_RE is not set"
  openclaw logs --plain --local-time --limit 5000 --max-bytes 1000000 > "$log" 2>/dev/null \
    || say "the log read failed"
  first="$(grep -m1 -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "$log" | cut -c1-19)"
  awk -v a="$first" -v b="${SMOKE_START:-}" 'BEGIN { exit !(a != "" && b != "" && a < b) }' \
    || say "the read does not reach back to SMOKE_START"
  awk -v s="${SMOKE_START:-~}" 'substr($0, 1, 19) >= s' "$log" | grep -F 'idx-whatsapp-channel' > "$sel"
  n_in=$(awk '/ plugins \{"component":"idx-whatsapp-channel\.cloud-api","event":"webhook-accepted","delivered":[0-9]+,/ { d = $0; sub(/.*"event":"webhook-accepted","delivered":/, "", d); sub(/,.*/, "", d); n += d } END { print n + 0 }' "$sel")
  n_reply=$(grep -c -E ' plugins \{"component":"idx-whatsapp-channel\.outbound","outcome":"(sent|safe-text)"' "$sel")
  n_busy=$(grep -c -F ' plugins {"component":"idx-whatsapp-channel.outbound","outcome":"busy"' "$sel")
  [ "$n_in" = "${SMOKE_EXPECT_IN:-}" ] || say "inbound messages: $n_in, expected ${SMOKE_EXPECT_IN:-?}"
  [ "$n_reply" = "${SMOKE_EXPECT_REPLY:-}" ] || say "replies: $n_reply, expected ${SMOKE_EXPECT_REPLY:-?}"
  [ "$n_busy" = "${SMOKE_EXPECT_BUSY:-}" ] || say "busy replies: $n_busy, expected ${SMOKE_EXPECT_BUSY:-?}"
  if [ "$ok" = yes ]; then
    grep -Eqi -e "$SMOKE_LEAK_RE" "$sel"; rc=$?
    case $rc in 0) echo "leaks: REVIEW: abort" ;; 1) echo "leaks: clean" ;; *) echo "leaks: REVIEW: the pattern did not run (grep exit $rc)" ;; esac
    grep -Eq -e '^[^ ]+ (warn|error) ' -e '"outcome":"not_sent"|"reason":"unbound-turn"|"event":"inbound-dropped"|send-failed|cloud-api-refused|webhook-verify-refused|webhook-rejected|webhook-error|inbound-handler-error|dispatch-error|listener-error|credentials-changed' "$sel"; rc=$?
    case $rc in 0) echo "failures: REVIEW: abort" ;; 1) echo "failures: clean" ;; *) echo "failures: REVIEW: the pattern did not run (grep exit $rc)" ;; esac
  else
    echo "leaks: not checked"
    echo "failures: not checked"
  fi
  rm -f "$log" "$sel"
)
```
<!-- owner-check:smoke-log:end -->
Anything but those two `clean` lines is an abort: roll back (7.6), then look at the log
by hand. The counts use only the plugin's own JSON lines (`plugins {"component":...`), so
each event counts once. Timestamps are compared as local wall-clock time without the
offset, so do not run the smoke test across a daylight-saving change (on the fall-back
night, between 00:00 and 02:00 local time); if a run crosses one, record `SMOKE_START`
again and repeat it. It was run against the real 2026.9.5 gateway in the harness (mode
`cloud-api`, check O, with the harness's own expected counts) and against fixture logs in
`tests/test_runbook_owner_checks.py`, including a failed read, a read that does not reach
back, missing or extra events, a leak, a failure line and a bad pattern.
Abort at any step also on: a reply to any number other than `<OWNER_TEST_NUMBER>`; any
message the owner did not trigger; two replies to one message (a dedupe miss); plugin
status `error`; a plugin line (the plugin's JSON lines) with message text, a peer number, a message id, a session key,
a run id, a path or a token; a run of `webhook-rejected` / `bad-signature` lines (someone
other than Meta is posting: stop the tunnel first). If the gateway restarts during the
test, the dedupe store keeps every message recorded before the restart, so a Meta retry
of one of them is counted `ignored` and starts nothing (proven on the pinned host, harness
mode `cloud-api-restart`, check E). A second reply to one message is still the two-replies
(dedupe-miss) abort above.
Record the outcome (pass, fail or aborted, and the step) in `docs/EVIDENCE_LOG.md`,
formats only.

### 7.6 Rollback
**Fast** (stops the Cloud API inside the running gateway within seconds; nothing is
deleted). Record the start and the listener URL first (`[::1]` instead of `127.0.0.1` if
the block listens on `::1`), then make the edit:
```bash
ROLLBACK_START="$(date +%Y-%m-%dT%H:%M:%S)"
OWNER_LISTEN_URL="http://127.0.0.1:<OWNER_PORT>/"
# run the confirmation block below once now (it must say NOT CONFIRMED twice), then:
openclaw config set plugins.entries.idx-whatsapp-channel.config.cloudApi.enabled false --strict-json
```
Run the block below once BEFORE the edit, while the listener still runs: it must print
`NOT CONFIRMED: no listener-stopped since ROLLBACK_START` and `NOT CONFIRMED: the
listener's port did not refuse (curl exit 0, HTTP code 404)`, which proves
`OWNER_LISTEN_URL` reaches the real listener. Then make the edit above, wait about five
seconds and run it again. The rollback counts as confirmed only when the log read succeeds,
the last listener event since `ROLLBACK_START` is `listener-stopped`, and the listener's
port refuses the connection (curl exit 7, HTTP code `000`; curl ignores proxy settings and
`~/.curlrc` here). Anything else prints `NOT CONFIRMED:` with the reason: revoke the access
token in Meta at once (step 3 of the full rollback), then look by hand.
<!-- owner-check:rollback:begin -->
```sh
(
  umask 077
  log="$(mktemp)" || exit 1
  ok=yes
  say() { echo "NOT CONFIRMED: $1"; ok=no; }
  [ -n "${ROLLBACK_START:-}" ] || say "ROLLBACK_START is not set"
  [ -n "${OWNER_LISTEN_URL:-}" ] || say "OWNER_LISTEN_URL is not set"
  openclaw logs --plain --local-time --limit 5000 --max-bytes 1000000 > "$log" 2>/dev/null \
    || say "the log read failed"
  first="$(grep -m1 -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "$log" | cut -c1-19)"
  awk -v a="$first" -v b="${ROLLBACK_START:-}" 'BEGIN { exit !(a != "" && b != "" && a < b) }' \
    || say "the read does not reach back to ROLLBACK_START"
  since="$(awk -v s="${ROLLBACK_START:-~}" 'substr($0, 1, 19) >= s' "$log")"
  last=$(printf '%s\n' "$since" | awk '/"component":"idx-whatsapp-channel\.cloud-api-listener","event":"listener-stopped"/ { l = "stopped" } /"component":"idx-whatsapp-channel\.cloud-api-listener","event":"listener-started"/ { l = "started" } END { print l }')
  case "$last" in
    stopped) ;;
    started) say "the listener started again after it stopped" ;;
    *) say "no listener-stopped since ROLLBACK_START" ;;
  esac
  code="$(curl -q --noproxy '*' -s -o /dev/null -m 5 -w '%{http_code}' "${OWNER_LISTEN_URL:-http://127.0.0.1:0/}")"; rc=$?
  { [ "$rc" = 7 ] && [ "$code" = 000 ]; } || say "the listener's port did not refuse (curl exit $rc, HTTP code $code)"
  [ "$ok" = yes ] && echo "rollback confirmed: listener-stopped logged and the port is closed"
  rm -f "$log"
)
```
<!-- owner-check:rollback:end -->
Then a fresh process, which never binds: `openclaw gateway stop && openclaw gateway start`.
The confirmation was run against the real 2026.9.5 gateway in the harness (mode
`cloud-api-rollback`, check O: `NOT CONFIRMED` while the listener ran, `rollback confirmed`
after the edit) and against fixture logs in `tests/test_runbook_owner_checks.py`.

Measured on 2026.9.5 (2026-11-08, harness mode `cloud-api-rollback`, checks H, F and V; see
WO-039 for the runs): with the default `hybrid` reload mode the `config set` alone is
hot-applied. The host replaces the plugin instance and stops the account about 0.6
seconds after the command returns (2.4 to 2.7 seconds after it was started, most of which
is the CLI's own run time). In every run so far the host did not wait for the turn that was
live at the edit: its reply was withheld (`untrusted-turn`) and made no Graph API request.
**A held reply can still go out before a deferred stop.** The host defers a channel restart
until live turns end (section 7, host facts), and nothing in its docs promises that a
plugin replacement never does the same; check H accepts that outcome
(`delivered-before-deferred-stop`: the held turn's reply goes out once, exactly, and the
account stops after it). If the host defers the stop, the listener stays bound until it
happens: until then a reply already being written can still be sent once, and a signed
message that arrives can still be accepted and start or queue a turn whose reply is sent.
That window was not exercised (the harness sends its post-edit message only after
`listener-stopped`). When the host stops at once, as in every run so far, no new turn
starts after the edit. Once the stop happens the port refuses connections, and a signed
message gets no turn and no reply. Only revoking the access token in Meta closes the
window before the stop. A fresh process
started with `enabled` false registers the plugin unconfigured, never binds the listener
and logs no `cloud-api-refused` line (off is not a refusal). Two more limits: a send already
on its way to Meta when the account stops is aborted locally but may already have been
accepted, and with reload mode `off` the edit waits for the restart. If no further reply
may go out at all, revoke the access token in Meta first (step 3 below): that cut does not
depend on the gateway. With reload mode `off`, `openclaw plugins disable
idx-whatsapp-channel` is the documented action that still applies (host docs, plugin
lifecycle); it was verified here as a config command on a stopped gateway (V), not on a
running one.

**Full**, in this order:
1. Unsubscribe the webhook: remove the `messages` subscription and the callback URL in the
   Meta app dashboard.
2. Stop the tunnel and remove its route to `<OWNER_PORT>`. Cloudflare: stop `cloudflared`,
   then `cloudflared tunnel delete -f <TUNNEL_NAME>` (the flag before the name), delete the
   `<PUBLIC_HOST>` DNS record in the Cloudflare dashboard by hand (`route dns` only creates
   records), and remove `<CREDENTIALS_FILE_PATH>` and, if no longer needed, the origin
   certificate from `cloudflared tunnel login`. Tailscale:
   `sudo tailscale funnel --https=443 --set-path=<WEBHOOK_PATH> off` (no output, exit 0;
   if it says Funnel is not available, `sudo tailscale serve --https=443
   --set-path=<WEBHOOK_PATH> off` has the same effect), then `tailscale funnel status
   --json` shows no `<PUBLIC_HOST>:443`, no `"443"` under `TCP` and no `Foreground`, and
   `https://<PUBLIC_HOST><WEBHOOK_PATH>` fails to connect. Do not use the hint the CLI printed at start
   (`tailscale funnel --https=443 off`): it removes every mount on the port.
3. Revoke the system-user access token in Meta Business settings (and rotate the app
   secret if it may have been exposed). Nothing on the gateway needs the new values:
   step 4 removes the block, after which no register builds or uses the Cloud API
   transport.
4. Remove the block with the gateway stopped: `openclaw gateway stop`, then
   `openclaw config unset plugins.entries.idx-whatsapp-channel.config.cloudApi`, then
   `openclaw config validate`, then `openclaw gateway start`. Verified offline in this
   order, on a stopped gateway (check V): the unset exits 0, validate passes, and
   `openclaw config get plugins.entries.idx-whatsapp-channel.config.cloudApi --json` then
   exits 1 with `Config path is valid but unset: ...`; `openclaw plugins disable
   idx-whatsapp-channel` exits 0 and leaves `enabled` false.
5. The owner deletes the credentials file, the dedupe store, any leftovers and the
   directory, by hand; the agent never deletes them. First list everything in it, since an
   editor may have left a backup (`cloud-api.json~`) or swap file (`.cloud-api.json.swp`)
   holding the secrets. The dedupe store is the `cloud-api-dedupe.v1/` directory (hashed
   markers only, no secret and no message data):
   ```bash
   ls -la "$HOME/idx-owner-secrets"
   rm "$HOME/idx-owner-secrets/cloud-api.json"   # then each leftover the listing showed, by name
   ls -la "$HOME/idx-owner-secrets/cloud-api-dedupe.v1"   # 32-hex-character markers, and after an early eviction an .evicted/ directory of empty 13-digit-named files
   rm -r "$HOME/idx-owner-secrets/cloud-api-dedupe.v1"
   rmdir "$HOME/idx-owner-secrets"               # fails if anything is left: list again
   ```
6. Restore the rest of the config from the section 2 snapshot (section 4, full rollback)
   and compare `plugins.entries.idx-whatsapp-channel` with `$SNAP/plugin-entry.json`.
Verify: no `listener-started` after the restart; `curl` to `127.0.0.1:<OWNER_PORT>` is
refused; `https://<PUBLIC_HOST><WEBHOOK_PATH>` no longer answers.
