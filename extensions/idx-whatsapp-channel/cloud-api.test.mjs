// WO-038: the Cloud API transport and its webhook, offline. Fakes only: an injected fetch,
// an injected clock, synthetic 555 peers and made-up ids. Nothing here reaches a network.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CLOUD_INBOUND_TEXT_MAX_LENGTH,
  CUSTOMER_SERVICE_WINDOW_MS,
  GRAPH_API_ORIGIN,
  MAX_INBOUND_AGE_MS,
  WINDOW_MAX_PEERS,
  createCloudApiTransport,
  createCloudApiWebhook,
  createHttpRouteHandler,
  readCloudApiConfig,
  signatureValid,
} from "./cloud-api-transport.mjs";
import { createChannelPlugin } from "./channel.mjs";
import { TRANSPORT_METHODS } from "./constants.mjs";
import { createIngress } from "./ingress.mjs";
import { createFakeHost } from "./test-support/host-emulation.mjs";

// Synthetic values of plausible shape. None is a real credential, id or number.
const CONFIG = Object.freeze({
  phoneNumberId: "1000000000001",
  graphApiVersion: "v99.9",
  accessToken: "TEST-ACCESS-TOKEN-not-a-real-token-0000000000",
  appSecret: "testappsecretnotreal000000000000",
  verifyToken: "test-verify-token-not-real",
  webhookPath: "/idx-whatsapp/cloud-api/webhook",
});
const PATH = CONFIG.webhookPath;
const WA_ID = "15550000001";
const PEER = "+15550000001";
const OTHER_WA_ID = "15550000002";
const T0 = 1_800_000_000_000;
const TS = String(T0 / 1000);

const sign = (raw, secret = CONFIG.appSecret) => `sha256=${createHmac("sha256", secret).update(raw).digest("hex")}`;

/** A text-message webhook payload in Meta's shape. */
function textPayload({ from = WA_ID, id = "wamid.TEST-1", body = "hi there", ts = TS, phoneNumberId = CONFIG.phoneNumberId, extra = {} } = {}) {
  return {
    object: "whatsapp_business_account",
    entry: [{
      id: "WABA-TEST",
      changes: [{
        field: "messages",
        value: {
          messaging_product: "whatsapp",
          metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: phoneNumberId },
          contacts: [{ profile: { name: "Test Buyer" }, ...(from === null ? { user_id: "BSUID-TEST" } : { wa_id: from }) }],
          messages: [{ ...(from === null ? {} : { from }), id, timestamp: ts, type: "text", text: { body }, ...extra }],
        },
      }],
    }],
  };
}

function statusPayload() {
  return {
    object: "whatsapp_business_account",
    entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: {
      messaging_product: "whatsapp",
      metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: CONFIG.phoneNumberId },
      statuses: [{ id: "wamid.OUT-1", status: "delivered", timestamp: TS, recipient_id: WA_ID }],
    } }] }],
  };
}

const post = (payload, { raw, signature } = {}) => {
  const bytes = Buffer.from(raw ?? JSON.stringify(payload), "utf8");
  return { method: "POST", url: PATH, headers: { "x-hub-signature-256": signature ?? sign(bytes), "content-type": "application/json" }, body: bytes };
};
const verifyGet = (params) => ({ method: "GET", url: `${PATH}?${new URLSearchParams(params)}`, headers: {}, body: undefined });

/** A recording logger. */
function recorder() {
  const lines = [];
  const log = { info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
  return { lines, log };
}

/** A webhook over a recording sink and a settable clock. */
function hook(overrides = {}) {
  const got = [];
  const clock = { t: T0 };
  const { lines, log } = recorder();
  const w = createCloudApiWebhook({ config: CONFIG, onInbound: (m) => { got.push(m); }, now: () => clock.t, log, ...overrides });
  return { w, got, clock, lines };
}

/** A fetch that records each call and answers from a script (default: one accepted send). */
function fakeFetch(answers = []) {
  const calls = [];
  let n = 0;
  const fn = async (url, init) => {
    calls.push({ url, init });
    const a = answers[n++] ?? { status: 200, json: { messaging_product: "whatsapp", contacts: [{ input: WA_ID, wa_id: WA_ID }], messages: [{ id: `wamid.SENT-${n}` }] } };
    if (a.throw) throw a.throw;
    return new Response(a.raw ?? JSON.stringify(a.json ?? {}), { status: a.status });
  };
  return { fn, calls };
}

/** A transport over a fake fetch, started, with one fresh inbound from PEER so its window is open. */
async function openTransport({ answers, windowMs, openWindow = true } = {}) {
  const f = fakeFetch(answers);
  const clock = { t: T0 };
  const { lines, log } = recorder();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn, now: () => clock.t, log, ...(windowMs ? { windowMs } : {}) });
  const ac = new AbortController();
  const got = [];
  const started = t.start({ accountId: "default", signal: ac.signal, onInbound: async (m) => { got.push(m); } });
  if (openWindow) assert.equal(t.webhook.handle(post(textPayload())).status, 200);
  return { t, f, clock, lines, ac, got, started };
}

const settle = () => new Promise((r) => setImmediate(r));

// ---- config ------------------------------------------------------------------

