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
- `verifyReply({ text, inbound, resolver }) -> Verdict`; `isWellFormedVerdict(value, inputText)`;
  `digitRuns(text)`.
- `CardResolver.resolve(ref, { sessionKey, turnId }) -> { text } | null`; `nullCardResolver`.
- `Transport`: `start`, `sendText`, `stop`, `isConfigured`; `unavailableTransport`.
- `createIngress({ now, ttlMs, maxEntries })`: `key`, `record`, `current`, `size`;
  `normalizePeerId(to)`.
- `createOutbound({ transport, ingress, verify, cardResolver, clock, deadlineMs, withholdMode, log })`
  -> `{ deliveryMode: "gateway", textChunkLimit: 4000, normalizePayload, sendText }`.
- `selfCheck(cfg) -> { ok: true } | { ok: false, reason }`; `SELF_TEST_VECTORS`.
- `createChannelPlugin(deps)` -> the channel object; `index.mjs` default export with
  `register(api)`.

## Safety requirements
- Verification failure never sends raw model text and never falls back to the stock
  plugin: a throw, a late verdict, a malformed verdict, a non-text payload, an unknown or
  stale card token, or no inbound record all withhold.
- Exactly one `transport.sendText(` call expression in the runtime, after the seal.
- The plugin refuses to register unless the host config denies `whatsapp`.
- No text, peer id or session key in logs. Synthetic data only in tests (555 numbers).
- No new dependency; no vendor source in the repo.

## Tests required
`verifier.test.mjs` (policy and card vectors, well-formedness), `channel.test.mjs`
(fail-closed gate behaviour, payload normalization, ingress, self-check, register modes,
default transport, end to end on the fake transport), `host.test.mjs` (source tests:
static import, single call site, allowed transport members, no default export outside
`index.mjs`; a Proxy transport; the missing-verifier and bad-verifier module tests in a
temp copy; the emulated deny/first-wins, dispatcher and registry checks; the same
outbound for tool, cron and heartbeat shapes). `tests/test_whatsapp_channel_skeleton.py`
runs them and checks the manifest without Node.

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
- Tool, cron and heartbeat sends carry no session key; they bind to the peer's current
  turn by `(accountId, canonical peer)`. The host's `to` spelling for these callers was
  not traced; `normalizePeerId` covers the common spellings, and a
  `messaging.normalizeTarget` is an install-PR item (core honours it for bundled plugins
  only).
- Policy gaps: digit-bearing tool clarifications and error notices are withheld; number
  words pass; `isError` is invisible to `sendText`; no chunker, so texts over 4000
  characters are withheld.
- The self-check reads the registration-time config only.
- Groups, channels, threads, media, polls, reactions, receipts, typing, QR, auth: out of
  scope.
- WO-036 and ADR-0015 live on #179's branch; a later merge may need a cross-reference
  pass.

## Owner decisions (pending)
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
