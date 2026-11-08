/**
 * The channel plugin object registered under channel id "whatsapp". Plain object,
 * no SDK import. It owns ingress (so the gate knows the user's turn) and routes
 * the inbound reply `deliver` into the same `outbound.sendText` every other
 * caller reaches; only `deliver` carries the trusted turn handle that `sendText`
 * requires. No `message` adapter, no `actions`, no media, polls or chunker.
 *
 * Owner decision 19 (2026-11-07): each admitted inbound gets a channel-chosen run id
 * that the host must report back at run start before the turn counts as bound; card
 * tool calls are admitted one by one against that run id (`createBeforeToolCallHandler`);
 * a peer has at most one active turn, and an overlapping message gets BUSY_TEXT.
 * Owner decision 21 (2026-11-07): a refused card call tied to its own turn withholds that
 * turn's later replies; a refusal of unknown origin refuses the call only.
 */

import { randomUUID } from "node:crypto";

import { CARD_TOOL_BLOCK_REASON, CHANNEL_ID, isCardTool } from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { createIngress, normalizePeerId } from "./ingress.mjs";
import { createOutbound } from "./outbound.mjs";
import { unavailableTransport } from "./transport.mjs";

/**
 * @typedef {"unknown-run" | "run-unconfirmed" | "run-ended" | "turn-expired" | "session-mismatch"
 *   | "requester-mismatch" | "handler-error"} RefusalCode
 * @typedef {{ block: false, marked: 0 | 1 }
 *         | { block: true, blockReason: string, reason: RefusalCode, withheld: 0 | 1 }} ToolCallDecision
 * @typedef {(args: { cfg: unknown, channel: "whatsapp", accountId: string, peer: { kind: "direct", id: string } })
 *   => { agentId: string, sessionKey: string }} RouteResolver
 * @typedef {{ runId: string, onAgentRunStart: (runId: unknown, ...rest: unknown[]) => undefined }} ReplyOptions
 * @typedef {(turn: { cfg: unknown, sessionKey: string, accountId: string, peerId: string, text: string, turnId: string,
 *   messageId: string | undefined, deliver: (payload: unknown, info?: unknown) => Promise<object>,
 *   replyOptions: ReplyOptions }) => Promise<void>} InboundRunner
 */

/** The admission codes the ingress may return; anything else is mapped to handler-error. */
const REFUSAL_CODES = new Set([
  "unknown-run",
  "run-unconfirmed",
  "run-ended",
  "turn-expired",
  "session-mismatch",
  "requester-mismatch",
]);

/**
 * A refusal. `withheld` is 1 only when the ingress tied the refusal to its own turn and
 * marked that turn `cardCallRefused` (it answered `withheld === true`, strictly); 0 for
 * every refusal of unknown origin and for every handler-side refusal. The host reads only
 * `block`, `blockReason`, `params` and `requireApproval`, so `reason` and `withheld` stay
 * internal (tests and audit).
 * @param {RefusalCode} reason @param {boolean} [withheld] @returns {ToolCallDecision}
 */
function refuse(reason, withheld = false) {
  return { block: true, blockReason: CARD_TOOL_BLOCK_REASON, reason, withheld: withheld === true ? 1 : 0 };
}

/**
 * Builds the requester check from a requester value read once. `undefined` (the
 * bundled-MCP path, which carries no requester) means no check; anything else must be a
 * plain object naming the WhatsApp channel, a non-empty string sender that normalizes to
 * the turn's peer, and, when `accountId` is a string, the turn's account. Every field is
 * read exactly once, here, so a getter cannot answer differently later.
 * @param {unknown} requester
 * @returns {((peer: string, accountId: string) => boolean) | undefined}
 */
function requesterCheck(requester) {
  if (requester === undefined) return undefined;
  if (requester === null || typeof requester !== "object" || Array.isArray(requester)) return () => false;
  const { channel, senderId, accountId } = /** @type {any} */ (requester);
  if (typeof channel !== "string" || channel.trim().toLowerCase() !== CHANNEL_ID) return () => false;
  if (typeof senderId !== "string" || senderId.trim() === "") return () => false;
  const sender = normalizePeerId(senderId);
  const account = typeof accountId === "string" ? accountId : undefined;
  return (peer, turnAccountId) => sender === peer && (account === undefined || account === turnAccountId);
}

/**
 * The card-tool admission handler (owner decision 19, 2026-11-07). The install PR
 * registers the returned function with the host's `before_tool_call` hook, which fires
 * BEFORE a tool executes; the host runner reads `block` and `blockReason` and vetoes a
 * blocked call (host trace 2026-11-07). It is the single admission path: nothing else
 * marks a turn.
 *
 * Each field is read once: `event.toolName` first; for a card tool then `event.runId`,
 * `ctx.runId`, `ctx.sessionKey`, `ctx.requester`. Never throws, never returns a bare value.
 *
 *   - tool name not a string (or any throw, such as a getter): refused "handler-error".
 *   - a non-card tool (`isCardTool` false): `{ block: false, marked: 0 }`; no other field
 *     is read and no state is read or changed.
 *   - a card tool is admitted, `{ block: false, marked: 1 }` with THAT turn marked
 *     `cardToolCalled`, only when `event.runId` is a non-empty string equal to `ctx.runId`
 *     and names a stored, unexpired turn whose run is confirmed and not ended, the
 *     context's session key equals that turn's, and a requester, when present, names
 *     channel "whatsapp", the turn's peer and (if it gives one) the turn's account. A
 *     call with no requester (the bundled-MCP path) is admitted on run id and session key
 *     alone: owner decision 19 (a) keeps MCP pending a host-level test that a dashboard
 *     request reusing a valid WhatsApp run id and session key is refused.
 *   - otherwise the call is refused, `{ block: true, blockReason, reason, withheld }`, and
 *     never marks a turn `cardToolCalled`. Owner decision 21 (2026-11-07): a refusal the
 *     ingress ties to its originating turn (run id, live confirmed run and session key all
 *     bind it; today only `requester-mismatch`) marks THAT turn `cardCallRefused`, so the
 *     verifier withholds its later replies, and answers `withheld: 1`. Every refusal of
 *     unknown origin (`unknown-run`, `turn-expired`, `run-ended`, `run-unconfirmed`,
 *     `session-mismatch`, and `handler-error` on this side) refuses the call only, changes
 *     no turn and answers `withheld: 0`. A session key alone never suppresses a turn.
 * @param {ReturnType<typeof createIngress>} ingress
 * @returns {(event: unknown, ctx: unknown) => ToolCallDecision}
 */
