# Runbook: install and roll back the IDX WhatsApp channel (owned send path)

**Status:** DRAFT. Not run. Installation is PAUSED (WO-037, owner items 19 and 21).
**Host:** OpenClaw 2026.9.5, global npm install. Commands checked against its bundled CLI
docs, not executed. **Plugin:** `extensions/idx-whatsapp-channel/` (id
`idx-whatsapp-channel`, claims channel id `whatsapp`). **Decision record:** ADR-0016.

Markers used below: **BLOCKED** = cannot run until the named decision or PR lands.
**TO-CONFIRM** = key, flag or behaviour taken from docs or the trace, not yet observed on
the real host. **CODE ITEM** = a change the install PR must make in the plugin before
this runbook is valid.

**Shell: run every block of this runbook in bash.** Start `bash` once, before section 2, and
keep that one shell open to the end, so that `$SNAP`, `START_CHECK`, `SMOKE_START` and the
other variables survive between blocks. macOS's default interactive zsh does not treat `#`
as a comment (its `INTERACTIVE_COMMENTS` option is off), so a pasted annotation would be
passed to the command as arguments. `tests/test_runbook_shell_blocks.py` keeps every block
safe in both: it lints every bash and sh block for comments zsh would act on, and runs each
block in `bash` and in `zsh -f -i` with recording stubs, failing on a comment word reaching a
command, a shell error, or a block that does not run to its end.
`tests/test_runbook_owner_checks.py` runs the owner-check blocks against fixture logs, also
under `zsh -f -i`.

The owner (operator) runs every command and sends every live message. The coding agent
never runs `openclaw`, `scripts/install.sh` or `consent.sh`, never reads `~/.openclaw`
or `.env`, and never sends a WhatsApp message.

## 1. Gate: all must be true before step 3

| # | Precondition | Today |
|---|---|---|
| G1 | Owner has approved the install in writing (lifting "keep installation paused"). | not met |
| G2 | The real-host replay test (`extensions/idx-whatsapp-channel/host-harness/run.mjs`) passes on the pinned host: a genuine turn delivers the exact stored card, and a dashboard request replaying both live WhatsApp IDs (run id and session key) can neither run the card tool nor suppress the genuine reply. | **met under the 3.6b host-level control.** Item 22 is DECIDED (WO-037, 2026-11-07; C7 below): the card is delivered and the replay's tool call refused in the default, `steer`, `followup` and `collect` modes; a replayed `queueMode: "interrupt"` aborts the genuine run by design (3b), and the same interrupt from a dashboard user is refused under 3.6b (`gateway.roles`, harness mode `interrupt-roles`). Cancellation by an admin or a shared-token or password holder is accepted as an owner-only availability risk. Rerun on the pinned host at each WO-041 head: the final-head run is recorded in WO-041 Status (A3 at 9abb35f) and, for the merge head, in PR #190. |
| G3 | Transport and credential decision made (Baileys, Cloud API or other) and its transport PR merged. Without the plugin's `cloudApi` block the entry ships `unavailableTransport`, which reports unconfigured and rejects every send. | **met** by #184 to #187 (WO-038 transport, WO-039 wiring off by default, WO-040 persistent dedupe). Live setup (credentials, number, tunnel, subscription, sends) is gated by the separate written approval of section 7, not by G3. |
| G4 | The install PR is merged into `main` with the CODE ITEMS below and green CI. | **open: WO-041 is the install PR** (startup assertions C4, the stock-plugin harness mode for C8 and 3.1, the 3.6 queue trace). Met when the owner merges it on green CI. Owner decision, 2026-11-10 (WO-041), not a waiver: "Wait for the install-readiness PR to resolve G4, stock plugin exclusion and queue handling." |
| G5 | `<REPO>` below is the main checkout on `main`, not a worktree. | — |

What is installable today: the default install (sections 2 to 4, no `cloudApi` block) is
still dark. The plugin loads, registers its hooks and dispatches turns on the real host, but
with `unavailableTransport` the account reports unconfigured, the host never starts it, no
inbound arrives and nothing is sent. The section 7 path (the Cloud API block) becomes
installable once its separate written approval and its preconditions (G1, G4 and G5, the
section 7 list) are met; nothing in this runbook is approved by a merge.

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
resolver, landed with the owned-channel install items on 2026-11-07; C4 and the C8 harness
proof land in WO-041, the install PR):
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
  start the log says `allowlist-invalid` with the reason. CONFIRMED on the pinned host
  (harness mode `cloud-api`, check R; WO-039 Status, host fact 2): an edit under
  `channels.whatsapp` restarts the channel (the plugin declares
  `reload.configPrefixes: ["channels.whatsapp"]`), and the host defers that restart until
  live turns end (`deferring until ... embedded run(s) complete`). A list change therefore
  takes effect after the current turn; no gateway restart is needed.
- C4 Startup assertions, DONE in WO-041 where the 2026.9.5 plugin API exposes the data (the
  self-check runs at `register` and refuses with `refusing to register: <reason>`):
  - `dm-scope-not-per-channel-peer`: the root `session.dmScope` is not exactly
    `per-channel-peer` (unset means the host default `main`), or a route binding for
    channel `whatsapp` overrides it (`resolveAgentRoute`,
    `dist/resolve-route-C3fi9e8K.mjs:302,331,392` [218c186c0a82]). `api.config` is the
    whole root config (`dist/loader-runtime-load-CdQ5OcQq.mjs:1208-1213` [91180d699f64]).
  - `card-tool-host-names-invalid`: a `CARD_TOOL_HOST_NAMES` pin that is not the literal
    `idx__<tool>`, is over 64 characters, is rejected by `isCardTool`, or maps to another
    base. The host gives a plugin no tool list at register (the `api` builder,
    `dist/setup-registry-C0Jco-hC.mjs:373-396` [7146e121eb5a], has no such member), so the
    pins are checked statically and the names the host really presents are checked by the
    harness (check T, every mode).
  - Not an assertion: "no other plugin claims channel `whatsapp`". The `api` gives no view
    of other plugins or channel owners at register, and `registerChannel` returns nothing
    either way (`dist/loader-runtime-load-CdQ5OcQq.mjs:2938-2995`); see C8 for what is
    covered and the owner check that stays.
  - Not an assertion: the queue mode. The owner decided to leave queue settings alone
    (3.6), so there is no config to assert.
- C5 SATISFIED BY THE HARNESS (WO-037 install prerequisite 6, formats only). The harness
  plugin records, for every `before_tool_call`, the literal `event.toolName`,
  `event.runId`, `ctx.runId`, `ctx.sessionKey`, `ctx.requester` and the decision, on the
  WhatsApp path (every mode) and the dashboard path (the replay modes); check A requires
  the genuine call admitted under its issued run id, check B the replay's call refused,
  and check T (WO-041) the literal names of all four card tools. The bundled-MCP hook
  context has no `requester` (EVIDENCE_LOG, WO-037 hook trace). One gap: no check asserts
  the model-visible text of a blocked call (the host is expected to hand the model
  `blockReason`, WO-037 decision on refused calls); it is not proven on the pinned host.
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
- C10 DONE, CONFIRMED on the pinned host (complete reply token, 2026-11-08): the
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
  rendered reply (own-wording renderer). The passthrough sweep was then rerun on the pinned
  host (WO-037 Status, real-host sweep P 58/58; WO-039 Status, `run.mjs cloud-api cloud-api
  genuine-only payloads`), consistent with C9b above; WO-041 run A1 repeats it. The
  strict inbound allowlist (C3) is unchanged.
- C7 DECIDED (WO-037 item 22): the host-level control is required, see 3.6b. Shared-token,
  password and admin holders can still cancel a live reply; that availability risk is
  accepted only for the owner.
