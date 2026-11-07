import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createChannelPlugin } from "./channel.mjs";
import { SAFE_TEXT, TRANSPORT_METHODS } from "./constants.mjs";
import entry from "./index.mjs";
import { createIngress } from "./ingress.mjs";
import { selfCheck } from "./self-check.mjs";
import { createFakeTransport } from "./test-support/fake-transport.mjs";
import {
  createEmulatedDispatcher,
  createEmulatedRegistry,
  createFakeApi,
  createFakeHost,
  emulatedActivation,
} from "./test-support/host-emulation.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PEER = "+15550000001";
const DENY_CFG = { plugins: { deny: ["whatsapp"] } };

const RUNTIME_FILES = readdirSync(HERE).filter((f) => f.endsWith(".mjs") && !f.endsWith(".test.mjs"));
const source = (f) => readFileSync(path.join(HERE, f), "utf8");
/** Source with block and line comments removed, so JSDoc typedefs are not scanned as code. */
const code = (f) => source(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function copyExtension(mutate) {
  const dir = mkdtempSync(path.join(tmpdir(), "idx-wa-skeleton-"));
  for (const f of [...RUNTIME_FILES, "openclaw.plugin.json"]) cpSync(path.join(HERE, f), path.join(dir, f));
  mutate(dir);
  return dir;
}

// ---- source tests -----------------------------------------------------------

test("source: runtime file set is exactly the designed one", () => {
  assert.deepEqual(RUNTIME_FILES.sort(), [
    "card-resolver.mjs", "channel.mjs", "constants.mjs", "index.mjs", "ingress.mjs",
    "outbound.mjs", "self-check.mjs", "transport.mjs", "verifier.mjs",
  ]);
  assert.equal(readdirSync(HERE).includes("package.json"), false);
});

test("FC-missing-verifier (source): static import in index.mjs, no lazy import anywhere, no import in try", () => {
  const index = source("index.mjs");
  assert.match(index, /^import \{ verifyReply \} from "\.\/verifier\.mjs";$/m);
  for (const f of RUNTIME_FILES) {
    const s = code(f);
    assert.ok(!/\bimport\s*\(/.test(s), `${f} has a dynamic import`);
    assert.ok(!/await\s+import/.test(s), `${f} awaits an import`);
    assert.ok(!/try\s*\{[^}]*\bimport\b/s.test(s), `${f} wraps an import in try`);
    assert.ok(!s.includes("test-support/"), `${f} imports test support`);
    assert.ok(!/from\s+["'](?!\.\/|node:)/.test(s), `${f} imports a non-local, non-builtin module`);
  }
});

/**
 * Every appearance of the identifier `transport` in the runtime that is not an immediate
 * member call `transport.<member>(`. Anything else (an alias `const t = transport`, a
 * destructuring `const { sendText } = transport`, passing it as an argument, `transport?.`,
 * `transport.sendText.call(`) changes these counts and fails the test below.
 */
const ALLOWED_NON_CALL_TRANSPORT = {
  "outbound.mjs": ["export function createOutbound({\n  transport,", "if (!transport || !ingress)"],
  "channel.mjs": ["export function createChannelPlugin({\n  transport = unavailableTransport,", "const outbound = createOutbound({\n    transport,"],
  "index.mjs": ["transport: unavailableTransport,"],
};

/** Source without comments and with string and template literals blanked, for identifier scans. */
const identifiers = (f) => code(f).replace(/"[^"\n]*"|'[^'\n]*'|`[^`]*`/g, '""');

test("FC-single-call-site (source): one transport.sendText( in outbound.mjs with sealed.text; transport is only ever called as transport.<member>( on four members; no alias, destructuring, bracket access, Reflect or seal elsewhere", () => {
  let callSites = 0;
  const members = new Set();
  for (const f of RUNTIME_FILES) {
    const s = identifiers(f);
    const sends = s.match(/\btransport\s*\.\s*sendText\s*\(/g) ?? [];
    callSites += sends.length;
    if (sends.length) assert.equal(f, "outbound.mjs");
    let nonCall = 0;
    // (?<![\/.\w$]) skips "./transport.mjs" in import statements and identifiers that merely end in "transport"
    for (const m of s.matchAll(/(?<![\/.\w$])transport(?![\w$])/g)) {
      const call = /^\s*\.\s*([A-Za-z_$][\w$]*)\s*\(/.exec(s.slice(m.index + m[0].length));
      if (call) members.add(call[1]);
      else nonCall += 1;
    }
    const allowed = ALLOWED_NON_CALL_TRANSPORT[f] ?? [];
    for (const snippet of allowed) assert.ok(s.includes(snippet), `${f} lacks ${JSON.stringify(snippet)}`);
    assert.equal(nonCall, allowed.length, `${f}: transport is aliased, destructured, passed or read without an immediate member call`);
    assert.ok(!/\btransport\s*\[/.test(s), `${f} indexes transport`);
    assert.ok(!/\btransport\s*\?\./.test(s), `${f} optional-chains transport`);
    assert.ok(!/Reflect\s*\.\s*(apply|get)/.test(s), `${f} uses Reflect`);
    if (f !== "outbound.mjs") assert.ok(!/\bseal\s*\(/.test(s), `${f} seals`);
  }
  assert.equal(callSites, 1);
  // The runtime uses start, sendText and isConfigured; stop is part of the interface
  // but unused here (the host stops an account through abortSignal).
  for (const m of members) assert.ok(TRANSPORT_METHODS.includes(m), `transport.${m} is not an allowed member`);
  assert.deepEqual([...members].sort(), ["isConfigured", "sendText", "start"]);
  const out = code("outbound.mjs");
  assert.match(out, /await transport\.sendText\(\{\s*accountId,\s*to: peer,\s*text: sealed\.text,/s);
  assert.equal((out.match(/\bseal\(/g) ?? []).length, 3); // definition, release, safe-text
});

test("single-read (source): sendText reads each context field once, up front, and the transport gets the canonical peer, never ctx.to", () => {
  const out = code("outbound.mjs");
  const body = out.slice(out.indexOf("async function sendText(ctx)"));
  const reads = body.match(/\bctx\??\.\w+/g) ?? [];
  assert.deepEqual(reads.map((r) => r.replace(/^ctx\??\./, "")).sort(), ["abortSignal", "accountId", "signal", "text", "to", "turn", "turnId"]);
  // every read happens before the first use of the resolved account id
  const lastRead = Math.max(...reads.map((r) => body.lastIndexOf(r)));
  assert.ok(lastRead < body.indexOf("const accountId ="));
  assert.ok(!/to:\s*ctx/.test(body));
});

test("D17 (source): no latest-turn fallback anywhere: outbound.mjs never calls .current(, ingress.mjs defines no current( method, and the gate names the no-turn-handle withhold", () => {
  const out = identifiers("outbound.mjs");
  assert.ok(!/\.\s*current\s*\(/.test(out), "outbound.mjs calls .current(");
  assert.ok(!/\bcurrent\s*\(/.test(identifiers("ingress.mjs")), "ingress.mjs defines or calls current(");
  for (const f of RUNTIME_FILES) assert.ok(!/\.\s*current\s*\(/.test(identifiers(f)), `${f} calls .current(`);
  assert.ok(source("outbound.mjs").includes('"no-turn-handle"'));
  // the only binding read is forTurn with the trusted handle, and it precedes the verifier
  const body = code("outbound.mjs").slice(code("outbound.mjs").indexOf("async function sendText(ctx)"));
  assert.equal((body.match(/ingress\s*\.\s*forTurn\s*\(/g) ?? []).length, 1);
  assert.ok(body.indexOf("ingress.forTurn(") < body.indexOf("runVerifier(text, record)"));
  // the live ingress has no such member either, and the seam on the turn is beforeToolCall
  assert.equal("current" in createIngress({ now: () => 0 }), false);
  assert.ok(!/\bnoteToolCall\b/.test(code("channel.mjs")));
  assert.ok(/\bbeforeToolCall\b/.test(code("channel.mjs")));
  assert.ok(/export function createBeforeToolCallHandler\(/.test(source("channel.mjs")));
});

test("FC-single-call-site (source, self-test): the scan catches a destructured raw send and a .call bypass", () => {
  const scan = (src) => {
    const s = src.replace(/"[^"\n]*"|'[^'\n]*'|`[^`]*`/g, '""');
    let nonCall = 0;
    let dotted = 0;
    for (const m of s.matchAll(/(?<![\/.\w$])transport(?![\w$])/g)) {
      const rest = s.slice(m.index + m[0].length);
      if (/^\s*\.\s*([A-Za-z_$][\w$]*)\s*\(/.test(rest)) dotted += 1;
      else nonCall += 1;
    }
    return { nonCall, dotted };
  };
  const base = identifiers("outbound.mjs");
  assert.deepEqual(scan(base), { nonCall: 2, dotted: 1 });
  const evasions = [
    "const { sendText: rawSend } = transport; await rawSend({ accountId, to: ctx.to, text: String(text) });",
    "const t = transport; await t.sendText({ accountId, to: ctx.to, text: String(text) });",
    "await transport.sendText.call(transport, { accountId, to: ctx.to, text: String(text) });",
    "await transport?.sendText({ accountId, to: ctx.to, text: String(text) });",
    "await rawSend(transport, String(text));",
  ];
  for (const e of evasions) {
    const mutated = base.replace("const verdict = runVerifier(text, record);", `${e}\n    const verdict = runVerifier(text, record);`);
    assert.notEqual(scan(mutated).nonCall, 2, e);
  }
});

test("source: only index.mjs has a default export (a stray standalone-file load registers nothing)", async () => {
  for (const f of RUNTIME_FILES) {
    const mod = await import(pathToFileURL(path.join(HERE, f)).href);
    if (f === "index.mjs") assert.equal(typeof mod.default.register, "function");
    else assert.equal("default" in mod, false, f);
    if (f !== "index.mjs") assert.ok(!/export\s+default/.test(source(f)), f);
  }
});

test("Proxy transport: the runtime touches only the four allowed members", async () => {
  const accessed = new Set();
  const fake = createFakeTransport();
  const proxied = new Proxy(fake, {
    get(t, p) {
      if (typeof p === "string") accessed.add(p);
      return Reflect.get(t, p);
    },
  });
  const host = createFakeHost({ replies: (t) => (t === "hi" ? "Hello!" : "Anything else?") });
  const plugin = createChannelPlugin({ transport: proxied, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  plugin.config.isConfigured({}, {});
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await fake.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  await fake.inbound({ accountId: "default", peerId: PEER, text: "ok", messageId: "m2", receivedAt: 2 });
  // a handle-less send touches no transport member at all
  assert.deepEqual(await plugin.outbound.sendText({ to: PEER, text: "Still there?", accountId: "default" }), { outcome: "not_sent", reason: "no-turn-handle" });
  for (const p of accessed) assert.ok(TRANSPORT_METHODS.includes(p), p);
  assert.deepEqual(fake.sent.map((s) => s.text), ["Hello!", "Anything else?"]);
});

// ---- FC-missing-verifier (module) --------------------------------------------

test("FC-missing-verifier: without verifier.mjs the entry does not import, so register() can never run", async () => {
  const dir = copyExtension((d) => rmSync(path.join(d, "verifier.mjs")));
  try {
    await assert.rejects(import(pathToFileURL(path.join(dir, "index.mjs")).href), (err) => err.code === "ERR_MODULE_NOT_FOUND");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("FC-missing-verifier: a verifier that releases everything fails the self-test and nothing registers", async () => {
  const dir = copyExtension((d) =>
    writeFileSync(
      path.join(d, "verifier.mjs"),
      [
        'export const VERIFIER_VERSION = "bad";',
        "export function digitRuns() { return []; }",
        "export function isInboundRecord() { return true; }",
        "export function isTokenOnlyText() { return false; }",
        'export function verifyReply({ text }) { return { kind: "release", rule: "no-figures", text }; }',
        "export function isWellFormedVerdict() { return true; }",
        "",
      ].join("\n"),
    ),
  );
  try {
    const mod = await import(pathToFileURL(path.join(dir, "index.mjs")).href);
    const { api, registered } = createFakeApi({ cfg: DENY_CFG });
    assert.throws(() => mod.default.register(api), /verifier-self-test-failed/);
    assert.equal(registered.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// ---- host emulation: deny, first wins ------------------------------------------

test("FC-no-stock-fallback (emulation, documents cited rules): the self-check and the deny predicate agree", () => {
  const accepted = [DENY_CFG, { plugins: { deny: [" WhatsApp "] } }, { plugins: { deny: ["telegram", "whatsapp"] } }];
  const refused = [{}, { plugins: {} }, { plugins: { deny: [] } }, { plugins: { deny: ["telegram"] } }, { plugins: { deny: [123] } }, { plugins: { entries: { whatsapp: { enabled: false } } } }];
  for (const cfg of accepted) {
    assert.equal(selfCheck(cfg).ok, true);
    assert.equal(emulatedActivation(cfg, "whatsapp", { origin: "bundled", channelId: "whatsapp" }), "blocked-by-denylist");
  }
  for (const cfg of refused) {
    assert.equal(selfCheck(cfg).ok, false);
    assert.notEqual(emulatedActivation(cfg, "whatsapp", { origin: "bundled", channelId: "whatsapp" }), "blocked-by-denylist");
  }
  // plugins.enabled === false refuses everything, including us; the self-check does not model it
  const allOff = { plugins: { enabled: false, deny: ["whatsapp"] } };
  assert.equal(emulatedActivation(allOff, "whatsapp"), "disabled:plugins-disabled");
  assert.equal(emulatedActivation(allOff, "idx-whatsapp-channel"), "disabled:plugins-disabled");
  // a config-origin plugin is not auto-enabled by channels.whatsapp; it needs an explicit entry or allow
  const configured = { plugins: { deny: ["whatsapp"] }, channels: { whatsapp: {} } };
  assert.equal(emulatedActivation(configured, "idx-whatsapp-channel", { origin: "config", channelId: "whatsapp" }), "disabled:not-selected");
  assert.equal(emulatedActivation({ ...configured, plugins: { deny: ["whatsapp"], entries: { "idx-whatsapp-channel": { enabled: true } } } }, "idx-whatsapp-channel", { origin: "config", channelId: "whatsapp" }), "eligible");
});

test("first registrant wins: with the stock plugin present ours conflicts; with it denied ours registers", () => {
  const stock = { id: "whatsapp", outbound: { sendText: async () => ({ messageId: "stock" }) } };
  const ours = createChannelPlugin({ transport: createFakeTransport() });
  const r1 = createEmulatedRegistry();
  assert.equal(r1.registerChannel("whatsapp", stock), "registered");
  assert.equal(r1.registerChannel("idx-whatsapp-channel", ours), "conflict");
  assert.equal(r1.outboundFor("whatsapp"), stock.outbound);
  const r2 = createEmulatedRegistry();
  if (emulatedActivation(DENY_CFG, "whatsapp") !== "blocked-by-denylist") r2.registerChannel("whatsapp", stock);
  assert.equal(r2.registerChannel("idx-whatsapp-channel", ours), "registered");
  assert.equal(r2.outboundFor("whatsapp"), ours.outbound);
});

// ---- dispatcher emulation -------------------------------------------------------

async function pluginWithOpenTurn({ verify, replies = () => "unused" } = {}) {
  const transport = createFakeTransport();
  const host = createFakeHost({ replies });
  let captured;
  const plugin = createChannelPlugin({
    transport,
    ...(verify ? { verify } : {}),
    resolveRoute: host.resolveRoute,
    runInbound: async (turn) => {
      captured = turn.deliver;
    },
  });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "3 or 4", messageId: "m1", receivedAt: 1 });
  return { transport, plugin, deliver: captured };
}

test("FC-dispatcher-emulation (a): verifier throws -> deliver resolves, SAFE_TEXT sent, raw never", async () => {
  const { transport, deliver } = await pluginWithOpenTurn({ verify: () => { throw new Error("boom"); } });
  const errors = [];
  const d = createEmulatedDispatcher({ deliver, onError: (e) => errors.push(e) });
  assert.equal(await d.enqueue({ text: "There are 12 homes" }), "delivered");
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  assert.equal(errors.length, 0);
});

test("FC-dispatcher-emulation (b): transport failure -> failed-deliver, onError once, zero sends, no second route", async () => {
  const { transport, deliver } = await pluginWithOpenTurn();
  const errors = [];
  const d = createEmulatedDispatcher({ deliver, onError: (e) => errors.push(e) });
  transport.failNextSend(new Error("socket closed"));
  assert.equal(await d.enqueue({ text: "Hello!" }), "failed-deliver");
  assert.equal(errors.length, 1);
  assert.equal(transport.sent.length, 0);
  assert.equal(d.counts.deliverCalls, 1);
});

test("FC-dispatcher-emulation (c): withheld reply is delivered-not-visible; the fallback goes through the same deliver and is itself verified", async () => {
  const silentPlugin = async () => {
    const transport = createFakeTransport();
    const host = createFakeHost({ replies: () => "x" });
    let captured;
    const plugin = createChannelPlugin({ transport, withholdMode: "silent", resolveRoute: host.resolveRoute, runInbound: async (t) => { captured = t.deliver; } });
    await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
    await transport.inbound({ accountId: "default", peerId: PEER, text: "3 or 4", messageId: "m1", receivedAt: 1 });
    return { transport, deliver: captured };
  };
  // withheld primary, digit-bearing fallback: both withheld, nothing sent
  const a = await silentPlugin();
  const da = createEmulatedDispatcher({ deliver: a.deliver });
  assert.equal(await da.enqueue({ text: "There are 12 homes" }, { text: "Try 5 more" }), "delivered-not-visible");
  assert.equal(a.transport.sent.length, 0);
  assert.equal(da.counts.deliverCalls, 2);
  // withheld primary, digit-free fallback: the fallback is sent
  const b = await silentPlugin();
  const db = createEmulatedDispatcher({ deliver: b.deliver });
  assert.equal(await db.enqueue({ text: "There are 12 homes" }, { text: "Could you say that again?" }), "delivered");
  assert.deepEqual(b.transport.sent.map((s) => s.text), ["Could you say that again?"]);
  // the deliver result shape for a withhold carries the reason, never adapter_returned_no_identity
  const r = await b.deliver({ text: "There are 12 homes" });
  assert.deepEqual(r, { visibleReplySent: false, suppression: { reason: "idx-withheld:unverified-figures" } });
});

test("FC-dispatcher-emulation (d): a non-text fallback is refused", async () => {
  const { transport, deliver } = await pluginWithOpenTurn();
  const d = createEmulatedDispatcher({ deliver });
  // safe-text mode: the refused media payload becomes SAFE_TEXT, which is sent once
  assert.equal(await d.enqueue({ text: "cap", mediaUrl: "https://example.com/a.jpg" }), "delivered");
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  const r = await deliver({ text: "Hello", poll: { question: "q", options: ["a", "b"] } });
  assert.equal(r.visibleReplySent, true); // SAFE_TEXT went out, not the poll or its caption
  assert.ok(!transport.sent.some((s) => s.text.includes("Hello") || s.text.includes("cap")));
});

test("deliver result shapes: sent -> { messageId, visibleReplySent: true }; non-text in silent mode -> not visible", async () => {
  const transport = createFakeTransport();
  const host = createFakeHost({ replies: () => "x" });
  let captured;
  const plugin = createChannelPlugin({ transport, withholdMode: "silent", resolveRoute: host.resolveRoute, runInbound: async (t) => { captured = t.deliver; } });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(await captured({ text: "Hello!" }), { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(await captured({ text: "cap", mediaUrl: "https://example.com/a.jpg" }), { visibleReplySent: false, suppression: { reason: "idx-withheld:non-text-payload" } });
});

// ---- same outbound for message tool, cron, heartbeat -------------------------------

test("FC-same-outbound-for-tool-cron-heartbeat: one adapter object; every handle-less shape is withheld no-turn-handle even with a fresh record, only the channel's deliver sends", async () => {
  const transport = createFakeTransport();
  let captured;
  const host = createFakeHost({ replies: () => "x" });
  const plugin = createChannelPlugin({ transport, resolveRoute: host.resolveRoute, runInbound: async (t) => { captured = t; } });
  const registry = createEmulatedRegistry();
  assert.equal(registry.registerChannel("idx-whatsapp-channel", plugin), "registered");
  const outbound = registry.outboundFor("whatsapp");
  assert.equal(outbound, plugin.outbound);

  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "3 or 4", messageId: "m1", receivedAt: 1 });
  // the message tool, cron and heartbeat reach this same object with the host's own context shapes;
  // none carries the channel-minted handle, so none sends (decision 17), whatever the text would verify as
  const tool = { cfg: DENY_CFG, to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" };
  const cron = { cfg: DENY_CFG, to: "whatsapp:+15550000001", text: "Good morning! Any new wishes for your search?", accountId: "default", threadId: undefined };
  const heartbeat = { cfg: DENY_CFG, to: "15550000001@s.whatsapp.net", text: "There are 12 new homes today", accountId: "default" };
  const stranger = { cfg: DENY_CFG, to: "+15550000002", text: "Hello!", accountId: "default" };

  for (const shape of [tool, cron, heartbeat, stranger]) {
    assert.deepEqual(await outbound.sendText(shape), { outcome: "not_sent", reason: "no-turn-handle" }, shape.to);
    assert.equal(transport.sent.length, 0, shape.to);
  }
  // the inbound deliver closes over the very same outbound and carries the handle: it releases
  assert.deepEqual(await captured.deliver({ text: "Anything else?" }), { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(await captured.deliver({ text: "Do you mean 3 or 4 bedrooms?" }), { messageId: "fake-2", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Anything else?", "Do you mean 3 or 4 bedrooms?"]);
  assert.deepEqual(transport.sent.map((s) => s.to), [PEER, PEER]);
});

test("single-read (host shape): a destination that changes between reads cannot be verified against one peer and delivered to another; a non-string destination is refused", async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  const plugin = createChannelPlugin({ transport, ingress });
  // the handle a channel deliver would hold, minted here so the host-shaped context can be built by hand
  const handle = ingress.record(ingress.key("default", PEER), { sessionKey: `agent:idx:whatsapp:direct:${PEER}`, turnId: "t1", text: "I want 3 bedrooms", receivedAt: 1 });
  const stranger = "+15550000002";
  // controls: PEER's handle under the stranger's address is untrusted; no handle at all is no-turn-handle
  assert.deepEqual(await plugin.outbound.sendText({ cfg: DENY_CFG, accountId: "default", to: stranger, text: "You asked for 3 bedrooms", turn: handle }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.deepEqual(await plugin.outbound.sendText({ cfg: DENY_CFG, accountId: "default", to: stranger, text: "You asked for 3 bedrooms" }), { outcome: "not_sent", reason: "no-turn-handle" });
  // a getter that names PEER on the first read and the stranger afterwards
  for (const text of ["You asked for 3 bedrooms", "There are 12 homes", "Hello!"]) {
    let reads = 0;
    const ctx = { cfg: DENY_CFG, accountId: "default", text, turn: handle, get to() { reads += 1; return reads === 1 ? PEER : stranger; } };
    const r = await plugin.outbound.sendText(ctx);
    assert.equal(reads, 1, text);
    assert.equal(typeof r.messageId, "string", text);
    assert.equal(transport.sent.at(-1).to, PEER, text);
  }
  assert.deepEqual(transport.sent.map((s) => s.text), ["You asked for 3 bedrooms", SAFE_TEXT, "Hello!"]);
  // the host's own destination spellings (cron and heartbeat shapes) with the handle: the
  // transport is handed the canonical peer, not the spelling
  for (const to of ["whatsapp:+15550000001", "15550000001@s.whatsapp.net", "15550000001@c.us"]) {
    const r = await plugin.outbound.sendText({ cfg: DENY_CFG, accountId: "default", to, text: "Anything else?", turn: handle });
    assert.equal(typeof r.messageId, "string", to);
    assert.equal(transport.sent.at(-1).to, PEER, to);
  }
  assert.ok(transport.sent.every((s) => s.to === PEER));
  // an object with a stateful toString, or any non-string, never reaches the transport (checked before binding)
  const before = transport.sent.length;
  let calls = 0;
  const shifty = { toString() { calls += 1; return calls === 1 ? PEER : stranger; } };
  for (const to of [shifty, 15550000001, undefined, null, "", "   ", ["+15550000001"], { to: PEER }]) {
    assert.deepEqual(await plugin.outbound.sendText({ cfg: DENY_CFG, accountId: "default", to, text: "Hello!", turn: handle }), { outcome: "not_sent", reason: "bad-destination" }, String(to));
    assert.deepEqual(await plugin.outbound.sendText({ cfg: DENY_CFG, accountId: "default", to, text: "Hello!" }), { outcome: "not_sent", reason: "bad-destination" }, String(to));
  }
  assert.equal(transport.sent.length, before);
  assert.ok(!transport.sent.some((s) => s.to === stranger || typeof s.to !== "string"));
  // the account id and the handle are read once as well
  let accountReads = 0;
  let turnReads = 0;
  const r = await plugin.outbound.sendText({ cfg: DENY_CFG, to: PEER, text: "Hello!", get accountId() { accountReads += 1; return "default"; }, get turn() { turnReads += 1; return handle; } });
  assert.equal(accountReads, 1);
  assert.equal(turnReads, 1);
  assert.equal(typeof r.messageId, "string");
});

test("R1-binding (a, host shape): a tool-shaped send naming the earlier turn by id is untrusted after the peer's next message, even though its figures match that turn", async () => {
  const transport = createFakeTransport();
  const turns = [];
  const host = createFakeHost({ replies: () => "x" });
  const plugin = createChannelPlugin({ transport, resolveRoute: host.resolveRoute, runInbound: async (t) => { turns.push(t); } });
  const registry = createEmulatedRegistry();
  registry.registerChannel("idx-whatsapp-channel", plugin);
  const outbound = registry.outboundFor("whatsapp");
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "3 or 4 beds?", messageId: "m1", receivedAt: 1 });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "hello?", messageId: "m2", receivedAt: 2 });
  const earlier = turns[0].turnId;
  assert.equal(typeof earlier, "string");
  const tool = { cfg: DENY_CFG, to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default", turnId: earlier };
  assert.deepEqual(await outbound.sendText(tool), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.deepEqual(await outbound.sendText({ ...tool, to: "whatsapp:+15550000001" }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.deepEqual(await outbound.sendText({ ...tool, turnId: turns[1].turnId }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, 0);
  // the channel's own deliver for that earlier turn still releases the same text
  assert.deepEqual(await turns[0].deliver({ text: "Do you mean 3 or 4 bedrooms?" }), { messageId: "fake-1", visibleReplySent: true });
  assert.deepEqual(transport.sent.map((s) => s.text), ["Do you mean 3 or 4 bedrooms?"]);
});

test("R1-binding (e, host runner): runInbound gets the turn id as a string and no value the ingress trusts as a handle", async () => {
  const transport = createFakeTransport();
  const ingress = createIngress({ now: () => 1 });
  let captured;
  const host = createFakeHost({ replies: () => "x" });
  const plugin = createChannelPlugin({ transport, ingress, resolveRoute: host.resolveRoute, runInbound: async (t) => { captured = t; } });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  const key = ingress.key("default", PEER);
  assert.equal(typeof captured.turnId, "string");
  assert.equal("current" in ingress, false); // no read by key exists for a runner-side send to lean on
  const props = Object.entries(captured);
  assert.ok(props.length >= 8);
  assert.equal(typeof captured.beforeToolCall, "function");
  // Rule 1 first: nothing the runner receives is a handle (this is the binding property)
  for (const [name, value] of props) assert.equal(ingress.forTurn(key, value), null, name);
  // then Rule 2: nothing the runner receives can mark the turn directly
  for (const [name, value] of props) assert.equal(ingress.markCardTool(value, "search_listings"), false, name);
  // a runner-side send that names the turn is untrusted; the runner's deliver is the only bound path
  assert.deepEqual(await plugin.outbound.sendText({ to: PEER, text: "Hello!", accountId: "default", turnId: captured.turnId }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.deepEqual(await plugin.outbound.sendText({ to: PEER, text: "Hello!", accountId: "default", turn: { turnId: captured.turnId, key } }), { outcome: "not_sent", reason: "untrusted-turn" });
  assert.equal(transport.sent.length, 0);
  assert.deepEqual(await captured.deliver({ text: "Hello!" }), { messageId: "fake-1", visibleReplySent: true });
});

test("fake host (emulation, documents the fail-closed hook): a seam decision that is not an object with a boolean block (a bare boolean, a number, undefined, a missing seam) blocks the tool as bad-decision, a seam that throws blocks it as seam-threw, and nothing executes; the live seam's decision lets the tool run exactly once", async () => {
  const runWith = async (beforeToolCall) => {
    let executed = 0;
    const delivered = [];
    const host = createFakeHost({
      tools: () => { executed += 1; return {}; },
      replies: () => ({ tool: "search_listings", reply: (o) => (o.blocked ? `blocked:${o.blocked}` : "ran") }),
    });
    const turn = { text: "homes?", sessionKey: "agent:idx:whatsapp:direct:+15550000001", turnId: "t", deliver: async (p) => { delivered.push(p.text); return { messageId: "x", visibleReplySent: true }; } };
    if (beforeToolCall !== "absent") turn.beforeToolCall = beforeToolCall;
    await host.runInbound(turn);
    return { executed, delivered, events: host.events, decisions: host.decisions };
  };
  for (const [label, seam] of [
    ["bare true", () => true],
    ["bare false", () => false],
    ["number 1", () => 1],
    ["number 0", () => 0],
    ["undefined", () => undefined],
    ["null", () => null],
    ["block not boolean", () => ({ block: "no" })],
    ["throws", () => { throw new Error("seam failed"); }],
    ["absent", "absent"],
  ]) {
    const r = await runWith(seam);
    assert.equal(r.executed, 0, label);
    assert.equal(r.events.at(-1), label === "throws" ? "tool-blocked:seam-threw" : "tool-blocked:bad-decision", label);
    assert.deepEqual(r.delivered, [label === "throws" ? "blocked:seam-threw" : "blocked:bad-decision"], label);
  }
  const ok = await runWith(() => ({ block: false, marked: 1 }));
  assert.equal(ok.executed, 1);
  assert.deepEqual(ok.events, ["before-tool-call:search_listings", "tool-executed"]);
  assert.deepEqual(ok.delivered, ["ran"]);
  const blocked = await runWith(() => ({ block: true, reason: "mark-failed", tainted: 1 }));
  assert.equal(blocked.executed, 0);
  assert.deepEqual(blocked.events, ["before-tool-call:search_listings", "tool-blocked:mark-failed"]);
  // the live channel seam returns a decision the emulation accepts, so a real card tool runs once
  const transport = createFakeTransport();
  let executed = 0;
  const host = createFakeHost({ tools: () => { executed += 1; return {}; }, replies: () => ({ tool: "idx__search_listings", reply: (o) => (o.blocked ? "blocked" : "Here you go!") }) });
  const plugin = createChannelPlugin({ transport, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await transport.inbound({ accountId: "default", peerId: PEER, text: "homes?", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(host.decisions, [{ block: false, marked: 1 }]);
  assert.deepEqual(host.events, ["before-tool-call:idx__search_listings", "tool-executed"]);
  assert.equal(executed, 1);
  // and the prose after the (marked) card call is withheld on the card rule, not released
  assert.deepEqual(transport.sent.map((s) => s.text), [SAFE_TEXT]);
  assert.deepEqual(host.results[0].withheld, { reason: "idx-withheld:card-turn-requires-tokens" });
});

test("host-shape normalizePayload: called as deliver-prepare does", () => {
  const plugin = createChannelPlugin({ transport: createFakeTransport() });
  assert.deepEqual(plugin.outbound.normalizePayload({ payload: { text: "Hello!" }, cfg: {}, accountId: "default" }), { text: "Hello!" });
  const once = plugin.outbound.normalizePayload({ payload: { text: "Hello!", mediaUrl: "https://example.com/a.jpg" }, cfg: {}, accountId: "default" });
  assert.deepEqual(once, { text: SAFE_TEXT });
  assert.deepEqual(plugin.outbound.normalizePayload({ payload: once, cfg: {}, accountId: "default" }), once);
});

test("registered entry plugin has no working transport even after a passing self-check", async () => {
  const { api, registered } = createFakeApi({ cfg: DENY_CFG });
  entry.register(api);
  const plugin = registered[0].plugin;
  assert.equal(plugin.config.isConfigured({}, {}), false);
  await assert.rejects(plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" }), /no transport configured/);
});
