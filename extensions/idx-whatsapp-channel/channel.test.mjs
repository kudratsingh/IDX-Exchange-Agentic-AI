import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createChannelPlugin } from "./channel.mjs";
import { INGRESS_MAX_ENTRIES, SAFE_TEXT, VERIFIER_DEADLINE_MS } from "./constants.mjs";
import entry from "./index.mjs";
import { createIngress, normalizePeerId } from "./ingress.mjs";
import { createOutbound } from "./outbound.mjs";
import { SELF_TEST_VECTORS, selfCheck, verifierSelfTest } from "./self-check.mjs";
import { createInMemoryCardResolver } from "./test-support/fake-card-resolver.mjs";
import { createFakeTransport } from "./test-support/fake-transport.mjs";
import { createFakeApi, createFakeHost } from "./test-support/host-emulation.mjs";
import { NO_TRANSPORT_MESSAGE } from "./transport.mjs";
import { verifyReply } from "./verifier.mjs";

const PEER = "+15550000001";
const SESSION = `agent:idx:whatsapp:direct:${PEER}`;
const DENY_CFG = { plugins: { deny: ["whatsapp"] } };

/** A gate over a fake transport with one open turn for PEER. */
function gate(overrides = {}, inboundText = "hi") {
  let t = 1000;
  const now = () => t;
  const transport = createFakeTransport();
  const ingress = createIngress({ now });
  if (inboundText !== null) {
    ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: inboundText, receivedAt: t });
  }
  const outbound = createOutbound({ transport, ingress, ...overrides });
  return { transport, ingress, outbound, advance: (ms) => { t += ms; } };
}

const RAW = "We have 12 homes for you";

// ---- fail-closed: verifier throws / deadline / malformed ------------------

test("FC-verifier-throws: raw text never sent; SAFE_TEXT in safe-text mode", async () => {
  const { transport, outbound } = gate({ verify: () => { throw new Error("boom"); } });
  const r = await outbound.sendText({ to: PEER, text: RAW, accountId: "default" });
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  assert.equal(typeof r.messageId, "string");
});

test("FC-verifier-throws: silent mode sends nothing and returns not_sent", async () => {
  const { transport, outbound } = gate({ verify: () => { throw new Error("boom"); }, withholdMode: "silent" });
  const r = await outbound.sendText({ to: PEER, text: RAW, accountId: "default" });
  assert.deepEqual(r, { outcome: "not_sent", reason: "verifier-threw" });
  assert.equal(transport.sent.length, 0);
});

test("FC-verifier-deadline: a slow release verdict is withheld; the same verdict in time is sent", async () => {
  let c = 0;
  const clock = () => c;
  const text = "Hello there";
  const slow = ({ text: t }) => { c += VERIFIER_DEADLINE_MS + 1; return { kind: "release", rule: "no-figures", text: t }; };
  const fast = ({ text: t }) => { c += 1; return { kind: "release", rule: "no-figures", text: t }; };

  const a = gate({ verify: slow, clock });
  await a.outbound.sendText({ to: PEER, text, accountId: "default" });
  assert.deepEqual(a.transport.sent.map((s) => s.text), [SAFE_TEXT]);

  const b = gate({ verify: slow, clock, withholdMode: "silent" });
  assert.deepEqual(await b.outbound.sendText({ to: PEER, text, accountId: "default" }), { outcome: "not_sent", reason: "verifier-deadline" });
  assert.equal(b.transport.sent.length, 0);

  const d = gate({ verify: fast, clock });
  await d.outbound.sendText({ to: PEER, text, accountId: "default" });
  assert.deepEqual(d.transport.sent.map((s) => s.text), [text]);
});

test("FC-verifier-malformed: every malformed verdict withholds and the raw text is never sent", async () => {
  const text = "There are 12 homes";
  const malformed = [
    undefined,
    null,
    "release",
    42,
    { kind: "release" },
    { kind: "release", text: 7 },
    { kind: "release", text: "altered text" },
    { kind: "release", viaCard: true, rule: "card", text: "invented 12 homes" },
    { kind: "other", text },
    Promise.resolve({ kind: "release", text }),
    { kind: "release", text, then: () => {} },
  ];
  for (const v of malformed) {
    const { transport, outbound } = gate({ verify: () => v, withholdMode: "silent" });
    const r = await outbound.sendText({ to: PEER, text, accountId: "default" });
    assert.deepEqual(r, { outcome: "not_sent", reason: "verifier-malformed" }, String(v));
    assert.equal(transport.sent.length, 0);
    const s = gate({ verify: () => v });
    await s.outbound.sendText({ to: PEER, text, accountId: "default" });
    assert.deepEqual(s.transport.sent.map((x) => x.text), [SAFE_TEXT]);
  }
});

