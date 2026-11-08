import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Namespace import so a runtime that lacks `createBeforeToolCallHandler` fails one
// assertion in its own test instead of failing this whole file at import time.
import * as channelModule from "./channel.mjs";
import { createChannelPlugin } from "./channel.mjs";
// Namespace import for the constants added by revision 6 (BUSY_TEXT, CARD_TOOL_BLOCK_REASON),
// so the file still loads against an older runtime and those tests fail on assertions.
import * as constants from "./constants.mjs";
import { INGRESS_MAX_ENTRIES, INGRESS_TURNS_PER_PEER, SAFE_TEXT, VERIFIER_DEADLINE_MS } from "./constants.mjs";
import entry from "./index.mjs";
import { createIngress, normalizePeerId } from "./ingress.mjs";
import { createOutbound } from "./outbound.mjs";
import { SELF_TEST_VECTORS, selfCheck, verifierSelfTest } from "./self-check.mjs";
import { createInMemoryCardResolver } from "./test-support/fake-card-resolver.mjs";
import { createFakeTransport } from "./test-support/fake-transport.mjs";
import { createFakeApi, createFakeHost, recordBoundTurn } from "./test-support/host-emulation.mjs";
import { NO_TRANSPORT_MESSAGE } from "./transport.mjs";
import { verifyReply } from "./verifier.mjs";

const PEER = "+15550000001";
const SESSION = `agent:idx:whatsapp:direct:${PEER}`;
const DENY_CFG = { plugins: { deny: ["whatsapp"] } };

/** Admits one card tool call for a run, as the hook handler would, and asserts it landed. */
function admitCard(ingress, runId, sessionKey = SESSION, toolName = "search_listings") {
  assert.deepEqual(ingress.admitCardCall({ runId, sessionKey, toolName }), { admitted: true });
}

/** A gate over a fake transport with one open, run-bound turn for PEER (and its trusted handle). */
function gate(overrides = {}, inboundText = "hi") {
  let t = 1000;
  const now = () => t;
  const transport = createFakeTransport();
  const ingress = createIngress({ now });
  let handle = null;
  let runId = null;
  if (inboundText !== null) {
    ({ handle, runId } = recordBoundTurn(ingress, { peerId: PEER, sessionKey: SESSION, turnId: "t1", text: inboundText, receivedAt: t }));
  }
  const outbound = createOutbound({ transport, ingress, ...overrides });
  return { transport, ingress, outbound, handle, runId, markCard: () => admitCard(ingress, runId), advance: (ms) => { t += ms; } };
}

/** The host's run-start call for a turn the test's own runner receives (owner decision 19). */
const confirm = (turn) => turn.replyOptions.onAgentRunStart(turn.replyOptions.runId);

/** An inbound record as the verifier sees it for an ordinary bound turn. */
const record = (text, extra = {}) => ({ sessionKey: SESSION, turnId: "t1", text, cardToolCalled: false, runBound: true, cardCallRefused: false, ...extra });

/** Every own and inherited property name of an object, for "no API named like a reset" checks. */
const memberNames = (o) => {
  const out = new Set();
  for (let p = o; p && p !== Object.prototype; p = Object.getPrototypeOf(p)) {
    for (const n of Reflect.ownKeys(p)) out.add(String(n));
  }
  return [...out];
};

const RAW = "We have 12 homes for you";

// ---- fail-closed: verifier throws / deadline / malformed ------------------

test("FC-verifier-throws: raw text never sent; SAFE_TEXT in safe-text mode", async () => {
  const { transport, outbound, handle } = gate({ verify: () => { throw new Error("boom"); } });
  const r = await outbound.sendText({ to: PEER, text: RAW, accountId: "default", turn: handle });
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  assert.equal(typeof r.messageId, "string");
});

test("FC-verifier-throws: silent mode sends nothing and returns not_sent", async () => {
  const { transport, outbound, handle } = gate({ verify: () => { throw new Error("boom"); }, withholdMode: "silent" });
  const r = await outbound.sendText({ to: PEER, text: RAW, accountId: "default", turn: handle });
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
  await a.outbound.sendText({ to: PEER, text, accountId: "default", turn: a.handle });
  assert.deepEqual(a.transport.sent.map((s) => s.text), [SAFE_TEXT]);

  const b = gate({ verify: slow, clock, withholdMode: "silent" });
  assert.deepEqual(await b.outbound.sendText({ to: PEER, text, accountId: "default", turn: b.handle }), { outcome: "not_sent", reason: "verifier-deadline" });
  assert.equal(b.transport.sent.length, 0);

  const d = gate({ verify: fast, clock });
  await d.outbound.sendText({ to: PEER, text, accountId: "default", turn: d.handle });
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
    const { transport, outbound, handle } = gate({ verify: () => v, withholdMode: "silent" });
    const r = await outbound.sendText({ to: PEER, text, accountId: "default", turn: handle });
    assert.deepEqual(r, { outcome: "not_sent", reason: "verifier-malformed" }, String(v));
    assert.equal(transport.sent.length, 0);
    const s = gate({ verify: () => v });
    await s.outbound.sendText({ to: PEER, text, accountId: "default", turn: s.handle });
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
  assert.deepEqual(await a.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: a.handle }), { outcome: "not_sent", reason: "x" });
  assert.equal(a.transport.sent.length, 0);
  assert.equal(kindReads, 1);
  // text answers the input on the first read and invented bytes afterwards
  let textReads = 0;
  const flipText = ({ text }) => ({ kind: "release", rule: "no-figures", get text() { textReads += 1; return textReads <= 1 ? text : "INVENTED 999 homes"; } });
  const b = gate({ verify: flipText });
  await b.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: b.handle });
  assert.deepEqual(b.transport.sent.map((s) => s.text), [input]);
  assert.equal(textReads, 1);
  // a Proxy that answers by read count
  let reads = 0;
  const proxied = ({ text }) => new Proxy({}, { get: (_, p) => (p === "kind" ? "release" : p === "rule" ? "no-figures" : p === "text" ? (++reads <= 1 ? text : "INVENTED 999 homes") : undefined) });
  const c = gate({ verify: proxied });
  await c.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: c.handle });
  assert.deepEqual(c.transport.sent.map((s) => s.text), [input]);
  // a card verdict whose text changes between reads: the first read is sealed
  let cardReads = 0;
  const flipCard = () => ({ kind: "release", rule: "card", viaCard: true, get text() { cardReads += 1; return cardReads <= 1 ? "123 Oak Ave | 960 sqft" : "123 Oak Ave | 2960 sqft"; } });
  const d = gate({ verify: flipCard }, "show me");
  d.markCard();
  await d.outbound.sendText({ to: PEER, text: "[[card:c1]]", accountId: "default", turn: d.handle });
  assert.deepEqual(d.transport.sent.map((s) => s.text), ["123 Oak Ave | 960 sqft"]);
  assert.equal(cardReads, 1);
  // an array or a frozen-unfriendly shape is still malformed
  const e = gate({ verify: () => ["release"], withholdMode: "silent" });
  assert.deepEqual(await e.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: e.handle }), { outcome: "not_sent", reason: "verifier-malformed" });
});

