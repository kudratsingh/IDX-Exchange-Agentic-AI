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

**What it guarantees, and what it cannot (2026-11-06 revision).** Within OpenClaw
2026.9.5 the prototype guarantees that a reply is withheld only while its release
handler runs. The host's sending boundary is fail-open: when the handler is absent,
times out, or returns a shape the host does not accept, OpenClaw sends the model's
text unchanged, and some sends skip the hook entirely. That is an architectural
blocker to the owner's requirement that the delivery boundary prevent any fallback to
unverified model text (section "Architectural blocker"). Token redaction and prompt
instructions reduce that risk but cannot remove it. The recommended way to remove it,
pending the owner, is in "Delivery boundary: feasibility and recommendation". This
prototype is kept unmerged as defence in depth: `before_tool_call` remains a real
fail-closed binding; `reply_payload_sending` is best effort.

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
6. **Correlation (2026-11-06 revision: unknown correlation withholds).** The release
   side must know every run it releases for. `before_tool_call` registers the run (a
   session digest and run id, 30 minute TTL) on every tool call in a WhatsApp direct
   chat, not only card calls. A payload with no run id, with event and context run ids
   that disagree, with a run id never registered, registered for another session, or
   whose registration expired, is withheld with the fixed line whatever its text,
   plain replies with no token included (`correlation_problem` /
   `correlationProblem`). A registered run with no card call still passes its text
   unless strict mode is on (an owner decision; shipped off). Only `before_tool_call`
   registers runs: `before_agent_run` is also fail-closed and carries `ctx.runId`, but
   its run id and session key were not shown to equal those on `reply_payload_sending`
   (the last hop and the session-key equality were not traced), so it is not used; it
   runs before inference and could not protect the outbound boundary anyway. Cost:
   only agent `idx` WhatsApp direct chats are ever registered, while the release
   handler acts on every WhatsApp payload, so with the plugin loaded these replies are
   always unknown correlation and replaced by the fixed line: a reply in a run that
   made no tool call (a greeting, a clarification), every WhatsApp group-chat reply,
   and every reply from an agent other than `idx`, tool calls or not.

### WhatsApp behaviour
A DM final reply (block streaming is off by default) goes through the dispatcher's
`reply_payload_sending` stage before channel delivery (`deliver-prepare:113-142`).
On a substitute the handler replaces the whole payload with `{text: <stored cards>}`:
the verifier reads only `text`, so every other field the model's reply produced
(media from `MEDIA:` lines or markdown images, `presentation`, `fallbackText`,
`spokenText`, `interactive`, `location`, `channelData`) is dropped, never shipped
beside the card. While the handler runs, the stored card text is what WhatsApp's own
formatting and chunking then send. A registered run with no card call passes its
payload as the model wrote it, all fields included (strict mode reads only `text`). When verification fails, or the
run is unknown, the user gets the fixed line. When the release hook does not run
(the plugin not loaded, a 15 s timeout, a failure outside the handler's own catch, a
result shape the host rejects, or a path that skips the hook) the model's raw text
goes out unchanged: on a card turn the model held only a token, but any figure it
invented, any malformed reply and any reply of an unmatched run are delivered as
written. That is the blocker below, not a guarantee. If the plugin never loaded, no
binding existed and the server refused, so no card value or token was issued.

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

### Why it fails closed (only while the release handler runs)
Card values exist in two places only: the server's rendering and the owner-only
store, which code reads at one point, the WhatsApp release handler, and only after
every check passes. What fails closed is the issuing of card values and, while the
release handler runs, the release. The send itself does not: items 2 to 4 send the
model's text unchanged (section "Architectural blocker").
1. `before_tool_call` throws or times out: the host blocks the tool; no card.
2. The plugin does not load: no binding; the server refuses; no card value and no
   token reach the model. But the release handler is absent too, so whatever the model
   writes (an invented figure included) is delivered unchanged. Not fail-closed.
3. A binding is forged with the plugin absent: a token may be issued, but nothing
   releases it; the user sees a raw token with no digits, plus any text the model
   wrote around it.
