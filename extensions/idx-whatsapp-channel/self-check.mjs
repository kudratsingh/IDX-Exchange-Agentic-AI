/**
 * Startup self-check, run by register(api) before registerChannel. Pure.
 *
 * It refuses unless the host config snapshot denies the stock plugin
 * (`plugins.deny` contains "whatsapp" after trim + lowercase, the host's own
 * normalization), the statically imported verifier passes its vectors, and
 * SAFE_TEXT is digit-free. BUSY_TEXT must be digit-free as well and differ from
 * SAFE_TEXT.
 *
 * The stock plugin is excluded in one of two forms (`stockPluginExcluded`):
 *   - `plugins.deny` contains "whatsapp" (the shipped rule), or
 *   - an explicit `plugins.allow` list that names this plugin ("idx-whatsapp-channel")
 *     and does not name "whatsapp", with no explicit `plugins.entries.whatsapp.enabled:
 *     true` (added 2026-11-07). On OpenClaw 2026.9.5 the stock
 *     WhatsApp plugin is an external package that is not installed by default, and the
 *     host then resolves the policy id "whatsapp" to the plugin that owns the whatsapp
 *     channel, which is this one: a deny of "whatsapp" keeps this plugin out of the
 *     gateway's startup plan (real-host harness, WO-037). A restrictive allow list keeps
 *     an unlisted stock plugin from loading without naming it in a deny list.
 *
 * Residual risk: the check sees the config at registration only. Removing the
 * deny or the allow list later and restarting brings the stock plugin back.
 */

import { BUSY_TEXT, CARD_TOOLS, PLUGIN_ID, REPLY_INSTRUCTION, REPLY_TOKEN, SAFE_TEXT, STOCK_PLUGIN_ID } from "./constants.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { verifyReply } from "./verifier.mjs";

/** The host compares trimmed, lowercased string ids; non-string entries are dropped. */
export function normalizePluginPolicyId(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : null;
}

/** @param {unknown} cfg */
export function stockPluginDenied(cfg) {
  const deny = /** @type {any} */ (cfg)?.plugins?.deny;
  if (!Array.isArray(deny)) return false;
  return deny.some((x) => normalizePluginPolicyId(x) === STOCK_PLUGIN_ID);
}

/** An explicit allow list that names this plugin and not the stock one. @param {unknown} cfg */
export function stockPluginNotAllowed(cfg) {
  const allow = /** @type {any} */ (cfg)?.plugins?.allow;
  if (!Array.isArray(allow) || allow.length === 0) return false;
  const ids = allow.map(normalizePluginPolicyId);
  if (!ids.includes(PLUGIN_ID) || ids.includes(STOCK_PLUGIN_ID)) return false;
  // An explicit enable of the stock id is refused too (belt and braces; send-boundary review).
  const entries = /** @type {any} */ (cfg)?.plugins?.entries;
  if (entries && typeof entries === "object") {
    for (const [id, entry] of Object.entries(entries)) {
      if (normalizePluginPolicyId(id) === STOCK_PLUGIN_ID && entry?.enabled === true) return false;
    }
  }
  return true;
}

/** The stock plugin is excluded by a deny entry or by a restrictive allow list. @param {unknown} cfg */
export function stockPluginExcluded(cfg) {
  return stockPluginDenied(cfg) || stockPluginNotAllowed(cfg);
}

const SELF_TEST_INBOUND = {
  sessionKey: "agent:idx:whatsapp:direct:selftest",
  turnId: "t1",
  text: "hi",
  cardToolCalled: false,
  runBound: true,
  cardCallRefused: false,
};
/** The same turn after a card tool call was admitted: only verified card tokens may leave (R1b). */
const SELF_TEST_CARD_TURN = { ...SELF_TEST_INBOUND, cardToolCalled: true };
/** The same turn with its run never confirmed: nothing may leave (R0b). */
const SELF_TEST_UNBOUND_TURN = { ...SELF_TEST_INBOUND, runBound: false };
/** The same turn after a card call tied to it was refused: nothing may leave (R0c). */
const SELF_TEST_REFUSED_TURN = { ...SELF_TEST_INBOUND, cardCallRefused: true };
const SELF_TEST_RESOLVER = Object.freeze({
  resolve: (ref, binding) =>
    ref === "selftest" && binding.sessionKey === SELF_TEST_INBOUND.sessionKey && binding.turnId === "t1"
      ? { text: "card body" }
      : null,
});