- C8 TRACED AND PROVEN with the stock package installed (WO-041; harness mode
  `stock-present` and `stock-present-allowlisted`, check Z). The host hands `register` its auto-enabled effective config,
  not the file (`dist/server-plugin-bootstrap-DsdH1fKq.mjs:24-47` [f1c13ecd94cf]). Channel
  auto-enable skips the stock `whatsapp` candidate because our manifest `preferOver`s it,
  unless the stock id is denied, disabled or explicitly selected
  (`dist/plugin-auto-enable.materialize-IpOcPSgc.mjs:161-176,209-231,341-359`
  [22f0fa98fbdd]). But a stock entry with material config, `plugins.entries.whatsapp.enabled:
  true` included (which `plugins install` writes), is added back to a restrictive allow list
  in memory (`:283-303`; the gateway logs "auto-enabled plugins for this runtime without
  writing config: - whatsapp plugin config present, added to plugin allowlist.",
  `dist/server-startup-config-DPBDTuFJ.mjs:104` [a946445f83ac]). So an allow list alone does
  NOT keep an installed stock plugin out. The self-check reads that effective config and
  refuses (`stock-whatsapp-not-denied`), so ours fails closed and the stock plugin runs
  instead: harness phase 1. With the stock entry also disabled (`openclaw plugins disable
  whatsapp`, entry `enabled: false`), auto-enable skips it (`:197-208,341`) and the loader
  leaves it out (`disabled-in-config`, `dist/config-normalization-shared-Btqp-2KT.mjs:84-86`
  [e9ea9129fdff]): harness phase 2, where ours loaded alone, the stock plugin was never
  loaded and the genuine card was delivered. Not asserted at startup (C4): "no other plugin
  claims channel `whatsapp`". The host reports a second claimant only as a load diagnostic,
  `channel already registered: whatsapp (<owner>)`
  (`dist/loader-runtime-load-CdQ5OcQq.mjs:2956-2959`), so 3.7 checks the log and `plugins
  inspect whatsapp` by hand.

Never link or install `extensions/idx-whatsapp-channel/host-harness/plugin/`: it is a
test-only build with an unauthenticated loopback inject port, and it logs synthetic text.
Residual recorded, not closed: any code in the gateway process can reach the plugin's
process-wide ingress through its well-known key; that is the in-process plugin trust
boundary.

## 2. Backup (operator runs; output stays outside the repo)

Run in bash (see the top), in the shell that stays open for the whole window.

Snapshot through the CLI only. Nothing here is committed; the archive holds the owner
allowlist and possibly secrets, so the folder is private.

```bash
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/idx-openclaw-backups/whatsapp-channel-$TS"
mkdir -p -m 700 "$SNAP"
# expect 2026.9.5
openclaw --version                                   > "$SNAP/version.txt"
openclaw config file                                 > "$SNAP/config-path.txt"
# must pass first
openclaw config validate
# timestamped archive
openclaw backup create --only-config --verify --output "$SNAP"
for k in plugins.deny plugins.allow plugins.load.paths plugins.entries \
         session.dmScope messages.queue channels.whatsapp commands.allowFrom bindings \
         gateway.auth gateway.roles gateway.trustedProxies gateway.tailscale gateway.bind; do
  if openclaw config get "$k" --json > "$SNAP/$k.json.tmp" 2> "$SNAP/$k.err"; then
    mv "$SNAP/$k.json.tmp" "$SNAP/$k.json"
  else
    mv "$SNAP/$k.json.tmp" "$SNAP/$k.failed"; echo unset > "$SNAP/$k.unset"
  fi
done
# read every non-empty .err
ls "$SNAP"/*.err | while read -r f; do [ -s "$f" ] && echo "READ: $f"; done
# never feed these to config set
grep -l __OPENCLAW_REDACTED__ "$SNAP"/*.json
openclaw plugins list --json                         > "$SNAP/plugins-list.json"
openclaw plugins inspect whatsapp --json             > "$SNAP/stock-whatsapp.json"
openclaw channels status --channel whatsapp --json   > "$SNAP/channels-status.json"
```

Exactly one of `$SNAP/<key>.json` and `$SNAP/<key>.unset` exists per key: with `--json` an
unset path prints a failure envelope on stdout and exits 1 (`dist/config-cli-C89Y1yYt.mjs:97-101`
[5cba26048ad9]), which goes to `<key>.failed`, never to `<key>.json`; stderr goes to
`<key>.err`, so a warning never lands in a value file. Read every non-empty `.err` the loop
names.

`config get` prints the runtime view: the authored config with each plugin's schema
defaults filled in and `~` paths expanded (`dist/config-cli-C89Y1yYt.mjs:94-96`; on the
pinned host, under the stock channel schema, an authored block without them reads back with
`groupPolicy: "allowlist"` and `mediaMaxMb: 50` added and a `~` authDir made absolute:
harness stock modes). So the `.json` files are for reading and comparing, not for writing back. The block
R5b restores is the authored one, read straight from the config file with a JSON tool and no
`openclaw` call:
<!-- owner-check:authored-snapshot:begin -->
```sh
(
  umask 077
  cfg="$(cat "$SNAP/config-path.txt")"
  out="$SNAP/channels.whatsapp.authored.json"
  if python3 -I -c '
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
def inc(o):
    return isinstance(o, dict) and ("$include" in o or any(inc(v) for v in o.values()))
if inc(c.get("channels", {})) or "$include" in c:
    sys.exit("uses $include")
w = c.get("channels", {}).get("whatsapp")
if not isinstance(w, dict):
    sys.exit("no channels.whatsapp block")
json.dump(w, sys.stdout, indent=2, sort_keys=True)
print()
' "$cfg" > "$out.tmp"; then
    mv "$out.tmp" "$out" && echo "authored: saved"
  else
    mv "$out.tmp" "$out.failed"; echo "authored: REVIEW: not saved; see the message above"
  fi
)
```
<!-- owner-check:authored-snapshot:end -->
It prints `authored: saved` and writes `$SNAP/channels.whatsapp.authored.json`. It stops
(`authored: REVIEW`) when the file is not plain JSON (for example JSON5 with comments), has
no `channels.whatsapp` block, or uses `$include` at the root or anywhere under `channels`: then
open the file that holds the block (the `$include` target, or the restored copy from the
section 2 archive, `openclaw backup restore`, last-resort paragraph of section 4) and copy
the block by hand into that file name; never take it from `config get`.