test("CA-1 isConfigured: true only when every required value is a non-empty string of plausible shape and fetch is injected", () => {
  const ok = createCloudApiTransport({ config: CONFIG, fetch: async () => new Response("{}") });
  assert.equal(ok.isConfigured(), true);
  assert.equal(createCloudApiTransport({ config: CONFIG }).isConfigured(), false, "no fetch");
  for (const bad of [undefined, null, "config", [], 7]) assert.equal(readCloudApiConfig(bad), null);
  const fields = ["phoneNumberId", "graphApiVersion", "accessToken", "appSecret", "verifyToken", "webhookPath"];
  const implausible = {
    phoneNumberId: ["<PHONE_NUMBER_ID>", "12a45", "1234", " 1000000000001", "+1000000000001"],
    graphApiVersion: ["<GRAPH_API_VERSION>", "99.9", "v99", "v99.9/../x", "latest"],
    accessToken: ["<ACCESS_TOKEN>", "short-token", "TEST ACCESS TOKEN with spaces 000000000", "x".repeat(4097)],
    appSecret: ["<APP_SECRET>", "tooshort", "testappsecret-with-dash-00000000"],
    verifyToken: ["<VT>", "short", "test verify token with spaces", "x".repeat(257)],
    webhookPath: ["idx/webhook", "/", "/a/../b", "/a//b", "/a?x=1", "/a b", "//evil.example.com/x"],
  };
  for (const f of fields) {
    for (const v of [undefined, "", 42, null, ["x"], ...implausible[f]]) {
      const cfg = { ...CONFIG, [f]: v };
      if (v === undefined) delete cfg[f];
      assert.equal(readCloudApiConfig(cfg), null, `${f}=${JSON.stringify(v)}`);
      assert.equal(createCloudApiTransport({ config: cfg, fetch: async () => new Response("{}") }).isConfigured(), false);
    }
  }
  // a reused secret is refused: the verify token rides in a GET query string
  assert.equal(readCloudApiConfig({ ...CONFIG, verifyToken: CONFIG.appSecret }), null);
  assert.equal(readCloudApiConfig({ ...CONFIG, verifyToken: CONFIG.accessToken }), null);
  assert.equal(readCloudApiConfig({ ...CONFIG, accountId: "bad id" }), null);
  // each field is read once, so a getter cannot pass the check and then change
  const reads = {};
  const counted = {};
  for (const f of fields) Object.defineProperty(counted, f, { enumerable: true, get: () => { reads[f] = (reads[f] ?? 0) + 1; return CONFIG[f]; } });
  assert.ok(readCloudApiConfig(counted));
  for (const f of fields) assert.equal(reads[f], 1, f);
  assert.ok(Object.isFrozen(readCloudApiConfig(CONFIG)));
});

test("CA-2 the transport object has exactly the four Transport members plus webhook, frozen", () => {
  const t = createCloudApiTransport({ config: CONFIG, fetch: async () => new Response("{}") });
  assert.deepEqual(Object.keys(t).sort(), [...TRANSPORT_METHODS, "webhook"].sort());
  assert.ok(Object.isFrozen(t));
  assert.ok(Object.isFrozen(t.webhook));
  assert.deepEqual(Object.keys(t.webhook).sort(), ["handle", "path", "routeHandler"]);
  assert.equal(t.webhook.path, PATH);
});

test("CA-3 an unconfigured transport rejects start and sendText and its webhook answers 404 to everything", async () => {
  const t = createCloudApiTransport({ config: { ...CONFIG, accessToken: "" }, fetch: async () => { throw new Error("no fetch expected"); } });
  await assert.rejects(t.start({ accountId: "default", onInbound: async () => {} }), /cloud api: not-configured$/);
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "hi" }), /not-configured/);
  assert.equal(t.webhook.handle(verifyGet({ "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "abc" })).status, 404);
  assert.equal(t.webhook.handle(post(textPayload())).status, 404);
});

// ---- send --------------------------------------------------------------------

test("CA-4 sendText: one POST to the messages endpoint with the bearer token from config, JSON text body with preview_url false, the wa_id recipient, an abort signal joined from the caller's and the running start's, and no redirects; returns the message id", async () => {
  const { t, f, ac } = await openTransport();
  const signal = new AbortController().signal;
  const r = await t.sendText({ accountId: "default", to: PEER, text: "Hello!", signal });
  assert.deepEqual(r, { messageId: "wamid.SENT-1" });
  assert.equal(f.calls.length, 1);
  const { url, init } = f.calls[0];
  assert.equal(url, `${GRAPH_API_ORIGIN}/${CONFIG.graphApiVersion}/${CONFIG.phoneNumberId}/messages`);
  assert.equal(url.replace(CONFIG.graphApiVersion, "<GRAPH_API_VERSION>").replace(CONFIG.phoneNumberId, "<PHONE_NUMBER_ID>"), "https://graph.facebook.com/<GRAPH_API_VERSION>/<PHONE_NUMBER_ID>/messages");
  assert.equal(init.method, "POST");
  assert.deepEqual(init.headers, { authorization: `Bearer ${CONFIG.accessToken}`, "content-type": "application/json" });
  assert.deepEqual(JSON.parse(init.body), { messaging_product: "whatsapp", recipient_type: "individual", to: WA_ID, type: "text", text: { preview_url: false, body: "Hello!" } });
  assert.ok(init.signal instanceof AbortSignal, "fetch always gets a signal (the caller's joined with the start's)");
  assert.equal(init.signal.aborted, false);
  assert.equal(init.redirect, "error");
  assert.deepEqual(Object.keys(init).sort(), ["body", "headers", "method", "redirect", "signal"]);
  // the canonical peer in any accepted spelling maps to the same wa_id
  await t.sendText({ accountId: "default", to: "whatsapp:+1 555 000 0001", text: "Again" });
  assert.equal(JSON.parse(f.calls[1].init.body).to, WA_ID);
  ac.abort();
});

test("CA-5 no retry: a 5xx, a 4xx, a 429 and a network error each make exactly one request and throw an error with no token, body, recipient or Meta text", async () => {
  const secretish = [CONFIG.accessToken, CONFIG.appSecret, CONFIG.verifyToken, "Hello there", WA_ID, "5550000001", "Meta says"];
  const cases = [
    [{ status: 500, json: { error: { message: "Meta says boom Hello there 15550000001", code: 1, fbtrace_id: "TRACE" } } }, /api-error \(http 500, code 1\)$/],
    [{ status: 400, json: { error: { message: "Meta says (#100) Invalid parameter", code: 100 } } }, /api-error \(http 400, code 100\)$/],
    [{ status: 429, json: { error: { message: "Meta says (#130429) Rate limit hit", code: 130429 } } }, /api-error \(http 429, code 130429\)$/],
    [{ status: 401, json: { error: { message: `Meta says token ${CONFIG.accessToken} expired`, code: 190 } } }, /api-error \(http 401, code 190\)$/],
    [{ status: 400, json: { error: { message: "Meta says re-engagement", code: 131047 } } }, /outside-customer-service-window \(http 400, code 131047\)$/],
    [{ status: 502, raw: "<html>Meta says bad gateway Hello there</html>" }, /api-error \(http 502\)$/],
    [{ throw: new Error(`Meta says fetch failed ${GRAPH_API_ORIGIN} Bearer ${CONFIG.accessToken} Hello there`) }, /network-error$/],
  ];
  for (const [answer, want] of cases) {
    const { t, f, lines, ac } = await openTransport({ answers: [answer] });
    const err = await t.sendText({ accountId: "default", to: PEER, text: "Hello there" }).then(() => null, (e) => e);
    assert.ok(err instanceof Error, JSON.stringify(answer.status));
    assert.match(err.message, want);
    assert.equal(f.calls.length, 1, "exactly one request, never a retry");
    const exposed = `${err.message} ${String(err.stack)} ${JSON.stringify(err)} ${JSON.stringify(lines)} ${String(err.cause ?? "")}`;
    for (const s of secretish) assert.ok(!exposed.includes(s), `${want}: leaked ${s}`);
    if (answer.status) assert.equal(err.status, answer.status);
    ac.abort();
  }
});

test("CA-6 abort: the caller's signal aborts the request through the joined signal, and an aborted fetch throws `aborted` without retrying", async () => {
  const { t, ac } = await openTransport({ openWindow: true });
  ac.abort();
  const calls = [];
  const t2 = createCloudApiTransport({
    config: CONFIG,
    now: () => T0,
    fetch: (url, init) => {
      calls.push(init.signal);
      return new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(Object.assign(new Error("This operation was aborted"), { name: "AbortError" }))));
    },
  });
  const sac = new AbortController();
  void t2.start({ accountId: "default", signal: sac.signal, onInbound: async () => {} });
  t2.webhook.handle(post(textPayload()));
  const sendAc = new AbortController();
  const p = t2.sendText({ accountId: "default", to: PEER, text: "Hello!", signal: sendAc.signal });
  await settle();
  sendAc.abort();
  await assert.rejects(p, /cloud api: aborted$/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].aborted, true, "the caller's abort reached the signal fetch was given");
  sac.abort();
  assert.ok(t);
});

