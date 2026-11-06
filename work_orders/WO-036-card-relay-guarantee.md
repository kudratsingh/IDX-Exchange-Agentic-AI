# WO-036 — Card relay guarantee (Layer 3 proposal)

**Driver:** owner (decided on 2026-11-06 to move this work order into key-free
implementation, and approves each install and activation step); agent (writes the
offline prototype, tests and evidence)
**Depends on:** #169 (Layer 1, the relay check; merged as `4ec99bd`), #172 (Layer 2, one
copy of the card; merged), ADR-0012 (deterministic card relay and the gateway privilege
boundary), ADR-0015 (code-controlled card delivery, proposed). It no longer depends on
the Phase 2 chart trial (owner decisions, 2026-11-06, below).
**Estimated effort:** the proposal and the offline prototype (one PR); install and
activation are separate operator steps, not sized here
**Autonomy level this moves toward:** L1 (every card the human reads carries the tool's
own numbers, closing the L1 card-relay defect); mechanism (c) would also be the first L2
infrastructure.

## Objective
A card that a card tool renders reaches the user with the tool's numbers unchanged,
because code puts it there, not because the model was asked to copy it. This work order
names three mechanisms, the rule that picks one, and what each would need. It builds
nothing.

## Why
On 2026-11-05 Phase 1 turn P1-4 failed (trace `8e84ac5c94834523`, `EVIDENCE_LOG.md`):
the model retyped card 2 and changed its living area, then corrected itself in the same
reply. The policy already forbids changing a card, and OpenClaw 2026.9.5 has no
supported way to pass a tool's text to the chat unchanged, so the model types every card
it shows.

## Inputs
- The problem record: `docs/EVIDENCE_LOG.md` (the 2026-11-05 Phase 1 session entry) and
  `docs/ACTIVATION_HANDOFF.md` procedure 1 (the reworded P1-4 and the relay check after
  each card turn).