4. The release hook does not run (timeout, a failure outside its catch, a rejected
   result shape, a skipped path): the model's text goes out unchanged. On a card turn
   it only ever held a token (switch on) or a refusal (switch off with the plugin
   loaded, item 7), so the tool's figures are not in it, but invented figures and
   malformed replies are delivered. Not fail-closed. Only with the plugin absent and
   the switch off does the model get the card, which is today's behaviour.
5. The release hook runs and a check fails, or the run is unknown (no run id, never
   registered, another session, expired): the fixed line, then cancels.
6. The store cannot be read safely (permissions, symlink, owner, size, shape): the
   record counts as missing; withheld.
7. The plugin is on but the server switch is off (critique fix, corrected in the
   review of #176): the server refuses every card call that carries the binding
   argument, so the model never holds a card value. The earlier design sent the full
   card and relied on the release hook's ledger to withhold the retyped reply; that
   failed open whenever the two hooks could not be correlated (a different run id or
   session key in the reply hook, no run id at the tool hook, so a `none` binding, or a
   gateway restart emptying the in-memory ledger).
8. Paths that skip the release hook (the message tool's `sendMessage`, heartbeat,
   cron and exec-completion turns; block streaming if turned on and ACP finals were
   not traced) cannot carry a card value we issued, since the model holds only tokens
   on a card turn, but any figure the model invents on them is sent unchecked. Not
   safe; see "Paths that skip the hook".
While the release handler runs, the remaining way to show a wrong number is the
model inventing one in a registered run with no card call: on card turns any text
outside tokens is withheld, and unmatched runs are withheld whatever their text, but a
registered card-free run passes its text (strict mode, below, is an owner decision).
When the handler does not run, nothing in this prototype stops it.

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
  is withheld (revised 2026-11-06: always, not only while a card run is open, and so
  is a run the release side never registered for that session); the stub tests use
  the field paths named in the critique; the pre-activation check is listed below.
  Not shown: the real host's values (no host run in this offline work).
- **Low, citations — adopted** (this section). **Low, accessibility — adopted:** an
  80-bit ref and 64-bit tag, with words first in the token. **Low, privacy and
  pruning — adopted in part:** only a digest and an enum enter the binding, and
  pruning removes only expired records while a full store refuses the write. Not
  adopted: a per-session cap and expiry tied to the ledger (a global cap of 64 and a
  300 s wall-clock TTL remain; owner decision).

### Limitations
- **Architectural blocker (OpenClaw 2026.9.5).** The prototype withholds only while
  its release handler runs. With the handler absent (plugin missing, failed to load,
  disabled, or not granted conversation access), timed out, failing outside its own
  catch, or returning a shape the host rejects, the host delivers the model's text
  unchanged; heartbeat, cron and exec-completion turns and message-tool sends skip
  the hook. Token redaction and prompt instructions reduce this; they cannot remove
  it. The `test_host_blocker_*` tests assert this outcome so the suite shows the gap.
- An invented figure in a registered run without a card call is not blocked unless
  strict mode is turned on. Layer 1 still detects offline.
- With the plugin loaded, unknown correlation replaces these WhatsApp replies with
  the fixed line every time: a run that made no tool call, any group chat, and any
  agent other than `idx` (only `idx` direct chats are registered; the cost of
  correlating through `before_tool_call` only).
- The dashboard gets no cards; its refusal wording is the model's relay.
- While the release handler runs, a store problem or a session/run mismatch between
  the two hooks costs the card: the user sees the fixed line or a refusal. A skipped
  hook or an unloaded plugin is different: the model's text goes out unchanged,
  invented figures included (the blocker above). On a card turn that text holds a raw
  token rather than a card value, but nothing stops a figure the model made up. This
  prototype guarantees neither delivery nor "no wrong number".
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
8. The delivery boundary (2026-11-06): choose Path A (an owned WhatsApp channel) or
   Path B (an external adapter) from "Delivery boundary: feasibility and
   recommendation", and approve or reject the transport dependency either needs
   (Baileys, or the paid WhatsApp Cloud API). Until then the guarantee is limited as
   stated above and #179 stays unmerged.

## Architectural blocker (OpenClaw 2026.9.5, read only, 2026-11-06)
With the stock OpenClaw WhatsApp plugin, a plugin cannot guarantee that raw model text
never reaches a buyer. The only output hooks, `reply_payload_sending` and
`message_sending`, are fail-open by design, and the vendor documents this. If our
release hook is missing, throws or times out, OpenClaw sends the original reply
anyway, and some sends skip the hook entirely. `before_agent_run` does not help,
because it runs before the model writes anything. The only place where a failure
really stops the send is the channel's own delivery function. The stock WhatsApp
plugin owns that function, and nothing supported lets another plugin add code there.
Meeting the requirement means owning the WhatsApp send path: either our own WhatsApp
channel plugin with the stock one blocked, or a separate adapter process. Both need a
WhatsApp transport library (Baileys, a new dependency) or the paid WhatsApp Cloud API.
That needs the owner's approval, and so do any config change, linking and activation.

Evidence, read from the installed `openclaw` 2026.9.5 and `@openclaw/whatsapp`
2026.9.5 (`dist/` paths; first 12 hex of each file's sha256). Nothing was changed,
installed or run against the host.
- **Failure policy is hard-coded.** The global hook runner makes exactly three hooks
  fail-closed: `before_agent_run`, `before_install`, `before_tool_call`
  (`hook-runner-global-CN2-D2Rq.mjs:85-100`, `8a9a236d7874`); every other hook is
  fail-open, a throw logged and swallowed (`hooks-Jjh3afyP.mjs:425-441, 622-629,
  780-789`, `94e01df2379f`). The vendor docs say the same for both output hooks: "Log
  and skip the failed handler" (`docs/plugins/hooks/reference.md:93-95`,
  `e442a3a833f0`). No other caller passes a failure policy
  (`register.message-Buk5S0Rb.mjs:174`), and no config, manifest field or env var sets
  one: `plugins.entries.<id>.hooks` is strict with `allowPromptInjection`,
  `allowConversationAccess`, `timeoutMs` and `timeouts` only, and top-level `plugins`
  has no `required` key (`zod-schema-DN2u5FdA.mjs:673-689, 1834-1851`,
  `8c529aa3affc`).
- **Hook absent.** With no `reply_payload_sending` handler registered the payload is
  returned unchanged and sent (`deliver-prepare-BRk062mg.mjs:26-39, 121-141`,
  `03f60ee0178f`). A plugin that fails at gateway startup is recorded as an error and
  startup continues without its hooks (`loader-shared-BulwGaGf.mjs:146-169, 454-458`,
  `918b140f8fcd`; `server-startup-plugins-Dkw8Aafn.mjs:188-189`, `cd3653f55d3a`).
- **Throw or timeout.** The default timeout is 15000 ms, configurable from 1 to
  600000 ms (the cap is the config schema's `max(6e5)`,
  `zod-schema-DN2u5FdA.mjs:686, 688`, `8c529aa3affc`; the runtime only drops values
  that are not positive); a timeout rejects and is handled like any throw, so the payload is sent
  unchanged and a longer timeout only delays it (`loader-runtime-load-CdQ5OcQq.mjs:
  1881-1887, 3925-3942`, `91180d699f64`; `hooks-Jjh3afyP.mjs:382-392, 638-654,
  756-757`). The prototype's own catch returns `{cancel: true}`, which helps only while
  the handler itself runs.
- **Result shapes the host rejects.** Only `cancel === true` withholds and only a
  payload object replaces; `{cancel: "yes"}`, a primitive, or an object without a
  payload leaves the payload unchanged, and `{payload: null}` throws inside the
  fail-open try (`hooks-Jjh3afyP.mjs:479, 492-500, 765-767, 1135-1147`;
  `deliver-prepare-BRk062mg.mjs:133-140`).
- **Paths that skip the hook** (confidence medium-high; not every outbound caller was
  enumerated). Heartbeat, cron and exec-completion turns and observe-only admission
  set `suppressOutboundHooks` (`dispatch-BeNOmkLV.mjs:533, 571, 624-629`,
  `78ac59c89fc9`; `heartbeat-runner-run-BPqPC60M.mjs:1441-1445`, `4667a9bbcf0c`);
  outbound sends without `replyPayloadSendingHook`, such as message-tool
  `sendMessage`, skip it (`message-ChcmS1Sd.mjs:196-215`, `1129d1ceaf54`;
  `deliver-prepare-BRk062mg.mjs:273-278`). `message_sending` is fail-open twice, in the
  runner and in a catch that returns the original payload
  (`deliver-prepare-BRk062mg.mjs:264-271`; `lifecycle-BL9jY9Cb.mjs:244-273`,
  `e2a7991dd326`).
- **`before_agent_run` does not close it.** It is fail-closed only when a handler is
  registered; for a non-bundled plugin without `allowConversationAccess` the
  registration is dropped with a warning, and it runs before inference, so it never
  sees the model's output (`hooks-Jjh3afyP.mjs:316-327, 937-966`;
  `builtin-openclaw-C7-lQJ2Z.mjs:5640-5712, 7376-7391`, `97435362096a`;
  `loader-runtime-load-CdQ5OcQq.mjs:3917-3923`). Its event carries no run id; the run
  id is on `ctx` (`builtin-openclaw-C7-lQJ2Z.mjs:5673-5682, 6814-6833`).
