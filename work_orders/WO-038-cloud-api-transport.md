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

Owner instruction after review, 2026-11-08, verbatim: "Fix shutdown and reload before merge. Refuse sends while stopped and invalidate old turns across restart, even if their reply arrives after the new account starts. Add a regression that holds a turn open, stops or reloads the account, and verifies the late reply makes zero Graph API calls. For wiring, use an owner-only credentials file outside the repo and a separate loopback listener with a tunnel restricted to the webhook path. Log delivery failures privately, drop oversized inbound texts silently, and keep the 1 MiB and 30-minute defaults. In-memory dedupe is fine for the owner-only smoke test. Add bounded persistence before buyer rollout. Keep live setup behind separate approval."

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
2a. Lifecycle fix (owner instruction 2026-11-08): account epochs in `ingress.mjs`
   (`beginAccountEpoch`, `accountEpoch` and `endAccountEpoch`, all listed in `index.mjs`
   `INGRESS_MEMBERS`), the epoch calls in `channel.mjs` `gateway.startAccount`, and the
   running-only send rule in `cloud-api-transport.mjs`; `cloud-api-lifecycle.test.mjs`
   (10 tests).
2b. Wiring pieces, staged like the transport: `cloud-api-wiring.mjs`
   (`readOwnerCredentialsFile`, `createWebhookListener`; `node:fs`, `node:http`,
   `node:os`, `node:path`, `node:url`, `node:buffer`, `node:child_process` (only
   `execFileSync` of `/bin/ls -led` for the macOS ACL look) and `./cloud-api-transport.mjs`
   only) and `cloud-api-wiring.test.mjs` (9 tests, synthetic files in an OS temp
   directory, loopback sockets only).
3. Test plumbing for staged modules: `host.test.mjs` (runtime file set, PKG-2) and
   `tests/test_whatsapp_channel_skeleton.py` (`NODE_TESTS`, package shape) learn two
   named staged files (`cloud-api-transport.mjs`, `cloud-api-wiring.mjs`) that every
   source scan covers but `files` and the entry's import closure leave out.
4. This work order, ADR-0017 (proposed) and a short README section.

## Out of scope (each held for separate written owner approval)
Held until the owner has confirmed brokerage and IDX permissions and hosted-model data
handling (eligibility doc Q2, Q4, Q6):
- any credential: Meta app, system-user token, app secret, verify token, phone-number id,
  WhatsApp business account id, two-step PIN; no sign-up, no console step;
- number registration or display-name setup;
- the public tunnel, its certificate, and the webhook subscription in Meta's console;
- any live send, and the five-message smoke test (recommendation section 4);
- wiring the transport into `index.mjs`, starting the loopback listener, adding the two
  staged modules to the package `files`, and any config schema change (the install PR);
- bounded dedupe persistence (a file write; its own approval, and a gate before any buyer
  is allowlisted);
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
  (or `stop()`); an already-aborted signal resolves at once and never runs. A newer start
  takes over the sink and runs fresh; an older one resolves on its own signal. The
  transport is running only while a start holds the sink. Each start has its own abort
  controller: its end (abort or `stop()`) or a takeover by a newer start aborts it, which
  aborts any request still in flight under it, and drops its window pins.
