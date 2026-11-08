/**
 * Host emulation for tests, written fresh from the cited OpenClaw 2026.9.5 lines.
 * No vendor code is copied. These helpers DOCUMENT the cited host rules so the
 * tests can show the skeleton's behaviour under them; they are not proof of the
 * host's behaviour. Never imported by runtime code.
 *
 * Cited lines (sha256-12 of the dist file):
 *  - reply dispatcher awaits deliver; a throw is 'failed-deliver' with onError once;
 *    a registered fallback is retried once through the SAME deliver
 *    (dist/reply-dispatcher-Dt2lN800.mjs:354, 383-390, 435-439, 3786ba69e33f);
 *  - result classification: an object whose visibleReplySent !== false is
 *    'delivered'; visibleReplySent === false is 'delivered-not-visible' and the
 *    fallback is tried once (reply-dispatcher:107-118);
 *  - a channel id registers once, first wins (loader-runtime-load-CdQ5OcQq.mjs:2955-2960,
 *    91180d699f64);
 *  - deny is checked right after plugins.enabled and before every other rule
 *    (config-normalization-shared-Btqp-2KT.mjs:82-88, e9ea9129fdff); deny ids are
 *    trimmed + lowercased strings (config-state-BxYVV2MR.mjs:19-22, 9c7da903e40f);
 *    'bundled-channel-configured' auto-enable applies to origin 'bundled' only
 *    (config-normalization-shared:113-116);
 *  - registerChannel is absent in cli-metadata mode (loader-runtime-load:2140-2147);
 *  - before_tool_call event/ctx shapes, the `{ block, blockReason }` directive, the run id
 *    (`replyOptions.runId ?? randomUUID()`) and `onAgentRunStart(runId)` at run start
 *    (host trace 2026-11-07, recorded in WO-037 "Install prerequisites").
 */

import { randomUUID } from "node:crypto";

/**
 * @param {{ deliver: (payload: unknown) => Promise<unknown>, onError?: (err: unknown) => void }} opts
 */
export function createEmulatedDispatcher({ deliver, onError }) {
  const counts = { deliverCalls: 0, delivered: 0, deliveredNotVisible: 0, failedDeliver: 0, onErrorCalls: 0 };

  function classify(result) {
    if (result !== null && typeof result === "object" && /** @type {any} */ (result).visibleReplySent !== false) {
      counts.delivered += 1;
      return "delivered";
    }
    counts.deliveredNotVisible += 1;
    return "delivered-not-visible";
  }

  async function once(payload) {
    counts.deliverCalls += 1;
    try {
      return { ok: true, outcome: classify(await deliver(payload)) };
    } catch (err) {
      counts.failedDeliver += 1;
      counts.onErrorCalls += 1;
      onError?.(err);
      return { ok: false, outcome: "failed-deliver" };
    }
  }

  return {
    /**
     * @param {unknown} payload
     * @param {unknown} [fallback]
     * @returns {Promise<"delivered" | "delivered-not-visible" | "failed-deliver">}
     */
    async enqueue(payload, fallback) {
      const first = await once(payload);
      if (first.outcome === "delivered" || fallback === undefined) return first.outcome;
      // The only retry: the registered fallback through the same deliver. No other route.
      const second = await once(fallback);
      return second.outcome;
    },
    counts,
  };
}

/** First registrant of a channel id wins; a second, different plugin gets 'conflict'. */
export function createEmulatedRegistry() {
  /** @type {Array<{ pluginId: string, plugin: any }>} */
  const channels = [];
  return {
    registerChannel(pluginId, plugin) {
      const existing = channels.find((e) => e.plugin.id === plugin.id);
      if (existing && existing.pluginId !== pluginId) return "conflict";
      channels.push({ pluginId, plugin });
      return "registered";
    },
    outboundFor(channelId) {
      return channels.find((e) => e.plugin.id === channelId)?.plugin.outbound;
    },
    channels,
  };
}

/** The host's normalization of a plugin policy id: trimmed, lowercased string, else dropped. */
export function hostNormalizePluginId(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : null;
}

/**
 * Activation outcome for one plugin id, in the host's rule order.
 * @param {unknown} cfg
 * @param {string} pluginId
 * @param {{ origin?: "bundled" | "config" | "workspace", channelId?: string }} [opts]
 */
export function emulatedActivation(cfg, pluginId, { origin = "bundled", channelId } = {}) {
  const plugins = /** @type {any} */ (cfg)?.plugins ?? {};
  const id = hostNormalizePluginId(pluginId);
  if (plugins.enabled === false) return "disabled:plugins-disabled";
  const deny = Array.isArray(plugins.deny) ? plugins.deny.map(hostNormalizePluginId).filter(Boolean) : [];
  if (deny.includes(id)) return "blocked-by-denylist";
  const entry = plugins.entries?.[id];
  if (entry?.enabled === false) return "disabled:entry";
  if (entry?.enabled === true) return "eligible";
  const allow = Array.isArray(plugins.allow) ? plugins.allow.map(hostNormalizePluginId) : [];
  if (allow.includes(id)) return "eligible";
  if (origin === "bundled" && channelId && /** @type {any} */ (cfg)?.channels?.[channelId]) {
    return "eligible:bundled-channel-configured";
  }
  if (origin === "workspace") return "disabled:workspace-needs-explicit-enable";
  return "disabled:not-selected";
}

