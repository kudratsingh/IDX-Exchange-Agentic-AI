import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createChannelPlugin } from "./channel.mjs";
import { INGRESS_MAX_ENTRIES, INGRESS_TURNS_PER_PEER, SAFE_TEXT, VERIFIER_DEADLINE_MS } from "./constants.mjs";
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

/** A gate over a fake transport with one open turn for PEER (and its trusted handle). */
function gate(overrides = {}, inboundText = "hi") {
  let t = 1000;
  const now = () => t;
  const transport = createFakeTransport();
  const ingress = createIngress({ now });
  let handle = null;
  if (inboundText !== null) {
    handle = ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: inboundText, receivedAt: t });
  }
  const outbound = createOutbound({ transport, ingress, ...overrides });
  return { transport, ingress, outbound, handle, advance: (ms) => { t += ms; } };
}

/** An inbound record as the verifier sees it for an ordinary turn. */
const record = (text, extra = {}) => ({ sessionKey: SESSION, turnId: "t1", text, cardToolCalled: false, ...extra });

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

test("FC-verifier-malformed (getter/Proxy verdicts): fields are read once, so a verdict that changes between reads cannot pass the check with one value and send another", async () => {
  const input = "Hello there";
  // kind answers "withhold" on the first read and "release" afterwards (a withhold carries
  // no text, so the object is a plain withhold on its first and only read)
  let kindReads = 0;
  const flipKind = () => ({ get kind() { return kindReads++ === 0 ? "withhold" : "release"; }, reason: "x" });
  const a = gate({ verify: flipKind, withholdMode: "silent" });
  assert.deepEqual(await a.outbound.sendText({ to: PEER, text: input, accountId: "default" }), { outcome: "not_sent", reason: "x" });
  assert.equal(a.transport.sent.length, 0);
  assert.equal(kindReads, 1);
  // text answers the input on the first read and invented bytes afterwards
  let textReads = 0;
  const flipText = ({ text }) => ({ kind: "release", rule: "no-figures", get text() { textReads += 1; return textReads <= 1 ? text : "INVENTED 999 homes"; } });
  const b = gate({ verify: flipText });
  await b.outbound.sendText({ to: PEER, text: input, accountId: "default" });
  assert.deepEqual(b.transport.sent.map((s) => s.text), [input]);
  assert.equal(textReads, 1);
  // a Proxy that answers by read count
  let reads = 0;
  const proxied = ({ text }) => new Proxy({}, { get: (_, p) => (p === "kind" ? "release" : p === "rule" ? "no-figures" : p === "text" ? (++reads <= 1 ? text : "INVENTED 999 homes") : undefined) });
  const c = gate({ verify: proxied });
  await c.outbound.sendText({ to: PEER, text: input, accountId: "default" });
  assert.deepEqual(c.transport.sent.map((s) => s.text), [input]);
  // a card verdict whose text changes between reads: the first read is sealed
  let cardReads = 0;
  const flipCard = () => ({ kind: "release", rule: "card", viaCard: true, get text() { cardReads += 1; return cardReads <= 1 ? "123 Oak Ave | 960 sqft" : "123 Oak Ave | 2960 sqft"; } });
  const d = gate({ verify: flipCard }, "show me");
  await d.outbound.sendText({ to: PEER, text: "[[card:c1]]", accountId: "default" });
  assert.deepEqual(d.transport.sent.map((s) => s.text), ["123 Oak Ave | 960 sqft"]);
  assert.equal(cardReads, 1);
  // an array or a frozen-unfriendly shape is still malformed
  const e = gate({ verify: () => ["release"], withholdMode: "silent" });
  assert.deepEqual(await e.outbound.sendText({ to: PEER, text: input, accountId: "default" }), { outcome: "not_sent", reason: "verifier-malformed" });
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
  const allowed = new Set([SAFE_TEXT, ...inputs.map((t) => verifyReply({ text: t, inbound: record("3 or 4"), resolver: { resolve: () => null } })).filter((v) => v.kind === "release").map((v) => v.text)]);
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

test("ingress: round trip, newer becomes current and older stays addressable by its handle, expiry, eviction, normalization", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100, maxEntries: 3, turnsPerPeer: 2 });
  const k = ing.key("default", PEER);
  assert.equal(ing.current(k), null);
  assert.equal(ing.forTurn(k, "t1"), null);
  const h1 = ing.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.deepEqual(h1, { turnId: "t1", key: k });
  assert.ok(Object.isFrozen(h1));
  assert.equal(ing.current(k).turnId, "t1");
  assert.equal(ing.current(k).cardToolCalled, false);
  t = 10;
  const h2 = ing.record(k, { sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 1 });
  assert.equal(ing.current(k).turnId, "t2");
  assert.equal(ing.forTurn(k, h1).text, "hi");
  assert.equal(ing.forTurn(k, h2).text, "again");
  // a turn id string, a look-alike object or another peer's key is not a handle
  assert.equal(ing.forTurn(k, "t1"), null);
  assert.equal(ing.forTurn(k, "t9"), null);
  assert.equal(ing.forTurn(k, Object.freeze({ turnId: "t1", key: k })), null);
  assert.equal(ing.forTurn(k, { ...h1 }), null);
  assert.equal(ing.forTurn(ing.key("default", "+15550000002"), h1), null);
  assert.equal(ing.forTurn(k, null), null);
  assert.equal(ing.forTurn(k, undefined), null);
  // capacity per peer: the oldest turn drops out
  t = 20;
  const h3 = ing.record(k, { sessionKey: SESSION, turnId: "t3", text: "third", receivedAt: 2 });
  assert.equal(ing.forTurn(k, h1), null);
  assert.equal(ing.forTurn(k, h2).text, "again");
  // the TTL applies to each turn on its own stored time
  t = 115;
  assert.equal(ing.forTurn(k, h2), null);
  assert.equal(ing.current(k).turnId, "t3");
  t = 121;
  assert.equal(ing.current(k), null);
  assert.equal(ing.forTurn(k, h3), null);
  assert.equal(INGRESS_TURNS_PER_PEER, 4);
  t = 0;
  for (const p of ["+15550000001", "+15550000002", "+15550000003", "+15550000004"]) {
    ing.record(ing.key("default", p), { sessionKey: "s", turnId: p, text: "", receivedAt: 0 });
  }
  assert.equal(ing.size(), 3);
  assert.equal(ing.current(ing.key("default", "+15550000001")), null);
  assert.equal(ing.current(ing.key("default", "+15550000004")).turnId, "+15550000004");
  for (const spelling of ["+15550000001", "15550000001", "+1 (555) 000-0001", "15550000001@s.whatsapp.net", "15550000001@c.us", "whatsapp:+15550000001", "  +1-555-000-0001 "]) {
    assert.equal(normalizePeerId(spelling), "+15550000001", spelling);
    assert.equal(ing.key("default", spelling), k);
  }
  // a linked id is its own namespace: it never folds onto the phone-number record
  for (const spelling of ["15550000001@lid", "WHATSAPP:15550000001@lid", "+1 (555) 000-0001@LID"]) {
    assert.equal(normalizePeerId(spelling), "15550000001@lid", spelling);
    assert.notEqual(ing.key("default", spelling), k);
  }
  assert.equal(normalizePeerId("Group-ABC@g.us"), "group-abc@g.us");
  // canonical ids are fixed points
  for (const id of ["+15550000001", "15550000001@lid", "group-abc@g.us", "abc@lid"]) assert.equal(normalizePeerId(id), id);
  assert.equal(ing.key("acct2", PEER) === k, false);
  assert.equal(INGRESS_MAX_ENTRIES, 512);
});

