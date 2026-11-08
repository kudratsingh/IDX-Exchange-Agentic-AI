# WO-037 — Offline Path A skeleton: project-owned WhatsApp channel on a fake transport

**Driver:** agent (skeleton, tests, docs); owner (the pending decisions below, the later
install PR)
**Depends on:** the owner's Path A instruction of 2026-11-06; the read-only OpenClaw
2026.9.5 survey recorded in `docs/EVIDENCE_LOG.md` (2026-11-06, WO-037)
**Estimated effort:** 6 hours (agent)

## Objective
A channel plugin skeleton under `extensions/idx-whatsapp-channel/` that claims channel
id `whatsapp` for DMs and makes the reply verifier the only way text reaches the
transport, proven offline on a fake transport. Nothing is installed, enabled, linked or
configured; transport and credentials are deferred.

## Why
The hooks available to a plugin (`reply_payload_sending`, `message_sending`,
`before_agent_run`) fail open and cannot stop a delivery. The one awaited boundary a
plugin owns is its channel's `deliver`/`sendText`. Phase 1 session r6 (EVIDENCE_LOG,
2026-11-06) stopped on a relay defect where the model replaced one card's year with
another's; a verifier at the send boundary is the only place code can refuse that.

## Relationship to WO-036 / #179 (on hold)
WO-036 (`wo-036-card-relay-prototype`, PR #179) is the card-relay token-check prototype
and its feasibility check. It stays on hold and this work does not touch its branch. The
owner's instruction chose its "Path A" option: an owned WhatsApp send path, the stock
`@openclaw/whatsapp` plugin blocked by `plugins.deny: ["whatsapp"]`, our manifest
preferring over it, and the verifier run inside our channel's send. This work order
restates what it needs from that option and does not depend on the branch-only WO-036
text or ADR-0015. When #179's token check lands it plugs into `CardResolver`.

## Inputs
- Read-only: OpenClaw 2026.9.5 at `~/.npm-global/lib/node_modules/openclaw` and the
  stock plugin under `~/.openclaw/npm/projects/openclaw-whatsapp-290d7f7427`. Cited by
  file, line and sha256-12 in the EVIDENCE_LOG entry; never vendored.
- `extensions/idx-card-relay/` (WO-019 spike) and `tests/test_card_relay_spike.py` as
  the pattern for an offline Node extension with a pytest wrapper.

## In scope
1. The extension directory: manifest, entry with startup self-check, channel object,
   ingress, outbound gate, verifier, resolver and transport seams, constants, README.
2. Test support (fake transport, in-memory card resolver, host emulation written from
   cited lines) and three `node --test` files, wrapped by
   `tests/test_whatsapp_channel_skeleton.py`.
3. This work order, ADR-0016 (proposed), one EVIDENCE_LOG entry.

## Out of scope
- Installing, enabling, configuring or restarting anything; editing `~/.openclaw`;
  linking a device; any send; any paid call.
- A real transport (Baileys, Cloud API) and credentials. Groups, media, polls,
  reactions, typing, read receipts, QR login, auth state.
- Wiring `resolveRoute`/`runInbound` to `api.runtime.channel.*`; DM policy, allowlists,
  pairing; `messaging.normalizeTarget`; a chunker. All install-PR items.
- Any change to PR #179's branch, to `scripts/gates`, `scripts/guards`, `.claude/`,
  `.github/`, `.gitignore`.

## Interfaces
All in `extensions/idx-whatsapp-channel/`, plain ESM with JSDoc, Node built-ins only.
- `verifyReply({ text, inbound, resolver }) -> Verdict`;
  `isWellFormedVerdict(value, inputText, inbound)` (no release is well-formed unless
  `runBound === true`; rule `card` requires `cardToolCalled === true`, and a card turn
  accepts only rule `card`; revision 7: no release is well-formed unless
  `cardCallRefused === false`); `digitRuns(text)`; `isInboundRecord` (requires a boolean
  `cardToolCalled`, a boolean `runBound` and, since revision 7, a boolean
  `cardCallRefused`); `VERIFIER_VERSION = "5"`. Rule R0b withholds everything on an
  unbound turn as `unbound-turn`, before R1; R1 withholds a card token on a turn with no
  admitted card call as `card-without-trusted-call`, before the resolver is asked
  (revision 6, owner decision 19 (c)). Rule R0c, right after R0b and before R1, withholds
  everything on a turn whose own card call was refused tied as `card-call-refused`, card
  tokens included (revision 7, owner decision 21).
- `CardResolver.resolve(ref, { sessionKey, turnId }) -> { text } | null`; `nullCardResolver`.
- `Transport`: `start`, `sendText`, `stop`, `isConfigured`; `unavailableTransport`.
- `createIngress({ now, ttlMs, maxEntries, turnsPerPeer })`: `key`,
  `record(key, rec, run?) -> TurnHandle | null` (frozen `{ turnId, key }`, identity mapped
  to its entry by an instance-private WeakMap; `run = { runId, accountId, peerId }` stores
  the run id privately with the entry, one run id to one entry; a duplicate or non-string
  run id, or an account and peer that do not give `key`, is refused with `null`),
  `forTurn(key, handle)` (trusted handle only; a string or look-alike object yields
  null; the only record read, there is no `current` or any lookup by key alone),
  `confirmRun(handle, runId) -> boolean` (sets `runBound` only for exactly the issued id on
  a stored, unexpired turn whose run has not ended; monotonic), `endRun(handle) -> boolean`
  (idempotent; the run id admits no further card call and the turn stops being active),
  `hasActiveTurn(key) -> boolean` (a recorded, unexpired turn whose run has not ended;
  kept in an active index apart from the record store, so capacity eviction never ends an
  active turn),
  `admitCardCall({ runId, sessionKey, toolName, requesterMatches }) -> { admitted: true } |
  { admitted: false, reason } | { admitted: false, reason, withheld: true }` (the only
  marking path; marks that one turn; revision 7: a refusal reached after the session-key
  check, today only `requester-mismatch`, is tied to the entry the run id names, sets
  that entry's `cardCallRefused` and answers `withheld: true`; every earlier refusal is of
  unknown origin, answers without a `withheld` key and changes nothing), `size`;
  `normalizePeerId(to)`
  (`whatsapp:` prefix and the phone-number JID suffixes fold to `+<digits>`; `@lid` stays
  `<digits>@lid`, a separate namespace; canonical ids are fixed points). The handle maps,
  by identity, to the one stored entry it was minted for, so two records with the same
  turn id are two turns with two handles. Records (snapshots) carry `sessionKey`,
  `turnId`, `text`, `receivedAt`, `cardToolCalled`, `runBound` and (revision 7)
  `cardCallRefused`; all three flags are false at record time, monotonic and never
  inherited by a later turn; the run id is never in a snapshot. `markCardTool`, `markCardToolForSession`, `blockTurn`, `blockOpenTurns` and
  `toolCallBlocked` are removed (revision 6).
  Turn ids and run ids are channel-generated (`randomUUID`); the peer's message id reaches
  `runInbound` as `messageId` metadata only.
- `constants.mjs`: `CARD_TOOLS` (mirrors the server's one-copy tools, spelled as the
  server names them) and `isCardTool(name)`, which fails closed on spelling: the exact
  name, or any name whose trimmed, lowercased last segment after a namespace separator
  (`__`, `.`, `/`, `:`) is a `CARD_TOOLS` name (the host's `idx__search_listings`,
  ADR-0003), with or without the host's `-N` collision suffix (`idx__search_listings-2`),
  is a card tool; a name that differs otherwise is not.
- `createOutbound({ transport, ingress, verify, cardResolver, clock, deadlineMs, withholdMode, log, receiveBusySender })`
  -> `{ deliveryMode: "gateway", textChunkLimit: 4000, normalizePayload, sendText }`
  (these four keys only). `receiveBusySender(fn)` is called once at construction with the
  private busy sender, which sends the `BUSY_TEXT` constant and nothing else through the
  same private `transmit` (the one `transport.sendText(` call site); it is not on the
  returned object.
  `sendText(ctx)` binds only through `ctx.turn` (a TurnHandle): any `turnId` is withheld
  `untrusted-turn`; no `turn` at all is withheld `no-turn-handle`; a handle `forTurn`
  does not recognise is `untrusted-turn`. Each of these sends nothing (no `SAFE_TEXT`)
  and audits `hasRecord: false, boundToTurn: false`. There is no other binding path and
  no fallback to the peer's newest turn (decision 17). Each context field is read once, up front;
  `to` must be a non-empty string (else `bad-destination`, nothing sent) and the
  transport receives the canonical peer id the record was looked up under, never
  `ctx.to`. A `SAFE_TEXT` send returns `{ messageId, withheld: reason }`.
- The turn object passed to `runInbound` carries `cfg`, `sessionKey`, `accountId`,
  `peerId`, `text`, `turnId` (string), `messageId`, `deliver` and
  `replyOptions: { runId, onAgentRunStart }`; never the handle, and no per-turn tool seam
  (`beforeToolCall` is removed in revision 6). `onAgentRunStart(id, ...)` confirms the run
  only for exactly the issued `runId` while the turn is stored, unexpired and its run not
  ended; it returns `undefined` for every argument (the string `"reply-dispatch"` would
  take over completion ownership, host trace 2026-11-07) and never throws. The run ends in
  a `finally` when the `runInbound` promise settles, resolved or rejected.
- One active turn per peer: an inbound for a peer key with an active turn is not
  recorded, not routed and not run (no `resolveRoute`, no `runInbound`), its text is not
  stored or logged, and the peer gets `BUSY_TEXT` (both withhold modes); the audit line is
  `outcome: "busy"` with no text and no peer.
- `createBeforeToolCallHandler(ingress) -> (event, ctx) => ToolCallDecision`: the
  function the install PR registers with the host's `before_tool_call` hook (fires before
  execution), and the single admission path. It reads `event.toolName` first, then, for a
  card tool only, `event.runId`, `ctx.runId`, `ctx.sessionKey` and `ctx.requester`, each
  once. A non-card tool is `{ block: false, marked: 0 }` with no other field read and no
  state touched. A card tool is admitted, `{ block: false, marked: 1 }` with that one turn
  marked, only when `event.runId` is a non-empty string equal to `ctx.runId` naming a
  stored, unexpired turn whose run is confirmed and not ended, `ctx.sessionKey` equals the
  turn's stored key, and a present `requester` is a plain object whose trimmed, lowercased
  `channel` is `whatsapp`, whose non-empty string `senderId` normalises to the turn's peer
  and whose `accountId`, if a string, is the turn's. A missing requester (bundled MCP) is
  admitted on run id and session key alone (decision 19 (a)). Anything else refuses the
  call, `{ block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason, withheld: 0 | 1 }`;
  codes `unknown-run`, `run-unconfirmed`, `run-ended`, `turn-expired` (also an
  evicted turn), `session-mismatch`, `requester-mismatch`, `handler-error` (non-string
  tool name, any throw, or an ingress answer outside the codes). `withheld` is 1 only
  when the ingress answered `withheld === true` (a tied refusal, revision 7), and 0 for
  every other refusal, including `handler-error` and the handler-side `unknown-run` (run
  id missing, or `event.runId` and `ctx.runId` differ), which change no turn. The host
  reads only `block`, `blockReason`, `params` and `requireApproval`, so `reason` and
  `withheld` stay internal. Never throws, never returns a bare value; no `tainted` field. Not registered by `index.mjs` (install-PR item).
