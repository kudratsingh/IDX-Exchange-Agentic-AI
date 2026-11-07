/**
 * The channel plugin object registered under channel id "whatsapp". Plain object,
 * no SDK import. It owns ingress (so the gate knows the user's turn) and routes
 * the inbound reply `deliver` into the same `outbound.sendText` every other
 * caller reaches; only `deliver` carries the trusted turn handle that `sendText`
 * requires. No `message` adapter, no `actions`, no media, polls or chunker.
 */

import { randomUUID } from "node:crypto";

import { CHANNEL_ID, isCardTool } from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { createIngress, normalizePeerId } from "./ingress.mjs";
import { createOutbound } from "./outbound.mjs";
import { unavailableTransport } from "./transport.mjs";

/**
 * @typedef {{ block: false, marked: number }
 *         | { block: true, reason: "no-turn-for-session" | "mark-failed" | "handler-error", tainted: number }} ToolCallDecision
 * @typedef {(args: { cfg: unknown, channel: "whatsapp", accountId: string, peer: { kind: "direct", id: string } })
 *   => { agentId: string, sessionKey: string }} RouteResolver
 * @typedef {(turn: { cfg: unknown, sessionKey: string, accountId: string, peerId: string, text: string, turnId: string,
 *   messageId: string | undefined, deliver: (payload: unknown, info?: unknown) => Promise<object>,
 *   beforeToolCall: (toolName: unknown) => ToolCallDecision }) => Promise<void>} InboundRunner
 */

/** @param {unknown} n @returns {number} a taint count, or -1 when the ingress gave none. */
function taintCount(n) {
  return typeof n === "number" && Number.isInteger(n) && n >= 0 ? n : -1;
}

/**
 * The hook-shaped card-tool mark (owner decision 16, blocking since the owner's
 * instruction of 2026-11-06). The install PR registers the returned function with the
 * host's `before_tool_call` hook, which fires BEFORE a tool executes. A successful
 * trusted mark is a precondition for executing a card tool: the handler returns a
 * decision object, never throws and never returns a bare number.
 *
 *   - `{ block: false, marked: 0 }` for a non-card tool name (a string `isCardTool`
 *     rejects): the tool runs, the turn stays on the ordinary rules.
 *   - `{ block: false, marked: n }`, n >= 1, when the tool is a card tool and
 *     `markCardToolForSession(ctx.sessionKey, toolName)` marked at least one open turn
 *     of that session (over-marking a concurrent turn is the safe direction).
 *   - `{ block: true, reason: "no-turn-for-session", tainted: m }` when the tool is a
 *     card tool and no turn was marked (unknown or mismatched session key, a non-string
 *     key, no open turn): correlation failed, so the affected turn cannot be identified.
 *     Before returning, `ingress.blockOpenTurns()` taints EVERY open turn of every peer
 *     (m is its count) so that whichever turn the call belonged to withholds its reply.
 *   - `{ block: true, reason: "handler-error", tainted: m }` when anything throws inside
 *     the handler (a throwing getter or Proxy trap on the event or context, a throwing
 *     ingress method) or the tool name is not a string (undefined, a number, an object):
 *     the tool cannot be identified, so it must not run, whatever kind it is. The taint
 *     is applied inside its own try/catch; if even that throws, `tainted` is -1.
 *
 * The source of the mark is the host's trusted tool-call event: never the model, never
 * the card store. The host's `before_tool_call` hook is fail-closed in OpenClaw 2026.9.5
 * (hook-runner-global, cited in the EVIDENCE_LOG survey), so a handler throw would
 * already block; this handler blocks explicitly with a decision object instead, so it can
 * taint the turns first. The exact block directive the host expects from a
 * `before_tool_call` handler is untraced: the install PR maps `{ block: true }` onto it
 * and proves with one real event that a blocked card tool does not execute. Nothing here
 * registers the handler with the host.
 * @param {ReturnType<typeof createIngress>} ingress
 * @returns {(event: unknown, ctx: unknown) => ToolCallDecision}
 */