- `sendText({ accountId, to, text, signal })`: refuses locally (no request) when
  unconfigured; `transport-not-running` when no start is running (before the first start,
  after a stop or abort, between a stop and the next start), checked before any other
  field; for another account, for empty or over-4096 text, for a peer that is not
  canonical `+<digits>` (a `@lid` peer is refused), and when the peer's last inbound
  (Meta's message time) is unknown or older than `windowMs` (default 24 h). Otherwise one
  `fetch` POST to `https://graph.facebook.com/<GRAPH_API_VERSION>/<PHONE_NUMBER_ID>/messages`
  with `authorization: Bearer <ACCESS_TOKEN>`, `content-type: application/json`,
  `redirect: "error"`, a signal joined from the caller's `signal` and the running
  start's controller (either aborts the request), and body `{ messaging_product: "whatsapp",
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
- Ingress epochs (`ingress.mjs`, process-wide with `processIngress`): every entry keeps
  its account's epoch at record time. `beginAccountEpoch(accountId)` raises that
  account's counter (it never goes down) and drops every earlier entry of that account:
  its run ends, it leaves the active-turn index and the record store, and `forTurn`,
  `confirmRun`, `admitCardCall` and `captureReply` (`turn-expired`), `replySections`,
  `issuedRun` and `hasActiveTurn` also check the epoch. Other accounts are untouched.
  `accountEpoch(accountId)` reads the counter; `endAccountEpoch(accountId, epoch)` raises
  it (as `beginAccountEpoch` does) only while `epoch` is still the present one, and
  otherwise changes nothing and returns false.
- `gateway.startAccount` (`channel.mjs`): keeps the epoch `beginAccountEpoch` returns
  when it starts, and when its `abortSignal` aborts calls `endAccountEpoch` with that
  epoch, so the abort voids turns only while this call is still the account's newest
  start. The test is on the process-wide counter, not on state private to one plugin
  object, so it holds across plugin objects that share the process ingress and the one
  transport (fix review, 2026-11-08): an older object's signal aborted after a newer
  object's start cannot void the newer turns or free their busy peer. An inbound that
  reaches a stopped or superseded start's sink (in any plugin object) is dropped before
  it is recorded (`inbound-dropped` / `account-stopped`). The result: a reply the host hands to
  an old turn's `deliver` after a stop or a reload finds no trusted record, and the gate
  withholds it `untrusted-turn` with no transport call at all, in both withhold modes.
- `readOwnerCredentialsFile(path, deps?)` (`cloud-api-wiring.mjs`): reads the owner's JSON
  file once and returns a frozen config for `createCloudApiTransport`. It refuses with a
  `CredentialsFileError` carrying a fixed reason only (no path, no value, no file text)
  unless the path is absolute; the file's real location (real paths, so a symlinked
  parent cannot hide it) is outside the repo root, this module's directory and
  `~/.openclaw`; `lstat` sees a regular file, not a symlink, with exactly one link (a
  hard link would let a second name, perhaps inside the repo, reach the same bytes:
  `hard-linked`); it is owned by the current uid with no group or other mode bit; its
  directory is owned by the uid and not group- or world-writable; on macOS neither the
  file nor its directory carries an extended ACL (`acl-present`, or `acl-unknown` when
  `/bin/ls -led` cannot answer), since an ACL can grant other users access that the
  mode bits do not show (on Linux any ACL entry beyond the owner's shows in the group
  bits, which the mode test refuses); it is opened with `O_NOFOLLOW` and the open
  descriptor matches the first look (inode, device, link count, owner, mode); it is at most 16 KiB of UTF-8 JSON, a plain
  object with exactly the six config keys (`accessToken`, `appSecret`,
  `graphApiVersion`, `phoneNumberId`, `verifyToken`, `webhookPath`; no `accountId`), each
  a non-empty string that `readCloudApiConfig` accepts. `repoRoot`, `home`, `uid`,
  `maxBytes`, the ACL look and the `fs` calls are injectable for tests.