test("FC-single-call-site (behavioural): over many inputs the transport only ever sees the verdict text or SAFE_TEXT", async () => {
  const inputs = [
    "Hello!", "Hi there, how can I help?", "There are 12 homes", "Do you mean 3 or 4 bedrooms?", "34 bedrooms?",
    "", "   ", "Priced at 850000", "[[card:a]]", "[[card:a", "Built 1998", "Twelve homes", "٣ homes", "a".repeat(4001),
    "Can you share your budget?", "Under 800000?", "Pasadena it is.", "1. one 2. two", "24/7", "ok", "Sure thing",
    "What area?", "Condo or house?", "3 or 4 it is", "Both 3 and 4 work", "4 then", "5 then", "Great, 3 bedrooms",
    "Which city?", "Anything else?",
  ];
  const { transport, outbound, handle } = gate({}, "3 or 4");
  for (const text of inputs) {
    try {
      await outbound.sendText({ to: PEER, text, accountId: "default", turn: handle });
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

test("no inbound record and no handle: withheld no-turn-handle silently even in safe-text mode; an expired handle is untrusted and silent too", async () => {
  const { transport, outbound } = gate({}, null);
  assert.deepEqual(await outbound.sendText({ to: PEER, text: "Hello", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  assert.equal(transport.sent.length, 0);
  // the record the handle names has expired: nothing to speak to, nothing sent
  const late = gate({}, "hi");
  late.advance(1_800_001);
  assert.deepEqual(await late.outbound.sendText({ to: PEER, text: "Hello", accountId: "default", turn: late.handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(late.transport.sent.length, 0);
});

test("transport returning no messageId after a send makes sendText reject, never not_sent", async () => {
  const { transport, outbound, handle } = gate();
  transport.emptyReceiptNextSend();
  await assert.rejects(outbound.sendText({ to: PEER, text: "Hello", accountId: "default", turn: handle }), /no messageId/);
  assert.equal(transport.sent.length, 1);
});

test("a transport error propagates and is not retried", async () => {
  const { transport, outbound, handle } = gate();
  let calls = 0;
  const orig = transport.sendText;
  transport.sendText = async (req) => { calls += 1; return orig(req); };
  transport.failNextSend(new Error("network down"));
  await assert.rejects(outbound.sendText({ to: PEER, text: "Hello", accountId: "default", turn: handle }), /network down/);
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

test("ingress: round trip, every turn addressable only by its handle (no lookup by key), expiry, eviction, normalization", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100, maxEntries: 3, turnsPerPeer: 2 });
  const k = ing.key("default", PEER);
  // no read by key alone: a caller without a handle has nothing to send against
  assert.equal("current" in ing, false);
  assert.equal(ing.forTurn(k, "t1"), null);
  const h1 = ing.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.deepEqual(h1, { turnId: "t1", key: k });
  assert.ok(Object.isFrozen(h1));
  assert.equal(ing.forTurn(k, h1).turnId, "t1");
  assert.equal(ing.forTurn(k, h1).cardToolCalled, false);
  assert.equal(ing.forTurn(k, h1).runBound, false); // recorded without a run: never bound
  t = 10;
  const h2 = ing.record(k, { sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 1 });
  assert.equal(ing.forTurn(k, h2).turnId, "t2");
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
  assert.equal(ing.forTurn(k, h3).turnId, "t3");
  t = 121;
  assert.equal(ing.forTurn(k, h3), null);
  assert.equal(INGRESS_TURNS_PER_PEER, 4);
  t = 0;
  const peers = ["+15550000001", "+15550000002", "+15550000003", "+15550000004"];
  const hs = peers.map((p) => ing.record(ing.key("default", p), { sessionKey: "s", turnId: p, text: "", receivedAt: 0 }));
  assert.equal(ing.size(), 3);
  assert.equal(ing.forTurn(ing.key("default", peers[0]), hs[0]), null);
  assert.equal(ing.forTurn(ing.key("default", peers[3]), hs[3]).turnId, "+15550000004");
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
  const { handle: h, runId } = recordBoundTurn(a, { peerId: PEER, sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  b.record(k, { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.equal(b.forTurn(k, h), null);
  assert.equal(b.confirmRun(h, runId), false);
  assert.equal(a.forTurn(k, h).turnId, "t1");
  // a caller cannot flip the stored flags through a returned record
  const rec = a.forTurn(k, h);
  assert.ok(Object.isFrozen(rec));
  assert.throws(() => { "use strict"; rec.cardToolCalled = true; });
  assert.throws(() => { "use strict"; rec.runBound = false; });
  assert.equal(a.forTurn(k, h).cardToolCalled, false);
  admitCard(a, runId);
  const marked = a.forTurn(k, h);
  assert.equal(marked.cardToolCalled, true);
  assert.throws(() => { "use strict"; marked.cardToolCalled = false; });
  assert.equal(a.forTurn(k, h).cardToolCalled, true);
  // the run id is never part of a record snapshot
  assert.deepEqual(Object.keys(marked).sort(), ["cardCallRefused", "cardToolCalled", "receivedAt", "runBound", "sessionKey", "text", "turnId"]);
  assert.equal(marked.cardCallRefused, false);
  assert.ok(!JSON.stringify(marked).includes(runId));
});

test("ingress: cardToolCalled is monotonic, per turn, and only an admitted card call on the turn's own confirmed run marks it", () => {
  let t = 0;
  const ing = createIngress({ now: () => t });
  const k = ing.key("default", PEER);
  const { handle: h1, runId: r1 } = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  assert.equal(ing.forTurn(k, h1).cardToolCalled, false);
  // non-card names admit nothing (a spelling that still names a card tool is one: see isCardTool)
  for (const name of ["get_listing_details", "health", "search_listing", "search_listings_v2", "idx__search_listings_v2", "", undefined, null, 7]) {
    assert.equal(ing.admitCardCall({ runId: r1, sessionKey: SESSION, toolName: name }).admitted, false, String(name));
  }
  // a handle, a turn id or a forged object is not a run id
  for (const runId of [h1, "t1", h1.turnId, { runId: r1 }, null, undefined, ""]) {
    assert.deepEqual(ing.admitCardCall({ runId, sessionKey: SESSION, toolName: "search_listings" }), { admitted: false, reason: "unknown-run" }, String(runId));
  }
  assert.equal(ing.forTurn(k, h1).cardToolCalled, false);
  // the turn's own run admits; admitting again is idempotent
  admitCard(ing, r1);
  admitCard(ing, r1, SESSION, "recommend");
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  // no API clears it: nothing on the ingress or the handle is named like a reset
  for (const n of [...memberNames(ing), ...memberNames(h1)]) assert.doesNotMatch(n, /clear|unmark|unbind|unconfirm|reset/i);
  // a later turn for the same peer starts false; the older turn stays true
  t = 10;
  const { handle: h2 } = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 1 });
  assert.equal(ing.forTurn(k, h2).cardToolCalled, false);
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  // the ingress keeps no session-keyed or taint API
  for (const gone of ["markCardTool", "markCardToolForSession", "blockTurn", "blockOpenTurns"]) assert.equal(gone in ing, false, gone);
});

test("ingress: a handle names the one entry it was minted for, so a second record with the same turn id neither replaces it nor inherits its mark", async () => {
  const ing = createIngress({ now: () => 1 });
  const k = ing.key("default", PEER);
  const first = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "same", text: "homes", receivedAt: 1 });
  const h1 = first.handle;
  admitCard(ing, first.runId);
  const { handle: h2 } = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "same", text: "thanks", receivedAt: 2 });
  assert.notEqual(h1, h2);
  assert.deepEqual(h1, h2); // structurally identical, yet two different turns
  assert.equal(ing.forTurn(k, h1).text, "homes");
  assert.equal(ing.forTurn(k, h1).cardToolCalled, true);
  assert.equal(ing.forTurn(k, h2).text, "thanks");
  assert.equal(ing.forTurn(k, h2).cardToolCalled, false);
  // the gate sees the same: a prose reply bound by the marked handle stays on the card rule
  const transport = createFakeTransport();
  const outbound = createOutbound({ transport, ingress: ing });
  const prose = "Here are some great homes for you.";
  assert.deepEqual(await outbound.sendText({ to: PEER, text: prose, accountId: "default", turn: h1 }), { messageId: "fake-1", withheld: "card-turn-requires-tokens" });
  assert.equal(typeof (await outbound.sendText({ to: PEER, text: prose, accountId: "default", turn: h2 })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, prose]);
  // once the first entry is evicted its handle is gone for good, whatever the turn id
  const tiny = createIngress({ now: () => 1, turnsPerPeer: 1 });
  const old = recordBoundTurn(tiny, { peerId: PEER, sessionKey: SESSION, turnId: "same", text: "a", receivedAt: 1 });
  const kept = recordBoundTurn(tiny, { peerId: PEER, sessionKey: SESSION, turnId: "same", text: "b", receivedAt: 2 });
  assert.equal(tiny.forTurn(k, old.handle), null);
  assert.deepEqual(tiny.admitCardCall({ runId: old.runId, sessionKey: SESSION, toolName: "search_listings" }), { admitted: false, reason: "turn-expired" });
  assert.equal(tiny.forTurn(k, kept.handle).text, "b");
  assert.equal(tiny.forTurn(k, kept.handle).cardToolCalled, false);
});

test("ingress + gate: a linked-id destination does not bind to the phone-number peer's record", async () => {
  const { transport, outbound, ingress, handle } = gate({}, "I want 3 bedrooms");
  const lid = "15550000001@lid";
  assert.notEqual(ingress.key("default", lid), ingress.key("default", PEER));
  for (const to of [lid, "whatsapp:15550000001@lid", "+1 (555) 000-0001@lid"]) {
    // the phone-number peer's handle is minted for another key: untrusted under the linked id
    assert.deepEqual(await outbound.sendText({ to, text: "You asked for 3 bedrooms", accountId: "default", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" }, to);
    assert.deepEqual(await outbound.sendText({ to, text: "You asked for 4 bedrooms", accountId: "default", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" }, to);
    assert.deepEqual(await outbound.sendText({ to, text: "You asked for 3 bedrooms", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" }, to);
  }
  assert.equal(transport.sent.length, 0);
  // a linked-id peer with its own turn is addressable as itself, and the transport is told the canonical id
  const { handle: lh } = recordBoundTurn(ingress, { peerId: lid, sessionKey: `agent:idx:whatsapp:direct:${lid}`, turnId: "l1", text: "hey", receivedAt: 1 });
  assert.equal(typeof (await outbound.sendText({ to: "WHATSAPP:15550000001@lid", text: "Hello!", accountId: "default", turn: lh })).messageId, "string");
  assert.deepEqual(transport.sent, [{ accountId: "default", to: lid, text: "Hello!" }]);
});

test("gate: a handle-bearing send spelled with a whatsapp: prefix or a phone-number JID suffix is delivered to the canonical peer, never the caller's spelling", async () => {
  const { transport, outbound, handle } = gate({}, "3 or 4");
  const spellings = ["whatsapp:+15550000001", "15550000001@s.whatsapp.net", "15550000001@c.us", "WhatsApp:15550000001@S.WHATSAPP.NET", "+1 (555) 000-0001", " 15550000001 "];
  for (const to of spellings) {
    for (const text of ["Anything else?", "Do you mean 3 or 4 bedrooms?", "There are 12 homes"]) {
      const r = await outbound.sendText({ to, text, accountId: "default", turn: handle });
      assert.equal(typeof r.messageId, "string", `${to} ${text}`);
      assert.equal(transport.sent.at(-1).to, PEER, `${to} ${text}`);
    }
  }
  assert.equal(transport.sent.length, spellings.length * 3);
  assert.ok(transport.sent.every((s) => s.to === PEER));
  assert.ok(!transport.sent.some((s) => s.text === "There are 12 homes"));
  assert.deepEqual(transport.sent.slice(0, 3).map((s) => s.text), ["Anything else?", "Do you mean 3 or 4 bedrooms?", SAFE_TEXT]);
});

test("ingress: run binding: one run id per entry, confirmed only by the exact id on a stored, unexpired, unended turn; endRun is idempotent; hasActiveTurn follows the run", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100 });
  const k = ing.key("default", PEER);
  const rec = { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 };
  // refused records store nothing
  for (const run of [null, 7, { runId: "", accountId: "default", peerId: PEER }, { runId: 5, accountId: "default", peerId: PEER }, { runId: "r", accountId: 1, peerId: PEER }, { runId: "r", accountId: "default", peerId: "+15550000002" }, { runId: "r", accountId: "acct2", peerId: PEER }]) {
    assert.equal(ing.record(k, rec, run), null, JSON.stringify(run));
  }
  assert.equal(ing.size(), 0);
  assert.equal(ing.hasActiveTurn(k), false);
  const h = ing.record(k, rec, { runId: "run-a", accountId: "default", peerId: "whatsapp:+1 (555) 000-0001" });
  assert.notEqual(h, null);
  assert.equal(ing.hasActiveTurn(k), true);
  // one run id, one entry
  assert.equal(ing.record(ing.key("default", "+15550000002"), rec, { runId: "run-a", accountId: "default", peerId: "+15550000002" }), null);
  // confirmation: only the exact issued string, only through the turn's own handle
  for (const id of ["RUN-A", " run-a", "run-b", "", undefined, null, 1, { toString: () => "run-a" }]) assert.equal(ing.confirmRun(h, id), false, String(id));
  assert.equal(ing.confirmRun({ ...h }, "run-a"), false);
  assert.equal(ing.confirmRun("t1", "run-a"), false);
  assert.equal(ing.forTurn(k, h).runBound, false);
  assert.equal(ing.confirmRun(h, "run-a"), true);
  assert.equal(ing.forTurn(k, h).runBound, true);
  // a later wrong id does not unconfirm
  assert.equal(ing.confirmRun(h, "run-b"), false);
  assert.equal(ing.forTurn(k, h).runBound, true);
  // ending: idempotent, the turn stops being active, its run admits nothing, its record stays
  assert.equal(ing.endRun(h), true);
  assert.equal(ing.endRun(h), true);
  assert.equal(ing.endRun({ ...h }), false);
  assert.equal(ing.hasActiveTurn(k), false);
  assert.deepEqual(ing.admitCardCall({ runId: "run-a", sessionKey: SESSION, toolName: "search_listings" }), { admitted: false, reason: "run-ended" });
  assert.equal(ing.forTurn(k, h).runBound, true);
  assert.equal(ing.forTurn(k, h).cardToolCalled, false);
  // an ended run cannot be confirmed
  const h2 = ing.record(k, { ...rec, turnId: "t2" }, { runId: "run-c", accountId: "default", peerId: PEER });
  ing.endRun(h2);
  assert.equal(ing.confirmRun(h2, "run-c"), false);
  // a turn recorded with no run is active until the TTL, never confirmable
  const k3 = ing.key("default", "+15550000003");
  const h3 = ing.record(k3, rec);
  assert.equal(ing.hasActiveTurn(k3), true);
  assert.equal(ing.confirmRun(h3, undefined), false);
  // the TTL is the backstop: an unended turn past it is no longer active and cannot be confirmed
  const h4 = ing.record(k, { ...rec, turnId: "t4" }, { runId: "run-d", accountId: "default", peerId: PEER });
  assert.equal(ing.hasActiveTurn(k), true);
  t = 101;
  assert.equal(ing.hasActiveTurn(k), false);
  assert.equal(ing.hasActiveTurn(k3), false);
  assert.equal(ing.confirmRun(h4, "run-d"), false);
  // capacity eviction of a peer's records does not end that peer's active turn; endRun
  // or the TTL does (one active turn per peer survives other peers filling the store)
  let u = 0;
  const small = createIngress({ now: () => u, ttlMs: 100, maxEntries: 2 });
  const peers = ["+15550000001", "+15550000002", "+15550000003"];
  const hs = peers.map((p, i) => small.record(small.key("default", p), { sessionKey: `agent:idx:whatsapp:direct:${p}`, turnId: `e${i}`, text: "hi" }, { runId: `run-e${i}`, accountId: "default", peerId: p }));
  assert.equal(small.size(), 2);
  assert.equal(small.forTurn(hs[0].key, hs[0]), null, "evicted");
  assert.equal(small.hasActiveTurn(hs[0].key), true, "still active while its run is open");
  assert.deepEqual(small.admitCardCall({ runId: "run-e0", sessionKey: "agent:idx:whatsapp:direct:+15550000001", toolName: "search_listings" }), { admitted: false, reason: "turn-expired" });
  small.endRun(hs[0]);
  assert.equal(small.hasActiveTurn(hs[0].key), false);
  assert.equal(small.hasActiveTurn(hs[1].key), true);
  u = 101;
  assert.equal(small.hasActiveTurn(hs[1].key), false, "the TTL still backstops");
});

test("audit log never carries text, peer or session key", async () => {
  const lines = [];
  const log = { info: (o) => lines.push(o), warn: (o) => lines.push(o), error: (o) => lines.push(o) };
  const { outbound, handle, runId } = gate({ log }, "3 or 4");
  await outbound.sendText({ to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default", turn: handle });
  await outbound.sendText({ to: PEER, text: "There are 12 homes", accountId: "default", turn: handle });
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
  assert.deepEqual(lines.map((l) => l.outcome), ["sent", "safe-text", "not_sent", "sent", "not_sent"]);
  assert.deepEqual(lines.map((l) => l.boundToTurn), [true, true, false, true, false]);
  assert.deepEqual(lines.map((l) => l.hasRecord), [true, true, false, true, false]);
  assert.equal(lines[2].reason, "no-turn-handle");
  assert.equal(lines[4].reason, "untrusted-turn");
  const blob = JSON.stringify(lines);
  for (const forbidden of ["bedrooms", "12 homes", "Hello", "5550000", SESSION, SAFE_TEXT, "t1", handle.key]) assert.ok(!blob.includes(forbidden), forbidden);
  assert.ok(!blob.includes(runId), "no run id");
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
  // the busy reply is checked as well: digit-free, short, and not SAFE_TEXT
  assert.deepEqual(selfCheck(DENY_CFG, { busyText: "Busy, try again in 5 minutes" }), { ok: false, reason: "busy-text-invalid" });
  assert.deepEqual(selfCheck(DENY_CFG, { busyText: SAFE_TEXT }), { ok: false, reason: "busy-text-invalid" });
  assert.deepEqual(selfCheck(DENY_CFG, { busyText: "" }), { ok: false, reason: "busy-text-invalid" });
});

// ---- default transport ------------------------------------------------------

test("default transport: unconfigured, startAccount rejects, sendText rejects once, no retry", async () => {
  const plugin = createChannelPlugin();
  assert.equal(plugin.config.isConfigured({}, {}), false);
  await assert.rejects(plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" }), new RegExp(NO_TRANSPORT_MESSAGE.replace(/[()]/g, "\\$&")));
  // even with an open turn and its trusted handle, nothing can go out
  const ingress = createIngress({ now: () => 0 });
  const h = ingress.record(ingress.key("default", PEER), { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 0 });
  const withTurn = createChannelPlugin({ ingress });
  await assert.rejects(withTurn.outbound.sendText({ to: PEER, text: "Hello", accountId: "default", turn: h }), /no transport configured/);
  assert.deepEqual(selfCheck(DENY_CFG), { ok: true });
  const fake = createChannelPlugin({ transport: createFakeTransport() });
  assert.equal(fake.config.isConfigured({}, {}), true);
});

// ---- end to end on the fake transport ----------------------------------------

test("end to end: greeting and clarification sent, invented figures replaced, cards bound to the turn and to an admitted card call", async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const resolver = createInMemoryCardResolver();
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: () => ({ listings: 1 }),
    // The card is stored for the turn the host is answering (turn.turnId is the
    // channel-generated id; turn.messageId is the peer's id, metadata only).
    replies: (t, turn) => {
      if (t === "hi") return "Hello! How can I help you find a home?";
      if (t === "3 or 4 beds?") return "Do you mean 3 or 4 bedrooms?";
      if (t === "anything in pasadena") return "There are 12 listings";
      if (t === "show me") {
        return {
          tool: "search_listings",
          reply: ({ result }) => {
            if (result) resolver.store(turn.sessionKey, turn.turnId, "c1", "123 Oak Ave | 3 bd | 960 sqft\n");
            return "[[card:c1]]";
          },
        };
      }
      if (t === "show me again") return { tool: "search_listings", reply: () => "[[card:c1]]" };
      if (t === "show without a search") return "[[card:c1]]";
      return "ok";
    },
  });
  const plugin = createChannelPlugin({ transport, ingress, cardResolver: resolver, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  assert.equal(transport.started, true);
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });

  await say("hi", "m1");
  await say("3 or 4 beds?", "m2");
  await say("anything in pasadena", "m3");
  await say("show me", "m4");
  await say("show me again", "m5"); // same token, next turn: resolver has nothing for that turn
  await say("show without a search", "m6"); // a token with no card call on its own turn

  assert.deepEqual(transport.sent.map((s) => s.text), [
    "Hello! How can I help you find a home?",
    "Do you mean 3 or 4 bedrooms?",
    SAFE_TEXT,
    "123 Oak Ave | 3 bd | 960 sqft\n",
    SAFE_TEXT,
    SAFE_TEXT,
  ]);
  assert.deepEqual(host.results.map((r) => r.withheld?.reason), [undefined, undefined, "idx-withheld:unverified-figures", undefined, "idx-withheld:unknown-token", "idx-withheld:card-without-trusted-call"]);
  assert.ok(!transport.sent.some((s) => s.text === "There are 12 listings"));
  for (const s of transport.sent) assert.equal(s.to, PEER);
  assert.equal(host.results[0].visibleReplySent, true);
  assert.equal(typeof host.results[0].messageId, "string");
  assert.deepEqual(host.turns.map((x) => x.messageId), ["m1", "m2", "m3", "m4", "m5", "m6"]);
  assert.equal(host.turns[3].sessionKey, SESSION);
  // the host's run-start callback always got undefined back
  assert.deepEqual(host.runStartReturns, [undefined, undefined, undefined, undefined, undefined, undefined]);
});

test("turn ids are channel-generated: a re-sent peer message id is a new turn and does not resolve the earlier turn's card", async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const resolver = createInMemoryCardResolver();
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: () => ({ listings: 1 }),
    replies: (t, turn) => {
      if (t !== "show me") return "ok";
      return {
        tool: "search_listings",
        reply: () => {
          if (turn.messageId === "m4" && !host.turns.some((x) => x !== turn && x.messageId === "m4")) {
            resolver.store(turn.sessionKey, turn.turnId, "c1", "123 Oak Ave | 3 bd | 960 sqft");
          }
          return "[[card:c1]]";
        },
      };
    },
  });
  const plugin = createChannelPlugin({ transport, ingress, cardResolver: resolver, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
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
  // run ids are channel-generated as well, one per turn, distinct from the turn ids
  const runIds = host.turns.map((x) => x.replyOptions.runId);
  assert.equal(new Set([...runIds, ...ids]).size, 6);
  for (const id of runIds) assert.match(id, /^[0-9a-f-]{36}$/);
  // an inbound without a message id still gets a turn
  await say("hi", undefined);
  assert.equal(host.turns[3].messageId, undefined);
  assert.match(host.turns[3].turnId, /^[0-9a-f-]{36}$/);
});

test("in-flight reply: a reply to turn N that lands after turn N+1 is verified against turn N; a tool send without a handle is withheld", async () => {
  const transport = createFakeTransport();
  const host = createFakeHost({ replies: () => "x" });
  const delivers = [];
  const plugin = createChannelPlugin({ transport, resolveRoute: host.resolveRoute, runInbound: async (turn) => { confirm(turn); delivers.push(turn.deliver); } });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  await say("3 or 4 beds?", "m1");
  await say("hello?", "m2");
  // the model's clarification for m1 arrives now
  const r = await delivers[0]({ text: "Do you mean 3 or 4 bedrooms?" });
  assert.deepEqual(r, { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?"]);
  // a tool send has no handle: nothing to bind to, nothing sent (not even SAFE_TEXT), though the peer has two fresh turns
  assert.deepEqual(await plugin.outbound.sendText({ to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?"]);
  // a figure the user wrote in m2 but not in m1 is unverified for the m1 reply
  const r2 = await delivers[0]({ text: "Hello back, 5 options?" });
  assert.equal(r2.visibleReplySent, true); // SAFE_TEXT, not the raw text
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?", SAFE_TEXT]);
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
  const { handle: otherHandle } = recordBoundTurn(ingress, { peerId: other, turnId: "t9", text: "hey", receivedAt: 1 });
  assert.deepEqual(await outbound.sendText({ to: other, text: "Hello!", accountId: "default", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  // another account id changes the key as well
  assert.deepEqual(await outbound.sendText({ to: PEER, text: "Hello!", accountId: "acct2", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, 0);
  // the other peer's own handle releases to them, and the transport is told that peer
  assert.equal(typeof (await outbound.sendText({ to: other, text: "Hello!", accountId: "default", turn: otherHandle })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.to), [other]);
});

test("R1-binding (a, f): a bare turnId from any caller is untrusted even when it names the turn whose figures match; a send with neither is withheld no-turn-handle", async () => {
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
  // (f) neither: no handle, so there is no fallback to the newest turn; nothing is sent in
  // either mode, not even SAFE_TEXT, although the peer has two fresh records
  assert.deepEqual(await outbound.sendText({ to: PEER, text: clarification, accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  assert.deepEqual(await outbound.sendText({ to: PEER, text: "Which city?", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  assert.equal(transport.sent.length, 0);
  // (d) the real handle still releases against its own turn
  assert.equal(typeof (await outbound.sendText({ to: PEER, text: clarification, accountId: "default", turn: handle })).messageId, "string");
  assert.equal(transport.sent.at(-1).text, clarification);
});

// ---- Rule 2: card turns require verified card tokens --------------------------------

/** A plugin on the fake transport whose host runner is scripted per inbound text. The
 *  runner confirms the run like the host does; `cardCall(turn, name)` fires the hook
 *  handler for that turn's own run, as the host would for a tool requested on it. */
async function cardPlugin({ script, resolver = createInMemoryCardResolver(), withholdMode } = {}) {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const results = [];
  const turns = [];
  const host = createFakeHost({ replies: () => "unused" });
  const hook = channelModule.createBeforeToolCallHandler(ingress);
  const cardCall = (turn, toolName) => {
    const runId = turn.replyOptions.runId;
    return hook({ toolName, params: {}, runId, toolCallId: "c" }, { toolName, agentId: "idx", sessionKey: turn.sessionKey, runId, toolCallId: "c" });
  };
  const plugin = createChannelPlugin({
    transport,
    ingress,
    cardResolver: resolver,
    ...(withholdMode ? { withholdMode } : {}),
    resolveRoute: host.resolveRoute,
    runInbound: async (turn) => {
      turns.push(turn);
      confirm(turn);
      await script(turn, { results, resolver, cardCall });
    },
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  return { transport, ingress, plugin, results, turns, say, resolver, cardCall };
}

test("R2-card-turn (a, b): after an admitted search_listings call prose becomes SAFE_TEXT with the card-turn reason; a resolving token sends the card bytes exactly", async () => {
  const card = "123 Oak Ave | 3 bd | 960 sqft\n";
  const { transport, results, say } = await cardPlugin({
    script: async (turn, { results: out, resolver, cardCall }) => {
      assert.deepEqual(cardCall(turn, "search_listings"), { block: false, marked: 1 });
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
    script: async (turn, { results: out, cardCall }) => {
      assert.deepEqual(cardCall(turn, "search_listings"), { block: false, marked: 1 });
      out.push(await turn.deliver({ text: "Here are some great homes for you." }));
    },
  });
  await say("anything in pasadena", "m1");
  assert.deepEqual(results, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:card-turn-requires-tokens" } }]);
  assert.equal(transport.sent.length, 0);
});

test("R2-card-turn (c, d, e): ordinary turns keep greetings and clarifications; a non-card tool name leaves the flag false", async () => {
  const { transport, turns, say } = await cardPlugin({
    script: async (turn, { cardCall }) => {
      if (turn.text === "hi") await turn.deliver({ text: "Hi! How can I help you today?" });
      if (turn.text === "3 or 4 bedrooms?") await turn.deliver({ text: "Do you mean 3 or 4 bedrooms?" });
      if (turn.text === "details please") {
        // a non-card name neither marks nor blocks: the tool may run and the turn stays ordinary
        for (const name of ["get_listing_details", "idx__get_listing_details", "health", "search_listings_v2"]) {
          assert.deepEqual(cardCall(turn, name), { block: false, marked: 0 }, name);
        }
        await turn.deliver({ text: "Sure, which one?" });
      }
    },
  });
  await say("hi", "m1");
  await say("3 or 4 bedrooms?", "m2");
  await say("details please", "m3");
  assert.deepEqual(transport.sent.map((s) => s.text), ["Hi! How can I help you today?", "Do you mean 3 or 4 bedrooms?", "Sure, which one?"]);
  // the flag stayed false: ordinary prose still releases on that turn
  assert.deepEqual(await turns[2].deliver({ text: "Happy to help." }), { messageId: "fake-4", visibleReplySent: true });
  assert.equal(turns.length, 3);
});

test("R2-card-turn (e, host runner): the turn object carries the ids as strings, nothing the ingress accepts as a handle, and no per-turn tool seam", async () => {
  const { transport, ingress, turns, say } = await cardPlugin({ script: async () => {} });
  await say("hi", "m1");
  const turn = turns[0];
  const key = ingress.key("default", PEER);
  assert.equal(typeof turn.turnId, "string");
  assert.equal(typeof turn.deliver, "function");
  assert.equal("current" in ingress, false); // no read by key for the runner (or anyone) to lean on
  // Rule 1 first: nothing the runner receives is a handle
  for (const [name, value] of Object.entries(turn)) assert.equal(ingress.forTurn(key, value), null, name);
  for (const [name, value] of Object.entries(turn.replyOptions)) assert.equal(ingress.forTurn(key, value), null, name);
  assert.equal(ingress.forTurn(key, turn.turnId), null);
  assert.equal(ingress.forTurn(key, { turnId: turn.turnId, key }), null);
  // Rule 2: the hook handler is the single admission path; the turn carries no tool seam
  assert.equal("beforeToolCall" in turn, false);
  assert.equal("noteToolCall" in turn, false);
  assert.deepEqual(Object.keys(turn.replyOptions).sort(), ["onAgentRunStart", "runId"]);
  assert.equal(typeof turn.replyOptions.runId, "string");
  // the run has ended (the runner settled), so the run id admits no card call now
  assert.equal(ingress.admitCardCall({ runId: turn.replyOptions.runId, sessionKey: turn.sessionKey, toolName: "recommend" }).reason, "run-ended");
  assert.deepEqual(await turn.deliver({ text: "Here you go!" }), { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Here you go!"]);
});

test("R2-card-turn (f): the mark is monotonic and per turn; an ended run admits no further mark", async () => {
  const { transport, turns, say, cardCall } = await cardPlugin({
    script: async (turn, { cardCall: call }) => {
      if (turn.text !== "search") return;
      assert.deepEqual(call(turn, "search_listings"), { block: false, marked: 1 });
    },
  });
  const prose = { text: "Here are a few homes." };
  const withheld = (r) => r.withheld?.reason;
  await say("search", "m1");
  assert.equal(withheld(await turns[0].deliver(prose)), "idx-withheld:card-turn-requires-tokens");
  assert.deepEqual(cardCall(turns[0], "get_listing_details"), { block: false, marked: 0 }); // no way back
  assert.equal(withheld(await turns[0].deliver(prose)), "idx-withheld:card-turn-requires-tokens");
  await say("thanks", "m2");
  // the new turn starts unmarked: prose releases there while the older turn stays marked
  assert.equal(withheld(await turns[1].deliver(prose)), undefined);
  assert.equal(withheld(await turns[0].deliver(prose)), "idx-withheld:card-turn-requires-tokens");
  // the older turn's ended run cannot mark the newer turn (no session-keyed marking any more)
  const late = cardCall(turns[0], "recommend");
  assert.equal(late.block, true);
  assert.equal(late.reason, "run-ended");
  assert.equal(withheld(await turns[1].deliver(prose)), undefined);
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, SAFE_TEXT, prose.text, SAFE_TEXT, prose.text]);
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
      const { handle, runId } = recordBoundTurn(ingress, { peerId: PEER, sessionKey: SESSION, turnId: "t1", text: "3 or 4", receivedAt: 1 });
      if (cardTurn) admitCard(ingress, runId);
      const plugin = createChannelPlugin({ transport, ingress, withholdMode, verify: () => verdict });
      const r = await plugin.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: handle });
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
  const { handle: okHandle } = recordBoundTurn(ingress, { peerId: PEER, sessionKey: SESSION, turnId: "t1", text: "3 or 4", receivedAt: 1 });
  const cardTurn = recordBoundTurn(ingress, { peerId: PEER, sessionKey: SESSION, turnId: "t2", text: "show me", receivedAt: 1 });
  admitCard(ingress, cardTurn.runId);
  const ok = createChannelPlugin({ transport, ingress, verify: ({ text }) => (text === "[[card:a]]" ? { kind: "release", rule: "card", viaCard: true, text: "card body" } : text === echo ? { kind: "release", rule: "user-figures", text } : { kind: "release", rule: "no-figures", text }) });
  for (const input of [digitFree, echo]) assert.equal(typeof (await ok.outbound.sendText({ to: PEER, text: input, accountId: "default", turn: okHandle })).messageId, "string", input);
  assert.equal(typeof (await ok.outbound.sendText({ to: PEER, text: "[[card:a]]", accountId: "default", turn: cardTurn.handle })).messageId, "string");
  assert.deepEqual(transport.sent.map((s) => s.text), [digitFree, echo, "card body"]);
});

test("a second plugin instance (fresh ingress, e.g. another process) holds no handle and trusts none, so it sends nothing", async () => {
  const transportA = createFakeTransport();
  const ingressA = createIngress({ now: () => 1 });
  const hostA = createFakeHost({ replies: () => "Hello!" });
  const a = createChannelPlugin({ transport: transportA, ingress: ingressA, resolveRoute: hostA.resolveRoute, runInbound: hostA.runInbound });
  await a.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transportA.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  const transportB = createFakeTransport();
  const b = createChannelPlugin({ transport: transportB });
  assert.deepEqual(await b.outbound.sendText({ to: PEER, text: "Hello!", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  // even a handle minted by A's ingress is untrusted in B
  const foreign = ingressA.record(ingressA.key("default", PEER), { sessionKey: SESSION, turnId: "t2", text: "again", receivedAt: 2 });
  assert.deepEqual(await b.outbound.sendText({ to: PEER, text: "Hello!", accountId: "default", turn: foreign }), { outcome: "not_sent", reason: "untrusted-turn" });
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

// ---- Decision 17: the channel-minted handle is required; no latest-turn fallback -----------

test("D17-no-turn-handle: a fresh inbound record exists, yet a send without a handle is withheld with nothing sent, in both modes; the channel's own deliver on that turn releases", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const transport = createFakeTransport();
    let t = 1000;
    const ingress = createIngress({ now: () => t });
    let captured;
    const host = createFakeHost({ replies: () => "unused" });
    const plugin = createChannelPlugin({ transport, ingress, withholdMode, resolveRoute: host.resolveRoute, runInbound: async (turn) => { confirm(turn); captured = turn; } });
    await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
    await transport.inbound({ accountId: "default", peerId: PEER, text: "I want 3 bedrooms", messageId: "m1", receivedAt: t });
    t += 2000; // seconds old, far inside the TTL: the record is current and unexpired
    const greeting = "Hello! How can I help you find a home?";
    const echo = "You asked for 3 bedrooms, right?";
    // the texts would pass every verifier rule against this record
    assert.equal(verifyReply({ text: greeting, inbound: record("I want 3 bedrooms"), resolver: { resolve: () => null } }).kind, "release");
    assert.equal(verifyReply({ text: echo, inbound: record("I want 3 bedrooms"), resolver: { resolve: () => null } }).kind, "release");
    for (const text of [greeting, echo]) {
      for (const to of [PEER, "whatsapp:+15550000001", "15550000001@s.whatsapp.net"]) {
        assert.deepEqual(await plugin.outbound.sendText({ cfg: DENY_CFG, to, text, accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" }, `${withholdMode} ${to} ${text}`);
      }
    }
    assert.equal(transport.sent.length, 0, withholdMode);
    // positive control: the same turn's deliver carries the handle and releases the greeting
    assert.deepEqual(await captured.deliver({ text: greeting }), { messageId: "fake-1", visibleReplySent: true });
    assert.deepEqual(await captured.deliver({ text: echo }), { messageId: "fake-2", visibleReplySent: true });
    assert.deepEqual(transport.sent.map((s) => s.text), [greeting, echo]);
  }
});

// ---- Decision 16: the card-turn mark comes from the host's before-tool-call event ------------

/** A plugin whose fake host runs tools through the registered hook: the admission fires
 *  before execution, then the tool runs, then the model replies. */
async function toolPlugin({ tools, replies, withholdMode } = {}) {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const host = createFakeHost({ replies, tools, hook: channelModule.createBeforeToolCallHandler(ingress) });
  const plugin = createChannelPlugin({ transport, ingress, ...(withholdMode ? { withholdMode } : {}), resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text, messageId) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId, receivedAt: 1 });
  return { transport, host, plugin, say, ingress };
}

const APOLOGY = "Sorry, something went wrong searching.";
const SEARCH_APOLOGY = "Sorry, I couldn't run that search.";
const CARD = "123 Oak Ave | 3 bd | 960 sqft\n";

test("D16 (a): a card tool that THROWS still leaves the turn marked, because the admission marked it before execution; the digit-free apology is withheld card-turn-requires-tokens", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const { transport, host, say } = await toolPlugin({
      withholdMode,
      tools: () => { throw new Error("upstream search failed"); },
      replies: () => ({ tool: "search_listings", reply: ({ error }) => (error ? APOLOGY : "unexpected success") }),
    });
    await say("anything in pasadena", "m1");
    assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-threw"], withholdMode);
    assert.deepEqual(host.decisions, [{ block: false, marked: 1 }], withholdMode);
    if (withholdMode === "safe-text") {
      assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
      assert.equal(host.results[0].visibleReplySent, true);
      assert.deepEqual(host.results[0].withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
    } else {
      assert.equal(transport.sent.length, 0);
      assert.deepEqual(host.results, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:card-turn-requires-tokens" } }]);
    }
    assert.ok(!transport.sent.some((s) => s.text === APOLOGY));
  }
});

test("D16 (b): a card tool that returns an error-shaped result leaves the turn marked; the apology is withheld", async () => {
  const { transport, host, say } = await toolPlugin({
    tools: () => ({ isError: true, content: [{ type: "text", text: "search backend unavailable" }] }),
    replies: () => ({ tool: "search_listings", reply: ({ result }) => (result?.isError ? APOLOGY : "unexpected success") }),
  });
  await say("anything in pasadena", "m1");
  assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-executed"]);
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  assert.deepEqual(host.results[0].withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
});

test("D16 (c): createBeforeToolCallHandler admits a card call only for the run it names and marks that turn alone; a non-card tool is never blocked and reads no other field; a refused card call of unknown origin changes no turn", () => {
  assert.equal(typeof channelModule.createBeforeToolCallHandler, "function");
  const ing = createIngress({ now: () => 1 });
  const k1 = ing.key("default", PEER);
  const k2 = ing.key("default", "+15550000002");
  const otherSession = "agent:idx:whatsapp:direct:+15550000002";
  const a = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "a", text: "hi" });
  const b = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "b", text: "more" });
  const c = recordBoundTurn(ing, { peerId: "+15550000002", sessionKey: otherSession, turnId: "c", text: "hello" });
  const handler = channelModule.createBeforeToolCallHandler(ing);
  const call = (toolName, runId, sessionKey, extra = {}) => handler({ toolName, params: {}, runId, toolCallId: "x" }, { toolName, agentId: "idx", sessionKey, runId, toolCallId: "x", ...extra });
  // b's run marks b only, not the other open turn of the same session, not another peer
  assert.deepEqual(call("get_market_stats", b.runId, SESSION), { block: false, marked: 1 });
  assert.equal(ing.forTurn(k1, b.handle).cardToolCalled, true);
  assert.equal(ing.forTurn(k1, a.handle).cardToolCalled, false);
  assert.equal(ing.forTurn(k2, c.handle).cardToolCalled, false);
  // a non-card tool is allowed whatever the context, and the context is not even read
  const boom = () => { throw new Error("boom"); };
  for (const ctx of [{ sessionKey: otherSession }, {}, { sessionKey: 42 }, null, undefined, { get runId() { return boom(); }, get sessionKey() { return boom(); } }]) {
    assert.deepEqual(handler({ toolName: "get_listing_details" }, ctx), { block: false, marked: 0 });
  }
  // a card call naming no open run is refused and every turn stays as it was (no global taint)
  const before = [[k1, a.handle], [k1, b.handle], [k2, c.handle]].map(([k, h]) => ing.forTurn(k, h));
  for (const ctx of [{}, { sessionKey: 42 }, { sessionKey: null }, null, undefined, []]) {
    const d = handler({ toolName: "search_listings" }, ctx);
    assert.equal(d.block, true, JSON.stringify(ctx));
    assert.equal(d.reason, "unknown-run", JSON.stringify(ctx));
    assert.equal(d.blockReason, constants.CARD_TOOL_BLOCK_REASON);
  }
  assert.equal(call("search_listings", "agent:idx:whatsapp:direct:nobody", SESSION).reason, "unknown-run");
  assert.deepEqual([[k1, a.handle], [k1, b.handle], [k2, c.handle]].map(([k, h]) => ing.forTurn(k, h)), before);
  // c's own run marks c
  assert.deepEqual(call("recommend", c.runId, otherSession), { block: false, marked: 1 });
  assert.equal(ing.forTurn(k2, c.handle).cardToolCalled, true);
  assert.throws(() => channelModule.createBeforeToolCallHandler(undefined), /needs an ingress/);
  assert.throws(() => channelModule.createBeforeToolCallHandler({ markCardToolForSession: () => 0 }), /needs an ingress/);
});

// ---- Card-call refusals (rewritten from the blocking-mark BM-* tests for owner decision 19) ----

test("BM-1 (mismatched session, rewritten): a card call whose session key is not the turn's is refused session-mismatch and does not execute; no taint, so the digit-free apology releases while a later resolving token is withheld card-without-trusted-call; with the matching key the tool runs and the token releases", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const transport = createFakeTransport();
    const ingress = createIngress({ now: () => 1 });
    const resolver = createInMemoryCardResolver();
    let executed = 0;
    const host = createFakeHost({
      hook: channelModule.createBeforeToolCallHandler(ingress),
      // the right run id, the right peer, a different agent prefix on the key
      rewrite: ({ ctx }) => ({ ctx: { ...ctx, sessionKey: ctx.sessionKey.replace(/^agent:idx:/u, "agent:other:") } }),
      tools: () => { executed += 1; return { listings: 1 }; },
      replies: () => ({ tool: "search_listings", reply: ({ blocked }) => (blocked ? SEARCH_APOLOGY : "unexpected success") }),
    });
    const plugin = createChannelPlugin({ transport, ingress, cardResolver: resolver, withholdMode, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
    await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
    await transport.inbound({ accountId: "default", peerId: PEER, text: "anything in pasadena", messageId: "m1", receivedAt: 1 });
    assert.deepEqual(host.decisions, [{ block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "session-mismatch", withheld: 0 }], withholdMode);
    assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-blocked:session-mismatch"], withholdMode);
    assert.equal(executed, 0, withholdMode);
    // no listing data entered the turn and the turn is not tainted: the apology releases
    assert.deepEqual(transport.sent.map((s) => s.text), [SEARCH_APOLOGY], withholdMode);
    assert.deepEqual(host.results, [{ messageId: "fake-1", visibleReplySent: true }], withholdMode);
    // a card appearing for that turn later is not supported by any admitted call
    const turn = host.turns[0];
    resolver.store(turn.sessionKey, turn.turnId, "c1", CARD);
    const later = await turn.deliver({ text: "[[card:c1]]" });
    if (withholdMode === "safe-text") {
      assert.deepEqual(later.withheld, { reason: "idx-withheld:card-without-trusted-call" });
      assert.deepEqual(transport.sent.map((s) => s.text), [SEARCH_APOLOGY, SAFE_TEXT]);
    } else {
      assert.deepEqual(later, { visibleReplySent: false, suppression: { reason: "idx-withheld:card-without-trusted-call" } });
      assert.equal(transport.sent.length, 1);
    }
    assert.ok(!transport.sent.some((s) => s.text === CARD));
  }
  // positive control: the matching key admits the call, the tool executes and the token releases
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const resolver = createInMemoryCardResolver();
  let executed = 0;
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: () => { executed += 1; return { listings: 1 }; },
    replies: (_t, turn) => ({
      tool: "search_listings",
      reply: ({ result }) => {
        if (!result) return SEARCH_APOLOGY;
        resolver.store(turn.sessionKey, turn.turnId, "c1", CARD);
        return "[[card:c1]]";
      },
    }),
  });
  const plugin = createChannelPlugin({ transport, ingress, cardResolver: resolver, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "anything in pasadena", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(host.decisions, [{ block: false, marked: 1 }]);
  assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-executed"]);
  assert.equal(executed, 1);
  assert.deepEqual(transport.sent.map((s) => s.text), [CARD]);
  assert.deepEqual(host.results, [{ messageId: "fake-1", visibleReplySent: true }]);
});

/** An ingress wrapper that forwards every method to the real one except those in `overrides`, and records calls. */
function wrapIngress(real, overrides = {}) {
  const calls = [];
  const wrapped = {};
  for (const name of Object.keys(real)) {
    wrapped[name] = (...args) => {
      calls.push(name);
      if (name in overrides) return overrides[name](...args);
      return real[name](...args);
    };
  }
  return { wrapped, calls };
}

test("BM-2 (handler error, rewritten): a throwing getter on the context or the event, an ingress whose admitCardCall throws or answers garbage, and an event without a string tool name each refuse handler-error, run nothing and change no turn", async () => {
  const boom = () => { throw new Error("boom"); };
  // (a) the ctx sessionKey getter throws inside a real run: the tool is not executed
  {
    const transport = createFakeTransport();
    const ingress = createIngress({ now: () => 1 });
    let executed = 0;
    const host = createFakeHost({
      hook: channelModule.createBeforeToolCallHandler(ingress),
      rewrite: ({ ctx }) => ({ ctx: { ...ctx, get sessionKey() { return boom(); } } }),
      tools: () => { executed += 1; return {}; },
      replies: () => ({ tool: "search_listings", reply: ({ blocked }) => (blocked ? SEARCH_APOLOGY : "unexpected success") }),
    });
    const plugin = createChannelPlugin({ transport, ingress, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
    await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
    await transport.inbound({ accountId: "default", peerId: PEER, text: "homes?", messageId: "m1", receivedAt: 1 });
    assert.deepEqual(host.decisions, [{ block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "handler-error", withheld: 0 }]);
    assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-blocked:handler-error"]);
    assert.equal(executed, 0);
    // nothing ran and nothing was marked: the turn stays ordinary and its apology releases
    assert.deepEqual(transport.sent.map((s) => s.text), [SEARCH_APOLOGY]);
  }
  // (b) the ingress throws, or answers garbage, inside admitCardCall
  {
    const real = createIngress({ now: () => 1 });
    const t = recordBoundTurn(real, { peerId: PEER, sessionKey: SESSION, text: "hi" });
    const event = { toolName: "search_listings", runId: t.runId };
    const ctx = { sessionKey: SESSION, runId: t.runId };
    const thrown = wrapIngress(real, { admitCardCall: boom });
    const handler = channelModule.createBeforeToolCallHandler(thrown.wrapped);
    assert.deepEqual(handler(event, ctx), { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "handler-error", withheld: 0 });
    assert.deepEqual(thrown.calls, ["admitCardCall"]);
    for (const garbage of [undefined, null, 1, true, { admitted: "yes" }, { admitted: false, reason: "made-up" }, { admitted: false }]) {
      const g = wrapIngress(real, { admitCardCall: () => garbage });
      assert.deepEqual(channelModule.createBeforeToolCallHandler(g.wrapped)(event, ctx), { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "handler-error", withheld: 0 }, JSON.stringify(garbage));
    }
    assert.equal(real.forTurn(t.handle.key, t.handle).cardToolCalled, false);
    // a non-card tool never reaches the ingress
    assert.deepEqual(handler({ toolName: "get_listing_details" }, ctx), { block: false, marked: 0 });
    assert.deepEqual(thrown.calls, ["admitCardCall"]);
    // the real ingress admits the same call
    assert.deepEqual(channelModule.createBeforeToolCallHandler(real)(event, ctx), { block: false, marked: 1 });
  }
  // (c) an event without a string tool name, or with a throwing getter: the tool cannot be identified
  {
    const ing = createIngress({ now: () => 1 });
    const t = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, text: "hi" });
    const handler = channelModule.createBeforeToolCallHandler(ing);
    for (const event of [{}, { toolName: undefined }, { toolName: 7 }, { toolName: ["search_listings"] }, { toolName: { name: "search_listings" } }, { toolName: null }, { tool: "search_listings" }, undefined, null, "search_listings", 7, { get toolName() { return boom(); } }, { toolName: "search_listings", get runId() { return boom(); } }]) {
      assert.deepEqual(handler(event, { sessionKey: SESSION, runId: t.runId }), { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "handler-error", withheld: 0 }, String(event));
    }
    assert.equal(ing.forTurn(t.handle.key, t.handle).cardToolCalled, false);
    assert.equal(ing.forTurn(t.handle.key, t.handle).runBound, true);
  }
});

test("BM-4 (non-card tool, mismatched session): the hook handler neither marks nor blocks, the tool executes and the ordinary reply releases", async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  let executed = 0;
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    rewrite: ({ ctx }) => ({ ctx: { ...ctx, sessionKey: "agent:other:whatsapp:direct:nobody", runId: "not-a-run" } }),
    tools: () => { executed += 1; return { address: "123 Oak Ave" }; },
    replies: () => ({ tool: "get_listing_details", reply: ({ result }) => (result ? "Here is what I found. Want the details?" : SEARCH_APOLOGY) }),
  });
  const plugin = createChannelPlugin({ transport, ingress, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "details please", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(host.decisions, [{ block: false, marked: 0 }]);
  assert.deepEqual(host.events, ["before-tool-call:get_listing_details", "tool-executed"]);
  assert.equal(executed, 1);
  assert.deepEqual(transport.sent.map((s) => s.text), ["Here is what I found. Want the details?"]);
  assert.deepEqual(host.results, [{ messageId: "fake-1", visibleReplySent: true }]);
  // greetings keep working on that turn
  assert.deepEqual(await host.turns[0].deliver({ text: "Anything else?" }), { messageId: "fake-2", visibleReplySent: true });
});

test("BM-7 (decision shape, rewritten): the handler never throws and never returns a bare value; every decision is { block: false, marked: 0 | 1 } or { block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason: <code>, withheld: 0 | 1 }, with withheld 1 only for requester-mismatch", () => {
  const boom = () => { throw new Error("boom"); };
  const trap = new Proxy({}, { get: boom, has: boom, ownKeys: boom, getOwnPropertyDescriptor: boom });
  const { proxy: revoked, revoke } = Proxy.revocable({}, {});
  revoke();
  const garbage = [null, undefined, 7, "", [], {}, true, Symbol("x"), () => {}, trap, revoked, { toolName: "search_listings" }, "search_listings", "get_listing_details", " idx__recommend "];
  const label = (v) => { try { return typeof v === "symbol" ? "symbol" : typeof v === "object" && v !== null ? JSON.stringify(v) ?? "object" : String(v); } catch { return `<${typeof v}>`; } };
  const CODES = ["unknown-run", "run-unconfirmed", "run-ended", "turn-expired", "session-mismatch", "requester-mismatch", "handler-error"];
  const isDecision = (d) => {
    if (d === null || typeof d !== "object" || typeof d.block !== "boolean") return false;
    if (d.block === false) return (d.marked === 0 || d.marked === 1) && Object.keys(d).length === 2;
    if (d.withheld !== 0 && d.withheld !== 1) return false;
    if (d.withheld === 1 && d.reason !== "requester-mismatch") return false;
    return d.blockReason === constants.CARD_TOOL_BLOCK_REASON && CODES.includes(d.reason) && Object.keys(d).length === 4;
  };
  assert.equal(typeof constants.CARD_TOOL_BLOCK_REASON, "string");
  assert.ok(constants.CARD_TOOL_BLOCK_REASON.length > 0);
  assert.equal(/\p{N}/u.test(constants.CARD_TOOL_BLOCK_REASON), false);
  const ing = createIngress({ now: () => 1 });
  const t = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, text: "hi" });
  const handler = channelModule.createBeforeToolCallHandler(ing);
  const events = [...garbage, { toolName: trap }, { get toolName() { return boom(); } }, { toolName: "search_listings", extra: trap }, { toolName: "search_listings", runId: t.runId }, { toolName: "search_listings", runId: trap }];
  const ctxs = [...garbage, { sessionKey: SESSION, runId: t.runId }, { get sessionKey() { return boom(); }, runId: t.runId }, { sessionKey: trap, runId: t.runId }, { sessionKey: SESSION, runId: t.runId, requester: trap }];
  for (const event of events) {
    for (const ctx of ctxs) {
      let d;
      assert.doesNotThrow(() => { d = handler(event, ctx); });
      assert.ok(isDecision(d), `handler(${label(event)}, ${label(ctx)}) -> ${JSON.stringify(d)}`);
      assert.equal("tainted" in d, false);
    }
  }
  // a string tool name that is not a card tool is never blocked, whatever the context
  for (const ctx of ctxs) assert.deepEqual(handler({ toolName: "get_listing_details" }, ctx), { block: false, marked: 0 });
});

test("BM-8 (expired turn, rewritten): a card call on a turn past the ingress TTL is refused turn-expired, does not execute, and the reply is withheld untrusted-turn with nothing sent", async () => {
  let t = 1;
  const ingress = createIngress({ now: () => t, ttlMs: 100 });
  const transport = createFakeTransport();
  let executed = 0;
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: () => { executed += 1; return { listings: 1 }; },
    replies: () => {
      t += 101; // the model's tool call comes after the TTL has passed; the run never settled
      return { tool: "search_listings", reply: ({ blocked }) => (blocked ? SEARCH_APOLOGY : "unexpected success") };
    },
  });
  const plugin = createChannelPlugin({ transport, ingress, now: () => t, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "homes?", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(host.decisions, [{ block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "turn-expired", withheld: 0 }]);
  assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-blocked:turn-expired"]);
  assert.equal(executed, 0);
  // the expired handle is untrusted at the gate as well: silent even in safe-text mode
  assert.equal(transport.sent.length, 0);
  assert.deepEqual(host.results, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } }]);
});

test("D16 (d): a mark applied before execution survives a later record of a new turn for the same peer", async () => {
  const { transport, host, say } = await toolPlugin({
    tools: () => { throw new Error("timeout"); },
    replies: (t) => (t === "search" ? { tool: "search_listings", reply: () => APOLOGY } : "You're welcome!"),
  });
  await say("search", "m1");
  await say("thanks", "m2");
  assert.deepEqual(host.events, ["before-tool-call:search_listings", "tool-threw"]);
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, "You're welcome!"]);
  // the old handle's record is still marked: prose on it stays withheld; the new turn is unmarked
  assert.deepEqual((await host.turns[0].deliver({ text: "Here are some homes." })).withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
  assert.deepEqual(await host.turns[1].deliver({ text: "Anything else?" }), { messageId: "fake-4", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT, "You're welcome!", SAFE_TEXT, "Anything else?"]);
});

test("D16 (f): the host's own spelling of a card tool (idx__ prefix, server prefix, case, padding) is admitted and marks the turn; a failed call under that spelling still withholds the apology", async () => {
  // includes the host's `-N` collision suffix on a bundled MCP name (install prerequisite 5)
  const spellings = ["idx__search_listings", "mcp__idx__search_listings", "idx.search_listings", "Search_Listings", " search_listings", "search_listings ", "IDX__Get_Market_Stats", "idx__search_listings-2", "idx__recommend-1", "mcp__idx__get_market_stats-3"];
  for (const name of spellings) {
    const { transport, host, say } = await toolPlugin({
      tools: () => { throw new Error("upstream search failed"); },
      replies: () => ({ tool: name, reply: ({ error }) => (error ? APOLOGY : "unexpected success") }),
    });
    await say("homes in pasadena", "m1");
    assert.deepEqual(host.events, [`before-tool-call:${name}`, "tool-threw"], name);
    assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT], name);
    assert.deepEqual(host.results[0].withheld, { reason: "idx-withheld:card-turn-requires-tokens" }, name);
    assert.ok(!transport.sent.some((s) => s.text === APOLOGY), name);
  }
  // the handler admits under the same spellings, before any tool runs
  for (const name of spellings) {
    const ing = createIngress({ now: () => 1 });
    const t = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, text: "hi" });
    const handler = channelModule.createBeforeToolCallHandler(ing);
    // without a run the same spelling is a card call and is refused, never let through unchecked
    assert.deepEqual(handler({ toolName: name }, {}), { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "unknown-run", withheld: 0 }, name);
    assert.deepEqual(handler({ toolName: name, runId: t.runId }, { sessionKey: SESSION, runId: t.runId }), { block: false, marked: 1 }, name);
    assert.equal(ing.forTurn(t.handle.key, t.handle).cardToolCalled, true, name);
  }
  // a name that only resembles a card tool is not one: the turn stays ordinary (positive control for D16 (e))
  for (const name of ["idx__get_listing_details", "search_listings_v2", "idx__search_listing"]) {
    const { transport, host, say } = await toolPlugin({
      tools: () => { throw new Error("lookup failed"); },
      replies: () => ({ tool: name, reply: () => "Sorry, that lookup failed. Which one did you mean?" }),
    });
    await say("details please", "m1");
    assert.deepEqual(host.events, [`before-tool-call:${name}`, "tool-threw"], name);
    assert.deepEqual(transport.sent.map((s) => s.text), ["Sorry, that lookup failed. Which one did you mean?"], name);
  }
});

test("D16 (e): an ordinary turn with a non-card tool that throws, then a digit-free apology, is released under the ordinary rules", async () => {
  const { transport, host, say } = await toolPlugin({
    tools: () => { throw new Error("listing lookup failed"); },
    replies: () => ({ tool: "get_listing_details", reply: () => "Sorry, I couldn't fetch that listing. Which one did you mean?" }),
  });
  await say("details please", "m1");
  assert.deepEqual(host.events, ["before-tool-call:get_listing_details", "tool-threw"]);
  assert.deepEqual(transport.sent.map((s) => s.text), ["Sorry, I couldn't fetch that listing. Which one did you mean?"]);
  assert.deepEqual(host.results, [{ messageId: "fake-1", visibleReplySent: true }]);
});

// ---- Owner decision 19 (2026-11-07): run binding, isolation, release support, one active turn ----

const P1 = PEER;
const P2 = "+15550000002";
const S1 = SESSION;
const S2 = `agent:idx:whatsapp:direct:${P2}`;
const flush = () => new Promise((resolve) => setImmediate(resolve));
/** Tests that hold runs open fail on a timeout instead of hanging when a runtime lacks the busy path. */
const HELD = { timeout: 5000 };

/**
 * Two (or more) peers whose runs the test holds open. `begin(peer, text)` sends an
 * inbound and returns once the fake host is holding that run (its reply function
 * returned nothing; the test delivers by hand); `end(peer)` lets the run settle. The
 * ingress is wrapped only to capture the handles the channel minted, so a test can read
 * the stored records directly.
 */
async function heldPlugin({ withholdMode, ttlMs = 10_000, maxEntries, hostOpts = {}, peerHold = true } = {}) {
  const transport = createFakeTransport();
  let t = 1;
  const real = createIngress({ now: () => t, ttlMs, ...(maxEntries !== undefined ? { maxEntries } : {}) });
  const handles = [];
  const ingress = { ...real, record: (...args) => { const h = real.record(...args); if (h) handles.push(h); return h; } };
  const resolver = createInMemoryCardResolver();
  const executions = [];
  const releases = new Map();
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: (name, run) => { executions.push({ name, sessionKey: run.sessionKey }); return { listings: 1 }; },
    replies: () => undefined,
    hold: peerHold ? (run) => new Promise((resolve) => { releases.set(run.turn.peerId, [...(releases.get(run.turn.peerId) ?? []), resolve]); }) : undefined,
    ...hostOpts,
  });
  const lines = [];
  const plugin = createChannelPlugin({
    transport,
    ingress,
    cardResolver: resolver,
    now: () => t,
    log: { info: (o) => lines.push(o), warn: (o) => lines.push(o) },
    ...(withholdMode ? { withholdMode } : {}),
    resolveRoute: host.resolveRoute,
    runInbound: host.runInbound,
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const pending = new Map();
  const begin = async (peer, text) => {
    const done = transport.inbound({ accountId: "default", peerId: peer, text, messageId: `m-${text}`, receivedAt: t });
    await flush();
    const turn = host.turns.at(-1);
    const run = host.runs.at(-1);
    pending.set(peer, [...(pending.get(peer) ?? []), done]);
    return { done, turn, run };
  };
  /** Settles every held run of the peer. */
  const end = async (peer) => {
    for (const resolve of releases.get(peer) ?? []) resolve();
    releases.delete(peer);
    await Promise.all(pending.get(peer) ?? []);
    pending.delete(peer);
  };
  const recordAt = (i) => real.forTurn(handles[i].key, handles[i]);
  return { transport, real, ingress, handles, recordAt, resolver, executions, host, plugin, begin, end, lines, advance: (ms) => { t += ms; } };
}

test("RB-1 (binding, MCP path): with P1 and P2 both active and confirmed, a card call carrying P1's run id and P1's session key and no requester is admitted, executes and marks P1 only; P1's token reply releases; P2 is unchanged", HELD, async () => {
  const h = await heldPlugin();
  const a = await h.begin(P1, "homes in pasadena");
  const b = await h.begin(P2, "hello");
  assert.deepEqual(h.host.runStartReturns, [undefined, undefined]);
  const r = await h.host.callTool(a.run, "idx__search_listings");
  assert.equal(r.executed, true);
  assert.deepEqual(h.host.decisions, [{ block: false, marked: 1 }]);
  assert.deepEqual(h.executions, [{ name: "idx__search_listings", sessionKey: S1 }]);
  assert.equal(h.recordAt(0).cardToolCalled, true);
  assert.equal(h.recordAt(1).cardToolCalled, false);
  assert.equal(h.recordAt(1).runBound, true);
  h.resolver.store(S1, a.turn.turnId, "c1", CARD);
  assert.deepEqual(await a.turn.deliver({ text: "[[card:c1]]" }), { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(await b.turn.deliver({ text: "Hi! How can I help?" }), { messageId: "fake-2", visibleReplySent: true });
  assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, CARD], [P2, "Hi! How can I help?"]]);
  await h.end(P1);
  await h.end(P2);
});

test("RB-2 (binding, requester path): a requester naming channel 'WhatsApp ' (padded, cased), P1 in a JID or spaced spelling and the turn's account id is admitted", HELD, async () => {
  for (const requester of [
    { channel: "WhatsApp ", accountId: "default", senderId: "15550000001@s.whatsapp.net", senderIsOwner: false, roleIds: [] },
    { channel: " WHATSAPP", accountId: "default", senderId: "+1 (555) 000-0001" },
    { channel: "whatsapp", senderId: "whatsapp:+15550000001" }, // no accountId: not compared
  ]) {
    const h = await heldPlugin();
    const a = await h.begin(P1, "homes");
    await h.begin(P2, "hello");
    const r = await h.host.callTool(a.run, "search_listings", { requester });
    assert.equal(r.executed, true, JSON.stringify(requester));
    assert.equal(h.recordAt(0).cardToolCalled, true);
    assert.equal(h.recordAt(1).cardToolCalled, false);
    await h.end(P1);
    await h.end(P2);
  }
});

test("RB-3 (binding refusals, revision 7): each forged, mismatched or stale card call is refused with its code and nothing executes; no refusal marks a card call, the untied ones change neither record, and only a requester mismatch on P1's own run id and key marks P1 (and only P1) cardCallRefused", HELD, async () => {
  const boom = () => { throw new Error("boom"); };
  const h = await heldPlugin();
  const a = await h.begin(P1, "homes");
  const b = await h.begin(P2, "hello");
  const P1run = a.run.runId;
  const P2run = b.run.runId;
  const ev = (patch) => ({ event }) => ({ event: { ...event, ...patch } });
  const cx = (patch) => ({ ctx }) => ({ ctx: { ...ctx, ...patch } });
  const both = (runId) => ({ event, ctx }) => ({ event: { ...event, runId }, ctx: { ...ctx, runId } });
  const without = (obj, key) => { const o = { ...obj }; delete o[key]; return o; };
  const cases = [
    ["missing run id", { rewrite: ({ event, ctx }) => ({ event: without(event, "runId"), ctx: without(ctx, "runId") }) }, "unknown-run"],
    ["empty run id", { rewrite: both("") }, "unknown-run"],
    ["non-string run id", { rewrite: both(7) }, "unknown-run"],
    ["unknown run id", { rewrite: both("4f1c0000-0000-4000-8000-000000000000") }, "unknown-run"],
    ["event.runId differs from ctx.runId", { rewrite: cx({ runId: P2run }) }, "unknown-run"],
    ["ctx.runId missing", { rewrite: ({ ctx }) => ({ ctx: without(ctx, "runId") }) }, "unknown-run"],
    ["event.runId missing", { rewrite: ({ event }) => ({ event: without(event, "runId") }) }, "unknown-run"],
    ["session key missing", { rewrite: ({ ctx }) => ({ ctx: without(ctx, "sessionKey") }) }, "session-mismatch"],
    ["session key is P2's", { rewrite: cx({ sessionKey: S2 }) }, "session-mismatch"],
    ["session key is the dashboard's", { rewrite: cx({ sessionKey: "agent:idx:main" }) }, "session-mismatch"],
    ["requester names P2", { requester: { channel: "whatsapp", accountId: "default", senderId: P2 } }, "requester-mismatch"],
    ["requester channel webchat", { requester: { channel: "webchat", accountId: "default", senderId: P1 } }, "requester-mismatch"],
    ["requester null", { requester: null }, "requester-mismatch"],
    // an array carrying every expected field, so only the array guard can refuse it
    ["requester array", { requester: Object.assign([], { channel: "whatsapp", accountId: "default", senderId: P1 }) }, "requester-mismatch"],
    ["requester array of the peer", { requester: [P1] }, "requester-mismatch"],
    ["requester senderId not a string", { requester: { channel: "whatsapp", senderId: 15550000001 } }, "requester-mismatch"],
    ["requester senderId empty", { requester: { channel: "whatsapp", senderId: "  " } }, "requester-mismatch"],
    ["requester accountId mismatch", { requester: { channel: "whatsapp", accountId: "acct2", senderId: P1 } }, "requester-mismatch"],
    ["throwing getter on the event", { rewrite: ({ event }) => ({ event: { ...event, get runId() { return boom(); } } }) }, "handler-error"],
    ["throwing getter on the ctx", { rewrite: ({ ctx }) => ({ ctx: { ...ctx, get requester() { return boom(); } } }) }, "handler-error"],
    ["throwing getter inside the requester", { requester: { channel: "whatsapp", get senderId() { return boom(); } } }, "handler-error"],
  ];
  let tied = false;
  for (const [label, opts, reason] of cases) {
    const before = h.host.decisions.length;
    const r = await h.host.callTool(a.run, "search_listings", opts);
    assert.equal(r.executed, false, label);
    const d = h.host.decisions[before];
    // owner decision 21: a requester mismatch on P1's own run id and key is tied to P1's turn
    const withheld = reason === "requester-mismatch" ? 1 : 0;
    assert.deepEqual(d, { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason, withheld }, label);
    assert.deepEqual(r.outcome, { blocked: constants.CARD_TOOL_BLOCK_REASON }, label);
    tied = tied || withheld === 1;
    // an untied refusal before the first tied one leaves P1 unrefused; P2 is never touched
    assert.equal(h.recordAt(0).cardCallRefused, tied, label);
    assert.equal(h.recordAt(1).cardCallRefused, false, label);
  }
  assert.equal(tied, true);
  assert.deepEqual(h.executions, []);
  for (const i of [0, 1]) {
    assert.equal(h.recordAt(i).cardToolCalled, false);
    assert.equal(h.recordAt(i).runBound, true);
  }
  // P2's own run with P1's key is refused too, and P1's run with P1's key still admits
  assert.equal((await h.host.callTool(b.run, "search_listings", { rewrite: cx({ sessionKey: S1 }) })).executed, false);
  assert.equal(h.host.decisions.at(-1).reason, "session-mismatch");
  assert.equal(P1run, a.turn.replyOptions.runId);
  await h.end(P1);
  // run ended: the runner settled, so P1's run id admits nothing
  assert.equal((await h.host.callTool(a.run, "search_listings")).executed, false);
  assert.equal(h.host.decisions.at(-1).reason, "run-ended");
  await h.end(P2);
  assert.equal(h.recordAt(0).cardToolCalled, false);

  // run unconfirmed: the host never called onAgentRunStart
  const u = await heldPlugin({ hostOpts: { confirmRun: false } });
  const ua = await u.begin(P1, "homes");
  assert.equal((await u.host.callTool(ua.run, "search_listings")).executed, false);
  assert.equal(u.host.decisions.at(-1).reason, "run-unconfirmed");
  await u.end(P1);

  // a host-minted follow-up id: onAgentRunStart reports another id, so the issued one stays
  // unconfirmed and the host's own id is unknown
  const f = await heldPlugin({ hostOpts: { runIdFor: () => "e2a1c3f0-0000-4000-8000-000000000001" } });
  const fa = await f.begin(P1, "homes");
  assert.notEqual(fa.run.runId, fa.turn.replyOptions.runId);
  assert.equal((await f.host.callTool(fa.run, "search_listings")).executed, false);
  assert.equal(f.host.decisions.at(-1).reason, "unknown-run");
  assert.equal((await f.host.callTool(fa.run, "search_listings", { rewrite: both(fa.turn.replyOptions.runId) })).executed, false);
  assert.equal(f.host.decisions.at(-1).reason, "run-unconfirmed");
  assert.equal(f.recordAt(0).runBound, false);
  await f.end(P1);

  // turn past the TTL while its run is still open
  const e = await heldPlugin({ ttlMs: 100 });
  const ea = await e.begin(P1, "homes");
  e.advance(101);
  assert.equal((await e.host.callTool(ea.run, "search_listings")).executed, false);
  assert.equal(e.host.decisions.at(-1).reason, "turn-expired");
  await e.end(P1);
  assert.deepEqual([...u.executions, ...f.executions, ...e.executions], []);
});

test("RB-4 (unconfirmed turn): when the host runs under another run id, even a greeting is withheld unbound-turn (SAFE_TEXT in safe-text mode, nothing in silent mode) and its card calls are refused", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode, hostOpts: { runIdFor: () => "e2a1c3f0-0000-4000-8000-000000000002" } });
    const a = await h.begin(P1, "hi");
    assert.equal(h.recordAt(0).runBound, false);
    const r = await a.turn.deliver({ text: "Hello! How can I help you find a home?" });
    if (withholdMode === "safe-text") {
      assert.deepEqual(r, { messageId: "fake-1", visibleReplySent: true, withheld: { reason: "idx-withheld:unbound-turn" } });
      assert.deepEqual(h.transport.sent.map((s) => s.text), [SAFE_TEXT]);
    } else {
      assert.deepEqual(r, { visibleReplySent: false, suppression: { reason: "idx-withheld:unbound-turn" } });
      assert.equal(h.transport.sent.length, 0);
    }
    assert.equal((await h.host.callTool(a.run, "search_listings")).executed, false, withholdMode);
    assert.equal(h.host.decisions.at(-1).reason, "unknown-run");
    assert.deepEqual(h.executions, []);
    await h.end(P1);
  }
});

test("RB-5 (run-start callback): onAgentRunStart returns undefined and never throws for any argument; only the issued id confirms, and a later wrong id does not unconfirm", async () => {
  const boom = () => { throw new Error("boom"); };
  const trap = new Proxy({}, { get: boom, has: boom, ownKeys: boom, getOwnPropertyDescriptor: boom });
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  let captured;
  const plugin = createChannelPlugin({
    transport,
    ingress,
    resolveRoute: ({ peer }) => ({ agentId: "idx", sessionKey: `agent:idx:whatsapp:direct:${peer.id}` }),
    runInbound: async (turn) => { captured = turn; },
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: P1, text: "hi", messageId: "m1", receivedAt: 1 });
  // the run has ended (the runner settled), so even the right id no longer confirms
  const start = captured.replyOptions.onAgentRunStart;
  assert.equal(start(captured.replyOptions.runId), undefined);
  assert.deepEqual(await captured.deliver({ text: "Hello!" }), { messageId: "fake-1", visibleReplySent: true, withheld: { reason: "idx-withheld:unbound-turn" } });
  assert.deepEqual(transport.sent.map((x) => x.text), [SAFE_TEXT]);
  // a live run: garbage first, then the right id, then wrong ids
  const transport2 = createFakeTransport();
  const ingress2 = createIngress({ now: () => 1 });
  const seen = [];
  const plugin2 = createChannelPlugin({
    transport: transport2,
    ingress: ingress2,
    resolveRoute: ({ peer }) => ({ agentId: "idx", sessionKey: `agent:idx:whatsapp:direct:${peer.id}` }),
    runInbound: async (turn) => {
      const cb = turn.replyOptions.onAgentRunStart;
      for (const arg of [undefined, null, 0, "", "reply-dispatch", turn.turnId, turn.replyOptions.runId.toUpperCase(), ` ${turn.replyOptions.runId}`, { toString: () => turn.replyOptions.runId }, [turn.replyOptions.runId], Symbol("x"), trap, () => turn.replyOptions.runId]) {
        let out = "unset";
        assert.doesNotThrow(() => { out = cb(arg, "token", { trap }); });
        seen.push(out);
      }
      seen.push(cb(turn.replyOptions.runId, "token", {}));
      seen.push(cb("other-id"));
      seen.push(cb(undefined));
      captured = turn;
    },
  });
  await plugin2.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport2.inbound({ accountId: "default", peerId: P1, text: "hi", messageId: "m1", receivedAt: 1 });
  assert.ok(seen.every((v) => v === undefined), JSON.stringify(seen.map(String)));
  assert.deepEqual(await captured.deliver({ text: "Hello!" }), { messageId: "fake-1", visibleReplySent: true });
});

test("RI-1 (isolation): dashboard card calls (webchat requester, a dashboard session with no requester, a forged WhatsApp requester with an unknown run id, P1's valid run id under the dashboard key) are refused and run nothing; P1 and P2 are unchanged, their greetings release, and P1's own card call is still admitted", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes");
    const b = await h.begin(P2, "hello");
    const calls = [
      ["a", { sessionKey: "agent:idx:main", requester: { channel: "webchat", accountId: "default", senderId: "dashboard-user", senderIsOwner: true, roleIds: [] } }, "unknown-run"],
      ["b", { sessionKey: "agent:idx:dashboard:7d3c2b1a-0000-4000-8000-000000000003" }, "unknown-run"],
      ["c", { sessionKey: "agent:idx:main", requester: { channel: "whatsapp", accountId: "default", senderId: P1 } }, "unknown-run"],
      ["d", { sessionKey: "agent:idx:main", runId: a.run.runId }, "session-mismatch"],
    ];
    for (const [label, opts, reason] of calls) {
      const r = await h.host.dashboardToolCall("idx__search_listings", opts);
      assert.equal(r.executed, false, `${withholdMode} ${label}`);
      const d = h.host.decisions.at(-1);
      assert.equal(d.block, true, label);
      assert.equal(typeof d.blockReason, "string");
      assert.ok(d.blockReason.length > 0);
      assert.equal(d.reason, reason, label);
    }
    assert.deepEqual(h.executions, [], withholdMode);
    for (const i of [0, 1]) assert.deepEqual([h.recordAt(i).cardToolCalled, h.recordAt(i).runBound], [false, true], `${withholdMode} ${i}`);
    assert.deepEqual(await a.turn.deliver({ text: "Hi! How can I help?" }), { messageId: "fake-1", visibleReplySent: true });
    assert.deepEqual(await b.turn.deliver({ text: "Hello there!" }), { messageId: "fake-2", visibleReplySent: true });
    // P1's own card call is still admitted and its token reply releases
    assert.equal((await h.host.callTool(a.run, "search_listings")).executed, true);
    h.resolver.store(S1, a.turn.turnId, "c1", CARD);
    assert.deepEqual(await a.turn.deliver({ text: "[[card:c1]]" }), { messageId: "fake-3", visibleReplySent: true });
    assert.equal(h.recordAt(1).cardToolCalled, false);
    assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, "Hi! How can I help?"], [P2, "Hello there!"], [P1, CARD]]);
    await h.end(P1);
    await h.end(P2);
  }
});

test("RI-2 (HOST-LEVEL TEST REQUIRED AT INSTALL, owner decision 19 (a)): a call reusing P1's valid run id AND P1's session key while P1's run is active is indistinguishable offline and IS admitted (marks P1); once P1's run ends the same reuse is refused run-ended. The install PR must prove on the real host (lane serialization, no steering or follow-up into the run) that a dashboard request cannot carry both", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes");
    const b = await h.begin(P2, "hello");
    // pinned: the offline handler cannot tell this from P1's own MCP call
    const reuse = await h.host.dashboardToolCall("search_listings", { sessionKey: S1, runId: a.run.runId });
    assert.equal(reuse.executed, true, withholdMode);
    assert.deepEqual(h.host.decisions.at(-1), { block: false, marked: 1 }, withholdMode);
    assert.equal(h.recordAt(0).cardToolCalled, true, withholdMode);
    assert.deepEqual([h.recordAt(1).cardToolCalled, h.recordAt(1).runBound], [false, true], withholdMode);
    assert.deepEqual(await b.turn.deliver({ text: "Hello there!" }), { messageId: "fake-1", visibleReplySent: true }, withholdMode);
    await h.end(P1);
    const late = await h.host.dashboardToolCall("search_listings", { sessionKey: S1, runId: a.run.runId });
    assert.equal(late.executed, false, withholdMode);
    assert.equal(h.host.decisions.at(-1).reason, "run-ended", withholdMode);
    assert.equal(h.executions.length, 1, withholdMode);
    await h.end(P2);
  }
});

test("RI-3 (isolation): a non-card tool from the dashboard is allowed and changes nothing; P1 and P2 stay ordinary bound turns and their greetings release, in both modes", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes");
    const b = await h.begin(P2, "hello");
    for (const opts of [{ sessionKey: "agent:idx:main", requester: { channel: "webchat" } }, { sessionKey: "agent:idx:dashboard:7d3c2b1a-0000-4000-8000-000000000004" }]) {
      const r = await h.host.dashboardToolCall("idx__get_listing_details", opts);
      assert.equal(r.executed, true, withholdMode);
      assert.deepEqual(h.host.decisions.at(-1), { block: false, marked: 0 }, withholdMode);
    }
    for (const i of [0, 1]) assert.deepEqual([h.recordAt(i).cardToolCalled, h.recordAt(i).runBound], [false, true], `${withholdMode} ${i}`);
    assert.deepEqual(await a.turn.deliver({ text: "Hi! How can I help?" }), { messageId: "fake-1", visibleReplySent: true }, withholdMode);
    assert.deepEqual(await b.turn.deliver({ text: "Hello there!" }), { messageId: "fake-2", visibleReplySent: true }, withholdMode);
    assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, "Hi! How can I help?"], [P2, "Hello there!"]], withholdMode);
    await h.end(P1);
    await h.end(P2);
  }
});

test("RS-1 (release support, gate): a resolvable card token on a bound turn with no admitted card call is withheld card-without-trusted-call in both modes", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const resolver = createInMemoryCardResolver();
    const g = gate({ cardResolver: resolver, withholdMode }, "show me");
    resolver.store(SESSION, "t1", "c1", CARD);
    const r = await g.outbound.sendText({ to: PEER, text: "[[card:c1]]", accountId: "default", turn: g.handle });
    if (withholdMode === "safe-text") {
      assert.deepEqual(r, { messageId: "fake-1", withheld: "card-without-trusted-call" });
      assert.deepEqual(g.transport.sent.map((s) => s.text), [SAFE_TEXT]);
    } else {
      assert.deepEqual(r, { outcome: "not_sent", reason: "card-without-trusted-call" });
      assert.equal(g.transport.sent.length, 0);
    }
    // once a card call is admitted on the turn's own run the same token releases
    g.markCard();
    assert.equal(typeof (await g.outbound.sendText({ to: PEER, text: "[[card:c1]]", accountId: "default", turn: g.handle })).messageId, "string");
    assert.equal(g.transport.sent.at(-1).text, CARD);
  }
  // the self-check pins it: a verifier that ignores cardToolCalled for tokens fails the self-test
  const ignoresSupport = ({ text, inbound, resolver }) => verifyReply({ text, inbound: inbound && typeof inbound === "object" ? { ...inbound, cardToolCalled: true } : inbound, resolver });
  assert.equal(verifierSelfTest(ignoresSupport), false);
  const ignoresBinding = ({ text, inbound, resolver }) => verifyReply({ text, inbound: inbound && typeof inbound === "object" ? { ...inbound, runBound: true } : inbound, resolver });
  assert.equal(verifierSelfTest(ignoresBinding), false);
  assert.equal(verifierSelfTest(verifyReply), true);
});

test("RA-1 (busy): while P1's turn is active, P1's second message gets exactly BUSY_TEXT through the transport, is not recorded and does not reach the host; after P1's run ends the next message is admitted", HELD, async () => {
  const h = await heldPlugin();
  const a = await h.begin(P1, "homes in pasadena");
  assert.equal(h.handles.length, 1);
  await h.transport.inbound({ accountId: "default", peerId: "whatsapp:+1 555 000 0001", text: "are you there? 42", messageId: "m2", receivedAt: 2 });
  assert.equal(h.handles.length, 1, "the overlapping message is not recorded");
  assert.equal(h.host.turns.length, 1, "runInbound not called again");
  assert.deepEqual(h.transport.sent, [{ accountId: "default", to: P1, text: constants.BUSY_TEXT }]);
  // the audit line says busy and carries no text, peer, session key or run id
  const busy = h.lines.filter((l) => l.outcome === "busy");
  assert.equal(busy.length, 1);
  const blob = JSON.stringify(h.lines);
  for (const forbidden of ["are you there", "5550000", S1, a.turn.replyOptions.runId, constants.BUSY_TEXT]) assert.ok(!blob.includes(forbidden), forbidden);
  // the active turn itself is untouched
  assert.deepEqual(await a.turn.deliver({ text: "Which area?" }), { messageId: "fake-2", visibleReplySent: true });
  await h.end(P1);
  const next = await h.begin(P1, "thanks");
  assert.equal(h.handles.length, 2);
  assert.equal(h.host.turns.length, 2);
  assert.deepEqual(await next.turn.deliver({ text: "You're welcome!" }), { messageId: "fake-3", visibleReplySent: true });
  await h.end(P1);
});

test("RA-2 (busy is per peer): P2's message during P1's active turn is admitted and dispatched", HELD, async () => {
  const h = await heldPlugin();
  await h.begin(P1, "homes");
  const b = await h.begin(P2, "hello");
  assert.equal(h.host.turns.length, 2);
  assert.equal(b.turn.peerId, P2);
  assert.deepEqual(await b.turn.deliver({ text: "Hello there!" }), { messageId: "fake-1", visibleReplySent: true });
  assert.ok(!h.transport.sent.some((s) => s.text === constants.BUSY_TEXT));
  await h.end(P1);
  await h.end(P2);
});

test("RA-3 (busy backstops): a runner that rejects still ends the run, so the next message is admitted; an active turn past the TTL no longer blocks", HELD, async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  let calls = 0;
  const plugin = createChannelPlugin({
    transport,
    ingress,
    resolveRoute: ({ peer }) => ({ agentId: "idx", sessionKey: `agent:idx:whatsapp:direct:${peer.id}` }),
    runInbound: async (turn) => {
      calls += 1;
      confirm(turn);
      if (calls === 1) throw new Error("agent run failed");
      await turn.deliver({ text: "Hello again!" });
    },
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await assert.rejects(transport.inbound({ accountId: "default", peerId: P1, text: "hi", messageId: "m1", receivedAt: 1 }), /agent run failed/);
  await transport.inbound({ accountId: "default", peerId: P1, text: "hi again", messageId: "m2", receivedAt: 2 });
  assert.equal(calls, 2);
  assert.deepEqual(transport.sent.map((s) => s.text), ["Hello again!"]);
  // a run that never settles: the TTL ends the active turn
  const h = await heldPlugin({ ttlMs: 100 });
  await h.begin(P1, "homes");
  await h.transport.inbound({ accountId: "default", peerId: P1, text: "still there?", messageId: "m2", receivedAt: 2 });
  assert.deepEqual(h.transport.sent.map((s) => s.text), [constants.BUSY_TEXT]);
  h.advance(101);
  const late = h.transport.inbound({ accountId: "default", peerId: P1, text: "hello?", messageId: "m3", receivedAt: 3 });
  await flush();
  assert.equal(h.host.turns.length, 2);
  assert.equal(h.handles.length, 2);
  await h.end(P1);
  await late;
});

test("RA-4 (busy text): BUSY_TEXT is digit-free, differs from SAFE_TEXT, is sent in both modes, and the host-facing outbound exposes no busy method", HELD, async () => {
  const BUSY = constants.BUSY_TEXT;
  assert.equal(typeof BUSY, "string");
  assert.ok(BUSY.trim().length > 0 && BUSY.length <= 200);
  assert.equal(/\p{N}/u.test(BUSY), false);
  assert.notEqual(BUSY, SAFE_TEXT);
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    await h.begin(P1, "homes");
    await h.transport.inbound({ accountId: "default", peerId: P1, text: "again", messageId: "m2", receivedAt: 2 });
    assert.deepEqual(h.transport.sent.map((s) => s.text), [BUSY], withholdMode);
    assert.deepEqual(Object.keys(h.plugin.outbound).sort(), ["deliveryMode", "normalizePayload", "sendText", "textChunkLimit"], withholdMode);
    for (const n of memberNames(h.plugin.outbound)) assert.doesNotMatch(n, /busy/i);
    for (const n of Object.keys(h.plugin)) assert.doesNotMatch(n, /busy/i);
    await h.end(P1);
  }
  // a host-facing send of the busy text is an ordinary handle-less send: withheld
  const plugin = createChannelPlugin({ transport: createFakeTransport() });
  assert.deepEqual(await plugin.outbound.sendText({ to: P1, text: BUSY, accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
});

test("RA-5 (busy, same tick): two inbounds from one peer started before either is awaited admit exactly one turn; the other gets BUSY_TEXT and never reaches the host", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const first = h.transport.inbound({ accountId: "default", peerId: P1, text: "homes", messageId: "m1", receivedAt: 1 });
    const second = h.transport.inbound({ accountId: "default", peerId: "whatsapp:+1 555 000 0001", text: "also condos", messageId: "m2", receivedAt: 1 });
    // not awaited before asserting: a second admitted run would be held open, and the test
    // must fail on the assertions below rather than on a timeout
    await flush();
    assert.equal(h.host.turns.length, 1, `${withholdMode}: runInbound called once`);
    assert.equal(h.handles.length, 1, `${withholdMode}: one turn recorded`);
    assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, constants.BUSY_TEXT]], withholdMode);
    await h.end(P1);
    await Promise.all([first, second]);
  }
});