test("CA-7 a 2xx answer without a usable message id returns an empty receipt (the gate then audits a sent-without-id)", async () => {
  for (const answer of [{ status: 200, json: { messages: [] } }, { status: 200, raw: "not json" }, { status: 201, json: { messages: [{ id: "" }] } }, { status: 200, json: { messages: [{ id: "bad id" }] } }]) {
    const { t, ac } = await openTransport({ answers: [answer] });
    assert.deepEqual(await t.sendText({ accountId: "default", to: PEER, text: "Hello!" }), {});
    ac.abort();
  }
});

test("CA-8 the transport refuses what Cloud API text cannot carry: empty or over-long text, a linked id or non-phone peer, another account", async () => {
  const { t, f, ac } = await openTransport();
  for (const [req, want] of [
    [{ to: PEER, text: "" }, /invalid-text/],
    [{ to: PEER, text: "x".repeat(4097) }, /invalid-text/],
    [{ to: PEER, text: 7 }, /invalid-text/],
    [{ to: "15550000001@lid", text: "hi" }, /unsupported-recipient/],
    [{ to: "someone", text: "hi" }, /unsupported-recipient/],
    [{ to: PEER, text: "hi", accountId: "other" }, /unknown-account/],
  ]) {
    await assert.rejects(t.sendText({ accountId: "default", ...req }), want);
  }
  assert.equal(f.calls.length, 0);
  ac.abort();
});

// ---- the 24-hour customer service window ---------------------------------------

test("CA-9 24-hour window: an unknown peer and a stale peer are refused before any request; a fresh peer is sent; the window and clock are injectable", async () => {
  const { t, f, clock, ac } = await openTransport({ openWindow: false });
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "hi" }), /outside-customer-service-window$/, "unknown peer");
  assert.equal(f.calls.length, 0);
  assert.equal(t.webhook.handle(post(textPayload())).status, 200);
  clock.t = T0 + CUSTOMER_SERVICE_WINDOW_MS;
  assert.deepEqual(await t.sendText({ accountId: "default", to: PEER, text: "hi" }), { messageId: "wamid.SENT-1" }, "exactly 24 h is still inside");
  clock.t = T0 + CUSTOMER_SERVICE_WINDOW_MS + 1;
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "hi" }), /outside-customer-service-window$/, "stale peer");
  assert.equal(f.calls.length, 1);
  // another peer's inbound opens nothing for this one
  clock.t = T0 + CUSTOMER_SERVICE_WINDOW_MS + 2;
  t.webhook.handle(post(textPayload({ from: OTHER_WA_ID, id: "wamid.OTHER", ts: String(Math.floor(clock.t / 1000)) })));
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "hi" }), /outside-customer-service-window/);
  assert.deepEqual(await t.sendText({ accountId: "default", to: "+15550000002", text: "hi" }), { messageId: "wamid.SENT-2" });
  ac.abort();
  // the window is anchored on Meta's message time, and injectable
  const short = await openTransport({ windowMs: 60_000 });
  short.clock.t = T0 + 60_001;
  await assert.rejects(short.t.sendText({ accountId: "default", to: PEER, text: "hi" }), /outside-customer-service-window/);
  short.ac.abort();
});

// ---- start / stop -------------------------------------------------------------

test("CA-10 start registers the sink and stays pending until its signal aborts; before start the webhook answers 503 so Meta retries; stop ends every pending start", async () => {
  const f = fakeFetch();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn, now: () => T0 });
  assert.equal(t.webhook.handle(post(textPayload())).status, 503, "not started: deferred, nothing delivered");
  const got = [];
  const ac = new AbortController();
  let settled = false;
  const p = t.start({ accountId: "default", signal: ac.signal, onInbound: async (m) => { got.push(m); } }).then(() => { settled = true; });
  await settle();
  assert.equal(settled, false, "pending while running");
  assert.equal(t.webhook.handle(post(textPayload())).status, 200);
  assert.equal(got.length, 1);
  ac.abort();
  await p;
  assert.equal(settled, true);
  assert.equal(t.webhook.handle(post(textPayload({ id: "wamid.AFTER" }))).status, 503, "after abort the sink is gone");
  // an already-aborted signal resolves at once; stop() resolves a start with no signal
  await t.start({ accountId: "default", signal: AbortSignal.abort(), onInbound: async () => {} });
  const q = t.start({ accountId: "default", onInbound: async () => {} });
  await t.stop();
  await q;
  await t.stop();
  await assert.rejects(t.start({ accountId: "default" }), /no-inbound-sink/);
  await assert.rejects(t.start({ accountId: "other", onInbound: async () => {} }), /unknown-account/);
});

