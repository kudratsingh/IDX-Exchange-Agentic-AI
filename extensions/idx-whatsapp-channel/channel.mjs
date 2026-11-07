/**
 * The channel plugin object registered under channel id "whatsapp". Plain object,
 * no SDK import. It owns ingress (so the gate knows the user's turn) and routes
 * the inbound reply `deliver` into the same `outbound.sendText` every other
 * caller uses. No `message` adapter, no `actions`, no media, polls or chunker.
 */

import { randomUUID } from "node:crypto";

import { CHANNEL_ID } from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { createIngress, normalizePeerId } from "./ingress.mjs";
import { createOutbound } from "./outbound.mjs";
import { unavailableTransport } from "./transport.mjs";

/**
 * @typedef {(args: { cfg: unknown, channel: "whatsapp", accountId: string, peer: { kind: "direct", id: string } })
 *   => { agentId: string, sessionKey: string }} RouteResolver
 * @typedef {(turn: { cfg: unknown, sessionKey: string, accountId: string, peerId: string, text: string, turnId: string,
 *   messageId: string | undefined, deliver: (payload: unknown, info?: unknown) => Promise<object>,
 *   noteToolCall: (toolName: unknown) => boolean }) => Promise<void>} InboundRunner
 */

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

    /** The card-tool seam. The install PR wires this to the host's tool-call observation
     *  (the stock hooks are observation-only here, so this cannot stop a tool, it only
     *  tightens the verifier for the turn: once a card tool ran, only verified card tokens
     *  may leave). A missed mark leaves the turn on the ordinary rules; whether the hook
     *  or the card store is the source of the mark is owner decision 16. Marking is
     *  monotonic and only accepts CARD_TOOLS names. */
    const noteToolCall = (toolName) => ingress.markCardTool(handle, toolName);

    await runInbound({
      cfg: scope.cfg,
      sessionKey: route.sessionKey,
      accountId: scope.accountId,
      peerId,
      text: typeof msg.text === "string" ? msg.text : "",
      turnId,
      messageId,
      deliver,
      noteToolCall,
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
