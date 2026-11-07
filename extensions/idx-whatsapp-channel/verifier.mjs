/**
 * Reply verifier: pure, synchronous, no I/O, no clock.
 *
 * Policy (skeleton, open for owner review). Rules apply in order; the first match
 * decides. A "figure" is a maximal run of Unicode decimal digits, compared whole.
 *
 *   R0 preconditions: not a string, empty, too long, or no inbound record -> withhold.
 *   R1 card references: the text must be tokens only; every token must resolve
 *      through the resolver for this session and turn; the result is the input with
 *      each token replaced by the resolver's bytes exactly.
 *   R2 no figures -> release unchanged.
 *   R3 every figure also appears in the user's inbound text for the turn -> release.
 *   R4 otherwise -> withhold "unverified-figures".
 */

import { CARD_REF_RE, DIGIT_RUN_RE, MAX_TEXT_LENGTH, PARTIAL_TOKEN_RE } from "./constants.mjs";

export const VERIFIER_VERSION = "1";

/**
 * @typedef {{ sessionKey: string, turnId: string, text: string, receivedAt?: number }} InboundRecord
 * @typedef {{ resolve(ref: string, binding: { sessionKey: string, turnId: string }): { text: string } | null }} CardResolver
 * @typedef {{ kind: "release", text: string, rule: "no-figures" | "user-figures" | "card", viaCard?: true }
 *         | { kind: "withhold", reason: string }} Verdict
 */

/** @param {string} reason @returns {Verdict} */
function withhold(reason) {
  return { kind: "withhold", reason };
}

/**
 * Maximal runs of Unicode decimal digits, in order of appearance.
 * @param {string} text
 * @returns {string[]}
 */
export function digitRuns(text) {
  return typeof text === "string" ? text.match(DIGIT_RUN_RE) ?? [] : [];
}

/**
 * True when `rec` carries the three string fields the verifier needs.
 * @param {unknown} rec
 * @returns {rec is InboundRecord}
 */
export function isInboundRecord(rec) {
  return (
    rec !== null &&
    typeof rec === "object" &&
    typeof (/** @type {any} */ (rec).sessionKey) === "string" &&
    typeof (/** @type {any} */ (rec).turnId) === "string" &&
    typeof (/** @type {any} */ (rec).text) === "string"
  );
}

/**
 * True when the text, with every full card token removed, is whitespace only.
 * Shared by R1 and by the gate's well-formedness check for `viaCard` verdicts.
 * @param {string} text
 */
export function isTokenOnlyText(text) {
  if (typeof text !== "string") return false;
  const stripped = text.replace(CARD_REF_RE, "");
  return stripped.trim() === "" && stripped.length !== text.length;
}

/**
 * @param {{ text: unknown, inbound: unknown, resolver: CardResolver }} input
 * @returns {Verdict}
 */
export function verifyReply({ text, inbound, resolver }) {
  // R0
  if (typeof text !== "string") return withhold("not-text");
  if (text.trim() === "") return withhold("empty");
  if (text.length > MAX_TEXT_LENGTH) return withhold("too-long");
  if (!isInboundRecord(inbound)) return withhold("no-inbound-record");

  // R1
  if (PARTIAL_TOKEN_RE.test(text)) {
    const matches = [...text.matchAll(CARD_REF_RE)];
    const withoutFull = text.replace(CARD_REF_RE, "");
    if (PARTIAL_TOKEN_RE.test(withoutFull)) return withhold("malformed-token");
    if (matches.length > 0) {
      if (withoutFull.trim() !== "") return withhold("prose-around-card");
      const seen = new Set();
      for (const m of matches) {
        if (seen.has(m[1])) return withhold("duplicate-token");
        seen.add(m[1]);
      }
      const binding = { sessionKey: inbound.sessionKey, turnId: inbound.turnId };
      let out = "";
      let cursor = 0;
      for (const m of matches) {
        const resolved = resolver.resolve(m[1], binding);
        if (resolved === null || resolved === undefined) return withhold("unknown-token");
        if (
          typeof resolved !== "object" ||
          typeof resolved.text !== "string" ||
          resolved.text === ""
        ) {
          return withhold("resolver-malformed");
        }
        out += text.slice(cursor, m.index) + resolved.text;
        cursor = m.index + m[0].length;
      }
      out += text.slice(cursor);
      return { kind: "release", rule: "card", viaCard: true, text: out };
    }
  }

  // R2
  const runs = digitRuns(text);
  if (runs.length === 0) return { kind: "release", rule: "no-figures", text };

  // R3
  const allowed = new Set(digitRuns(inbound.text));
  if (runs.every((run) => allowed.has(run))) {
    return { kind: "release", rule: "user-figures", text };
  }

  // R4
  return withhold("unverified-figures");
}

/**
 * Gate-side check of a verifier result. Rejects anything that is not a plain
 * object with a known kind, a release whose text is not the input (unless it is a
 * card verdict for a token-only input), and any thenable (the verifier is sync).
 * @param {unknown} value
 * @param {string} inputText
 * @returns {boolean}
 */
export function isWellFormedVerdict(value, inputText) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const v = /** @type {any} */ (value);
  if (typeof v.then === "function") return false;
  if (v.kind === "withhold") return typeof v.reason === "string" && v.reason !== "";
  if (v.kind !== "release") return false;
  if (typeof v.text !== "string" || v.text.trim() === "") return false;
  if (v.text.length > MAX_TEXT_LENGTH) return false;
  if (v.text === inputText) return v.viaCard !== true;
  return v.viaCard === true && v.rule === "card" && isTokenOnlyText(inputText);
}