test("RA-6 (busy survives eviction): a peer whose records are evicted for capacity while its run is open still gets BUSY_TEXT and no second run until that run ends", HELD, async () => {
  const P3 = "+15550000003";
  const h = await heldPlugin({ maxEntries: 2 });
  const a = await h.begin(P1, "homes");
  await h.begin(P2, "hello");
  await h.begin(P3, "hi");
  assert.equal(h.real.size(), 2, "P1's records were evicted for capacity");
  assert.equal(h.recordAt(0), null, "P1's turn is no longer stored");
  // not awaited before asserting (a wrongly admitted run would be held open)
  const overlap = h.transport.inbound({ accountId: "default", peerId: P1, text: "are you there?", messageId: "m2", receivedAt: 2 });
  await flush();
  assert.equal(h.host.turns.length, 3, "runInbound not called for P1 again while its run is open");
  assert.equal(h.handles.length, 3, "the overlapping message is not recorded");
  assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, constants.BUSY_TEXT]]);
  // the evicted turn fails closed meanwhile: its card calls are refused and its reply is untrusted
  assert.equal((await h.host.callTool(a.run, "search_listings")).executed, false);
  assert.equal((await a.turn.deliver({ text: "Which area?" })).visibleReplySent, false);
  assert.equal(h.transport.sent.length, 1);
  await h.end(P1);
  await overlap;
  const next = await h.begin(P1, "thanks");
  assert.equal(h.host.turns.length, 4);
  assert.deepEqual(await next.turn.deliver({ text: "You're welcome!" }), { messageId: "fake-2", visibleReplySent: true });
  await h.end(P1);
  await h.end(P2);
  await h.end(P3);
});