- **Where a failure does stop the send.** In the reply dispatcher, a throw in
  `beforeDeliver` or in the channel's own `deliver`/`preparePayload` sends nothing
  (failed-before-deliver or failed-deliver, then `onError`); the only resend is a TTS
  text fallback through the same `deliver`, and a channel `beforeDeliver` stage rejects
  at 15 s, which also blocks (`reply-dispatcher-Dt2lN800.mjs:15-56, 107-109, 304-391,
  400-437`, `3786ba69e33f`). The vendor docs: "Failure is not permission to send the
  same payload through another path" (`docs/plugins/sdk-channel-outbound.md:314`,
  `d60f2781e49c`).
- **That point belongs to the WhatsApp plugin.** `@openclaw/whatsapp` builds its own
  delivery adapter and dispatcher options inside its monitor
  (`.setup/monitor-BblvzLpX.mjs:3415-3511`, `6a6ca5dcd340`), and
  `messaging.transformReplyPayload` is resolved from the loaded channel plugin of that
  channel id only, synchronously, with no session or run
  (`reply-pipeline-CP9cBMci.mjs:14-46`, `8be817592adc`; `reply-transform-BiHTxlzJ.mjs:
  30-39`, `c825fdb3becf`); the stock plugin defines none (`.setup/channel-CSclZYjU.mjs:
  198-250`, `f7f7ddf74828`). No supported way for another plugin to add code there
  was found (by inspection, not proven).