Secrets: `config get` replaces token and password leaves with `__OPENCLAW_REDACTED__`, and
only the gateway's own RPC write path turns that back into the real value; the CLI `config
set` would write the literal sentinel (`dist/redact-snapshot-BOWMnozc.mjs:86-91,160-166`
[f1477491f2d6]). The `grep -l` line lists every snapshot file that holds it: never pass one
of them, or an object taken from one, to `config set`. A secret leaf that is lost comes back
only from the backup archive (section 4, last resort).

Write down, by hand, from those files: whether `whatsapp` (stock) was `enabled`; the exact
prior `plugins.deny` list (or unset); whether `plugins.allow` is set, its exact list, and
whether that list contains `"whatsapp"`; the exact `plugins.entries.whatsapp` value (from
`plugins.entries.json`, for example `{"enabled": true}`); and every `channels.whatsapp` key
with its value type (in particular `dmPolicy`, `allowFrom` and how many entries it has,
`groupAllowFrom` and how many entries it has, `groups`, `selfChatMode`, `groupPolicy`, and
every `accounts.<id>` with its own `dmPolicy`, `allowFrom`, `groupAllowFrom`, `groupPolicy`
and other keys). The rollback needs all of it:
R4 restores the allow list, R5b restores the whole authored `channels.whatsapp` block from
`$SNAP/channels.whatsapp.authored.json` (the R3 uninstall deletes it), and R6 restores the stock
entry by the form that works with the restored allow list. If the snapshot's root
`dmPolicy` is not `"allowlist"` (or is unset), or any `accounts.<id>` has its own
`dmPolicy` that is not `"allowlist"`, stop and ask the owner before section 3: the restore
must never leave a DM policy unset or open, because the host default is `pairing` (pinned `docs/channels/whatsapp.md:538`
[e84687e1e3f8]), which answers strangers with a pairing code. Read `dmPolicy` from the
authored file: the runtime view shows the schema default `pairing` when it is unset. The
`gateway.*` keys are the ones 3.6b may write; they are recorded to see what 3.6b changed,
and are restored key by key (R4b), never as whole objects.

Before the window, read only, nothing changed (they show what else could message or run
during the outage):
```bash
# expect whatsapp only
openclaw channels list
# expect no enabled job
openclaw cron list --all --json
# the repos own LaunchAgents, if any
launchctl list | grep idx-exchange
# no job that sends or restarts the gateway
crontab -l
```
Window rules, from the section 3 stop until the restore is verified: no reboot and no
logout of the macOS user. On macOS `gateway stop` is a `launchctl bootout` that does not
persist a disable, so KeepAlive and RunAtLoad stay and a reboot or new login starts the
gateway again from whatever config is current (`docs/cli/gateway/service.md:175`
[2c6b2dd5ccb3]). `openclaw gateway stop --disable` persists the stop until the next explicit
`gateway start`; TO-CONFIRM whether it suits this window (the runbook's own `gateway start`
steps would re-enable it). The restore needs no download only while the stock package
stays installed (3.1 option (b)); reinstalling `@openclaw/whatsapp` is a download and needs
its own approval.

Before every `gateway stop` of the window (section 3, 7.2, 7.6 and section 4): close every
Control UI or dashboard tab, and make sure no dashboard turn is queued or running. The
host's restart recovery re-admits accepted Control UI inputs when the browser reconnects
and resumes an interrupted turn a few seconds after startup
(`docs/gateway/restart-recovery.md:25-26,408-413` [fada59ce732f]), so a dashboard input
could reach a session after a stop and start with nobody sending it. After each `gateway
start`, watch `openclaw logs --follow` for a minute: any agent run or reply the owner did
not trigger (a resumed or re-admitted turn) is an abort. After that minute, one tab may be
opened read-only to read the card-call messages that S3 and M3 compare against, sending
nothing in it; close it before the next `gateway stop`. The rule ends when the smoke test
has passed and 7.6 is not needed, or when the restore is verified after a rollback. TO-CONFIRM: `--only-config` copies the root file only, not `$include`
dependencies; if the live config uses includes, take a full `openclaw backup create
--verify --output "$SNAP"` as well.

## 3. Install (BLOCKED until G1-G5)

Run in bash, in the same shell as section 2 (`$SNAP` is used below).

Stop the gateway first so no hot reload sees a half state (stock denied but ours not
loaded, or ours loaded before the deny, which its self-check refuses).

```bash
openclaw gateway stop
```

3.1 Keep the stock plugin out with an explicit allow list (the deny form blocks our own
plugin on this host when the stock plugin is absent, see above). Set the allow list to
every plugin id the snapshot shows as loaded, plus ours, and never `whatsapp`. Use a
conditional write so a changed list is never clobbered. First see whether the stock plugin
is installed:
```bash
# not found, or installed with a status
openclaw plugins inspect whatsapp
openclaw config get plugins.entries.whatsapp --json
```
Stock plugin not installed:
```bash
# prior allow unset: list every currently loaded plugin id from plugins-list.json plus ours
openclaw config set plugins.allow '["<LOADED_IDS...>","idx-whatsapp-channel"]' --strict-json --expect-current-absent
```
Stock plugin installed (the live host had stock `@openclaw/whatsapp` 2026.9.5 installed,
EVIDENCE_LOG, WO-037 SDK survey). Owner decision, 2026-11-10 (WO-041), quoted: "Keep the
stock plugin installed while the harness checks whether the allowlist excludes it." The
harness found that the allow list alone does NOT exclude it (C8, phase 1 of the stock
modes). Option (b) below is therefore a PROPOSED route, harness-proven, awaiting the
owner's written decision; option (a) is the alternative. Neither is chosen in this runbook.

(b) PROPOSED, awaiting the owner's decision: allow list plus a disabled stock entry
(harness-proven in modes `stock-present` and `stock-present-allowlisted`, check Z; C8).
The allow list alone is not enough: while `plugins.entries.whatsapp.enabled` is `true`
(the stock install writes it), the gateway adds `whatsapp` back to the allow list in
memory, and our self-check then refuses to register. So the stock entry is disabled too,
with the gateway stopped, in this order (the harness runs exactly this sequence):
```bash
# prints: Disabled plugin whatsapp. Saved for the next Gateway start.
openclaw plugins disable whatsapp
# enabled: false
openclaw config get plugins.entries.whatsapp --json
# read the list back NOW: the disable rewrites it
openclaw config get plugins.allow --json
# prior allow unset: as above, with --expect-current-absent. Prior allow set: the recorded
# list without whatsapp, plus ours, expecting exactly the JSON the line above printed:
openclaw config set plugins.allow '["<RECORDED_IDS_WITHOUT_WHATSAPP...>","idx-whatsapp-channel"]' --strict-json --expect-current-json '<ALLOW_JSON_PRINTED_ABOVE>'
# no whatsapp
openclaw config get plugins.allow --json
```
The disable rewrites `plugins.allow` in normalized form: each id trimmed and lowercased,
known aliases mapped to their plugin id, non-string entries dropped
(`dist/config-normalization-shared-Btqp-2KT.mjs:163-166` [e9ea9129fdff]). So the expected
value is the read-back after the disable, not the snapshot. If the conditional write is
refused anyway ("The config file changed while this command was writing ..."), read the
list back again and repeat the write with that value; never drop the condition. The list
you write must hold the recorded ids (their normalized forms are fine), never `whatsapp`.
Check after 3.7: the 3.7 auto-enable check prints `auto-enable: clean`, the log has no
`refusing to register` and no `channel already registered: whatsapp`, and `openclaw
plugins inspect whatsapp` reports it disabled, not loaded. Rollback: section 4 R4 (the
recorded allow list) and R6 (the stock entry back, by the form section 4 gives for the
recorded allow list). The stock package and its linked device stay in place, so no reinstall is
needed to return to stock (TO-CONFIRM, as in section 4, whether the device needs a relink
after the outage). The harness link-installed the identical 2026.9.5 tarball (sha512 equal
to the npm registry's, from a local copy, never downloaded) because a managed archive
install runs `npm install`, which needs the network; the activation rules it exercised
distinguish only bundled and workspace origins (`config-normalization-shared:82-118`), so
they apply alike to the owner's npm install.

(a) The alternative, not chosen either: uninstall the stock plugin after section 2.
```bash
# drops its entries, allow/deny ids, install record, managed files and the whole channels.whatsapp block, leaves enabled: false
openclaw plugins uninstall whatsapp
# not found
openclaw plugins inspect whatsapp
# no whatsapp
openclaw config get plugins.allow --json
```
(`docs/cli/plugins/uninstall-and-update.md:32` [f6823e926220].) Rollback consequence: the
package is gone, so returning to stock needs a reinstall of `@openclaw/whatsapp` version
2026.9.5 with `openclaw plugins install` (a network download, owner-run) and a relink of the device
(`openclaw channels login --channel whatsapp`, owner only); TO-CONFIRM whether the stock
auth state survives the uninstall. The uninstall also deletes `channels.whatsapp`, because
the stock manifest claims that channel (the same code path as R3 in section 4, inferred for
the stock plugin, not harness-run): 3.2 then builds the block again, and a return to stock
restores it as section 4 R5b does. After it, the not-installed branch above applies.

3.2 Set the inbound allowlist (C3), then link the production package in place from the
repo (no copy). The plugin's channel schema is strict, so first make `channels.whatsapp`
hold only the keys it accepts (`enabled`, `dmPolicy`, `allowFrom`, `accounts.<id>` with
`enabled`/`dmPolicy`/`allowFrom`, `groupPolicy: "disabled"`, `configWrites: false`,
`selfChatMode`); note any other key from the authored snapshot
(`$SNAP/channels.whatsapp.authored.json`) and unset it. `config get` shows schema defaults
(for example `mediaMaxMb`) that are not authored keys; do not unset those by name. Our
channel reads `accounts.<id>.allowFrom` first and never falls back to the root list when the
account has its own (`allowlist.mjs`), so each recorded account is cut too, by its own
conditional command, and an account's own `dmPolicy` is set to `"allowlist"`:
```bash
openclaw config get channels.whatsapp --json
openclaw config unset channels.whatsapp.<KEY_OUR_SCHEMA_REJECTS>
openclaw config set channels.whatsapp.dmPolicy '"allowlist"' --strict-json
openclaw config set channels.whatsapp.allowFrom '["<OWNER_E164>"]' --strict-json
openclaw config set channels.whatsapp.accounts.<id>.allowFrom '["<OWNER_E164>"]' --strict-json --expect-current-json '<RECORDED_ACCOUNT_ALLOWFROM_JSON>'
openclaw config set channels.whatsapp.accounts.<id>.dmPolicy '"allowlist"' --strict-json --expect-current-json '<RECORDED_ACCOUNT_DMPOLICY_JSON>'
openclaw config get channels.whatsapp.accounts.default.allowFrom --json
openclaw plugins install -l "<REPO>/extensions/idx-whatsapp-channel" --force --accept-capabilities
# C10 prompt hook
openclaw config set plugins.entries.idx-whatsapp-channel.hooks.allowConversationAccess true --strict-json
# allowPromptInjection must not be false
openclaw config get plugins.entries.idx-whatsapp-channel.hooks --json
# must pass with our schema loaded
openclaw config validate
```
The `unset` line runs once per key the strict schema rejects (for example
`groupAllowFrom`, `accounts.<id>.authDir`, `accounts.<id>.groupPolicy`); the two account
lines run once per recorded account, the `dmPolicy` one only for an account with its own
`dmPolicy`; the last line must print `["<OWNER_E164>"]` or "Config path is valid but unset".
The harness stock modes run exactly these per-key commands. `--force` confirms the local
source after review; it does not copy or overwrite the directory. The link uses the production `package.json` (C6, `openclaw.extensions:
["./index.mjs"]`); never link `host-harness/plugin/`. If `plugins.allow` was already set
in the snapshot, 3.1 adds `idx-whatsapp-channel` to the recorded list instead.

3.3 Enable it.
```bash
openclaw plugins enable idx-whatsapp-channel
```

3.4 Session scope (already set by `scripts/install.sh`; check, set only if different).
```bash
# expect per-channel-peer
openclaw config get session.dmScope
# only if it was not
openclaw config set session.dmScope per-channel-peer
```

3.5 `before_tool_call` handler: no command. The plugin registers it (CODE ITEM C1). Verified
in 3.7.

3.6 Queue mode: **no config write.** Owner decision, 2026-11-10 (WO-041): "Leave queue
settings alone pending the trace and keep dashboard traffic out of the WhatsApp session
during the smoke test." Run only the read-only check:
```bash
# record it, leave it as it is
openclaw config get messages.queue --json
# unset, or no entry for whatsapp and no wildcard entry
openclaw config get commands.allowFrom --json
```
What the 2026.9.5 trace found (WO-041, offline, read from the host's `dist/`):
- The mode for a turn is the first of: the turn's own inline mode (a `chat.send`
  `queueMode`, or an inline `/queue` directive), the session's stored `/queue` mode,
  `messages.queue.byChannel.<channel>`, `messages.queue.mode`, and `steer`. The default is
  `steer` for every channel; a plugin can set a default debounce, not a mode
  (`resolveQueueSettingsCore`, `dist/settings-GfUY60zL.mjs:443-457` [f4e0965d3d1c];
  `dist/get-reply-DN4OcavF.mjs:3953` [ddacdea4bc3e]; `docs/concepts/queue.md:100-108`
  [6d163ca12fc5]).
- `byChannel` keys on the incoming message's `Provider`, not on the session: the reply
  path passes `channel: sessionCtx.Provider` (`get-reply:3398-3406`). This channel sends
  `Provider: "whatsapp"` (`index.mjs`, `createHostRunner`); every dashboard, webchat or
  Control UI `chat.send` sends `Provider: "webchat"`, even into a WhatsApp session key
  (`dist/operator-role-policy-CQ0LLlEF.mjs:67-73` [ad2d89613e59];
  `dist/message-channel-constants-Cd7Eq8Zi.mjs:3` [7bf6f3791b27]). So
  `byChannel.whatsapp` governs WhatsApp messages and `byChannel.webchat` dashboard ones,
  and a `chat.send` `queueMode` overrides every config value
  (`dist/chat-send-handler-BBsH-uIk.mjs:3279` [a363309dfead] into `get-reply:3953`).
- The channel's `BUSY_TEXT` gate covers overlaps between its own turns only
  (`ingress.hasActiveTurn`, `channel.mjs`). The host decides queueing per session key: a
  session counts as busy when any run is active on it, whatever its source
  (`get-reply:3480-3502`). So a WhatsApp message that arrives while a dashboard run is live
  on the same WhatsApp session passes the channel's gate and gets `byChannel.whatsapp`,
  then `messages.queue.mode`, then `steer`: it is injected into the dashboard run, or
  queued behind it when the two differ in tool authority
  (`dist/agent-runner.runtime-DRp6jmuv.mjs:8004-8008,8108` [f3f4732fc5ee]). Either way
  the WhatsApp turn may get no reply of its own, or only a late one. `byChannel.whatsapp` is therefore
  not inert, but no value of it refuses a second source. What protects the smoke test in
  both directions is the 7.5 rule: nothing from the dashboard or any other source into
  the WhatsApp session, plus the 3.6b role control.
- Accepted values are `steer`, `followup`, `collect` and `interrupt` only
  (`dist/zod-schema.core-CZ0zDyHR.mjs:139-163` [a0556a4cf9fe]). None refuses a second
  source: `steer` injects into the active run (or falls back to a follow-up), `followup`
  and `collect` queue behind it (`collect` drains messages from different channels one by
  one, not folded, `dist/drain-BTaNE7X8.mjs:951` [c43b88f8baa2]), `interrupt` aborts it.
- A WhatsApp peer cannot set `/queue`: directives are cleared unless the sender is
  authorized for commands (`get-reply:1024`), and with `CommandAuthorized: false`, which
  this channel passes, that is denied unless `commands.allowFrom` names the sender or `*`
  for the provider (`dist/command-auth-wg-svLNP.mjs:176-190,222-231` [5b53ddf1e137]),
  hence the read-only check above. A `/queue` stored from the dashboard on the WhatsApp
  session would also govern that session's later turns (inferred: one stored value per
  session entry).
For the owner to decide later (no choice is made here; both leave the 3.6b control and
the 7.5 rule in force):
- Option 1, skip the step: no queue config. A dashboard message into a live WhatsApp run
  follows `steer` (injected into the run, or queued on a tool-authority mismatch), and a
  WhatsApp message into a live dashboard run on that session does the same; the 7.5 rule
  (send nothing from the dashboard during the smoke) and the 3.6b role control keep both
  from happening.
- Option 2, `openclaw config set messages.queue.byChannel.webchat '"followup"' --strict-json
  --expect-current-absent`: dashboard text then waits until the WhatsApp run ends instead
  of being injected into it, for every webchat session on the gateway; a client that sends
  an explicit `queueMode` still overrides it. It covers that direction only: a WhatsApp
  message into a live dashboard run still follows `byChannel.whatsapp` or the default. Not
  run, not harness-tested here.

3.6b Host-level control for dashboard users (required by item 22). Owner runs the audit
first; nothing here prints a secret (`config get` is redacted). Do NOT run
`openclaw gateway auth-token --show`.
```bash
# mode, token/password set redacted, allowTailscale, trustedProxy
openclaw config get gateway.auth --json
openclaw config get gateway.bind --json; openclaw config get gateway.tailscale --json
openclaw config get gateway.trustedProxies --json; openclaw config get gateway.roles --json
# every paired device and its approved scopes
openclaw devices list --json
openclaw security audit --json
```
If any person other than the owner can reach the dashboard (a paired device that is not
the owner's, Tailscale Serve, a proxy), they must authenticate by identity (trusted proxy
or Tailscale) and fall under a role without admin that cannot see sessions it did not
create; the shared token or password stays with the owner only. Before any write to
`gateway.auth.mode` (a switch to `trusted-proxy` for the identity source): every CLI write
to that path deletes the other modes' credentials, the password for `token`, the token for
`password`, and both for `trusted-proxy` (`dist/config-cli-runner-CBXweqWm.mjs:221-240,382`
[4fb01f709751]). The token or password is then gone from the config. It comes back only
from the section 2 archive, by the single-leaf restore of section 4 R4c, never by copying the
restored file over the live config.
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
# for the auto-enable check below
START_CHECK="$(date +%Y-%m-%dT%H:%M:%S)"; sleep 1
openclaw gateway start
openclaw gateway status --require-rpc
# loaded, channel whatsapp, hooks before_tool_call, after_tool_call C1, C9 and before_prompt_build C10
openclaw plugins inspect idx-whatsapp-channel --runtime
# stock: not found, disabled or denied, never loaded
openclaw plugins inspect whatsapp
# before 7.2: not configured / skipped expected
openclaw channels status --channel whatsapp --probe
# unchanged tool count, names starting with idx__
openclaw mcp doctor idx --probe
# owner only, or not found
openclaw config get channels.whatsapp.accounts.default.allowFrom --json
# no refusing to register, no allowlist-invalid, no channel already registered: whatsapp
openclaw logs --follow
```
Then the auto-enable check. The host logs its in-memory auto-enable as one header line,
`gateway: auto-enabled plugins for this runtime without writing config:`, followed by one
`- <change>` line per change with no time stamp of its own
(`dist/server-startup-config-DPBDTuFJ.mjs:104` [a946445f83ac]), so a search for one line
that holds both never matches. The block below reads the log from `START_CHECK`, which the
block above records just before `gateway start`, in the same terminal. It prints
`auto-enable: clean` only when the log shows a gateway start (`gateway starting...`) at or
after `START_CHECK` and no change line under such a header names WhatsApp; it prints each
such line after `auto-enable: REVIEW:`, and `not checked` when no start is logged since
`START_CHECK` (a `START_CHECK` taken after the start would otherwise hide the header).
Run on the pinned host in the stock modes of the harness: it flagged `- whatsapp plugin
config present, added to plugin allowlist.` in phase 1 and printed clean in phase 2.
<!-- owner-check:auto-enable:begin -->
```sh
(
  umask 077
  log="$(mktemp)" || exit 1
  ok=yes
  say() { echo "auto-enable: REVIEW: $1"; ok=no; }
  [ -n "${START_CHECK:-}" ] || say "START_CHECK is not set"
  openclaw logs --plain --local-time --limit 5000 --max-bytes 1000000 > "$log" 2>/dev/null \
    || say "the log read failed"
  first="$(grep -m1 -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "$log" | cut -c1-19)"
  awk -v a="$first" -v b="${START_CHECK:-}" 'BEGIN { exit !(a != "" && b != "" && a < b) }' \
    || say "the read does not reach back to START_CHECK"
  if [ "$ok" = yes ]; then
    awk -v s="$START_CHECK" '
      /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T/ { keep = (substr($0, 1, 19) >= s); head = (keep && index($0, "auto-enabled plugins for this runtime") > 0); if (keep && index($0, " gateway starting...") > 0) st++; next }
      keep && head && tolower($0) ~ /whatsapp/ { print "auto-enable: REVIEW: " $0; n++ }
      END { if (st == 0) { print "auto-enable: REVIEW: no gateway start logged since START_CHECK"; print "auto-enable: not checked" } else if (n == 0) print "auto-enable: clean" }' "$log"
  else
    echo "auto-enable: not checked"
  fi
  rm -f "$log"
)
```
<!-- owner-check:auto-enable:end -->
Any of these failing: run the full rollback (section 4), do not debug live. One exception:
before the section 7 block is enabled, the probe line's "not configured / skipped" is the
expected result (no transport), not a failure. A missing `before_prompt_build` hook is not
a refusal either (the plugin logs `prompt-hook-unavailable` and card turns reply
`SAFE_TEXT`), but it means `allowConversationAccess` (3.2) did not take: roll back.

