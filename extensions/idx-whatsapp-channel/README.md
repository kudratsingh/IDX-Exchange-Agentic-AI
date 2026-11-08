# idx-whatsapp-channel — offline Path A skeleton

A project-owned OpenClaw channel plugin that claims channel id `whatsapp` for DMs and
puts every outbound text through one verified gate. It runs on a fake transport in tests
and nothing points the host at it. Since the owned-channel install items (2026-11-07) it
also ships as a production package (`package.json`), drops senders outside the
configured allowlist, and resolves card tokens from a turn-bound card store that code
fills from the trusted card tool result of the same turn.

## What it is
- `openclaw.plugin.json`: manifest, id `idx-whatsapp-channel` (not `whatsapp`, so
  `plugins.deny: ["whatsapp"]` blocks only the stock plugin), `channels: ["whatsapp"]`,
  `channelConfigs.whatsapp.preferOver: ["whatsapp"]`, an empty strict `configSchema`.
  `channelConfigs.whatsapp.schema` (validates `channels.whatsapp`) is strict
  (`additionalProperties: false`): `enabled`, `dmPolicy` (only `"allowlist"`),
  `allowFrom` (strings), `accounts.<id>` with `enabled`, `dmPolicy` and `allowFrom`, and
  the repo baseline's `groupPolicy` (only `"disabled"`), `configWrites` (only `false`)
  and `selfChatMode` (accepted, read by no code here). An existing live section with any
  other key (a stock WhatsApp setting) fails `openclaw config validate` until it is
  removed, which the runbook does before the link install.
- `package.json` (owner item 12): `"name": "idx-whatsapp-channel"`, equal to the manifest
  id so the host has no id/name mismatch to warn about; private; `"type": "module"`; no
  dependencies and no scripts; `openclaw.extensions: ["./index.mjs"]`;
  `openclaw.compat: { pluginApi: ">=2026.9.5", minGatewayVersion: "2026.9.5" }`; a
  `files` list of the eleven runtime modules, the manifest and this README only (no
  tests, no `test-support/`, no `host-harness/`). A link install loads the directory in
  place, so `files` governs packed archives; a source test pins that the list is exactly
  the modules `index.mjs` reaches.
- `allowlist.mjs` (runbook C3): `resolveDmAccess(cfg, accountId)` and
  `senderAllowed(cfg, accountId, peerId)`, pure. The source is the config the host hands
  `startAccount` (`channels.whatsapp`; a present `accounts.<id>.dmPolicy` / `.allowFrom`
  wins and never falls back). Fail closed: no section, `enabled: false`, a `dmPolicy`
  other than exactly `"allowlist"`, and a missing, non-array, empty or malformed
  `allowFrom` (any entry that is not a phone number after `normalizePeerId`: `"*"`, a
  `@lid` id, a placeholder) each drop every inbound. Senders and entries compare in
  canonical form (`+<digits>`), so `whatsapp:+1 555 000 0001` and the
  phone-number JID form (`<digits>@s.whatsapp.net`) are the same entry; a `@lid` sender never matches. The
  channel runs the check first in `onInbound`, before the runner check, the busy check,
  the route, the record and the run: a dropped sender gets nothing (no reply, no
  `BUSY_TEXT`, no record) and leaves one audit line
  `{ event: "inbound-dropped", reason }` with no peer and no text. `startAccount` logs
  `allowlist-invalid` with the reason once when the policy drops everyone. The channel
  declares `reload: { configPrefixes: ["channels.whatsapp"] }` so an edit restarts it
  with the new list (TO-CONFIRM on the real host).
