/**
 * Startup self-check, run by register(api) before registerChannel. Pure.
 *
 * It refuses unless the host config snapshot denies the stock plugin
 * (`plugins.deny` contains "whatsapp" after trim + lowercase, the host's own
 * normalization), the statically imported verifier passes its vectors, and
 * SAFE_TEXT is digit-free. Only `plugins.deny` is accepted: it is checked before
 * every other enablement rule and an explicit deny is authoritative.
 *
 * Residual risk: the check sees the config at registration only. Removing the
 * deny later and restarting brings the stock plugin back.
 */

import { SAFE_TEXT, STOCK_PLUGIN_ID } from "./constants.mjs";
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

const SELF_TEST_INBOUND = { sessionKey: "agent:idx:whatsapp:direct:selftest", turnId: "t1", text: "hi" };
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
  { text: "[[card:abc]]", inbound: { ...SELF_TEST_INBOUND, text: "show me" }, expect: "withhold" },
  {
    text: "[[card:selftest]]",
    inbound: SELF_TEST_INBOUND,
    resolver: SELF_TEST_RESOLVER,
    expect: "release",
    expectText: "card body",
  },
  {
    text: "Here it is: [[card:selftest]]",
    inbound: SELF_TEST_INBOUND,
    resolver: SELF_TEST_RESOLVER,
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

/**
 * @param {unknown} cfg
 * @param {{ verify?: typeof verifyReply, safeText?: string }} [opts]
 * @returns {{ ok: true } | { ok: false, reason: "config-missing" | "stock-whatsapp-not-denied" | "verifier-self-test-failed" | "safe-text-invalid" }}
 */
export function selfCheck(cfg, { verify = verifyReply, safeText = SAFE_TEXT } = {}) {
  if (cfg === null || typeof cfg !== "object") return { ok: false, reason: "config-missing" };
  if (!stockPluginDenied(cfg)) return { ok: false, reason: "stock-whatsapp-not-denied" };
  if (!verifierSelfTest(verify)) return { ok: false, reason: "verifier-self-test-failed" };
  if (!safeTextValid(safeText)) return { ok: false, reason: "safe-text-invalid" };
  return { ok: true };
}