export function createBeforeToolCallHandler(ingress) {
  if (!ingress || typeof ingress.admitCardCall !== "function") {
    throw new Error("idx-whatsapp-channel: createBeforeToolCallHandler needs an ingress");
  }
  return (event, ctx) => {
    try {
      const ev = event !== null && typeof event === "object" ? /** @type {any} */ (event) : undefined;
      const cx = ctx !== null && typeof ctx === "object" ? /** @type {any} */ (ctx) : undefined;
      const toolName = ev ? ev.toolName : undefined;
      if (typeof toolName !== "string") return refuse("handler-error");
      if (!isCardTool(toolName)) return { block: false, marked: 0 };
      const eventRunId = ev.runId;
      const ctxRunId = cx ? cx.runId : undefined;
      const sessionKey = cx ? cx.sessionKey : undefined;
      const requester = cx ? cx.requester : undefined;
      if (typeof eventRunId !== "string" || eventRunId === "" || ctxRunId !== eventRunId) return refuse("unknown-run");
      const requesterMatches = requesterCheck(requester);
      const result = ingress.admitCardCall({ runId: eventRunId, sessionKey, toolName, requesterMatches });
      if (result !== null && typeof result === "object" && result.admitted === true) return { block: false, marked: 1 };
      const reason = result !== null && typeof result === "object" ? result.reason : undefined;
      if (!REFUSAL_CODES.has(reason)) return refuse("handler-error");
      return refuse(reason, result.withheld === true);
    } catch {
      return refuse("handler-error");
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
  /** The busy sender, handed over once by createOutbound; never on the host-facing object. */
  let sendBusy = null;
  const outbound = createOutbound({
    transport,
    ingress,
    cardResolver,
    log,
    receiveBusySender: (fn) => {
      sendBusy = fn;
    },
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
    const key = ingress.key(scope.accountId, peerId);
    // One active turn per peer (owner decision 19 (b)). An overlapping message is not
    // recorded, never reaches the host (no route, no run, so no follow-up or steering
    // into the active run) and its text is neither stored nor logged; the peer gets the
    // fixed busy reply. The check and the record below run in one synchronous stretch,
    // with no await between them, so two inbounds cannot both pass it.
    // The outbound audit line for the busy send (outcome "busy") carries no text and no peer.
    if (ingress.hasActiveTurn(key)) {
      if (sendBusy) await sendBusy({ accountId: scope.accountId, to: peerId });
      return;
    }
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
    // The run id is generated here too and handed to the host as `replyOptions.runId`
    // (the host uses `replyOptions.runId` when given, host trace 2026-11-07). It is kept
    // privately by the ingress, never logged and never in a record snapshot.
    const runId = randomUUID();
    const messageId = typeof msg.messageId === "string" && msg.messageId !== "" ? msg.messageId : undefined;
    // The trusted handle for this turn lives in this closure only. The host runner gets
    // the turn id as a string (metadata) and functions that close over the handle; it
    // never receives the handle itself, so no runner-side code can bind a send to a turn.
    // Every other sender (tool, cron, heartbeat, CLI) holds no handle and is withheld.
    const handle = ingress.record(
      key,
      {
        sessionKey: route.sessionKey,
        turnId,
        text: typeof msg.text === "string" ? msg.text : "",
        receivedAt: typeof msg.receivedAt === "number" ? msg.receivedAt : now(),
      },
      { runId, accountId: scope.accountId, peerId },
    );
    if (handle === null) {
      log?.warn?.({ component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason: "record-refused" });
      return;
    }

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

    /** The host calls this once at run start with the run id it actually used
     *  (`replyOptions.onAgentRunStart(runId, ...)`, host trace 2026-11-07). Only exactly
     *  the issued id, on a stored, unexpired turn whose run has not ended, confirms the
     *  run; any other argument confirms nothing and never unconfirms. It always returns
     *  undefined (the string "reply-dispatch" would take over completion ownership) and
     *  never throws. */
    const onAgentRunStart = (id) => {
      try {
        if (typeof id === "string" && id === runId) ingress.confirmRun(handle, id);
      } catch {
        /* confirmation failure leaves the turn unbound: every reply on it is withheld */
      }
      return undefined;
    };

    try {
      await runInbound({
        cfg: scope.cfg,
        sessionKey: route.sessionKey,
        accountId: scope.accountId,
        peerId,
        text: typeof msg.text === "string" ? msg.text : "",
        turnId,
        messageId,
        deliver,
        replyOptions: { runId, onAgentRunStart },
      });
    } finally {
      // The run ends when the runner settles, resolved or rejected: its run id admits no
      // further card call and the peer's next message is admitted. `deliver` keeps working.
      ingress.endRun(handle);
    }
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