// ---- Owner decision 21 (2026-11-07, revision 7): a refused card call tied to its own turn withholds that turn ----

const OTHER_SENDER = "+15550000009";
const BUDGET_INBOUND = "My budget is 650000 for a 3 bed in Irvine";
const BUDGET_CLAIM = "Good news: a 3 bed in Irvine is listed at 650000.";
const SPELLED_CLAIM = "I found a three-bedroom home on Maple Street listed at six hundred fifty thousand dollars.";
/** A WhatsApp requester naming a different 555 sender than the turn's peer. */
const otherRequester = (senderId = OTHER_SENDER) => ({ channel: "whatsapp", accountId: "default", senderId });
const TIED = { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "requester-mismatch", withheld: 1 };

/** Asserts a deliver result and the transport for a withheld reply in the given mode. */
function assertWithheld(withholdMode, result, transport, reason, label) {
  if (withholdMode === "safe-text") {
    assert.deepEqual(result, { messageId: `fake-${transport.sent.length}`, visibleReplySent: true, withheld: { reason: `idx-withheld:${reason}` } }, label);
    assert.equal(transport.sent.at(-1).text, SAFE_TEXT, label);
  } else {
    assert.deepEqual(result, { visibleReplySent: false, suppression: { reason: `idx-withheld:${reason}` } }, label);
  }
}

