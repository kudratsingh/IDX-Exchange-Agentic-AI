// Offline prototype only (WO-036, ADR-0015 proposed): never installed or activated.
// The pure twin of src/idx_agent/channels/card_delivery.py: the token format and the
// release decision. Imports node:crypto only; no fs, process, network or host module.
// Both read tests/fixtures/card_delivery_vectors.json and must agree on every case.
import { createHash } from "node:crypto";

export const ALPHABET = "bcdfghjkmnpqrstv";
export const REF_LETTERS = 20;
export const TAG_LETTERS = 16;
export const TOKEN_HEAD = "[[Listing details not shown. Please ask again. idx-card:";
export const TOKEN_TAIL = "]]";
export const MARKER = "idx-card";
export const CHANNEL_WA = "wa";
export const CHANNEL_NONE = "none";
export const MAX_TEXT_BYTES = 200_000;
export const CARD_NOT_DELIVERED_LINE =
  "I couldn't send those listing details safely this time. Please ask again.";

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const LETTERS = `[${ALPHABET}]`;
const TOKEN_SOURCE =
  escape(TOKEN_HEAD) +
  `(${LETTERS}{${REF_LETTERS}})\\.(${LETTERS}{${TAG_LETTERS}})` +
  escape(TOKEN_TAIL);
const REF = new RegExp(`^${LETTERS}{${REF_LETTERS}}$`);
const HEX64 = /^[0-9a-f]{64}$/;
const SAFE_ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const CHANNEL = /^[a-z]{1,16}$/;
const BLANK = /^[ \t\r\n]*$/;
const DIGIT = /[0-9]/;
const RECORD_KEYS = [
  "v", "ref", "call", "trace_id", "session", "run", "channel", "message",
  "message_sha256", "created_ms", "expires_ms",
].sort();

/** @param {string} text @returns {string} sha256 hex of the UTF-8 bytes */
const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");

/** @param {Uint8Array} bytes @returns {string} two letters per byte, high half first */
export function letters(bytes) {
  let out = "";
  for (const b of bytes) out += ALPHABET[b >> 4] + ALPHABET[b & 15];
  return out;
}

/** @param {string} message */
export const messageDigest = (message) => sha256(message);
/** @param {string} sessionKey the host session key; only its digest leaves the hook */
export const sessionDigest = (sessionKey) => sha256("idx-card-session\0" + sessionKey);
/** @param {string} ref @returns {string} the store file name for ref */
export const fileName = (ref) => "card-" + sha256("idx-card-file\0" + ref) + ".json";

/**
 * @param {{ref: string, trace_id: string, session: string, run: string, call: string,
 *          message_sha256: string}} r
 * @returns {string} the token's 16-letter check
 */
export function cardTag(r) {
  const parts = ["idx-card", r.ref, r.trace_id, r.session, r.run, r.call, r.message_sha256];
  const digest = createHash("sha256").update(parts.join("\0"), "utf8").digest();
  return letters(digest.subarray(0, TAG_LETTERS / 2));
}

/** @typedef {{v: 1, ref: string, call: string, trace_id: string, session: string,
 *   run: string, channel: string, message: string, message_sha256: string,
 *   created_ms: number, expires_ms: number}} CardRecord */

const str = (value, pattern) => typeof value === "string" && pattern.test(value);
const ms = (value) => Number.isSafeInteger(value) && value >= 0;

/** @param {unknown} value @returns {CardRecord | undefined} exactly a record, or nothing */
export function parseRecord(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return;
  const keys = Object.keys(value).sort();
  if (keys.length !== RECORD_KEYS.length || keys.some((k, i) => k !== RECORD_KEYS[i])) return;
  const r = /** @type {Record<string, unknown>} */ (value);
  if (r.v !== 1 || !str(r.ref, REF) || !str(r.call, SAFE_ID) || !str(r.trace_id, SAFE_ID)
      || !str(r.session, HEX64) || !str(r.run, SAFE_ID) || !str(r.channel, CHANNEL)
      || typeof r.message !== "string" || r.message.length < 1
      || !str(r.message_sha256, HEX64) || !ms(r.created_ms) || !ms(r.expires_ms)
      || r.expires_ms <= r.created_ms) return;
  return /** @type {CardRecord} */ (value);
}

