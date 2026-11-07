# idx-whatsapp-channel — offline Path A skeleton

A project-owned OpenClaw channel plugin that claims channel id `whatsapp` for DMs and
puts every outbound text through one verified gate. This directory is the skeleton
only: it runs on a fake transport in tests and nothing points the host at it.

## What it is
- `openclaw.plugin.json`: manifest, id `idx-whatsapp-channel` (not `whatsapp`, so
  `plugins.deny: ["whatsapp"]` blocks only the stock plugin), `channels: ["whatsapp"]`,
  `channelConfigs.whatsapp.preferOver: ["whatsapp"]`, an empty strict `configSchema`.
- `index.mjs`: hand-written `register(api)`. Returns without doing anything in the
  `cli-metadata` and `tool-discovery` modes; in `full`, `discovery`, `setup-only` and
  `setup-runtime` it runs the startup self-check against `api.config` (the host's
  OpenClawConfig snapshot) and throws unless the stock plugin is denied, the statically
  imported verifier passes its vectors and `SAFE_TEXT` is digit-free. A throw inside
  `register` is caught by the loader, the plugin is marked `error` and no channel is
  registered.
- `channel.mjs`: the channel object. `capabilities.chatTypes: ["direct"]`; no `message`
  adapter, no `actions`, no media, polls or chunker; `config.isConfigured` is false
  until a real transport exists, so the host records the account as skipped instead
  of entering its restart loop. It owns ingress: each inbound text is recorded per
  `(accountId, peer)` with the session key and a channel-generated turn id
  (`randomUUID`; the peer's WhatsApp message id is sender-chosen and travels only as
  metadata, so a re-sent id cannot bind a new turn to an earlier turn's card).
  `ingress.record` returns a trusted turn handle that stays in the closure of that
  inbound. The inbound reply `deliver` callback is routed into the same
  `outbound.sendText` the message tool, cron, heartbeat and CLI reach through the
  registry, passing the handle as `turn` so a reply that lands after the peer's next
  message is verified against the message it answers; it is the only caller in this
  skeleton that holds a handle, so it is the only one that can send (decision 17). The
  host runner receives the turn id as a string (metadata), `deliver`, and
  `beforeToolCall(toolName)`, which marks the turn as a card turn through the closure
  and is named for when the host fires it: before the tool executes (decision 16); it
  never receives the handle, so nothing on the runner's side can bind a send to a turn.
  `createBeforeToolCallHandler(ingress)` is the hook-shaped twin: it returns
  `(event, ctx) => ingress.markCardToolForSession(ctx?.sessionKey, event?.toolName)`,
  the function the install PR registers with the host's `before_tool_call` hook (the
  fail-closed hook that fires before execution; the hook knows the session key, not our
  handle, so it marks every open turn of the session, over-marking being the safe
  direction). Both seams match the tool name with `isCardTool`, which accepts the host's
  namespaced spelling (`idx__search_listings`, ADR-0003) as well as the bare server name,
  case and padding included, so a spelling difference cannot skip the mark. The handler
  returns the number of turns it marked and never throws, whatever the host passes (a
  non-object, a non-string session key, a non-card tool, or an argument whose property
  read throws all return 0); whether the host treats a numeric return from a
  `before_tool_call` handler as a block directive is unverified, so the install PR
  confirms it or registers a wrapper that discards the return value. `index.mjs`
  registers nothing with the host api (hook signature unverified, install-PR item). A
  `deliver` that sent `SAFE_TEXT` returns
  `{ messageId, visibleReplySent: true, withheld: { reason } }` (a message went out, so
  the dispatcher must not retry a fallback); a `deliver` that sent nothing returns
  `{ visibleReplySent: false, suppression: { reason } }`.
- `outbound.mjs`: the gate. `normalizePayload({ payload, cfg, accountId })` (the host's
  envelope, idempotent) admits `text` and `replyToId` only; any present content field
  other than text refuses the whole payload, caption included. `sendText(ctx)` first
  binds the send to a turn: `ctx.turn` must be a handle the ingress minted for this
  `(accountId, peer)`; a handle it does not recognise (forged, another peer's, expired,
  evicted) is withheld `untrusted-turn` and nothing is sent, not even `SAFE_TEXT`, since
  there is no trusted record to speak to. A bare `ctx.turnId` from any caller is
  `untrusted-turn` as well: naming a turn by id proves nothing. A context with neither
  (the message tool, cron, heartbeat and CLI shapes) is withheld `no-turn-handle` with
  nothing sent in either mode: the handle is required and there is no fallback to the
  peer's newest turn, even when that peer wrote seconds ago (decision 17). The handle
  is therefore the only binding path, `boundToTurn` is true on every line that records
  a send, and `ingress.forTurn` is the gate's only record read. Every context field is
  read exactly once, up front: `to` must be a non-empty string (anything else is
  withheld `bad-destination`, nothing sent), the one value read is canonicalised, the
  record is looked up under that canonical peer, and the transport is handed that same
  canonical peer, so a getter or a stateful `toString` on `to` cannot have the verifier
  check one peer and the transport deliver to another. It then runs the
  verifier under a wall-clock deadline, snapshots the verifier's result with every field
  read once (a getter or Proxy cannot answer the check with one value and the seal with
  another), rejects a thrown, late or malformed verdict (malformed includes an incomplete
  or inconsistent release, below), and sends only sealed text through the single
  `transport.sendText(` call in the runtime. A transport error propagates and is never
  retried here. One audit line per call carries outcome, reason, rule, whether a record
  existed, whether the send was bound to a trusted turn (`boundToTurn`) and the text
  length; never the text, the peer, the session key or the turn id.