test("FC-single-call-site (behavioural): over many inputs the transport only ever sees the verdict text or SAFE_TEXT", async () => {
  const inputs = [
    "Hello!", "Hi there, how can I help?", "There are 12 homes", "Do you mean 3 or 4 bedrooms?", "34 bedrooms?",
    "", "   ", "Priced at 850000", "[[card:a]]", "[[card:a", "Built 1998", "Twelve homes", "٣ homes", "a".repeat(4001),
    "Can you share your budget?", "Under 800000?", "Pasadena it is.", "1. one 2. two", "24/7", "ok", "Sure thing",
    "What area?", "Condo or house?", "3 or 4 it is", "Both 3 and 4 work", "4 then", "5 then", "Great, 3 bedrooms",
    "Which city?", "Anything else?",
  ];
  const { transport, outbound } = gate({}, "3 or 4");
  for (const text of inputs) {
    try {
      await outbound.sendText({ to: PEER, text, accountId: "default" });
    } catch (e) {
      assert.fail(String(e));
    }
  }
  const allowed = new Set([SAFE_TEXT, ...inputs.map((t) => verifyReply({ text: t, inbound: { sessionKey: SESSION, turnId: "t1", text: "3 or 4" }, resolver: { resolve: () => null } })).filter((v) => v.kind === "release").map((v) => v.text)]);
  assert.equal(transport.sent.length, inputs.length);
  for (const s of transport.sent) assert.ok(allowed.has(s.text), JSON.stringify(s.text));
  assert.ok(transport.sent.some((s) => s.text === "Do you mean 3 or 4 bedrooms?"));
  assert.ok(!transport.sent.some((s) => s.text === "There are 12 homes"));
});

test("no inbound record: withheld silently even in safe-text mode", async () => {
  const { transport, outbound } = gate({}, null);
  assert.deepEqual(await outbound.sendText({ to: PEER, text: "Hello", accountId: "default" }), { outcome: "not_sent", reason: "no-inbound-record" });
  assert.equal(transport.sent.length, 0);
});

test("transport returning no messageId after a send makes sendText reject, never not_sent", async () => {
  const { transport, outbound } = gate();
  transport.emptyReceiptNextSend();
  await assert.rejects(outbound.sendText({ to: PEER, text: "Hello", accountId: "default" }), /no messageId/);
  assert.equal(transport.sent.length, 1);
});

test("a transport error propagates and is not retried", async () => {
  const { transport, outbound } = gate();
  let calls = 0;
  const orig = transport.sendText;
  transport.sendText = async (req) => { calls += 1; return orig(req); };
  transport.failNextSend(new Error("network down"));
  await assert.rejects(outbound.sendText({ to: PEER, text: "Hello", accountId: "default" }), /network down/);
  assert.equal(calls, 1);
  assert.equal(transport.sent.length, 0);
});

// ---- normalizePayload ------------------------------------------------------

test("normalizePayload: host envelope, pass-through and idempotency", () => {
  const { outbound } = gate();
  const env = (payload) => ({ payload, cfg: {}, accountId: "default" });
  assert.deepEqual(outbound.normalizePayload(env({ text: "Hello!" })), { text: "Hello!" });
  // exact message-tool default payload
  assert.deepEqual(outbound.normalizePayload(env({ text: "Hello!", mediaUrl: undefined, mediaUrls: undefined, audioAsVoice: false })), { text: "Hello!" });
  // exact normalizeOutboundReplyPayload output with a quote target
  const reply = { text: "Hello!", mediaUrls: undefined, mediaUrl: undefined, presentation: undefined, interactive: undefined, channelData: undefined, sensitiveMedia: undefined, replyToId: "ABC" };
  assert.deepEqual(outbound.normalizePayload(env(reply)), { text: "Hello!", replyToId: "ABC" });
  assert.deepEqual(outbound.normalizePayload(env({ text: "Hello!", mediaUrls: [] })), { text: "Hello!" });
  for (const x of [{ text: "Hello!" }, reply, { text: SAFE_TEXT }, { text: "cap", mediaUrl: "https://example.com/a.jpg" }]) {
    const once = outbound.normalizePayload(env(x));
    assert.deepEqual(outbound.normalizePayload(env(once)), once);
  }
});