- `card-render.mjs`: `renderCards(toolName, result)`, a pure, deterministic renderer
  from a card tool's own result to `{ ref, text }` cards. It parses the result's single
  text content block (the one copy of the tool's structured result the model sees,
  ONE_COPY_TOOLS) and needs an `ok: true` envelope. One card per listing for
  `search_listings` (`data.listings`), `find_similar_listings` (`data.matches[].listing`)
  and `recommend` (`data.subject`, `data.recommendations[].listing`), and one market card
  for `get_market_stats` (without it a market turn could never release anything, since a
  card turn releases only tokens). Only the fields in `RENDERED_LISTING_FIELDS` /
  `RENDERED_MARKET_FIELDS` are read (never `remarks`, coordinates or flags); a listing
  carrying any deny-listed or agent-contact key (`FORBIDDEN_LISTING_KEYS`, pinned equal to
  `safety/columns.py` by the pytest wrapper) gets no card. Strings lose control and
  format characters and the characters markdown, links and tags are built from
  (brackets, parentheses, angle brackets, emphasis marks, backticks, pipes, braces, `#`,
  `!`); one that still looks like a link, an email or a phone number is left out. Fields and cards are length-bounded
  (`CARD_MAX_LENGTH` 700, at most 50 cards per result). The ref is the listing's
  `listing_id` as the result shows it, with characters outside `[A-Za-z0-9._-]` replaced
  by `-`, at most 64 (or `listing_key` when there is no id); a market card's ref is
  `market-<city or ZIP>`. A ref that would carry two different texts gets no card.
- Turn-bound card store (in `ingress.mjs`) and capture (`channel.mjs`).
  `createAfterToolCallHandler(ingress)` is registered with the host's `after_tool_call`
  hook (an observe hook; event `{ toolName, params, runId, toolCallId, result, error,
  durationMs }`, OpenClaw 2026.9.5 types). For a card tool with one run id on event and
  context and no `error`, it renders the result and calls `ingress.captureCards`, which
  stores the cards on the turn only when the hook handler admitted that very call: the
  run id names a stored, unexpired, confirmed turn whose run has not ended, the session
  key is the turn's, and the tool call id was recorded by `admitCardCall` for this turn
  with the same tool name (the before-hook handler now reads `event.toolCallId` and passes
  it). Each call id is captured once. At most `CARD_MAX_PER_TURN` (100) cards per turn; a
  ref captured again with a different text is poisoned. `resolveCard(ref, { sessionKey,
  turnId })` answers `{ text }` only for a card of the one stored, unexpired turn with
  that binding (two live turns sharing it: null); cards are evicted and expire with their
  turn. `card-resolver.mjs`: `createTurnCardResolver(ingress)` over that store, which
  `index.mjs` uses by default (the harness and tests may inject their own);
  `nullCardResolver` stays for tests. The verifier's rules are unchanged: a card token
  still needs an admitted call on its own turn (R1) and a card turn still releases only
  tokens (R1b).
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
  case and padding included. `index.mjs` registers it with `api.on("before_tool_call")`
  (real-host replay PR).
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
- `verifier.mjs`: pure, synchronous policy (below). `card-resolver.mjs`: the turn-bound
  resolver and the null resolver (above). `ingress.mjs`: bounded, expiring records (the
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
- Not installed, enabled, linked or configured. No dependency, no network, no
  credentials, no auth directory, no QR flow. On OpenClaw 2026.9.5 a plugin named only in
  `plugins.load.paths` has no install record and the gateway never starts it; a link
  install needs the `package.json` (owner item 12, now present) and
  `--accept-capabilities` (real-host harness, 2026-11-07). The self-check and `isConfigured: false` are the actual
  guards, and an accidentally loaded skeleton can neither start an account nor send.
- Not a Baileys or Cloud API transport. Transport and credential choices are deferred;
  `Transport` (`start`, `sendText`, `stop`, `isConfigured`) is the seam.
- Wired to the host since 2026-11-07 (`index.mjs`, `createHostRunner`): route resolution
  through `api.runtime.channel.routing.resolveAgentRoute`, the inbound context through
  `finalizeInboundContext`, and dispatch through `dispatchReplyWithBufferedBlockDispatcher`
  with the channel's own `deliver` and `replyOptions`. The `before_tool_call` handler is
  registered with no matcher, before the channel, and so is the `after_tool_call` capture
  handler. One frozen ingress per process
  (`processIngress`) is shared by every loaded copy of the module, because the host
  registers the plugin from several copies and keeps every copy's hook. A host runtime
  without `api.on` makes registration refuse. Without a runtime the entry still passes no
  runner and an inbound is dropped with a warning.
- `host-harness/`: test-only real-host replay harness (see its README). Never linked or
  installed; the live link targets this directory's root only.

## Run the tests
```
node --test extensions/idx-whatsapp-channel/verifier.test.mjs \
            extensions/idx-whatsapp-channel/channel.test.mjs \
            extensions/idx-whatsapp-channel/host.test.mjs \
            extensions/idx-whatsapp-channel/entry.test.mjs \
            extensions/idx-whatsapp-channel/allowlist.test.mjs \
            extensions/idx-whatsapp-channel/cards.test.mjs
.venv/bin/python -m pytest -q tests/test_whatsapp_channel_skeleton.py
```
The pytest wrapper skips (with a reason, visible under `-rs`) when `node` is missing or
older than 20. The CI workflow has no Node setup step, so whether the Node tests run in
CI depends on the runner image shipping Node 20+; the workflow is not edited on this
branch (gates consent), so this is contingent, not guaranteed. Locally with Node present
the wrapper's five tests pass (manifest, package shape, the renderer's lists pinned to
the Python server, the Node suite, the harness syntax check).

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
both modes (approved 2026-11-07, item 20).