test("ingress: a handle minted by one instance is untrusted in another, and returned records are frozen copies", () => {
  const a = createIngress({ now: () => 0 });
  const b = createIngress({ now: () => 0 });
  const k = a.key("default", PEER);
  const h = a.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  b.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.equal(b.forTurn(k, h), null);
  assert.equal(a.forTurn(k, h).turnId, "t1");
  // a caller cannot flip the stored flag through a returned record
  const rec = a.forTurn(k, h);
  assert.ok(Object.isFrozen(rec));
  assert.throws(() => { "use strict"; rec.cardToolCalled = true; });
  assert.equal(a.forTurn(k, h).cardToolCalled, false);
  assert.equal(a.markCardTool(h, "search_listings"), true);
  const marked = a.current(k);
  assert.equal(marked.cardToolCalled, true);
  assert.throws(() => { "use strict"; marked.cardToolCalled = false; });
  assert.equal(a.current(k).cardToolCalled, true);
});

test("ingress: cardToolCalled is monotonic, per turn, and only a trusted handle with a card tool name marks it", () => {
  let t = 0;
  const ing = createIngress({ now: () => t });
  const k = ing.key("default", PEER);
  const h1 = ing.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.equal(ing.forTurn(k, h1).cardToolCalled, false);
  // non-card names, forged handles and strings mark nothing
  for (const name of ["get_listing_details", "health", "Search_Listings", "", undefined, null, 7]) {
    assert.equal(ing.markCardTool(h1, name), false, String(name));
  }
  assert.equal(ing.markCardTool(Object.freeze({ turnId: "t1", key: k }), "search_listings"), false);
  assert.equal(ing.markCardTool("t1", "search_listings"), false);
  assert.equal(ing.markCardTool(null, "search_listings"), false);
  assert.equal(ing.forTurn(k, h1).cardToolCalled, false);
  // the real handle with a card tool marks; marking again is idempotent
  assert.equal(ing.markCardTool(h1, "search_listings"), true);
  assert.equal(ing.markCardTool(h1, "recommend"), true);
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  // no API clears it: nothing on the ingress or the handle is named like a reset
  const names = (o) => {
    const out = new Set();
    for (let p = o; p && p !== Object.prototype; p = Object.getPrototypeOf(p)) {
      for (const n of Reflect.ownKeys(p)) out.add(String(n));
    }
    return [...out];
  };
  for (const n of [...names(ing), ...names(h1)]) assert.doesNotMatch(n, /clear|unmark|reset/i);
  // a later turn for the same peer starts false; the older turn stays true
  t = 10;
  const h2 = ing.record(k, { sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 1 });
  assert.equal(ing.current(k).cardToolCalled, false);
  assert.equal(ing.forTurn(k, h2).cardToolCalled, false);
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  // a handle whose turn has been evicted marks nothing
  const tiny = createIngress({ now: () => 0, turnsPerPeer: 1 });
  const old = tiny.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  tiny.record(k, { sessionKey: SESSION, turnId: "t2", text: "hi", receivedAt: 0 });
  assert.equal(tiny.markCardTool(old, "search_listings"), false);
  assert.equal(tiny.current(k).cardToolCalled, false);
});