## 3b. The real-host replay harness (G2; agent may run it, nothing live)

Runs the pinned host as a real gateway in a sandbox (temporary home, state and config;
`sandbox-exec` denies every read and write under `~/.openclaw` and all outbound network
except loopback), with a fake WhatsApp transport, a scripted loopback model and a fake
`idx` MCP server. Synthetic data only; no credentials, no paid calls.
```bash
IDX_HARNESS_ROOT=<scratch dir> IDX_HARNESS_STOCK_TGZ=<local copy of whatsapp-2026.9.5.tgz> \
  node extensions/idx-whatsapp-channel/host-harness/run.mjs \
  genuine-only not-allowlisted default steer followup collect interrupt-roles payloads \
  cloud-api cloud-api-rollback cloud-api-restart stock-present stock-present-allowlisted
```
One JSON line per mode; exit 0 only when every requested mode passes all of its checks.
Every mode: A (the genuine turn's card call admitted, the tool ran once, exactly the
expected reply reached the peer), I (the reply instruction reached every genuine model
request and no dashboard one) and T (the card-tool names the host presented are exactly
the pinned `idx__<tool>` names). Replay modes (`default`, `steer`, `followup`, `collect`,
`interrupt-roles`) add L (the genuine run was live at the replay), B (the replay did not run
the tool) and C (the replay did not suppress the genuine reply). `not-allowlisted` adds D,
`payloads` adds P, the `cloud-api*` modes add their Cloud API checks (section 7) with K and
O, and the two stock modes add Z (C8, 3.1 (b), the 3.7 auto-enable check and the section
4 rollback). Plain `interrupt` is left out on purpose: the replay's
interrupt aborts the genuine run, so C fails (`cancelled-by-interrupt`) and B lacks its
evidence, by design (EVIDENCE_LOG, WO-037 two full runs); `interrupt-roles` is the mode that
shows the 3.6b control refusing it. The stock modes need a local copy of the stock tarball;
the harness never downloads it and refuses any copy whose sha512 differs from the
registry's.

