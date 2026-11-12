// WO-038 lifecycle fix (owner instruction 2026-11-08): a stopped transport sends nothing,
// and a turn opened before a stop or a reload can never send again, even when its reply
// arrives after the account has started anew. Fakes only: an injected fetch, synthetic 555
// peers and made-up ids. Nothing here reaches a network.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import { createCloudApiTransport } from "./cloud-api-transport.mjs";
import { createBeforeToolCallHandler, createChannelPlugin } from "./channel.mjs";
import { createIngress } from "./ingress.mjs";
import { processIngress } from "./index.mjs";
import { createFakeTransport } from "./test-support/fake-transport.mjs";
import { createFakeHost, recordBoundTurn } from "./test-support/host-emulation.mjs";

// Synthetic values of plausible shape. None is a real credential, id or number.
const CONFIG = Object.freeze({
  phoneNumberId: "1000000000001",
  graphApiVersion: "v99.9",
  accessToken: "TEST-ACCESS-TOKEN-not-a-real-token-0000000000",
  appSecret: "testappsecretnotreal000000000000",
  verifyToken: "test-verify-token-not-real",
  webhookPath: "/idx-whatsapp/cloud-api/webhook",
});
const WA_ID = "15550000001";
const PEER = "+15550000001";
const PEER_2 = "+15550000002";
const CFG = { plugins: { deny: ["whatsapp"] }, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER, PEER_2] } }, session: { dmScope: "per-channel-peer" } };
/** A released reply (no figures) and one the verifier withholds (a figure the user never
 *  wrote), which in safe-text mode would otherwise go out as SAFE_TEXT. */
const REPLIES = Object.freeze({ released: "Hello!", withheld: "That one is listed at $1,234,567." });
const MODES = ["safe-text", "silent"];

const sign = (raw) => `sha256=${createHmac("sha256", CONFIG.appSecret).update(raw).digest("hex")}`;
let msgSeq = 0;
/** A signed POST carrying one text message from `from`, stamped now. */
function inbound(from = WA_ID, body = "any homes?") {
  msgSeq += 1;
  const payload = {
    object: "whatsapp_business_account",
    entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: {
      messaging_product: "whatsapp",
      metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: CONFIG.phoneNumberId },
      contacts: [{ profile: { name: "Test Buyer" }, wa_id: from }],
      messages: [{ from, id: `wamid.LIFE-${msgSeq}`, timestamp: String(Math.floor(Date.now() / 1000)), type: "text", text: { body } }],
    } }] }],
  };
  const bytes = Buffer.from(JSON.stringify(payload), "utf8");
  return { method: "POST", url: CONFIG.webhookPath, headers: { "x-hub-signature-256": sign(bytes) }, body: bytes };
}

/** A fetch that records each call and answers one accepted send. */
function fakeFetch() {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ messages: [{ id: `wamid.SENT-${calls.length}` }] }), { status: 200 });
  };
  return { fn, calls };
}

const settle = async (n = 10) => {
  for (let i = 0; i < n; i += 1) await new Promise((r) => setImmediate(r));
};

/** A promise the test resolves by hand. */
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

/**
 * The real channel over the real Cloud API transport with a counting fake fetch, on a
 * shared ingress (the process-wide one by default, as the entry wires it). Every turn's
 * reply is held: the fake host's runner awaits a promise the test resolves through
 * `turns[i].release(text)`.
 */
function rig({ withholdMode, ingress = processIngress() }) {
  const f = fakeFetch();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn });
  /** @type {Array<{ text: string, release: (reply: string) => void }>} */
  const turns = [];
  const host = createFakeHost({
    replies: async (text) => {
      const gate = deferred();
      turns.push({ text, release: gate.resolve });
      return gate.promise;
    },
  });
  const plugin = createChannelPlugin({ transport: t, ingress, resolveRoute: host.resolveRoute, runInbound: host.runInbound, withholdMode });
  /** Starts the account with a fresh signal and returns its controller and promise. */
  const startAccount = () => {
    const ac = new AbortController();
    const running = plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: ac.signal });
    return { ac, running };
  };
  /** Releases a held turn's reply and waits until the host has delivered it. */
  const releaseAndDeliver = async (i, reply) => {
    const before = host.results.length;
    turns[i].release(reply);
    for (let k = 0; k < 50 && host.results.length === before; k += 1) await settle(1);
    await settle();
    return host.results.at(-1);
  };
  return { f, t, host, plugin, turns, startAccount, releaseAndDeliver };
}