- `constants.mjs` adds `BUSY_TEXT` and `CARD_TOOL_BLOCK_REASON`, both fixed and digit-free.
- `selfCheck(cfg) -> { ok: true } | { ok: false, reason }` (`busy-text-invalid` when
  `BUSY_TEXT` carries a digit, is empty or over 200 characters, or equals `SAFE_TEXT`);
  `SELF_TEST_VECTORS` (an unbound greeting, a token on a non-card turn and an unbound
  card token all withhold; revision 7 adds a refused-turn greeting, a refused-turn
  listing claim reusing the buyer's budget, a refused card turn's resolving token and a
  record without `cardCallRefused`, all withheld, and every other vector's record carries
  `cardCallRefused: false`).
- `createChannelPlugin(deps)` -> the channel object; `index.mjs` default export with
  `register(api)`.

## Safety requirements
- Verification failure never sends raw model text and never falls back to the stock
  plugin: a throw, a late verdict, a malformed verdict, a non-text payload, an unknown or
  stale card token, or no inbound record all withhold.
- Exactly one `transport.sendText(` call expression in the runtime, after the seal.
- A send binds to a turn only through the trusted handle the ingress minted for it; a
  turn id string, a structurally identical object, another peer's handle or an expired
  or evicted one withholds `untrusted-turn` and sends nothing. The host runner never
  holds the handle.
- No send without a channel-minted handle: a context with no `turn` is withheld
  `no-turn-handle` and sends nothing in either mode, even when the peer has a fresh
  record. Proactive sends (tool, cron, heartbeat, CLI, alert delivery) are therefore
  withheld until a handle-bearing path exists (item 18).
- The card-turn mark is applied from the host's trusted before-tool-call event, before
  the tool executes, so a card tool that fails still leaves the turn marked; the model
  and the card store are never the source of the mark. The tool name is matched in the
  host's spelling as well as the server's (`isCardTool`), so a namespace prefix, case,
  padding or the host's `-N` collision suffix cannot skip admission; over-marking is the
  accepted direction.
- One active turn per peer holds across capacity eviction: a peer whose records are
  evicted while its run is open stays busy until the run ends or the TTL passes.
- A turn that called a card tool (`cardToolCalled`) releases only fully resolved card
  tokens; the flag is monotonic and no API clears it. Ordinary turns keep greetings and
  clarifications.
- Run binding (decision 19): a card tool executes only when its call names, by the run id
  the channel issued and the host confirmed at run start, a stored, unexpired turn whose
  run has not ended, with that turn's session key and (when present) a requester naming
  that turn's peer. A failing call is refused and never marks a card turn, and no other
  turn is touched. A session key alone never admits a call and never suppresses a turn.
- Tied refusals (decision 21, revision 7): a refused card call is tied to a turn only when
  every run-binding check admission uses passed for that turn (run id equal on event and
  context, naming a stored, unexpired entry whose run is confirmed and not ended, and the
  context's session key equal to that entry's). A tied refusal marks that turn alone
  `cardCallRefused` (monotonic, never cleared or inherited), and every reply delivered on
  it afterwards is withheld `card-call-refused`, `SAFE_TEXT` or silence by mode, card
  tokens included. A refusal of unknown origin (`unknown-run`, `turn-expired`, `run-ended`,
  `run-unconfirmed`, `session-mismatch`, `handler-error`) refuses the call only and
  changes no turn.
- Release support (decision 19 (c)): a reply is released only on a turn whose run was
  confirmed (`runBound`) and, since revision 7, whose own card call was not refused tied
  (`cardCallRefused === false`); a card token only on a turn with an admitted card call
  (`cardToolCalled`). An unbound or refused turn withholds everything, greetings
  included.
- One active turn per peer (decision 19 (b)): an overlapping inbound never reaches the
  host and gets the fixed `BUSY_TEXT`, through the one call site; no follow-up or steering
  reaches an active WhatsApp run from WhatsApp.
- The gate accepts only complete, self-consistent release verdicts (one of the three
  rules, `viaCard` matching the rule, no `reason`, text consistent with the rule and the
  record); anything else is `verifier-malformed` and withheld.
- The destination is read once and the peer the verifier checked is the peer the
  transport is given: a non-string or changing `to` is refused, and a linked-id address
  never binds to the phone-number peer's record.
- The plugin refuses to register unless the host config denies `whatsapp`.
- No text, peer id or session key in logs. Synthetic data only in tests (555 numbers).
- No new dependency; no vendor source in the repo.

## Tests required
`verifier.test.mjs` (policy and card vectors, well-formedness), `channel.test.mjs`
(fail-closed gate behaviour, payload normalization, ingress, self-check, register modes,
default transport, end to end on the fake transport, the decision 16 and 17
regressions), `host.test.mjs` (source tests:
static import, single call site, allowed transport members, no default export outside
`index.mjs`; a Proxy transport; the missing-verifier and bad-verifier module tests in a
temp copy; the emulated deny/first-wins, dispatcher and registry checks; the same
outbound for tool, cron and heartbeat shapes). Turn-binding revision: Rule 1 (a bare
`turnId` naming the real earlier turn is untrusted after a newer message; a forged
structurally equal handle; the real handle with another peer's address; the real handle
still releasing after the peer's next message; the `runInbound` turn object exposing no
value the ingress trusts; a send with neither `turn` nor `turnId` withheld
`no-turn-handle`), Rule 2 (end to end:
`beforeToolCall("search_listings")` then prose -> `SAFE_TEXT` with reason
`card-turn-requires-tokens`, then a resolving token -> card bytes; ordinary greeting and
user-figure clarification unchanged; a non-card tool name leaves the flag false;
monotonic flag; `markCardToolForSession` counts; verifier vectors for R0, R1 before R1b,
R1b and ordinary release), Rule 3 (`isWellFormedVerdict` and gate-level cases for every
incomplete or inconsistent release and withhold, with positive controls for the three
rules). Review fixes of the revision: a `to` getter that changes between reads is
delivered to the peer the verifier checked, never the second value, and every non-string
destination is `bad-destination` with nothing sent (behavioural and source tests; the
source test pins the seven context reads and `to: peer` at the call site); a `@lid`
address finds no record under the `+<digits>` peer; two records with the same turn id keep
separate handles, records and marks, and the gate withholds prose bound by the marked
one. Decisions 16 and 17: a source test that `outbound.mjs` never calls `.current(`,
`ingress.mjs` defines no `current(` and the string `no-turn-handle` appears in the gate;
the tool, cron and heartbeat shapes all withheld `no-turn-handle` with the transport
untouched while the channel's `deliver` releases; the required regression (a peer wrote
seconds ago, a digit-free greeting and a user-figure echo without a handle are `not_sent`
`no-turn-handle` in both withhold modes, and the same turn's `deliver` releases them);
the fake host firing `beforeToolCall` before a card tool that throws or returns an
error-shaped result, the apology withheld `card-turn-requires-tokens` and the event order
recorded; `createBeforeToolCallHandler` marking every open turn of a session, returning
0 for non-card tools, missing session keys, garbage and arguments whose property read
throws, without throwing; a pre-execution mark surviving a later record for the same
peer; an ordinary turn with a failing non-card tool releasing its apology; the host's own
tool-name spellings (`idx__search_listings`, `mcp__idx__search_listings`, dotted, cased,
padded) marking through both seams with the apology withheld, and look-alike names
(`idx__get_listing_details`, `search_listings_v2`) leaving the turn ordinary; the
`isCardTool` table in `verifier.test.mjs`. Canonical destination: a handle-bearing send
spelled `whatsapp:+<digits>`, `<digits>@s.whatsapp.net` or `<digits>@c.us` reaches the
transport as `+<digits>` (gate test and host-shape test; a gate that forwarded the raw
destination fails both). Blocking mark (owner instruction 2026-11-06, `BM-*` in
`channel.test.mjs` and `R0b` in `verifier.test.mjs`): a mismatched session key (the right
peer under an `agent:other:` prefix) blocks `search_listings` with
`{ block: true, reason: "no-turn-for-session", tainted: 1 }`, the fake host records
`tool-blocked:no-turn-for-session` and never `tool-executed`, the apology is withheld
`blocked-tool-call` (`SAFE_TEXT` in safe-text mode, nothing and `visibleReplySent: false`
in silent mode) and so is a later resolving token on that turn, while the matching key is
`{ block: false, marked: 1 }` with the tool run and the token released; handler errors (a
`sessionKey` getter that throws, an ingress wrapper whose `markCardToolForSession`
throws, an event without a string tool name, the per-turn seam with a throwing
`markCardTool`, an evicted turn giving `mark-failed`, a turn past the ingress TTL giving
`mark-failed` with `tainted: 0`, no execution and the reply withheld `untrusted-turn`,
while `forTurn`, `markCardTool`, `blockTurn` and `markCardToolForSession` all refuse the
expired handle) each block and taint; a session key that matches another peer's open turn
is pinned as accepted (`{ block: false, marked: 1 }`, the other turn marked, the calling
turn unmarked, no card bytes crossing peers), a known cost listed under Limitations; taint is
monotonic and not inherited and no member matches `/unblock|untaint|clear|reset/i`; a
non-card tool under a mismatched session is `{ block: false, marked: 0 }` and its reply
releases; a blocked turn withholds a resolving token at the gate in both modes and a
verifier that ignores the taint fails the self-test; verifier vectors for the missing
flag, R0b before R1 and `isWellFormedVerdict` on a blocked record; a decision-shape table
over garbage inputs (null, 7, "", [], a throwing Proxy, a revoked Proxy) for both seams;
the fake host treats a non-decision return as a `bad-decision` block; a card tool from a
session with no WhatsApp turn blocks and taints the open WhatsApp turn while a non-card
tool from it does not, and a later turn releases (BM-10, item 19).
Revision 6 (owner decision 19, 2026-11-07; the text above records the earlier revisions,
and the tests named below supersede it where they differ). New in `channel.test.mjs`:
RB-1 (P1's run id and key on the MCP path admitted, P1 marked only, its token reply
releases, P2 unchanged), RB-2 (a padded, cased `WhatsApp ` requester with P1 in a JID or
spaced spelling and the right account admitted), RB-3 (twenty refusal cases on a live run,
each with its code, plus run ended, run unconfirmed, a host-minted follow-up id and a turn
past the TTL; nothing executes, neither record changes), RB-4 (an unconfirmed turn
withholds a greeting `unbound-turn` in both modes and its card calls are refused), RB-5
(`onAgentRunStart` returns `undefined` and never throws for any argument; only the issued
id confirms, a later wrong id does not unconfirm, an ended run cannot be confirmed), RI-1
(four dashboard card calls refused in both modes, nothing executed, P1 and P2 unchanged,
greetings release, P1's own card call still admitted), RI-2 (the case left to the host-level
test: P1's run id and key reused while P1 is active is admitted; after the run ends it is
`run-ended`), RI-3 (a non-card dashboard tool allowed, nothing changed), RS-1 (a resolvable
token on a bound turn with no admitted call is `card-without-trusted-call` in both modes;
verifiers that ignore either flag fail the self-test), RA-1..4 (busy reply, per peer,
rejecting runner and TTL backstop, BUSY_TEXT constraints and no busy member on the
host-facing outbound), RA-5 (two same-peer inbounds started in the same tick admit one
turn and send one `BUSY_TEXT`, in both modes), RA-6 (a peer evicted for capacity while
its run is open still gets `BUSY_TEXT` and no second run), and an ingress run-binding unit
test (now also: eviction leaves the turn active until `endRun` or the TTL). RI-2 and
RI-3 run in both withhold modes with P1 and P2 active; RB-3's array requester carries
every expected field, so only the array guard refuses it; D16 (f) and the `isCardTool`
table cover the `-N` collision suffix and 64-character names. `verifier.test.mjs`: R0 for
`runBound`, R0b `unbound-turn`, R0b before R1, RS-1 (verifier) and RS-2
(`isWellFormedVerdict`). `host.test.mjs`: D19 (source: no `markCardToolForSession`,
`blockOpenTurns`, `toolCallBlocked`, `blockTurn`, `markCardTool`, `blocked-tool-call` or
`beforeToolCall` in any runtime file; the run id minted with `randomUUID`, passed as
`replyOptions: { runId, onAgentRunStart }`, confirmed only on an exact match, the callback
returning `undefined`, `endRun` in a `finally`; `admitCardCall` called only by the hook
handler; `sendBusy` called once, behind `hasActiveTurn`); the single-call-site test now
counts four `seal(` (definition, release, safe-text, busy) and pins `seal(BUSY_TEXT)` once.

