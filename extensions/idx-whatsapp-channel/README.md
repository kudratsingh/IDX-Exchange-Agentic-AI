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
  message is verified against the message it answers. The host runner receives the turn
  id as a string (metadata), `deliver`, and `noteToolCall(toolName)`, which marks the
  turn as a card turn through the closure; it never receives the handle, so nothing on
  the runner's side can bind a send to a turn. A `deliver` that sent `SAFE_TEXT` returns
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
  `untrusted-turn` as well: naming a turn by id proves nothing. Only a context with
  neither binds to the peer's newest turn (tool, cron, heartbeat, CLI). Every context
  field is read exactly once, up front: `to` must be a non-empty string (anything else is
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
  newest four turns per peer) and peer id canonicalisation (`whatsapp:` prefix and the
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
  `recommend`) and `isCardTool`.
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

The card-tool mark is the `noteToolCall(toolName)` seam on the turn object the channel
hands `runInbound`; it calls `ingress.markCardTool` with the turn's own handle. The
install PR wires it to the host's tool-call observation. The stock hooks available to a
plugin are observation-only here: they cannot stop a tool call, and the mark cannot
either; it only tightens the verifier for that turn. A missed mark leaves the turn on the
ordinary rules, which is the residual risk: whether the hook or the card store is the
source of the mark is owner decision 16 in WO-037. `markCardToolForSession` exists so a
source that knows only the session key can mark every open turn of it (over-marking is
the safe direction).

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
`WITHHOLD_MODE = "safe-text"`: when the peer has a current inbound record, a withheld
reply becomes the single constant `SAFE_TEXT` ("I couldn't send that reply safely.
Please ask again."). When no record exists (an unsolicited tool, cron or heartbeat send
to a peer who has not written), the result is `{ outcome: "not_sent" }` and nothing goes
out. `"silent"` everywhere is one constant away. The inbound `deliver` reports a withhold that
sent nothing to the dispatcher as `{ visibleReplySent: false, suppression: { reason } }`
so the host records it as not visible rather than as a delivered reply; a withhold that
sent `SAFE_TEXT` is reported visible (a message did go out, and a not-visible result would
make the dispatcher retry its fallback after it) with the reason in `withheld.reason`. An
`untrusted-turn` withhold never sends, in either mode.

## Residual risks
- The self-check sees the config at registration only. Removing the deny and restarting
  brings the stock plugin back; a runbook note (later PR) covers it, the host does not.
- Ingress records live in process memory. A send from another process (CLI) or after a
  restart finds no record and is withheld; a late reply (TTL 30 min) is withheld. Fail
  closed, but silent. `deliveryMode: "gateway"` keeps CLI sends in the gateway process.
- The newest four turns per peer are kept. A reply still in flight when the peer has
  since written four or more messages finds its handle no longer trusted and is withheld
  `untrusted-turn` (nothing sent, reported as not visible). A tool, cron or heartbeat
  send always binds to the newest turn, so a tool clarification echoing an older
  message's figures is withheld; a caller that tries to name the older turn by id is
  withheld `untrusted-turn` instead of being allowed through.
- The transport receives the canonical peer id the record was checked under
  (`+<digits>`, `<digits>@lid`, or a lowercased other id), not the caller's spelling. The
  transport PR owns the mapping from that id to its own address format; until it lands,
  whether a `@lid` address reaches the same person as the phone-number peer is unknown,
  which is why the skeleton keeps them apart rather than folding them together.
- The card-tool mark depends on the install PR wiring `noteToolCall` (or
  `markCardToolForSession`) to a source that sees every card tool call. Until then, and
  whenever that source misses a call, the turn is verified under the ordinary rules
  (greetings and user-figure echoes release; invented figures are still withheld by
  R4). Marking is monotonic and only tightens; it can never loosen a turn.
- A verifier that never returns stalls that session's serialized reply queue (the
  dispatcher awaits `deliver`); nothing is sent, but the turn is lost. A worker-thread
  verifier is the future fix.
- `channelConfigs.whatsapp.schema` is permissive because it validates the operator's
  existing `channels.whatsapp` section; the skeleton validates no channel config.
- Host behaviour (deny, first-wins registration, dispatcher outcomes) is emulated from
  cited lines in `test-support/host-emulation.mjs`, not exercised against the host.