test("ingress: a handle names the one entry it was minted for, so a second record with the same turn id neither replaces it nor inherits its mark", async () => {
  const ing = createIngress({ now: () => 1 });
  const k = ing.key("default", PEER);
  const h1 = ing.record(k, { sessionKey: SESSION, turnId: "same", text: "homes", receivedAt: 1 });
  assert.equal(ing.markCardTool(h1, "search_listings"), true);
  const h2 = ing.record(k, { sessionKey: SESSION, turnId: "same", text: "thanks", receivedAt: 2 });
  assert.notEqual(h1, h2);
  assert.deepEqual(h1, h2); // structurally identical, yet two different turns
  assert.equal(ing.forTurn(k, h1).text, "homes");
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  assert.equal(ing.forTurn(k, h2).text, "thanks");
  assert.equal(ing.forTurn(k, h2).cardToolCalled, false);
  assert.equal(ing.current(k).text, "thanks");
  // the gate sees the same: a prose reply bound by the marked handle stays on the card rule
  const transport = createFakeTransport();
  const outbound = createOutbound({ transport, ingress: ing });
  const prose = "Here are some great homes for you.";
  assert.deepEqual(await outbound.sendText({ to: PEER, text: prose, accountId: "default", turn: h1 }), { messageId: "fake-1", withheld: "card-turn-requires-tokens" });
  assert.equal(typeof (await outbound.sendText({ to: PEER, text: prose, accountId: "default", turn: h2 })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, prose]);
  // once the first entry is evicted its handle is gone for good, whatever the turn id
  const tiny = createIngress({ now: () => 1, turnsPerPeer: 1 });
  const old = tiny.record(k, { sessionKey: SESSION, turnId: "same", text: "a", receivedAt: 1 });
  tiny.record(k, { sessionKey: SESSION, turnId: "same", text: "b", receivedAt: 2 });
  assert.equal(tiny.forTurn(k, old), null);
  assert.equal(tiny.markCardTool(old, "search_listings"), false);
  assert.equal(tiny.current(k).text, "b");
});