## 4. Rollback (no consent token; never wait on one)

Run in bash, in the same shell as section 2 if it is still open; otherwise start `bash` and
set `SNAP` to the section 2 folder first.

Rollback restores config the operator changed. It deletes nothing tracked and does not
touch WhatsApp auth state, so it needs no `delete`, `paid` or `gates` token and must never
be held for one.

**Fast rollback** (stop our send path at once; WhatsApp stays dark because the stock
plugin's entry is disabled, `plugins.entries.whatsapp.enabled: false` from 3.1 (b), or the
stock package is absent (3.1 (a), or never installed). The allow list alone does not keep
an installed stock plugin out (C8): with ours disabled, nothing holds back an enabled stock
entry):
```bash
openclaw plugins disable idx-whatsapp-channel && openclaw gateway restart
```

**Full rollback**, reverse order of section 3, using the values recorded in section 2:
```bash
openclaw gateway stop
# R1 queue 3.6: nothing to undo, 3.6 writes no queue config owner decision, 2026-11-10
# R2 dmScope 3.4: leave per-channel-peer, it is the repo baseline. Revert only if the
# snapshot shows another value AND the owner asks for it.
# R3 our plugin 3.3, 3.2. Without --force, uninstall prints a preview and asks for
# confirmation, so it needs an interactive terminal docs/cli/plugins/uninstall-and-update.md:36
# The uninstall also DELETES the whole channels.whatsapp block: it removes the channel
# config of every channel our manifest declares, whether or not another plugin claims it
# dist/uninstall-config-CBhuoZUg.mjs:99-105 46b48ecb370b, harness stock modes. R5b
# puts it back. Keep SNAP/channels.whatsapp.authored.json at hand before this step.
openclaw plugins disable idx-whatsapp-channel
# drops the link, repo files stay, confirm the prompt
openclaw plugins uninstall idx-whatsapp-channel --keep-files
# expect Config path is valid but unset
openclaw config get channels.whatsapp --json
# ALLOW_JSON_AFTER_R3: the list now, without idx-whatsapp-channel
openclaw config get plugins.allow --json
# R4 allow 3.1, or 3.2 when it added our id to a recorded list: back to the recorded value,
# expecting exactly the JSON the line above printed. If the write is refused The config
# file changed while this command was writing ..., read the list back again and repeat
# with that value, never drop the condition.
# if it was unset before
openclaw config unset plugins.allow
# if it was set
openclaw config set plugins.allow '<RECORDED_ALLOW_JSON>' --strict-json --expect-current-json '<ALLOW_JSON_AFTER_R3>'
# R4b gateway 3.6b: only the sub-keys 3.6b wrote, one command each, never a whole object.
# gateway.auth is redacted in the snapshot token and password print as
# __OPENCLAW_REDACTED__, section 2: never restore gateway.auth as a whole object and never
# touch gateway.auth.token or gateway.auth.password, a lost secret comes back only from the
# backup archive.
# if it was unset before
openclaw config unset gateway.roles
# if it was set
openclaw config set gateway.roles '<RECORDED_JSON>' --strict-json --expect-current-json '<JSON_3.6b_WROTE>'
# each gateway.auth sub-key 3.6b changed, by itself mode, trustedProxy, allowTailscale,
# identityScopes, and the same for gateway.trustedProxies or gateway.tailscale.
# A write to gateway.auth.mode deletes the other modes token or password. If 3.6b changed
# the mode, write the mode back first, then the other sub-keys, then run R4c below, last,
# before R5b and before gateway start.
# if it was absent before
openclaw config unset gateway.auth.<SUBKEY>
# if it was set
openclaw config set gateway.auth.<SUBKEY> '<RECORDED_JSON>' --strict-json --expect-current-json '<JSON_3.6b_WROTE>'
```
R4c, only when 3.6b changed `gateway.auth.mode`: bring back the one secret leaf the mode
write deleted (`token` for token mode, `password` for password mode) from the section 2
archive, after every R4b line, because any later write to the mode would delete it again.
Never copy the restored file over the live config: it is the pre-window config, with every
recorded sender list and group policy, and would undo R5b's owner-only cut and the watch.
The archive is restored into a fresh `$SNAP/restored`; `backup restore` accepted an
`--only-config` archive on the pinned host (harness stock modes; it prints the restored
paths and the explicit-activation notice, and changes nothing live):
```bash
ls "$SNAP"/*.tar.gz
openclaw backup restore "$SNAP/<ARCHIVE>.tar.gz" --target "$SNAP/restored"
AUTH_SECRET=token
```
Then the block below. It writes only `gateway.auth.$AUTH_SECRET`, and only when it is unset
now, through `openclaw config patch --stdin`, so the value never appears in a command line,
the process list, the terminal or the shell history (`config patch --stdin` reads a JSON5
patch from stdin, `docs/cli/config.md:377-383` [27c7a3eae604],
`dist/config-cli-C89Y1yYt.mjs:256` [5cba26048ad9]; `config set` takes its value in argv
only). `config patch` has no expectation flags, so the block checks that the leaf is unset
first and writes nothing otherwise; the patch touches no other path, so no mode pruning
runs. It prints `secret:
restored gateway.auth.token` or a `secret: REVIEW:` line, never the value. If it says the
restored config has no such leaf, or `backup restore` fails on the owner's build, the secret
cannot be recovered this way: set a new token or password, as the owner sets one, before
`gateway start`.
<!-- owner-check:auth-secret:begin -->
```sh
(
  umask 077
  cfg="$(cat "$SNAP/config-path.txt")"
  restored="$(find "$SNAP/restored" -type f -path "*/payload/posix$cfg" 2>/dev/null | head -n 1)"
  case "${AUTH_SECRET:-}" in
    token|password) ;;
    *) echo "secret: REVIEW: set AUTH_SECRET to token or password"; exit 0 ;;
  esac
  if [ -z "$restored" ]; then
    echo "secret: REVIEW: no restored config under SNAP/restored, run the backup restore line first"
  elif openclaw config get "gateway.auth.$AUTH_SECRET" --json > /dev/null 2>&1; then
    echo "secret: REVIEW: gateway.auth.$AUTH_SECRET is already set, nothing written"
  elif ! python3 -I -c 'import json, sys; a = json.load(open(sys.argv[1], encoding="utf-8")).get("gateway", {}).get("auth", {}); v = a.get(sys.argv[2]); sys.exit(0 if isinstance(v, str) and v else 3)' "$restored" "$AUTH_SECRET"; then
    echo "secret: REVIEW: the restored config has no gateway.auth.$AUTH_SECRET, set a new one"
  elif python3 -I -c 'import json, sys; a = json.load(open(sys.argv[1], encoding="utf-8"))["gateway"]["auth"]; print(json.dumps({"gateway": {"auth": {sys.argv[2]: a[sys.argv[2]]}}}))' "$restored" "$AUTH_SECRET" | openclaw config patch --stdin > /dev/null 2>&1; then
    echo "secret: restored gateway.auth.$AUTH_SECRET"
  else
    echo "secret: REVIEW: the patch failed, nothing printed"
  fi
)
```
<!-- owner-check:auth-secret:end -->
Then the rest of the full rollback:
```bash
# R5b channels.whatsapp, after R3: the WHOLE authored block in one write, typed locally from
# SNAP/channels.whatsapp.authored.json never from the runtime-view .json, the allowlist
# values stay outside the repo. The owner-only cut applies to every sender list and to
# group access, root and each account: every allowFrom and groupAllowFrom is written as
# OWNER_E164, and groupPolicy is written as disabled at the root and in each
# account that has its own, for the watch restore order below. Guard: if the authored
# dmPolicy, root or any account, is not allowlist, stop and ask the owner section 2.
openclaw config set channels.whatsapp '<AUTHORED_BLOCK_JSON_WITH_OWNER_ONLY_LISTS>' --strict-json --expect-current-absent
# must print allowlist, never leave it unset
openclaw config get channels.whatsapp.dmPolicy --json
# the authored block as now written, read from the file not config get, to compare with
# SNAP/channels.whatsapp.authored.json the lists differ only by the owner-only cut:
python3 -I -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["channels"]["whatsapp"], indent=2, sort_keys=True))' "$(cat "$SNAP/config-path.txt")"
# R6 stock entry: ONLY if section 2 recorded it as enabled and it is not enabled now. With the
# gateway stopped, plugins enable keeps the allow list as it is and is refused blocked by
# allowlist when the list is set without whatsapp dist/management-mutations-DfooQCya.mjs:170,201
# df08dd50fd50, dist/enable--azUUNOl.mjs:90 eff28c91a912. So, by the section 2 record
# R3 to R6 in this order are harness-run, both allow-list forms: stock modes, check Z:
# recorded allow list unset or contains whatsapp, exit 0
openclaw plugins enable whatsapp
# recorded allow list set without whatsapp
openclaw config set plugins.entries.whatsapp.enabled true --strict-json --expect-current-json false
# the recorded value, enabled: true, stop if not
openclaw config get plugins.entries.whatsapp --json
openclaw config validate
openclaw gateway start
```
Restore order for the stock channel (after the outage it may answer offline messages that
WhatsApp delivers at reconnect, bounded by its dedupe lifetime and a short stale-history
guard of unknown length, `docs/channels/whatsapp.md:135`): restore with every effective
sender list holding the owner only and group access off (R5b cuts `allowFrom` and
`groupAllowFrom` at the root and in each `accounts.<id>`, and writes `groupPolicy:
"disabled"`; `open` would bypass every sender list and an unset `groupAllowFrom` falls
back to `allowFrom`, `docs/channels/whatsapp.md:290-292`); watch `openclaw logs --follow` for
10 to 15 minutes for any inbound dispatch or reply the owner did not trigger (`openclaw
gateway stop` ends an unwanted turn); then write each recorded value back with its own
paired command, all before one restart:
```bash
openclaw config set channels.whatsapp.allowFrom '<RECORDED_ALLOWFROM_JSON>' --strict-json --expect-current-json '["<OWNER_E164>"]'
openclaw config set channels.whatsapp.groupAllowFrom '<RECORDED_GROUPALLOWFROM_JSON>' --strict-json --expect-current-json '["<OWNER_E164>"]'
openclaw config set channels.whatsapp.groupPolicy '<RECORDED_GROUPPOLICY_JSON>' --strict-json --expect-current-json '"disabled"'
openclaw config unset channels.whatsapp.groupPolicy
openclaw config set channels.whatsapp.accounts.<id>.allowFrom '<RECORDED_ACCOUNT_ALLOWFROM_JSON>' --strict-json --expect-current-json '["<OWNER_E164>"]'
openclaw config set channels.whatsapp.accounts.<id>.groupAllowFrom '<RECORDED_ACCOUNT_GROUPALLOWFROM_JSON>' --strict-json --expect-current-json '["<OWNER_E164>"]'
openclaw config set channels.whatsapp.accounts.<id>.groupPolicy '<RECORDED_ACCOUNT_GROUPPOLICY_JSON>' --strict-json --expect-current-json '"disabled"'
openclaw gateway restart
```
Run each line only for a key the authored snapshot holds: `groupPolicy` by `set` when the
snapshot has a root value, by `unset` when it has none; the account lines once per account
and key. The harness stock modes run these writes (all but the 10 to 15 minute watch).
The effective list is the account's own when it has one (section 7, C3), so a recorded
account list that is not written back leaves that account owner-only. During the window the owner sends
nothing to their own number (self-chat). Never add `<BOT_NUMBER>` to the stock allowlist:
the Cloud API number writing to the stock-linked number could start a bot-to-bot loop.
Verify against the snapshot. `gateway status --require-rpc` must pass first: with the
gateway unreachable, `channels status` falls back to a config-only summary and proves
nothing (`docs/cli/channels.md:80-81` [cf5c27fc3931]).
```bash
# must pass before the probe below
openclaw gateway status --require-rpc
# same status as stock-whatsapp.json
openclaw plugins inspect whatsapp
# disabled or not found
openclaw plugins inspect idx-whatsapp-channel
# same as channels-status.json: linked and connected
openclaw channels status --channel whatsapp --probe
for k in plugins.deny plugins.allow plugins.load.paths plugins.entries session.dmScope \
         messages.queue channels.whatsapp commands.allowFrom bindings \
         gateway.auth gateway.roles gateway.trustedProxies gateway.tailscale gateway.bind; do
  # compare with SNAP/k.json or .unset
  openclaw config get "$k" --json
done
```
These compare runtime view with runtime view. For `channels.whatsapp` also compare the
authored block in the config file with `$SNAP/channels.whatsapp.authored.json` (R5b's
read-back line); a `gateway.auth` value shows its secrets as `__OPENCLAW_REDACTED__` in both.
`plugins.entries` cannot match the snapshot exactly after R3: the uninstall leaves an exact
`enabled: false` entry for our id and removes our own allow/deny ids
(`docs/cli/plugins/uninstall-and-update.md:32` [f6823e926220]), so compare every other id's
entry. It should not touch the `whatsapp` deny, but compare `plugins.deny` after R3.
The stock channel must also be seen working: the probe shows the account linked and
connected as in `channels-status.json`, and `openclaw logs --follow` shows it reconnect with
no repeated disconnects. TO-CONFIRM: that the linked device survives the outage without a
relink (expected for a window of hours). Relink only if the probe says not linked, the log
shows a logged-out or unlinked state, the device was removed on the phone, or a reconnect
loop persists: `openclaw channels login --channel whatsapp` (add `--account <id>` for a
named account), run in a terminal on the gateway host; it is QR-only and the owner scans it
there from the phone's Linked devices screen, since a QR sent elsewhere can expire
(`docs/channels/whatsapp.md:54-65`; `docs/cli/channels.md:197-212`). Never run `openclaw
channels logout`: it clears the WhatsApp auth state for the account
(`docs/channels/whatsapp.md:549`) and forces a relink.

