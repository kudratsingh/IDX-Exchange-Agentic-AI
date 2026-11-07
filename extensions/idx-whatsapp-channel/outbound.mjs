/**
 * The outbound gate. Every send path (inbound reply deliver, message tool, cron,
 * heartbeat, CLI) ends in `sendText` here, and `sendText` holds the only
 * `transport.sendText(` call expression in the runtime. The call receives sealed
 * text only: a verdict the verifier released and the gate accepted, or SAFE_TEXT.
 */

import {
  MAX_TEXT_LENGTH,
  SAFE_TEXT,
  VERIFIER_DEADLINE_MS,
  WITHHOLD_MODE,
} from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
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
   * @param {string} text
   * @param {import("./verifier.mjs").InboundRecord | null} record
   * @returns {import("./verifier.mjs").Verdict}
   */
  function runVerifier(text, record) {
    const t0 = clock();
    /** @type {unknown} */
    let v;
    try {
      v = verify({ text, inbound: record, resolver: cardResolver });
    } catch {
      v = { kind: "withhold", reason: "verifier-threw" };
    }
    if (clock() - t0 > deadlineMs) v = { kind: "withhold", reason: "verifier-deadline" };
    if (!isWellFormedVerdict(v, text)) v = { kind: "withhold", reason: "verifier-malformed" };
    return /** @type {import("./verifier.mjs").Verdict} */ (v);
  }

  /**
   * @param {{ to: string, text: unknown, accountId?: string, cfg?: unknown, signal?: AbortSignal, abortSignal?: AbortSignal }} ctx
   * @returns {Promise<{ messageId: string } | { outcome: "not_sent", reason: string }>}
   */
  async function sendText(ctx) {
    const accountId = typeof ctx?.accountId === "string" && ctx.accountId !== "" ? ctx.accountId : "default";
    const record = ingress.current(ingress.key(accountId, ctx?.to));
    const text = ctx?.text;
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
          textLength: typeof text === "string" ? text.length : -1,
        });
        return { outcome: "not_sent", reason };
      }
    }

    if (!isSealed(sealed) || sealed.text.length > MAX_TEXT_LENGTH) {
      // Unreachable by construction; kept so the call site below is type-checked.
      return { outcome: "not_sent", reason: "unsealed" };
    }

    // THE ONE CALL SITE. Only sealed text reaches the transport.
    const receipt = await transport.sendText({
      accountId,
      to: ctx.to,
      text: sealed.text,
      signal: ctx.signal ?? ctx.abortSignal,
    });
    const messageId = receipt && typeof receipt === "object" ? receipt.messageId : undefined;
    audit({
      outcome,
      reason,
      rule,
      hasRecord: record !== null,
      textLength: sealed.text.length,
    });
    if (typeof messageId !== "string" || messageId === "") {
      // The platform send happened, so this is not a no-send: never report not_sent.
      throw new Error("idx-whatsapp-channel: transport returned no messageId after a send");
    }
    return { messageId };
  }

  return Object.freeze({
    deliveryMode: "gateway",
    textChunkLimit: MAX_TEXT_LENGTH,
    normalizePayload,
    sendText,
  });
}
