// Offline prototype only (WO-036, ADR-0015 proposed). Never installed or activated:
// there is deliberately no openclaw.plugin.json, package.json or config entry, and the
// module never installs or configures itself. If installed it would run with the
// gateway's privileges; these limits are code discipline, not a sandbox.
//
// Two hooks:
// - before_tool_call (fail-closed in OpenClaw 2026.9.5: a throw or timeout blocks the
//   tool) registers the run for this WhatsApp direct chat on every tool call, and for
//   the idx card tools writes the idx_delivery binding into their arguments, from host
//   fields only, and records the call in the run's ledger entry;
// - reply_payload_sending (FAIL-OPEN in OpenClaw 2026.9.5) withholds any payload whose
//   run was not registered for its session (no run id, unknown, other session,
//   expired), puts the stored cards in a WhatsApp reply when verify.mjs says so, and
//   otherwise withholds or cancels; any throw inside the handler cancels.
//
// Correlation uses before_tool_call only. before_agent_run is also fail-closed and
// carries ctx.runId, but its run id and session key were not shown to equal those
// on reply_payload_sending, so it is not used; it runs before inference and would not
// protect the outbound boundary anyway. Cost: a reply in a run that made no tool call
// is unknown correlation and is withheld.
//
// NOT A GUARANTEE (WO-036 "Architectural blocker"): the release decision binds only
// while the handler runs. If this plugin is absent, the handler times out, or the host
// rejects its result, OpenClaw delivers the model's text unchanged, and some sends
// skip the hook entirely. What does hold: with the plugin absent no card call is ever
// bound, so with IDX_CARD_DELIVERY=1 the server refuses it and the model never sees a
// card value or a token; with the switch off the server refuses any bound card call.
import { homedir } from "node:os";
import { join } from "node:path";
import { readRecord } from "./store.mjs";
import {
  CHANNEL_NONE, CHANNEL_WA, parseTokens, sessionDigest, verifyAndSubstitute,
} from "./verify.mjs";

export const CARD_TOOLS = new Set([
  "idx__search_listings", "idx__get_market_stats", "idx__find_similar_listings",
  "idx__recommend",
]);
export const BINDING_ARG = "idx_delivery";
// dmScope per-channel-peer names a WhatsApp direct chat agent:idx:whatsapp:direct:<peer>
// (OpenClaw 2026.9.5 dist/session-key-CPlMYURm.mjs:394-396).
const WHATSAPP_DM = /^agent:idx:whatsapp:direct:\S+$/;
const SAFE_ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const NONE = Object.freeze({ v: 1, channel: CHANNEL_NONE });
const BUSY = "IDX card delivery is busy; ask again in a moment.";
// The one directory read: card_store.DEFAULT_DIR. The server's IDX_CARD_DIR setting is
// not read here (it exists for tests); any other value there withholds every card.
export const CARD_DIRECTORY = join(homedir(), ".openclaw", "idx-cards");

/**
 * The binding for one card call. "wa" only for agent idx in a WhatsApp direct chat
 * whose turn targets the chat itself: in before_tool_call ctx.channelId is the
 * conversation target (equal to the session key on a dashboard turn), not a channel
 * name, and ctx.requester is not set on the embedded runner.
 * @param {any} event @param {any} ctx
 */
export function deriveBinding(event, ctx) {
  const found = deriveRun(event, ctx);
  const call = event?.toolCallId ?? ctx?.toolCallId;
  if (!found) return NONE;
  if (typeof call !== "string" || !SAFE_ID.test(call)) return NONE;
  return { v: 1, channel: CHANNEL_WA, ...found, call };
}

/**
 * The run a before_tool_call belongs to, for agent idx in a WhatsApp direct chat
 * whose turn targets the chat itself; undefined otherwise (never registered).
 * @param {any} event @param {any} ctx
 * @returns {{session: string, run: string} | undefined}
 */
export function deriveRun(event, ctx) {
  const sessionKey = ctx?.sessionKey;
  const run = event?.runId ?? ctx?.runId;
  if (ctx?.agentId !== "idx" || typeof sessionKey !== "string" || !WHATSAPP_DM.test(sessionKey)) {
    return undefined;
  }
  if (typeof ctx.channelId !== "string" || !ctx.channelId || ctx.channelId === sessionKey) {
    return undefined;
  }
  if (ctx.requester?.channel !== undefined && ctx.requester.channel !== "whatsapp") return undefined;
  if (event?.runId && ctx?.runId && event.runId !== ctx.runId) return undefined;
  if (typeof run !== "string" || !SAFE_ID.test(run)) return undefined;
  return { session: sessionDigest(sessionKey), run };
}

/**
 * Per-run record of the runs registered and the card calls bound in before_tool_call
 * (awaited, fail-closed), so the release step knows every run it will release for
 * and every card a run asked for, even when no record exists.
 * @param {{now: () => number, ttlMs?: number, maxRuns?: number}} options
 */
