import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createChannelPlugin } from "./channel.mjs";
import { SAFE_TEXT, TRANSPORT_METHODS } from "./constants.mjs";
import entry from "./index.mjs";
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

test("FC-single-call-site (source): one transport.sendText( in outbound.mjs with sealed.text; only four transport members; no bracket access, Reflect or seal elsewhere", () => {
  let callSites = 0;
  const members = new Set();
  for (const f of RUNTIME_FILES) {
    const s = code(f);
    const sends = s.match(/\btransport\s*\.\s*sendText\s*\(/g) ?? [];
    callSites += sends.length;
    if (sends.length) assert.equal(f, "outbound.mjs");
    // (?<!\/) skips the module path "./transport.mjs" in import statements
    for (const m of s.matchAll(/(?<!\/)\btransport\s*\.\s*([A-Za-z_$][\w$]*)/g)) members.add(m[1]);
    assert.ok(!/\btransport\s*\[/.test(s), `${f} indexes transport`);
    assert.ok(!/Reflect\s*\.\s*apply/.test(s), `${f} uses Reflect.apply`);
    if (f !== "outbound.mjs") assert.ok(!/\bseal\s*\(/.test(s), `${f} seals`);
  }
  assert.equal(callSites, 1);
  // The runtime uses start, sendText and isConfigured; stop is part of the interface
  // but unused here (the host stops an account through abortSignal).
  for (const m of members) assert.ok(TRANSPORT_METHODS.includes(m), `transport.${m} is not an allowed member`);
  assert.deepEqual([...members].sort(), ["isConfigured", "sendText", "start"]);
  const out = code("outbound.mjs");
  assert.match(out, /await transport\.sendText\(\{\s*accountId,\s*to: ctx\.to,\s*text: sealed\.text,/s);
  assert.equal((out.match(/\bseal\(/g) ?? []).length, 3); // definition, release, safe-text
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
  const host = createFakeHost({ replies: () => "Hello!" });
  const plugin = createChannelPlugin({ transport: proxied, resolveRoute: host.resolveRoute, runInbound: host.runInbound });
  plugin.config.isConfigured({}, {});
  await plugin.gateway.startAccount({ cfg: DENY_CFG, accountId: "default" });
  await fake.inbound({ accountId: "default", peerId: PEER, text: "hi", messageId: "m1", receivedAt: 1 });
  await plugin.outbound.sendText({ to: PEER, text: "Anything else?", accountId: "default" });
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

test("FC-same-outbound-for-tool-cron-heartbeat: one adapter object, one verification", async () => {
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
  // the inbound deliver closes over the very same outbound: identity shown by behaviour below
  const tool = { cfg: DENY_CFG, to: PEER, text: "Do you mean 3 or 4 bedrooms?", accountId: "default" };
  const cron = { cfg: DENY_CFG, to: "whatsapp:+15550000001", text: "Good morning! Any new wishes for your search?", accountId: "default", threadId: undefined };
  const heartbeat = { cfg: DENY_CFG, to: "15550000001@s.whatsapp.net", text: "There are 12 new homes today", accountId: "default" };
  const stranger = { cfg: DENY_CFG, to: "+15550000002", text: "Hello!", accountId: "default" };

  assert.equal(typeof (await outbound.sendText(tool)).messageId, "string");
  assert.equal(typeof (await outbound.sendText(cron)).messageId, "string");
  assert.equal(typeof (await outbound.sendText(heartbeat)).messageId, "string");
  assert.deepEqual(await outbound.sendText(stranger), { outcome: "not_sent", reason: "no-inbound-record" });
  await captured.deliver({ text: "Anything else?" });

  assert.deepEqual(transport.sent.map((s) => s.text), [
    "Do you mean 3 or 4 bedrooms?",
    "Good morning! Any new wishes for your search?",
    SAFE_TEXT,
    "Anything else?",
  ]);
  assert.ok(!transport.sent.some((s) => s.to === "+15550000002"));
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