test("normalizePayload: any present non-text content refuses the whole payload (caption dropped)", async () => {
  const bad = [
    { text: "caption", mediaUrl: "https://example.com/a.jpg" },
    { text: "caption", mediaUrls: ["https://example.com/a.jpg"] },
    { text: "caption", presentation: { kind: "card" } },
    { text: "caption", interactive: { buttons: [] } },
    { text: "caption", location: { lat: 1, lon: 2 } },
    { text: "caption", channelData: { x: 1 } },
    { text: "caption", poll: { question: "q", options: ["a", "b"] } },
    { text: "caption", fallbackText: "fb" },
    { text: "caption", spokenText: "sp" },
    { text: "caption", audioAsVoice: true },
    { text: "caption", unknownKey: "x" },
    { text: "caption", replyToId: 42 },
    "just a string",
    null,
    ["text"],
  ];
  const { transport, outbound } = gate();
  for (const payload of bad) {
    assert.deepEqual(outbound.normalizePayload({ payload, cfg: {}, accountId: "default" }), { text: SAFE_TEXT }, JSON.stringify(payload));
  }
  const silent = gate({ withholdMode: "silent" });
  for (const payload of bad) {
    assert.equal(silent.outbound.normalizePayload({ payload, cfg: {}, accountId: "default" }), null);
  }
  // an empty text with nothing else is no visible payload, not a refusal
  assert.equal(outbound.normalizePayload({ payload: { text: "" }, cfg: {} }), null);
  assert.equal(outbound.normalizePayload({ payload: {}, cfg: {} }), null);
  assert.equal(transport.sent.length, 0);
});

// ---- ingress ---------------------------------------------------------------

test("ingress: round trip, newer replaces older, expiry, eviction, normalization", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100, maxEntries: 3 });
  const k = ing.key("default", PEER);
  assert.equal(ing.current(k), null);
  ing.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.equal(ing.current(k).turnId, "t1");
  ing.record(k, { sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 1 });
  assert.equal(ing.current(k).turnId, "t2");
  t = 101;
  assert.equal(ing.current(k), null);
  t = 0;
  for (const p of ["+15550000001", "+15550000002", "+15550000003", "+15550000004"]) {
    ing.record(ing.key("default", p), { sessionKey: "s", turnId: p, text: "", receivedAt: 0 });
  }
  assert.equal(ing.size(), 3);
  assert.equal(ing.current(ing.key("default", "+15550000001")), null);
  assert.equal(ing.current(ing.key("default", "+15550000004")).turnId, "+15550000004");
  for (const spelling of ["+15550000001", "15550000001", "+1 (555) 000-0001", "15550000001@s.whatsapp.net", "whatsapp:+15550000001", "WHATSAPP:15550000001@lid", "  +1-555-000-0001 "]) {
    assert.equal(normalizePeerId(spelling), "+15550000001", spelling);
    assert.equal(ing.key("default", spelling), k);
  }
  assert.equal(normalizePeerId("Group-ABC@g.us"), "group-abc@g.us");
  assert.equal(ing.key("acct2", PEER) === k, false);
  assert.equal(INGRESS_MAX_ENTRIES, 512);
});