// ---- the owner's regression: hold a turn, stop or reload, release the late reply ----------

test("CL-1 stop: a turn held open across an account stop (its start signal aborted) makes zero Graph API calls when its reply arrives, in both withhold modes, for a released and a withheld reply", async () => {
  for (const withholdMode of MODES) {
    for (const [kind, reply] of Object.entries(REPLIES)) {
      const r = rig({ withholdMode });
      const { ac, running } = r.startAccount();
      await settle();
      assert.equal(r.t.webhook.handle(inbound()).status, 200);
      await settle();
      assert.equal(r.turns.length, 1, "the turn is running and held");
      ac.abort();
      await running;
      const late = await r.releaseAndDeliver(0, reply);
      assert.equal(r.f.calls.length, 0, `${withholdMode} ${kind}: the late reply made a Graph API call`);
      assert.deepEqual(late, { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } }, `${withholdMode} ${kind}`);
    }
  }
});

test("CL-2 reload: a turn held open across a reload (abort, then startAccount with a new signal) makes zero Graph API calls when its reply arrives after the new account started; the new turn from the same peer is admitted (not BUSY) and its reply makes exactly one; both orders, both withhold modes", async () => {
  for (const withholdMode of MODES) {
    for (const [kind, reply] of Object.entries(REPLIES)) {
      for (const order of ["new-first", "old-first"]) {
        const label = `${withholdMode} ${kind} ${order}`;
        const r = rig({ withholdMode });
        const first = r.startAccount();
        await settle();
        assert.equal(r.t.webhook.handle(inbound()).status, 200);
        await settle();
        assert.equal(r.turns.length, 1);
        // reload: the host aborts the old start and starts the account again
        first.ac.abort();
        await first.running;
        const second = r.startAccount();
        await settle();
        assert.equal(r.t.webhook.handle(inbound(WA_ID, "and in the next town?")).status, 200);
        await settle();
        assert.equal(r.turns.length, 2, `${label}: the peer's next message started a new turn`);
        assert.equal(r.f.calls.length, 0, `${label}: no BUSY_TEXT went out for the voided turn`);
        if (order === "new-first") {
          const fresh = await r.releaseAndDeliver(1, REPLIES.released);
          assert.equal(r.f.calls.length, 1, `${label}: the new turn's reply`);
          assert.equal(fresh.visibleReplySent, true);
          const late = await r.releaseAndDeliver(0, reply);
          assert.equal(r.f.calls.length, 1, `${label}: the late reply made a Graph API call`);
          assert.deepEqual(late, { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } });
        } else {
          const late = await r.releaseAndDeliver(0, reply);
          assert.equal(r.f.calls.length, 0, `${label}: the late reply made a Graph API call`);
          assert.deepEqual(late, { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } });
          const fresh = await r.releaseAndDeliver(1, REPLIES.released);
          assert.equal(r.f.calls.length, 1, `${label}: the new turn's reply`);
          assert.equal(fresh.visibleReplySent, true);
        }
        assert.equal(JSON.parse(r.f.calls[0].init.body).text.body, REPLIES.released, label);
        assert.equal(JSON.parse(r.f.calls[0].init.body).to, WA_ID, label);
        second.ac.abort();
        await second.running;
      }
    }
  }
});

test("CL-3 a reload that leaves the old start's signal unaborted until after the new start (late abort) still voids the old turn and does not void the new one", async () => {
  const r = rig({ withholdMode: "safe-text", ingress: createIngress() });
  const first = r.startAccount();
  await settle();
  r.t.webhook.handle(inbound());
  await settle();
  const second = r.startAccount(); // a newer start takes over before the old signal aborts
  await settle();
  r.t.webhook.handle(inbound(WA_ID, "again"));
  await settle();
  assert.equal(r.turns.length, 2);
  first.ac.abort(); // the old signal, aborted late, must not void the newer start's turn
  await first.running;
  assert.deepEqual(await r.releaseAndDeliver(0, REPLIES.withheld), { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } });
  assert.equal(r.f.calls.length, 0);
  const fresh = await r.releaseAndDeliver(1, REPLIES.released);
  assert.equal(fresh.visibleReplySent, true);
  assert.equal(r.f.calls.length, 1);
  second.ac.abort();
  await second.running;
});