export function createBeforeToolCallHandler(ingress) {
  if (
    !ingress ||
    typeof ingress.markCardToolForSession !== "function" ||
    typeof ingress.blockOpenTurns !== "function"
  ) {
    throw new Error("idx-whatsapp-channel: createBeforeToolCallHandler needs an ingress");
  }
  return (event, ctx) => {
    try {
      const toolName = event !== null && typeof event === "object" ? /** @type {any} */ (event).toolName : undefined;
      if (typeof toolName !== "string") throw new TypeError("tool name is not a string");
      if (!isCardTool(toolName)) return { block: false, marked: 0 };
      const sessionKey = ctx !== null && typeof ctx === "object" ? /** @type {any} */ (ctx).sessionKey : undefined;
      const marked = ingress.markCardToolForSession(sessionKey, toolName);
      if (typeof marked === "number" && marked >= 1) return { block: false, marked };
      // Correlation failed: the turn this call belongs to cannot be found, so every turn
      // that could be it is tainted before the block is returned.
      const tainted = taintCount(ingress.blockOpenTurns());
      return { block: true, reason: "no-turn-for-session", tainted };
    } catch {
      let tainted = -1;
      try {
        tainted = taintCount(ingress.blockOpenTurns());
      } catch {
        tainted = -1;
      }
      return { block: true, reason: "handler-error", tainted };
    }
  };
}

/**
 * @param {{
 *   transport?: import("./transport.mjs").Transport,
 *   cardResolver?: import("./card-resolver.mjs").CardResolver,
 *   now?: () => number,
 *   clock?: () => number,
 *   log?: { info?: Function, warn?: Function, error?: Function },
 *   resolveRoute?: RouteResolver,
 *   runInbound?: InboundRunner,
 *   ingress?: ReturnType<typeof createIngress>,
 *   verify?: import("./verifier.mjs").verifyReply,
 *   deadlineMs?: number,
 *   withholdMode?: "safe-text" | "silent",
 * }} [deps]
 */