test("audit log never carries text, peer or session key", async () => {
  const lines = [];
  const log = { info: (o) => lines.push(o), warn: (o) => lines.push(o), error: (o) => lines.push(o) };
  const { outbound } = gate({ log }, "3 or 4");
  await outbound.sendText({ to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" });
  await outbound.sendText({ to: PEER, text: "There are 12 homes", accountId: "default" });
  await outbound.sendText({ to: "+15550000009", text: "Hello", accountId: "default" });
  assert.equal(lines.length, 3);
  const blob = JSON.stringify(lines);
  for (const forbidden of ["bedrooms", "12 homes", "Hello", "5550000", SESSION, SAFE_TEXT]) assert.ok(!blob.includes(forbidden), forbidden);
  for (const line of lines) {
    assert.equal(typeof line.outcome, "string");
    assert.equal(typeof line.hasRecord, "boolean");
    assert.equal(typeof line.textLength, "number");
  }
});

// ---- startup self-check and register(api) ---------------------------------

test("FC-no-stock-fallback: register refuses unless the host config denies the stock plugin", () => {
  for (const cfg of [undefined, null, "x", {}, { plugins: {} }, { plugins: { deny: [] } }, { plugins: { deny: ["telegram"] } }, { plugins: { deny: [123] } }, { plugins: { entries: { whatsapp: { enabled: false } } } }]) {
    const { api, registered } = createFakeApi({ cfg });
    assert.throws(() => entry.register(api), /stock-whatsapp-not-denied|config-missing/, JSON.stringify(cfg));
    assert.equal(registered.length, 0);
  }
  for (const cfg of [DENY_CFG, { plugins: { deny: [" WhatsApp "] } }, { plugins: { deny: ["telegram", "whatsapp"] } }]) {
    const { api, registered } = createFakeApi({ cfg });
    entry.register(api);
    assert.equal(registered.length, 1);
    assert.equal(registered[0].plugin.id, "whatsapp");
  }
});

test("registration modes: skip for cli-metadata and tool-discovery, register otherwise, refuse unknown", () => {
  for (const mode of ["cli-metadata", "tool-discovery"]) {
    const { api, registered } = createFakeApi({ cfg: {}, registrationMode: mode });
    entry.register(api); // no throw even without the deny
    assert.equal(registered.length, 0);
  }
  for (const mode of ["full", "discovery", "setup-only", "setup-runtime"]) {
    const ok = createFakeApi({ cfg: DENY_CFG, registrationMode: mode });
    entry.register(ok.api);
    assert.equal(ok.registered.length, 1, mode);
    const bad = createFakeApi({ cfg: {}, registrationMode: mode });
    assert.throws(() => entry.register(bad.api), /stock-whatsapp-not-denied/);
    assert.equal(bad.registered.length, 0);
  }
  assert.throws(() => entry.register(createFakeApi({ cfg: DENY_CFG, registrationMode: "made-up" }).api), /unknown registration mode/);
});

test("the registered plugin meets the registerChannel requirements and has no bypass surfaces", () => {
  const { api, registered } = createFakeApi({ cfg: DENY_CFG });
  entry.register(api);
  const plugin = registered[0].plugin;
  assert.equal(typeof plugin.id, "string");
  assert.ok(plugin.id.length > 0);
  assert.ok(Array.isArray(plugin.capabilities.chatTypes) && plugin.capabilities.chatTypes.length > 0);
  for (const t of plugin.capabilities.chatTypes) assert.ok(["direct", "group", "channel", "thread"].includes(t));
  assert.deepEqual(plugin.capabilities.chatTypes, ["direct"]);
  assert.equal(typeof plugin.config.listAccountIds, "function");
  assert.equal(typeof plugin.config.resolveAccount, "function");
  assert.equal(plugin.config.isConfigured({}, {}), false);
  for (const k of ["label", "selectionLabel", "docsPath", "blurb"]) assert.equal(typeof plugin.meta[k], "string");
  for (const absent of ["message", "actions", "messaging", "auth", "heartbeat", "directory"]) assert.equal(absent in plugin, false, absent);
  for (const absent of ["sendMedia", "sendPayload", "sendPoll", "chunker", "sendTextOnlyErrorPayloads", "resolveTarget"]) assert.equal(absent in plugin.outbound, false, absent);
  assert.equal(plugin.outbound.deliveryMode, "gateway");
});

test("manifest shape and SAFE_TEXT", () => {
  const manifest = JSON.parse(readFileSync(new URL("./openclaw.plugin.json", import.meta.url), "utf8"));
  assert.notEqual(manifest.id, "whatsapp");
  assert.equal(manifest.id, entry.id);
  assert.deepEqual(manifest.channels, ["whatsapp"]);
  assert.deepEqual(manifest.channelConfigs.whatsapp.preferOver, ["whatsapp"]);
  assert.equal(typeof manifest.configSchema, "object");
  assert.equal(typeof manifest.channelConfigs.whatsapp.schema, "object");
  assert.equal(/\p{Nd}/u.test(SAFE_TEXT), false);
});

test("self-check unit: vectors pass against the shipped verifier; a digit in SAFE_TEXT is refused", () => {
  assert.ok(SELF_TEST_VECTORS.length >= 6);
  assert.equal(verifierSelfTest(verifyReply), true);
  assert.deepEqual(selfCheck(DENY_CFG), { ok: true });
  assert.deepEqual(selfCheck(DENY_CFG, { safeText: "Try again in 5 minutes" }), { ok: false, reason: "safe-text-invalid" });
  assert.deepEqual(selfCheck(DENY_CFG, { safeText: "" }), { ok: false, reason: "safe-text-invalid" });
  assert.deepEqual(selfCheck(DENY_CFG, { verify: ({ text }) => ({ kind: "release", rule: "no-figures", text }) }), { ok: false, reason: "verifier-self-test-failed" });
  assert.deepEqual(selfCheck(DENY_CFG, { verify: () => { throw new Error("x"); } }), { ok: false, reason: "verifier-self-test-failed" });
});

// ---- default transport ------------------------------------------------------

test("default transport: unconfigured, startAccount rejects, sendText rejects once, no retry", async () => {
  const plugin = createChannelPlugin();
  assert.equal(plugin.config.isConfigured({}, {}), false);
  await assert.rejects(plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" }), new RegExp(NO_TRANSPORT_MESSAGE.replace(/[()]/g, "\\$&")));
  // even with an open turn, nothing can go out
  const ingress = createIngress({ now: () => 0 });
  ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  const withTurn = createChannelPlugin({ ingress });
  await assert.rejects(withTurn.outbound.sendText({ to: PEER, text: "Hello", accountId: "default" }), /no transport configured/);
  assert.deepEqual(selfCheck(DENY_CFG), { ok: true });
  const fake = createChannelPlugin({ transport: createFakeTransport() });
  assert.equal(fake.config.isConfigured({}, {}), true);
});

// ---- end to end on the fake transport ----------------------------------------

test("end to end: greeting and clarification sent, invented figures replaced, cards bound to the turn", async () => {
  const transport = createFakeTransport();
  const resolver = createInMemoryCardResolver();
  const host = createFakeHost({
    replies: (t) => {
      if (t === "hi") return "Hello! How can I help you find a home?";
      if (t === "3 or 4 beds?") return "Do you mean 3 or 4 bedrooms?";
      if (t === "anything in pasadena") return "There are 12 listings";
      if (t.startsWith("show")) return "[[card:c1]]";
      return "ok";
    },
  });
  const plugin = createChannelPlugin({ transport, cardResolver: resolver, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  assert.equal(transport.started, true);
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });

  await say("hi", "m1");
  await say("3 or 4 beds?", "m2");
  await say("anything in pasadena", "m3");
  resolver.store(SESSION, "m4", "c1", "123 Oak Ave | 3 bd | 960 sqft\n");
  await say("show me", "m4");
  await say("show me again", "m5"); // same token, next turn: resolver has nothing for m5

  assert.deepEqual(transport.sent.map((s) => s.text), [
    "Hello! How can I help you find a home?",
    "Do you mean 3 or 4 bedrooms?",
    SAFE_TEXT,
    "123 Oak Ave | 3 bd | 960 sqft\n",
    SAFE_TEXT,
  ]);
  assert.ok(!transport.sent.some((s) => s.text === "There are 12 listings"));
  for (const s of transport.sent) assert.equal(s.to, PEER);
  assert.equal(host.results[0].visibleReplySent, true);
  assert.equal(typeof host.results[0].messageId, "string");
});

test("a second plugin instance (fresh ingress, e.g. another process) has no record and sends nothing", async () => {
  const transportA = createFakeTransport();
  const hostA = createFakeHost({ replies: () => "Hello!" });
  const a = createChannelPlugin({ transport: transportA, resolveRoute: hostA.resolveRoute, runInbound: hostA.runInbound });
  await a.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transportA.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  const transportB = createFakeTransport();
  const b = createChannelPlugin({ transport: transportB });
  assert.deepEqual(await b.outbound.sendText({ to: PEER, text: "Hello!", accountId: "default" }), { outcome: "not_sent", reason: "no-inbound-record" });
  assert.equal(transportB.sent.length, 0);
  assert.deepEqual(transportA.sent.map((s) => s.text), ["Hello!"]);
});

test("inbound without a route resolver or runner is dropped, not replied to", async () => {
  const transport = createFakeTransport();
  const warns = [];
  const plugin = createChannelPlugin({ transport, log: { warn: (o) => warns.push(o) } });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  assert.equal(transport.sent.length, 0);
  assert.equal(warns.length, 1);
  assert.equal(warns[0].reason, "no-runner");
});