/** Vectors the shipped verifier must satisfy before the channel registers. */
export const SELF_TEST_VECTORS = Object.freeze([
  { text: "Hello! How can I help?", inbound: SELF_TEST_INBOUND, expect: "release" },
  {
    text: "Do you mean 3 or 4 bedrooms?",
    inbound: { ...SELF_TEST_INBOUND, text: "3 or 4" },
    expect: "release",
  },
  { text: "There are 12 homes", inbound: SELF_TEST_INBOUND, expect: "withhold" },
  { text: "[[card:abc]]", inbound: { ...SELF_TEST_CARD_TURN, text: "show me" }, expect: "withhold" },
  // A resolving token on a turn with no admitted card call is withheld (R1).
  {
    text: "[[card:selftest]]",
    inbound: SELF_TEST_INBOUND,
    resolver: SELF_TEST_RESOLVER,
    expect: "withhold",
  },
  {
    text: "Here it is: [[card:selftest]]",
    inbound: SELF_TEST_CARD_TURN,
    resolver: SELF_TEST_RESOLVER,
    expect: "withhold",
  },
  // A card turn: prose is withheld even when digit-free or echoing the user's figures.
  { text: "Here are some great homes for you.", inbound: SELF_TEST_CARD_TURN, expect: "withhold" },
  {
    text: "Do you mean 3 or 4 bedrooms?",
    inbound: { ...SELF_TEST_CARD_TURN, text: "3 or 4" },
    expect: "withhold",
  },
  {
    text: "[[card:selftest]]",
    inbound: SELF_TEST_CARD_TURN,
    resolver: SELF_TEST_RESOLVER,
    expect: "release",
    expectText: "card body",
  },
  // An ordinary bound turn keeps its greeting.
  { text: "Hi! How can I help you today?", inbound: SELF_TEST_INBOUND, expect: "release" },
  // A record without the card-turn flag is malformed and withheld.
  {
    text: "Hello!",
    inbound: { sessionKey: SELF_TEST_INBOUND.sessionKey, turnId: "t1", text: "hi", runBound: true, cardCallRefused: false },
    expect: "withhold",
  },
  // A record without the run-bound flag is malformed and withheld.
  {
    text: "Hello!",
    inbound: { sessionKey: SELF_TEST_INBOUND.sessionKey, turnId: "t1", text: "hi", cardToolCalled: false, cardCallRefused: false },
    expect: "withhold",
  },
  // An unbound turn releases nothing: not a greeting, not even a resolving card token.
  { text: "Hi!", inbound: SELF_TEST_UNBOUND_TURN, expect: "withhold" },
  {
    text: "[[card:selftest]]",
    inbound: { ...SELF_TEST_UNBOUND_TURN, cardToolCalled: true },
    resolver: SELF_TEST_RESOLVER,
    expect: "withhold",
  },
  // A turn whose own card call was refused (tied) releases nothing (R0c): not a greeting,
  // not a listing claim that reuses the buyer's own budget, not a resolving card token.
  { text: "Hi! How can I help?", inbound: SELF_TEST_REFUSED_TURN, expect: "withhold" },
  {
    text: "A 3 bed is listed at 650000",
    inbound: { ...SELF_TEST_REFUSED_TURN, text: "My budget is 650000 for a 3 bed" },
    expect: "withhold",
  },
  {
    text: "[[card:selftest]]",
    inbound: { ...SELF_TEST_REFUSED_TURN, cardToolCalled: true },
    resolver: SELF_TEST_RESOLVER,
    expect: "withhold",
  },
  // A record without the refused flag is malformed and withheld.
  {
    text: "Hello!",
    inbound: { sessionKey: SELF_TEST_INBOUND.sessionKey, turnId: "t1", text: "hi", cardToolCalled: false, runBound: true },
    expect: "withhold",
  },
]);

/** @param {typeof verifyReply} verify */
export function verifierSelfTest(verify = verifyReply) {
  for (const vec of SELF_TEST_VECTORS) {
    let v;
    try {
      v = verify({ text: vec.text, inbound: vec.inbound, resolver: vec.resolver ?? nullCardResolver });
    } catch {
      return false;
    }
    if (!v || typeof v !== "object" || v.kind !== vec.expect) return false;
    if (vec.expect === "release" && v.text !== (vec.expectText ?? vec.text)) return false;
  }
  return true;
}

export function safeTextValid(text = SAFE_TEXT) {
  return typeof text === "string" && text.trim() !== "" && text.length <= 200 && !/\p{N}/u.test(text);
}

/** The busy reply obeys the same rules as SAFE_TEXT and is a different text. */
export function busyTextValid(text = BUSY_TEXT, safeText = SAFE_TEXT) {
  return safeTextValid(text) && text !== safeText;
}

/** The model-facing reply instruction names the one token and every card tool, carries
 *  no digit, and stays short (complete reply token, 2026-11-08). */
export function replyInstructionValid(text = REPLY_INSTRUCTION) {
  return (
    typeof text === "string" &&
    text.length <= 1000 &&
    !/\p{N}/u.test(text) &&
    text.includes(REPLY_TOKEN) &&
    CARD_TOOLS.every((t) => text.includes(t))
  );
}

/**
 * @param {unknown} cfg
 * @param {{ verify?: typeof verifyReply, safeText?: string, busyText?: string, replyInstruction?: string }} [opts]
 * @returns {{ ok: true } | { ok: false, reason: "config-missing" | "stock-whatsapp-not-denied" | "verifier-self-test-failed" | "safe-text-invalid" | "busy-text-invalid" | "reply-instruction-invalid" }}
 */
export function selfCheck(cfg, { verify = verifyReply, safeText = SAFE_TEXT, busyText = BUSY_TEXT, replyInstruction = REPLY_INSTRUCTION } = {}) {
  if (cfg === null || typeof cfg !== "object") return { ok: false, reason: "config-missing" };
  if (!stockPluginExcluded(cfg)) return { ok: false, reason: "stock-whatsapp-not-denied" };
  if (!verifierSelfTest(verify)) return { ok: false, reason: "verifier-self-test-failed" };
  if (!safeTextValid(safeText)) return { ok: false, reason: "safe-text-invalid" };
  if (!busyTextValid(busyText, safeText)) return { ok: false, reason: "busy-text-invalid" };
  if (!replyInstructionValid(replyInstruction)) return { ok: false, reason: "reply-instruction-invalid" };
  return { ok: true };
}
