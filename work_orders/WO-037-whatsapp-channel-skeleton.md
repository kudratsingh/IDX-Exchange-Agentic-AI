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
  `isWellFormedVerdict(value, inputText, inbound)` (no release is well-formed on a blocked
  turn); `digitRuns(text)`; `isInboundRecord` (requires a boolean `cardToolCalled` and a
  boolean `toolCallBlocked`); `VERIFIER_VERSION = "3"`. Rule R0b withholds everything on
  a blocked turn as `blocked-tool-call`, before R1.
- `CardResolver.resolve(ref, { sessionKey, turnId }) -> { text } | null`; `nullCardResolver`.
- `Transport`: `start`, `sendText`, `stop`, `isConfigured`; `unavailableTransport`.
- `createIngress({ now, ttlMs, maxEntries, turnsPerPeer })`: `key`, `record(key, rec) ->
  TurnHandle` (frozen `{ turnId, key }`, identity mapped to its entry by an instance-private WeakMap),
  `forTurn(key, handle)` (trusted handle only; a string or look-alike object yields
  null; the only record read, there is no `current` or any lookup by key alone),
  `markCardTool(handle, toolName) -> boolean`,
  `markCardToolForSession(sessionKey, toolName) -> count`,
  `blockTurn(handle) -> boolean` (taints the one turn a trusted handle names; false for an
  untrusted, evicted or expired one, since `forTurn`, `markCardTool` and `blockTurn`
  apply one TTL),
  `blockOpenTurns() -> count` (taints every stored, unexpired turn of every peer), `size`;
  `normalizePeerId(to)`
  (`whatsapp:` prefix and the phone-number JID suffixes fold to `+<digits>`; `@lid` stays
  `<digits>@lid`, a separate namespace; canonical ids are fixed points). The handle maps,
  by identity, to the one stored entry it was minted for, so two records with the same
  turn id are two turns with two handles. Records carry `cardToolCalled` and
  `toolCallBlocked`, both false at record time, monotonic (set only, never cleared) and
  never inherited by a later turn.
  Turn ids are channel-generated (`randomUUID`); the peer's message id reaches
  `runInbound` as `messageId` metadata only.
- `constants.mjs`: `CARD_TOOLS` (mirrors the server's one-copy tools, spelled as the
  server names them) and `isCardTool(name)`, which fails closed on spelling: the exact
  name, or any name whose trimmed, lowercased last segment after a namespace separator
  (`__`, `.`, `/`, `:`) is a `CARD_TOOLS` name (the host's `idx__search_listings`,
  ADR-0003), is a card tool; a name that differs otherwise is not.
- `createOutbound({ transport, ingress, verify, cardResolver, clock, deadlineMs, withholdMode, log })`
  -> `{ deliveryMode: "gateway", textChunkLimit: 4000, normalizePayload, sendText }`.
  `sendText(ctx)` binds only through `ctx.turn` (a TurnHandle): any `turnId` is withheld
  `untrusted-turn`; no `turn` at all is withheld `no-turn-handle`; a handle `forTurn`
  does not recognise is `untrusted-turn`. Each of these sends nothing (no `SAFE_TEXT`)
  and audits `hasRecord: false, boundToTurn: false`. There is no other binding path and
  no fallback to the peer's newest turn (decision 17). Each context field is read once, up front;
  `to` must be a non-empty string (else `bad-destination`, nothing sent) and the
  transport receives the canonical peer id the record was looked up under, never
  `ctx.to`. A `SAFE_TEXT` send returns `{ messageId, withheld: reason }`.
- The turn object passed to `runInbound` carries `turnId` (string), `messageId`,
  `deliver` and `beforeToolCall(toolName) -> ToolCallDecision` (named for the host event
  it is fired from, before the tool executes); never the handle. The decision is
  `{ block: false, marked: 0 }` for a non-card name, `{ block: false, marked: 1 }` when
  the trusted mark landed on this turn, `{ block: true, reason: "mark-failed", tainted }`
  when the mark failed (handle no longer trusted: evicted or past the ingress TTL;
  `blockTurn(handle)` first, `tainted` 1, or 0 for a turn that is gone or expired and so
  already untrusted), and `{ block: true, reason: "handler-error", tainted }` for a
  non-string name or any throw (`blockTurn` in its own try/catch). Never throws, never
  returns a bare number or boolean.
