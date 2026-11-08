/**
 * Host wiring of the plugin entry (WO-037 real-host replay, 2026-11-07). Offline: the host
 * runtime is a fake with the traced shapes of OpenClaw 2026.9.5. The real-host evidence is
 * produced by host-harness/run.mjs, which these tests do not run.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import entry, { createHostRunner, createPluginEntry, processIngress } from "./index.mjs";
import { CARD_TOOL_BLOCK_REASON, SAFE_TEXT } from "./constants.mjs";
import { selfCheck, stockPluginExcluded } from "./self-check.mjs";

const PEER = "+15555550101";
const SESSION = `agent:main:whatsapp:direct:${PEER}`;
const ALLOW_CFG = { plugins: { allow: ["idx-whatsapp-channel", "openai"] }, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER] } } };

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

test("HW-2 register with a host runtime: one channel with a runner, a before_tool_call hook, an after_tool_call hook (both with no matcher) and a before_prompt_build hook; the first refuses an unbound card call; the prompt hook adds nothing for an unknown run", () => {
  const { runtime } = fakeRuntime();
  const { api, channels, hooks } = fakeHostApi({ runtime });
  createPluginEntry().register(api);
  assert.equal(channels.length, 1);
  assert.deepEqual(hooks.map((h) => h.name), ["before_tool_call", "after_tool_call", "before_prompt_build"]);
  assert.equal(hooks[0].opts, undefined, "no matcher: every tool call reaches the handler");
  assert.equal(hooks[1].opts, undefined, "no matcher on the capture hook either");
  assert.equal(hooks[2].opts, undefined, "the ordinary prompt phase, no tool authority");
  assert.equal(hooks[2].handler({ prompt: "hi", messages: [] }, { runId: "dashboard-run", sessionKey: "agent:idx:main" }), undefined);
  assert.equal(hooks[1].handler({ toolName: "idx__search_listings", runId: "nope", result: {} }, { runId: "nope" }), undefined);
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

test("HW-7b a refused before_prompt_build registration is best effort: the gating hooks and the channel still register, and one prompt-hook-unavailable line is logged", () => {
  const { runtime } = fakeRuntime();
  const { api, channels, hooks } = fakeHostApi({ runtime });
  const warned = [];
  api.logger = { error() {}, info() {}, warn: (m) => warned.push(m) };
  api.on = (name, handler, opts) => {
    if (name === "before_prompt_build") throw new Error("conversation access not granted");
    hooks.push({ name, handler, opts });
  };
  createPluginEntry().register(api);
  assert.deepEqual(hooks.map((h) => h.name), ["before_tool_call", "after_tool_call"]);
  assert.equal(channels.length, 1);
  assert.deepEqual(warned, [{ component: "idx-whatsapp-channel.entry", event: "prompt-hook-unavailable" }]);
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

test("HW-8 (owned-channel install item 3; complete reply token): the entry's default card resolver is the turn-bound reply store, filled only by the after_tool_call hook from an admitted call's result, and released only as [[card:reply]]", async () => {
  const listing = { listing_key: 7, listing_id: "SYN7001", city: "Irvine", postal_code: "92618", list_price: 650000, bedrooms: 3 };
  // the server's approved reply (synthetic): released exactly (approved reply passthrough, 2026-11-08)
  const expected = "Showing 1 active listing on page 1, as of 2026-10-01\n\n*Irvine 92618*\n$650,000\n3 beds";
  const env = { ok: true, data: { listings: [listing] }, message: expected, provenance: { as_of: { active: "2026-10-01" } } };
  const result = { content: [{ type: "text", text: `structuredContent:\n${JSON.stringify(env, null, 2)}` }], details: {} };
  for (const [name, admit, reply, want] of [
    ["admitted call, token", true, "[[card:reply]]", expected],
    ["admitted call, old per-listing token", true, "[[card:SYN7001]]", SAFE_TEXT],
    ["no admitted call", false, "[[card:reply]]", SAFE_TEXT],
    ["admitted call, prose", true, "A 3 bed in Irvine at $650,000.", SAFE_TEXT],
  ]) {
    let hooks = null;
    const { runtime } = fakeRuntime({
      onDispatch: async ({ replyOptions, ctx, dispatcherOptions }) => {
        replyOptions.onAgentRunStart(replyOptions.runId);
        const event = { toolName: "idx__search_listings", params: {}, runId: replyOptions.runId, toolCallId: `call-${name}` };
        const hctx = { runId: replyOptions.runId, sessionKey: ctx.SessionKey, toolCallId: event.toolCallId };
        if (admit) assert.deepEqual(hooks[0].handler(event, hctx), { block: false, marked: 1 });
        // the after hook fires either way; without an admission it stores nothing
        hooks[1].handler({ ...event, result, durationMs: 1 }, hctx);
        await dispatcherOptions.deliver({ text: reply }, { kind: "final" });
      },
    });
    const t = capturingTransport();
    const host = fakeHostApi({ runtime });
    createPluginEntry({ transport: t.transport }).register(host.api);
    hooks = host.hooks;
    await host.channels[0].plugin.gateway.startAccount({ cfg: ALLOW_CFG, accountId: "default" });
    await t.inbound({ accountId: "default", peerId: PEER, text: "3 bed in Irvine", messageId: "m1", receivedAt: 1 });
    assert.deepEqual(t.sent.map((s) => s.text), [want], name);
  }
});

test("HW-9 (owned-channel install item 2): the entry's channel drops a sender outside channels.whatsapp allowFrom before the host runtime sees it", async () => {
  const { runtime, calls } = fakeRuntime();
  const t = capturingTransport();
  const host = fakeHostApi({ runtime });
  createPluginEntry({ transport: t.transport }).register(host.api);
  await host.channels[0].plugin.gateway.startAccount({ cfg: ALLOW_CFG, accountId: "default" });
  await t.inbound({ accountId: "default", peerId: "+15555550199", text: "hi", messageId: "m1", receivedAt: 1 });
  assert.equal(calls.routes.length, 0);
  assert.equal(calls.dispatches.length, 0);
  assert.equal(t.sent.length, 0);
});
