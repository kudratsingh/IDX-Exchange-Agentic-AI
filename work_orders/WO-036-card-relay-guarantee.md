# WO-036 — Card relay guarantee (Layer 3 proposal)

**Driver:** owner (chooses the mechanism after the chart trial and approves each build,
install and activation step); agent (writes the chosen work, tests and evidence)
**Depends on:** #169 (Layer 1, the relay check; merged as `4ec99bd`), the Layer 2 PR (one
copy of the card, not yet open), WO-030 (#148, chart delivery) and its one Phase 2 chart
trial (D5), ADR-0012 (deterministic card relay and the gateway privilege boundary)
**Estimated effort:** this proposal, done; each mechanism is sized below and starts only
after the owner chooses it
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
This proposal only:
1. The three mechanisms, each with what it guarantees, what it depends on and what it
   would take to build.
2. The decision rule, exactly as the owner gave it.
3. One focused, read-only check of the OpenClaw 2026.9.5 plugin API for mechanism (b),
   with file:line citations. Nothing was changed, installed or run.

## Out of scope
- Building, installing, enabling or activating any mechanism.
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
- **Depends on** image relay proving intact in the Phase 2 chart trial
  (`docs/ACTIVATION_HANDOFF.md`, procedure 5b, step 5): one WhatsApp image arrived, no
  `MEDIA:` line is visible, and no `⚠️` line appeared.
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
Decided after the chart trial, by the owner, in this order:
- images intact → (a);
- a hook exists → (b);
- neither → (c), as the first L2 infrastructure.

"Images intact" is the Phase 2 chart trial's recorded result (procedure 5b, step 5).
"A hook exists" is answered by the check above. Until the owner applies the rule,
Layers 1 and 2 are the only protection, and Layer 1 fails any turn with a changed
number.

## Files expected to change
This proposal: this file only. A build, once chosen, gets its own work order with its
own file list. Expected areas: (a) `src/idx_agent/` card rendering and the chart
directory, the card skills; (b) `extensions/idx-card-relay/`; (c) a new adapter
component, with the skills and channel docs.

## Interfaces and contracts
- The card message a tool returns stays the source of truth (`docs/CONTRACTS.md`).
- Layer 1's verdicts (`pass`, `fail`, `unavailable`) stay the acceptance check for every
  mechanism.
- ADR-0012's required boundary applies to all three: only rendered card blocks are
  eligible, code inserts the original UTF-8 block, and a regression test shows that a
  model rewrite cannot change a card number.

## Implementation requirements
None in this work order. Each build work order must:
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
For this proposal: the docs gates. Each build brings the regression test from
Implementation requirements 1, offline tests on synthetic cards, and the channel checks
its own work order names.

## Acceptance criteria
- This file states the problem, all three mechanisms, the decision rule exactly, the
  autonomy level, the hook check with file:line citations, and the status "proposal,
  not approved to build".
- Nothing is built, installed, enabled or paid for.

## Verification commands
```bash
python3 scripts/gates/pii_scan.py work_orders/WO-036-card-relay-guarantee.md
python3 scripts/gates/confidential_text.py work_orders/WO-036-card-relay-guarantee.md
python3 scripts/gates/forbidden_paths.py work_orders/WO-036-card-relay-guarantee.md
```

## Deliverables
This work order. No code, extension, config, install or evidence entry.

## Stop conditions
- The owner has not applied the decision rule: build nothing.
- "A hook exists" is ambiguous here: the hook covers WhatsApp's final text and not the
  dashboard's stream. Ask; do not pick (b) on WhatsApp alone.
- Any mechanism would need a session write, a broader tool, a relaxed tool policy or a
  silent extra hook (ADR-0012): stop.
- A build would change OpenClaw config, install a plugin or restart the gateway without
  the owner's approval for that step: stop.
- A newer OpenClaw than 2026.9.5 is installed: the check above is void; redo it first.

## Status
proposal, not approved to build — 2026-11-05 — Layer 3 work order written from the
owner's decisions of 2026-11-05. The OpenClaw 2026.9.5 hook check for (b) was done read
only. Nothing was built, installed or activated. Owner questions: (1) Does "a hook
exists" require the dashboard's streamed text to be covered, or is WhatsApp's final
delivery enough? (2) Under (a) or (c), does the dashboard stay detection-only?