Last resort, whole-file restore, never part of the window's rollback (R4c restores one leaf
instead): `openclaw backup restore "$SNAP/<archive>.tar.gz" --target "$SNAP/restored"` (fresh
directory, never in place), then with the gateway stopped copy the restored config file over
the path in `config-path.txt`, run `openclaw config validate`, start. That brings back the
pre-window config whole, every recorded sender list and group policy included, so after the
WhatsApp outage write R5b's owner-only cut again before the start and run the restore order
and its watch. On the pinned host `backup restore` accepted an `--only-config` archive
(harness stock modes); TO-CONFIRM on the owner's build. If it refuses there, a deleted secret
cannot be recovered from the archive: set a new token or password.

## 5. Live smoke test (the stock-transport form; G3 is met, the Cloud API smoke is 7.5 and is gated by the section 7 approval; owner sends, agent never sends)

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
- Two replies to one message, or any reply in the stock plugin's style (the stock plugin
  loaded: its entry not disabled, or the 3.7 auto-enable check not clean).
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

Run every block in bash, in one shell kept open from 7.2 to 7.6 (`SMOKE_START`,
`ROLLBACK_START` and the other variables live in it).

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
# a list holding only OWNER_TEST_NUMBER
openclaw config get channels.whatsapp.allowFrom --json
# not found, or a list holding only OWNER_TEST_NUMBER
openclaw config get channels.whatsapp.accounts.default.allowFrom --json
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

