/**
 * Reply verifier: pure, synchronous, no I/O, no clock.
 *
 * Policy (skeleton, open for owner review). Rules apply in order; the first match
 * decides. A "figure" is a maximal run of Unicode numeric characters (`\p{N}`: decimal
 * digits in any script, other numerals such as ½ ⑫ ², letter numerals such as Ⅻ),
 * compared whole. Number words ("twelve") are not figures.
 *
 *   R0 preconditions: not a string, empty, too long, or no inbound record -> withhold;
 *      a record without a boolean `cardToolCalled` or a boolean `toolCallBlocked` ->
 *      withhold "malformed-inbound-record".
 *   R0b blocked turns: if a card tool call on this turn was blocked (`toolCallBlocked ===
 *      true`: the trusted mark could not be applied before execution, or the hook handler
 *      failed, so the turn is tainted), everything is withheld "blocked-tool-call", card
 *      tokens included: a blocked tool produced no verified card, and the turn is no
 *      longer trustworthy. The flag is monotonic and never inherited by a later turn.
 *   R1 card references: if a token fragment (`[[`, `]]`, `[card:`, `card:...]`) appears,
 *      the text must be tokens only; every token must resolve through the resolver for
 *      this session and turn; the result is the input with each token replaced by the
 *      resolver's bytes exactly. The resolver's `text` is read once and that one value
 *      is both checked and substituted.
 *   R1b card turns: if the turn called a card tool (`cardToolCalled === true`), nothing
 *      but a fully resolved token-only text may leave, so any prose, with or without
 *      figures, is withheld "card-turn-requires-tokens". Greetings and clarifications
 *      keep releasing on ordinary turns (flag false) under R2 and R3.
 *   R2 no figures -> release unchanged.
 *   R3 every figure also appears in the user's inbound text for the turn -> release.
 *   R4 otherwise -> withhold "unverified-figures".
 *
 * `isWellFormedVerdict` is the gate's independent check of a verdict against the input
 * and the record: a release must name one of the three rules and be self-consistent
 * with it; an incomplete or inconsistent release is malformed and the gate withholds.
 * No release is well-formed on a blocked turn.
 */

import { CARD_REF_RE, DIGIT_RUN_RE, MAX_TEXT_LENGTH, PARTIAL_TOKEN_RE } from "./constants.mjs";

export const VERIFIER_VERSION = "3";

/**
 * @typedef {{ sessionKey: string, turnId: string, text: string, cardToolCalled: boolean, toolCallBlocked: boolean, receivedAt?: number }} InboundRecord
 * @typedef {{ resolve(ref: string, binding: { sessionKey: string, turnId: string }): { text: string } | null }} CardResolver
 * @typedef {{ kind: "release", text: string, rule: "no-figures" | "user-figures" | "card", viaCard?: true }
 *         | { kind: "withhold", reason: string }} Verdict
 */

const RELEASE_RULES = Object.freeze(["no-figures", "user-figures", "card"]);

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

/** @param {unknown} rec the three string fields, without the flag. */
function hasRecordFields(rec) {
  return (
    rec !== null &&
    typeof rec === "object" &&
    typeof (/** @type {any} */ (rec).sessionKey) === "string" &&
    typeof (/** @type {any} */ (rec).turnId) === "string" &&
    typeof (/** @type {any} */ (rec).text) === "string"
  );
}

/**
 * True when `rec` carries the three string fields and the two boolean flags the verifier
 * needs: `cardToolCalled` (card turn) and `toolCallBlocked` (tainted turn).
 * @param {unknown} rec
 * @returns {rec is InboundRecord}
 */
export function isInboundRecord(rec) {
  return (
    hasRecordFields(rec) &&
    typeof (/** @type {any} */ (rec).cardToolCalled) === "boolean" &&
    typeof (/** @type {any} */ (rec).toolCallBlocked) === "boolean"
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
  if (!hasRecordFields(inbound)) return withhold("no-inbound-record");
  if (!isInboundRecord(inbound)) return withhold("malformed-inbound-record");

  // R0b: a tainted turn releases nothing, tokens included. Before R1, so a partial or
  // resolving token on a blocked turn is "blocked-tool-call", not a token verdict.
  if (inbound.toolCallBlocked === true) return withhold("blocked-tool-call");

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
        if (typeof resolved !== "object") return withhold("resolver-malformed");
        // One read. A getter or Proxy cannot answer the type check with one value and
        // the substitution with another.
        const cardText = resolved.text;
        if (typeof cardText !== "string" || cardText === "") return withhold("resolver-malformed");
        out += text.slice(cursor, m.index) + cardText;
        cursor = m.index + m[0].length;
      }
      out += text.slice(cursor);
      return { kind: "release", rule: "card", viaCard: true, text: out };
    }
  }

  // R1b: a turn that called a card tool releases verified card bytes only.
  if (inbound.cardToolCalled === true) return withhold("card-turn-requires-tokens");

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
 * Gate-side check of a verifier result against the input text and the inbound record.
 *
 * A withhold is well-formed only when `reason` is a non-empty string and no `text` is
 * present. A release is well-formed only when every one of these holds: `kind` is
 * "release"; `text` is a non-empty string within MAX_TEXT_LENGTH; `rule` is exactly one
 * of "no-figures", "user-figures", "card"; `viaCard` is `true` for the card rule and
 * absent otherwise; no `reason`; no thenable (the verifier is sync); the record is a
 * valid InboundRecord; and the rule is self-consistent with input and record:
 *   "no-figures":   text is the input and carries no figure;
 *   "user-figures": text is the input, carries at least one figure, and every figure
 *                   appears in the record's text;
 *   "card":         the input is token-only (the gate cannot re-resolve, so it trusts the
 *                   bytes only after these structural checks).
 * On a card turn (`cardToolCalled === true`) the only acceptable release rule is "card".
 * On a blocked turn (`toolCallBlocked === true`) no release is well-formed at all.
 * Anything else is malformed.
 * @param {unknown} value
 * @param {string} inputText
 * @param {unknown} inbound
 * @returns {boolean}
 */
export function isWellFormedVerdict(value, inputText, inbound) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const v = /** @type {any} */ (value);
  if (v.then !== undefined) return false;
  if (v.kind === "withhold") return typeof v.reason === "string" && v.reason !== "" && v.text === undefined;
  if (v.kind !== "release") return false;
  if (v.reason !== undefined) return false;
  if (typeof v.text !== "string" || v.text.trim() === "") return false;
  if (v.text.length > MAX_TEXT_LENGTH) return false;
  if (!RELEASE_RULES.includes(v.rule)) return false;
  if (v.rule === "card" ? v.viaCard !== true : v.viaCard !== undefined) return false;
  if (!isInboundRecord(inbound)) return false;
  if (inbound.toolCallBlocked === true) return false;
  if (inbound.cardToolCalled === true && v.rule !== "card") return false;
  if (v.rule === "card") return isTokenOnlyText(inputText);
  if (v.text !== inputText) return false;
  const runs = digitRuns(v.text);
  if (v.rule === "no-figures") return runs.length === 0;
  // "user-figures"
  if (runs.length === 0) return false;
  const allowed = new Set(digitRuns(inbound.text));
  return runs.every((run) => allowed.has(run));
}