Retired or rewritten in revision 6, and why:
- BM-9 (cross-peer session key accepted as a mark) retired: its pinned behaviour is the
  gap decision 19 closes. Its intent is now RB-3 ("key = P2's" refused) and RI-1.
- BM-10 (a dashboard card call taints every open WhatsApp turn) retired: the global taint
  is removed. Its intent (a dashboard card call does not run) is RI-1, and the opposite of
  its collateral (WhatsApp turns unchanged) is asserted there.
- BM-3 (taint monotonic) and BM-5 (gate withholds on a tainted turn) retired with
  `toolCallBlocked`. Monotonic flags stay pinned by the ingress tests (`cardToolCalled`,
  `runBound`), and the "withhold everything" rule now belongs to R0b `unbound-turn`
  (verifier tests, RB-4, self-check vectors).
- BM-2 (per-turn seam) and the per-turn parts of BM-7, BM-8 and R2 retired with
  `beforeToolCall`. BM-1, BM-2 (hook), BM-7 and BM-8 are rewritten against the run-id
  handler. They keep: a refused card call does not execute; handler errors refuse; the
  decision shape is never a bare value; an expired turn admits nothing. They no longer
  expect a taint: a refused call leaves its turn ordinary, so a digit-free apology
  releases and a later token is `card-without-trusted-call`.
- D16 (c) and the hook half of D16 (f) rewritten from session-keyed marking to per-run
  admission. D16 (a), (b), (d), (e) are unchanged in intent: the mark lands before
  execution, a failed card call still counts as a card turn, a non-card tool never blocks.
- The ingress `markCardToolForSession` count test retired. The `markCardTool` assertions in
  the ingress tests now go through `admitCardCall`.
- The fake-host "bad-decision" table rewritten: the traced host allows on a null,
  undefined or malformed return, so the emulation now does too and blocks only on
  `block === true` or a throw. The runtime handler never returns anything else.
- Every gate or channel test that expects a release now records its turn with a confirmed
  run (`recordBoundTurn` in test-support, or a runner calling `onAgentRunStart`), and every
  card-token release first admits a card call. The end-to-end and turn-id tests reach their
  cards through an admitted `search_listings` call.

Revision 7 (owner decision 21, 2026-11-07). Host-level tests run in both withhold modes
unless noted.
- RW-1 (buyer budget reused as a listing price). The inbound is "My budget is 650000 for a
  3 bed in Irvine". The turn's own `idx__search_listings` call carries the turn's run id
  and session key and a WhatsApp requester naming another 555 sender, so it is refused
  tied. The model's "Good news: a 3 bed in Irvine is listed at 650000." never reaches the
  transport: safe-text mode sends exactly `SAFE_TEXT` once, silent mode sends nothing,
  and deliver reports `idx-withheld:card-call-refused`. The decision is
  `{ block: true, blockReason, reason: "requester-mismatch", withheld: 1 }` and the tool
  did not execute. Controls, each named:
  - RW-1b: the same reply on an ordinary turn with no card call releases under R3, a
    known limit.
  - RW-1c: after an unknown-origin refusal the turn's reply releases. The refusals are
    dashboard-style calls with this turn's session key and no run id, or a foreign run id,
    with or without a mismatching requester; each is `unknown-run` with `withheld: 0`.
  - RW-1d: after an admitted card call the same prose is withheld
    `card-turn-requires-tokens`.
- RW-2 (spelled-out listing claim). "I found a three-bedroom home on Maple Street listed
  at six hundred fifty thousand dollars." after a tied refusal is withheld
  `card-call-refused`. On an ordinary turn the same text releases, a pinned known limit.
  The verifier units show the same split: `card-call-refused` on a refused record, and
  `no-figures` on an ordinary one (item 5, number words).
- RW-3 (an unrelated WhatsApp reply still delivers). P1 and P2 are open at once. P1's
  call carries P1's run id and key and a requester naming P2, so it is refused tied and
  P1's reply is withheld. P2 stays untouched:
  - P2's clarification echoing P2's own figures is released unchanged to P2, and P2's
    record keeps `cardCallRefused: false`.
  - dashboard-style calls carrying P2's key (no run id, a foreign run id, a mismatching
    requester) are refused `withheld: 0`.
  - P2's own admitted card call and resolving token still release the card.
- RW-4 (characterization, no recall). A reply block delivered before the tied refusal was
  released. A block delivered after it is withheld.
- RI-4 (HOST-LEVEL TEST REQUIRED AT INSTALL). This pins the flagged owner choice offline.
  A dashboard call reusing P1's live run id and session key, with a webchat requester, is
  tied to P1 and withholds P1's reply. The install gate must show that the real host
  refuses such a call and that P1's reply is not withheld.
