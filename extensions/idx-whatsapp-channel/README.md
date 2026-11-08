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
  imported verifier passes its vectors, `SAFE_TEXT` is digit-free and `BUSY_TEXT` is
  digit-free and differs from `SAFE_TEXT`. A throw inside
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
  `replyOptions: { runId, onAgentRunStart }`; it never receives the handle, so nothing on
  the runner's side can bind a send to a turn.
  Run binding (owner decision 19, 2026-11-07). Each admitted inbound also gets a
  channel-generated run id (`randomUUID`), stored privately by the ingress with that one
  entry and never logged or put in a record snapshot. The host uses
  `replyOptions.runId` as the run id when given and calls
  `replyOptions.onAgentRunStart(runId, ...)` once at run start (host trace 2026-11-07).
  Only exactly the issued id, on a stored, unexpired turn whose run has not ended,
  confirms the run (`runBound`, monotonic). The callback returns `undefined` for every
  argument and never throws, because returning `"reply-dispatch"` would take over
  completion ownership. The run ends in a `finally` when `runInbound` settles, resolved or
  rejected. A host-minted follow-up id never confirms anything.
  `createBeforeToolCallHandler(ingress)` is the `(event, ctx)` function the install PR
  registers with the host's `before_tool_call` hook, and the single admission path (the
  per-turn `beforeToolCall` seam, `markCardTool`, `markCardToolForSession`, `blockTurn`,
  `blockOpenTurns` and the `toolCallBlocked` taint are gone). It reads `event.toolName`
  first; a non-card name (`isCardTool` false) is `{ block: false, marked: 0 }` with no
  other field read. For a card tool it reads `event.runId`, `ctx.runId`, `ctx.sessionKey`
  and `ctx.requester` once each and admits the call, `{ block: false, marked: 1 }` with
  that turn alone marked `cardToolCalled`, only when `event.runId` is a non-empty string
  equal to `ctx.runId` naming a stored, unexpired turn whose run is confirmed and not
  ended, the session key equals that turn's, and a present requester is a plain object
  naming channel `whatsapp` (trimmed, lowercased), a non-empty string `senderId` that
  normalises to the turn's peer and, if it gives a string `accountId`, the turn's account.
  With no requester (the bundled-MCP path) run id and session key suffice (decision 19
  (a), pending the install PR's host-level test). Anything else refuses the call:
  `{ block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason, withheld }` with `reason`
  one of `unknown-run`, `run-unconfirmed`, `run-ended`, `turn-expired`,
  `session-mismatch`, `requester-mismatch`, `handler-error`. A refusal never marks a turn
  `cardToolCalled`. Owner decision 21 (revision 7): a refusal is tied to its own turn when
  every run-binding check passed for it (the run id names a stored, unexpired turn whose
  run is confirmed and not ended, and the session key is that turn's), which today means
  `requester-mismatch` only. A tied refusal marks that one turn `cardCallRefused` and
  answers `withheld: 1`; the verifier then withholds that turn's later replies. Every other
  refusal is of unknown origin: it refuses the call only, changes no turn and answers
  `withheld: 0`. A session key alone ties nothing, so it never suppresses a turn. The host
  reads `block` and `blockReason` and vetoes the call before execution; `reason` and
  `withheld` stay internal. `isCardTool` accepts the host's
  namespaced spelling (`idx__search_listings`, ADR-0003) as well as the bare server name,
  case and padding included. `index.mjs` registers nothing with the host api
  (install-PR item).
  One active turn per peer (decision 19 (b)): a turn is active from record until its run
  ends, with the ingress TTL as the backstop. An inbound for a peer with an active turn is
  not recorded, not routed and not run, and its text is neither stored nor logged. The
  peer gets `BUSY_TEXT` ("I'm still working on your last message. Please send this one
  again after I reply.") in both withhold modes, through the same single call site. The
  audit line says `outcome: "busy"` and carries no text and no peer. Other peers are
  unaffected, and from WhatsApp no follow-up or steering reaches an active run.
  A `deliver` that sent `SAFE_TEXT` returns
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
  `transport.sendText(` call in the runtime, inside the private `transmit` that the
  busy reply also uses. The busy sender is handed to the channel once, at construction
  (`receiveBusySender`), sends only `BUSY_TEXT` and is not a member of the host-facing
  outbound object (its keys stay `deliveryMode`, `textChunkLimit`, `normalizePayload`,
  `sendText`). A transport error propagates and is never
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
  handle keeps its own record and its own mark). Each record carries `cardToolCalled`,
  `runBound` and `cardCallRefused`, all false at record time and monotonic:
  `admitCardCall` (the hook handler's only marking path, by run id) sets the first on an
  admitted call and the third on a tied refusal, `confirmRun(handle, runId)` the second.
  Nothing clears any of them, a later turn never inherits them, lookups return frozen
  copies, and `isInboundRecord` requires all three booleans (a record missing one is
  `malformed-inbound-record`). `record(key, rec, { runId, accountId, peerId })` refuses
  a duplicate or malformed run id; `endRun(handle)` retires the run id; `hasActiveTurn(key)`
  answers the busy check from an active index kept apart from the record store, so
  capacity eviction of a peer's records never ends that peer's active turn (only `endRun`
  or the TTL does).
  `transport.mjs`: the interface the real transport will implement and the default that
  rejects everything. `constants.mjs`, including `CARD_TOOLS` (mirrors the server's
  one-copy tools: `search_listings`, `get_market_stats`, `find_similar_listings`,
  `recommend`, spelled as the server names them) and `isCardTool`, which fails closed on
  spelling: the exact name matches, and so does any name whose trimmed, lowercased last
  segment after a namespace separator (`__`, `.`, `/`, `:`) is a `CARD_TOOLS` name, so
  the host's `idx__search_listings` marks a turn exactly as `search_listings` does, and
  so does the host's collision spelling with a `-N` suffix (`idx__search_listings-2`); a
  name that differs otherwise (`search_listings_v2`, `search_listings-v2`,
  `get_listing_details`) never marks. A host name cut inside its tool segment by the
  host's 64-character cap is not recognised; the install PR asserts the literal host
  names at startup.
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
  `cardToolCalled`, `runBound` or `cardCallRefused` -> withhold
  `malformed-inbound-record`.
- R0b unbound turns: `runBound !== true` (the host never confirmed the run id the channel
  issued for this turn) -> withhold `unbound-turn`, whatever the text, tokens included:
  with no trusted run there is no trusted activity to support any verdict (decision 19
  (c)). R0b runs before R1.
- R0c refused turns: `cardCallRefused === true` (a card call tied to this turn was
  refused) -> withhold `card-call-refused`, whatever the text, tokens included, and even
  after a later admitted call on the same turn (decision 21, which keeps item 16's
  protection). Without it, a reply on such a turn would be judged as ordinary: a price
  that reuses the buyer's own budget would pass R3 and a price in words would pass R2.
  `VERIFIER_VERSION` is "5".
- R1 cards: if a token fragment appears (`[[`, `]]`, `[card:`, or `card:` closed by `]`),
  the text must consist of complete `[[card:<ref>]]` tokens and whitespace only (no prose
  beside a card, no duplicate ref, no partial or re-spelled token). Bare `card:` inside
  ordinary prose ("discard:", "credit card:", "scorecard:") is not a fragment and falls
  through to R2/R3. On a turn with no admitted card call (`cardToolCalled !== true`) a
  token is withheld `card-without-trusted-call` before the resolver is asked. Otherwise
  each ref is resolved for this session and turn; a null result (the
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
from the card store, and since revision 6 only through the run-bound admission above
(owner decision 19). Because the mark lands before execution and is monotonic, a card
tool that then throws, times out or returns an error result leaves the turn marked, so
the model's digit-free apology after a failed search is withheld
`card-turn-requires-tokens`. A refused card call does not execute and never marks the turn
a card turn. When the refusal is tied to its own turn (decision 21) the turn is marked
`cardCallRefused` and every reply on it after the refusal is withheld `card-call-refused`;
a refusal of unknown origin leaves the turn ordinary, so a digit-free apology releases and
a later card token is withheld `card-without-trusted-call`. The fake host in `test-support` emulates the traced host:
it uses `replyOptions.runId` (or a test-chosen follow-up id), calls `onAgentRunStart`,
fires the hook with the traced event and context shapes, executes only when the decision
is not `block: true`, and records the order, so the tests can assert the admission
preceded execution and a refused tool never ran.

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
`card`; rule `card` needs `cardToolCalled === true`; on an unbound turn
(`runBound !== true`) or a refused turn (`cardCallRefused !== false`) no release is
well-formed at all. The gate does not re-derive the
verdict; it refuses one that does not account for itself, so a verifier bug that releases
with a missing or wrong rule, on an unbound turn, or a card without an admitted call, is
withheld.

Known withholds under this policy, by design until a token path exists: numbered lists,
"24/7", office hours, years, step numbers, superscripts and fractions (`ft²`, `½ bath`),
tool clarifications and error notices that carry figures (`isError` is not visible in
the `sendText` context), any text with a double bracket or `[card:` fragment
(`malformed-token`), on a card turn every reply that is not a resolved card token
(a follow-up question after a search, a "no results" sentence, an apology), on an
ordinary turn any card token (`card-without-trusted-call`), and on an unbound turn every
reply at all (`unbound-turn`). Number words
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
`untrusted-turn` withhold never sends, in either mode. An unbound turn (`unbound-turn`)
is an ordinary verifier withhold on a trusted handle: `SAFE_TEXT` goes out in safe-text
mode and is reported visible with the reason, nothing goes out in silent mode and the
result is `{ visibleReplySent: false, suppression: { reason } }`; the audit line carries
the reason with `boundToTurn: true`. `BUSY_TEXT` is not a withheld reply: it goes out in
both modes (owner choice, flagged).

## Residual risks
- The self-check sees the config at registration only. Removing the deny and restarting
  brings the stock plugin back; a runbook note (later PR) covers it, the host does not.
- Proactive sends are withheld in this skeleton. The message tool, cron, heartbeat and
  CLI (alert delivery included) reach `sendText` without a channel-minted handle and are
  withheld `no-turn-handle` with nothing sent, even to a peer who wrote seconds ago. They
  stay withheld until a handle-bearing path for proactive sends exists, which is a later
  owner item (WO-037 item 18, deferred by the owner on 2026-11-06). Fail closed, but
  silent toward the peer; the audit line records it.
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
- The card-tool admission depends on the install PR registering
  `createBeforeToolCallHandler` with the host's `before_tool_call` hook. Until then no card
  call is admitted, so no turn is a card turn and every card token is withheld
  `card-without-trusted-call`; greetings and user-figure echoes on bound turns release and
  invented figures are withheld by R4. The event and context shapes and the run-id flow are
  from the 2026-11-07 trace and emulated here, not exercised: the install PR captures one
  real event per `CARD_TOOLS` tool and path first.
- Pinned case left to the install PR (RI-2, decision 19 (a)): on the bundled-MCP path
  there is no requester, so a call that reuses P1's valid run id AND P1's session key while
  P1's run is active is indistinguishable offline and is admitted (it marks P1). After the
  run ends the same reuse is refused `run-ended`. The install PR's host-level test must
  show on the real dispatch path that a dashboard request cannot carry both (lane
  serialization, no steering or follow-up into the run). Otherwise the card tools move to
  a path that verifies the originating turn and peer.
- Run-end window: the run ends when the channel's `runInbound` promise settles. If the
  host can start a next run on the same session key before that promise settles, the old
  run id stays admissible until then. The host-level test must cover this ordering.
- A run that never settles keeps its peer busy (`BUSY_TEXT`) until the ingress TTL
  (30 min) expires the turn; the peer's next message after that is admitted. The same
  holds when the peer's records are evicted for capacity while the run is open (RA-6):
  the peer stays busy, the evicted turn's card calls are refused `turn-expired` and its
  replies are untrusted (nothing sent), until the run ends or the TTL passes.
- Host follow-ups and message folding from sources other than WhatsApp are not blocked by
  the busy rule; keeping them out of WhatsApp sessions is an install-PR config item (the
  queue-mode keys are untraced).
- A refused card call hands the model `blockReason` as the tool result, and the model may
  answer in prose. After a tied refusal (decision 21) every later reply on that turn is
  withheld `card-call-refused`. Replies delivered before the refusal are already out and
  are not recalled (RW-4). After a refusal of unknown origin the turn stays ordinary: its
  prose releases if digit-free and is withheld if it carries figures the user did not
  write.
- Ordinary-turn limits, pinned: a turn with no card call has no card evidence, so a reply
  quoting the buyer's own budget as a listing price releases under R3 (RW-1b), and a price
  spelled out in words releases under R2 (RW-2; number words are not figures, item 5).
- Tie rule depends on the install gate (decision 21): offline, a call that reuses a live
  WhatsApp run id and session key with a requester naming someone else is tied to that
  WhatsApp turn and withholds its reply (pinned by RI-4). The real-host replay test must
  show such a dashboard call is refused and does not withhold the WhatsApp turn; if the
  host admits it, the install moves the card tools to a path that verifies the
  originating turn and peer.
- A verifier that never returns stalls that session's serialized reply queue (the
  dispatcher awaits `deliver`); nothing is sent, but the turn is lost. A worker-thread
  verifier is the future fix.
- `channelConfigs.whatsapp.schema` is permissive because it validates the operator's
  existing `channels.whatsapp` section; the skeleton validates no channel config.
- Host behaviour (deny, first-wins registration, dispatcher outcomes) is emulated from
  cited lines in `test-support/host-emulation.mjs`, not exercised against the host.