test("CL-10 across plugin objects: two channel objects share the process ingress and the one Cloud API transport (the host registers more than once); the first object's start signal aborting after the second object's start leaves the second's held turn deliverable (exactly one Graph API call) and its peer busy, and the first object's sink drops inbounds", async () => {
  for (const withholdMode of MODES) {
    const ingress = createIngress();
    const f = fakeFetch();
    const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn });
    const turns = [];
    const host = createFakeHost({
      replies: async (text) => {
        const gate = deferred();
        turns.push({ text, release: gate.resolve });
        return gate.promise;
      },
    });
    const mk = () => createChannelPlugin({ transport: t, ingress, resolveRoute: host.resolveRoute, runInbound: host.runInbound, withholdMode });
    const p1 = mk();
    const p2 = mk();
    const a1 = new AbortController();
    const r1 = p1.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: a1.signal });
    await settle();
    const a2 = new AbortController();
    const r2 = p2.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: a2.signal });
    await settle();
    assert.equal(t.webhook.handle(inbound()).status, 200);
    await settle();
    assert.equal(turns.length, 1, `${withholdMode}: P2's turn is held`);
    a1.abort(); // the older object's signal aborts late
    await r1;
    // the peer is still busy under P2: its next message is not a second running turn
    assert.equal(t.webhook.handle(inbound(WA_ID, "still there?")).status, 200);
    await settle();
    assert.equal(turns.length, 1, `${withholdMode}: a second concurrent turn started for the busy peer`);
    const busyCalls = f.calls.length;
    assert.equal(busyCalls, 1, `${withholdMode}: the busy reply went out once`);
    // P2's legitimate reply is delivered: exactly one more Graph API call
    const before = host.results.length;
    turns[0].release(REPLIES.released);
    for (let k = 0; k < 50 && host.results.length === before; k += 1) await settle(1);
    await settle();
    assert.equal(host.results.at(-1).visibleReplySent, true, withholdMode);
    assert.equal(f.calls.length, busyCalls + 1, `${withholdMode}: P2's reply made exactly one Graph API call`);
    assert.equal(JSON.parse(f.calls.at(-1).init.body).text.body, REPLIES.released);
    // stopping P2 now voids its turns; P1's stale start could not, and P2's own abort does
    const epochBefore = ingress.accountEpoch("default");
    assert.equal(ingress.endAccountEpoch("default", epochBefore - 1), false, "a stale epoch changes nothing");
    assert.equal(ingress.accountEpoch("default"), epochBefore);
    a2.abort();
    await r2;
    assert.equal(ingress.accountEpoch("default"), epochBefore + 1, "the newest start's own abort ends its epoch");
  }

  // the older object's sink (a fake transport that keeps every sink) drops once a newer
  // object has started the account, before anything is recorded
  const ingress = createIngress();
  const fakeOld = createFakeTransport();
  const fakeNew = createFakeTransport();
  const warns = [];
  const host = createFakeHost({ replies: () => "Hello!" });
  const opts = { ingress, resolveRoute: host.resolveRoute, runInbound: host.runInbound, log: { warn: (m) => warns.push(m) } };
  const q1 = createChannelPlugin({ ...opts, transport: fakeOld });
  const q2 = createChannelPlugin({ ...opts, transport: fakeNew });
  await q1.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: new AbortController().signal });
  await q2.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: new AbortController().signal });
  await fakeOld.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m-old", receivedAt: 1 });
  assert.equal(host.turns.length, 0);
  assert.equal(ingress.size(), 0);
  assert.deepEqual(warns.at(-1), { component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason: "account-stopped" });
  await fakeNew.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m-new", receivedAt: 2 });
  assert.equal(host.turns.length, 1);
});

// ---- the transport refuses sends unless running -------------------------------------------