- **Layer 1, detection (#169, merged):** `src/idx_agent/channels/relay_check.py` and
  `scripts/check_relay.py`. A reply passes only if it is the card message itself, or
  holds it whole and adds no digits. A changed number fails the turn even if the reply
  corrects itself. It detects; it does not prevent, and the user has already seen the
  wrong number when it fails.
- **Layer 2, one copy (next PR, key-free):** send the model one copy of the card, with
  integral numbers as integers, and make the card the whole reply. It is added as a
  fourth reply shape in the relay cases so the measurement runs score it. It lowers the
  chance of a retype; it cannot rule one out.
- The relay measurement (owner decision, 2026-11-05): five runs of the seven relay and
  description cases, at most 140 chat calls, one token, reporting the error rate per
  reply shape as counts only. It measures Layers 1 and 2; it is not part of the rule
  below.
- `docs/adrs/0012-deterministic-card-relay.md` and `extensions/idx-card-relay/`: the
  2026-10-26 hook review, the uninstalled two-hook spike, its failed browser gate, and
  the human's superseding decision to cancel the relay and decline installation.
- `docs/CHART_DELIVERY.md` (WO-030): how a server-written PNG reaches WhatsApp through a
  `MEDIA:` line in the reply, with evidence E1 to E16.
- The installed OpenClaw 2026.9.5 (`~/.npm-global/lib/node_modules/openclaw`) and its
  WhatsApp plugin (`@openclaw/whatsapp` 2026.9.5), read only, for the check in
  "Mechanism (b)" below.

## In scope
1. The three mechanisms, each with what it guarantees, what it depends on and what it
   would take to build.
2. The decision rule, as the owner first gave it, and the owner's decisions of
   2026-11-06 that replace it.
3. One focused, read-only check of the OpenClaw 2026.9.5 plugin API for mechanism (b),
   with file:line citations. Nothing was changed, installed or run.
4. From 2026-11-06: the recommended architecture and an offline, key-free prototype
   with regression tests (see "Recommended architecture"), default off.

## Out of scope
- Installing, enabling or activating any mechanism; the prototype is never installed.
- Any OpenClaw config, plugin, hook, `.env` or gateway change, or a restart.
- Paid calls, live turns, and the relay measurement itself.
- Changing Layer 1 or Layer 2, the skills, the tool descriptions or the routing pins.
- The email draft preview. Its approval is bound to the stored draft by code
  (ADR-0012, superseding decision); it is not a card relay.
- Copying OpenClaw source into the repository. The check below cites file and line only.

## The three mechanisms

### (a) Server-rendered card image
Our code draws the card as a PNG and attaches it to the reply. The card's text carries
no digits, so the model has no number to retype.
- **Path.** The WO-030 chart path, reused: the server writes the PNG into the
  `idx-charts` directory inside the agent workspace and the reply names it with a
  standalone `MEDIA:` line (`docs/CHART_DELIVERY.md` §3, E8, E9, E15). No new tool, no
  `message` tool, no public URL and no OpenClaw config change.
- **Guarantee.** The numbers the user reads are pixels our code drew. The model relays a
  file token and digit-free text. Layer 1 then checks that the reply adds no digits and
  carries the token.
- **Depended on** image relay proving intact in the Phase 2 chart trial
  (`docs/ACTIVATION_HANDOFF.md`, procedure 5b, step 5). The owner's decisions of
  2026-11-06 supersede waiting for that trial; (a) is not chosen (see "Recommended
  architecture" below: an image is not selectable or readable aloud, and it rides the
  model-relayed `MEDIA:` line).
- **Questions to settle in its build work order.** One image per card or one per reply
  (E6 sends identical sources once). Whether the dashboard shows reply media; it is
  not established here. What the model still receives so it can answer "the second
  one" without seeing numbers it might type. Accessibility: numbers in an image cannot
  be read aloud or copied. Card images hold listing data, so they need the chart files'
  owner-only mode and prune job (WO-030, D6).
- **Size.** About one PR: a card renderer, the digit-free text, a skill rule and offline
  tests. Its activation follows the chart trial's procedure.

### (b) Gateway hook
Code inside the OpenClaw gateway replaces the model's reply text with the original card
before the reply reaches the channel. The check below records what OpenClaw 2026.9.5
provides for this; nothing was changed.

#### The check (2026-11-05, read only)
Installed package: `openclaw` 2026.9.5 (`package.json`), and `@openclaw/whatsapp`
2026.9.5 under `~/.openclaw/npm/projects/openclaw-whatsapp-290d7f7427/`. Paths below are
relative to the `openclaw` package unless they say "plugin". The first 12 hex digits of
each file's sha256 are given so the citation can be checked against the same build.

| File | sha256 (first 12) |
|---|---|
| `docs/plugins/hooks.md` | `5eeeef6ddac4` |
| `docs/plugins/hooks/messages.md` | `7c2f8aee1970` |
| `docs/plugins/hooks/reference.md` | `e442a3a833f0` |
| `docs/concepts/streaming.md` | `53023648a373` |
| `dist/api-DArLOVCi.d.ts` (hook types) | `7decea02a45e` |
| `dist/hooks-Jjh3afyP.mjs` (hook runner) | `94e01df2379f` |
| `dist/deliver-prepare-BRk062mg.mjs` | `03f60ee0178f` |
| `dist/dispatch-BeNOmkLV.mjs` | `78ac59c89fc9` |
| `dist/lifecycle-BL9jY9Cb.mjs` (channel turns) | `e2a7991dd326` |
| `dist/server-chat-Bchd-0vr.mjs` (dashboard live events) | `5f032399b002` |
| `dist/chat-send-handler-BBsH-uIk.mjs` (dashboard chat) | `a363309dfead` |
| `dist/reply-pipeline-CP9cBMci.mjs` | `8be817592adc` |
| `dist/builtin-openclaw-C7-lQJ2Z.mjs` (tool end) | `97435362096a` |
| plugin `dist/.setup/monitor-BblvzLpX.mjs` (WhatsApp) | `6a6ca5dcd340` |

Every hook that sees or changes a reply:

| Seam | Where | Replace the text? | Sees the tool result? | Notes |
|---|---|---|---|---|
| `reply_payload_sending` | `docs/plugins/hooks/messages.md:68-70, 116-119`; types `dist/api-DArLOVCi.d.ts:6005-6023`; run at `dist/deliver-prepare-BRk062mg.mjs:26-39`, built into delivery at `:113-142` | **Yes.** It returns a whole new payload, text included, or `cancel` | **No.** The event has `payload`, `kind`, `channel`, `sessionKey`, `runId` and `usageState` only | Runs after normalization and before channel delivery. On a thrown error or a 15-second timeout the handler is logged and skipped (`docs/plugins/hooks/reference.md:94`; `dist/hooks-Jjh3afyP.mjs:389`), so it fails open: the model's text goes out |
| `message_sending` | `messages.md:67, 112-115`; types `api-DArLOVCi.d.ts:5398-5410`; run at `deliver-prepare-BRk062mg.mjs:144-210` | **Yes**, as a `content` string, or `cancel` | **No.** `to`, `content`, reply and thread ids, metadata | Same fail-open policy (`reference.md:94`) |
| `after_tool_call` | `reference.md:149`; types `api-DArLOVCi.d.ts:6084-6092`, handler returns `void` at `:6488`; emitted at `dist/builtin-openclaw-C7-lQJ2Z.mjs:3583-3603` | **No**, observe only | **Yes**: `result` (the sanitized result), `runId`, `toolCallId` | Fired and not awaited (`.catch` at `:3602`). Observe handlers run concurrently (`reference.md:27`), so ordering against the sending hook is not a documented guarantee |
| `agent_end` | `reference.md:133`; types `api-DArLOVCi.d.ts:5797-5803`, `void` at `:6475` | **No**, observe only | Final messages, after the reply | Needs `allowConversationAccess` for a non-bundled plugin (`docs/plugins/hooks.md:125-130`) |
| `before_agent_finalize` | `reference.md:132`; result type `api-DArLOVCi.d.ts:5817-5830` | **No.** It can only `continue`, `revise` (ask for another model pass) or `finalize` | No | A revise is another paid model call and still lets the model type the card |
| `before_agent_reply`, `before_dispatch` | `reference.md:131, 164`; `messages.md:15-18` | Claim the turn before the model runs | No; no tool has run yet | Not a seam after a card tool call |
| `llm_output` | `reference.md:142` | **No**, observe only | No | |
| `tool_result_persist`, `before_message_write` | `reference.md:151-152`; types `api-DArLOVCi.d.ts:6099-6116` | Rewrites the transcript, not the delivery | `tool_result_persist` sees the tool message | A session write; ADR-0012 forbids it for the relay |
| `reply_dispatch` | `messages.md:20-23`; `reference.md:165` | Takes over the whole reply: model execution, replay and delivery | Through its own run | A runtime takeover. ADR-0012 ruled it broader than a card relay; it is mechanism (c)'s scale, inside the gateway |
| Channel `messaging.transformReplyPayload` | `dist/reply-pipeline-CP9cBMci.mjs:24-34` | Yes, for the channel plugin's own replies | No | Owned by the channel plugin itself, not by a third-party hook. Relevant to (c) |

**WhatsApp.** Channel turns go through `src/channels/turn/lifecycle.ts`
(`dist/lifecycle-BL9jY9Cb.mjs:81, 336`), whose dispatcher installs the
`reply_payload_sending` stage before delivery (`dist/dispatch-BeNOmkLV.mjs:571-572`).
WhatsApp has no preview stream (the channel table at `docs/concepts/streaming.md:205-211`
lists Telegram, Discord, Slack, Mattermost and MS Teams, not WhatsApp). Block streaming is off by default
(`streaming.md:55`); if it were on, each block would reach the hook on its own
(plugin `monitor-BblvzLpX.mjs:3043, 3355`). So on WhatsApp the final text **can be
replaced** before delivery, but only by joining two hooks on `runId`: `after_tool_call`
to capture the card and `reply_payload_sending` to substitute it. No single supported
callback has both the tool result and the outgoing text. This is what the 2026-10-26
spike did with stubbed transport (ADR-0012, "Authorized two-hook spike").

**Dashboard (Control UI).** Live text is not covered. The dashboard's event handler
forwards the model's assistant stream to `emitChatDelta`
(`dist/server-chat-Bchd-0vr.mjs:1029-1031`), which broadcasts it to the browser
(`:520-560`). That file has no reference to the hook runner, `reply_payload_sending` or
`message_sending` (a search for those names finds no match). Its terminal frame is built
from the buffered model text (`:662-690`). The dashboard's chat handler also broadcasts
a settled final from the dispatcher's delivered payloads
(`dist/chat-send-handler-BBsH-uIk.mjs:2374-2556`), and that dispatcher does carry the
sending hook (`dispatch-BeNOmkLV.mjs:631-665`, called at `chat-send-handler:3235`). So a
hook could change the settled final, but the browser has already shown the model's
digits while the reply streamed. Which of the two finals the browser keeps was not
established by this reading. The transcript keeps the model's original text
(`messages.md:32-36`). The ADR-0012 host probe observed the same thing on 2026-10-26:
the browser broadcast a synthetic rewrite with zero calls to the sending hook. P1-4 ran
on the dashboard.

**Install and permission.** A native plugin runs inside the gateway process with its
privileges (`hooks.md:79-80`). It needs `openclaw plugins install --link <dir> --force`,
`openclaw plugins enable <id>` and a `plugins.entries.<id>` entry in `openclaw.json`
(`hooks.md:83-99`), then a reload. `after_tool_call` and `reply_payload_sending` are not
on the `allowConversationAccess` list (`hooks.md:125-130`); `agent_end` is.
`plugins.allow` and `plugins.deny` still apply (`hooks.md:119-122`). Every one of these
steps is an install and config change for the owner to approve. None was taken.

**Answer for the decision rule.** A hook that can replace the reply text after a card
tool call exists for WhatsApp's final delivery, as a two-hook join that fails open. No
hook covers the dashboard's streamed text. The owner decides whether that counts as "a
hook exists" (see Stop conditions and the owner questions in Status).

- **Size, if chosen.** The spike in `extensions/idx-card-relay/` is a starting point:
  an install manifest, fail-closed handling, lifecycle and capacity limits, a host probe
  for WhatsApp, and a decision on the dashboard. It is the project's first TypeScript
  runtime component inside the gateway (ADR-0012, "Required boundary").

### (c) Own output path
Our own channel adapter sits between the model and WhatsApp. After the model's turn,
code inserts the card text into the reply, so the model never types a card.
- **Shape.** The model writes prose plus a card reference. The adapter replaces each
  reference with the exact card message our server rendered for that turn (keyed by
  the trace id the server already issues), refuses a reply whose references are missing
  or foreign, and sends the result to WhatsApp. How the adapter connects (its own
  WhatsApp channel plugin using the channel-owned reply transform, a `reply_dispatch`
  takeover, or a service outside the gateway) is the first question of its build work
  order.
- **Guarantee.** Byte-identical cards on WhatsApp by construction, with no dependence on
  OpenClaw's hook order or failure policy.
- **L2 infrastructure.** Owning the output path gives the system its own place to hold
  per-conversation state, confirmations and deadlines, which L2 needs
  (`docs/AUTONOMY_LADDER.md`). It would be the first L2 infrastructure.
- **Costs.** The largest of the three: a new runtime component on the message path,
  its own security review, a rollback rehearsal and a fresh live acceptance. The
  dashboard stays OpenClaw's and would keep detection only (Layer 1), unless the owner
  decides otherwise.

## Decision rule
Superseded on 2026-11-06. The rule as first given was: decided after the chart trial,
by the owner, in this order: images intact → (a); a hook exists → (b); neither → (c).
The owner replaced it with these decisions (2026-11-06, quoted exactly):

> - Leave the checkout and .env unchanged. Phase 1 remains unaccepted; no further live turns.
> - Move WO-036 into key-free implementation. Prioritize deterministic text delivery on WhatsApp.
> - A hook qualifies only if failures withhold the reply. The documented fail-open hooks alone don’t qualify.
> - Dashboard card output must also be protected before it’s used for acceptance or buyers. If its stream cannot be protected initially, refuse card turns there. WhatsApp-first is acceptable with that restriction enforced.
> - These decisions supersede waiting for the Phase 2 chart trial. Return the design, offline prototype and regression tests in a PR. No install, activation, gateway changes or paid calls.

Their authorization, also 2026-11-06 (quoted exactly): "Prioritize WO-036 before
further acceptance. Authorize key-free investigation and an offline prototype for
code-controlled text delivery, so cards remain selectable and accessible. Find the
smallest path that inserts the trusted tool message before users see it and withholds
the response if delivery cannot be verified. Explicitly address WhatsApp delivery and
dashboard streaming. A hook that fails open cannot provide the guarantee. Don't make
this depend on completing Phase 2 first. Add synthetic regressions for both observed
failures—changed square footage and a year copied from another card—and missing, stale
or cross-session results. Return the recommended architecture, limitations and a
reviewable PR. No installation, activation, gateway changes or paid calls."

Until the prototype is accepted, installed and activated by separate owner steps,
Layers 1 and 2 are the only protection in use, and Layer 1 fails any turn with a
changed number.

## Recommended architecture: the token relay (offline prototype, 2026-11-06)
ADR-0015 (proposed) records the decision and the exceptions to ADR-0012. In short: the
model never receives card values, a fail-closed hook supplies the binding that lets
the server issue a card, and only code puts the stored card text into a WhatsApp
reply. The cards arrive as real text (selectable, read aloud by screen readers).

### How it works
1. **Binding (fail-closed hook).** A gateway extension registers `before_tool_call`.
   OpenClaw's global hook runner marks that hook fail-closed
   (`dist/hook-runner-global-CN2-D2Rq.mjs:95-99`, sha256 `8a9a236d7874`), and a throw
   or timeout blocks the tool call (`dist/agent-tools.before-tool-call-ya9NNSXc.mjs:3052-3062`,
   `39e6ae403ad4`). Bundled MCP tools are wrapped with this hook
   (`dist/builtin-openclaw-C7-lQJ2Z.mjs:1832`, `97435362096a`), and the adjusted
   input reaches `runtime.callTool` unchanged (`dist/agent-bundle-mcp-materialize-Bf4ktXvL.mjs:322`,
   `2dddc7447d86`). For the four idx card tools only, the hook writes one argument,
   `idx_delivery`, through the host's shallow merge (call site
   `agent-tools.before-tool-call:3030-3035`, helper `:853-861`), so a value the model
   sent is replaced.