## Residual risks
- Operator cancellation, an availability risk (WO-037 item 22, decided 2026-11-07). Any
  client with `operator.write` can cancel a live WhatsApp reply (`chat.send` with
  `queueMode: "interrupt"`, `chat.abort`, `sessions.abort`), and on default settings every
  dashboard user gets admin. No tool path prevents it. The host-level control, proven on
  the real host: identity-authenticated dashboard users under `gateway.roles` with
  `sessions.others: "none"` and no admin are refused on WhatsApp sessions. Shared-token,
  password and admin holders bypass roles, so that credential stays with the owner. No
  client can make a card tool run by replaying a live run id and session key.
- Process-wide ingress: any code in the gateway process can reach it through its
  well-known key and call its methods (mint and confirm a run of its own, then have the
  hook admit card calls for it). Same trust boundary as other in-process plugin code.
- The allow-list self-check form relies on the host not adding "whatsapp" to an allow
  list by itself (channel auto-enable); unconfirmed on 2026.9.5. The install asserts that no
  other plugin claims channel `whatsapp` (runbook C4).
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
- The card-tool admission and the run-id flow were exercised on the real host by the
  replay harness (2026-11-07); the `after_tool_call` capture was not. From the 2026.9.5
  types and docs only: `after_tool_call` is an observe hook whose emitter "may await
  completion or dispatch fire-and-forget", so whether it fires on the bundled-MCP path,
  whether its `toolCallId` equals the before-hook's, whether `result` is the
  `{ content: [{ type: "text", text }] }` shape the renderer parses, and whether it runs
  before the model's next step are all untraced. Each failure direction is a withhold:
  no capture, so the token is `unknown-token` and the peer gets `SAFE_TEXT` (or silence).
  The install gate must show one real capture per `CARD_TOOLS` tool on the WhatsApp path
  (formats only).
- Card refs come from the listing id the model saw. A model that copies an id wrongly,
  or writes a ref from an earlier turn or another peer, gets nothing released. A
  clarification on a card turn (the tool asked for a city) is still withheld, because a
  card turn releases only tokens (R1b) and a clarification has no card.
- The market card renders the server's aggregate figures with fixed wording of its own
  (window, sample count, medians, sale-to-list, a fixed low-sample line); it does not
  reuse the server's `message` text. Owner to confirm the market card and its wording.
- The allowlist is read from the config `startAccount` received. A live edit takes
  effect only if the host restarts the channel on a `channels.whatsapp` change, which
  `reload.configPrefixes` asks for but which is untraced on 2026.9.5. A linked-id
  (`@lid`) sender is dropped even when it is the owner, until the transport PR maps it.
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
  show that a dashboard request replaying both live WhatsApp IDs can neither run the card
  tool nor suppress the WhatsApp reply; installation stays paused until it does, and if
  either check fails the install moves the card tools to a path that verifies the
  originating turn and peer. The owner accepted this tie rule on 2026-11-07 for the
  offline prototype only.
- A verifier that never returns stalls that session's serialized reply queue (the
  dispatcher awaits `deliver`); nothing is sent, but the turn is lost. A worker-thread
  verifier is the future fix.
- `channelConfigs.whatsapp.schema` is strict. The merge of two manifests' schemas for one
  channel id (ours and a stock plugin's, if one is ever installed) is untraced; the
  runtime allowlist check does not depend on the schema.
- Host behaviour (deny, first-wins registration, dispatcher outcomes) is emulated from
  cited lines in `test-support/host-emulation.mjs`, not exercised against the host.