/** @param {CardRecord} record @returns {string} the token the model relays */
export const mintToken = (record) => TOKEN_HEAD + record.ref + "." + cardTag(record) + TOKEN_TAIL;

/** @param {string} text @returns {{tokens: Array<[string, string]>, outside: string}} */
export function parseTokens(text) {
  const tokens = [...text.matchAll(new RegExp(TOKEN_SOURCE, "g"))].map((m) => [m[1], m[2]]);
  return { tokens, outside: text.replace(new RegExp(TOKEN_SOURCE, "g"), "") };
}

/** @typedef {{action: "pass"|"substitute"|"withhold"|"drop", text: string|null|undefined,
 *   reason: string, refs: string[]}} Decision */

const withhold = (reason) => ({ action: "withhold", text: CARD_NOT_DELIVERED_LINE, reason, refs: [] });
const drop = (reason) => ({ action: "drop", text: null, reason, refs: [] });

/**
 * Decide one outgoing payload; the rules and their order match verify_and_substitute.
 * @param {string | null | undefined} text
 * @param {{channel: string, session: string, run: string, nowMs: number,
 *   records: Map<string, CardRecord>, boundCalls: string[],
 *   runState?: "open"|"released"|"failed", strict?: boolean, cardInSession?: boolean}} ctx
 * @returns {Decision}
 */
export function verifyAndSubstitute(text, ctx) {
  const body = typeof text === "string" ? text : "";
  const bound = ctx.boundCalls ?? [];
  const runState = ctx.runState ?? "open";
  const plain = () =>
    ctx.strict && ctx.cardInSession && DIGIT.test(body)
      ? withhold("strict_digits")
      : { action: "pass", text, reason: "no_tokens", refs: [] };
  if (ctx.channel !== "whatsapp") return { action: "pass", text, reason: "not_whatsapp", refs: [] };
  if (runState === "failed") return drop("run_failed");
  if (new TextEncoder().encode(body).length > MAX_TEXT_BYTES) return withhold("too_long");
  const { tokens, outside } = parseTokens(body);
  if (!ctx.run) {
    if (tokens.length || outside.includes(MARKER) || bound.length) return withhold("no_run_id");
    return plain();
  }
  if (outside.includes(MARKER)) {
    const tail = outside.slice(outside.indexOf(MARKER));
    return withhold(tail.includes(TOKEN_TAIL) ? "malformed_token" : "partial_token");
  }
  if (!tokens.length) {
    if (!bound.length) return plain();
    if (runState === "released") return drop("after_release");
    return withhold("unreferenced");
  }
  if (runState === "released") return drop("already_released");
  const refs = tokens.map(([ref]) => ref);
  if (new Set(refs).size !== refs.length) return withhold("duplicate");
  if (!BLANK.test(outside)) return withhold("text_outside_tokens");
  for (const [ref, tag] of tokens) {
    let problem = recordProblem(ctx.records.get(ref), ref, tag, ctx);
    if (!problem && !bound.includes(ctx.records.get(ref).call)) problem = "unbound";
    if (problem) return withhold(problem);
  }
  const calls = refs.map((ref) => ctx.records.get(ref).call);
  if (new Set(calls).size !== calls.length) return withhold("duplicate");
  const boundSet = new Set(bound);
  if (calls.length !== boundSet.size || calls.some((c) => !boundSet.has(c))) {
    return withhold("unreferenced");
  }
  const delivered = refs.map((ref) => ctx.records.get(ref).message).join("\n\n");
  return { action: "substitute", text: delivered, reason: "delivered", refs };
}

/** @returns {string | undefined} the first reason this token cannot be released */
function recordProblem(record, ref, tag, ctx) {
  if (!record || record.ref !== ref) return "unknown_ref";
  if (cardTag(record) !== tag) return "tag_mismatch";
  if (messageDigest(record.message) !== record.message_sha256) return "digest_mismatch";
  if (record.session !== ctx.session) return "wrong_session";
  if (record.run !== ctx.run) return "wrong_run";
  if (ctx.nowMs >= record.expires_ms) return "expired";
  if (record.channel !== CHANNEL_WA) return "wrong_channel";
  return undefined;
}