export function createChannelPlugin({
  transport = unavailableTransport,
  cardResolver = nullCardResolver,
  now = Date.now,
  clock,
  log,
  resolveRoute,
  runInbound,
  ingress = createIngress({ now }),
  verify,
  deadlineMs,
  withholdMode,
} = {}) {
  const outbound = createOutbound({
    transport,
    ingress,
    cardResolver,
    log,
    ...(clock ? { clock } : {}),
    ...(verify ? { verify } : {}),
    ...(deadlineMs !== undefined ? { deadlineMs } : {}),
    ...(withholdMode !== undefined ? { withholdMode } : {}),
  });

  /**
   * @param {{ cfg: unknown, accountId: string }} scope
   * @param {import("./transport.mjs").InboundText} msg
   */
  async function onInbound(scope, msg) {
    if (!resolveRoute || !runInbound) {
      log?.warn?.({ component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason: "no-runner" });
      return;
    }
    const peerId = normalizePeerId(msg.peerId);
    const route = resolveRoute({
      cfg: scope.cfg,
      channel: CHANNEL_ID,
      accountId: scope.accountId,
      peer: { kind: "direct", id: peerId },
    });
    // The turn id is generated here, never taken from the message: WhatsApp message ids
    // come from the sender's client, so a peer-chosen id would let a re-sent id bind a
    // new turn to an earlier turn's card. The message id travels as metadata only.
    const turnId = randomUUID();
    const messageId = typeof msg.messageId === "string" && msg.messageId !== "" ? msg.messageId : undefined;
    // The trusted handle for this turn lives in this closure only. The host runner gets
    // the turn id as a string (metadata) and two functions that close over the handle; it
    // never receives the handle itself, so no runner-side code can bind a send to a turn.
    // Every other sender (tool, cron, heartbeat, CLI) holds no handle and is withheld.
    const handle = ingress.record(ingress.key(scope.accountId, peerId), {
      sessionKey: route.sessionKey,
      turnId,
      text: typeof msg.text === "string" ? msg.text : "",
      receivedAt: typeof msg.receivedAt === "number" ? msg.receivedAt : now(),
    });

    /** The inbound reply path. Same envelope, same sendText as every other caller; bound
     *  to this turn by its trusted handle, so a reply that lands after the peer's next
     *  message is verified against the message it answers. */
    const deliver = async (payload) => {
      const p = outbound.normalizePayload({ payload, cfg: scope.cfg, accountId: scope.accountId });
      if (!p) return { visibleReplySent: false, suppression: { reason: "idx-withheld:non-text-payload" } };
      const r = await outbound.sendText({
        cfg: scope.cfg,
        to: peerId,
        accountId: scope.accountId,
        text: p.text,
        replyToId: p.replyToId,
        turn: handle,
      });
      if ("outcome" in r && r.outcome === "not_sent") {
        return { visibleReplySent: false, suppression: { reason: `idx-withheld:${r.reason}` } };
      }
      if (typeof r.withheld === "string") {
        // SAFE_TEXT went out, so the reply is visible (no fallback retry); the reason rides along.
        return { messageId: r.messageId, visibleReplySent: true, withheld: { reason: `idx-withheld:${r.withheld}` } };
      }
      return { messageId: r.messageId, visibleReplySent: true };
    };

    /** The per-turn card-tool seam, named for when it fires: the host's before-tool-call
     *  event, BEFORE the tool executes (owner decision 16). It returns the same decision
     *  shape as `createBeforeToolCallHandler` and never throws: a non-card name is
     *  `{ block: false, marked: 0 }`; a card tool whose trusted mark landed on this turn
     *  is `{ block: false, marked: 1 }`; a card tool whose mark failed (the turn was
     *  evicted or expired, so the handle is no longer trusted) is
     *  `{ block: true, reason: "mark-failed", tainted }` after `blockTurn(handle)`
     *  (tainted is 1, or 0 when the turn is evicted or past the ingress TTL: it is already
     *  untrusted, so there is nothing left to taint and the gate withholds its replies
     *  `untrusted-turn`); a
     *  non-string tool name or a throw inside is `{ block: true, reason: "handler-error",
     *  tainted }` after `blockTurn(handle)` in its own try/catch. A card tool executes
     *  only after a successful mark; marks and taints are monotonic. */
    const beforeToolCall = (toolName) => {
      try {
        if (typeof toolName !== "string") throw new TypeError("tool name is not a string");
        if (!isCardTool(toolName)) return { block: false, marked: 0 };
        if (ingress.markCardTool(handle, toolName) === true) return { block: false, marked: 1 };
        const tainted = ingress.blockTurn(handle) === true ? 1 : 0;
        return { block: true, reason: "mark-failed", tainted };
      } catch {
        let tainted = -1;
        try {
          tainted = ingress.blockTurn(handle) === true ? 1 : 0;
        } catch {
          tainted = -1;
        }
        return { block: true, reason: "handler-error", tainted };
      }
    };

    await runInbound({
      cfg: scope.cfg,
      sessionKey: route.sessionKey,
      accountId: scope.accountId,
      peerId,
      text: typeof msg.text === "string" ? msg.text : "",
      turnId,
      messageId,
      deliver,
      beforeToolCall,
    });
  }

  return {
    id: CHANNEL_ID,
    meta: {
      label: "WhatsApp (IDX owned send path)",
      selectionLabel: "WhatsApp (IDX)",
      docsPath: "/extensions/idx-whatsapp-channel/README.md",
      blurb: "Project-owned WhatsApp DM channel; every send passes the reply verifier.",
    },
    capabilities: { chatTypes: ["direct"] },
    config: {
      listAccountIds: () => ["default"],
      resolveAccount: (_cfg, accountId) => ({ accountId: accountId ?? "default", enabled: true }),
      isConfigured: () => transport.isConfigured() === true,
    },
    outbound,
    gateway: {
      /** @param {{ cfg: unknown, accountId: string, abortSignal?: AbortSignal }} ctx */
      async startAccount(ctx) {
        const accountId = ctx?.accountId ?? "default";
        await transport.start({
          accountId,
          signal: ctx?.abortSignal,
          onInbound: (msg) => onInbound({ cfg: ctx?.cfg, accountId }, msg),
        });
      },
    },
  };
}