- `createWebhookListener({ handler, host, port, path, log? })` (`cloud-api-wiring.mjs`): a
  separate `node:http` server. `host` must be the literal `127.0.0.1` or `::1` (a name
  such as `localhost` is refused); `port` 0-65535; `path` a valid webhook path; `handler`
  the transport's `webhook.routeHandler`, which keeps every route check. Exactly `path`
  (query allowed) with GET or POST reaches the handler; any other path is 404 and any
  other method 405 (`allow: GET, POST`), both with `connection: close`,
  `content-length: 0` and no body; a malformed request is 400, oversized headers 431, a
  header or request timeout 408, each closing the socket. Limits: 8 KiB of headers, 5 s
  for headers, 15 s per request (above the adapter's 10 s body deadline), 5 s keep-alive,
  timeouts checked every second, 64 connections. `start({ signal })` binds and resolves
  `{ port }`; an abort of that signal, or `stop()`, closes the server and its sockets and
  releases the port; a stale signal cannot stop a later start. An abort or a `stop()`
  while `start()` is still binding cancels it: the port is released as soon as it is
  bound, the start rejects (`stopped while starting`) and `stop()` resolves once the port
  is free; a second `start()` while one is pending or running is refused. Logs are fixed events
  (`listener-started`, `listener-stopped`, `listener-error` with the error code,
  `request-refused` with `not-found` or `method-not-allowed`), never a path, query,
  header, address, port or body.

## Wiring plan for the install PR (not done here; owner decisions of 2026-11-08)
1. Config source, DECIDED: option (a), an owner-only credentials file. The owner creates
   one JSON file outside the repo and outside `~/.openclaw`, owned by the gateway's user,
   mode 600 (or 400), holding exactly the six config keys; its absolute path is the only
   new plugin-config key. The install calls `readOwnerCredentialsFile` once at register
   and passes the result to `createCloudApiTransport`. The agent never sees or writes the
   file. (Options (b) environment and (c) SecretRefs are not used; (c) would also have
   broken the built-ins-only rule.)
2. One transport per process. The host registers this plugin from more than one module
   copy (WO-037, real-host replay), and only one copy's channel starts. The install keeps
   the transport, and the listener below, behind a process-wide frozen key, as
   `processIngress` does for the ingress, and passes the transport to
   `createPluginEntry({ transport })`. The ingress epochs are process-wide too, so a
   reload in one copy voids the old turns every copy's hooks can see, and a late abort
   of an older copy's start cannot void a newer copy's turns (CL-10).
3. Ingress, DECIDED: a separate loopback listener, not `api.registerHttpRoute`. The
   install builds `createWebhookListener({ handler: cloud.webhook.routeHandler, host:
   "127.0.0.1", port: <OWNER_PORT>, path: cloud.webhook.path, log })` and starts it from
   `gateway.startAccount` with the same `abortSignal`, so a stop or reload closes the
   port with the account. The gateway port stays loopback and private; nothing on it is
   internet-facing.
4. Public HTTPS (owner-run): Meta needs a public URL with a valid, not self-signed
   certificate. The owner's tunnel (for example a named Cloudflare Tunnel or Tailscale
   Funnel) targets the listener's port only and forwards only `<WEBHOOK_PATH>`, GET and
   POST; the listener refuses every other path and method as a second layer. The
   tunnel's access logs see the verify token in the GET query once at subscription; the
   owner should rotate it after subscribing if those logs are kept.
5. The allowlist, one-active-turn rule, verifier and outbound gate stay exactly as they
   are and run in front: the webhook only feeds `onInbound`, and the transport only
   sends sealed text the gate hands it. `sendText` keeps its own 24-hour and
   running-only refusals as defence in depth.
6. Delivery failures, DECIDED: logged privately. `send-failed` (synchronous) and
   `send-failed-async` (a `failed` status) go to the gateway's local log only, with a
   reason and Meta's numeric code at most, never an id, a peer or text; no notification
   to the licensed human or anyone else.
7. Oversized inbound text, DECIDED: dropped silently, meaning no reply to the sender.
   The webhook keeps its one content-free local warning, `inbound-dropped` /
   `too-long`, with no text, peer or id.
8. Dedupe: in memory, accepted for the owner-only smoke test. Bounded dedupe persistence
   is a hard prerequisite before any buyer is added to the allowlist (see the gate below).
9. Live setup (credentials, number registration, the tunnel, the webhook subscription,
   any live send and the five-message smoke test) stays behind separate written owner
   approval; nothing here grants it.
10. Rollback: stop the tunnel, unsubscribe the webhook, revoke the token, then runbook 4.

### Gate before buyer rollout: bounded dedupe persistence (hard prerequisite)
No buyer number may be added to `channels.whatsapp.allowFrom` until the webhook's dedupe
survives a gateway restart. Until then the allowlist holds the owner's own test number
only. Design sketch, for its own approval (it adds a file write):
- what is stored: message ids only (Meta's `wamid` values, no peer, no text, no
  timestamp beyond the expiry), one per line or a small JSON array;
- lifetime: each id expires after the inbound age limit (30 minutes), since an older
  message is dropped as stale anyway, so nothing needs to be kept longer;