// ---- webhook verification (GET) --------------------------------------------------

test("CA-11 GET verification: subscribe plus the exact verify token echoes the challenge as plain text; anything else is 403", () => {
  const { w, lines } = hook();
  const good = w.handle(verifyGet({ "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "1158201444" }));
  assert.equal(good.status, 200);
  assert.equal(good.body, "1158201444");
  assert.match(good.headers["content-type"], /^text\/plain/);
  assert.equal(good.headers["x-content-type-options"], "nosniff");
  for (const params of [
    { "hub.mode": "subscribe", "hub.verify_token": "wrong-token-of-some-length", "hub.challenge": "1" },
    { "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken.slice(0, -1), "hub.challenge": "1" },
    { "hub.mode": "subscribe", "hub.verify_token": `${CONFIG.verifyToken}x`, "hub.challenge": "1" },
    { "hub.mode": "unsubscribe", "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "1" },
    { "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "1" },
    { "hub.mode": "subscribe", "hub.challenge": "1" },
    { "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken },
    { "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "<script>x</script> y" },
  ]) {
    const r = w.handle(verifyGet(params));
    assert.equal(r.status, 403, JSON.stringify(params));
    assert.equal(r.body, "");
  }
  assert.equal(w.handle({ method: "GET", url: `/other?hub.mode=subscribe`, headers: {} }).status, 404);
  assert.equal(w.handle({ method: "PUT", url: PATH, headers: {}, body: Buffer.from("") }).status, 405);
  assert.ok(!JSON.stringify(lines).includes(CONFIG.verifyToken));
});

// ---- signature (POST) ------------------------------------------------------------

test("CA-12 signature: HMAC-SHA256 of the raw bytes with the app secret; missing, repeated, wrong prefix, wrong length, wrong secret, tampered body and a re-serialised body are all 401 with nothing delivered", () => {
  const { w, got } = hook();
  const raw = JSON.stringify(textPayload(), null, 2); // whitespace Meta might send
  const bytes = Buffer.from(raw, "utf8");
  const good = sign(bytes);
  const hex = good.slice("sha256=".length);
  const bad = [
    undefined,
    "",
    [good, good],
    hex,
    `sha1=${hex}`,
    `sha256=${hex.slice(0, 63)}`,
    `sha256=${hex}0`,
    `sha256=${"0".repeat(64)}`,
    sign(bytes, "anothersecretnotreal000000000000"),
    `sha256=${hex.replace(/./u, (c) => (c === "a" ? "b" : "a"))}`,
    ` ${good}`,
  ];
  for (const signature of bad) {
    const req = { method: "POST", url: PATH, headers: signature === undefined ? {} : { "x-hub-signature-256": signature }, body: bytes };
    assert.equal(w.handle(req).status, 401, JSON.stringify(signature));
  }
  // one changed byte in the body
  const tampered = Buffer.from(raw.replace("hi there", "hi thera"), "utf8");
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": good }, body: tampered }).status, 401);
  // JSON re-parse attack: the signature is over the raw bytes, so a compact re-serialisation
  // of the same object (what a parse-then-verify server would hash) does not verify
  const reserialised = Buffer.from(JSON.stringify(JSON.parse(raw)), "utf8");
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": good }, body: reserialised }).status, 401);
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": sign(reserialised) }, body: bytes }).status, 401);
  assert.equal(got.length, 0);
  // the right signature on the raw bytes passes, header name in any case, hex in either case
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "X-Hub-Signature-256": `sha256=${hex.toUpperCase()}` }, body: bytes }).status, 200);
  assert.equal(got.length, 1);
  assert.equal(signatureValid(bytes, good, CONFIG.appSecret), true);
  // a body that is not bytes is refused before any check
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": good }, body: raw }).status, 400);
});

test("CA-13 the signature is checked before any decode or parse: an unsigned body that would throw in JSON.parse is 401, a signed one is 400", () => {
  const { w, got } = hook();
  const junk = Buffer.from([0xff, 0xfe, 0x7b]);
  assert.equal(w.handle({ method: "POST", url: PATH, headers: {}, body: junk }).status, 401);
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": sign(junk) }, body: junk }).status, 400, "invalid UTF-8");
  const notJson = Buffer.from("{not json", "utf8");
  assert.equal(w.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": sign(notJson) }, body: notJson }).status, 400);
  assert.equal(got.length, 0);
});

// ---- payload parsing ---------------------------------------------------------------

test("CA-14 a text message from the configured number id is handed over once, mapped to the canonical peer, with Meta's time", () => {
  const { w, got } = hook();
  const r = w.handle(post(textPayload({ body: "Show me homes in <TEST_CITY>" })));
  assert.equal(r.status, 200);
  assert.deepEqual(got, [{ accountId: "default", peerId: PEER, text: "Show me homes in <TEST_CITY>", messageId: "wamid.TEST-1", receivedAt: T0 }]);
  assert.ok(Object.isFrozen(got[0]));
  // an explicit "default" account id is the same config
  const explicit = hook({ config: { ...CONFIG, accountId: "default" } });
  explicit.w.handle(post(textPayload()));
  assert.equal(explicit.got[0].accountId, "default");
});

test("CA-15 ignored with a 200 and no inbound: another phone-number id, statuses, non-text types, group and username-only senders, stale or future or malformed messages, other fields and objects", () => {
  const cases = {
    "other number id": textPayload({ phoneNumberId: "1000000000002" }),
    statuses: statusPayload(),
    image: (() => { const p = textPayload(); const m = p.entry[0].changes[0].value.messages[0]; m.type = "image"; delete m.text; m.image = { id: "MEDIA" }; return p; })(),
    reaction: (() => { const p = textPayload(); p.entry[0].changes[0].value.messages[0].type = "reaction"; return p; })(),
    group: textPayload({ extra: { group_id: "GROUP-TEST" } }),
    "username only (no from)": textPayload({ from: null }),
    "non-phone from": textPayload({ from: "abc" }),
    "empty body": textPayload({ body: "   " }),
    "over-long body": textPayload({ body: "x".repeat(CLOUD_INBOUND_TEXT_MAX_LENGTH + 1) }),
    stale: textPayload({ ts: String(Math.floor((T0 - MAX_INBOUND_AGE_MS - 1000) / 1000)) }),
    future: textPayload({ ts: String(Math.floor((T0 + 600_000) / 1000)) }),
    "bad timestamp": textPayload({ ts: "soon" }),
    "bad id": textPayload({ id: "has space" }),
    "other field": (() => { const p = textPayload(); p.entry[0].changes[0].field = "account_update"; return p; })(),
    "other product": (() => { const p = textPayload(); p.entry[0].changes[0].value.messaging_product = "other"; return p; })(),
    "other object": { ...textPayload(), object: "page" },
    "no entry": { object: "whatsapp_business_account" },
    "array payload": [textPayload()],
    "null payload": null,
  };
  for (const [name, payload] of Object.entries(cases)) {
    const { w, got } = hook();
    assert.equal(w.handle(post(payload)).status, 200, name);
    assert.equal(got.length, 0, name);
  }
});

test("CA-16 a batch delivers each valid text message and skips the rest; a duplicate id is delivered once within the TTL and again after it", () => {
  const { w, got, clock } = hook({ dedupeTtlMs: 60_000 });
  const p = textPayload();
  const v = p.entry[0].changes[0].value;
  v.messages.push({ from: OTHER_WA_ID, id: "wamid.TEST-2", timestamp: TS, type: "text", text: { body: "second" } });
  v.messages.push({ ...v.messages[0] }); // same id inside one POST
  v.statuses = [{ id: "wamid.OUT-1", status: "read", timestamp: TS, recipient_id: WA_ID }];
  assert.equal(w.handle(post(p)).status, 200);
  assert.deepEqual(got.map((m) => m.messageId), ["wamid.TEST-1", "wamid.TEST-2"]);
  // Meta's retry of the same POST
  assert.equal(w.handle(post(p)).status, 200);
  assert.equal(got.length, 2);
  clock.t = T0 + 60_001;
  const later = textPayload({ ts: String(Math.floor(clock.t / 1000)) });
  w.handle(post(later));
  assert.equal(got.length, 3, "past the dedupe TTL the id is new again");
  // the dedupe memory is bounded
  const small = hook({ dedupeMaxEntries: 2 });
  for (const id of ["a.1", "a.2", "a.3", "a.1"]) small.w.handle(post(textPayload({ id })));
  assert.deepEqual(small.got.map((m) => m.messageId), ["a.1", "a.2", "a.3", "a.1"], "the oldest id was evicted");
});

test("CA-17 a body over the limit is 413 before the signature or any parse, with nothing delivered", () => {
  const { w, got } = hook({ maxBodyBytes: 512 });
  const p = textPayload({ body: "x".repeat(600) });
  const r = post(p);
  assert.ok(r.body.byteLength > 512);
  assert.equal(w.handle(r).status, 413);
  assert.equal(w.handle({ ...r, headers: {} }).status, 413, "size first, then signature");
  assert.equal(got.length, 0);
});

test("CA-18 the agent run never holds the response: handle is synchronous and returns 200 while onInbound is still pending; a rejecting or throwing sink is logged without detail", async () => {
  let resolveRun;
  const pending = new Promise((r) => { resolveRun = r; });
  const { lines, log } = recorder();
  const w = createCloudApiWebhook({ config: CONFIG, now: () => T0, log, onInbound: () => pending });
  const r = w.handle(post(textPayload()));
  assert.ok(!(r instanceof Promise));
  assert.equal(r.status, 200);
  resolveRun();
  const rejecting = createCloudApiWebhook({ config: CONFIG, now: () => T0, log, onInbound: async () => { throw new Error(`boom ${PEER} hi there`); } });
  assert.equal(rejecting.handle(post(textPayload())).status, 200);
  const throwing = createCloudApiWebhook({ config: CONFIG, now: () => T0, log, onInbound: () => { throw new Error(`boom ${PEER}`); } });
  assert.equal(throwing.handle(post(textPayload())).status, 200);
  await settle();
  assert.deepEqual(lines.filter((l) => l.event === "inbound-handler-error").map((l) => l.reason).sort(), ["rejected", "threw"]);
  assert.ok(!JSON.stringify(lines).includes("5550000001"));
});

// ---- logs ----------------------------------------------------------------------

test("CA-19 logs carry events, reasons and counts only: no text, peer, message id, token, secret, verify token or signature", async () => {
  const { t, lines, ac } = await openTransport({ answers: [{ status: 200 }, { status: 500, json: { error: { message: "x", code: 2 } } }] });
  const body = Buffer.from(JSON.stringify(textPayload({ id: "wamid.LOGCHECK", body: "my private question" })), "utf8");
  const signature = sign(body);
  t.webhook.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": signature }, body });
  t.webhook.handle({ method: "POST", url: PATH, headers: { "x-hub-signature-256": `sha256=${"0".repeat(64)}` }, body });
  t.webhook.handle(verifyGet({ "hub.mode": "subscribe", "hub.verify_token": CONFIG.verifyToken, "hub.challenge": "abc" }));
  t.webhook.handle(verifyGet({ "hub.mode": "subscribe", "hub.verify_token": "nope-nope-nope-nope", "hub.challenge": "abc" }));
  await t.sendText({ accountId: "default", to: PEER, text: "a reply text" });
  await t.sendText({ accountId: "default", to: PEER, text: "a reply text" }).catch(() => {});
  ac.abort();
  assert.ok(lines.length >= 5);
  const all = JSON.stringify(lines);
  for (const s of ["my private question", "hi there", "a reply text", "5550000001", "wamid.", CONFIG.accessToken, CONFIG.appSecret, CONFIG.verifyToken, signature.slice(7), "nope-nope"]) {
    assert.ok(!all.includes(s), `log carries ${s}`);
  }
  for (const l of lines) {
    assert.equal(l.component, "idx-whatsapp-channel.cloud-api");
    for (const k of Object.keys(l)) assert.ok(["component", "event", "reason", "delivered", "ignored", "status", "apiCode"].includes(k), k);
  }
});

// ---- the host route adapter ------------------------------------------------------

/** A minimal IncomingMessage stand-in that streams `chunks` after a tick. */
function fakeReq({ method = "POST", url = PATH, headers = {}, chunks = [], end = true }) {
  const req = new EventEmitter();
  Object.assign(req, { method, url, headers, pause() {}, destroy() {} });
  setImmediate(() => {
    for (const c of chunks) req.emit("data", c);
    if (end) req.emit("end");
  });
  return req;
}
function fakeRes() {
  const res = { statusCode: 0, headers: {}, body: undefined, setHeader(k, v) { res.headers[k.toLowerCase()] = v; }, end(b) { res.body = b; } };
  return res;
}

test("CA-20 route adapter: reads the raw stream, answers from the handler, returns true; a declared or streamed oversize body is 413, a stalled body 408", async () => {
  const got = [];
  const w = createCloudApiWebhook({ config: CONFIG, now: () => T0, onInbound: (m) => { got.push(m); }, maxBodyBytes: 4096 });
  const route = createHttpRouteHandler(w, { readTimeoutMs: 50 });
  const bytes = Buffer.from(JSON.stringify(textPayload()), "utf8");
  const half = Math.floor(bytes.length / 2);
  const res = fakeRes();
  assert.equal(await route(fakeReq({ headers: { "x-hub-signature-256": sign(bytes) }, chunks: [bytes.subarray(0, half), bytes.subarray(half)] }), res), true);
  assert.equal(res.statusCode, 200);
  assert.equal(got.length, 1);
  const declared = fakeRes();
  await route(fakeReq({ headers: { "content-length": "999999" }, chunks: [] }), declared);
  assert.equal(declared.statusCode, 413);
  assert.equal(declared.headers.connection, "close");
  // a well-formed (here unverifiable) signature header gets the body read
  const shaped = { "x-hub-signature-256": `sha256=${"0".repeat(64)}` };
  const streamed = fakeRes();
  await route(fakeReq({ headers: shaped, chunks: [Buffer.alloc(3000), Buffer.alloc(3000)] }), streamed);
  assert.equal(streamed.statusCode, 413);
  const stalled = fakeRes();
  await route(fakeReq({ headers: shaped, chunks: [Buffer.from("{")], end: false }), stalled);
  assert.equal(stalled.statusCode, 408);
  const verify = fakeRes();
  await route(fakeReq({ method: "GET", url: `${PATH}?hub.mode=subscribe&hub.verify_token=${CONFIG.verifyToken}&hub.challenge=42`, chunks: [] }), verify);
  assert.equal(verify.statusCode, 200);
  assert.equal(verify.body, "42");
  assert.equal(got.length, 1);
});

// ---- end to end through the channel's gate -----------------------------------------

test("CA-21 end to end on fakes: a signed inbound from an allowlisted peer runs a turn and the gate's reply leaves as one Cloud API request; a peer outside the allowlist gets nothing", async () => {
  const f = fakeFetch();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn, now: () => T0 });
  const host = createFakeHost({ replies: () => "Hello!" });
  const plugin = createChannelPlugin({ transport: t, ingress: createIngress({ now: () => T0 }), now: () => T0, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  const cfg = { plugins: { deny: ["whatsapp"] }, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER] } } };
  assert.equal(plugin.config.isConfigured(), true);
  const ac = new AbortController();
  const running = plugin.gateway.startAccount({ cfg, accountId: "default", abortSignal: ac.signal });
  await settle();
  assert.equal(t.webhook.handle(post(textPayload())).status, 200);
  for (let i = 0; i < 20 && f.calls.length === 0; i += 1) await settle();
  assert.equal(f.calls.length, 1);
  assert.deepEqual(JSON.parse(f.calls[0].init.body).text, { preview_url: false, body: "Hello!" });
  assert.equal(JSON.parse(f.calls[0].init.body).to, WA_ID);
  // a stranger's DM: the webhook accepts it, the channel's allowlist drops it, nothing is sent
  assert.equal(t.webhook.handle(post(textPayload({ from: "15550000009", id: "wamid.STRANGER" }))).status, 200);
  for (let i = 0; i < 10; i += 1) await settle();
  assert.equal(f.calls.length, 1);
  ac.abort();
  await running;
});

// ---- source ---------------------------------------------------------------------

test("CA-22 source: no hard-coded credential, id or number; built-in and local imports only; no environment or file read; not imported by the entry", () => {
  const src = readFileSync(new URL("./cloud-api-transport.mjs", import.meta.url), "utf8");
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const imports = [...code.matchAll(/^\s*import\b[^;]*?\bfrom\s+"([^"]+)"/gms)].map((m) => m[1]);
  assert.deepEqual(imports, ["node:buffer", "node:crypto", "./ingress.mjs"]);
  assert.ok(!/\bimport\s*\(/.test(code), "no dynamic import");
  assert.ok(!/\brequire\s*\(/.test(code));
  for (const banned of [/process\.env/, /readFile/, /\bfs\b/, /\bhttps?\.request\b/, /globalThis\.fetch/, /\bexport\s+default\b/]) {
    assert.ok(!banned.test(code), String(banned));
  }
  // the only URL is the fixed Graph origin; no token, secret, id or phone literal
  const urls = [...src.matchAll(/https?:\/\/[^\s"'`)]+/g)].map((m) => m[0]);
  assert.deepEqual([...new Set(urls)], [GRAPH_API_ORIGIN]);
  assert.ok(!/EAA[A-Za-z0-9]/.test(src), "no Meta-style access token");
  assert.ok(!/Bearer [A-Za-z0-9]/.test(src), "the bearer value is never a literal");
  assert.ok(!/["'`][0-9a-f]{32}["'`]/i.test(src), "no app-secret-shaped literal");
  const digitRuns = [...code.replace(/\b\d{1,3}(?:_\d{3})+\b/g, "").matchAll(/\d{7,}/g)].map((m) => m[0]);
  assert.deepEqual(digitRuns, [], "no long digit literal (phone number or phone-number id)");
  assert.ok(!/\+\d/.test(code.replace(/\/[^/\n]*\/u/g, "")), "no +<digits> literal outside regexes");
  // the entry still ships the unavailable transport and does not import this module
  const index = readFileSync(new URL("./index.mjs", import.meta.url), "utf8");
  assert.ok(!index.includes("cloud-api-transport"));
  assert.match(index, /export function createPluginEntry\(\{ transport = unavailableTransport, cardResolver \} = \{\}\)/);
  const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
  assert.ok(!pkg.files.includes("cloud-api-transport.mjs"), "staged, not shipped");
});

// ---- review fixes ------------------------------------------------------------------

/** A request whose listeners are counted, so a test can see whether the body was read. */
function countedReq(opts) {
  const req = fakeReq(opts);
  req.dataListenersEver = 0;
  const on = req.on.bind(req);
  req.on = (ev, fn) => {
    if (ev === "data") req.dataListenersEver += 1;
    return on(ev, fn);
  };
  return req;
}

test("CA-23 route adapter: an unsigned or malformed-signature POST is 401 before any body byte is buffered; reads in flight are capped (503 retry-after); an idle body is 408 before the overall deadline", async () => {
  const got = [];
  const w = createCloudApiWebhook({ config: CONFIG, now: () => T0, onInbound: (m) => { got.push(m); } });
  const route = createHttpRouteHandler(w, { readTimeoutMs: 80, idleTimeoutMs: 80, maxConcurrentReads: 2 });
  const big = [Buffer.alloc(512 * 1024)];
  for (const headers of [{}, { "x-hub-signature-256": "" }, { "x-hub-signature-256": "sha256=zz" }, { "x-hub-signature-256": ["a", "b"] }, { "x-hub-signature-256": `sha1=${"0".repeat(64)}` }]) {
    const req = countedReq({ headers: { "content-length": String(512 * 1024), ...headers }, chunks: big, end: false });
    const res = fakeRes();
    assert.equal(await route(req, res), true);
    assert.equal(res.statusCode, 401, JSON.stringify(headers));
    assert.equal(res.headers.connection, "close");
    assert.equal(req.dataListenersEver, 0, "the body was never read");
  }
  // two stalled, well-formed-but-fake signed reads fill the cap; a third is turned away unread
  const shaped = { "x-hub-signature-256": `sha256=${"0".repeat(64)}` };
  const a = route(fakeReq({ headers: shaped, chunks: [], end: false }), fakeRes());
  const b = route(fakeReq({ headers: shaped, chunks: [], end: false }), fakeRes());
  const third = countedReq({ headers: shaped, chunks: big, end: false });
  const busy = fakeRes();
  await route(third, busy);
  assert.equal(busy.statusCode, 503);
  assert.equal(busy.headers["retry-after"], "5");
  assert.equal(busy.headers.connection, "close");
  assert.equal(third.dataListenersEver, 0);
  await Promise.all([a, b]);
  // the slots are released after the stalled reads time out
  const bytes = Buffer.from(JSON.stringify(textPayload()), "utf8");
  const ok = fakeRes();
  await route(fakeReq({ headers: { "x-hub-signature-256": sign(bytes) }, chunks: [bytes] }), ok);
  assert.equal(ok.statusCode, 200);
  assert.equal(got.length, 1);
  // idle gap: one chunk then silence ends the read long before the overall deadline
  const slow = createHttpRouteHandler(w, { readTimeoutMs: 60_000, idleTimeoutMs: 30 });
  const idle = fakeRes();
  const t0 = Date.now();
  await slow(fakeReq({ headers: shaped, chunks: [Buffer.from("{")], end: false }), idle);
  assert.equal(idle.statusCode, 408);
  assert.ok(Date.now() - t0 < 5_000, "idle timeout, not the overall deadline");
});

test("CA-24 the window entry of a peer whose turn is running cannot be evicted by a flood of senders the allowlist drops; once the turn ends the table is bounded again", async () => {
  const f = fakeFetch();
  const clock = { t: T0 };
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn, now: () => clock.t });
  let release;
  const turnHeld = new Promise((r) => { release = r; });
  const host = createFakeHost({ replies: async () => { await turnHeld; return "Hello!"; } });
  const plugin = createChannelPlugin({ transport: t, ingress: createIngress({ now: () => clock.t }), now: () => clock.t, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  const cfg = { plugins: { deny: ["whatsapp"] }, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER] } } };
  const ac = new AbortController();
  const running = plugin.gateway.startAccount({ cfg, accountId: "default", abortSignal: ac.signal });
  await settle();
  assert.equal(t.webhook.handle(post(textPayload())).status, 200);
  await settle();
  /** One signed batch from `n` distinct synthetic senders outside the allowlist. */
  const flood = (n, tag) => {
    const p = textPayload();
    p.entry[0].changes[0].value.messages = Array.from({ length: n }, (_, i) => ({
      from: `1555200${String(i).padStart(4, "0")}`, id: `wamid.${tag}-${i}`, timestamp: String(Math.floor(clock.t / 1000)), type: "text", text: { body: "spam" },
    }));
    return post(p);
  };
  clock.t = T0 + 60_000;
  assert.equal(t.webhook.handle(flood(WINDOW_MAX_PEERS, "FLOOD")).status, 200);
  for (let i = 0; i < 5; i += 1) await settle();
  // the turn now releases its reply: it leaves as one Cloud API request, not a local refusal
  release();
  for (let i = 0; i < 40 && f.calls.length === 0; i += 1) await settle();
  assert.equal(f.calls.length, 1, "the allowlisted peer's reply was sent");
  assert.equal(JSON.parse(f.calls[0].init.body).to, WA_ID);
  for (let i = 0; i < 10; i += 1) await settle();
  // with no turn running, the table is an ordinary bounded LRU again: a second flood evicts
  // the peer, and a send outside any turn is refused locally
  assert.equal(t.webhook.handle(flood(WINDOW_MAX_PEERS, "FLOOD2")).status, 200);
  for (let i = 0; i < 5; i += 1) await settle();
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "hi" }), /outside-customer-service-window$/);
  assert.equal(f.calls.length, 1);
  ac.abort();
  await running;
});

test("CA-25 a `failed` status (Meta's asynchronous send error) is logged as send-failed-async with Meta's numeric code only; other statuses stay silent", () => {
  const { w, got, lines } = hook();
  const p = statusPayload();
  p.entry[0].changes[0].value.statuses = [
    { id: "wamid.OUT-1", status: "failed", timestamp: TS, recipient_id: WA_ID, errors: [{ code: 131047, title: "Meta says re-engagement", message: `Meta says ${WA_ID}`, error_data: { details: "Meta says details" } }] },
    { id: "wamid.OUT-2", status: "failed", timestamp: TS, recipient_id: WA_ID, errors: [{ code: 131026, title: "Meta says undeliverable" }] },
    { id: "wamid.OUT-3", status: "failed", timestamp: TS, recipient_id: WA_ID },
    { id: "wamid.OUT-4", status: "failed", timestamp: TS, recipient_id: WA_ID, errors: [{ code: "131049" }] },
    { id: "wamid.OUT-5", status: "delivered", timestamp: TS, recipient_id: WA_ID },
    "junk",
  ];
  assert.equal(w.handle(post(p)).status, 200);
  assert.equal(got.length, 0);
  const failed = lines.filter((l) => l.event === "send-failed-async");
  assert.deepEqual(failed.map(({ reason, apiCode }) => ({ reason, apiCode })), [
    { reason: "outside-customer-service-window", apiCode: 131047 },
    { reason: "delivery-failed", apiCode: 131026 },
    { reason: "delivery-failed", apiCode: undefined },
    { reason: "delivery-failed", apiCode: undefined },
  ]);
  for (const l of failed) assert.deepEqual(Object.keys(l).filter((k) => !["component", "event", "reason", "apiCode"].includes(k)), []);
  const all = JSON.stringify(lines);
  for (const s of ["wamid.", "5550000001", "Meta says"]) assert.ok(!all.includes(s), `log carries ${s}`);
  // a status for another phone-number id is not ours and stays silent
  const other = hook();
  const q = statusPayload();
  q.entry[0].changes[0].value.metadata.phone_number_id = "1000000000002";
  q.entry[0].changes[0].value.statuses[0].status = "failed";
  other.w.handle(post(q));
  assert.equal(other.lines.filter((l) => l.event === "send-failed-async").length, 0);
});

test("CA-26 inbound text longer than the 4096-character send limit is delivered intact; only a body over CLOUD_INBOUND_TEXT_MAX_LENGTH is dropped, with a too-long warning", () => {
  const { w, got, lines } = hook();
  const long = "x".repeat(5000);
  const emoji = "\u{1F3E0}".repeat(2100); // 4200 UTF-16 code units
  const cap = "y".repeat(CLOUD_INBOUND_TEXT_MAX_LENGTH);
  w.handle(post(textPayload({ id: "wamid.L1", body: long })));
  w.handle(post(textPayload({ id: "wamid.L2", body: emoji })));
  w.handle(post(textPayload({ id: "wamid.L3", body: cap })));
  assert.deepEqual(got.map((m) => m.text.length), [5000, 4200, CLOUD_INBOUND_TEXT_MAX_LENGTH]);
  assert.equal(got[0].text, long);
  assert.equal(lines.filter((l) => l.reason === "too-long").length, 0);
  assert.equal(w.handle(post(textPayload({ id: "wamid.L4", body: `${cap}z` }))).status, 200);
  assert.equal(got.length, 3);
  assert.deepEqual(lines.filter((l) => l.reason === "too-long").map((l) => [l.event, l.reason]), [["inbound-dropped", "too-long"]]);
  assert.ok(!JSON.stringify(lines).includes("yyyy"));
});

test("CA-27 only the default account id is accepted, since the channel lists and starts only that one; any other id leaves the transport unconfigured", async () => {
  for (const accountId of ["buyers", "Default", "default ", "", 7]) {
    assert.equal(readCloudApiConfig({ ...CONFIG, accountId }), null, JSON.stringify(accountId));
    const t = createCloudApiTransport({ config: { ...CONFIG, accountId }, fetch: async () => new Response("{}") });
    assert.equal(t.isConfigured(), false);
    const plugin = createChannelPlugin({ transport: t, ingress: createIngress({ now: () => T0 }), now: () => T0 });
    assert.equal(plugin.config.isConfigured(), false, "the channel reports it, instead of a 503 forever");
  }
  const t = createCloudApiTransport({ config: { ...CONFIG, accountId: "default" }, fetch: async () => new Response("{}") });
  assert.equal(t.isConfigured(), true);
  const plugin = createChannelPlugin({ transport: t, ingress: createIngress({ now: () => T0 }), now: () => T0 });
  assert.deepEqual(plugin.config.listAccountIds(), ["default"]);
});

test("CA-28 dedupe is in memory: one transport keeps it across a channel restart (stop and start); a new instance (a gateway restart) accepts a seen id again only inside the inbound age limit (documented residual risk)", async () => {
  const f = fakeFetch();
  const clock = { t: T0 };
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn, now: () => clock.t });
  const got = [];
  let ac = new AbortController();
  let running = t.start({ accountId: "default", signal: ac.signal, onInbound: async (m) => { got.push(m); } });
  const once = post(textPayload({ id: "wamid.RESTART" }));
  assert.equal(t.webhook.handle(once).status, 200);
  ac.abort();
  await running;
  ac = new AbortController();
  running = t.start({ accountId: "default", signal: ac.signal, onInbound: async (m) => { got.push(m); } });
  assert.equal(t.webhook.handle(once).status, 200);
  assert.equal(got.length, 1, "a channel restart on the same transport still drops the duplicate");
  ac.abort();
  await running;
  // a gateway restart: a fresh instance has no memory of the id
  const inside = hook();
  inside.clock.t = T0 + 20 * 60_000;
  inside.w.handle(once);
  assert.equal(inside.got.length, 1, "residual: accepted again within the age limit");
  const outside = hook();
  outside.clock.t = T0 + MAX_INBOUND_AGE_MS + 1000;
  outside.w.handle(once);
  assert.equal(outside.got.length, 0, "the age limit bounds the replay window");
});