export function createLedger({ now, ttlMs = 30 * 60_000, maxRuns = 256 }) {
  /** @type {Map<string, {session: string, run: string, calls: string[], state: "open"|"released"|"failed", at: number}>} */
  const runs = new Map();
  const key = (session, run) => session + "\0" + run;
  const prune = () => {
    for (const [k, entry] of runs) if (now() - entry.at >= ttlMs) runs.delete(k);
  };
  /** @returns the run's entry, created if there is room; undefined when full */
  const register = (session, run) => {
    prune();
    const k = key(session, run);
    let entry = runs.get(k);
    if (!entry) {
      if (runs.size >= maxRuns) return undefined;
      entry = { session, run, calls: [], state: "open", at: now() };
      runs.set(k, entry);
    }
    entry.at = now();
    return entry;
  };
  return {
    runs,
    register(session, run) {
      return register(session, run) !== undefined;
    },
    bind(session, run, call) {
      const entry = register(session, run);
      if (!entry) return false;
      if (!entry.calls.includes(call)) entry.calls.push(call);
      return true;
    },
    get(session, run) {
      prune();
      return runs.get(key(session, run));
    },
    /** Every live registration, as the verifier's knownRuns. */
    knownRuns() {
      prune();
      return [...runs.values()].map((e) => ({ session: e.session, run: e.run, expires_ms: e.at + ttlMs }));
    },
    cardInSession(session) {
      prune();
      for (const entry of runs.values()) if (entry.session === session && entry.calls.length) return true;
      return false;
    },
  };
}

/**
 * @param {{directory: string, uid: number, now?: () => number, strict?: boolean,
 *   read?: typeof readRecord, verify?: typeof verifyAndSubstitute,
 *   ttlMs?: number}} options
 */
export function createDelivery({
  directory, uid, now = Date.now, strict = false, read = readRecord,
  verify = verifyAndSubstitute, ttlMs,
}) {
  const ledger = createLedger({ now, ttlMs });

  /**
   * before_tool_call: registers the run on every tool call (a full ledger leaves a
   * non-card run unregistered, so its reply is withheld); binds the four card tools,
   * and a full ledger blocks a card tool.
   */
  const beforeToolCall = (event, ctx) => {
    if (!CARD_TOOLS.has(event?.toolName)) {
      const found = deriveRun(event, ctx);
      if (found) ledger.register(found.session, found.run);
      return undefined;
    }
    const binding = deriveBinding(event, ctx);
    if (binding.channel === CHANNEL_WA && !ledger.bind(binding.session, binding.run, binding.call)) {
      return { block: true, blockReason: BUSY };
    }
    return { params: { [BINDING_ARG]: { ...binding } } };
  };

  /**
   * reply_payload_sending: never substitutes off WhatsApp; unknown correlation
   * withholds; any throw cancels. Binds only while the host runs it (fail-open hook).
   */
  const replyPayloadSending = (event, ctx) => {
    try {
      if (event?.channel !== "whatsapp" || ctx?.channelId !== "whatsapp") return undefined;
      const payload = event.payload ?? {};
      const sessionKey = event.sessionKey ?? ctx.sessionKey;
      const session = typeof sessionKey === "string" && sessionKey ? sessionDigest(sessionKey) : "";
      const ids = [event.runId, ctx.runId].filter((id) => typeof id === "string" && id);
      const run = ids.length && ids.every((id) => id === ids[0]) ? ids[0] : "";
      const entry = run ? ledger.get(session, run) : undefined;
      const text = typeof payload.text === "string" ? payload.text : "";
      const records = new Map();
      for (const [ref] of parseTokens(text).tokens) {
        const record = read(directory, ref, uid);
        if (record) records.set(ref, record);
      }
      const decision = verify(typeof payload.text === "string" ? payload.text : undefined, {
        channel: "whatsapp",
        session,
        run,
        nowMs: now(),
        records,
        boundCalls: entry ? [...entry.calls] : [],
        knownRuns: ledger.knownRuns(),
        runState: entry ? entry.state : "open",
        strict,
        cardInSession: ledger.cardInSession(session),
      });
      if (entry && decision.action === "substitute") entry.state = "released";
      if (entry && decision.action === "withhold") entry.state = "failed";
      if (decision.action === "substitute") return { payload: { ...payload, text: decision.text } };
      if (decision.action === "withhold") {
        return { payload: { text: decision.text }, reason: decision.reason };
      }
      if (decision.action === "drop") return { cancel: true, reason: decision.reason };
      return undefined;
    } catch {
      return { cancel: true };
    }
  };

  return { beforeToolCall, replyPayloadSending, ledger };
}

export default {
  id: "idx-card-delivery",
  name: "IDX card delivery OFFLINE PROTOTYPE (not installable)",
  /** @param {{on: (hook: string, handler: Function) => void}} api */
  register(api) {
    const delivery = createDelivery({
      directory: CARD_DIRECTORY,
      uid: process.getuid(),
    });
    api.on("before_tool_call", delivery.beforeToolCall);
    api.on("reply_payload_sending", delivery.replyPayloadSending);
  },
};