/** A plugin whose host runs one inbound to completion, with the hook wired and a counted tool. */
async function tiedPlugin({ withholdMode, replies, tools } = {}) {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  let executed = 0;
  const host = createFakeHost({
    hook: channelModule.createBeforeToolCallHandler(ingress),
    tools: tools ?? (() => { executed += 1; return { listings: 1 }; }),
    replies,
  });
  const plugin = createChannelPlugin({ transport, ingress, withholdMode, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  const say = (text) => transport.inbound({ accountId: "default", peerId: PEER, text, messageId: "m1", receivedAt: 1 });
  return { transport, ingress, host, say, executed: () => executed };
}

test("RW-1 (buyer budget reused as a listing price): the turn's own idx__search_listings call is refused tied (another 555 sender, same run id and key), so the reply quoting the budget as a price never reaches the transport; SAFE_TEXT once in safe-text mode, nothing in silent mode; the tool never ran", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await tiedPlugin({
      withholdMode,
      replies: () => ({ tool: "idx__search_listings", requester: otherRequester(), reply: ({ blocked }) => (blocked ? BUDGET_CLAIM : "unexpected success") }),
    });
    await h.say(BUDGET_INBOUND);
    assert.deepEqual(h.host.decisions, [TIED], withholdMode);
    assert.deepEqual(h.host.events, ["before-tool-call:idx__search_listings", "tool-blocked:requester-mismatch"], withholdMode);
    assert.equal(h.executed(), 0, withholdMode);
    assert.equal(h.host.results.length, 1, withholdMode);
    if (withholdMode === "safe-text") {
      assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[PEER, SAFE_TEXT]]);
      assert.deepEqual(h.host.results[0], { messageId: "fake-1", visibleReplySent: true, withheld: { reason: "idx-withheld:card-call-refused" } });
    } else {
      assert.equal(h.transport.sent.length, 0);
      assert.deepEqual(h.host.results[0], { visibleReplySent: false, suppression: { reason: "idx-withheld:card-call-refused" } });
    }
    assert.ok(!h.transport.sent.some((s) => s.text.includes("650000")), withholdMode);
  }
});

