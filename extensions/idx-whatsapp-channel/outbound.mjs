/**
 * The outbound gate. Every send path (inbound reply deliver, message tool, cron,
 * heartbeat, CLI) ends in `sendText` here, and `sendText` holds the only
 * `transport.sendText(` call expression in the runtime. The call receives sealed
 * text only: a verdict the verifier released and the gate accepted, or SAFE_TEXT.
 * A send reaches the verifier only when it carries the trusted turn handle the ingress
 * minted; in this skeleton only the channel's own inbound `deliver` holds one.
 *
 * The busy reply (one active turn per peer, owner decision 19 (b)) goes through the same
 * private `transmit` and so the same call site. It only ever sends the BUSY_TEXT
 * constant, and it is not a member of the returned host-facing object: the channel
 * receives it once, at construction, through the `receiveBusySender` callback.
 */

import {
  BUSY_TEXT,
  MAX_TEXT_LENGTH,
  SAFE_TEXT,
  VERIFIER_DEADLINE_MS,
  WITHHOLD_MODE,
} from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { normalizePeerId } from "./ingress.mjs";
import { isWellFormedVerdict, verifyReply } from "./verifier.mjs";

/** @typedef {import("./transport.mjs").Transport} Transport */
/** @typedef {import("./card-resolver.mjs").CardResolver} CardResolver */
/** @typedef {ReturnType<import("./ingress.mjs").createIngress>} Ingress */

const SEALED = Symbol("idx-whatsapp-channel.sealed");

/** @param {string} text */
function seal(text) {
  return Object.freeze({ [SEALED]: true, text });
}

/** @param {unknown} v */
function isSealed(v) {
  return v !== null && typeof v === "object" && /** @type {any} */ (v)[SEALED] === true;
}

/**
 * A payload field is absent when it carries no content: undefined, null, false,
 * the empty string or an empty array. The message tool sends `audioAsVoice: false`
 * and `mediaUrl: undefined` on every text send; the inbound reply normalizer emits
 * `mediaUrls, mediaUrl, presentation, interactive, channelData, sensitiveMedia` as
 * undefined and a string `replyToId` when the reply quotes the inbound.
 * @param {unknown} v
 */
function isAbsent(v) {
  return (
    v === undefined ||
    v === null ||
    v === false ||
    v === "" ||
    (Array.isArray(v) && v.length === 0)
  );
}

/** Keys that may carry a value: `text` is the content, `replyToId` a quote target. */
const ALLOWED_PRESENT_KEYS = new Set(["text", "replyToId"]);

/**
 * @param {{
 *   transport: Transport,
 *   ingress: Ingress,
 *   verify?: typeof verifyReply,
 *   cardResolver?: CardResolver,
 *   clock?: () => number,
 *   deadlineMs?: number,
 *   withholdMode?: "safe-text" | "silent",
 *   log?: { info?: Function, warn?: Function, error?: Function },
 *   receiveBusySender?: (sendBusy: (req: { accountId?: string, to: string }) => Promise<{ messageId: string } | { outcome: "not_sent", reason: string }>) => void,
 * }} deps
 */
