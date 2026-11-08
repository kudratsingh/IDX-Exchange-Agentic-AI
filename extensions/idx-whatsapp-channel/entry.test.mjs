/**
 * Host wiring of the plugin entry (WO-037 real-host replay, 2026-11-07). Offline: the host
 * runtime is a fake with the traced shapes of OpenClaw 2026.9.5. The real-host evidence is
 * produced by host-harness/run.mjs, which these tests do not run.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import entry, { createHostRunner, createPluginEntry, processIngress } from "./index.mjs";
import { CARD_TOOL_BLOCK_REASON } from "./constants.mjs";
import { selfCheck, stockPluginExcluded } from "./self-check.mjs";

const PEER = "+15555550101";
const SESSION = `agent:main:whatsapp:direct:${PEER}`;
const ALLOW_CFG = { plugins: { allow: ["idx-whatsapp-channel", "openai"] } };

/** A fake host runtime that records what the entry hands it. */
function fakeRuntime({ onDispatch } = {}) {
  const calls = { routes: [], contexts: [], dispatches: [] };
  const runtime = {
    channel: {
      routing: {
        resolveAgentRoute: (args) => {
          calls.routes.push(args);
          return { agentId: "main", sessionKey: SESSION, extra: "ignored" };
        },
      },
      reply: {
        finalizeInboundContext: (ctx) => {
          calls.contexts.push(ctx);
          return { ...ctx, finalized: true };
        },
        dispatchReplyWithBufferedBlockDispatcher: async (args) => {
          calls.dispatches.push(args);
          if (onDispatch) await onDispatch(args);
        },
      },
    },
  };
  return { runtime, calls };
}

/** A host api with a runtime and hook registry. */
function fakeHostApi({ cfg = ALLOW_CFG, runtime, registrationMode = "full", withOn = true } = {}) {
  const channels = [];
  const hooks = [];
  const api = {
    id: "idx-whatsapp-channel",
    config: cfg,
    pluginConfig: {},
    registrationMode,
    logger: { error() {}, warn() {}, info() {} },
    registerChannel: (x) => channels.push(x),
    runtime,
  };
  if (withOn) api.on = (name, handler, opts) => hooks.push({ name, handler, opts });
  return { api, channels, hooks };
}

/** A transport whose start hands the harness the inbound callback and resolves at once. */
function capturingTransport() {
  const sent = [];
  let onInbound = null;
  return {
    sent,
    inbound: (msg) => onInbound(msg),
    transport: {
      isConfigured: () => true,
      start: async (opts) => {
        onInbound = opts.onInbound;
      },
      sendText: async (req) => {
        sent.push(req);
        return { messageId: `m${sent.length}` };
      },
      stop: async () => {},
    },
  };
}

test("HW-1 createHostRunner: null without the host runtime; with it, a direct WhatsApp DM context and replyOptions passed through unchanged", async () => {
  assert.equal(createHostRunner({}), null);
  assert.equal(createHostRunner({ runtime: { channel: { routing: {}, reply: {} } } }), null);
  const { runtime, calls } = fakeRuntime();
  const runner = createHostRunner({ runtime, logger: {} });
  assert.ok(runner);
  assert.deepEqual(runner.resolveRoute({ cfg: {}, channel: "whatsapp", accountId: "default", peer: { kind: "direct", id: PEER } }), { agentId: "main", sessionKey: SESSION });
  const replyOptions = { runId: "r-1", onAgentRunStart: () => undefined };
  const deliver = async () => ({ visibleReplySent: true });
  await runner.runInbound({ cfg: { a: 1 }, sessionKey: SESSION, accountId: "default", peerId: PEER, text: "hi", turnId: "t", messageId: "m", deliver, replyOptions });
  const ctx = calls.contexts[0];
  for (const [k, v] of Object.entries({ Body: "hi", BodyForAgent: "hi", From: PEER, To: PEER, SenderId: PEER, SessionKey: SESSION, AccountId: "default", ChatType: "direct", Provider: "whatsapp", Surface: "whatsapp", OriginatingChannel: "whatsapp", OriginatingTo: PEER, MessageSid: "m", CommandAuthorized: false })) {
    assert.equal(ctx[k], v, k);
  }
  const d = calls.dispatches[0];
  assert.equal(d.replyOptions, replyOptions, "replyOptions is the channel's own object");
  assert.equal(d.ctx.finalized, true);
  assert.deepEqual(d.cfg, { a: 1 });
  assert.deepEqual(await d.dispatcherOptions.deliver({ text: "x" }, { kind: "final" }), { visibleReplySent: true });
});

test("HW-2 register with a host runtime: one channel with a runner and one before_tool_call hook with no matcher, which refuses an unbound card call", () => {
  const { runtime } = fakeRuntime();
  const { api, channels, hooks } = fakeHostApi({ runtime });
  createPluginEntry().register(api);
  assert.equal(channels.length, 1);
  assert.equal(hooks.length, 1);
  assert.equal(hooks[0].name, "before_tool_call");
  assert.equal(hooks[0].opts, undefined, "no matcher: every tool call reaches the handler");
  const h = hooks[0].handler;
  assert.deepEqual(h({ toolName: "message", runId: "x" }, { runId: "x" }), { block: false, marked: 0 });
  assert.deepEqual(h({ toolName: "idx__search_listings", runId: "nope" }, { runId: "nope", sessionKey: SESSION }), { block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason: "unknown-run", withheld: 0 });
});