test("RW-1b (control, known limit): the same budget-as-price reply on an ordinary turn with no card call releases under R3, because an ordinary turn carries no card evidence", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await tiedPlugin({ withholdMode, replies: () => BUDGET_CLAIM });
    await h.say(BUDGET_INBOUND);
    assert.deepEqual(h.host.decisions, [], withholdMode);
    assert.deepEqual(h.transport.sent.map((s) => s.text), [BUDGET_CLAIM], withholdMode);
    assert.deepEqual(h.host.results, [{ messageId: "fake-1", visibleReplySent: true }], withholdMode);
  }
});

test("RW-1c (control, unknown origin): a dashboard-style card call carrying this turn's session key with no run id, or with a foreign run id (even with a mismatching WhatsApp requester), is refused withheld 0 and the turn's reply still releases: refuse only the call", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, BUDGET_INBOUND);
    const calls = [
      ["no run id", { sessionKey: S1, noRunId: true }],
      ["no run id, mismatching requester", { sessionKey: S1, noRunId: true, requester: otherRequester() }],
      ["foreign run id", { sessionKey: S1 }],
      ["foreign run id, mismatching requester", { sessionKey: S1, requester: otherRequester() }],
    ];
    for (const [label, opts] of calls) {
      const r = await h.host.dashboardToolCall("idx__search_listings", opts);
      assert.equal(r.executed, false, `${withholdMode} ${label}`);
      assert.deepEqual(h.host.decisions.at(-1), { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, reason: "unknown-run", withheld: 0 }, `${withholdMode} ${label}`);
      assert.equal(h.recordAt(0).cardCallRefused, false, `${withholdMode} ${label}`);
    }
    assert.deepEqual(h.executions, []);
    assert.deepEqual(await a.turn.deliver({ text: BUDGET_CLAIM }), { messageId: "fake-1", visibleReplySent: true }, withholdMode);
    assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), [[P1, BUDGET_CLAIM]], withholdMode);
    await h.end(P1);
  }
});