- Unit coverage, in `channel.test.mjs`:
  - RW-units (ingress): each untied reason (`unknown-run` with no or a foreign run id,
    `run-unconfirmed`, `run-ended`, `session-mismatch` with another peer's key or none,
    `turn-expired`) answers without a `withheld` key and leaves every stored turn's
    `cardCallRefused` false. A tied refusal marks that entry only: other turns of the same
    peer and other peers are untouched. A requester check that throws or is not a function
    is tied. The flag is monotonic: a later admitted call marks the card turn and does not
    clear it. It is frozen in the snapshot, no member is named like a reset, and the
    peer's next turn starts false.
  - RW-units (gate): on a refused turn, a resolving token after a later admitted call is
    withheld `card-call-refused`, and the next turn releases.
  - RW-units (handler): `withheld` is 1 only for a strict `withheld === true`. The
    handler-side `unknown-run` (with the turn's own key and a mismatching requester) and
    `handler-error` are `withheld: 0` and change nothing.
  - RW-units (self-check): the refused-turn vectors are present, and a verifier that
    ignores `cardCallRefused`, or withholds only digit-free text on a refused turn, fails
    the self-test.
- Unit coverage, in `verifier.test.mjs`:
  - R0 for a missing or non-boolean `cardCallRefused`
  - R0c: a refused turn withholds a greeting, a user-figure echo and a resolving token,
    on a card turn too
  - R0c ordering: R0 and R0b first, so an unbound refused turn stays `unbound-turn`
  - RW-1 and RW-2 at the verifier
  - RW-units `isWellFormedVerdict`: a forged release on a refused turn is rejected for
    `no-figures`, `user-figures` and `card`, each with a positive control
  - three refused-turn rows and a missing-flag row in the completeness table
- Unit coverage, in `host.test.mjs`:
  - D21 (source): `cardCallRefused` is assigned once, to `true`, inside `admitCardCall`
    after the session-key check. No other runtime file assigns it. The handler derives
    `withheld` only from a strict `=== true`, and R0c is present.
  - the emulation test: a `noRunId` call carries no run id key, a dashboard call
    otherwise gets a foreign id, and a run's reply can give its one tool call a requester.

Rewritten in revision 7, and why:
- RB-3. Its requester-mismatch cases are now tied by design, so "neither peer's record
  changes" no longer holds for them. The test still refuses every case with its code and
  executes nothing. It now asserts `withheld` per case: 1 for requester mismatch, 0
  otherwise. It checks after every case that P1 is unrefused until the first tied case,
  that P2 is never touched, and that no refusal marks `cardToolCalled`.
- BM-7. The decision shape gains `withheld: 0 | 1`, and 1 is allowed only with
  `requester-mismatch`. The key count went from 3 to 4.
- Exact-shape assertions gain `withheld: 0`: BM-1, BM-2, BM-8 and D16 (f).
- Record helpers gain `cardCallRefused: false`: `record()` in `channel.test.mjs` and
  `inbound()` in `verifier.test.mjs`. So do the self-check vectors and the hand-built
  records in the R0 loops and the completeness table. Each still fails on the field it
  names.
- The snapshot-keys assertion in the ingress test now lists `cardCallRefused`.
- The version pin is "5".
No assertion's safety intent is weakened. Every changed expectation is either the added
`withheld` field or the tied refusal that decision 21 asks for.
`tests/test_whatsapp_channel_skeleton.py` runs them and checks the manifest without Node.

## Acceptance
- All Node tests and the full pytest suite pass; ruff clean; the three docs gates pass on
  the new files.
- Fail before, pass after: the fail-closed tests fail against a deliberately naive
  outbound that falls back to raw text on verifier failure, and pass against ours.
- Nothing installed or configured; no file outside the listed paths changed.

## Verification commands
```bash
node --test extensions/idx-whatsapp-channel/verifier.test.mjs \
            extensions/idx-whatsapp-channel/channel.test.mjs \
            extensions/idx-whatsapp-channel/host.test.mjs
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/ruff check . && .venv/bin/ruff format --check .
python3 scripts/gates/forbidden_paths.py <new paths>
python3 scripts/gates/pii_scan.py <new paths>
python3 scripts/gates/confidential_text.py <new paths>
```

## Critique fixes: adopted and not adopted
The design review raised sixteen items. Disposition:
- Adopted (critical): `normalizePayload` takes the host envelope
  `{ payload, cfg, accountId }` and is idempotent; a field is absent when undefined,
  null, false, empty string or empty array, so the message tool's `audioAsVoice: false`
  and the reply normalizer's undefined keys and string `replyToId` pass; tests feed both
  exact shapes.
- Adopted (high): peer canonicalisation (`whatsapp:` prefix, JID suffix, phone shapes to
  `+digits`) with table tests; the inbound `deliver` returns
  `{ visibleReplySent: false, suppression: { reason } }` for a withhold and
  `{ messageId, visibleReplySent: true }` for a send, and the emulated dispatcher
  classifies on `visibleReplySent`; `config.isConfigured` reports the transport's state
  so an accidentally loaded skeleton is skipped, not restarted ten times; the in-process
  ingress limitation is documented with a two-instance test, and `deliveryMode` is
  `"gateway"` so CLI sends run in the gateway process.
- Adopted (medium): the self-check accepts string deny entries only (host trim +
  lowercase); the "not installable" claim is corrected (loadable via
  `plugins.load.paths`, not loaded because no config names it) and a source test proves
  only `index.mjs` has a default export; `register` skips `cli-metadata` and
  `tool-discovery`, registers in the four other modes and refuses unknown ones;
  `viaCard` is accepted only for `rule: "card"` on a token-only input, with the invented
  text vector; known withholds (numbered lists, 24/7, hours, years) have vectors; the
  source test pins the allowed transport members, forbids bracket access and
  `Reflect.apply`, limits `seal(` to `outbound.mjs`, and a Proxy test records property
  access.
- Adopted (low): a transport receipt without `messageId` makes `sendText` throw (the send
  happened) rather than report `not_sent`; `emulatedActivation` takes an origin and shows
  a config-origin plugin needs an explicit enable; `performance.now` is the deadline
  clock.
- Not adopted: lowering the deadline from 250 ms to 50 ms (kept at 250 pending the owner
  item; the clock change is in); defining a chunker (kept as an owner item: either chunks
  are verified separately or texts over 4000 characters are withheld); the host-faithful
  dispatcher result classification beyond the `visibleReplySent` predicate (the
  emulation is labelled as documentation of cited rules, not proof).

## Limitations
- Loadable through `plugins.load.paths` without `package.json`; not loaded because no
  config names it. The install PR decides on a `package.json` and an explicit
  `plugins.entries.idx-whatsapp-channel.enabled: true` or allow entry (a config-origin
  plugin is not auto-enabled by `channels.whatsapp`).
- `channelConfigs.whatsapp.schema` is permissive; the merge of two manifests' schemas for
  one channel id was not traced.
- The verifier is synchronous, so the deadline is a post-hoc check; a non-returning
  verifier stalls that session's reply queue (nothing is sent).
- The dispatcher, durable queue, hooks, registry conflicts and `startAccount` lifecycle
  are emulated from cited lines, not exercised.
- `resolveRoute`/`runInbound` are seams; the entry wires none and the default transport
  never delivers an inbound.
- Tool, cron, heartbeat and CLI sends carry no channel-minted handle and are withheld
  `no-turn-handle` with nothing sent (decision 17); alert delivery over this channel is
  therefore not possible in this skeleton until a handle-bearing path for proactive
  sends exists (item 18). The inbound `deliver` binds to its own turn through the trusted
  handle (`turn` in the `sendText` context), so a reply in flight when the peer's next
  message arrives is verified against the message it answers; the newest four turns per
  peer are kept, older in-flight replies find their handle no longer trusted and are
  withheld `untrusted-turn`. Any caller that passes a `turnId` is withheld the same way.
  The host's `to` spelling for these callers was not traced;
  `normalizePeerId` covers the common spellings, and a `messaging.normalizeTarget` is an
  install-PR item (core honours it for bundled plugins only). The transport is handed the
  canonical peer id (`+<digits>`, `<digits>@lid` or a lowercased other id), not the
  caller's spelling; the transport PR owns the mapping back to its address format, and
  whether a `@lid` address is the same person as the phone-number peer is for it to
  settle (the skeleton keeps them apart).
- The card-tool admission handler is not yet registered with the host
  (`createBeforeToolCallHandler`; `index.mjs` registers nothing). The event and context
  shapes, the `{ block, blockReason }` directive and the run-id flow come from the
  2026-11-07 host trace and are emulated in test-support. They are not exercised against
  the real host. The install PR captures real events first (see "Install prerequisites").
- Bundled-MCP path (decision 19 (a)): with no `requester`, a card call is admitted on the
  issued run id and the session key alone. A caller that holds both a live WhatsApp run id
  and that peer's session key, while the run is active, is indistinguishable offline and
  is admitted (pinned by RI-2). The install PR's host-level test must show a dashboard
  request cannot carry both. If it cannot show that, the card tools move to a path that
  verifies the originating turn and peer (plugin tools with `requester`).
- Run-end window: the run ends when the channel's `runInbound` promise settles. If the
  host lets a next run on the same session key start before that promise settles, that run
  carries a fresh host id and is refused, but the old run id stays admissible until the
  settle. The host-level test must cover this ordering.
- Active-turn backstop: a run that never settles keeps its peer busy until the ingress TTL
  (30 min), after which the peer's next message is admitted (owner choice, flagged).
- After a refused card call the model gets `blockReason` as the tool result and may
  answer in prose. If the refusal is tied to the turn (decision 21), every reply delivered
  on that turn afterwards is withheld `card-call-refused`. If it is of unknown origin, the
  turn stays ordinary: digit-free prose releases under R2, figures the user did not write
  are withheld by R4, and a card token is withheld `card-without-trusted-call`.
- Reply blocks delivered before a tied refusal are already out and are not recalled; only
  blocks delivered after it are withheld (RW-4).
- RW-1b, known limit: an ordinary turn (no card call at all) has no card evidence, so a
  reply quoting the buyer's own budget as a listing price ("listed at 650000" after "my
  budget is 650000") releases under R3.
- RW-2, known limit: on an ordinary turn a price spelled out in words releases under R2,
  because number words are not figures (item 5).
- The tie rule leans on installation gate (a): offline, a call that reuses a live
  WhatsApp run id and session key with a mismatching requester is tied to that WhatsApp
  turn and withholds its reply (RI-4). If the real host lets a dashboard call carry both,
  the install uses a tool path that verifies the originating turn and peer.
- An evicted turn's run id is remembered for a bounded while (twice the ingress capacity
  in entries), so a late call reports `turn-expired`; past that it reports `unknown-run`.
  Both refuse.
- Host follow-ups and folding: from WhatsApp none reach an active run, because an
  overlapping message is answered `BUSY_TEXT` and never handed to the host. Follow-ups or
  folding from other sources into a WhatsApp session are an install-PR config item. The
  queue-mode keys that turn them off are untraced.
- A `SAFE_TEXT` send on a card turn is reported to the dispatcher as visible (with the
  reason in `withheld`), the same as any other `SAFE_TEXT` send, so the dispatcher does
  not send a fallback after it.
- Policy gaps: figure-bearing tool clarifications and error notices are withheld; number
  words pass; `isError` is invisible to `sendText`; no chunker, so texts over 4000
  characters are withheld. A figure is any `\p{N}` run (decimal digits, `½`, `²`, `⑫`,
  `Ⅻ`), so superscripts and fractions in listing text are withheld too.
- CI: the workflow has no Node setup step (not edited here, gates consent), so the Node
  tests run in CI only if the runner image ships Node 20+; otherwise the wrapper skips.
- The self-check reads the registration-time config only.
- Groups, channels, threads, media, polls, reactions, receipts, typing, QR, auth: out of
  scope.
- WO-036 and ADR-0015 live on #179's branch; a later merge may need a cross-reference
  pass.

## Install prerequisites (owner item 19)
Decided 2026-11-07. The install PR does not register the `before_tool_call` handler until
each requirement below holds and is pinned by a regression in that PR.

Implemented offline, revision 6 (2026-11-07): requirements 1, 2 and 4 and the binding and
isolation regressions now live on this branch against the emulated host (RB-*, RI-*,
RS-*, RA-* in `channel.test.mjs`). The open points below were decided by the owner the
same day (Owner decisions, item 19 (a), (b), (c)). The design differs from requirement 1's
sketch in one respect: admission goes through `ingress.admitCardCall(runId, ...)`, the
only marking path, instead of `markCardTool(handle, name)`. `markCardTool` is removed. The
run is also confirmed through `replyOptions.onAgentRunStart`, and the run ends when
`runInbound` settles. What remains for the install PR:
- the real-host replay test of decision 19 (a), which stays an installation gate. Since
  revision 7 (decision 21) it covers two things on the real dispatch path (lane
  serialization, no steering or follow-up into the run, the run-end window):
  - a dashboard request that reuses a live WhatsApp run id and session key is refused
  - that refusal does not withhold the WhatsApp turn's reply
  If the host admits such a call, the install uses "a tool path that verifies the
  originating turn and peer" (owner, 2026-11-07). Offline, RI-2 pins the admission without
  a requester and RI-4 the withhold with a mismatching requester.
- the queue-mode config that keeps host follow-ups and message folding out of WhatsApp
  sessions (keys untraced), and asserting it at startup
- real-event capture per requirement 6, including that `onAgentRunStart` receives the
  issued run id on the WhatsApp dispatch path
- registering the handler without a matcher (requirement 5) and asserting it is
  registered; the `dmScope` assertion (requirement 3)
- asserting at startup the literal host name of every `CARD_TOOLS` tool and that
  `isCardTool` accepts each one (the host's 64-character cap could cut into a tool
  segment, which `isCardTool` does not recognise; its `-N` collision suffix is accepted)

Host facts come from the read-only trace of OpenClaw 2026.9.5 (Status 2026-11-07;
EVIDENCE_LOG, same date, with file, line and sha256-12 for each). The host facts
themselves are untouched by revision 6.

What the host gives the hook. The event carries `toolName`, `params`, `runId` and
`toolCallId` and no session, channel or account field. The context is an allowlist:
`agentId`, `sessionKey`, `sessionId`, `runId`, `toolCallId`, `channelId` and, only on
some paths, `requester` (`channel`, the agent's own `accountId`, `senderId`,
`senderIsOwner`). The host's internal `turnSource*` fields never reach a plugin. No inbound
message id reaches the hook. The only per-turn value it does receive is the run id, which
the runner takes from the dispatcher's `replyOptions.runId` when one is passed and
otherwise mints at random. `ctx.channelId` is not a usable discriminator: on dashboard
runs it is the session key, and elsewhere it can fall back to a bare channel name.
`requester.channel` can read `whatsapp` on heartbeat, isolated cron, subagent and
admin-origin dashboard runs, because those inherit the persisted route. The bundled-MCP
path that serves the `idx__*` tools on the built-in harness passes no `requester` at all.

1. Trusted binding to turn and peer. The channel mints a random run id for each inbound
   and passes it as `replyOptions.runId`. It keeps `runId -> handle` for the ingress TTL
   and admits a card call only when `event.runId` is a run id it issued, `ctx.runId`
   equals it, and `ctx.sessionKey` equals the bound turn's stored key. It then marks
   through the handle-bound per-turn path (`markCardTool(handle, name)`). The handle names
   both the turn and the peer, so this binds the call to both. Where `ctx.requester` is
   present (plugin tools), its `channel` and its normalised `senderId` must also match
   the bound turn. A session key or `requester` value never admits a call on its own,
   because callers supply them: `markCardToolForSession` stops being an allow path, which
   closes BM-9.