What the prototype still gives, honestly: with the plugin absent, `before_tool_call`
never binds, so under `IDX_CARD_DELIVERY=1` the server refuses every card call and the
model is never given a card value or a token (asserted in
`tests/test_card_delivery_host_blockers.py`); with the plugin loaded, a retyped card
can hold no tool figure because the model held only a token. Neither stops an invented
figure, a malformed reply or an unmatched run's reply from being sent when the release
handler does not run. The blocker tests (`test_host_blocker_*` in Python,
"host blocker:" in Node) model the documented host semantics (emulated, not copied)
and assert that outcome.

Options that would remove the blocker (detail and costs in the next section):
1. **An owned send path: our own WhatsApp channel plugin (Path A).** It claims channel
   id `whatsapp` with `preferOver: ["whatsapp"]`, the stock plugin is denied, and the
   verifier runs inside its only send function. Needs from the owner: approval of the
   transport dependency, the config change, a QR link and a supervised activation.
2. **An external adapter (Path B).** A separate process owns the WhatsApp connection
   and sends only verified replies; OpenClaw's WhatsApp channel is denied. Needs from
   the owner: the same dependency decision (or the paid Cloud API), enabling the
   gateway HTTP endpoint with narrowed scopes, and running a second service.
3. **An upstream fail-closed option.** OpenClaw adding a per-plugin failure policy or
   a `required` flag for `reply_payload_sending`, or a supported channel delivery
   hook. No code from us beyond a request; the timing is not ours. Needs from the owner:
   a decision to raise it with the vendor. Until it ships, it is not a path.
A partial hardening was found and not adopted: a dispatcher `appendBeforeDeliver`
stage reachable from the `reply_dispatch` hook context would fail closed on its own
throw or timeout (`reply-dispatcher-Dt2lN800.mjs:15-57, 326-343`;
`api-DArLOVCi.d.ts:5015, 5913-5929`, `7decea02a45e`), but whether the hook's facade
exposes it is unverified, and a missing plugin still means no gate.