- `verifier.mjs`: pure, synchronous policy (below). `card-resolver.mjs`: the null
  resolver (withholds every card token). `ingress.mjs`: bounded, expiring records (the
  newest four turns per peer), reachable only through their handles (there is no read
  by key: no `current`, nothing that returns a peer's newest turn), and peer id
  canonicalisation (`whatsapp:` prefix and the
  phone-number JID suffixes `@s.whatsapp.net` and `@c.us` fold to `+<digits>`; a linked
  id stays `<digits>@lid`, its own namespace, so it never shares a record with the
  phone-number peer). `record` returns a frozen `{ turnId, key }` handle whose identity is
  the key of a WeakMap private to the instance, mapping the handle to the one stored entry
  it was minted for; `forTurn(key, handle)` answers only for that identity, that key and
  that very entry, so a turn id string or a look-alike object is not a handle and a second
  record carrying the same turn id is a different turn with its own handle (the older
  handle keeps its own record and its own mark). Each record carries `cardToolCalled`, false at
  record time and monotonic: `markCardTool(handle, toolName)` (trusted handle plus a
  `CARD_TOOLS` name) or `markCardToolForSession(sessionKey, toolName)` (every open turn of
  the session; over-marking a concurrent turn is accepted, under-marking is not) sets it,
  nothing clears it, a later turn never inherits it, and lookups return frozen copies.
  `transport.mjs`: the interface the real transport will implement and the default that
  rejects everything. `constants.mjs`, including `CARD_TOOLS` (mirrors the server's
  one-copy tools: `search_listings`, `get_market_stats`, `find_similar_listings`,
  `recommend`, spelled as the server names them) and `isCardTool`, which fails closed on
  spelling: the exact name matches, and so does any name whose trimmed, lowercased last
  segment after a namespace separator (`__`, `.`, `/`, `:`) is a `CARD_TOOLS` name, so
  the host's `idx__search_listings` marks a turn exactly as `search_listings` does; a
  name that differs otherwise (`search_listings_v2`, `get_listing_details`) never marks.
- `test-support/`: fake transport, in-memory card resolver and host emulation. Used by
  tests only; a source test proves no runtime file imports them.

## What it is not
- Not installed, enabled, linked or configured. No `package.json`, no dependency, no
  network, no credentials, no auth directory, no QR flow. The directory is loadable
  through `plugins.load.paths` (manifest plus `index.mjs` is enough for the loader); it
  is not loaded only because no config names it. The self-check and
  `isConfigured: false` are the actual guards, and an accidentally loaded skeleton can
  neither start an account nor send.
- Not a Baileys or Cloud API transport. Transport and credential choices are deferred;
  `Transport` (`start`, `sendText`, `stop`, `isConfigured`) is the seam.
- Not wired to the host's route resolver or inbound turn runner. `createChannelPlugin`
  takes `resolveRoute` and `runInbound` seams; the entry passes none, and without them
  an inbound is dropped with a warning.

## Run the tests
```
node --test extensions/idx-whatsapp-channel/verifier.test.mjs \
            extensions/idx-whatsapp-channel/channel.test.mjs \
            extensions/idx-whatsapp-channel/host.test.mjs
.venv/bin/python -m pytest -q tests/test_whatsapp_channel_skeleton.py
```
The pytest wrapper skips (with a reason, visible under `-rs`) when `node` is missing or
older than 20. The CI workflow has no Node setup step, so whether the Node tests run in
CI depends on the runner image shipping Node 20+; the workflow is not edited on this
branch (gates consent), so this is contingent, not guaranteed. Locally with Node present
the wrapper's two tests pass and the Node suite runs inside it.

## Verifier policy (skeleton, open for owner review)
`verifyReply({ text, inbound, resolver })` is pure and synchronous. Rules apply in order;
the first match decides. A figure is a maximal run of Unicode numeric characters
(`\p{N}`: decimal digits in any script, other numerals such as `½`, `⑫`, `²`, `⒓`, and
letter numerals such as `Ⅻ`), compared whole: `34` never passes on the strength of `3`
and `4`; `1,240` is the two runs `1` and `240`; `ft²` carries the figure `²`. Number
words ("twelve") are not figures.

- R0: not a string, empty, longer than 4000 characters, or no inbound record for the peer
  (unknown session, nothing recorded, expired) -> withhold. A record without a boolean
  `cardToolCalled` -> withhold `malformed-inbound-record`.
- R1 cards: if a token fragment appears (`[[`, `]]`, `[card:`, or `card:` closed by `]`),
  the text must consist of complete `[[card:<ref>]]` tokens and whitespace only (no prose
  beside a card, no duplicate ref, no partial or re-spelled token). Bare `card:` inside
  ordinary prose ("discard:", "credit card:", "scorecard:") is not a fragment and falls
  through to R2/R3. Each ref is resolved for this session and turn; a null result (the
  default resolver always returns null) withholds `unknown-token`; the resolver's `text`
  is read once and that one value is both checked and substituted; the release text is
  the input with each token replaced by the resolver's bytes exactly.
- R1b card turns: if the turn called a card tool (`cardToolCalled === true`), any text
  that is not a fully resolved token-only text -> withhold `card-turn-requires-tokens`.
  Prose with or without figures, greetings and clarifications included, is withheld on
  such a turn; the only release is rule `card`. R1 runs first, so a partial token on a
  card turn is still `malformed-token` and an unknown one `unknown-token`.
- R2: no figures -> release unchanged. Greetings, apologies, digit-free clarifications
  (ordinary turns only).
- R3: every figure appears in the user's inbound text for the turn -> release unchanged.
  "Do you mean 3 or 4 bedrooms?" after "3 or 4" passes (ordinary turns only).
- R4: otherwise withhold `unverified-figures`.

The card-tool mark comes from the host's trusted before-tool-call event, applied BEFORE
the tool executes (owner decision 16, decided 2026-11-06), never from the model and never
from the card store. Per turn it is the `beforeToolCall(toolName)` seam on the turn
object the channel hands `runInbound`, which calls `ingress.markCardTool` with the turn's
own handle; per session it is `createBeforeToolCallHandler(ingress)`, whose
`(event, ctx)` function the install PR registers with the host's `before_tool_call` hook
(the fail-closed hook) and which marks every open turn of `ctx.sessionKey` for a
`CARD_TOOLS` name in `event.toolName`. Because the mark lands before execution and is
monotonic, a card tool that then throws, times out, is refused or returns an error result
leaves the turn marked, so the model's digit-free apology after a failed search is
withheld `card-turn-requires-tokens` rather than released as an ordinary greeting. The
tool name in the event is matched by `isCardTool`, which accepts the host's namespaced
spelling (`idx__search_listings`, `mcp__idx__search_listings`), a cased or padded
spelling, and the bare server name alike, so the mark is not lost to a spelling the
skeleton did not foresee. The mark cannot stop a tool call: the handler only marks and
returns a count, and whether the host reads a numeric return as a block directive is for
the install PR to confirm (or to hide behind a wrapper that returns nothing); it only
tightens the verifier for that turn. A call the hook never sees leaves the turn on the
ordinary rules, which is the residual risk. The fake host in `test-support` runs the same
order (mark, execute, reply) and records it so the tests can assert the mark preceded the
failure, under the bare and the namespaced tool names.

Gate-side, outside the verifier: the result is snapshotted first (each of `kind`, `text`,
`reason`, `rule`, `viaCard`, `then` read exactly once into a frozen plain object; an array
or non-object becomes malformed), then: a throw -> `verifier-threw`; wall time over the
deadline (250 ms, measured around the call with `performance.now`) -> `verifier-deadline`
even if the verdict said release; anything that is not a well-formed verdict ->
`verifier-malformed`. The seal reads the snapshot, so the bytes checked are the bytes
sent.

Verdict completeness (`isWellFormedVerdict(value, inputText, inbound)`): a withhold is
well-formed only with a non-empty string `reason` and no `text`. A release is well-formed
only if all of these hold: `kind` is `release`; `text` is a non-empty string within 4000
characters; `rule` is exactly one of `no-figures`, `user-figures`, `card`; `viaCard` is
`true` for `card` and absent otherwise (`false`, `null`, `0`, `""` are malformed); no
`reason`; no thenable; the record is valid; and the rule is self-consistent with input and
record: `no-figures` means the text is the input and has no figure; `user-figures` means
the text is the input, has at least one figure, and each appears in the record's text;
`card` means the input is token-only (the gate cannot re-resolve, so it trusts the bytes
only after the structural checks). On a card turn the only acceptable release rule is
`card`. The gate does not re-derive the verdict; it refuses one that does not account for
itself, so a verifier bug that releases with a missing or wrong rule is withheld.

Known withholds under this policy, by design until a token path exists: numbered lists,
"24/7", office hours, years, step numbers, superscripts and fractions (`ft²`, `½ bath`),
tool clarifications and error notices that carry figures (`isError` is not visible in
the `sendText` context), any text with a double bracket or `[card:` fragment
(`malformed-token`), and on a card turn every reply that is not a resolved card token
(a follow-up question after a search, a "no results" sentence, an apology). Number words
pass on ordinary turns; "credit card: yes or no?" passes on ordinary turns. Thousands
separators make the policy stricter, not looser.

## Withheld-reply default (owner decision pending)
`WITHHOLD_MODE = "safe-text"`: when the send is bound to a trusted turn and the verifier
withheld it, the reply becomes the single constant `SAFE_TEXT` ("I couldn't send that
reply safely. Please ask again."). A send without a handle (`no-turn-handle`: the
message tool, cron, heartbeat and CLI shapes, whether or not the peer has a fresh
record) or with an untrusted one (`untrusted-turn`) sends nothing in either mode and
returns `{ outcome: "not_sent", reason }`: there is no trusted record to speak to.
`"silent"` everywhere is one constant away. The inbound `deliver` reports a withhold that
sent nothing to the dispatcher as `{ visibleReplySent: false, suppression: { reason } }`
so the host records it as not visible rather than as a delivered reply; a withhold that
sent `SAFE_TEXT` is reported visible (a message did go out, and a not-visible result would
make the dispatcher retry its fallback after it) with the reason in `withheld.reason`. An
`untrusted-turn` withhold never sends, in either mode.

## Residual risks
- The self-check sees the config at registration only. Removing the deny and restarting
  brings the stock plugin back; a runbook note (later PR) covers it, the host does not.
- Proactive sends are withheld in this skeleton. The message tool, cron, heartbeat and
  CLI (alert delivery included) reach `sendText` without a channel-minted handle and are
  withheld `no-turn-handle` with nothing sent, even to a peer who wrote seconds ago. They
  stay withheld until a handle-bearing path for proactive sends exists, which is a later
  owner item (WO-037 item 18). Fail closed, but silent toward the peer; the audit line
  records it.
- Ingress records and handles live in process memory. A reply after a restart, or a
  handle from another process (CLI), is untrusted and withheld; a late reply (TTL 30 min)
  is withheld. Fail closed, but silent. `deliveryMode: "gateway"` keeps CLI sends in the
  gateway process.
- The newest four turns per peer are kept. A reply still in flight when the peer has
  since written four or more messages finds its handle no longer trusted and is withheld
  `untrusted-turn` (nothing sent, reported as not visible). A caller that tries to name
  an older turn by id is withheld `untrusted-turn` instead of being allowed through.
- The transport receives the canonical peer id the record was checked under
  (`+<digits>`, `<digits>@lid`, or a lowercased other id), not the caller's spelling. The
  transport PR owns the mapping from that id to its own address format; until it lands,
  whether a `@lid` address reaches the same person as the phone-number peer is unknown,
  which is why the skeleton keeps them apart rather than folding them together.
- The card-tool mark depends on the install PR registering `createBeforeToolCallHandler`
  with the host's `before_tool_call` hook (or wiring `beforeToolCall` per turn) so that
  every card tool call is seen before it executes. Until then, and whenever the hook
  misses a call, the turn is verified under the ordinary rules (greetings and user-figure
  echoes release; invented figures are still withheld by R4). Marking is monotonic and
  only tightens; it can never loosen a turn, and a failed card call leaves it in place.
  The tool name the hook event carries is matched in the host's spelling as well as the
  server's (`isCardTool`), but the exact field and spelling the real event uses are
  unverified: the install PR captures one real `before_tool_call` event per `CARD_TOOLS`
  tool and asserts the handler marks it before the handler is registered.
- A verifier that never returns stalls that session's serialized reply queue (the
  dispatcher awaits `deliver`); nothing is sent, but the turn is lost. A worker-thread
  verifier is the future fix.
- `channelConfigs.whatsapp.schema` is permissive because it validates the operator's
  existing `channels.whatsapp` section; the skeleton validates no channel config.
- Host behaviour (deny, first-wins registration, dispatcher outcomes) is emulated from
  cited lines in `test-support/host-emulation.mjs`, not exercised against the host.