- size: bounded by count (the in-memory 4096), oldest dropped first;
- file: owner-only (mode 600, owned by the gateway's user) in the same directory as the
  credentials file, outside the repo and `~/.openclaw`, checked with the same rules as
  the credentials file on load; written atomically (temp file, then rename) after each
  accepted inbound or on a short debounce, and loaded once at start with expired ids
  dropped;
- failure: if the file cannot be read or written, the webhook answers 503 (Meta retries)
  instead of accepting without dedupe.

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
| Data only as needed for messaging; no sharing across customers | P1 | Logs carry no text, peer or id; the webhook keeps message ids only (dedupe) and last-inbound times per peer (window), both bounded and in memory. The planned dedupe persistence keeps ids only, expiring with the age limit, in an owner-only file. |
| No training on WhatsApp data | Eligibility doc S1 s4.7 | Owner and program rule: WhatsApp message content excluded from every shared training or eval set; the model vendor must not train on API inputs (Q6). Nothing here writes message content anywhere. |
| AI Providers rule | Eligibility doc S1 s4.7 | Unchanged: the assistant stays scoped to the owner's real-estate service. |
| Valid TLS, signed webhook | M1 | Owner-run tunnel with a valid certificate, restricted to the webhook path, to the loopback listener; signature over raw bytes before parse. |

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

Lifecycle fix (owner instruction 2026-11-08), `cloud-api-lifecycle.test.mjs`, CL-1 to CL-10,
on the real `createChannelPlugin`, the process-wide ingress (`processIngress`) or a shared
`createIngress`, and `createCloudApiTransport` over a counting fake fetch: CL-1 holds a
turn open (the fake host's runner awaits a promise the test controls), stops the account
(aborts the `startAccount` signal), releases the reply and requires zero fetch calls and an
`untrusted-turn` suppression, in both withhold modes, for a reply the verifier would
release and one it would withhold (which in safe-text mode would otherwise go out as the
safe text); CL-2 does the same across a reload (abort, then `startAccount` with a new
signal), requires the peer's next message to start a new turn instead of a busy reply,
and checks both orders: the new turn's reply makes exactly one call and the late reply
none; CL-3 a late abort of the older signal after the newer start voids the old turn
only; CL-4 `transport-not-running` with no fetch before the first start, after an abort,
after `stop()`, between a stop and the next start and for an already-aborted start, and
a restart runs fresh; CL-5 a start abort, `stop()` and a takeover each abort a fetch in
flight through the signal it was given, one request and no retry; CL-6 a stop drops the
window pins of its held turns, and a late settle from the old turn does not unpin the
peer for the next start; CL-7 `beginAccountEpoch` voids every lookup for earlier turns,
counts up, and leaves later turns valid; CL-8 another account's turns survive, through
the ingress and through two channels on one ingress; CL-9 an inbound reaching a stopped
start's sink is dropped before it is recorded; CL-10 two plugin objects on one ingress
and one Cloud API transport, the first object's signal aborted after the second object's
start: the second object's held turn still delivers with exactly one Graph API call, its
peer stays busy (one busy reply, no second running turn), a stale `endAccountEpoch`
changes nothing, and the first object's sink drops inbounds. CL-5 now bounds its wait
(a 2 s race and a 5 s test timeout), so a request that is never aborted fails with the
case named instead of hanging the run. CA-4 and CA-6 now check the joined
signal (the caller's abort still aborts the request) instead of the caller's own object.

Wiring pieces, `cloud-api-wiring.test.mjs`, CW-1 to CW-9: a good file is read once into a
frozen config the transport accepts (0600 and 0400); the refusal matrix (relative,
empty and non-string paths, missing, a directory, inside the real repo root and an
injected one, inside an injected `~/.openclaw`, a symlink, a symlinked parent that lands
in the repo, eight loose modes, a wrong owner by injected uid, a group- and
world-writable directory, oversize by default and injected limit, bad JSON, invalid
UTF-8, empty, array and string JSON, an extra key, a `__proto__` key, each key missing,
empty or non-string, an implausible id, a reused secret and an unsafe path, a hard link
from outside to a file inside the repo, a hard-linked pair outside it, a link count seen
only on the open descriptor, an ACL reported by an injected look (file, directory only,
a failed look, a non-boolean answer) and, on macOS, a real `chmod +a` ACL on a mode-600
file and on a mode-700 directory), each a fixed reason with no path or value in the
error (the leak check reads the message, the error's own fields and the stack head,
never the stack's frame paths, and looks for specific markers such as the sandbox's
own temp path; CW-9 checks that helper); a swap between `lstat` and `open`; a
source test (imports, no environment, no file write, no fetch, server limits present,
staged); listener construction refusals (non-loopback hosts including `localhost`,
`0.0.0.0`, `::` and a mapped IPv4 address, bad ports and paths); real loopback requests
on an ephemeral port (GET verification, a signed POST reaching the sink, unsigned and
wrongly signed POSTs 401, ten other paths 404 and five other methods 405 with
`connection: close` and no body, 431 for oversized headers, logs free of path, query,
token, text, peer, address and port); the lifecycle (the account signal alone stops it
and releases the port, checked by polling the port without calling `stop()`; `stop()` is
idempotent, the same port binds again, a busy port fails with a fixed message and
`EADDRINUSE` code, a stale signal cannot stop a later start, and the fresh signal alone
releases it); and CW-8, an abort in the same tick as `start()` and a `stop()` while it is
pending each make the start reject and leave the port free, and a second `start()`
while one is pending is refused.

## Decisions (owner)
Owner instruction 2026-11-08, verbatim: "Fix shutdown and reload before merge. Refuse sends while stopped and invalidate old turns across restart, even if their reply arrives after the new account starts. Add a regression that holds a turn open, stops or reloads the account, and verifies the late reply makes zero Graph API calls. For wiring, use an owner-only credentials file outside the repo and a separate loopback listener with a tunnel restricted to the webhook path. Log delivery failures privately, drop oversized inbound texts silently, and keep the 1 MiB and 30-minute defaults. In-memory dedupe is fine for the owner-only smoke test. Add bounded persistence before buyer rollout. Keep live setup behind separate approval."

1. DECIDED (keep): webhook body limit 1 MiB (Meta allows 3 MB). An authentic larger batch
   would be refused 413 and retried for 7 days.
2. DECIDED (keep): inbound age limit 30 minutes, the ingress TTL: a message Meta delivers
   later, after an outage, is acknowledged and dropped, with no reply.
3. To confirm: 503 while the account is not started, so Meta retries instead of the
   message being lost. The age limit bounds what a retry can start.
4. To confirm: username-only senders (no `from`) are dropped: the allowlist is
   phone-based.
5. To confirm: the transport and its wiring pieces are staged, not shipped: the package
   `files` list and the entry's import closure leave them out, and two existing tests
   (`host.test.mjs` runtime file set and PKG-2) name the two staged files. The install PR
   moves them into `files`.
6. DECIDED: a separate loopback listener (`createWebhookListener`) with a tunnel
   restricted to the webhook path, not a route on the gateway (`registerHttpRoute`).
7. DECIDED: config from an owner-only credentials file outside the repo (wiring plan
   option (a), `readOwnerCredentialsFile`).
8. DECIDED: in-memory dedupe is accepted for the owner-only smoke test. After a gateway
   restart a message id seen before is accepted again while its Meta timestamp is
   inside the 30-minute age limit (a duplicate delivery or a replayed captured request can
   start a second turn and a second billed reply); that stays a residual risk only while
   the allowlist holds the owner alone. Bounded dedupe persistence is a hard gate before
   any buyer is added (wiring plan, "Gate before buyer rollout").
9. DECIDED: asynchronous and synchronous send failures are logged privately, local log
   only (`send-failed-async`, `send-failed`, no id, peer or text), with no notification.
   The outbound audit's "sent" still means "accepted by Meta".
10. DECIDED: inbound text over 65,536 UTF-16 code units is dropped silently: no reply to
    the sender, and one content-free local `inbound-dropped` / `too-long` warning.
11. To confirm: webhook ingress limits: at most 8 body reads at once (503 `retry-after`
    above it), 2 s idle gap and 10 s overall per read; an unsigned POST is 401 before its
    body is read. The listener adds 8 KiB headers, 5 s for headers, 15 s per request and
    64 connections.
12. To confirm: one account only (`accountId` "default"), matching the channel.
13. DECIDED (fixed before merge): shutdown and reload. Sends are refused while the
    transport is stopped, and turns opened before a stop or reload are voided by an
    ingress epoch, so their late replies make no Graph API call.
14. DECIDED: live setup (credentials, number, tunnel, subscription, live sends, smoke
    test) stays behind separate written approval.

## Open owner items (before any credential)
Eligibility doc Q1-Q7, in particular brokerage permission (Q2), MLS and IDX display rules
for this channel (Q4) and the hosted-model data handling (Q6); opt-in text and record;
escalation route; privacy policy; the tunnel product (it must restrict to the webhook
path and target the listener port); bounded dedupe persistence before any buyer; then
credentials, number registration, subscription and the smoke test, each by separate
written approval.

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

Lifecycle fix and wiring pieces, 2026-11-08 (owner instruction above). Account epochs in the
ingress and their two calls in `startAccount`; the running-only send rule, per-start abort
controllers and per-start pins in the transport; `cloud-api-wiring.mjs` (credentials file
reader, loopback listener), staged and not wired. Decisions 1, 2, 6-10, 13 and 14 are
recorded as DECIDED; the wiring plan and ADR-0017 (still proposed) follow them. Nothing
installed, wired, registered or configured; no credential, no Graph API call, no network
beyond 127.0.0.1 in tests; the implementer made no commit.

Node, `cd extensions/idx-whatsapp-channel && node --test`: 262/262 (`verifier.test.mjs` 37,
`channel.test.mjs` 78, `host.test.mjs` 30, `entry.test.mjs` 11, `allowlist.test.mjs` 11,
`cards.test.mjs` 18, `reply.test.mjs` 25, `host-harness/checks.test.mjs` 8,
`cloud-api.test.mjs` 28, the new `cloud-api-lifecycle.test.mjs` 9 and
`cloud-api-wiring.test.mjs` 7), up from 246. Fail before, pass after: the lifecycle file
run against the HEAD runtime in a scratch copy fails all 9 (CL-1 the late reply after a
stop makes one Graph API call; CL-2 and CL-3 the peer's next message after a reload gets
the busy reply instead of a new turn, because the old turn is still active; CL-4 a send
before any start reaches the window check instead of `transport-not-running`; CL-5 fetch
gets no signal to abort, so the fake fetch fails as a network error; CL-6 a stop keeps the
held turn's pin; CL-7 and CL-8 `beginAccountEpoch` does not exist; CL-9 a stopped sink
still records a turn). With only the new transport on the old channel and ingress, 6 still
fail (CL-1 now makes no call but the old turn's deliver fails instead of being withheld
`untrusted-turn`; CL-2 and CL-3 as before); with only the new channel and ingress on the old
transport, 3 still fail (CL-4, CL-5, CL-6). pytest
(`tests/test_whatsapp_channel_skeleton.py tests/test_docstring_lengths.py
tests/test_whatsapp_reply_payloads.py`): 126 passed. Ruff check and format clean on the one
Python file touched; the three docs gates pass on every changed and new path.

Fix review, 2026-11-08 (seven confirmed findings, all fixed; no commit). (1) A late abort
of an older plugin object's start voided a newer object's live turns, because the
"newest start" test used a map private to each object: `startAccount` now keeps the
epoch it began and ends it with the compare-and-raise `endAccountEpoch`, and the sink's
drop test compares the same epoch (CL-10). (2) An abort or `stop()` while the listener
was still binding left the port bound: the listener now has a starting state that
cancels the pending start and releases the port (CW-8). (3) macOS ACLs were not checked:
the reader now refuses a file or directory with an extended ACL. (4) A hard link was
accepted: the reader now refuses a link count other than one. (5) CW-7 did not test the
abort alone; it now polls the port with no `stop()`. (6) The leak check matched words in
the checkout path; it now ignores stack frames and uses specific markers. (7) CL-5 could
hang; it now races a timer and has a test timeout. Fail before, pass after, in scratch
copies under the session scratchpad: CL-10 against the per-object guard fails (2 running
turns, expected 1); CL-5 against a takeover that does not abort fails in about 2 s with
`takeover: the in-flight request was never aborted` instead of hanging; the new wiring
tests against the pre-fix module fail CW-2 (`hard-linked` expected, `accepted`), CW-4
and CW-8 (start resolved instead of rejecting); against a mutant whose signal no longer
stops a listening server, CW-7 (`the port is released by the abort alone`) and CW-8 fail;
a throwaway script with real `chmod +a` ACLs prints `ACCEPTED` for the pre-fix module and
`acl-present` for the fixed one. The whole wiring file passes from a scratchpad path (the
path that broke the old leak check). After the fixes: `node --test` 265/265
(`cloud-api-lifecycle.test.mjs` 10, `cloud-api-wiring.test.mjs` 9, every other file
unchanged); pytest on the three files 126 passed; ruff check and format clean; the three
docs gates pass on all 13 changed and new paths. `index.mjs` still ships
`unavailableTransport`; nothing is wired.