## Delivery boundary: feasibility and recommendation (recommendation pending the owner)
Question (owner, 2026-11-06): which delivery path cannot fall back to raw model text
when the verifier is missing, throws or times out? Compared read only, with the
citations above and in the paths below. This is a recommendation; the owner decides.

**Recommendation: Path A, a small project-owned WhatsApp channel plugin.** It claims
channel id `whatsapp`, sets `preferOver: ["whatsapp"]` in its manifest, and the stock
`@openclaw/whatsapp` plugin is blocked with `plugins.deny: ["whatsapp"]`. The only
function in it that can call the WhatsApp transport is its outbound/deliver step,
which calls the existing `verify.mjs` under its own deadline and, on any result other
than verified, withholds the reply or sends a fixed safe text. Direct messages and
text only; media refused. Stop treating the #179 hook prototype as the guarantee:
finish its regressions and limitation wording, keep it unmerged as defence in depth
(`before_tool_call` stays the fail-closed binding; `reply_payload_sending` is best
effort). Choose Path B only if the owner would rather run a separate process than keep
native ingress; today B pushes buyer turns through an owner-privileged gateway
endpoint, so it is the riskier of the two.

Why: only Path A blocks raw model text by construction, through supported and
documented APIs, without raising privilege.
1. Missing verifier: if `verify.mjs` or the plugin fails to load, no channel is
   registered and startup continues (`loader-shared-BulwGaGf.mjs:146-169`). Deny is
   checked before every other enablement rule (`config-normalization-shared-Btqp-2KT.mjs:84`,
   `e9ea9129fdff`), so the stock plugin cannot take its place, and with no plugin
   owning `whatsapp` nothing can send there: the message tool, cron and queue replays
   send through the channel plugin's own outbound (`docs/plugins/sdk-channel-plugins.md:
   19-37`, `7863cbed7dde`).
2. Throwing verifier: the dispatcher awaits the channel's deliver
   (`reply-dispatcher-Dt2lN800.mjs:354`) and a throw is recorded and passed to
   `onError` (`:383-390`); the only resend goes back through the same deliver (`:435`).
3. Timed-out verifier: the dispatcher puts no deadline on deliver (`:354`), so our
   deliver sets its own; the transport call sits after a verified result, so a timeout
   means no send.

### Path A: project-owned WhatsApp channel plugin (stock plugin denied)
- **Fail-closed by construction:** yes, if `plugins.deny` contains `whatsapp` and
  every transport send is reachable only through deliver after a verified result. A
  channel id registers once, first wins (`loader-runtime-load-CdQ5OcQq.mjs:2938-2960`);
  `preferOver` for "a maintained fork that keeps the same channel id" is documented
  (`docs/plugins/manifest/surfaces.md:516-541`, `c0cc9e27f93e`).
- **Missing / throwing / timed-out verifier:** no channel at all / caught before the
  transport call, failed-before-deliver, no other route / own deadline (for example
  2 s), withheld. Needs a static import of `verify.mjs` and a startup self-test.
  Residual risk: an operator who removes the deny brings the stock plugin back; a
  startup check and a runbook note cover it, the host does not.
- **Supported API:** the channel plugin SDK (outbound, DM policy, pairing, session
  grammar are plugin-owned). Not supported: deep-importing the stock plugin's socket
  and login helpers (no exports map); do not.
- **Effort:** large but bounded, about 1,000 to 1,500 lines plus tests (the stock
  plugin is about 13,000 lines of dist JS; ours is DM-only, text-only, no groups).
  About four PRs: the ADR-0015 revision and contract tests on a fake transport; a
  channel skeleton with an owned deliver; the real transport (Baileys, a new
  dependency needing owner approval); a cutover and rollback runbook, then a
  supervised owner-run activation. Tests need no keys: missing verifier means no
  channel; throw, timeout, unknown correlation, an unmatched run with invented
  figures, host error notices, deferred block resend, queue replay and message-tool
  sends each withhold or send fixed text; one call site touches the transport.
- **Rollback:** disable our plugin and remove `whatsapp` from `plugins.deny` together,
  restart the gateway, re-link by QR if our plugin used its own auth directory.
  Keep the stock auth directory, the session store and the `channels.whatsapp`
  allowlist and pairing config; check the outbound delivery queue is empty first, or
  queued payloads replay through the stock plugin unverified. Minutes, plus a QR scan
  if the auth directory is not shared.
- **Risks:** the same unofficial WhatsApp Web protocol the stock plugin bundles
  (baileys 7.0.0-rc14, `@openclaw/whatsapp` `package.json`, `7793fbdd3351`), so ban
  risk similar to today but a new linked device or reconnect bugs could trip
  anti-abuse checks; a session conflict if both plugins connect one account
  (deny-first prevents it); protocol maintenance is ours; in-process transport code
  needs a security review; message-tool and cron sends may carry no run id and would
  be withheld; the new dependency breaks the no-new-dependency rule unless approved.
  Dashboard unchanged: card turns stay refused.

### Path B: external adapter (separate process owns WhatsApp; OpenClaw's channel denied)
- **Fail-closed by construction:** yes, in our process: OpenClaw has no WhatsApp
  sender loaded, and the adapter sends only after a verified result. Missing verifier:
  the adapter fails at import and never connects (silence, not raw text); throw and
  timeout: caught, withheld.
- **Supported API:** partly. The gateway's OpenAI-compatible endpoint is documented
  but disabled by default; with token or password auth it grants the full operator
  scope set and "Treats chat turns as owner-sender turns"; narrowing needs
  trusted-proxy auth (`docs/gateway/openai-http-api.md:8, 41-52, 95-106`,
  `b0292382aa0e`). The WhatsApp side is Baileys (unofficial) or the Cloud API
  (official; a Meta business account, possible cost).
- **Effort:** similar code (about 800 to 1,500 lines) plus a second supervised
  service: transport, allowlist, DM policy and pairing re-implemented, a per-buyer
  session-key map, a gateway client, the verify gate, re-keying the card binding, and
  a privilege test that buyer turns run without `operator.admin`. About five PRs plus
  owner config work.
- **Rollback:** stop and disable the adapter first, then remove the deny, re-enable
  `channels.whatsapp`, turn the HTTP endpoint off, restart, re-link if needed.
  Minutes; two linked devices on one number risk duplicate replies during cutover.
- **Risks:** gateway privilege (every buyer turn an owner/operator turn unless
  narrowing is set up and tested), a new network surface, lost native ingress
  semantics, a second process to monitor, the same ban risk or Meta onboarding.

### Path C: the current hook prototype (#179), for comparison
- **Fail-closed by construction:** no (section "Architectural blocker"). Missing,
  throwing outside its catch, or timed-out release handler: raw text delivered.
- **Effort:** this revision (regressions, blocker tests, wording); one PR, kept
  unmerged. **Rollback:** nothing is installed; leaving `IDX_CARD_DELIVERY` unset and
  the plugin unloaded is today's state. **Risk:** false assurance if anyone reads
  `reply_payload_sending` as a guarantee; its value is defence in depth.

### Next steps (proposed)
1. Key-free, no owner action: this revision of #179, unmerged.
2. Key-free: revise ADR-0015 and this design to name Path A as the target boundary,
   with `reply_payload_sending` marked best effort; dashboard card turns stay refused.
3. Owner: choose Path A or B, and approve or reject the transport dependency
   (Baileys) or the paid Cloud API.
4. Key-free, after 3: Path A PR 1, a channel skeleton on a fake transport with the
   contract tests above; nothing installed or loaded.
5. Owner-approved dependency: PR 2, the real transport (DM-only, text-only, own auth
   directory, startup self-test, refusal to start unless the stock plugin is denied).
6. Key-free: PR 3, the cutover and rollback runbook (deny-first ordering, the auth
   directory decision, an empty-queue check, QR re-link).
7. Owner only: a supervised activation on a test number. Never automated here.

### Open questions for the owner
- Reuse the stock auth directory (fast rollback, shared session state) or link as a
  new device (cleaner, a QR re-link and a new linked-device footprint)?
- Do message-tool, cron and heartbeat sends carry a session key and run id in the
  owned outbound context, or will they always be withheld? Not traced; needs a
  fake-transport test.
- Baileys as a new direct dependency, or the official Cloud API despite the Meta
  account and possible cost?
- A withheld reply: silence, or one fixed safe text (a constant in our code, never
  model text)?
- Where does the persisted outbound delivery queue live, and what read-only check
  confirms it is empty before cutover and rollback?
- Is an operator removing the `plugins.deny` entry an acceptable residual risk with a
  startup self-check and a runbook note, or is a CI and config guard wanted too?

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
`tests/test_card_delivery_host_blockers.py` (host emulation, 2026-11-06 revision),
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
simulated hook failures. Revision of 2026-11-06: unmatched reply runs with invented
figures (no run id, unknown run, another session's run, expired registration), the
malformed-reply payloads with the release handler throwing, and host-emulation
blocker tests for the hook absent or timed out.

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
offline prototype held unmerged (#179); architectural blocker reported; delivery
boundary recommendation (Path A) pending the owner — 2026-11-06 — Revised on the
owner's instruction of 2026-11-06 ("Hold #179 ..."; "Continue the read-only
feasibility check first ..."). Current main merged. Unknown correlation now withholds:
`before_tool_call` registers every run in a WhatsApp direct chat, and a payload with
no run id or a run not registered for its session (never, another session, expired)
is withheld whatever its text (`before_agent_run` not used; see "How it works", item
6). Regressions added in Python and Node from the shared vectors: unmatched reply runs
with invented figures (withheld) and ten malformed-reply payloads (withheld by the
verifier, cancelled when the release handler throws). Host-emulation blocker tests
(`test_host_blocker_*`, "host blocker:") assert today's outcome honestly: with the
release hook absent, timed out, failing outside its catch or returning a rejected
shape, the malformed reply is delivered unchanged; with the plugin absent no card
value or token is issued. The guarantee is restated everywhere as withholding only
while the release handler runs; "Architectural blocker" and "Delivery boundary:
feasibility and recommendation" are new. Tests: 145 new Python tests (65 in
`tests/test_card_delivery.py`, 80 in `tests/test_card_delivery_host_blockers.py`) and
158 Node tests (78 new; corrected from 88); full suite 5746 passed, 131 skipped; ruff check and format
clean. ADR-0015 stays proposed. Key-free and model-free: no paid call, no install,
activation, config, gateway, `.env` or `~/.openclaw` change; the installed OpenClaw
and WhatsApp plugin were read only. Review fixes (same day): a substitute now replaces
the whole payload (`{text}` only), so model media, `presentation`, `fallbackText` and
other fields never ship beside a stored card; Python `correlation_problem` skips a
`None` or non-mapping `known_runs` as `correlationProblem` does; the limitation and
"Why it fails closed" wording no longer says a skipped hook only costs the card or
that hook-skipping paths are safe; the group-chat and other-agent withhold cost is
stated; two citations corrected. Tests after the fixes: 151 new Python tests and 161
Node tests (81 new); full suite 5752 passed, 131 skipped; ruff check and format clean.

Earlier: offline prototype in review; not installed or activated; owner decisions
pending — 2026-11-06 — Built from the owner's decisions of 2026-11-06 on branch
`wo-036-card-relay-prototype` (stacked on #171): the token relay described in
"Recommended architecture", ADR-0015 (proposed, not accepted), default off
(`IDX_CARD_DELIVERY` unset, main's behaviour byte-identical). Key-free and model-free:
no paid call, no install, activation, config, gateway, `.env` or `~/.openclaw` change.
Fail before, pass after: with the release step as on main, the changed-square-footage
regression fails (4 of 4); with the prototype it passes. After the review fixes
(`9f3eb75`): 266 new Python tests and 70 Node tests pass; the full suite passes (5593
passed, 131 skipped). The critique's
critical, high and medium fixes are adopted, two of them in part, as listed above. Owner
decisions pending: the seven under "Owner decisions pending". The first proposal's
owner questions are answered by the 2026-11-06 decisions (the dashboard's stream must
be protected or its card turns refused; WhatsApp first is acceptable).

Earlier: proposal, not approved to build — 2026-11-05 — Layer 3 work order written from
the owner's decisions of 2026-11-05; the OpenClaw 2026.9.5 hook check for (b) done read
only.