- `createBeforeToolCallHandler(ingress) -> (event, ctx) => ToolCallDecision`: the
  function the install PR registers with the host's `before_tool_call` hook (fires before
  execution). `{ block: false, marked: 0 }` for a non-card tool name (a string
  `isCardTool` rejects); `{ block: false, marked: n }`, n >= 1, when
  `markCardToolForSession(ctx.sessionKey, event.toolName)` marked at least one open turn;
  `{ block: true, reason: "no-turn-for-session", tainted: m }` when a card tool marked no
  turn (unknown session key, a key mismatched to every stored turn, non-string key, no
  open turn), after `ingress.blockOpenTurns()` tainted every open turn of every peer (m
  is its count; a key that matches some other peer's open turn is accepted as a mark on
  that turn, see Limitations);
  `{ block: true, reason: "handler-error", tainted: m }` when anything throws inside the
  handler or the tool name is not a string (the tool cannot be identified, so it is
  blocked whatever its kind), after `blockOpenTurns()` in its own try/catch (m is -1 if
  that threw too). Never throws, never returns a bare number. The host's hook runner is
  fail-closed on a throw (survey); the exact block directive it reads is untraced, so the
  install PR maps `{ block: true }` onto it and proves with one real event that a blocked
  card tool does not execute. Not registered by `index.mjs` (install-PR item).
- `selfCheck(cfg) -> { ok: true } | { ok: false, reason }`; `SELF_TEST_VECTORS`.
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
  host's spelling as well as the server's (`isCardTool`), so a namespace prefix, case or
  padding cannot skip the mark; over-marking is the accepted direction.
- A turn that called a card tool (`cardToolCalled`) releases only fully resolved card
  tokens; the flag is monotonic and no API clears it. Ordinary turns keep greetings and
  clarifications.
- A card tool executes only after a successful trusted mark; a correlation failure or
  handler error blocks execution and taints the affected turns (`toolCallBlocked`,
  monotonic, never inherited), and every reply on a tainted turn is withheld
  `blocked-tool-call`, card tokens included. When the affected turn cannot be identified
  (the hook's session key matches no open turn, or the event is unreadable) every open
  turn of every peer is tainted: failing closed across peers is the accepted cost.
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
- The card-tool mark is not yet registered with the host: `beforeToolCall` is the
  per-turn seam on the turn object and `createBeforeToolCallHandler` the hook-shaped
  function the install PR registers with `before_tool_call` (decision 16; the hook
  signature is unverified, so `index.mjs` registers nothing). The mark fires before the
  tool executes and is monotonic, so a failed card call leaves it in place; a card tool
  whose mark could not be applied is blocked by the seam's decision and its turn tainted
  (`toolCallBlocked`), so every reply on it is withheld; a call the hook misses leaves
  that turn on the ordinary rules. The tool name is matched in the host's spelling as
  well as the server's, but the field and spelling the real event carries are untraced:
  the install PR captures one real `before_tool_call` event per `CARD_TOOLS` tool and
  asserts the handler marks it, and maps the decision's `{ block: true }` onto the block
  directive the host's hook runner reads (untraced; only the fail-closed treatment of a
  throw was surveyed), proving with one real event that a blocked card tool does not
  execute, before registering it.
- A correlation failure in the hook handler (a card tool under a session key that matches
  no open turn, or an unreadable event) taints every open turn of every peer, because the
  affected turn cannot be identified. Each such peer's in-flight replies become
  `SAFE_TEXT` (or silence); their next messages start untainted turns. Accepted cost of
  failing closed; a quiet gateway taints nothing and a non-card tool never taints.
- The hook handler trusts the host's session key. A key that matches another peer's
  stored, unexpired turn is indistinguishable from a correct one: the mark lands on that
  other turn, the handler answers `{ block: false, marked: 1 }`, the card tool runs, and
  the calling turn stays unmarked (its digit-free prose releases under R2; the other
  peer's next reply on the marked turn is held to card tokens). Only a key matching no
  open turn blocks. Card bytes never cross peers (tokens resolve against the calling turn
  only) and invented figures are still withheld by R4. Pinned by BM-9 as a known cost.
  The per-turn seam is handle-bound and has no such gap, so the install PR prefers it for
  the mark whenever the real `before_tool_call` event carries turn context, with the
  session-keyed handler as the fallback.
- The host hook fires for every agent session. A card tool called from a session with no
  WhatsApp turn (dashboard, alert or cron run) is blocked `no-turn-for-session` and taints
  every open WhatsApp turn at that moment; their in-flight replies, greetings included,
  are withheld `blocked-tool-call`. Later turns start untainted; non-card tools block
  nothing. Pinned by BM-10; the scoping question is owner item 19.
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
19. Card tools from sessions outside this channel (pending, raised 2026-11-07). The hook
    handler blocks them and taints every open WhatsApp turn (shipped, fail closed, BM-10).
    Options: keep that; or scope the handler to this channel's sessions so a dashboard or
    alert card call is blocked (or allowed) without tainting WhatsApp turns, which needs
    the host's session-key format traced first; or leave non-WhatsApp sessions to their
    own guard. A related host-trust case: a key naming another peer's open turn is
    accepted as a successful mark (BM-9); the install PR prefers the handle-bound per-turn
    seam where the real event carries turn context.

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
and the affected reply withheld when correlation or marking fails. Implemented as:
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