test("RW-1d (control, admitted card call): on a turn whose card call was admitted the same budget-as-price prose is withheld card-turn-requires-tokens", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await tiedPlugin({ withholdMode, replies: () => ({ tool: "idx__search_listings", reply: ({ result }) => (result ? BUDGET_CLAIM : "unexpected block") }) });
    await h.say(BUDGET_INBOUND);
    assert.deepEqual(h.host.decisions, [{ block: false, marked: 1 }], withholdMode);
    assert.equal(h.executed(), 1, withholdMode);
    assertWithheld(withholdMode, h.host.results[0], h.transport, "card-turn-requires-tokens", withholdMode);
    assert.ok(!h.transport.sent.some((s) => s.text === BUDGET_CLAIM), withholdMode);
  }
});

test("RW-2 (spelled-out listing claim): after a tied refusal the number-word listing claim is withheld card-call-refused in both modes; on an ordinary turn the same text releases no-figures (known limit, item 5)", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await tiedPlugin({
      withholdMode,
      replies: () => ({ tool: "search_listings", requester: otherRequester(), reply: () => SPELLED_CLAIM }),
    });
    await h.say("any 3 bed homes on Maple Street?");
    assert.deepEqual(h.host.decisions, [TIED], withholdMode);
    assert.equal(h.executed(), 0, withholdMode);
    assertWithheld(withholdMode, h.host.results[0], h.transport, "card-call-refused", withholdMode);
    assert.equal(h.transport.sent.length, withholdMode === "safe-text" ? 1 : 0, withholdMode);
    assert.ok(!h.transport.sent.some((s) => s.text === SPELLED_CLAIM), withholdMode);
    // known limit, pinned: an ordinary turn releases it, number words are not figures
    const o = await tiedPlugin({ withholdMode, replies: () => SPELLED_CLAIM });
    await o.say("any 3 bed homes on Maple Street?");
    assert.deepEqual(o.transport.sent.map((s) => s.text), [SPELLED_CLAIM], withholdMode);
  }
});