test("ingress + gate: a linked-id destination does not bind to the phone-number peer's record", async () => {
  const { transport, outbound, ingress } = gate({}, "I want 3 bedrooms");
  const lid = "15550000001@lid";
  assert.notEqual(ingress.key("default", lid), ingress.key("default", PEER));
  for (const to of [lid, "whatsapp:15550000001@lid", "+1 (555) 000-0001@lid"]) {
    assert.deepEqual(await outbound.sendText({ to, text: "You asked for 3 bedrooms", accountId: "default" }), { outcome: "not_sent", reason: "no-inbound-record" }, to);
    assert.deepEqual(await outbound.sendText({ to, text: "You asked for 4 bedrooms", accountId: "default" }), { outcome: "not_sent", reason: "no-inbound-record" }, to);
  }
  assert.equal(transport.sent.length, 0);
  // a linked-id peer with its own turn is addressable as itself, and the transport is told the canonical id
  ingress.record(ingress.key("default", lid), { sessionKey: `agent:idx:whatsapp:direct:${lid}`, turnId: "l1", text: "hey", receivedAt: 1 });
  assert.equal(typeof (await outbound.sendText({ to: "WHATSAPP:15550000001@lid", text: "Hello!", accountId: "default" })).messageId, "string");
  assert.deepEqual(transport.sent, [{ accountId: "default", to: lid, text: "Hello!" }]);
});

test("ingress: markCardToolForSession marks every open turn of that session and no other, returns the count", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100 });
  const k1 = ing.key("default", PEER);
  const k2 = ing.key("default", "+15550000002");
  const other = "agent:idx:whatsapp:direct:+15550000002";
  const a = ing.record(k1, { sessionKey: SESSION, turnId: "a", text: "hi", receivedAt: 0 });
  const b = ing.record(k1, { sessionKey: SESSION, turnId: "b", text: "more", receivedAt: 1 });
  const c = ing.record(k2, { sessionKey: other, turnId: "c", text: "hello", receivedAt: 2 });
  assert.equal(ing.markCardToolForSession(SESSION, "get_listing_details"), 0);
  assert.equal(ing.markCardToolForSession(undefined, "search_listings"), 0);
  assert.equal(ing.markCardToolForSession({ sessionKey: SESSION }, "search_listings"), 0);
  assert.equal(ing.forTurn(k1, a).cardToolCalled, false);
  assert.equal(ing.markCardToolForSession(SESSION, "search_listings"), 2);
  assert.equal(ing.forTurn(k1, a).cardToolCalled, true);
  assert.equal(ing.forTurn(k1, b).cardToolCalled, true);
  assert.equal(ing.forTurn(k2, c).cardToolCalled, false);
  assert.equal(ing.markCardToolForSession("agent:idx:whatsapp:direct:nobody", "search_listings"), 0);
  // an expired turn is not counted
  t = 150;
  const d = ing.record(k2, { sessionKey: other, turnId: "d", text: "now", receivedAt: 3 });
  assert.equal(ing.markCardToolForSession(other, "recommend"), 1);
  assert.equal(ing.forTurn(k2, d).cardToolCalled, true);
});