test("CL-4 the transport refuses transport-not-running, with no request, before its first start, after an abort, after stop() and between a stop and the next start; a restart runs fresh", async () => {
  const f = fakeFetch();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn });
  const req = { accountId: "default", to: PEER, text: "Hello!" };
  await assert.rejects(t.sendText(req), /cloud api: transport-not-running$/, "before the first start");
  // running: an inbound opens the window and a send goes out
  let ac = new AbortController();
  let running = t.start({ accountId: "default", signal: ac.signal, onInbound: async () => {} });
  assert.equal(t.webhook.handle(inbound()).status, 200);
  assert.deepEqual(await t.sendText(req), { messageId: "wamid.SENT-1" });
  ac.abort();
  await running;
  await assert.rejects(t.sendText(req), /cloud api: transport-not-running$/, "after the start signal aborted");
  // refused before anything else is looked at: even a malformed request names the lifecycle
  await assert.rejects(t.sendText({ to: "nobody", text: "" }), /transport-not-running$/);
  // a restart runs fresh; stop() ends it again
  ac = new AbortController();
  running = t.start({ accountId: "default", signal: ac.signal, onInbound: async () => {} });
  assert.deepEqual(await t.sendText(req), { messageId: "wamid.SENT-2" }, "the window is Meta's fact and survives the restart");
  await t.stop();
  await running;
  await assert.rejects(t.sendText(req), /transport-not-running$/, "after stop()");
  // a start with an already-aborted signal never runs
  await t.start({ accountId: "default", signal: AbortSignal.abort(), onInbound: async () => {} });
  await assert.rejects(t.sendText(req), /transport-not-running$/);
  assert.equal(f.calls.length, 2, "only the two running sends reached fetch");
  // the error carries the fixed reason only
  const err = await t.sendText(req).catch((e) => e);
  assert.equal(err.reason, "transport-not-running");
  for (const s of [CONFIG.accessToken, CONFIG.appSecret, WA_ID, "Hello!"]) assert.ok(!`${err.message} ${err.stack}`.includes(s), s);
});