2. Isolation. A card call that fails binding is refused for that call only, with
   `{ block: true, blockReason }`, and changes no WhatsApp turn. The failures are: an
   unknown, missing or mismatched run id, a mismatched key or requester, or a handler
   error. There is no `blockOpenTurns` and no key-wide mark, which closes BM-10.
   Amended 2026-11-07 by item 21: a requester mismatch on a call whose run id and session
   key bind it to a live, confirmed turn is tied to that turn and withholds that turn's
   later replies; it still changes no other turn. On the host side nothing couples the
   refusal to another session:
   - The host vetoes the call before execution and returns the reason to the model as a
     tool result. The run is not aborted.
   - Its block bookkeeping is keyed by run and tool-call id, and only tool-end accounting
     reads it.
   - Loop-detection history is filtered by run id when read, and detection is off unless
     configured.
   - Sessions with different keys run in separate lanes.
3. Session keys. `session.dmScope` stays `per-channel-peer`. `config/openclaw.idx.json5`
   already sets it, and `tests/test_openclaw_merge_config.py` asserts it. The host default
   is `main`. Under `main`, every DM from every peer, the dashboard Home, the default
   heartbeat and main-target cron share one key and one lane, so an inbound can be
   steered into another peer's active run and peer binding is impossible. Under
   `per-channel-peer`, the key the hook sees on both tool paths equals the transcript key
   (`agent:<id>:whatsapp:direct:<peer>`), provided the channel's inbound context sets no
   `RuntimePolicySessionKey`. The install PR asserts the resolved keys for a
   WhatsApp DM and for the dashboard Home differ.
4. Block directive. The host reads `block`, `blockReason`, `params` and `requireApproval`
   and nothing else. The handler returns `blockReason`, not `reason`. A null return
   allows. The decision's `marked` and `tainted` stay internal. A throw or a timeout
   (15 s default) fails closed for that call.
5. Matcher. Register without a `matcher`, because a misspelled matcher silently skips
   the hook and the tool runs ungated. Filter with `isCardTool` on `event.toolName`,
   which the host lowercases and, for bundled MCP tools, spells `<server>__<tool>`
   (sanitised, capped at 64 characters, with a `-N` suffix on a collision). Assert at
   startup that the handler is registered.
6. One real event per path, captured before registration, as formats only and never
   values. Capture it for a WhatsApp DM turn and for a dashboard Home turn:
   - the literal `event.toolName` of each `CARD_TOOLS` tool and which path served it
   - that `event.runId`, `ctx.runId` and the issued run id agree
   - whether `ctx.requester` is present, and the shape of `ctx.sessionKey`
   - the model-visible text of a blocked call

Regressions, in the install PR:
- Binding. Peers P1 and P2 each have an open turn. A card call carrying P1's issued run
  id and P1's key is admitted and marks P1's turn only. The same call is refused, with
  nothing marked or tainted, in each of these cases (origin unknown, so only the call is
  refused):
  - the run id is unknown or missing
  - `event.runId` and `ctx.runId` differ
  - the key is P2's or missing
  - the run id belongs to a turn past the TTL
  A follow-up turn whose run id was never issued is refused.
  Amended 2026-11-07 by item 21: when a present `requester` names P2 or another channel
  on a call carrying P1's own issued run id and key, the call is a tied refusal. It is
  refused `requester-mismatch` with `withheld: 1`, it sets `cardCallRefused` on P1's turn
  and only P1's, so P1's later replies are withheld (`SAFE_TEXT` or silence by mode), and
  P2's turn is unchanged.
- Isolation. WhatsApp turns for P1 and P2 are open concurrently. Two dashboard card calls
  are each refused with a non-empty `blockReason`:
  - a plain one: a dashboard key (`agent:<id>:main` or `agent:<id>:dashboard:<uuid>`), a
    `webchat` requester or none, and an arbitrary run id
  - a forged one: `requester.channel: "whatsapp"` and an unknown run id
  Afterwards, both WhatsApp turns' `cardToolCalled`, `cardCallRefused` and `runBound`
  are unchanged (neither turn is marked refused by the dashboard calls),
  their greetings and card-token replies still release, and P1's own card call is still
  admitted. One host-level check on the real dispatch path then shows that the vetoed
  dashboard tool did not execute while a concurrent WhatsApp run's card call did.

Open points the trace raised. All three were DECIDED 2026-11-07; see Owner decisions,
item 19 (a), (b), (c). They are kept here as raised:
- (a) On the bundled-MCP path the issued run id is the only binding, because no
  `requester` is available to cross-check. Accept that, or serve the card tools as plugin
  tools so the requester check applies.
  - Residual: a gateway client that learned a live WhatsApp run id could present it. Only
    admin-scope clients can set an origin, and whether run ids reach Control UI clients
    is untraced.
- (b) A queued follow-up turn runs under a fresh random run id that the channel never
  learns. A steered message runs under the active run's id.
  - Under requirement 1, a card call on a follow-up is always refused. One on a steered
    message binds to the active run's turn, not to the steered message.
  - Accept that, or choose a queue mode without follow-ups.
- (c) The 2026-11-06 instruction to withhold the affected reply when correlation fails.
  With an unknown run id the affected turn cannot be identified without touching others.
  - Recommendation: taint only the WhatsApp turns whose stored key equals the refused
    call's `ctx.sessionKey`. A key may widen a withhold but never admit a call.
  - Under `per-channel-peer` that is the calling peer's own turns, and never a turn
    under a dashboard, cron or heartbeat key, so requirement 2 still holds.
  - Cost: a caller that forges a peer's key can cause that peer's replies to be
    withheld, which fails closed.

## Owner decisions (pending unless marked DECIDED)
1. Withheld-reply default: `safe-text` to a peer with an open turn and silence otherwise
   (shipped), or silence everywhere, or safe text everywhere; approve or reword
   `SAFE_TEXT`.
2. Withhold shape toward the host: `visibleReplySent: false` (shipped, no throw, no
   durable-queue replay) versus throwing to surface it in delivery diagnostics.