test("HW-3 register refuses a host runtime without api.on (a runner without the hook would run card tools unbound)", () => {
  const { runtime } = fakeRuntime();
  const { api, channels } = fakeHostApi({ runtime, withOn: false });
  assert.throws(() => createPluginEntry().register(api), /before_tool_call hook unavailable/);
  assert.equal(channels.length, 0);
  // No runtime and no api.on: the offline skeleton shape still registers, with no runner.
  const bare = fakeHostApi({ runtime: undefined, withOn: false });
  createPluginEntry().register(bare.api);
  assert.equal(bare.channels.length, 1);
});

test("RH-1 (real-host regression): a hook registered by a separately loaded copy of the entry admits the card call of a turn the other copy's channel recorded", async () => {
  // The host loaded the module more than once in one gateway ("full" and "discovery"),
  // kept every copy's hook and ran one copy's channel; a per-copy ingress refused every
  // genuine card call "unknown-run". A query string gives Node a separate module instance.
  const copy = await import("./index.mjs?copy=rh1");
  assert.notEqual(copy.createPluginEntry, createPluginEntry, "a separate module instance");
  assert.equal(copy.processIngress(), processIngress(), "one ingress per process");

  let decision = null;
  let hookFromOtherCopy = null;
  const { runtime } = fakeRuntime({
    onDispatch: async ({ replyOptions, ctx }) => {
      replyOptions.onAgentRunStart(replyOptions.runId);
      decision = hookFromOtherCopy({ toolName: "idx__search_listings", runId: replyOptions.runId }, { runId: replyOptions.runId, sessionKey: ctx.SessionKey });
    },
  });
  const t = capturingTransport();
  const full = fakeHostApi({ runtime, registrationMode: "full" });
  createPluginEntry({ transport: t.transport }).register(full.api);
  const discovery = fakeHostApi({ runtime, registrationMode: "discovery" });
  copy.createPluginEntry().register(discovery.api);
  hookFromOtherCopy = discovery.hooks[0].handler;

  await full.channels[0].plugin.gateway.startAccount({ cfg: ALLOW_CFG, accountId: "default" });
  await t.inbound({ accountId: "default", peerId: PEER, text: "show me a 3 bed", messageId: "m1", receivedAt: 1 });
  assert.deepEqual(decision, { block: false, marked: 1 });
});

test("HW-4 processIngress: one frozen process-wide object behind a non-writable, non-configurable, non-enumerable key", () => {
  const a = processIngress();
  assert.equal(processIngress(), a);
  assert.ok(Object.isFrozen(a), "members cannot be replaced");
  assert.throws(() => {
    "use strict";
    a.admitCardCall = () => ({ admitted: true });
  }, TypeError);
  const key = Symbol.for("idx-whatsapp-channel.ingress.v1");
  const desc = Object.getOwnPropertyDescriptor(globalThis, key);
  assert.equal(desc.writable, false);
  assert.equal(desc.configurable, false);
  assert.equal(desc.enumerable, false);
  assert.throws(() => {
    "use strict";
    globalThis[key] = {};
  }, TypeError);
  assert.equal(processIngress(), a);
});

test("HW-7 a hook registration that throws leaves no channel registered", () => {
  const { runtime } = fakeRuntime();
  const { api, channels } = fakeHostApi({ runtime });
  api.on = () => {
    throw new Error("host refused the hook");
  };
  assert.throws(() => createPluginEntry().register(api), /host refused the hook/);
  assert.equal(channels.length, 0);
});

test("HW-5 self-check allow-list form: an explicit allow list that names this plugin and not the stock one excludes the stock plugin", () => {
  for (const cfg of [ALLOW_CFG, { plugins: { allow: [" IDX-WhatsApp-Channel "] } }, { plugins: { deny: ["whatsapp"] } }]) {
    assert.equal(stockPluginExcluded(cfg), true, JSON.stringify(cfg));
    assert.deepEqual(selfCheck(cfg), { ok: true });
  }
  for (const cfg of [
    { plugins: { allow: [] } },
    { plugins: { allow: ["openai"] } },
    { plugins: { allow: ["idx-whatsapp-channel", "whatsapp"] } },
    { plugins: { allow: ["idx-whatsapp-channel", " WhatsApp "] } },
    { plugins: { allow: "idx-whatsapp-channel" } },
    { plugins: {} },
    { plugins: { allow: ["idx-whatsapp-channel"], entries: { whatsapp: { enabled: true } } } },
    { plugins: { allow: ["idx-whatsapp-channel"], entries: { " WhatsApp ": { enabled: true } } } },
  ]) {
    assert.equal(stockPluginExcluded(cfg), false, JSON.stringify(cfg));
    assert.deepEqual(selfCheck(cfg), { ok: false, reason: "stock-whatsapp-not-denied" });
  }
});

test("HW-6 the default export is a production entry: unavailable transport, so the channel reports unconfigured", () => {
  const { runtime } = fakeRuntime();
  const { api, channels } = fakeHostApi({ runtime });
  entry.register(api);
  assert.equal(channels[0].plugin.config.isConfigured(), false);
});
