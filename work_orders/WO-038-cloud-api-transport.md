# WO-038 — WhatsApp Cloud API transport for the owned channel, offline only

**Driver:** agent (module, tests, docs); owner (every decision below, credentials, the
tunnel, the install PR approval, the live smoke test)
**Depends on:** WO-037 (owned channel, PR #183 at 25c4aa2); ADR-0016;
`docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md`; `docs/WHATSAPP_TRANSPORT_RECOMMENDATION.md`
**Decision record:** ADR-0017 (proposed, flagged for the owner)

Owner instruction, verbatim: "Prepare the Cloud API adapter offline in parallel. Keep
credentials and the five-message live smoke test for separate approval after confirming
brokerage and IDX permissions and hosted-model data handling. WhatsApp Business
Messaging Policy"

## Objective
A Cloud API implementation of the channel's `Transport` seam and a signed-webhook
handler for inbound text, proven offline with fakes, so that once the owner approves,
the install PR only has to supply owner-held config, register one route and open a
tunnel. Nothing is wired: `index.mjs` still ships `unavailableTransport`.

## In scope (offline only)
1. `extensions/idx-whatsapp-channel/cloud-api-transport.mjs`: `createCloudApiTransport`,
   `createCloudApiWebhook`, `createHttpRouteHandler`, `readCloudApiConfig`,
   `signatureValid` and the constants they use. Node built-ins (`node:crypto`,
   `node:buffer`) and `./ingress.mjs` (`normalizePeerId`) only.
2. `extensions/idx-whatsapp-channel/cloud-api.test.mjs` (28 tests, fakes only).
3. Test plumbing for a staged module: `host.test.mjs` (runtime file set, PKG-2) and
   `tests/test_whatsapp_channel_skeleton.py` (`NODE_TESTS`, package shape) learn one
   named staged file that every source scan covers but `files` and the entry's import
   closure leave out.
4. This work order, ADR-0017 (proposed) and a short README section.

## Out of scope (each held for separate written owner approval)
Held until the owner has confirmed brokerage and IDX permissions and hosted-model data
handling (eligibility doc Q2, Q4, Q6):
- any credential: Meta app, system-user token, app secret, verify token, phone-number id,
  WhatsApp business account id, two-step PIN; no sign-up, no console step;
- number registration or display-name setup;
- the public tunnel, its certificate, and the webhook subscription in Meta's console;
- any live send, and the five-message smoke test (recommendation section 4);
- wiring the transport into `index.mjs`, registering the route, adding the module to the
  package `files`, and any config schema change (the install PR);
- templates, proactive sends (item 18), media, groups, read receipts, typing indicators.
No network was used except reading Meta's public developer docs and policy page; no
Graph API endpoint was called; no paid call; synthetic 555 numbers and placeholder ids
only.

## Interfaces
`createCloudApiTransport({ config, fetch, now?, log?, windowMs?, webhookOptions? })`
returns a frozen object: `start`, `sendText`, `stop`, `isConfigured` (the `Transport`
seam, which is all the channel touches) and `webhook` (`path`, `handle`, `routeHandler`)
for the install to register.
- `config` (injected object only, never a file or the environment): `phoneNumberId`
  (5-32 digits), `graphApiVersion` (`vN.N`), `accessToken` (32-4096 token characters),
  `appSecret` (16-256 letters and digits), `verifyToken` (16-256 printable, no spaces),
  `webhookPath` (absolute, 1-8 plain segments, no dot segments, query or double slash),
  optional `accountId`, which may only be `"default"`: the channel lists and starts that
  one account alone (`listAccountIds`), so any other value would leave `start` refusing
  and the webhook answering 503 forever; it makes the config unusable instead, and
  `isConfigured()` reports false. More accounts need a channel change first. Each field is
  read once; the verify token may not equal either real secret, since it travels in a
  query string.
- `isConfigured()`: true only for a fully plausible config and an injected `fetch`.
- `start({ accountId, signal, onInbound })`: rejects when unconfigured, without a sink or
  for another account; otherwise holds the sink and stays pending until `signal` aborts
  (or `stop()`); an already-aborted signal resolves at once. A newer start takes over the
  sink; an older one resolves on its own signal.
- `sendText({ accountId, to, text, signal })`: refuses locally (no request) when
  unconfigured, for another account, for empty or over-4096 text, for a peer that is not
  canonical `+<digits>` (a `@lid` peer is refused), and when the peer's last inbound
  (Meta's message time) is unknown or older than `windowMs` (default 24 h). Otherwise one
  `fetch` POST to `https://graph.facebook.com/<GRAPH_API_VERSION>/<PHONE_NUMBER_ID>/messages`
  with `authorization: Bearer <ACCESS_TOKEN>`, `content-type: application/json`,
  `redirect: "error"`, the caller's `signal`, and body `{ messaging_product: "whatsapp",
  recipient_type: "individual", to: <digits>, type: "text", text: { preview_url: false,
  body } }`. Never retried. A non-2xx answer or a network failure throws `CloudApiError`
  whose message is `idx-whatsapp-channel: cloud api: <reason>` plus at most the HTTP status
  and Meta's numeric code (reasons: `api-error`, `outside-customer-service-window` for
  code 131047, `network-error`, `aborted`); never the token, the body, the recipient or
  Meta's error text. A 2xx returns `{ messageId }` from `messages[0].id`, or `{}` when
  none is usable (the gate then audits a sent-without-id and throws, as today). A 2xx
  means Meta accepted the request, not that the user got it: 131047 and other delivery
  errors (131026 undeliverable, 131049 ecosystem limit) may arrive only later, as a
  `failed` status on the webhook [M5, M6], so the outbound audit's "sent" means
  "accepted by Meta". The webhook warns on each such status (below); nothing feeds it back
  to the gate or the licensed human yet (decision 9).
- Window table: one last-inbound time per peer, at most 1024 peers, oldest-touched
  evicted. A peer whose inbound the channel's sink is still handling (its turn is
  running) is pinned and never evicted, so senders the allowlist drops, whose sink call
  settles at once, cannot close an admitted peer's window mid-turn. Entries past
  `windowMs` are pruned first. Pinned entries are bounded by inbounds in flight.
- `createCloudApiWebhook({ config, onInbound, now?, log?, isReady?, maxBodyBytes?,
  maxInboundAgeMs?, dedupeTtlMs?, dedupeMaxEntries? })` returns `{ path, maxBodyBytes,
  handle }`; `handle({ method, url, headers, body })` is synchronous and returns
  `{ status, headers, body }`:
  - GET on the path: 200 echoing `hub.challenge` as `text/plain` only when `hub.mode` is
    `subscribe`, the verify token matches (SHA-256 digests compared with
    `timingSafeEqual`, so neither content nor length leaks) and the challenge is 1-256
    printable characters; else 403.
  - POST on the path: 413 over the body limit (default 1 MiB); 401 unless
    `X-Hub-Signature-256` is `sha256=` plus 64 hex characters equal, in constant time, to
    HMAC-SHA256 of the raw bytes keyed with the app secret (checked before any decode or
    parse); 503 with `retry-after` while no `start` is active; 400 for bytes that are not
    UTF-8 JSON; else 200.
  - Read from a 200: only `object: "whatsapp_business_account"`, `field: "messages"`,
    `messaging_product: "whatsapp"` changes whose `metadata.phone_number_id` equals the
    configured id; from them only `type: "text"` messages with a 7-15 digit `from`, a
    non-empty body of at most 65,536 UTF-16 code units (our cap,
    `CLOUD_INBOUND_TEXT_MAX_LENGTH`; Meta states no inbound maximum [M4], and 4096 is the
    send limit only [M3]; a longer body is dropped with an `inbound-dropped` /
    `too-long` warning), an id, no `group_id`, and a timestamp
    neither more than 5 minutes ahead nor older than `maxInboundAgeMs` (default 30 min),
    whose id was not seen within the dedupe TTL (default 24 h, at most 4096 ids). Each
    goes to `onInbound({ accountId, peerId: "+<digits>", text, messageId, receivedAt })`,
    frozen, without being awaited. Statuses, other types, username-only senders (no
    `from`), stale and malformed messages are acknowledged and dropped. Each `failed`
    status also logs one warning, `{ event: "send-failed-async", reason, apiCode? }`,
    with `reason` `outside-customer-service-window` for code 131047 and
    `delivery-failed` otherwise, and `apiCode` only when `errors[0].code` is a safe
    integer; never the wamid, the recipient or Meta's text.
  - Any other method 405; any other path 404; an unusable config 404 for everything.
- `createHttpRouteHandler(webhook, { readTimeoutMs?, idleTimeoutMs?, maxConcurrentReads? })`:
  the host route handler `(req, res) => Promise<true>`. Before reading a POST body it
  answers 413 for a declared oversize body, 401 when `X-Hub-Signature-256` is missing or
  not `sha256=` plus 64 hex characters, and 503 with `retry-after: 5` when
  `maxConcurrentReads` (default 8) bodies are already being read, so an unsigned request
  is never buffered and open connections hold at most 8 bodies (8 MiB) between them. It
  then reads the raw stream with listeners: 413 for a streamed oversize body, 408 after
  `readTimeoutMs` (default 10 s) or after `idleTimeoutMs` (default 2 s) without a chunk.
  Every early answer carries `connection: close`. The HMAC itself is checked by
  `handle`. It never throws.
- Logs: `{ component: "idx-whatsapp-channel.cloud-api", event, reason?, delivered?,
  ignored?, status?, apiCode? }` only (events include `send-failed`,
  `send-failed-async`, `inbound-dropped`, `webhook-accepted`, `webhook-rejected`).

## Wiring plan for the install PR (not done here)
1. Config source, owner decision (the agent never sees the values). Options: (a) an
   owner-created JSON file outside the repo and outside `~/.openclaw`, mode 600, whose
   path is the only new plugin-config key, read once at register with `node:fs`; (b) the
   gateway process environment set by the owner's launch agent; (c) host SecretRefs. The
   host warns that plaintext in agent-readable files such as `openclaw.json` stays
   exposed (docs/gateway/secrets.md:19), which rules out putting the token in plugin
   config. Option (c) needs `openclaw/plugin-sdk/secret-ref-runtime`
   (docs/plugins/sdk-subpaths.md:270), which breaks the built-ins-only rule, so it would
   need its own approval.
2. One transport per process. The host registers this plugin from more than one module
   copy (WO-037, real-host replay). A static same-plugin route registration replaces the
   earlier one (gateway-routes.md:45; loader :2900-2906), and only one copy's channel
   starts. If each copy built its own transport, the route could feed one that was never
   started, so every POST would get 503. The install keeps the transport behind a
   process-wide frozen key, as `processIngress` does for the ingress. It then passes it
   to `createPluginEntry({ transport })` and registers
   `api.registerHttpRoute({ path: cloud.webhook.path, auth: "plugin", match: "exact",
   handler: cloud.webhook.routeHandler })` before `registerChannel`, only in the modes that
   expose the method ("full", "discovery"; not in "setup-only").
3. The allowlist, one-active-turn rule, verifier and outbound gate stay exactly as they
   are and run in front: the webhook only feeds `onInbound`, and the transport only
   sends sealed text the gate hands it. `sendText` keeps its own 24-hour refusal as
   defence in depth.
4. Public HTTPS (owner-run): Meta needs a public URL with a valid, not self-signed
   certificate. The gateway binds loopback, so the owner runs a tunnel (for example a
   named Cloudflare Tunnel or Tailscale Funnel) to the gateway port. It should forward only
   `<WEBHOOK_PATH>` and only GET and POST, so the dashboard and other routes stay off the
   internet. If the chosen tunnel cannot restrict by path, the fallback is a separate
   loopback listener for the webhook alone (ADR-0017). The tunnel's own access logs see the
   verify token in the GET query once at subscription; the owner should rotate it after
   subscribing if the logs are kept.
5. Rollback: stop the tunnel, unsubscribe the webhook, revoke the token, then runbook 4.

## Host facts (OpenClaw 2026.9.5, read only, never run; sha256-12 in brackets)
- `api.registerHttpRoute(params)`: `{ path, handler, auth: "gateway" | "plugin", match?:
  "exact" | "prefix", handleUpgrade?, gatewayRuntimeScopeSurface?, nodeCapability?,
  replaceExisting? }`. The handler is `(req: IncomingMessage, res: ServerResponse) =>
  Promise<boolean | void> | boolean | void` (dist/api-DArLOVCi.d.ts:7316-7333, :35287
  [7decea02a45e]).
- Auth must be explicit. `"plugin"` is for plugin-managed signature checks and gets no
  operator scopes. Routes that overlap at different auth levels are rejected. A static
  same-plugin registration replaces the earlier one
  (docs/plugins/architecture-internals/gateway-routes.md:32-52 [df238dd9a4d2]). The
  channel-plugin guide shows a webhook on `auth: "plugin"` that verifies its own
  signature (docs/plugins/sdk-channel-plugins.md:429-437 [7863cbed7dde]).
- Path rules: the path is trimmed and given a leading `/`. A missing path is a
  registration warning, and a bad auth or a foreign-owned path is an error
  (dist/http-route-overlap-CYyCb1q8.mjs:5-13 [36ceb65e37c4];
  dist/loader-runtime-load-CdQ5OcQq.mjs:2869-2906 [91180d699f64]). The method is exposed
  in "full", "discovery" and "tool-discovery" through the bound registrars, and in
  "setup-runtime" (same file :1874-1880, :1988, :2004-2005, :2140-2141); the install
  checks `typeof api.registerHttpRoute === "function"` before calling it.
- Raw body: the dispatcher calls `route.handler(req, res)` with the unread request, so
  the handler reads the stream and keeps the raw bytes for the HMAC. A handler throw is
  logged with `String(err)` and answered with a failure
  (dist/plugins-http-BBC_f-6g.mjs:101-118 [6dca4fca41ab]); our adapter never throws. The
  host's own webhook body default is 1 MiB (dist/http-body-CcomBDG-.mjs:8 [a7dcd8757274]).
- Through a tunnel: a request from a proxy the gateway does not trust is still dispatched
  to a plugin-authenticated route (dist/server-start-gE7ggn-j.mjs:6564-6567
  [ca2f0adbe827]), so the signature is the route's only gate. Plugin routes answer 503
  until startup sidecars are ready, and Meta retries those (gateway-routes.md:61).

## Meta facts (all retrieved 2026-11-08)
- Verification: Meta sends GET with `hub.mode=subscribe`, `hub.challenge` and
  `hub.verify_token`. Answer 200 with the challenge when the token matches, else a
  non-200. Signature: `X-Hub-Signature-256: sha256=<hash>`, HMAC-SHA256 of the POST
  payload keyed with the app secret. The page does not say whether that means raw bytes,
  so we hash the raw bytes (the only form a sender can sign). TLS must be valid and not
  self-signed. Failed deliveries are retried for 7 days and duplicates are expected. A
  POST can batch up to 1000 updates [M1].
- Payloads can be up to 3 MB; a non-200 triggers a retry; retries can duplicate [M2].
- Send: `https://graph.facebook.com/<API_VERSION>/<PHONE_NUMBER_ID>/messages`, bearer
  token, JSON `{ messaging_product, recipient_type: "individual", to, type: "text", text:
  { preview_url, body } }`, body at most 4096 characters. The success answer holds
  `contacts[].wa_id` and `messages[].id` [M3].
- Inbound text: `entry[].changes[]` with `field: "messages"`, `value.metadata.
  phone_number_id`, and `value.messages[]` with `from`, `id`, `timestamp` (Unix seconds as
  a string), `type: "text"` and `text.body`. `from` and `wa_id` are omitted for a user who
  adopted a username and whose number is unavailable, and `from_user_id` then carries a
  business-scoped user id [M4]. The phone-number allowlist cannot admit such a user, so
  the webhook drops them.
- Statuses: `value.statuses[]` (`sent`, `delivered`, `read`, `failed`, `played`) under the
  same `messages` field, with no `value.messages`. `failed` means the message could not be
  sent or delivered, and only then does the status carry `errors[]` [M5].
- Errors: `{ error: { message, type, code, error_data, fbtrace_id } }`. Code 131047 means
  more than 24 hours since the user last wrote, and the fix is a template. 130429 and
  131056 are rate limits ("try again later"). 190 is an expired token. Errors come back
  synchronously in the Graph response, asynchronously in the messages webhook, or both,
  and Meta says to watch both [M6]. We never retry automatically.
- Inbound text length: the text webhook reference describes `text.body` only as the text
  of the message and states no maximum [M4]; the 4096-character limit is for sends [M3].
- Customer service window: it opens when the user messages, lasts 24 hours and resets on
  each user message. Outside it only templates may be sent [M7; P1].

## Policy requirements mapped to the design
| Requirement | Source | Where it lands |
|---|---|---|
| Opt-in before messaging; honour opt-outs | P1 (opt-in permission; "respect all requests" to block or opt out); Meta's opt-in page requires the opt-in to name the business (eligibility doc S6) | Owner-collected at intake, naming `<BUSINESS_NAME>`, with a record; the allowlist admits only opted-in numbers and removing an entry is the opt-out. P1 itself sets no wording. |
| Human escalation path | P1: "prompt, clear, and direct escalation paths" | Owner item: the licensed human's contact route in the business profile and in the assistant's hand-off reply, staffed. The transport adds nothing here. |
| 24-hour window, no free-form send outside it | P1; M7; M6 code 131047 | Reply-only gate (no turn handle, no send); `sendText` refuses an unknown or stale peer locally; 131047 maps to the same reason, whether it comes back from the send or later as a `failed` status (a `send-failed-async` warning). |
| No proactive or template sends | P1 (conversations start only with an approved template) | No template code exists; item 18 stays withheld by the gate. |
| Data only as needed for messaging; no sharing across customers | P1 | Logs carry no text, peer or id; the webhook keeps message ids only (dedupe) and last-inbound times per peer (window), both bounded and in memory. |
| No training on WhatsApp data | Eligibility doc S1 s4.7 | Owner and program rule: WhatsApp message content excluded from every shared training or eval set; the model vendor must not train on API inputs (Q6). Nothing here writes message content anywhere. |
| AI Providers rule | Eligibility doc S1 s4.7 | Unchanged: the assistant stays scoped to the owner's real-estate service. |
| Valid TLS, signed webhook | M1 | Owner-run tunnel with a valid certificate; signature over raw bytes before parse. |

## Tests required (all offline, `node --test`)
`cloud-api.test.mjs`, CA-1 to CA-28: the config matrix (each field missing, empty,
non-string or implausible, a reused secret, a bad account id, each field read once);
exactly four Transport members plus `webhook`, frozen; an unconfigured transport rejects
and its webhook answers 404; the send request shape exactly (URL with the placeholders
substituted back, headers including the bearer from config, JSON body, `redirect:
"error"`, the caller's signal); no retry on 500, 400, 429, 401, 502 and a network error,
with no token, secret, body, recipient or Meta text in the error, its stack or the logs;
abort pass-through; receipts without an id; local refusals (text, `@lid`, account); the
24-hour window (unknown peer, stale, exactly 24 h, another peer, injected window); start
and stop lifecycle with 503 before start; GET verification pass and eight failures; the
signature cases (missing, repeated, bare hex, `sha1=`, short, long, zeros, wrong secret,
one flipped digit, a leading space, a tampered body, and both directions of a JSON
re-serialisation); the signature before decode; text mapping; 19 ignored shapes; batch,
duplicate and TTL dedupe and bounded memory; oversize body; no awaiting the sink and
logging a rejecting sink; a log scan for text, peers, ids, token, secret, verify token and
signature; the route adapter (chunked stream, declared and streamed oversize, a stalled
body, a GET); end to end through `createChannelPlugin` with the fake host (allowlisted
peer gets one Cloud API request with the gate's reply; a stranger gets nothing); and a
source test (imports `node:buffer`, `node:crypto` and `./ingress.mjs` only, no dynamic
import, no environment or file read, the fixed Graph origin as its only URL, no token,
secret, id or phone literal, not imported by the entry, not in `files`). Review fixes,
CA-23 to CA-28: an unsigned or malformed-signature POST is 401 with no body listener
attached, reads in flight are capped (503 `retry-after`) and an idle body is 408 before
the overall deadline; an admitted peer's window survives a 1024-sender flood while its
turn runs (through `createChannelPlugin` and the fake host) and the table is bounded
again after it; `failed` statuses warn `send-failed-async` with the numeric code only;
inbound text over 4096 characters (and emoji-heavy text) is delivered, and only text over
65,536 code units is dropped with `too-long`; a non-default account id leaves the
transport and the channel unconfigured; dedupe survives a channel restart on one
transport, and a new instance re-accepts a seen id only inside the age limit.

## Decisions to confirm (owner)
1. Webhook body limit 1 MiB (Meta allows 3 MB). An authentic larger batch would be
   refused 413 and retried for 7 days.
2. Inbound age limit 30 minutes, the ingress TTL: a message Meta delivers later, after an
   outage, is acknowledged and dropped, with no reply.
3. 503 while the account is not started, so Meta retries instead of the message being
   lost. The age limit bounds what a retry can start.
4. Username-only senders (no `from`) are dropped: the allowlist is phone-based.
5. The transport is staged, not shipped: the package `files` list and the entry's import
   closure leave it out, and two existing tests (`host.test.mjs` runtime file set and
   PKG-2) now name one staged file. The install PR moves it into `files`.
6. Route on the gateway (`registerHttpRoute`, `auth: "plugin"`) with a path-restricted
   tunnel, or the separate-listener fallback (ADR-0017).
7. Config source (wiring plan 1).
8. Dedupe is in memory only. One transport per process keeps it across channel restarts
   (config reloads), but after a gateway restart a message id seen before is accepted
   again while its Meta timestamp is inside the 30-minute age limit: one of Meta's
   expected duplicate deliveries, or a replay of a captured signed request (for example
   from tunnel or proxy logs at the TLS terminator), can then start a second turn and a
   second billed reply. Residual risk, accepted for now; the options are a shorter age
   limit or persisting recent ids (bounded, ids only, TTL = the age limit), which needs a
   file write and its own approval.
9. Asynchronous send failures (a `failed` status, including 131047) are logged as
   `send-failed-async` only. The outbound audit has already recorded the reply as sent
   ("accepted by Meta"), and nothing tells the licensed human that a reply, possibly the
   hand-off text, never arrived. Whether to surface it (audit follow-up, alert) is open.
10. Inbound text cap 65,536 UTF-16 code units (ours; Meta states none). A longer message
    is acknowledged and dropped with a `too-long` warning and the user gets no reply;
    whether they should get the fixed hand-off text instead is open.
11. Webhook ingress limits: at most 8 body reads at once (503 `retry-after` above it),
    2 s idle gap and 10 s overall per read; an unsigned POST is 401 before its body is
    read.
12. One account only (`accountId` "default"), matching the channel.

## Open owner items (before any credential)
Eligibility doc Q1-Q7, in particular brokerage permission (Q2), MLS and IDX display rules
for this channel (Q4) and the hosted-model data handling (Q6); opt-in text and record;
escalation route; privacy policy; tunnel choice; then credentials, number registration,
subscription and the smoke test, each by separate written approval.

## Acceptance
All of the above tests pass with the existing suite unchanged in behaviour; `index.mjs`
still defaults to `unavailableTransport`; the three docs gates pass on every changed path.

## Verification commands
```
cd extensions/idx-whatsapp-channel && node --test
.venv/bin/python -m pytest -q tests/test_whatsapp_channel_skeleton.py tests/test_docstring_lengths.py
python scripts/gates/forbidden_paths.py <paths>; python scripts/gates/pii_scan.py <paths>;
python scripts/gates/confidential_text.py <paths>
```

## Sources (retrieved 2026-11-08)
- [M1] https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint
- [M2] https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks
- [M3] https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/text-messages
- [M4] https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text
- [M5] https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status
- [M6] https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
- [M7] https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages
- [P1] WhatsApp Business Messaging Policy, last updated 2026-09-23, https://business.whatsapp.com/policy (301 to https://whatsappbusiness.com/policy/)
- Eligibility sources S1 and S6 as listed in `docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md`.

## Status
2026-11-08, offline module and tests (branch `wo-038-cloud-api-transport`, stacked on
#183 at 25c4aa2). Nothing installed, wired, registered or configured; no credential, no
Graph API call, no paid call; the implementer made no commit.

Node, `cd extensions/idx-whatsapp-channel && node --test`: 237/237 (`verifier.test.mjs`
37, `channel.test.mjs` 78, `host.test.mjs` 30, `entry.test.mjs` 11, `allowlist.test.mjs`
11, `cards.test.mjs` 18, `reply.test.mjs` 22, `host-harness/checks.test.mjs` 8, the new
`cloud-api.test.mjs` 22), up from 215. Fail before, pass after: with the new module
present and `host.test.mjs` of 25c4aa2, 2 of 30 fail (the runtime file set and PKG-2), the
other 28 pass. Ten mutations of the module in a scratch copy, each caught by at least one
CA test: no signature check, a signature over re-serialised JSON, no window check, no
dedupe, no phone-number-id filter, no stale drop, no size limit, a leaked network error,
link previews on, and a prefix-only verify-token match. pytest
(`tests/test_whatsapp_channel_skeleton.py tests/test_docstring_lengths.py`): 7 passed.
Ruff check and format are clean on the one Python file touched.

Review fixes, 2026-11-08 (seven confirmed findings, all low or medium): the route refuses
unsigned POSTs before reading, caps reads in flight and adds an idle timeout; admitted
peers are pinned in the window table while their turn runs; `failed` statuses warn
`send-failed-async`; inbound text gets its own 65,536 cap with a `too-long` warning; only
the `default` account id is accepted; the in-memory dedupe limit is recorded as decision
8 and in ADR-0017. Node: 243/243 (`cloud-api.test.mjs` 28, the other files unchanged).
CA-23 to CA-27 fail against the pre-fix module in a scratch copy and pass after; CA-28
pins the documented bound and passes on both. pytest: 7 passed. Ruff check and format
clean; the three docs gates pass on every changed path.