Number rule. `<BOT_NUMBER>` must be a new number dedicated to the Cloud API. It is never
the number the stock channel is linked to, which is the owner's personal number (WO-001
Status: "linked by QR from the human's own phone"; `config/openclaw.idx.json5:102-103`: "no
dedicated number yet"), and never the brokerage line (`docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md`,
phone-number row). Registering a number on the Cloud API requires deleting its WhatsApp app
account first, which ends that account and its linked devices (Meta, business phone numbers
and number migration docs), so the stock channel could not come back as it is. The owner
checks this before the approval; sending from the personal phone to `<BOT_NUMBER>` is fine.

Preconditions: G1, G2, G4 and G5 of section 1; G3 is now the WO-039 wiring merged on
`main`; section 3 completed (3.1 to 3.7, with 3.7 passing); eligibility questions Q2
(brokerage), Q4 (MLS and IDX display) and Q6 (hosted-model data handling) answered in
`docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md` (all three are pending); the separate written
approval above. The other open owner items of WO-038 (the eligibility questions Q1, Q3, Q5
and Q7, the opt-in text and record, the escalation route and the privacy policy) the owner
may waive in writing for an owner-only smoke test, in which only the owner's number is on
the allowlist; none of them is waived today. Then: section 2 backup taken, plus
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
# owner only, no ACL lines
ls -led "$HOME/idx-owner-secrets" "$HOME/idx-owner-secrets/cloud-api.json"
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
# expect listener-started, there must be no cloud-api-refused line
openclaw logs --follow
openclaw channels status --channel whatsapp --probe
# 404: only the webhook path is served
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:<OWNER_PORT>/"
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

How this was verified (2026-11-08): neither tunnel binary was installed on the agent's
side and none was run. The rules and expected outputs below come from reading each
product's source at its latest release tag and its official docs, then an independent
adversarial re-read of the same sources that corrected several details. The owner's offline
checks below are the confirmation on the owner's own build; any output that differs means
stop and report.

Owner-supplied evidence, 2026-11-10 (offline, formats only; not a live validation and not
an approval). The owner installed `cloudflared` with Homebrew on the gateway host: version
2026.10.7 (built 2026-10-30T16:43:29Z), the pinned version. Against a placeholder-only
config of the template shape below (host `offline-check.example.invalid`, segment
`TESTSEGMENT`, an all-zero tunnel UUID, a credentials path that does not exist, service
`http://127.0.0.1:18789`): `ingress validate` printed `Validating rules from  <path>` (two
spaces), `OK`, `exit=0`, with no "unused keys" warning; `ingress rule` for the webhook URL
printed `Using rules from <path>`, `Matched rule #0` and the hostname, path
`^/TESTSEGMENT/whatsapp$` and service lines, so the rule index is 0-based on this build.
All eight negative variants listed below (`/`, `<path>/`, `<path>x`, `<path>/extra`,
`/prefix<path>`, `/a/..<path>`, `<path>%0A`, `<other host><path>`) printed `Matched rule #1`
and `service: http_status:404`; the three URLs expected to match (`/<seg>/whatsap%70`,
`/<seg>%2Fwhatsapp`, `<path>?hub.mode=subscribe&hub.challenge=1`) printed `Matched rule #0`
and the listener service (the two encoded ones by design; the listener answers them 404,
CW-11). The 7.3 offline checks on the owner's build therefore match this runbook exactly.
Still open: the same checks against the real config, which exists only after the tunnel is
created (a live step under the section 7 approval).

**Chosen: Cloudflare Tunnel, named and locally managed (`cloudflared` 2026.10.7).** Owner
decision, 2026-11-10 (WO-041): "Tunnel choice: Cloudflare named tunnel."
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
`<TUNNEL_UUID>` and `<CREDENTIALS_FILE_PATH>` come from the setup block below.
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

Owner-run setup, live (it creates a tunnel and a DNS record in the owner's Cloudflare
account, so it runs only under the section 7 approval), in this order. Every command and
expected output is taken from the `cloudflared` 2026.10.7 source or Cloudflare's docs
(cited per step) and is TO-CONFIRM on the owner's build. The agent runs none of it.

Two secrets come out of it. The origin certificate `cert.pem` lets its holder create,
delete and manage every tunnel of the account; the tunnel credentials JSON lets its holder
run this one tunnel (Cloudflare docs, "Tunnel permissions", developers.cloudflare.com
cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/tunnel-permissions/).
Neither ever goes into the repo, a commit, chat or a ticket, and neither may sit under the
repo or under `~/.openclaw`. Keep the tunnel's credentials in a directory of their own,
not in the Cloud API secrets directory of 7.1: that directory is checked owner-only by the
gateway, holds the gateway's dedupe store, is listed and removed by 7.6 step 5, and the
two secrets have different owners (Meta, Cloudflare) and lifetimes, so sharing it makes the
removal and the permission checks less clear.