2. **Channel identification (critique fix).** In `before_tool_call`, `ctx.channelId`
   is the conversation target, not a channel name: `channelId: attempt.currentChannelId`
   (`builtin-openclaw:19690`), which is `originatingTo ?? OriginatingTo ?? To`
   (`dist/agent-runner.runtime-DRp6jmuv.mjs:1971`, `f3f4732fc5ee`); a dashboard
   `chat.send` uses the internal route with `originatingTo = sessionKey`
   (`dist/chat-origin-routing-IBVBZAzW.mjs:104-108`, `79501da5f78a`). So the hook binds
   `channel: "wa"` only when all hold: `ctx.agentId === "idx"`; `ctx.sessionKey` is
   `agent:idx:whatsapp:direct:<peer>` (dmScope `per-channel-peer`,
   `dist/session-key-CPlMYURm.mjs:394-396`, `39bd60e3065a`); `ctx.channelId` is
   non-empty and differs from the session key (a dashboard turn into the WhatsApp
   session has them equal); `ctx.requester.channel`, if the host ever sets it, is
   `whatsapp`; the run and tool-call ids are present and agree. Anything else binds
   `channel: "none"`. The binding holds `{v, channel, session: sha256 of the session
   key, run, call}`, never the peer, the session key or a phone number. `sender_id` is
   never used: the model supplies it.
