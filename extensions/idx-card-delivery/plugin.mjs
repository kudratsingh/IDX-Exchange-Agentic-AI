// Offline prototype only (WO-036, ADR-0015 proposed). Never installed or activated:
// there is deliberately no openclaw.plugin.json, package.json or config entry, and the
// module never installs or configures itself. If installed it would run with the
// gateway's privileges; these limits are code discipline, not a sandbox.
//
// Two hooks:
// - before_tool_call (fail-closed in OpenClaw 2026.9.5: a throw or timeout blocks the
//   tool) writes the idx_delivery binding into the idx card tools' arguments, from
//   host fields only, and records the call in a per-run ledger;
// - reply_payload_sending (fail-open: skipped on a throw or timeout) puts the stored
//   cards in a WhatsApp reply when verify.mjs says so, else withholds or cancels.
// A skipped release can only send the model's text, which on a card turn is a token.
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

/**
 * The binding for one card call. "wa" only for agent idx in a WhatsApp direct chat
 * whose turn targets the chat itself: in before_tool_call ctx.channelId is the
 * conversation target (equal to the session key on a dashboard turn), not a channel
 * name, and ctx.requester is not set on the embedded runner.
 * @param {any} event @param {any} ctx
 */
export function deriveBinding(event, ctx) {
  const sessionKey = ctx?.sessionKey;
  const run = event?.runId ?? ctx?.runId;
  const call = event?.toolCallId ?? ctx?.toolCallId;
  if (ctx?.agentId !== "idx" || typeof sessionKey !== "string" || !WHATSAPP_DM.test(sessionKey)) {
    return NONE;
  }
  if (typeof ctx.channelId !== "string" || !ctx.channelId || ctx.channelId === sessionKey) {
    return NONE;
  }
  if (ctx.requester?.channel !== undefined && ctx.requester.channel !== "whatsapp") return NONE;
  if (event?.runId && ctx?.runId && event.runId !== ctx.runId) return NONE;
  if (typeof run !== "string" || !SAFE_ID.test(run)) return NONE;
  if (typeof call !== "string" || !SAFE_ID.test(call)) return NONE;
  return { v: 1, channel: CHANNEL_WA, session: sessionDigest(sessionKey), run, call };
}

/**
 * Per-run record of the card calls bound in before_tool_call (awaited, fail-closed),
 * so the release step knows every card a run asked for even when no record exists.
 * @param {{now: () => number, ttlMs?: number, maxRuns?: number}} options
 */
export function createLedger({ now, ttlMs = 30 * 60_000, maxRuns = 256 }) {
  /** @type {Map<string, {session: string, run: string, calls: string[], state: "open"|"released"|"failed", at: number}>} */
  const runs = new Map();
  const key = (session, run) => session + "\0" + run;
  const prune = () => {
    for (const [k, entry] of runs) if (now() - entry.at > ttlMs) runs.delete(k);
  };
  return {
    runs,
    bind(session, run, call) {
      prune();
      const k = key(session, run);
      let entry = runs.get(k);
      if (!entry) {
        if (runs.size >= maxRuns) return false;
        entry = { session, run, calls: [], state: "open", at: now() };
        runs.set(k, entry);
      }
      if (!entry.calls.includes(call)) entry.calls.push(call);
      entry.at = now();
      return true;
    },
    get(session, run) {
      prune();
      return runs.get(key(session, run));
    },
    /** The newest open run of the session (used only when a payload has no run id). */
    latestOpen(session) {
      prune();
      let found;
      for (const entry of runs.values()) {
        if (entry.session === session && entry.state === "open"
            && (!found || entry.at >= found.at)) found = entry;
      }
      return found;
    },
    cardInSession(session) {
      prune();
      for (const entry of runs.values()) if (entry.session === session) return true;
      return false;
    },
  };
}

/**
 * @param {{directory: string, uid: number, now?: () => number, strict?: boolean,
 *   read?: typeof readRecord}} options
 */
export function createDelivery({ directory, uid, now = Date.now, strict = false, read = readRecord }) {
  const ledger = createLedger({ now });

  /** before_tool_call: a binding for the four card tools; a full ledger blocks. */
  const beforeToolCall = (event, ctx) => {
    if (!CARD_TOOLS.has(event?.toolName)) return undefined;
    const binding = deriveBinding(event, ctx);
    if (binding.channel === CHANNEL_WA && !ledger.bind(binding.session, binding.run, binding.call)) {
      return { block: true, blockReason: BUSY };
    }
    return { params: { [BINDING_ARG]: { ...binding } } };
  };

  /** reply_payload_sending: never substitutes off WhatsApp; any throw cancels. */
  const replyPayloadSending = (event, ctx) => {
    try {
      if (event?.channel !== "whatsapp" || ctx?.channelId !== "whatsapp") return undefined;
      const payload = event.payload ?? {};
      const sessionKey = event.sessionKey ?? ctx.sessionKey;
      const session = typeof sessionKey === "string" && sessionKey ? sessionDigest(sessionKey) : "";
      const ids = [event.runId, ctx.runId].filter((id) => typeof id === "string" && id);
      const run = ids.length && ids.every((id) => id === ids[0]) ? ids[0] : "";
      const entry = run ? ledger.get(session, run) : ledger.latestOpen(session);
      const text = typeof payload.text === "string" ? payload.text : "";
      const records = new Map();
      for (const [ref] of parseTokens(text).tokens) {
        const record = read(directory, ref, uid);
        if (record) records.set(ref, record);
      }
      const decision = verifyAndSubstitute(payload.text, {
        channel: "whatsapp",
        session,
        run,
        nowMs: now(),
        records,
        boundCalls: entry ? [...entry.calls] : [],
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
      directory: join(homedir(), ".openclaw", "idx-cards"),
      uid: process.getuid(),
    });
    api.on("before_tool_call", delivery.beforeToolCall);
    api.on("reply_payload_sending", delivery.replyPayloadSending);
  },
};
