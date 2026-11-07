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
  `(accountId, peer)` with the session key and turn id, and the inbound reply
  `deliver` callback is routed into the same `outbound.sendText` the message tool,
  cron, heartbeat and CLI reach through the registry.
- `outbound.mjs`: the gate. `normalizePayload({ payload, cfg, accountId })` (the host's
  envelope, idempotent) admits `text` and `replyToId` only; any present content field
  other than text refuses the whole payload, caption included. `sendText(ctx)` looks up
  the peer's current inbound record, runs the verifier under a wall-clock deadline,
  rejects a thrown, late or malformed verdict, and sends only sealed text through the
  single `transport.sendText(` call in the runtime. A transport error propagates and is
  never retried here. One audit line per call carries outcome, reason, rule, whether a
  record existed and the text length; never the text, the peer or the session key.
- `verifier.mjs`: pure, synchronous policy (below). `card-resolver.mjs`: the null
  resolver (withholds every card token). `ingress.mjs`: bounded, expiring records and
  peer id canonicalisation. `transport.mjs`: the interface the real transport will
  implement and the default that rejects everything. `constants.mjs`.
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

## Verifier policy (skeleton, open for owner review)
`verifyReply({ text, inbound, resolver })` is pure and synchronous. Rules apply in order;
the first match decides. A figure is a maximal run of Unicode decimal digits, compared
whole: `34` never passes on the strength of `3` and `4`; `1,240` is the two runs `1` and
`240`.

- R0: not a string, empty, longer than 4000 characters, or no inbound record for the peer
  (unknown session, nothing recorded, expired) -> withhold.
- R1 cards: if any fragment of `[[card:<ref>]]` appears, the text must consist of
  complete tokens and whitespace only (no prose beside a card, no duplicate ref, no
  partial or re-spelled token). Each ref is resolved for this session and turn; a null
  result (the default resolver always returns null) withholds `unknown-token`; the
  release text is the input with each token replaced by the resolver's bytes exactly.
- R2: no figures -> release unchanged. Greetings, apologies, digit-free clarifications.
- R3: every figure appears in the user's inbound text for the turn -> release unchanged.
  "Do you mean 3 or 4 bedrooms?" after "3 or 4" passes.
- R4: otherwise withhold `unverified-figures`.

Gate-side, outside the verifier: a throw -> `verifier-threw`; wall time over the
deadline (250 ms, measured around the call with `performance.now`) -> `verifier-deadline`
even if the verdict said release; anything that is not a well-formed verdict (wrong kind,
text altered without being a card verdict for a token-only input, a Promise or thenable)
-> `verifier-malformed`.

Known withholds under this policy, by design until a token path exists: numbered lists,
"24/7", office hours, years, step numbers, tool clarifications and error notices that
carry digits (`isError` is not visible in the `sendText` context). Number words pass.
Thousands separators make the policy stricter, not looser.

## Withheld-reply default (owner decision pending)
`WITHHOLD_MODE = "safe-text"`: when the peer has a current inbound record, a withheld
reply becomes the single constant `SAFE_TEXT` ("I couldn't send that reply safely.
Please ask again."). When no record exists (an unsolicited tool, cron or heartbeat send
to a peer who has not written), the result is `{ outcome: "not_sent" }` and nothing goes
out. `"silent"` everywhere is one constant away. The inbound `deliver` reports a withhold
to the dispatcher as `{ visibleReplySent: false, suppression: { reason } }` so the host
records it as not visible rather than as a delivered reply.

## Residual risks
- The self-check sees the config at registration only. Removing the deny and restarting
  brings the stock plugin back; a runbook note (later PR) covers it, the host does not.
- Ingress records live in process memory. A send from another process (CLI) or after a
  restart finds no record and is withheld; a late reply (TTL 30 min) is withheld. Fail
  closed, but silent. `deliveryMode: "gateway"` keeps CLI sends in the gateway process.
- A verifier that never returns stalls that session's serialized reply queue (the
  dispatcher awaits `deliver`); nothing is sent, but the turn is lost. A worker-thread
  verifier is the future fix.
- `channelConfigs.whatsapp.schema` is permissive because it validates the operator's
  existing `channels.whatsapp` section; the skeleton validates no channel config.
- Host behaviour (deny, first-wins registration, dispatcher outcomes) is emulated from
  cited lines in `test-support/host-emulation.mjs`, not exercised against the host.