test("CL-5 a stop during an in-flight fetch aborts it through the signal fetch was given (start abort, stop(), and a takeover by a newer start); each is one request, never retried", { timeout: 5_000 }, async () => {
  for (const how of ["abort", "stop", "takeover"]) {
    const calls = [];
    const t = createCloudApiTransport({
      config: CONFIG,
      fetch: (url, init) => {
        calls.push(init.signal);
        return new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(Object.assign(new Error("This operation was aborted"), { name: "AbortError" }))));
      },
    });
    const ac = new AbortController();
    const running = t.start({ accountId: "default", signal: ac.signal, onInbound: async () => {} });
    t.webhook.handle(inbound());
    const p = t.sendText({ accountId: "default", to: PEER, text: "Hello!" });
    await settle(2);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].aborted, false);
    let next;
    if (how === "abort") ac.abort();
    else if (how === "stop") await t.stop();
    else next = new AbortController();
    if (next) void t.start({ accountId: "default", signal: next.signal, onInbound: async () => {} });
    // The fake fetch settles only on abort, so a broken abort would hang: bound the wait
    // and name the case instead.
    let timer;
    const hung = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${how}: the in-flight request was never aborted`)), 2_000);
    });
    try {
      await assert.rejects(Promise.race([p, hung]), /cloud api: aborted$/, how);
    } finally {
      clearTimeout(timer);
    }
    assert.equal(calls[0].aborted, true, how);
    assert.equal(calls.length, 1, `${how}: never retried`);
    ac.abort();
    next?.abort();
    await running;
  }
});

/** A signed batch from `n` distinct synthetic senders, none of them PEER. */
function flood(n, tag) {
  const payload = JSON.parse(inbound().body.toString("utf8"));
  payload.entry[0].changes[0].value.messages = Array.from({ length: n }, (_, i) => ({
    from: `1555300${String(i).padStart(4, "0")}`, id: `wamid.${tag}-${i}`, timestamp: String(Math.floor(Date.now() / 1000)), type: "text", text: { body: "spam" },
  }));
  const bytes = Buffer.from(JSON.stringify(payload), "utf8");
  return { method: "POST", url: CONFIG.webhookPath, headers: { "x-hub-signature-256": sign(bytes) }, body: bytes };
}

test("CL-6 a stop releases the window pins of its held turns, so the next start's flood can evict that peer; a late settle from the old turn does not unpin the peer for the next start", async () => {
  const f = fakeFetch();
  const t = createCloudApiTransport({ config: CONFIG, fetch: f.fn });
  const heldOld = deferred();
  const ac = new AbortController();
  const running = t.start({ accountId: "default", signal: ac.signal, onInbound: () => heldOld.promise });
  assert.equal(t.webhook.handle(inbound()).status, 200, "PEER's turn is held under the first start");
  ac.abort();
  await running;
  const ac2 = new AbortController();
  const heldNew = deferred();
  const running2 = t.start({ accountId: "default", signal: ac2.signal, onInbound: () => heldNew.promise });
  // PEER is not pinned under the new start: a flood evicts it, and the window is closed
  assert.equal(t.webhook.handle(flood(1100, "FLOOD-A")).status, 200);
  await assert.rejects(t.sendText({ accountId: "default", to: PEER, text: "Hello!" }), /outside-customer-service-window$/);
  // PEER writes under the new start (pinned there); the old turn then settles
  assert.equal(t.webhook.handle(inbound()).status, 200);
  heldOld.resolve();
  await settle();
  assert.equal(t.webhook.handle(flood(1100, "FLOOD-B")).status, 200);
  assert.deepEqual(await t.sendText({ accountId: "default", to: PEER, text: "Hello!" }), { messageId: "wamid.SENT-1" });
  assert.equal(f.calls.length, 1);
  heldNew.resolve();
  ac2.abort();
  await running2;
});

// ---- the ingress epochs ----------------------------------------------------------------

test("CL-7 beginAccountEpoch voids every earlier turn of that account for every lookup (forTurn, confirmRun, admitCardCall, captureReply, replySections, issuedRun, hasActiveTurn); epochs only rise; turns recorded after are valid", () => {
  const ing = createIngress({ now: () => 1 });
  const a = recordBoundTurn(ing, { peerId: PEER, turnId: "t-a" });
  const b = recordBoundTurn(ing, { peerId: PEER_2, turnId: "t-b", confirm: false });
  const keyA = ing.key("default", PEER);
  const keyB = ing.key("default", PEER_2);
  assert.deepEqual(ing.admitCardCall({ runId: a.runId, sessionKey: a.sessionKey, toolName: "idx__search_listings", toolCallId: "c1" }), { admitted: true });
  assert.equal(ing.hasActiveTurn(keyA), true);
  assert.equal(ing.beginAccountEpoch("default"), 1);
  assert.equal(ing.forTurn(keyA, a.handle), null);
  assert.equal(ing.forTurn(keyB, b.handle), null);
  assert.equal(ing.confirmRun(b.handle, b.runId), false, "an unconfirmed old run cannot be confirmed later");
  assert.equal(ing.hasActiveTurn(keyA), false, "the peer is free for its next message");
  assert.equal(ing.hasActiveTurn(keyB), false);
  assert.deepEqual(ing.admitCardCall({ runId: a.runId, sessionKey: a.sessionKey, toolName: "idx__search_listings", toolCallId: "c2" }), { admitted: false, reason: "turn-expired" });
  assert.deepEqual(ing.captureReply({ runId: a.runId, sessionKey: a.sessionKey, toolName: "idx__search_listings", toolCallId: "c1", section: { text: "x" } }), { stored: 0, reason: "turn-expired" });
  assert.equal(ing.replySections({ sessionKey: a.sessionKey, turnId: "t-a" }), null);
  assert.equal(ing.issuedRun({ runId: a.runId, sessionKey: a.sessionKey }), false);
  assert.equal(ing.issuedRun({ runId: b.runId, sessionKey: b.sessionKey }), false);
  assert.equal(ing.size(), 0, "the voided entries left the store");
  // the before_tool_call handler refuses an old run's card call and runs nothing
  const hook = createBeforeToolCallHandler(ing);
  assert.equal(hook({ toolName: "idx__search_listings", runId: a.runId, toolCallId: "c3" }, { runId: a.runId, sessionKey: a.sessionKey }).block, true);
  // new turns are valid, and the counter only rises
  const c = recordBoundTurn(ing, { peerId: PEER, turnId: "t-c" });
  assert.ok(ing.forTurn(keyA, c.handle));
  assert.equal(ing.issuedRun({ runId: c.runId, sessionKey: c.sessionKey }), true);
  assert.equal(ing.hasActiveTurn(keyA), true);
  assert.equal(ing.beginAccountEpoch("default"), 2);
  assert.equal(ing.beginAccountEpoch("default"), 3);
  assert.equal(ing.forTurn(keyA, c.handle), null);
  // an epoch bump on an account with nothing recorded is harmless
  assert.equal(ing.beginAccountEpoch("never-used"), 1);
});

test("CL-8 another account's turns are not invalidated: its handle, run, active turn and reply survive an epoch bump of the first account, through the ingress and through two channels sharing it", async () => {
  const ing = createIngress({ now: () => 1 });
  const mine = recordBoundTurn(ing, { peerId: PEER, turnId: "t-mine" });
  const theirs = recordBoundTurn(ing, { accountId: "second", peerId: PEER, turnId: "t-theirs" });
  ing.beginAccountEpoch("default");
  assert.equal(ing.forTurn(ing.key("default", PEER), mine.handle), null);
  assert.ok(ing.forTurn(ing.key("second", PEER), theirs.handle));
  assert.equal(ing.hasActiveTurn(ing.key("second", PEER)), true);
  assert.deepEqual(ing.admitCardCall({ runId: theirs.runId, sessionKey: theirs.sessionKey, toolName: "idx__search_listings" }), { admitted: true });

  // channel level: two accounts on one shared ingress, each with its own fake transport
  const shared = createIngress();
  const mk = () => {
    const fake = createFakeTransport();
    const gates = [];
    const host = createFakeHost({ replies: async () => { const g = deferred(); gates.push(g); return g.promise; } });
    const plugin = createChannelPlugin({ transport: fake, ingress: shared, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
    return { fake, gates, host, plugin };
  };
  const one = mk();
  const two = mk();
  const cfg2 = { ...CFG, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER] } } };
  const acOne = new AbortController();
  await one.plugin.gateway.startAccount({ cfg: cfg2, accountId: "default", abortSignal: acOne.signal });
  await two.plugin.gateway.startAccount({ cfg: cfg2, accountId: "second", abortSignal: new AbortController().signal });
  const p1 = one.fake.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  const p2 = two.fake.inbound({ accountId: "second", peerId: PEER, text: "hi", messageId: "m2", receivedAt: 1 });
  await settle();
  acOne.abort(); // stop "default" only
  one.gates[0].resolve("Hello!");
  two.gates[0].resolve("Hello!");
  await Promise.all([p1, p2]);
  assert.deepEqual(one.fake.sent, [], "the stopped account's late reply is not sent");
  assert.deepEqual(two.fake.sent.map((s) => s.text), ["Hello!"], "the other account's reply is sent");
  assert.deepEqual(one.host.results, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } }]);
});

test("CL-9 an inbound that reaches a stopped start's sink is dropped before it is recorded (account-stopped), and a stop frees the peer for the next start", async () => {
  const fake = createFakeTransport(); // keeps the old sink after an abort, unlike the Cloud API transport
  const warns = [];
  const host = createFakeHost({ replies: () => "Hello!" });
  const ing = createIngress();
  const plugin = createChannelPlugin({ transport: fake, ingress: ing, resolveRoute: host.resolveRoute, runInbound: host.runInbound, log: { warn: (m) => warns.push(m) } });
  const ac = new AbortController();
  await plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: ac.signal });
  ac.abort();
  await fake.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  assert.equal(host.turns.length, 0);
  assert.equal(ing.size(), 0);
  assert.deepEqual(warns.at(-1), { component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason: "account-stopped" });
  // the next start takes inbounds again
  await plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: new AbortController().signal });
  await fake.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m2", receivedAt: 2 });
  assert.equal(host.turns.length, 1);
  assert.deepEqual(fake.sent.map((s) => s.text), ["Hello!"]);
});