test("RW-3 (an unrelated WhatsApp reply still delivers): with P1 and P2 both open, P1's tied refusal withholds P1's reply only; P2's clarification echoing its own figures is released unchanged, dashboard-style calls carrying P2's key (no run id, foreign run id) leave P2 untouched, and P2's own admitted card call still releases its card", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes in irvine?");
    const b = await h.begin(P2, "is 3 or 4 bedrooms better under 900000?");
    // P1's own run id and key, with a requester naming P2: tied to P1's turn
    const r1 = await h.host.callTool(a.run, "idx__search_listings", { requester: otherRequester(P2) });
    assert.equal(r1.executed, false, withholdMode);
    assert.deepEqual(h.host.decisions.at(-1), TIED, withholdMode);
    assert.deepEqual([h.recordAt(0).cardCallRefused, h.recordAt(1).cardCallRefused], [true, false], withholdMode);
    // dashboard-style calls naming P2's key but no P2 run tie nothing
    for (const opts of [{ sessionKey: S2, noRunId: true }, { sessionKey: S2 }, { sessionKey: S2, requester: otherRequester() }]) {
      assert.equal((await h.host.dashboardToolCall("search_listings", opts)).executed, false, withholdMode);
      assert.equal(h.host.decisions.at(-1).withheld, 0, withholdMode);
    }
    assert.deepEqual([h.recordAt(1).cardCallRefused, h.recordAt(1).cardToolCalled, h.recordAt(1).runBound], [false, false, true], withholdMode);
    const p1 = await a.turn.deliver({ text: "Hi! Let me check on that." });
    assertWithheld(withholdMode, p1, h.transport, "card-call-refused", withholdMode);
    const clar = "Do you mean 3 or 4 bedrooms under 900000?";
    assert.equal((await b.turn.deliver({ text: clar })).visibleReplySent, true, withholdMode);
    assert.equal(h.transport.sent.at(-1).text, clar);
    assert.equal(h.transport.sent.at(-1).to, P2);
    // P2's own card call is admitted after P1's taint and its token releases the card
    assert.equal((await h.host.callTool(b.run, "search_listings")).executed, true, withholdMode);
    h.resolver.store(S2, b.turn.turnId, "c2", CARD);
    assert.equal((await b.turn.deliver({ text: "[[card:c2]]" })).visibleReplySent, true, withholdMode);
    const expected = [...(withholdMode === "safe-text" ? [[P1, SAFE_TEXT]] : []), [P2, clar], [P2, CARD]];
    assert.deepEqual(h.transport.sent.map((s) => [s.to, s.text]), expected, withholdMode);
    assert.equal(h.recordAt(1).cardCallRefused, false, withholdMode);
    await h.end(P1);
    await h.end(P2);
  }
});

test("RW-4 (characterization: no recall): a reply block delivered before the tied refusal was released and stays out; a block delivered after it is withheld card-call-refused", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes in irvine?");
    const early = "Let me look that up for you.";
    assert.deepEqual(await a.turn.deliver({ text: early }), { messageId: "fake-1", visibleReplySent: true }, withholdMode);
    assert.deepEqual((await h.host.callTool(a.run, "search_listings", { requester: otherRequester() })).executed, false);
    assert.deepEqual(h.host.decisions.at(-1), TIED, withholdMode);
    const late = await a.turn.deliver({ text: "Here is what I found." });
    assertWithheld(withholdMode, late, h.transport, "card-call-refused", withholdMode);
    assert.deepEqual(h.transport.sent.map((s) => s.text), withholdMode === "safe-text" ? [early, SAFE_TEXT] : [early], withholdMode);
    await h.end(P1);
  }
});

test("RW-units (ingress): every untied refusal reason leaves every stored turn's cardCallRefused false and answers no withheld key; a tied refusal marks that entry only; a throwing or non-function requester check is tied; the flag is monotonic, frozen in snapshots and not inherited", () => {
  let t = 0;
  const ing = createIngress({ now: () => t, ttlMs: 100 });
  const S2k = "agent:idx:whatsapp:direct:+15550000002";
  const a = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "a", text: "hi" });
  const b = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "b", text: "more" });
  const c = recordBoundTurn(ing, { peerId: "+15550000002", sessionKey: S2k, turnId: "c", text: "hello" });
  const u = recordBoundTurn(ing, { peerId: "+15550000003", sessionKey: "agent:idx:whatsapp:direct:+15550000003", turnId: "u", text: "hey", confirm: false });
  const e = recordBoundTurn(ing, { peerId: "+15550000004", sessionKey: "agent:idx:whatsapp:direct:+15550000004", turnId: "e", text: "yo" });
  ing.endRun(e.handle);
  const turns = [a, b, c, u, e];
  const flags = () => turns.map((x) => ing.forTurn(x.handle.key, x.handle)?.cardCallRefused);
  const no = () => false;
  const untied = [
    ["no run id", { runId: undefined, sessionKey: SESSION, requesterMatches: no }, "unknown-run"],
    ["foreign run id", { runId: "4f1c0000-0000-4000-8000-000000000009", sessionKey: SESSION, requesterMatches: no }, "unknown-run"],
    ["run unconfirmed", { runId: u.runId, sessionKey: u.sessionKey, requesterMatches: no }, "run-unconfirmed"],
    ["run ended", { runId: e.runId, sessionKey: e.sessionKey, requesterMatches: no }, "run-ended"],
    ["session key of the other peer", { runId: b.runId, sessionKey: S2k, requesterMatches: no }, "session-mismatch"],
    ["session key missing", { runId: b.runId, sessionKey: undefined, requesterMatches: no }, "session-mismatch"],
  ];
  for (const [label, call, reason] of untied) {
    assert.deepEqual(ing.admitCardCall({ toolName: "search_listings", ...call }), { admitted: false, reason }, label);
    assert.deepEqual(flags(), [false, false, false, false, false], label);
  }
  // tied: b's own run id and key, requester check false -> b only
  assert.deepEqual(ing.admitCardCall({ runId: b.runId, sessionKey: SESSION, toolName: "search_listings", requesterMatches: no }), { admitted: false, reason: "requester-mismatch", withheld: true });
  assert.deepEqual(flags(), [false, true, false, false, false]);
  assert.equal(ing.forTurn(b.handle.key, b.handle).cardToolCalled, false);
  // a requester check that throws, or is not a function, is tied too
  assert.deepEqual(ing.admitCardCall({ runId: c.runId, sessionKey: S2k, toolName: "recommend", requesterMatches: () => { throw new Error("boom"); } }), { admitted: false, reason: "requester-mismatch", withheld: true });
  assert.deepEqual(flags(), [false, true, true, false, false]);
  assert.deepEqual(ing.admitCardCall({ runId: a.runId, sessionKey: SESSION, toolName: "recommend", requesterMatches: 7 }), { admitted: false, reason: "requester-mismatch", withheld: true });
  assert.deepEqual(flags(), [true, true, true, false, false]);
  // monotonic: a later admitted call marks the card turn but does not clear the refusal
  assert.deepEqual(ing.admitCardCall({ runId: b.runId, sessionKey: SESSION, toolName: "search_listings" }), { admitted: true });
  const snap = ing.forTurn(b.handle.key, b.handle);
  assert.deepEqual([snap.cardToolCalled, snap.cardCallRefused], [true, true]);
  assert.throws(() => { "use strict"; snap.cardCallRefused = false; });
  assert.equal(ing.forTurn(b.handle.key, b.handle).cardCallRefused, true);
  for (const n of memberNames(ing)) assert.doesNotMatch(n, /clear|unrefuse|unwithhold|reset|untaint/i);
  // a turn past the TTL: refused turn-expired, untied (its record is no longer readable either)
  const fresh = createIngress({ now: () => t, ttlMs: 100 });
  const x = recordBoundTurn(fresh, { peerId: PEER, sessionKey: SESSION, turnId: "x", text: "hi" });
  const y = recordBoundTurn(fresh, { peerId: "+15550000002", sessionKey: S2k, turnId: "y", text: "hi" });
  t = 101;
  assert.deepEqual(fresh.admitCardCall({ runId: x.runId, sessionKey: SESSION, toolName: "search_listings", requesterMatches: no }), { admitted: false, reason: "turn-expired" });
  t = 0;
  assert.deepEqual([fresh.forTurn(x.handle.key, x.handle).cardCallRefused, fresh.forTurn(y.handle.key, y.handle).cardCallRefused], [false, false]);
  // not inherited: the peer's next turn starts false
  t = 0;
  const next = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, turnId: "n", text: "thanks" });
  assert.equal(ing.forTurn(next.handle.key, next.handle).cardCallRefused, false);
  assert.equal(ing.forTurn(b.handle.key, b.handle).cardCallRefused, true);
});

test("RW-units (gate): on a refused turn a resolving card token after a later admitted call is withheld card-call-refused in both modes, and the peer's next turn releases its greeting", async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const resolver = createInMemoryCardResolver();
    const g = gate({ cardResolver: resolver, withholdMode }, "show me");
    assert.equal(g.ingress.admitCardCall({ runId: g.runId, sessionKey: SESSION, toolName: "search_listings", requesterMatches: () => false }).withheld, true);
    g.markCard();
    resolver.store(SESSION, "t1", "c1", CARD);
    const r = await g.outbound.sendText({ to: PEER, text: "[[card:c1]]", accountId: "default", turn: g.handle });
    if (withholdMode === "safe-text") assert.deepEqual(r, { messageId: "fake-1", withheld: "card-call-refused" });
    else assert.deepEqual(r, { outcome: "not_sent", reason: "card-call-refused" });
    assert.ok(!g.transport.sent.some((s) => s.text === CARD));
    const next = recordBoundTurn(g.ingress, { peerId: PEER, sessionKey: SESSION, turnId: "t2", text: "thanks" });
    assert.equal(typeof (await g.outbound.sendText({ to: PEER, text: "You're welcome!", accountId: "default", turn: next.handle })).messageId, "string");
    assert.equal(g.transport.sent.at(-1).text, "You're welcome!");
  }
});

test("RW-units (handler): withheld is 1 only when the ingress answers withheld === true; handler-side unknown-run (run id missing, event and ctx disagree) and handler-error are withheld 0 and change no turn, even with the turn's own session key and a mismatching requester", () => {
  const ing = createIngress({ now: () => 1 });
  const t = recordBoundTurn(ing, { peerId: PEER, sessionKey: SESSION, text: "hi" });
  const handler = channelModule.createBeforeToolCallHandler(ing);
  const req = otherRequester();
  const read = () => ing.forTurn(t.handle.key, t.handle);
  const base = { block: true, blockReason: constants.CARD_TOOL_BLOCK_REASON, withheld: 0 };
  assert.deepEqual(handler({ toolName: "search_listings" }, { sessionKey: SESSION, requester: req }), { ...base, reason: "unknown-run" });
  assert.deepEqual(handler({ toolName: "search_listings", runId: t.runId }, { sessionKey: SESSION, requester: req }), { ...base, reason: "unknown-run" });
  assert.deepEqual(handler({ toolName: "search_listings" }, { sessionKey: SESSION, runId: t.runId, requester: req }), { ...base, reason: "unknown-run" });
  assert.deepEqual(handler({ toolName: "search_listings", runId: t.runId }, { sessionKey: SESSION, runId: t.runId, requester: { channel: "whatsapp", get senderId() { throw new Error("boom"); } } }), { ...base, reason: "handler-error" });
  assert.equal(read().cardCallRefused, false);
  // a wrapped ingress: only the strict boolean true reports withheld 1
  for (const [answer, withheld] of [[{ admitted: false, reason: "requester-mismatch", withheld: "yes" }, 0], [{ admitted: false, reason: "requester-mismatch", withheld: 1 }, 0], [{ admitted: false, reason: "requester-mismatch" }, 0], [{ admitted: false, reason: "requester-mismatch", withheld: true }, 1]]) {
    const w = wrapIngress(ing, { admitCardCall: () => answer });
    assert.equal(channelModule.createBeforeToolCallHandler(w.wrapped)({ toolName: "search_listings", runId: t.runId }, { sessionKey: SESSION, runId: t.runId }).withheld, withheld, JSON.stringify(answer));
  }
  assert.equal(read().cardCallRefused, false);
  // the real tied path
  assert.deepEqual(handler({ toolName: "search_listings", runId: t.runId }, { sessionKey: SESSION, runId: t.runId, requester: req }), TIED);
  assert.equal(read().cardCallRefused, true);
  assert.equal(read().cardToolCalled, false);
});

test("RI-4 (HOST-LEVEL TEST REQUIRED AT INSTALL, owner decision 21): offline, a call reusing P1's live run id AND session key with a requester naming another sender is tied to P1 and withholds P1's reply. The install gate must show the real host refuses such a dashboard call AND does not withhold P1's reply; if the host admits it, the install uses a tool path that verifies the originating turn and peer", HELD, async () => {
  for (const withholdMode of ["safe-text", "silent"]) {
    const h = await heldPlugin({ withholdMode });
    const a = await h.begin(P1, "homes");
    const b = await h.begin(P2, "hello");
    const r = await h.host.dashboardToolCall("search_listings", { sessionKey: S1, runId: a.run.runId, requester: { channel: "webchat", accountId: "default", senderId: "dashboard-user" } });
    assert.equal(r.executed, false, withholdMode);
    assert.deepEqual(h.host.decisions.at(-1), TIED, withholdMode);
    assert.equal(h.recordAt(0).cardCallRefused, true, withholdMode);
    assert.equal(h.recordAt(1).cardCallRefused, false, withholdMode);
    assertWithheld(withholdMode, await a.turn.deliver({ text: "Hi! How can I help?" }), h.transport, "card-call-refused", withholdMode);
    assert.equal((await b.turn.deliver({ text: "Hello there!" })).visibleReplySent, true, withholdMode);
    await h.end(P1);
    await h.end(P2);
  }
});

test("RW-units (self-check): the refused-turn vectors are present, and a verifier that ignores cardCallRefused, or accepts a record without it, fails the self-test and blocks registration", () => {
  const refused = SELF_TEST_VECTORS.filter((v) => v.inbound && v.inbound.cardCallRefused === true);
  assert.ok(refused.length >= 3);
  assert.ok(refused.every((v) => v.expect === "withhold"));
  assert.ok(SELF_TEST_VECTORS.some((v) => v.inbound && typeof v.inbound === "object" && !("cardCallRefused" in v.inbound) && v.expect === "withhold"));
  const ignoresRefusal = ({ text, inbound, resolver }) => verifyReply({ text, inbound: inbound && typeof inbound === "object" ? { ...inbound, cardCallRefused: false } : inbound, resolver });
  assert.equal(verifierSelfTest(ignoresRefusal), false);
  assert.deepEqual(selfCheck(DENY_CFG, { verify: ignoresRefusal }), { ok: false, reason: "verifier-self-test-failed" });
  // a verifier that withholds only greetings on a refused turn still fails on the budget echo
  const greetingsOnly = (input) => (input.inbound?.cardCallRefused === true && !/\p{N}/u.test(input.text) ? { kind: "withhold", reason: "x" } : ignoresRefusal(input));
  assert.equal(verifierSelfTest(greetingsOnly), false);
  assert.equal(verifierSelfTest(verifyReply), true);
});