/**
 * @param {{ cfg: unknown, registrationMode?: string }} opts
 */
export function createFakeApi({ cfg, registrationMode = "full" }) {
  /** @type {object[]} */
  const registered = [];
  const logs = { error: [], warn: [], info: [] };
  const api = {
    id: "idx-whatsapp-channel",
    config: cfg,
    pluginConfig: {},
    registrationMode,
    logger: {
      error: (m) => logs.error.push(m),
      warn: (m) => logs.warn.push(m),
      info: (m) => logs.info.push(m),
    },
  };
  if (registrationMode !== "cli-metadata") {
    api.registerChannel = (x) => registered.push(x);
  }
  return { api, registered, logs };
}

let boundRunSeq = 0;

/**
 * Records a turn the way the channel does and confirms its run the way the host does,
 * for gate-level tests that build turns by hand. Returns the trusted handle and the run
 * id. `confirm: false` leaves the run unconfirmed (every reply withheld "unbound-turn").
 * @param {ReturnType<import("../ingress.mjs").createIngress>} ingress
 * @param {{ accountId?: string, peerId: string, sessionKey?: string, turnId?: string, text?: string,
 *   receivedAt?: number, runId?: string, confirm?: boolean }} turn
 */
export function recordBoundTurn(ingress, { accountId = "default", peerId, sessionKey, turnId = "t1", text = "", receivedAt = 1, runId, confirm = true }) {
  boundRunSeq += 1;
  const id = runId ?? `run-${boundRunSeq}-${Math.random().toString(36).slice(2)}`;
  const handle = ingress.record(
    ingress.key(accountId, peerId),
    { sessionKey: sessionKey ?? `agent:idx:whatsapp:direct:${peerId}`, turnId, text, receivedAt },
    { runId: id, accountId, peerId },
  );
  if (handle === null) throw new Error("recordBoundTurn: record refused");
  if (confirm && ingress.confirmRun(handle, id) !== true) throw new Error("recordBoundTurn: confirm refused");
  return { handle, runId: id, sessionKey: sessionKey ?? `agent:idx:whatsapp:direct:${peerId}` };
}

/**
 * Fake host turn runner, emulating the traced host (OpenClaw 2026.9.5, host trace
 * 2026-11-07): per-channel-peer session keys, one reply per inbound.
 *
 * Runs: the run id is `turn.replyOptions.runId` when the channel passes one, a random id
 * when it does not, or `runIdFor(turn)` when the test supplies it (a host-minted follow-up
 * id, which never matches the channel's). At run start the runner calls
 * `turn.replyOptions.onAgentRunStart(runId)` once, unless `confirmRun` (a boolean or a
 * function of the turn) says no; the return values are kept in `runStartReturns`.
 *
 * Tool calls: the reply function `replies(text, turn, run)` (sync or async; an async one
 * keeps the run open while the test acts) may ask for one by returning
 * `{ tool: "<name>", reply: (outcome) => string | object }`, optionally with `requester`
 * (that one call's `ctx.requester`, for example a WhatsApp requester naming a different
 * sender on the run's own run id and session key: a tied refusal). Every tool request, from a
 * run or from `dashboardToolCall`, goes through `callTool`, which fires the registered
 * `hook` (the test passes `createBeforeToolCallHandler(ingress)`) with
 *   event `{ toolName, params: {}, runId, toolCallId }` and
 *   ctx `{ toolName, agentId: "idx", sessionKey, sessionId, runId, toolCallId }`, plus
 *   `requester` when `requesterFor(run)` (or the call's own `requester` option) gives one;
 *   with `noRunId: true` the call carries no `runId` key on either object (a dashboard
 *   request that names a WhatsApp session key but no run);
 * `rewrite({ event, ctx, run })` may replace either for forgery cases. The decision is
 * applied like the host: `block === true` -> the tool does not execute,
 * `tool-blocked:<reason>` is recorded and the reply gets `{ blocked: blockReason }`; a
 * throw -> blocked `seam-threw`; anything else (including null or a malformed value)
 * allows, executes `tools(name, run)` and records `tool-executed` or `tool-threw`. With no
 * hook registered the host runs the tool (`no-hook` is recorded first).
 *
 * `hold(run)`, when given, is awaited after the reply is delivered, so the run (and the
 * channel's active turn) stays open until the test settles it.
 * @param {{
 *   replies: (inboundText: string, turn: any, run: any) => unknown,
 *   tools?: (toolName: string, run: any) => unknown,
 *   hook?: (event: unknown, ctx: unknown) => unknown,
 *   requesterFor?: (run: any) => unknown,
 *   runIdFor?: (turn: any) => string,
 *   confirmRun?: boolean | ((turn: any) => boolean),
 *   rewrite?: (call: { event: any, ctx: any, run: any }) => { event?: unknown, ctx?: unknown } | void,
 *   hold?: (run: any) => Promise<unknown>,
 * }} opts
 */