test("audit log never carries text, peer or session key", async () => {
  const lines = [];
  const log = { info: (o) => lines.push(o), warn: (o) => lines.push(o), error: (o) => lines.push(o) };
  const { outbound, handle } = gate({ log }, "3 or 4");
  await outbound.sendText({ to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" });
  await outbound.sendText({ to: PEER, text: "There are 12 homes", accountId: "default" });
  await outbound.sendText({ to: "+15550000009", text: "Hello", accountId: "default" });
  await outbound.sendText({ to: PEER, text: "Anything else?", accountId: "default", turn: handle });
  await outbound.sendText({ to: PEER, text: "Anything else?", accountId: "default", turnId: "t1" });
  assert.equal(lines.length, 5);
  for (const line of lines) {
    assert.equal(typeof line.outcome, "string");
    assert.equal(typeof line.hasRecord, "boolean");
    assert.equal(typeof line.boundToTurn, "boolean");
    assert.equal(typeof line.textLength, "number");
  }
  assert.deepEqual(lines.map((l) => l.boundToTurn), [false, false, false, true, false]);
  assert.equal(lines[4].reason, "untrusted-turn");
  const blob = JSON.stringify(lines);
  for (const forbidden of ["bedrooms", "12 homes", "Hello", "5550000", SESSION, SAFE_TEXT, "t1", handle.key]) assert.ok(!blob.includes(forbidden), forbidden);
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
  assert.equal(/\p{N}/u.test(SAFE_TEXT), false);
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
    // The card is stored for the turn the host is answering (turn.turnId is the
    // channel-generated id; turn.messageId is the peer's id, metadata only).
    replies: (t, turn) => {
      if (t === "hi") return "Hello! How can I help you find a home?";
      if (t === "3 or 4 beds?") return "Do you mean 3 or 4 bedrooms?";
      if (t === "anything in pasadena") return "There are 12 listings";
      if (t === "show me") {
        resolver.store(turn.sessionKey, turn.turnId, "c1", "123 Oak Ave | 3 bd | 960 sqft\n");
        return "[[card:c1]]";
      }
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
  await say("show me", "m4");
  await say("show me again", "m5"); // same token, next turn: resolver has nothing for that turn

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
  assert.deepEqual(host.turns.map((x) => x.messageId), ["m1", "m2", "m3", "m4", "m5"]);
  assert.equal(host.turns[3].sessionKey, SESSION);
});

test("turn ids are channel-generated: a re-sent peer message id is a new turn and does not resolve the earlier turn's card", async () => {
  const transport = createFakeTransport();
  const resolver = createInMemoryCardResolver();
  const host = createFakeHost({
    replies: (t, turn) => {
      if (t === "show me" && turn.messageId === "m4" && !host.turns.some((x) => x !== turn && x.messageId === "m4")) {
        resolver.store(turn.sessionKey, turn.turnId, "c1", "123 Oak Ave | 3 bd | 960 sqft");
      }
      return t === "show me" ? "[[card:c1]]" : "ok";
    },
  });
  const plugin = createChannelPlugin({ transport, cardResolver: resolver, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  await say("show me", "m4");
  await say("something else", "m5");
  await say("show me", "m4"); // the peer re-sends an id it already used
  assert.deepEqual(transport.sent.map((s) => s.text), ["123 Oak Ave | 3 bd | 960 sqft", "ok", SAFE_TEXT]);
  const ids = host.turns.map((x) => x.turnId);
  assert.equal(new Set(ids).size, 3);
  for (const id of ids) {
    assert.match(id, /^[0-9a-f-]{36}$/);
    assert.ok(!["m4", "m5"].includes(id));
  }
  // an inbound without a message id still gets a turn
  await say("hi", undefined);
  assert.equal(host.turns[3].messageId, undefined);
  assert.match(host.turns[3].turnId, /^[0-9a-f-]{36}$/);
});

test("in-flight reply: a reply to turn N that lands after turn N+1 is verified against turn N; tool sends bind to the newest turn", async () => {
  const transport = createFakeTransport();
  const host = createFakeHost({ replies: () => "x" });
  const delivers = [];
  const plugin = createChannelPlugin({ transport, resolveRoute: host.resolveRoute, runInbound: async (turn) => { delivers.push(turn.deliver); } });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  await say("3 or 4 beds?", "m1");
  await say("hello?", "m2");
  // the model's clarification for m1 arrives now
  const r = await delivers[0]({ text: "Do you mean 3 or 4 bedrooms?" });
  assert.deepEqual(r, { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?"]);
  // a tool send has no turn and binds to the newest turn ("hello?"), where 3 and 4 are unverified
  await plugin.outbound.sendText({ to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?", SAFE_TEXT]);
  // a figure the user wrote in m2 but not in m1 is unverified for the m1 reply
  const r2 = await delivers[0]({ text: "Hello back, 5 options?" });
  assert.equal(r2.visibleReplySent, true); // SAFE_TEXT, not the raw text
  assert.equal(transport.sent.at(-1).text, SAFE_TEXT);
  // after INGRESS_TURNS_PER_PEER newer turns the m1 record is gone: its handle is no longer
  // trusted, so the reply is withheld untrusted-turn and nothing is sent (not even SAFE_TEXT)
  for (let i = 0; i < INGRESS_TURNS_PER_PEER; i += 1) await say(`more ${i}`, `m${i + 3}`);
  const before = transport.sent.length;
  assert.deepEqual(await delivers[0]({ text: "Do you mean 3 or 4 bedrooms?" }), { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } });
  assert.equal(transport.sent.length, before);
  // a turn id passed by hand, known or not, is untrusted
  assert.deepEqual(await plugin.outbound.sendText({ to: PEER, text: "Hello", accountId: "default", turnId: "not-a-turn" }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, before);
});

// ---- Rule 1: sends bind to their trusted originating turn ------------------------

test("R1-binding (b): a forged handle structurally equal to the real one is untrusted; nothing is sent", async () => {
  const { transport, outbound, handle, ingress } = gate({}, "hi");
  const forged = Object.freeze({ turnId: handle.turnId, key: handle.key });
  assert.deepEqual(forged, handle);
  assert.notEqual(forged, handle);
  for (const fake of [forged, { ...handle }, { turnId: "t1", key: ingress.key("default", PEER) }, "t1", handle.turnId, null, 0, true]) {
    assert.deepEqual(await outbound.sendText({ to: PEER, text: "Hello!", accountId: "default", turn: fake }), { outcome: "not_sent", reason: "untrusted-turn" }, String(fake));
  }
  assert.equal(transport.sent.length, 0);
  // the real handle releases against its own turn
  assert.equal(typeof (await outbound.sendText({ to: PEER, text: "Hello!", accountId: "default", turn: handle })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.text), ["Hello!"]);
});

test("R1-binding (c): the real handle for one peer used with another peer's address is untrusted; nothing is sent", async () => {
  const { transport, outbound, handle, ingress } = gate({}, "hi");
  const other = "+15550000002";
  ingress.record(ingress.key("default", other), { sessionKey: `agent:idx:whatsapp:direct:${other}`, turnId: "t9", text: "hey", receivedAt: 1 });
  assert.deepEqual(await outbound.sendText({ to: other, text: "Hello!", accountId: "default", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  // another account id changes the key as well
  assert.deepEqual(await outbound.sendText({ to: PEER, text: "Hello!", accountId: "acct2", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, 0);
  // the other peer still has an open turn, so an unbound send to them works
  assert.equal(typeof (await outbound.sendText({ to: other, text: "Hello!", accountId: "default" })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.to), [other]);
});

test("R1-binding (a, f): a bare turnId from any caller is untrusted even when it names the turn whose figures match; a send with neither binds to current", async () => {
  const { transport, outbound, handle, ingress } = gate({}, "3 or 4 beds?");
  // the peer has since written again
  ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t2", text: "hello?", receivedAt: 2 });
  const clarification = "Do you mean 3 or 4 bedrooms?";
  for (const turnId of [handle.turnId, "t2", "", "not-a-turn", null, 7]) {
    assert.deepEqual(await outbound.sendText({ to: PEER, text: clarification, accountId: "default", turnId }), { outcome: "not_sent", reason: "untrusted-turn" }, String(turnId));
  }
  // a handle and a turnId together are still untrusted
  assert.deepEqual(await outbound.sendText({ to: PEER, text: clarification, accountId: "default", turn: handle, turnId: handle.turnId }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, 0);
  // (f) neither: binds to the newest turn ("hello?"), where 3 and 4 are unverified -> SAFE_TEXT
  await outbound.sendText({ to: PEER, text: clarification, accountId: "default" });
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  await outbound.sendText({ to: PEER, text: "Which city?", accountId: "default" });
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, "Which city?"]);
  // (d) the real handle still releases against its own turn
  assert.equal(typeof (await outbound.sendText({ to: PEER, text: clarification, accountId: "default", turn: handle })).messageId, "string");
  assert.equal(transport.sent.at(-1).text, clarification);
});

// ---- Rule 2: card turns require verified card tokens --------------------------------

/** A plugin on the fake transport whose host runner is scripted per inbound text. */
async function cardPlugin({ script, resolver = createInMemoryCardResolver(), withholdMode } = {}) {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const results = [];
  const turns = [];
  const host = createFakeHost({ replies: () => "unused" });
  const plugin = createChannelPlugin({
    transport,
    ingress,
    cardResolver: resolver,
    ...(withholdMode ? { withholdMode } : {}),
    resolveRoute: host.resolveRoute,
    runInbound: async (turn) => {
      turns.push(turn);
      await script(turn, { results, resolver });
    },
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  return { transport, ingress, plugin, results, turns, say, resolver };
}

test("R2-card-turn (a, b): after noteToolCall(search_listings) prose becomes SAFE_TEXT with the card-turn reason; a resolving token sends the card bytes exactly", async () => {
  const card = "123 Oak Ave | 3 bd | 960 sqft\n";
  const { transport, results, say } = await cardPlugin({
    script: async (turn, { results: out, resolver }) => {
      assert.equal(turn.noteToolCall("search_listings"), true);
      out.push(await turn.deliver({ text: "Here are some great homes for you." }));
      resolver.store(turn.sessionKey, turn.turnId, "a1", card);
      out.push(await turn.deliver({ text: "[[card:a1]]" }));
      // prose is still withheld after the card went out: the flag does not clear
      out.push(await turn.deliver({ text: "Let me know what you think!" }));
    },
  });
  await say("anything in pasadena", "m1");
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, card, SAFE_TEXT]);
  assert.ok(!transport.sent.some((s) => s.text.includes("great homes")));
  assert.equal(results[0].visibleReplySent, true); // SAFE_TEXT went out, so the dispatcher must not retry a fallback
  assert.deepEqual(results[0].withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
  assert.deepEqual(results[1], { messageId: "fake-2", visibleReplySent: true });
  assert.deepEqual(results[2].withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
});

test("R2-card-turn (a, silent mode): the deliver result is not visible with suppression reason card-turn-requires-tokens and nothing is sent", async () => {
  const { transport, results, say } = await cardPlugin({
    withholdMode: "silent",
    script: async (turn, { results: out }) => {
      turn.noteToolCall("search_listings");
      out.push(await turn.deliver({ text: "Here are some great homes for you." }));
    },
  });
  await say("anything in pasadena", "m1");
  assert.deepEqual(results, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:card-turn-requires-tokens" } }]);
  assert.equal(transport.sent.length, 0);
});

test("R2-card-turn (c, d, e): ordinary turns keep greetings and clarifications; a non-card tool name leaves the flag false", async () => {
  const { transport, ingress, turns, say } = await cardPlugin({
    script: async (turn) => {
      if (turn.text === "hi") await turn.deliver({ text: "Hi! How can I help you today?" });
      if (turn.text === "3 or 4 bedrooms?") await turn.deliver({ text: "Do you mean 3 or 4 bedrooms?" });
      if (turn.text === "details please") {
        assert.equal(turn.noteToolCall("get_listing_details"), false);
        assert.equal(turn.noteToolCall("health"), false);
        assert.equal(turn.noteToolCall("Search_Listings"), false);
        assert.equal(turn.noteToolCall(undefined), false);
        await turn.deliver({ text: "Sure, which one?" });
      }
    },
  });
  await say("hi", "m1");
  await say("3 or 4 bedrooms?", "m2");
  await say("details please", "m3");
  assert.deepEqual(transport.sent.map((s) => s.text), ["Hi! How can I help you today?", "Do you mean 3 or 4 bedrooms?", "Sure, which one?"]);
  assert.equal(ingress.current(ingress.key("default", PEER)).cardToolCalled, false);
  assert.equal(turns.length, 3);
});

test("R2-card-turn (e, host runner): the turn object carries the id as a string and nothing the ingress accepts as a handle", async () => {
  const { ingress, turns, say } = await cardPlugin({ script: async () => {} });
  await say("hi", "m1");
  const turn = turns[0];
  const key = ingress.key("default", PEER);
  assert.equal(typeof turn.turnId, "string");
  assert.equal(typeof turn.deliver, "function");
  assert.equal(ingress.current(key).turnId, turn.turnId);
  // Rule 1 first: nothing the runner receives is a handle
  for (const [name, value] of Object.entries(turn)) assert.equal(ingress.forTurn(key, value), null, name);
  assert.equal(ingress.forTurn(key, turn.turnId), null);
  assert.equal(ingress.forTurn(key, { turnId: turn.turnId, key }), null);
  // then Rule 2: the seam exists and nothing the runner receives marks the turn directly
  assert.equal(typeof turn.noteToolCall, "function");
  for (const [name, value] of Object.entries(turn)) assert.equal(ingress.markCardTool(value, "search_listings"), false, name);
  // noteToolCall marks the turn through the closure without exposing the handle
  assert.equal(turn.noteToolCall("recommend"), true);
  assert.equal(ingress.current(key).cardToolCalled, true);
});

test("R2-card-turn (f): the mark is monotonic across turns of the same peer", async () => {
  const { ingress, turns, say } = await cardPlugin({ script: async (turn) => { if (turn.text === "search") turn.noteToolCall("search_listings"); } });
  const key = ingress.key("default", PEER);
  await say("search", "m1");
  assert.equal(ingress.current(key).cardToolCalled, true);
  assert.equal(turns[0].noteToolCall("get_listing_details"), false); // no way back
  assert.equal(ingress.current(key).cardToolCalled, true);
  await say("thanks", "m2");
  assert.equal(ingress.current(key).cardToolCalled, false);
  assert.equal(ingress.current(key).turnId, turns[1].turnId);
  // the older turn (reached through the ingress by session marking) stays marked
  assert.equal(ingress.markCardToolForSession(turns[0].sessionKey, "recommend"), 2);
  assert.equal(ingress.current(key).cardToolCalled, true);
});

// ---- Rule 3: incomplete release verdicts are malformed at the gate ---------------------

test("R3-verdict-completeness (gate): an incomplete or inconsistent verdict from an injected verifier is verifier-malformed; raw text never leaves", async () => {
  const digitFree = "Hello there";
  const echo = "Do you mean 3 or 4 bedrooms?";
  const figure = "There are 12 homes";
  const cases = [
    ["release with no rule", digitFree, { kind: "release", text: digitFree }],
    ["rule card without viaCard", "[[card:a]]", { kind: "release", rule: "card", text: "card body" }],
    ["viaCard true with rule no-figures", digitFree, { kind: "release", rule: "no-figures", viaCard: true, text: digitFree }],
    ["viaCard false", digitFree, { kind: "release", rule: "no-figures", viaCard: false, text: digitFree }],
    ["rule no-figures on a text with a figure", figure, { kind: "release", rule: "no-figures", text: figure }],
    ["rule user-figures whose figure is not in the inbound text", figure, { kind: "release", rule: "user-figures", text: figure }],
    ["rule user-figures on a text with no figures", digitFree, { kind: "release", rule: "user-figures", text: digitFree }],
    ["unknown rule trusted", digitFree, { kind: "release", rule: "trusted", text: digitFree }],
    ["release carrying reason", digitFree, { kind: "release", rule: "no-figures", text: digitFree, reason: "fine" }],
    ["release of rule no-figures on a card turn", digitFree, { kind: "release", rule: "no-figures", text: digitFree }, true],
    ["release of rule user-figures on a card turn", echo, { kind: "release", rule: "user-figures", text: echo }, true],
    ["withhold carrying text", digitFree, { kind: "withhold", reason: "x", text: digitFree }],
    ["withhold with empty reason", digitFree, { kind: "withhold", reason: "" }],
  ];
  for (const [label, input, verdict, cardTurn = false] of cases) {
    for (const withholdMode of ["silent", "safe-text"]) {
      const transport = createFakeTransport();
      const ingress = createIngress({ now: () => 1 });
      const handle = ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: "3 or 4", receivedAt: 1 });
      if (cardTurn) assert.equal(ingress.markCardTool(handle, "search_listings"), true);
      const plugin = createChannelPlugin({ transport, ingress, withholdMode, verify: () => verdict });
      const r = await plugin.outbound.sendText({ to: PEER, text: input, accountId: "default" });
      if (withholdMode === "silent") {
        assert.deepEqual(r, { outcome: "not_sent", reason: "verifier-malformed" }, label);
        assert.equal(transport.sent.length, 0, label);
      } else {
        assert.deepEqual(r, { messageId: "fake-1", withheld: "verifier-malformed" }, label);
        assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT], label);
      }
    }
  }
  // positive controls: complete verdicts for each rule pass through the same gate
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: "3 or 4", receivedAt: 1 });
  const ok = createChannelPlugin({ transport, ingress, verify: ({ text }) => (text === "[[card:a]]" ? { kind: "release", rule: "card", viaCard: true, text: "card body" } : text === echo ? { kind: "release", rule: "user-figures", text } : { kind: "release", rule: "no-figures", text }) });
  for (const input of [digitFree, echo, "[[card:a]]"]) assert.equal(typeof (await ok.outbound.sendText({ to: PEER, text: input, accountId: "default" })).messageId, "string", input);
  assert.deepEqual(transport.sent.map((s) => s.text), [digitFree, echo, "card body"]);
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
