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
 *  - registerChannel is absent in cli-metadata mode (loader-runtime-load:2140-2147).
 */

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

/**
 * Fake host turn runner: per-channel-peer session keys and one reply per inbound. The
 * reply function also receives the turn (channel-generated `turnId`, `messageId`
 * metadata, `sessionKey`), so a test can bind a card to the turn it answers.
 *
 * Tool calls: the reply function may ask for one by returning
 * `{ tool: "<name>", reply: (outcome) => string | object }`. The runner then fires the
 * before-tool-call seam FIRST (the host's before-tool-call event, which fires before
 * execution) and APPLIES ITS DECISION, as a fail-closed host does: by default the turn's
 * own `beforeToolCall(name)`; when the test passes `hook` (a session-keyed handler from
 * `createBeforeToolCallHandler`) the runner calls `hook({ toolName }, ctx)` instead,
 * with `ctx = { sessionKey: hookSession(turn) }` (`hookSession` defaults to the turn's
 * own session key) or `ctx = hookContext(turn)` when given. If the decision is
 * `{ block: true, reason }`, the runner records `tool-blocked:<reason>`, does NOT execute
 * the tool and asks `reply({ blocked: reason })` for the text; otherwise it executes
 * `tools(name, turn)` (which may throw or return an error-shaped result), records
 * `tool-executed` or `tool-threw`, and asks `reply({ result } | { error })`. A decision
 * that is not an object with a boolean `block` (a bare number, a boolean, undefined, null,
 * a missing seam) is treated as a block with reason `bad-decision`, and a seam or hook
 * that throws is a block with reason `seam-threw`: the emulation fails closed too.
 * `events` records the order (`before-tool-call:<name>`,
 * then `tool-blocked:<reason>` or `tool-executed`/`tool-threw`) and `decisions` the raw
 * decision values, so a test can assert the mark preceded execution or the block
 * prevented it.
 * @param {{
 *   replies: (inboundText: string, turn: any) => string | object | { tool: string, reply: (outcome: { result?: unknown, error?: unknown, blocked?: string }) => string | object },
 *   tools?: (toolName: string, turn: any) => unknown,
 *   hook?: (event: unknown, ctx: unknown) => unknown,
 *   hookSession?: (turn: any) => unknown,
 *   hookContext?: (turn: any) => unknown,
 * }} opts
 */
export function createFakeHost({ replies, tools, hook, hookSession, hookContext }) {
  const results = [];
  const turns = [];
  const events = [];
  const decisions = [];
  const runTool = tools ?? (() => { throw new Error("fake host has no tools"); });

  /** The before-tool-call decision for one tool request, through whichever seam the test chose. */
  function decide(turn, tool) {
    try {
      if (typeof hook === "function") {
        const ctx =
          typeof hookContext === "function"
            ? hookContext(turn)
            : { sessionKey: typeof hookSession === "function" ? hookSession(turn) : turn.sessionKey };
        return hook({ toolName: tool }, ctx);
      }
      if (typeof turn.beforeToolCall !== "function") {
        events.push("no-before-tool-call-seam");
        return undefined;
      }
      return turn.beforeToolCall(tool);
    } catch (error) {
      // The real hook runner is fail-closed: a throw blocks. Recorded so a test can see it.
      return { block: true, reason: "seam-threw", error };
    }
  }

  return {
    resolveRoute: ({ peer }) => ({ agentId: "idx", sessionKey: `agent:idx:whatsapp:direct:${peer.id}` }),
    runInbound: async (turn) => {
      turns.push(turn);
      let r = replies(turn.text, turn);
      if (r !== null && typeof r === "object" && typeof r.tool === "string" && typeof r.reply === "function") {
        const { tool, reply } = r;
        events.push(`before-tool-call:${tool}`);
        const decision = decide(turn, tool);
        decisions.push(decision);
        const wellFormed = decision !== null && typeof decision === "object" && typeof decision.block === "boolean";
        if (!wellFormed || decision.block === true) {
          const reason = wellFormed ? String(decision.reason) : "bad-decision";
          events.push(`tool-blocked:${reason}`);
          r = reply({ blocked: reason });
        } else {
          let outcome;
          try {
            outcome = { result: await runTool(tool, turn) };
            events.push("tool-executed");
          } catch (error) {
            outcome = { error };
            events.push("tool-threw");
          }
          r = reply(outcome);
        }
      }
      const result = await turn.deliver(typeof r === "string" ? { text: r } : r);
      results.push(result);
    },
    results,
    turns,
    events,
    decisions,
  };
}