3. **Server (behind `IDX_CARD_DELIVERY=1`, off unless exactly "1").** `_CardServer.call_tool`
   removes `idx_delivery` before any tool runs. No binding, a malformed one or
   `channel: "none"` returns the fixed refusal "Listing cards are sent on WhatsApp
   only for now." with no card, no token, no digit in its message and nothing stored.
   Otherwise the tool runs, its exact `message` is written durably (temp file, fsync,
   rename, directory fsync) to `~/.openclaw/idx-cards`, and only then does the token
   exist. A store or tool failure is a refusal. Off, a card call without an
   `idx_delivery` argument is byte-identical to main; a card call that carries one (any
   value: only the hook writes it) is refused with the store refusal and the tool does
   not run, so a loaded hook never meets a full card it would have to correlate (review
   of #176). The tool surface (schemas, descriptions, instructions) does not change
   either way.
4. **What the model sees.** The same AgentResult with `message` set to
   `[[Listing details not shown. Please ask again. idx-card:<20 letters>.<16 letters>]]`
   and `data` reduced to positions, random integer listing handles, the user's own
   filters and a note never to show handles. The existing rule "copy `message` exactly
   as the whole reply" makes the token the correct reply; no skill changes.
5. **Release (WhatsApp only).** `reply_payload_sending` acts only when `event.channel`
   (`deliveryContext.Surface ?? Provider`, `dist/deliver-prepare-BRk062mg.mjs:124`,
   `03f60ee0178f`) and the message context's `channelId` are both `whatsapp`. It reads
   the referenced records read-only and calls `verifyAndSubstitute`, the twin of
   `card_delivery.verify_and_substitute`. The stored bytes replace the tokens only
   when: every token is well formed and has a record; its tag recomputes; the stored
   digest matches the text; the record's session digest, run and channel match; it has
   not expired; no token repeats; the text around tokens is blank; and the tokens
   cover exactly the card calls the hook bound in this run. Otherwise the reply
   becomes "I couldn't send those listing details safely this time. Please ask again."
   (no digits), and later payloads of that run are cancelled. A throw inside the
   handler cancels the payload.

### WhatsApp behaviour
A DM final reply (block streaming is off by default) goes through the dispatcher's
`reply_payload_sending` stage before channel delivery (`deliver-prepare:113-142`), so
the stored card is what WhatsApp's own formatting and chunking then send: the same
deterministic code that sends server text today. When verification fails the user
gets the fixed line. When the release hook is skipped (15 s timeout, a throw the host
catches, the plugin not loaded) the model's raw text goes out, and on a card turn that
is a token with no digits; if the plugin never loaded, no binding existed and the
server refused, so no token exists either.

### Dashboard behaviour (card turns refused, in code)
The dashboard's live text is broadcast from the model's stream with no hook
(`dist/server-chat-Bchd-0vr.mjs:581, 1031`, `5f032399b002`), so it cannot be protected
in 2026.9.5. Card turns there are refused: a dashboard turn binds `none` (or no binding
at all if the plugin is absent), and the server refuses. The dashboard user sees the
model's relay of the refusal, and no card value at any point, because the model never
had one. Exception: a dashboard `chat.send` with `deliver: true` into a WhatsApp
session targets the chat itself, so it binds `wa`; then the dashboard shows the token
(letters only) while WhatsApp receives the card. The dashboard stays unusable for
acceptance or buyers until the host offers a fail-closed hook on its stream.

### Why it fails closed
Card values exist in two places only: the server's rendering and the owner-only
store, which code reads at one point, the WhatsApp release handler, and only after
every check passes.
1. `before_tool_call` throws or times out: the host blocks the tool; no card.
2. The plugin does not load: no binding; the server refuses; no token.
3. A binding is forged with the plugin absent: a token may be issued, but nothing
   releases it; the user sees a raw token with no digits.
4. The release hook is skipped: the model's text goes out; on a card turn it only ever
   held a token (switch on) or a refusal (switch off with the plugin loaded, item 7).
   Only with the plugin absent and the switch off does the model get the card, which
   is today's behaviour and carries no guarantee.
5. The release hook runs and a check fails: the fixed line, then cancels.
6. The store cannot be read safely (permissions, symlink, owner, size, shape): the
   record counts as missing; withheld.
7. The plugin is on but the server switch is off (critique fix, corrected in the
   review of #176): the server refuses every card call that carries the binding
   argument, so the model never holds a card value. The earlier design sent the full
   card and relied on the release hook's ledger to withhold the retyped reply; that
   failed open whenever the two hooks could not be correlated (a different run id or
   session key in the reply hook, no run id at the tool hook, so a `none` binding, or a
   gateway restart emptying the in-memory ledger).
8. Untraced paths (the message tool, block streaming if turned on, ACP finals) can
   carry only tokens: safe, but no card.
The remaining way to show a wrong number is the model inventing one with nothing to
copy. On card turns any text outside tokens is withheld; in replies without a card it
is not blocked (strict mode, below, is an owner decision).

### Critique fixes adopted (and those not)
- **Critical, store inside the workspace — adopted.** The store is
  `~/.openclaw/idx-cards`, beside the `workspace-idx` that the agent's `read` tool is
  limited to; files are named by a hash of the reference; a test pins the config's
  workspace and `fs.workspaceOnly: true` and refuses an `IDX_CARD_DIR` inside the
  workspace, also through a symlink.
- **Critical, wrong channel field — adopted** as in "Channel identification", with
  ctx-shape tests (WhatsApp DM, dashboard into the WhatsApp session, dmScope main,
  account-scoped keys, other channels, missing fields, mismatched run ids).
- **High, handles fail schema validation — adopted, option (b):** random integer
  handles (100000000 to 999999999), so `recommend.listing_key` and
  `draft_email.listing_keys` keep their integer schemas; `_CardServer` maps them back
  for both, refuses an unknown one, and position follow-ups are unchanged. A test runs
  the argument shapes through the tools' own JSON schemas. `draft_email`'s output
  stays model-relayed (out of scope).
- **High, silent revert on misconfiguration — adopted.** The hook keeps a per-run
  ledger of the tool-call ids it bound; the binding and record carry the tool-call id;
  every bound call must have a valid record and token, else withheld. The token is
  issued only after the durable write; a write error is a refusal.
- **Medium, broader claims than delivered — adopted.** The guarantee is scoped to the
  four card tools in runs that call them. Out of scope and model-relayed:
  `draft_email` previews, `bounded_analysis`, `rag_answer`, runs without a card tool.
  Activation needs a session reset (old transcripts hold full cards). Strict mode is
  concrete: an option in both functions that withholds any digit in a WhatsApp reply
  while the session has a bound card call in the plugin ledger (30 minutes); off.
- **Medium, multi-payload runs — adopted in part.** Released runs cancel repeated
  tokens and later commentary; a failed run sends the line once and cancels the rest.
  Not adopted: delivering one run's cards split across payloads. One payload must
  carry all of a run's cards, else withheld (simpler and fail-closed; vector
  `split_across_payloads`).
- **Medium, release code not run in CI — adopted.** The extension is plain ESM with
  JSDoc types; `tests/test_card_delivery_js.py` runs it on Node 18 or later.
- **Medium, correlation across hooks — adopted in part.** A payload without a run id
  is withheld while a card run is open; the stub tests use the field paths named in
  the critique; the pre-activation check is listed below. Not shown: the real host's
  values (no host run in this offline work).
- **Low, citations — adopted** (this section). **Low, accessibility — adopted:** an
  80-bit ref and 64-bit tag, with words first in the token. **Low, privacy and
  pruning — adopted in part:** only a digest and an enum enter the binding, and
  pruning removes only expired records while a full store refuses the write. Not
  adopted: a per-session cap and expiry tied to the ledger (a global cap of 64 and a
  300 s wall-clock TTL remain; owner decision).

### Limitations
- An invented figure in a reply without a card is not blocked unless strict mode is
  turned on. Layer 1 still detects offline.
- The dashboard gets no cards; its refusal wording is the model's relay.
- A skipped hook, an unloaded plugin, a store problem or a session/run mismatch
  between the two hooks costs the card: the user sees the fixed line, a refusal or a
  raw token. The guarantee is no wrong number, not delivery.
- One payload must carry all of a run's cards; commentary after a card call in the
  same run withholds the reply.
- Verified by reading the installed 2026.9.5 code and by stub tests, not by running
  the host. Unconfirmed, all failing closed (with the switch on the model holds only a
  token; with it off and the plugin loaded the server refuses, item 7): that
  `before_tool_call`'s `sandboxSessionKey` and run id equal the release hook's
  `SessionKey` and run id;
  that the host keeps passing an argument the schema does not declare (the server
  schemas have no `additionalProperties: false`; if a later OpenClaw strips it, every
  card is refused, which a test shows); that another plugin's `before_tool_call`
  params do not replace ours (`lastDefined` merge, `dist/hooks-Jjh3afyP.mjs:968-990`,
  `94e01df2379f`); and that OpenClaw's user-facing text filters keep the token.
- The text is still formatted after the hook (WhatsApp normalization and chunking);
  byte identity on the wire is not proven offline.
- The release hook reads only `~/.openclaw/idx-cards`. The server's `IDX_CARD_DIR`
  exists for tests; set to anything else, the server issues tokens the hook cannot
  find and every WhatsApp card turn is withheld (fails closed, no card).
- The tag has no secret: a process with the owner's uid that can write the store
  could plant a consistent record; that is outside the threat model.
- Handles and server search state live in memory; after a restart a handle is
  refused with "search again".
- The model cannot answer questions about card figures in free text ("which is
  cheaper?"); a code-rendered comparison would be a later work order.

### Owner decisions pending
1. Accept ADR-0015's exceptions to ADR-0012: `before_tool_call` used only to write the
   binding of the four card tools; read-only `node:fs` access to `~/.openclaw/idx-cards`;
   release on WhatsApp only, with the dashboard refused.
2. Accept that the model never sees card values (positions and handles only).
3. Strict mode: withhold digits in WhatsApp replies while the session had a card call
   in the last 30 minutes (shipped off).
4. The fixed texts: the failure line, the WhatsApp-only refusal, the store refusal,
   the handle refusal and the token's words.
5. Scope: the four card tools only; `draft_email` stays out (operator-gated).
6. Store TTL (300 s) and cap (64, refusing when full), and its place,
   `~/.openclaw/idx-cards`.
7. Before any activation (a separate operator action): a read-only host check that
   `before_tool_call` sees bundle-MCP card calls with the same session key and run id
   as `reply_payload_sending`, that the argument reaches the server, and a session
   reset for existing WhatsApp sessions.

## Files expected to change
The proposal: this file. The offline prototype (2026-11-06):
`src/idx_agent/channels/card_delivery.py` (pure core), `src/idx_agent/channels/card_store.py`
(store and handles), `src/idx_agent/mcp_server/server.py` (`_CardServer`, behind the
switch), `src/idx_agent/db/pool.py` and `.env.example` (the two settings, empty),
`extensions/idx-card-delivery/` (never installed; `extensions/idx-card-relay/` is kept
unchanged as the ADR-0012 record), `tests/card_delivery_vectors.py`,
`tests/fixtures/card_delivery_vectors.json`, `tests/test_card_delivery.py`,
`tests/test_card_store.py`, `tests/test_card_server_delivery.py`,
`tests/test_card_delivery_js.py`, `tests/test_db_pool.py` (the settings pin),
`docs/adrs/0015-code-controlled-card-delivery.md`, `docs/CONTRACTS.md` and
`docs/EVIDENCE_LOG.md` (one appended entry). No skill, tool description, server
instruction, routing pin, config, gate or CI file.

## Interfaces and contracts
- The card message a tool returns stays the source of truth (`docs/CONTRACTS.md`).
- Layer 1's verdicts (`pass`, `fail`, `unavailable`) stay the acceptance check for every
  mechanism.
- ADR-0012's required boundary applies to all three: only rendered card blocks are
  eligible, code inserts the original UTF-8 block, and a regression test shows that a
  model rewrite cannot change a card number.

## Implementation requirements
The prototype meets these; any later build must too:
1. Show, fail before and pass after, that a model reply with a changed card number
   cannot reach the user with that number.
2. Keep prose, document answers and clarifications the model's own.
3. Fail closed: a card that cannot be delivered exactly is withheld with a plain
   failure line, never shown changed.

## Safety requirements
- `docs/SAFETY_INVARIANTS.md`: no message leaves for anyone beyond the user's own chat;
  no new messaging tool; no session or transcript writes for the relay (ADR-0012).
- Gateway privilege: (b), and (c) if it lives in the gateway, run with the gateway's
  privileges. Code discipline is not a sandbox (ADR-0012).
- No listing text in tracked files; tests use synthetic cards only.

## Tests required
The docs gates, and for the prototype: the shared vectors in Python and in Node (changed
square footage, a year copied from another card, missing, stale, expired,
cross-session and forged results, digits or words outside tokens, duplicates, partial
tokens, unreferenced or unbound cards, the switch-off misconfiguration, multi-payload
runs, and the happy path byte for byte); the store's modes, symlink, owner, size, TTL,
cap and pruning; the server switch off (byte-identical without the binding argument,
refused with it) and on (refusals, store, projection, handles, schema shapes); both hooks with host-shaped stub contexts and
simulated hook failures.

## Acceptance criteria
- This file states the problem, all three mechanisms, the decision rules (first and
  superseding), the autonomy level, the hook check with file:line citations, the
  recommended architecture, its limitations and the owner decisions.
- The prototype shows fail before and pass after for a changed card number, is off by
  default with main's behaviour unchanged, and passes locally and in CI.
- Nothing is installed, enabled, activated or paid for.

## Verification commands
```bash
python3 scripts/gates/pii_scan.py work_orders/WO-036-card-relay-guarantee.md
python3 scripts/gates/confidential_text.py work_orders/WO-036-card-relay-guarantee.md
python3 scripts/gates/forbidden_paths.py work_orders/WO-036-card-relay-guarantee.md
MYSQL_HOST= python -m pytest -q tests/test_card_delivery.py tests/test_card_store.py \
  tests/test_card_server_delivery.py tests/test_card_delivery_js.py
node --test extensions/idx-card-delivery/delivery.test.mjs
```

## Deliverables
This work order, ADR-0015 (proposed), the offline prototype and its tests in one PR, and
one evidence entry. No install, activation, config, gateway change or paid call.

## Stop conditions
- Answered on 2026-11-06: build the offline prototype, WhatsApp-first, with dashboard
  card turns refused in code. Installing or activating it still needs the owner.
- Any mechanism would need a session write, a broader tool, a relaxed tool policy or a
  silent extra hook (ADR-0012): stop.
- A build would change OpenClaw config, install a plugin or restart the gateway without
  the owner's approval for that step: stop.
- A newer OpenClaw than 2026.9.5 is installed: the check above is void; redo it first.

## Status
offline prototype in review; not installed or activated; owner decisions pending —
2026-11-06 — Built from the owner's decisions of 2026-11-06 on branch
`wo-036-card-relay-prototype` (stacked on #171): the token relay described in
"Recommended architecture", ADR-0015 (proposed, not accepted), default off
(`IDX_CARD_DELIVERY` unset, main's behaviour byte-identical). Key-free and model-free:
no paid call, no install, activation, config, gateway, `.env` or `~/.openclaw` change.
Fail before, pass after: with the release step as on main, the changed-square-footage
regression fails (4 of 4); with the prototype it passes. 183 new Python tests and 68
Node tests pass; the full suite passes (5510 passed, 131 skipped). The critique's
critical, high and medium fixes are adopted, two of them in part, as listed above. Owner
decisions pending: the seven under "Owner decisions pending". The first proposal's
owner questions are answered by the 2026-11-06 decisions (the dashboard's stream must
be protected or its card turns refused; WhatsApp first is acceptable).

Earlier: proposal, not approved to build — 2026-11-05 — Layer 3 work order written from
the owner's decisions of 2026-11-05; the OpenClaw 2026.9.5 hook check for (b) done read
only.