3. ADR number 0016 (0015 is taken on #179's branch); confirm or renumber on merge order.
4. Error notices with digits: accept the withhold (shipped) or opt into
   `sendTextOnlyErrorPayloads` with a fixed digit-free error constant.
5. Number words: outside the figure definition (shipped) or add a word-number list.
6. Pytest wrapper when Node is absent: skip with a reason (shipped, matches the WO-019
   spike) or fail.
7. Card token grammar: `[[card:<ref>]]` placeholder; who adapts when #179 plugs in.
8. Residual risk of a removed deny: self-check plus runbook (shipped) or a CI/config guard.
9. Verifier deadline (250 ms shipped; 50 ms suggested), ingress TTL (30 min), capacity
   (512 peers).
10. Chunker: define one so chunks are verified separately, or keep the 4000-character
    withhold.
11. `deliveryMode: "gateway"` (shipped) versus `"direct"`.
12. Install-PR prerequisites to pre-approve or reject: a minimal `package.json`, an
    explicit enable entry, and whether the channel schema should mirror the stock keys.
13. Figure definition: `\p{N}` (shipped after review; withholds `½`, `²`, `⑫`, `Ⅻ` as
    well as decimal digits) or `\p{Nd}` only (the first cut; released those numerals).
14. Turns kept per peer for in-flight replies: four (shipped) or another number.
    (Whether a non-channel send may name a turn is item 17; the channel's own `deliver`
    binds through the trusted handle, never a `turnId`.)
15. CI Node step: add `actions/setup-node` so the wrapper cannot skip in CI (needs the
    gates consent token; not done on this branch).
16. DECIDED 2026-11-06: the card-tool mark comes from the host's trusted tool-call event,
    applied when `before_tool_call` fires and before the tool executes, so a card call
    that then fails (throws, times out, is refused, returns an error result) is covered
    too. Not the card store, not the model. Implemented as `beforeToolCall` on the turn
    object and `createBeforeToolCallHandler(ingress)` for the hook; the install PR
    registers the handler. Review fix for the owner to confirm (same date): `isCardTool`
    now also accepts the host's namespaced, cased or padded spelling of a `CARD_TOOLS`
    name (`idx__search_listings`), since the host presents MCP tools as `idx__<tool>` and
    an exact match would have left every real card call unmarked; `CARD_TOOLS` itself is
    unchanged, and over-marking is the direction this decision accepts.
    Approved 2026-11-06: the bare and namespaced IDX tool names (`isCardTool`). Same
    instruction: a successful trusted mark is required before a card tool executes; if
    correlation or marking fails, execution is blocked and the affected reply withheld
    (both seams return decisions; see Interfaces and the "blocking mark" Status entry).
    Superseded 2026-11-07 by decision 19 (c), revision 6: the refused call is still
    blocked before execution, but no turn is tainted, and the calling turn's digit-free
    reply releases under the ordinary rules (listed for confirmation in item 20).
    Restored 2026-11-07 by item 21 for refusals tied to their own turn.
17. DECIDED 2026-11-06: the channel-minted handle is required for this skeleton. A send
    without it is withheld `no-turn-handle` with nothing sent; the latest-turn fallback
    (`ingress.current`) is removed; a regression pins a peer with a recent inbound record
    whose handle-less send is withheld while the same turn's `deliver` releases. Any
    `turnId` in the send context stays `untrusted-turn`.
18. A handle-bearing path for proactive sends (alert delivery, cron, heartbeat, the
    message tool and CLI): how such a sender obtains a trusted handle, or an equivalent
    trusted record, so the gate can verify it. Until decided, every proactive send over
    this channel is withheld `no-turn-handle`.
    Deferred 2026-11-06 by the owner; proactive sends stay withheld `no-turn-handle`.
19. DECIDED 2026-11-07: an installation prerequisite. Before the install PR registers the
    hook handler, a card tool executes only when the call is bound by trusted values to
    its originating WhatsApp turn and that turn's peer, and refusing a card call from a
    dashboard (or any non-WhatsApp) session leaves concurrent WhatsApp turns unaffected.
    The host's channel metadata was traced read-only first; both regressions land in the
    install PR. The requirements, the traced host facts they rest on and three open
    points are under "Install prerequisites (owner item 19)". This branch keeps the
    shipped behaviour (BM-9's session-keyed mark, BM-10's global taint) as a skeleton
    record; the install PR replaces both. Raised as: card tools from sessions outside this
    channel block and taint every open WhatsApp turn (BM-10), and a key naming another
    peer's open turn is accepted as a mark (BM-9). Superseded on this branch by revision 6
    (BM-9 and BM-10 retired; see Tests required).
    Sub-decisions, DECIDED 2026-11-07 (owner's words):
    - (a) "Keep MCP if a host-level test proves that a dashboard request reusing a valid
      WhatsApp run ID and session key is refused. Otherwise use a tool path that can
      verify the originating turn and peer." Implemented: the MCP path is admitted on the
      issued, confirmed run id plus the session key; the reuse case is pinned by RI-2 and
      left to the install PR's host-level test.
    - (b) "Admit one active turn per peer. Give overlapping messages a fixed busy reply
      and keep host follow-ups and message folding out of this first install."
      Implemented: `hasActiveTurn` plus `BUSY_TEXT` (RA-1..6). The follow-up and folding
      config is an install-PR item.
    - (c) "Refuse unbound calls individually. A session key alone must never suppress
      another turn. Release a reply only when trusted activity for its own turn supports
      the verdict." Implemented: per-call refusal with no taint, R0b `unbound-turn`, R1
      `card-without-trusted-call`, `isWellFormedVerdict` requiring `runBound` (RB-3, RI-1,
      RS-1, RS-2). Amended 2026-11-07 by item 21: a refusal tied to its own turn withholds
      that turn; a refusal of unknown origin still refuses only the call.
    "Proceed with the offline binding tests. These are installation requirements."
20. Owner choices made in revision 6, flagged for confirmation: the `BUSY_TEXT` wording
    ("I'm still working on your last message. Please send this one again after I
    reply."); sending the busy reply in both withhold modes (it is a fixed constant, not a
    withheld reply); the ingress TTL (30 min) as the active-turn backstop when a run never
    settles; `runBound` required for every release, greetings included, so an unconfirmed
    turn gets only `SAFE_TEXT` (or silence); `CARD_TOOL_BLOCK_REASON` wording ("Listing
    tools run only inside a verified WhatsApp turn."); a refused card call leaves its
    turn ordinary, so the turn's digit-free reply (an apology, a clarification) releases
    after the refusal. This reverses item 16's approved "affected reply withheld" and
    needs the owner's confirmation.
    DECIDED 2026-11-07 for the first five choices: the owner approved them as written
    (the `BUSY_TEXT` wording, the busy reply in both modes, the TTL backstop, `runBound`
    for every release, the `CARD_TOOL_BLOCK_REASON` wording). The sixth (a refused call
    leaves its turn ordinary) is NOT approved: item 16's protection is kept; see item 21.
21. DECIDED 2026-11-07: withhold a turn whose own card call is refused. The owner's
    instruction, verbatim:
    "Approve the first five item 20 choices as written. Keep item 16’s protection. If a
    refused card call can be tied to its originating WhatsApp turn through trusted host
    context, withhold that turn’s model reply and use the fixed safe notice or silence
    according to the configured mode. If the origin is unknown, refuse only the call. A
    session key alone must never suppress another turn.

    Add regressions for a buyer budget reused as a listing price, a spelled-out listing
    claim, and an unrelated WhatsApp reply that still delivers. Keep the real-host replay
    test as an installation gate. If the host admits a dashboard call that reuses live
    WhatsApp IDs, use a tool path that verifies the originating turn and peer. Re-request
    review on #181 after CI passes. Keep #179 on hold and installation paused."
    Implemented in revision 7:
    - The tie rule. A refused card call is tied to a turn when every run-binding check
      that admission uses has passed for that turn: `event.runId` is a non-empty string
      equal to `ctx.runId`, it names an entry in the ingress run map, that entry is stored
      and unexpired, its run has not ended and was confirmed (`runBound`), and
      `ctx.sessionKey` equals the entry's session key. In `admitCardCall` order this
      means every refusal reached after the session-key check, which today is
      `requester-mismatch` alone (a requester check that throws included). Every earlier
      refusal (`unknown-run`, `turn-expired`, `run-ended`, `run-unconfirmed`,
      `session-mismatch`), and the handler-side `handler-error` and `unknown-run`, is of
      unknown origin: the call is refused and no state changes. A call that arrives after
      the run ended is `run-ended`, so it is of unknown origin too.
    - Why this rule. The evidence that would admit a call is the same evidence that ties a
      refusal to a turn. The run id is issued by the channel for one turn and confirmed by
      the host, so a tie never rests on a session key. A session key with no run id, a
      foreign run id, or an unconfirmed or ended run ties nothing. When the run id and
      session key bind a call to a live, confirmed turn but the requester disagrees, the
      call is treated as that turn's own call carrying inconsistent peer data. That turn
      alone is withheld, failing closed.
    - Mechanism. The record gains `cardCallRefused`: false at record time, monotonic,
      never cleared, never inherited, and present in the frozen snapshot. A tied refusal
      sets it on that one entry, and `admitCardCall` answers
      `{ admitted: false, reason, withheld: true }`. The handler's decision gains
      `withheld: 0 | 1`, which the host does not read. Verifier rule R0c sits after R0b
      and before R1 and withholds everything on such a turn as `card-call-refused`, card
      tokens included. `isWellFormedVerdict` accepts no release on it, and
      `VERIFIER_VERSION` is "5". The gate sends `SAFE_TEXT` in safe-text mode and nothing
      in silent mode, with no outbound change. Replies delivered before the refusal are
      not recalled.
    - Flagged owner choice. A requester mismatch counts as tied. This depends on
      installation gate (a): if the real host admits a dashboard call that reuses a live
      WhatsApp run id and session key, such a call could withhold that WhatsApp turn
      (pinned offline by RI-4). Per the owner, the tool path then changes to one that
      verifies the originating turn and peer. The alternative is to require the requester
      to match for a tie as well. Under today's admission rules the protection would then
      never fire, because every fully tied call is admitted.
    - Standing: "Re-request review on #181 after CI passes" (the orchestrator's step, not
      the implementer's) and "Keep #179 on hold and installation paused."

## Stop conditions
- Anything would need a paid call, a live send, an install, a config change under
  `~/.openclaw`, or a credential.
- A host fact cited here turns out to differ when the install PR traces it.
- A requirement would relax the fail-closed rules above.

## Status
2026-11-06 — implemented on `wo-036-whatsapp-channel-skeleton` (branch name as assigned
by the workflow; the work order number is 037). Node: 55 tests pass across the three
files. Fail before, pass after: in a scratch copy with the gate's withhold branch
replaced by a raw-text fallback, 8 of 21 `channel.test.mjs` tests fail (the two
verifier-throws tests, deadline, malformed, the behavioural single-call-site table, the
no-record case, the end-to-end run and the second-instance test); against the shipped
gate all 21 pass. No PR opened by the implementer. Nothing installed or configured.

2026-11-06, review fixes — ten findings from the code review, disposition:
- Fixed (medium): verifier result fields re-read after the well-formedness check
  (getter/Proxy TOCTOU); the gate now snapshots `kind`, `text`, `reason`, `rule`,
  `viaCard` once into a frozen object before checking and sealing.
- Fixed (medium): resolver `text` read three times; now one read, checked and
  substituted.
- Fixed (medium + low, same cause): `PARTIAL_TOKEN_RE` matched bare `card:` in prose, so
  "credit card: yes or no?" was withheld; now `[[`, `]]`, `[card:` or `card:...]`.
- Fixed (low): figures widened from `\p{Nd}` to `\p{N}` (owner decision 13).
- Fixed (low): turn ids are channel-generated (`randomUUID`), not the peer's message id.
- Fixed (low): in-flight replies bind to their own turn; ingress keeps four turns per
  peer with `forTurn` (owner decision 14).
- Fixed (low): the single-call-site source test now requires every `transport` identifier
  to be an immediate `transport.<member>(` call apart from four listed declaration sites,
  so destructuring, aliasing, `?.` and `.call` bypasses fail it; a self-test mutates the
  source five ways and checks each is caught.
- Corrected by a new EVIDENCE_LOG entry (low): the earlier entry's sentence read as if
  the two wrapper tests were skipped; they passed.
- Not fixed, documented (low): no `actions/setup-node` in CI (`.github/` needs the gates
  consent token; owner decision 15).
Node: 62 tests pass across the three files (55 before). Fail before, pass after: against
HEAD's runtime files in a scratch copy, the eight new or changed tests fail (three in
`verifier.test.mjs`, five in `channel.test.mjs`); the destructured and `.call` raw-send
copies fail the source test (16 pass, 2 fail each) where the old test passed them.

2026-11-06, turn binding revision — the owner's instruction: bind sends to their trusted
originating turn; require verified card tokens whenever that turn called a card tool while
keeping greetings and clarifications on ordinary turns; reject incomplete release
verdicts. Implemented as: `ingress.record` returns a frozen handle kept in an
instance-private WeakMap (identity to entry) and `forTurn` answers only for it; `sendText` withholds
`untrusted-turn` (nothing sent) for an unrecognised handle or any `turnId`; the channel
passes the handle from its `deliver` closure only and gives `runInbound` a string id plus
`noteToolCall`; records carry a monotonic `cardToolCalled`, verifier rule R1b withholds
prose on a card turn (`card-turn-requires-tokens`), `VERIFIER_VERSION` is "2";
`isWellFormedVerdict(value, inputText, inbound)` requires one of the three rules,
`viaCard` matching the rule, no `reason`, no thenable, no text on a withhold, and
rule-consistent text against the record, with `card` the only rule on a card turn.
Review fixes on the revision (same date): `sendText` reads every context field once, up
front, refuses a non-string or empty `to` (`bad-destination`, nothing sent) and hands the
transport the canonical peer the record was checked under, closing a getter or stateful
`toString` on `to` that had the verifier check one peer and the transport deliver to
another (present since HEAD 873f58c); `normalizePeerId` keeps `@lid` as its own
namespace (`<digits>@lid`) instead of folding it onto `+<digits>`; the ingress maps each
handle by identity to the entry it was minted for (WeakMap), so a duplicate turn id can
no longer re-point an older, marked handle at a newer unmarked record; the two Rule 1(e)
tests and the audit-log test now reach their binding assertions before any Rule 2 call,
so they fail on HEAD on the property they are named for; owner decision 14 no longer
says `deliver` passes `turnId`; the residual-risk count reads four newer messages, not
five.
One deviation from the pinned design: a `deliver` that sent `SAFE_TEXT` on a card turn
reports `visibleReplySent: true` with `withheld: { reason }` rather than
`visibleReplySent: false`, because a not-visible result makes the dispatcher send its
fallback after `SAFE_TEXT` already went out (two messages), and the existing in-flight and
dispatcher tests pin the visible shape; silent mode reports not visible with the
suppression reason as pinned. Node: 85 tests pass across the three files (62 before).
Fail before, pass after: with the runtime `.mjs` files of HEAD 873f58c in a scratch copy
and the new tests, 27 tests fail (17 assertion failures, 10 missing-API TypeErrors):
`verifier.test.mjs` 4 of 25 (R0 malformed record, R1b card turn, CARD_TOOLS, verdict
completeness), `channel.test.mjs` 17 of 38 (five ingress tests including the duplicate
turn id, the linked-id destination, the audit line, the in-flight reply, three Rule 1
binding tests, five Rule 2 card-turn tests, the Rule 3 gate test), `host.test.mjs` 6 of
22 (the single-call-site pin now reading `to: peer`, the single-read source and host-shape
tests, the canonical `to` in the tool/cron/heartbeat test, the tool-shaped bare `turnId`
send, the host runner's turn object). The pytest wrapper passes (2 tests) with
the sibling checkout's interpreter; this worktree has no `.venv`. Nothing installed or
configured; no commit made by the implementer.

2026-11-06, decisions 16 and 17 — the owner decided the card-tool mark comes from the
host's trusted before-tool-call event, applied before execution so failed card calls are
covered, and that the channel-minted handle is required with no latest-turn fallback.
Implemented as: `ingress.current` removed (no runtime caller remains; `forTurn` is the
only record read); `sendText` binds through `ctx.turn` alone, withholds `no-turn-handle`
(nothing sent, audit `hasRecord: false, boundToTurn: false`) when no handle is present
and `untrusted-turn` for any `turnId` or an unrecognised handle, so every send that
reaches the transport is bound to a trusted turn; the turn-object seam is renamed
`beforeToolCall`; `createBeforeToolCallHandler(ingress)` is exported from `channel.mjs`
for the install PR to register with `before_tool_call` (nothing registered by
`index.mjs`); the fake host runs mark, execute, reply in that order and records the
event sequence. Consequence: proactive sends (tool, cron, heartbeat, CLI, alert delivery)
are withheld in this skeleton until a handle-bearing path exists (new item 18).
Adapted tests, each because the contract changed: every direct `sendText` in the
fail-closed, malformed-verdict, single-call-site, transport-error, audit, default
transport, Rule 3 and linked-id tests now passes the turn's handle; the no-record test
expects `no-turn-handle` and adds an expired-handle case; the ingress tests read through
`forTurn` and assert no `current` member; the in-flight, Rule 1(a, f), Rule 1(c),
second-instance, Proxy-transport, single-read host-shape and tool/cron/heartbeat tests
expect `no-turn-handle` for handle-less sends and use a handle for the positive path;
the Rule 2 tests call `beforeToolCall` and check the mark through `deliver` outcomes
instead of `current`.
Review fixes on this revision (same date), four findings:
- Fixed (medium): both decision 16 seams matched the tool name exactly and
  case-sensitively, so the host's `idx__search_listings` (ADR-0003) would have skipped
  the mark and released prose on a card turn. `isCardTool` now accepts the exact name or
  any spelling whose trimmed, lowercased last segment after `__`, `.`, `/` or `:` is a
  `CARD_TOOLS` name; `CARD_TOOLS` is unchanged. This widens matching beyond the pinned
  design in the over-marking direction and is flagged under owner decision 16 for a
  nod. Regressions: `D16 (f)` (seven host spellings through the fake host and the hook
  handler, three look-alike names staying ordinary) and the `isCardTool` table; the
  three assertions that pinned `Search_Listings` as a non-card name were adapted to
  names that still differ. The install PR gains an acceptance item: capture one real
  `before_tool_call` event per card tool and assert the handler marks it.
- Fixed (low): `createBeforeToolCallHandler`'s function read `event.toolName` and
  `ctx.sessionKey` outside any try/catch, so a throwing getter or Proxy trap propagated
  despite the "never throws" wording; the reads and the mark are now inside a try/catch
  that returns 0. `D16 (c)` gains throwing-getter, throwing-Proxy and revoked-Proxy cases.
- Fixed (low): no handle-bearing send with a `whatsapp:` prefix or a phone-number JID
  suffix reached the transport in any test after the tool/cron/heartbeat shapes became
  `no-turn-handle`. A gate test and three lines in the single-read host-shape test now
  send with the handle under those spellings and assert the transport gets `+<digits>`;
  a scratch gate that forwarded the raw destination fails both (4 tests fail, 90 pass).
- Fixed (low): the handler's return value was described as "returns nothing" in the
  Interfaces and the README gate section and as "returns a number, blocks nothing" in the
  README channel section; all three now say it returns the mark count and that the host's
  treatment of a numeric hook return is for the install PR to confirm or wrap.
Node: 94 tests pass across the three files (85 before this revision, 92 before the
review fixes): `verifier.test.mjs` 25, `channel.test.mjs` 46, `host.test.mjs` 23. Fail
before, pass after: with the runtime `.mjs` files of HEAD 3213f63 in a scratch copy and
the new tests and test-support, 25 tests fail, all on assertions: `verifier.test.mjs` 1
of 25 (the `isCardTool` table), `channel.test.mjs` 19 of 46 (the no-record/no-handle
test, the ingress round trip, the linked-id destination, the audit line, the in-flight
reply, Rule 1(a, f), the five Rule 2 card-turn tests, the second instance, the decision
17 regression and the six decision 16 regressions), `host.test.mjs` 5 of 23 (the
decision 17 source test, the Proxy transport, the tool/cron/heartbeat shapes, the
single-read host shape, the host runner's turn object). The canonical-destination gate
test passes against HEAD by design (HEAD already handed the transport the canonical
peer); its fail case is the raw-destination mutation above. The pytest wrapper passes (2
tests) with the sibling checkout's interpreter. Docs gates pass on every changed file.
Nothing installed or configured; no commit made by the implementer.

2026-11-06, blocking mark — the owner approved the bare and namespaced IDX tool names
(decision 16), deferred item 18 (proactive sends stay withheld `no-turn-handle`), and
required a successful trusted mark before a card tool executes, with execution blocked
and the affected reply withheld when correlation or marking fails (superseded 2026-11-07
by decision 19 (c), revision 6: no taint, and the calling turn's digit-free reply
releases; see item 20). Implemented as:
records gain a monotonic `toolCallBlocked` (false at record time, never cleared, never
inherited; `isInboundRecord` requires it, so a record without it is
`malformed-inbound-record`); `ingress.blockTurn(handle)` taints one trusted turn and
`ingress.blockOpenTurns()` taints every stored, unexpired turn of every peer and returns
the count; verifier rule R0b, after the record checks and before R1, withholds everything
on a tainted turn as `blocked-tool-call` (tokens included), `isWellFormedVerdict` accepts
no release on one, `VERIFIER_VERSION` is "3", and the self-check vectors carry the flag
plus three new vectors (blocked greeting, blocked resolving token, record missing the
flag); both `channel.mjs` seams return a decision object and never a bare number or
boolean: `createBeforeToolCallHandler` answers `{ block: false, marked: 0 }` for a
non-card name, `{ block: false, marked: n }` when the session mark landed,
`{ block: true, reason: "no-turn-for-session", tainted }` after `blockOpenTurns()` when a
card tool marked no turn, and `{ block: true, reason: "handler-error", tainted }` after a
guarded `blockOpenTurns()` for a throw or a non-string tool name; the per-turn
`beforeToolCall` answers the same shape with `mark-failed` (after `blockTurn`) for a
card tool on a turn whose handle is no longer trusted and `handler-error` for a throw or
a non-string name. `outbound.mjs` is unchanged (the audit line already shows the verifier
reason); the fake host now applies the decision (a blocked tool is not executed and the
reply function is told `{ blocked: reason }`; a non-decision return is a `bad-decision`
block) and takes an optional `hook`/`hookSession`/`hookContext` to drive the
session-keyed handler. Nothing is registered with the host; the exact block directive the
host reads is untraced and is an install-PR item alongside the real-event proof.
Interpretation on one unpinned point, stated here: the per-turn seam treats a non-string
tool name as `handler-error` (the pinned text spells that out for the handler only), on
the same reasoning that an unidentifiable tool must not run.
Adapted tests, each because the contract changed: the `record()` helpers in both test
files and the vectors carry `toolCallBlocked: false`; the three records in the
no-inbound-record test and the R0 malformed-record loop carry the flag so they fail on
the field they name; `VERIFIER_VERSION` is "3"; every `beforeToolCall` return in R2 (a,
b), (a, silent), (c, d, e), (e, host runner) and (f) is compared to a decision object
instead of a boolean, and the `beforeToolCall(undefined)` line in (c, d, e) moved to the
decision-shape test because a non-string name now blocks and taints; D16 (c) was
rewritten for the decision contract (a card tool under a missing or mismatched session
key now blocks and taints every open turn rather than returning 0; garbage events are
`handler-error` blocks, covered in BM-2 and BM-7); D16 (f) compares the handler's return
to `{ block: false, marked: 1 }`; the reset-name regex in the ingress monotonic test
adds `unblock|untaint`; the ingress round trip asserts the new flag reads false. New
tests: `verifier.test.mjs` four (R0 missing `toolCallBlocked`, R0b withholds everything,
R0b before R1, `isWellFormedVerdict` on a blocked record) plus three blocked rows in the
completeness table (and the existing missing-flag row now carries `toolCallBlocked`);
`channel.test.mjs` seven (BM-1 mismatched session with positive
control, BM-2 hook handler errors, BM-2 per-turn seam errors and the evicted turn, BM-3
taint monotonic and not inherited, BM-4 non-card tool under a mismatched session, BM-5
gate and self-check on a blocked turn, BM-7 decision shape over garbage inputs);
`host.test.mjs` one (the emulation's `bad-decision` handling and the live seam running a
card tool exactly once). Node: 106 tests pass across the three files (94 before):
`verifier.test.mjs` 29, `channel.test.mjs` 53, `host.test.mjs` 24. Fail before, pass
after: with the runtime `.mjs` files of HEAD c6ecdbd in a scratch copy and the new tests
and test-support, 26 tests fail, all on assertions: `verifier.test.mjs` 6 of 29 (R0
`cardToolCalled` with the version pin, R0 `toolCallBlocked`, R0b withholds everything,
R0b before R1, R0b well-formedness, the completeness table), `channel.test.mjs` 19 of 53
(the ingress round trip, R2 (a, b), (a, silent), (c, d, e), (e, host runner), (f), D16
(a), (b), (c), (d), (e), (f), BM-1, BM-2 hook, BM-2 seam, BM-3, BM-4, BM-5, BM-7; the
D16 and R2 card-turn tests fail on HEAD because the fail-closed emulation treats HEAD's
boolean seam return as a `bad-decision` block, so the tool never runs there),
`host.test.mjs` 1 of 24 (the emulation test's live-seam half). The pytest wrapper passes
(2 tests) with the sibling checkout's interpreter. Docs gates pass on every changed file.
Nothing installed or configured; no commit made by the implementer.

2026-11-07, review fixes on the blocking mark — five confirmed review findings, all
addressed within the pinned design. (1, 3) The per-turn seam marked an expired turn as a
success: `markCardTool` and `blockTurn` looked the entry up without the TTL that `forTurn`
applies, so a card tool on a turn past `INGRESS_TTL_MS` answered `{ block: false, marked:
1 }`, ran, and only then had its reply withheld `untrusted-turn`. Fixed in `ingress.mjs`
by moving the TTL into `entryFor`, so `forTurn`, `markCardTool` and `blockTurn` apply one
TTL: an expired handle is untrusted for all three, the seam answers `{ block: true,
reason: "mark-failed", tainted: 0 }` (0 because the turn is already untrusted and there is
nothing left to taint), and the tool does not execute. Regression BM-8 (fake host with a
clock advanced past the TTL before the seam fires: `tool-blocked:mark-failed`, no
`tool-executed`, nothing sent, result `untrusted-turn`; a fresh turn as the positive
control; the TTL boundary on the ingress directly) plus expiry assertions in the ingress
monotonic test and BM-3. (2) A session key the host hands the hook that matches another
peer's stored, unexpired turn is accepted as a successful mark (the pinned design defines
the block by zero turns marked, so the handler cannot tell the marked turn is not the
calling one): the card tool runs, the other turn is marked, the calling turn stays
unmarked. Recorded as a residual risk in the README and under Limitations (the
handle-bound per-turn seam has no such gap; the install PR prefers it when the real event
carries turn context) and pinned by BM-9 so it is a known cost rather than a surprise; the
"mismatched key" wording in the README and Interfaces now says a key matching no open
turn. (4) The fake host's doc comment said a seam throw is `bad-decision`; the code and
the host test use `seam-threw`: comment and test title corrected. (5) The 2026-11-06
Status paragraph said four blocked cases in the completeness table; there are three new
rows plus one adapted: corrected above. Node: 108 tests pass across the three files (106
before): `verifier.test.mjs` 29, `channel.test.mjs` 55, `host.test.mjs` 24. Fail before,
pass after: with the runtime `.mjs` files of HEAD c6ecdbd in a scratch copy and the
current tests and test-support, 29 tests fail, all on assertions (zero TypeErrors):
`verifier.test.mjs` 6 of 29 (unchanged), `channel.test.mjs` 22 of 55 (the 19 listed above
plus the ingress monotonic test on the expiry assertion, BM-8 and BM-9), `host.test.mjs` 1
of 24 (unchanged). The pytest wrapper passes (2 tests) with the sibling checkout's
interpreter. Docs gates pass on every changed file. Nothing installed or configured; no
commit made by the implementer.

2026-11-07, orchestrator check before commit — the host's `before_tool_call` hook fires
for every agent session, which the review did not cover: a card tool called from a
session with no WhatsApp turn is blocked and taints every open WhatsApp turn. Pinned by
BM-10 (both withhold modes: a non-card tool from the dashboard session blocks nothing; a
card tool from it blocks `no-turn-for-session` with `tainted: 1`, the open turn's greeting
is withheld `blocked-tool-call`, a turn recorded afterwards releases its greeting);
recorded under Limitations, in the README residual risks and as owner item 19. No runtime
change. Node: 109 tests pass (`channel.test.mjs` 56). Fail before, pass after, rerun by
the orchestrator with the runtime `.mjs` files of c6ecdbd: 30 of 109 fail, all on
assertions (`verifier.test.mjs` 6, `channel.test.mjs` 23 including BM-10,
`host.test.mjs` 1).

2026-11-07, read-only host trace (owner item 19) — the owner recorded item 19 as an
installation prerequisite. It requires trusted binding to the originating turn and peer
before a card tool executes, and proof that refusing a dashboard card call leaves
concurrent WhatsApp turns unaffected. Both regressions go to the install PR.

The orchestrator traced OpenClaw 2026.9.5's `before_tool_call` contract, the channel
metadata in the hook context, the session-key formats and run isolation. It used four
tracers, a skeptic per tracer that re-read every citation, and a synthesis, then
re-checked itself the block directive, the context allowlist, run-id minting, the
bundled-MCP hook context, the dmScope default and the runtime-policy key. It read host
code only, with no config, session store or credential, and wrote nothing outside this
branch.

Result:
- Host side: a refused call is vetoed before execution and affects only that call.
- Skeleton side: the shipped handler fails both requirements. It admits a call on a
  session key, which callers supply and which names a conversation, not a turn (BM-9).
  It taints every open turn of every peer on a refusal (BM-10). It returns `reason`
  where the host reads `blockReason`.

The requirements, the binding design (a channel-issued run id per inbound, mapped to the
turn handle), both regressions and three open points are under "Install prerequisites
(owner item 19)". The open points are: run-id-only binding on the bundled-MCP path,
follow-up and steered turns, and the scope of a correlation-failure withhold. The
host's untraced remainder is in the EVIDENCE_LOG entry.

No runtime change on this branch. Nothing was installed, registered or configured, and
no paid call was made. Transport and credentials remain a separate decision.

2026-11-07, revision 6: run binding, one active turn per peer, release only on own-turn
support. This implements owner decision 19 (a), (b) and (c), decided the same day ("Proceed
with the offline binding tests. These are installation requirements."). It is offline
only.

What changed:
- The channel mints a run id per admitted inbound and passes
  `replyOptions: { runId, onAgentRunStart }`. The callback confirms the run only for the
  exact issued id and returns `undefined`. The run ends in a `finally` around `runInbound`.
- `createBeforeToolCallHandler` admits a card call per run id through
  `ingress.admitCardCall` and marks that turn only. Otherwise it refuses that call with
  `{ block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason }`.
- Removed: the per-turn `beforeToolCall` seam, `markCardTool`, `markCardToolForSession`,
  `blockTurn`, `blockOpenTurns` and `toolCallBlocked`.
- `VERIFIER_VERSION` is "4". R0b withholds `unbound-turn`, R1 withholds
  `card-without-trusted-call`, and `isWellFormedVerdict` requires `runBound`.
- One active turn per peer: an overlap gets `BUSY_TEXT` through the one
  `transport.sendText(` call site (now in a private `transmit`).
- The fake host emulates the traced run-id flow, the hook shapes and the
  `block`/`blockReason` directive, and lets a test hold runs open and fire dashboard calls.

Review of revision 6 (same date), seven findings, all confirmed and fixed:
- Fixed (medium): the one-active-turn gate failed open on capacity eviction. With
  `maxEntries` other peers writing while P1's run was open, P1's records were evicted and
  P1's next message was dispatched into a second run on the same key. `hasActiveTurn` now
  reads an active index kept apart from the record store; only `endRun` or the TTL removes
  an entry. An evicted active turn keeps its peer busy and fails closed meanwhile: card
  calls are refused `turn-expired` and replies are untrusted. Pinned by RA-6 and the
  ingress run-binding unit test.
- Fixed (medium): `isCardTool` missed the host's `-N` collision suffix
  (`idx__search_listings-2`), so such a call ran with no admission check and left its turn
  ordinary. The suffix is now stripped from the last segment before comparing. Pinned by
  the `isCardTool` table (suffix, 64-character names, near-miss negatives) and D16 (f): the
  handler refuses those spellings `unknown-run` with no run and admits them on a
  confirmed run. A name cut inside its tool segment by the host's 64-character cap is
  still not recognised. The install PR asserts the literal host names at startup (added
  under "Install prerequisites").
- Fixed (medium, tests): no test sent two same-peer inbounds in the same tick, so a
  mutant awaiting between the busy check and the record passed. RA-5 now fires both before
  awaiting either, in both modes, and the mutant fails it on an assertion.
- Fixed (low, tests): RB-3's array requester had no `channel`, so removing the
  `Array.isArray` guard passed. The case now carries every expected field, and the mutant
  fails RB-3.
- Fixed (low, tests): RI-2 and RI-3 now run in both withhold modes with P1 and P2 active.
  RI-3 checks that both records are unchanged and both greetings release.
- Fixed (low, docs): the host-facts sentence that had been split into the install-PR
  list is its own paragraph again, and the stale "Nothing here changes this branch's
  runtime" is reworded.
- Fixed (low, docs): item 16 and the 2026-11-06 blocking-mark Status entry are annotated
  as superseded by decision 19 (c). Item 20 now lists the release-after-refusal behaviour
  for the owner to confirm.
Each new or tightened regression was checked against a scratch mutant: active check on
the record store (RA-6 and the unit test fail), no suffix strip (the `isCardTool` table
and D16 (f) fail), an await before `resolveRoute` (RA-5 fails), and no array guard (RB-3
fails). Each fails on an assertion, not a timeout.

Node: 121 tests pass (`verifier.test.mjs` 30, `channel.test.mjs` 66, `host.test.mjs` 25).

Fail before, pass after. In a scratch copy holding the runtime `.mjs` files of d6daad2 with
the new tests and test-support, 93 of 121 do not pass:
- `verifier.test.mjs`: 29 of 30
- `channel.test.mjs`: 52 of 66. 51 fail, and RA-1 hits its 5 s timeout because the old
  runtime has no busy path, so the second message enters the held run.
- `host.test.mjs`: 12 of 25

There are no import errors. 51 failures are on assertions, among them:
- RB-1, RB-3, RB-4, RI-1, RI-2, RI-3, RA-3, RA-4, RA-5 and RA-6
- D16 (f), the `isCardTool` table and the ingress run-binding unit test
- the rewritten BM-1, BM-2, BM-7 and BM-8
- the verifier R0, R0b, RS-1 and RS-2 tests, and the D19 source test

41 are TypeErrors raised in test setup that calls the new `ingress.confirmRun` or reads
`turn.replyOptions`, which the old runtime lacks (RB-5 and RS-1 among them). One is the
RA-1 timeout. RB-2 and RA-2 pass on the old runtime too. They are positive cases (a
matching requester admitted, another peer unaffected) that the old session-keyed handler
also satisfies.

The pytest wrapper passes (2 tests). The docs gates (forbidden_paths, pii_scan,
confidential_text) pass on every changed file.

Owner choices are flagged as item 20. The retired and rewritten tests are listed under
Tests required. Remaining install-PR items are under "Install prerequisites". Nothing was
installed, registered or configured, no paid call was made, and the implementer made no
commit.

2026-11-07, revision 7: a refused card call tied to its own turn withholds that turn.
This implements owner decision 21 (item 21), decided the same day. It is offline only.

What changed:
- `ingress.mjs`: records gain `cardCallRefused`. It is false at record time, monotonic,
  never inherited, and in the frozen snapshot. `admitCardCall` sets it on the one entry
  its run id names when the refusal comes after the session-key check (today only
  `requester-mismatch`), and answers `withheld: true`. Earlier refusals answer as before
  and change nothing.
- `channel.mjs`: refusals carry `withheld: 0 | 1`. The value is 1 only for a strict
  `withheld === true` from the ingress. `handler-error` and the handler-side `unknown-run`
  are 0.
- `verifier.mjs`:
  - `VERIFIER_VERSION` is "5"
  - `isInboundRecord` requires the new boolean
  - R0c `card-call-refused` sits after R0b and before R1
  - `isWellFormedVerdict` accepts no release when `cardCallRefused !== false`
- `self-check.mjs`: four new vectors.
- `test-support/host-emulation.mjs`: a per-call `requester` on a run's tool request, and
  `noRunId` for dashboard-style calls.
- `outbound.mjs`: unchanged. A withhold on a recorded turn already sends `SAFE_TEXT` in
  safe-text mode and nothing in silent mode.

Node: 141 tests pass (`verifier.test.mjs` 36, `channel.test.mjs` 78, `host.test.mjs` 27),
up from 121.

Fail before, pass after. In a scratch copy holding the runtime `.mjs` files of dd2aa6a with
the new tests and test-support, 25 of 141 fail, all on assertions, with no TypeErrors,
import errors or timeouts:
- `verifier.test.mjs`: 7 of 36. These are R0 `cardCallRefused`, R0c, RW-1, RW-2, RW-units
  `isWellFormedVerdict`, the version pin in R0 `cardToolCalled`, and the completeness
  table.
- `channel.test.mjs`: 17 of 78. These are RW-1, RW-1c, RW-2, RW-3, RW-4, RI-4, the four
  RW-units tests, the rewritten RB-3, BM-1, BM-2, BM-7, BM-8 and D16 (f), and the ingress
  snapshot-keys test.
- `host.test.mjs`: 1 of 27, the D21 source test.

Some new tests pass on the old runtime by design:
- RW-1b and RW-1d are controls that pin ordinary-turn and card-turn behaviour.
- R0c ordering holds because R0 and R0b were already first.
- The emulation test exercises test-support only.

The pytest wrapper passes (2 tests). The docs gates (forbidden_paths, pii_scan,
confidential_text) pass on every changed file.

Standing, per item 21: re-request review on #181 after CI passes; that is the
orchestrator's step. #179 stays on hold and installation stays paused. Nothing was
installed, registered or configured, no paid call or network was used, and the
implementer made no commit.