export function createFakeHost({ replies, tools, hook, requesterFor, runIdFor, confirmRun = true, rewrite, hold }) {
  const results = [];
  const turns = [];
  const runs = [];
  const events = [];
  const decisions = [];
  const executions = [];
  const runStartReturns = [];
  let seq = 0;
  const runTool = tools ?? (() => { throw new Error("fake host has no tools"); });

  /**
   * One tool request through the registered hook, applied as the host applies it.
   * @param {any} run @param {string} toolName
   * @param {{ requester?: unknown, rewrite?: Function, noRunId?: boolean }} [opts]
   */
  async function callTool(run, toolName, opts = {}) {
    seq += 1;
    const toolCallId = `call-${seq}`;
    let event = { toolName, params: {}, runId: run.runId, toolCallId };
    let ctx = { toolName, agentId: "idx", sessionKey: run.sessionKey, sessionId: run.sessionId, runId: run.runId, toolCallId };
    if (opts.noRunId === true) {
      delete event.runId;
      delete ctx.runId;
    }
    const requester = "requester" in opts ? opts.requester : typeof requesterFor === "function" ? requesterFor(run) : undefined;
    if (requester !== undefined) ctx.requester = requester;
    const rw = opts.rewrite ?? rewrite;
    if (typeof rw === "function") {
      const out = rw({ event, ctx, run });
      if (out && typeof out === "object") {
        if ("event" in out) event = out.event;
        if ("ctx" in out) ctx = out.ctx;
      }
    }
    events.push(`before-tool-call:${toolName}`);
    let decision;
    if (typeof hook !== "function") {
      events.push("no-hook");
      decision = undefined;
    } else {
      try {
        decision = hook(event, ctx);
      } catch (error) {
        // The host runner treats a hook throw as a block (fail-closed).
        decision = { block: true, blockReason: "seam-threw", reason: "seam-threw", error };
      }
    }
    decisions.push(decision);
    if (decision !== null && typeof decision === "object" && decision.block === true) {
      events.push(`tool-blocked:${String(decision.reason ?? "blocked")}`);
      return { executed: false, outcome: { blocked: decision.blockReason } };
    }
    let outcome;
    try {
      outcome = { result: await runTool(toolName, run) };
      events.push("tool-executed");
    } catch (error) {
      outcome = { error };
      events.push("tool-threw");
    }
    executions.push({ toolName, sessionKey: run.sessionKey, runId: run.runId });
    return { executed: true, outcome };
  }

  return {
    resolveRoute: ({ peer }) => ({ agentId: "idx", sessionKey: `agent:idx:whatsapp:direct:${peer.id}` }),
    runInbound: async (turn) => {
      turns.push(turn);
      const ro = turn.replyOptions;
      const issued = ro && typeof ro.runId === "string" ? ro.runId : undefined;
      const runId = typeof runIdFor === "function" ? runIdFor(turn) : issued ?? randomUUID();
      const run = { runId, sessionKey: turn.sessionKey, sessionId: `session-${runs.length + 1}`, turn };
      runs.push(run);
      const confirm = typeof confirmRun === "function" ? confirmRun(turn) : confirmRun;
      if (confirm && ro && typeof ro.onAgentRunStart === "function") runStartReturns.push(ro.onAgentRunStart(runId));
      let r = await replies(turn.text, turn, run);
      if (r !== null && typeof r === "object" && typeof r.tool === "string" && typeof r.reply === "function") {
        const { tool, reply } = r;
        const { outcome } = await callTool(run, tool, "requester" in r ? { requester: r.requester } : {});
        r = await reply(outcome);
      }
      if (r !== undefined) {
        const result = await turn.deliver(typeof r === "string" ? { text: r } : r);
        results.push(result);
      }
      if (typeof hold === "function") await hold(run);
    },
    callTool,
    /**
     * A tool call from another agent session (dashboard, alert run) through the same hook.
     * @param {string} toolName
     * With `noRunId: true` the call carries no run id at all (event and ctx), whatever
     * `sessionKey` it names; otherwise `runId` defaults to a fresh random (foreign) id.
     * @param {{ sessionKey?: string, runId?: string, requester?: unknown, rewrite?: Function, noRunId?: boolean }} [opts]
     */
    dashboardToolCall(toolName, { sessionKey = "agent:idx:main", runId = randomUUID(), ...rest } = {}) {
      const run = { runId, sessionKey, sessionId: `dashboard-${randomUUID()}`, turn: null };
      return callTool(run, toolName, rest);
    },
    results,
    turns,
    runs,
    events,
    decisions,
    executions,
    runStartReturns,
  };
}