1. Log in (browser flow). In the browser, authorize the zone that holds `<PUBLIC_HOST>`
   (the domain it sits under). The certificate records that one zone, and `route dns`
   (step 3) writes its record into the certificate's zone whatever host name it is given
   (cloudflared 2026.10.7 `credentials/origin_cert.go` L23, `credentials/credentials.go`
   L51-55, `cfapi/hostname.go` L178-180; TO-CONFIRM on the owner's account). `login`
   always writes `~/.cloudflared/cert.pem` (it ignores
   `--origincert`), creating `~/.cloudflared` at mode 700 and the file at mode 600, and
   refuses to overwrite a non-empty one (`https://github.com/cloudflare/cloudflared/blob/2026.10.7/cmd/cloudflared/tunnel/login.go`
   L68-71, L126, L130, L134-150):
   ```bash
   cloudflared tunnel login
   ls -led "$HOME/.cloudflared" "$HOME/.cloudflared/cert.pem"
   ```
   Expected: the login prints the text below, and the listing shows owner-only modes and
   no ACL lines.
   ```text
   You have successfully logged in.
   If you wish to copy your credentials to a server, they have been saved to:
   <HOME>/.cloudflared/cert.pem
   ```
2. Create the tunnel, writing its credentials into their own owner-only directory.
   `--credentials-file` (alias `--cred-file`) sets the path; without it the JSON lands
   next to `cert.pem` as `<UUID>.json`. It is written at mode 400 and the command refuses
   an existing file (`cmd/cloudflared/tunnel/subcommands.go` L115-120, L254-262, L299-311;
   `subcommand_context.go` L165-173, L193-198):
   ```bash
   umask 077
   mkdir -p "$HOME/idx-tunnel-secrets" && chmod 700 "$HOME/idx-tunnel-secrets"
   cloudflared tunnel create --credentials-file "$HOME/idx-tunnel-secrets/<TUNNEL_NAME>.json" <TUNNEL_NAME>
   ls -led "$HOME/idx-tunnel-secrets" "$HOME/idx-tunnel-secrets/<TUNNEL_NAME>.json"
   ```
   Expected: the create prints the text below; the listing shows a `-r--------` file in an
   owner-only directory, with no ACL lines.
   ```text
   Tunnel credentials written to <CREDENTIALS_FILE_PATH>. Keep this file secret. To revoke these credentials, delete the tunnel.

   Created tunnel <TUNNEL_NAME> with id <TUNNEL_UUID>
   ```
   The printed id is the config's `tunnel:` value and the file is its `credentials-file:`
   (`config/configuration.go` L260; Cloudflare docs, "Create a locally
   managed tunnel", section 4).
3. Route the public host name to it (creates one CNAME to `<TUNNEL_UUID>.cfargotunnel.com`;
   without `--overwrite-dns` an existing record is an error, so do not add that flag)
   (`subcommands.go` L928-934, L1012-1016, L1052; `cfapi/hostname.go` L80-91):
   ```bash
   cloudflared tunnel route dns <TUNNEL_NAME> <PUBLIC_HOST>
   ```
   Expected (after a time stamp):
   ```text
   INF Added CNAME <PUBLIC_HOST> which will route to this tunnel tunnelID=<TUNNEL_UUID>
   ```
   (`<PUBLIC_HOST> is already configured to route to your tunnel` on a repeat.) The name
   printed after `Added CNAME` is the record Cloudflare actually made (`cfapi/hostname.go`
   L92-101): it must equal `<PUBLIC_HOST>` exactly. If it differs (for example
   `<PUBLIC_HOST>.<OTHER_ZONE>`, a login to the wrong zone), stop: delete that record in the
   dashboard by its printed name, log in again for the right zone, and repeat. Write the
   printed name down for 7.6. No command deletes the record; 7.6 does that in the
   dashboard.
4. Write `<CONFIG_PATH>` (mode 600) from the template above, then run the offline checks
   below against it.
5. Only after 7.2's listener is up: run the tunnel in the foreground (the config's
   `credentials-file` is used; `run` does not read `cert.pem` then, inferred from
   `subcommand_context.go` L56-66, L356-374):
   ```bash
   cloudflared tunnel --config <CONFIG_PATH> run <TUNNEL_NAME>
   ```
   Expected (each after a time stamp):
   ```text
   INF Starting tunnel tunnelID=<TUNNEL_UUID>
   INF Registered tunnel connection connIndex=0 connection=<ID> event=0 ip=<IP> location=<LOC> protocol=<quic|http2>
   ```
   (`subcommand_context.go` L279; `connection/observer.go` L56-64; usually one
   `Registered` line per connection, four by default, inferred.) Then the outside checks
   at the end of this section.

Owner offline checks (they parse the config file only; always pass `--config`; quote every
URL):
```bash
cloudflared --version
cloudflared tunnel --config <CONFIG_PATH> ingress validate; echo "exit=$?"
cloudflared tunnel --config <CONFIG_PATH> ingress rule 'https://<PUBLIC_HOST><WEBHOOK_PATH>'
```
Expected: the version `2026.10.7`; then the validate output below (any "unused keys"
warning instead of `OK` is a failure: fix the key); then the rule output below.
```text
Validating rules from  <CONFIG_PATH>
OK
exit=0
```
```text
Using rules from <CONFIG_PATH>
Matched rule #0
<TAB>hostname: <PUBLIC_HOST>
<TAB>path: ^/<RANDOM_SEGMENT>/whatsapp$
<TAB>service: http://127.0.0.1:<OWNER_PORT>
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

**Documented alternative, not chosen: Tailscale Funnel (`tailscale` 1.104.5).** It is weaker here: a `--set-path`
mount forwards the whole subtree under `<WEBHOOK_PATH>` (the listener 404s it, CW-11),
strips the mount from the path (so the target must repeat it), copies the client's `Host`
header unchecked, and by default uploads a log line naming the full target path. Required
first: run `tailscaled` with `--no-logs-no-support` (not available in the macOS App Store
or Standalone app). Then, with nothing else served on port 443 (`tailscale funnel status
--json` prints `{}`, or no `<PUBLIC_HOST>:443`, no `"443"` under `TCP` and no `Foreground`):
```bash
sudo tailscale funnel --bg --https=443 --set-path=<WEBHOOK_PATH> http://127.0.0.1:<OWNER_PORT><WEBHOOK_PATH>
# exactly one Handlers key, WEBHOOK_PATH, proxying to the same path
tailscale funnel status --json
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

Read-only check first: the app's App Mode (Development or Live) in the Meta app dashboard.
Meta warns that some webhooks are not sent while an app is in Development mode, so a smoke
test that sees no `webhook-accepted` with `delivered: 1` may be that. Switching the app to
Live is itself a live step under the section 7 approval; record which mode the test ran in.

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

Record the start time in the terminal where the checks will run, after every probe of
7.2, 7.3 and 7.4 has finished (each of them logs plugin lines the counts below would see)
and at least one second before M1 (the check compares whole seconds):
```bash
SMOKE_START="$(date +%Y-%m-%dT%H:%M:%S)"
```
During the test send nothing into the WhatsApp session from the dashboard, the CLI or any
other source: only the five messages from `<OWNER_TEST_NUMBER>` (owner decision,
2026-11-10, WO-041; see 3.6). Do not send `/new` or `/reset` either: it would be a sixth
inbound message. TO-CONFIRM: the channel id is still `whatsapp`, so with `per-channel-peer`
M1 may continue an existing session of the owner's number from the stock channel rather
than start a fresh one. A gateway restart during the test voids the run: roll back
or let it settle, then record `SMOKE_START` again and repeat M1 to M5.
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
other than Meta is posting: stop the tunnel first). A gateway restart during the test
voids the run (above), and the log counts cannot be trusted across it; the dedupe store
still keeps every message recorded before the restart, so a Meta retry of one of them is
counted `ignored` and starts nothing (proven on the pinned host, harness mode
`cloud-api-restart`, check E). A second reply to one message is still the two-replies
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
# run the confirmation block below once now it must say NOT CONFIRMED twice, then:
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
2. Stop the tunnel and remove its route to `<OWNER_PORT>`. Cloudflare: stop `cloudflared`
   (run in the foreground as in 7.3 step 5: Ctrl-C in its terminal; if it was installed as
   a launchd service with `cloudflared service install`: `cloudflared service uninstall`,
   with `sudo` if it was installed with `sudo`, which unloads and removes its
   `com.cloudflare.cloudflared` plist (cloudflared 2026.10.7
   `cmd/cloudflared/macos_service.go` L47-48, L114-120, L236-257); if it runs under
   Homebrew services: `brew services stop cloudflared`; each TO-CONFIRM on the owner's
   build; then `pgrep -fl cloudflared` prints nothing),
   then `cloudflared tunnel delete -f <TUNNEL_NAME>` (the flag before the name), delete the
   DNS record by the exact name 7.3 step 3 printed after `Added CNAME` (normally
   `<PUBLIC_HOST>`) in the Cloudflare dashboard by hand (`route dns` only creates
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
   # then each leftover the listing showed, by name
   rm "$HOME/idx-owner-secrets/cloud-api.json"
   # 32-hex-character markers, and after an early eviction an .evicted/ directory of empty 13-digit-named files
   ls -la "$HOME/idx-owner-secrets/cloud-api-dedupe.v1"
   rm -r "$HOME/idx-owner-secrets/cloud-api-dedupe.v1"
   # fails if anything is left: list again
   rmdir "$HOME/idx-owner-secrets"
   ```
6. Restore the rest of the config from the section 2 snapshot (section 4, full rollback).
   `plugins.entries.idx-whatsapp-channel` cannot match `$SNAP/plugin-entry.json` after
   section 4 R3 (which also deletes `channels.whatsapp`; R5b restores it) (the uninstall drops the entry or leaves `enabled: false`): check instead
   that it holds no `config.cloudApi` block and that `plugins inspect idx-whatsapp-channel`
   says disabled or not found.
Verify: no `listener-started` after the restart; `curl` to `127.0.0.1:<OWNER_PORT>` is
refused; `https://<PUBLIC_HOST><WEBHOOK_PATH>` no longer answers.

Merged form, TO-CONFIRM (not harness-proven): steps 4 and 6 each stop and start the
gateway, and section 4 does it again. After the fast rollback is confirmed and steps 1 to 3
are done, one cycle can do it all: `openclaw gateway stop`, `openclaw config unset
plugins.entries.idx-whatsapp-channel.config.cloudApi`, section 4 R1 to R6 (R3's uninstall
removes the plugin entry with its block), `openclaw config validate`, `openclaw gateway
start`, then the section 4 restore order (the owner-only watch for 10 to 15 minutes, then
the recorded `allowFrom` lists and the restart), then step 5 and the section 4 verify. The
tested order above stays the default.