export function createOutbound({
  transport,
  ingress,
  verify = verifyReply,
  cardResolver = nullCardResolver,
  clock = () => performance.now(),
  deadlineMs = VERIFIER_DEADLINE_MS,
  withholdMode = WITHHOLD_MODE,
  log,
  receiveBusySender,
}) {
  if (!transport || !ingress) {
    throw new Error("idx-whatsapp-channel: createOutbound needs a transport and an ingress");
  }
  if (withholdMode !== "safe-text" && withholdMode !== "silent") {
    throw new Error("idx-whatsapp-channel: unknown withholdMode");
  }

  /** @param {object} fields */
  function audit(fields) {
    // One line per call. Never the text, the peer or the session key.
    try {
      log?.info?.({ component: "idx-whatsapp-channel.outbound", ...fields });
    } catch {
      /* logging must never affect delivery */
    }
  }

  /**
   * Host shape: core calls `normalizePayload({ payload, cfg, accountId })`, up to
   * three times for one payload, so this is idempotent. The only admitted content
   * field is `text`; a payload with any present non-text content is refused whole
   * (caption dropped) and becomes `{ text: SAFE_TEXT }` in safe-text mode or null
   * (core suppresses null before any send) in silent mode.
   * @param {{ payload: unknown, cfg?: unknown, accountId?: string }} envelope
   * @returns {{ text: string, replyToId?: string } | null}
   */
  function normalizePayload(envelope) {
    const payload = envelope && typeof envelope === "object" ? /** @type {any} */ (envelope).payload : undefined;
    const refused = withholdMode === "safe-text" ? { text: SAFE_TEXT } : null;
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return refused;
    }
    for (const [key, value] of Object.entries(payload)) {
      if (isAbsent(value)) continue;
      if (!ALLOWED_PRESENT_KEYS.has(key)) return refused;
      if (typeof value !== "string") return refused;
    }
    const text = payload.text;
    if (typeof text !== "string" || text.trim() === "") return null;
    const out = { text };
    if (typeof payload.replyToId === "string" && payload.replyToId !== "") {
      out.replyToId = payload.replyToId;
    }
    return out;
  }

  /**
   * Plain, frozen copy of a verifier result with each field read exactly once. The
   * well-formedness check and the seal below both see this copy, so a getter or Proxy
   * on the verifier's object cannot answer the check with one value and the seal with
   * another. Anything that is not a plain non-array object becomes null (malformed).
   * @param {unknown} v
   * @returns {{ kind: unknown, text: unknown, reason: unknown, rule: unknown, viaCard: unknown, then: unknown } | null}
   */
  function snapshotVerdict(v) {
    if (v === null || typeof v !== "object" || Array.isArray(v)) return null;
    const { kind, text, reason, rule, viaCard, then } = /** @type {any} */ (v);
    return Object.freeze({ kind, text, reason, rule, viaCard, then });
  }

  /**
   * @param {string} text
   * @param {import("./verifier.mjs").InboundRecord | null} record
   * @returns {import("./verifier.mjs").Verdict}
   */
  function runVerifier(text, record) {
    const t0 = clock();
    /** @type {unknown} */
    let v;
    try {
      v = snapshotVerdict(verify({ text, inbound: record, resolver: cardResolver }));
    } catch {
      v = { kind: "withhold", reason: "verifier-threw" };
    }
    if (clock() - t0 > deadlineMs) v = { kind: "withhold", reason: "verifier-deadline" };
    if (!isWellFormedVerdict(v, text, record)) v = { kind: "withhold", reason: "verifier-malformed" };
    return /** @type {import("./verifier.mjs").Verdict} */ (v);
  }

  /**
   * The only path to the transport. Takes sealed text only and returns the platform
   * message id (undefined when the receipt carries none; the caller throws after its
   * audit line, since the platform send happened and is not a no-send).
   * @param {string} accountId @param {string} peer @param {unknown} sealed @param {AbortSignal | undefined} signal
   * @returns {Promise<string | undefined>}
   */
  async function transmit(accountId, peer, sealed, signal) {
    if (!isSealed(sealed) || sealed.text.length > MAX_TEXT_LENGTH) {
      // Unreachable by construction; kept so the call site below is type-checked.
      throw new Error("idx-whatsapp-channel: refusing an unsealed send");
    }
    // THE ONE CALL SITE. Only sealed text reaches the transport, addressed to the
    // canonical peer the caller resolved.
    const receipt = await transport.sendText({
      accountId,
      to: peer,
      text: sealed.text,
      signal,
    });
    const messageId = receipt && typeof receipt === "object" ? receipt.messageId : undefined;
    return typeof messageId === "string" && messageId !== "" ? messageId : undefined;
  }

  /**
   * The busy reply: BUSY_TEXT, and nothing else, to the canonical peer. Called only by
   * the channel's inbound handler when the ingress reports an active turn for that peer.
   * No verifier (the text is a fixed constant), no record read, no text or peer logged.
   * @param {{ accountId?: string, to: string }} req
   * @returns {Promise<{ messageId: string } | { outcome: "not_sent", reason: string }>}
   */
  async function sendBusy(req) {
    const rawAccountId = req?.accountId;
    const rawTo = req?.to;
    const accountId = typeof rawAccountId === "string" && rawAccountId !== "" ? rawAccountId : "default";
    if (typeof rawTo !== "string" || rawTo.trim() === "") {
      audit({ outcome: "not_sent", reason: "bad-destination", hasRecord: false, boundToTurn: false, textLength: -1 });
      return { outcome: "not_sent", reason: "bad-destination" };
    }
    const peer = normalizePeerId(rawTo);
    const messageId = await transmit(accountId, peer, seal(BUSY_TEXT), undefined);
    audit({ outcome: "busy", hasRecord: false, boundToTurn: false, textLength: BUSY_TEXT.length });
    if (messageId === undefined) {
      throw new Error("idx-whatsapp-channel: transport returned no messageId after a send");
    }
    return { messageId };
  }

  /**
   * Turn binding. `ctx.turn` is a trusted TurnHandle minted by `ingress.record`; only
   * the channel's own inbound `deliver` holds one, and it binds the reply to the turn it
   * answers (a channel-generated id, never the peer's message id). A handle the ingress
   * does not recognise (forged, another peer's, expired or evicted) withholds
   * "untrusted-turn" and sends nothing, not even SAFE_TEXT: there is no trusted record
   * to speak to. A bare `ctx.turnId`, from any caller, is likewise "untrusted-turn":
   * naming a turn by id proves nothing. A context with no handle at all (message tool,
   * cron, heartbeat, CLI) is withheld "no-turn-handle" and sends nothing either: the
   * handle is required (owner decision 17), there is no fallback to the peer's newest
   * turn, so a proactive send needs a handle-bearing path before anything goes out.
   *
   * Every context field is read exactly once, up front. The destination must be a
   * non-empty string (otherwise "bad-destination", nothing sent); the one value read is
   * canonicalised, the record is looked up under that canonical peer, and the transport
   * receives that same canonical peer, so a getter or stateful `toString` on `to` cannot
   * have the verifier check one peer and the transport deliver to another.
   * @param {{ to: string, text: unknown, accountId?: string, cfg?: unknown, turn?: unknown, turnId?: unknown, signal?: AbortSignal, abortSignal?: AbortSignal }} ctx
   * @returns {Promise<{ messageId: string, withheld?: string } | { outcome: "not_sent", reason: string }>}
   */
  async function sendText(ctx) {
    // One read per field. Nothing below touches `ctx` again.
    const rawAccountId = ctx?.accountId;
    const rawTo = ctx?.to;
    const text = ctx?.text;
    const turnId = ctx?.turnId;
    const turn = ctx?.turn;
    const signal = ctx?.signal;
    const abortSignal = ctx?.abortSignal;

    const accountId = typeof rawAccountId === "string" && rawAccountId !== "" ? rawAccountId : "default";
    const textLength = typeof text === "string" ? text.length : -1;
    if (typeof rawTo !== "string" || rawTo.trim() === "") {
      audit({ outcome: "not_sent", reason: "bad-destination", hasRecord: false, boundToTurn: false, textLength });
      return { outcome: "not_sent", reason: "bad-destination" };
    }
    const peer = normalizePeerId(rawTo);
    const key = ingress.key(accountId, peer);

    // The only binding path: a trusted handle. No handle, no send.
    if (turnId !== undefined) {
      audit({ outcome: "not_sent", reason: "untrusted-turn", hasRecord: false, boundToTurn: false, textLength });
      return { outcome: "not_sent", reason: "untrusted-turn" };
    }
    if (turn === undefined) {
      audit({ outcome: "not_sent", reason: "no-turn-handle", hasRecord: false, boundToTurn: false, textLength });
      return { outcome: "not_sent", reason: "no-turn-handle" };
    }
    const record = ingress.forTurn(key, turn);
    if (record === null) {
      audit({ outcome: "not_sent", reason: "untrusted-turn", hasRecord: false, boundToTurn: false, textLength });
      return { outcome: "not_sent", reason: "untrusted-turn" };
    }
    // Whatever is sent from here on is bound to a trusted turn; the audit field stays so
    // a reader of the log can see it on every line.
    const boundToTurn = true;
    const verdict = runVerifier(text, record);

    let sealed;
    let outcome;
    let reason;
    let rule;
    if (verdict.kind === "release") {
      sealed = seal(verdict.text);
      outcome = "sent";
      rule = verdict.rule;
    } else {
      reason = verdict.reason;
      if (withholdMode === "safe-text" && record) {
        sealed = seal(SAFE_TEXT);
        outcome = "safe-text";
      } else {
        audit({
          outcome: "not_sent",
          reason,
          hasRecord: record !== null,
          boundToTurn,
          textLength,
        });
        return { outcome: "not_sent", reason };
      }
    }

    const messageId = await transmit(accountId, peer, sealed, signal ?? abortSignal);
    audit({
      outcome,
      reason,
      rule,
      hasRecord: record !== null,
      boundToTurn,
      textLength: sealed.text.length,
    });
    if (messageId === undefined) {
      // The platform send happened, so this is not a no-send: never report not_sent.
      throw new Error("idx-whatsapp-channel: transport returned no messageId after a send");
    }
    // A SAFE_TEXT send reports why the reply was withheld; a release reports the id only.
    return outcome === "safe-text" ? { messageId, withheld: reason } : { messageId };
  }

  if (typeof receiveBusySender === "function") receiveBusySender(sendBusy);

  return Object.freeze({
    deliveryMode: "gateway",
    textChunkLimit: MAX_TEXT_LENGTH,
    normalizePayload,
    sendText,
  });
}
