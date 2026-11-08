/**
 * Card resolver seam. The verifier asks it for the bytes behind a card token, bound to a
 * session and a turn.
 *
 * `createTurnCardResolver(ingress)` is the production resolver. Since the complete reply
 * token (2026-11-08) it answers exactly one ref, REPLY_REF (`[[card:reply]]`): the reply
 * `composeReply` writes from the sections the ingress holds for exactly that session key
 * and turn id, one per card call admitted on that turn, in call order (rendered by code
 * from each call's trusted outcome in `after_tool_call`, see channel.mjs). Any other ref,
 * a listing id included, is null, and so is a turn whose admitted calls are not all
 * captured and rendered, or whose reply does not fit MAX_TEXT_LENGTH. Model text never
 * reaches the store. `nullCardResolver` verifies nothing, so every token is withheld;
 * tests use it.
 */

import { REPLY_REF } from "./constants.mjs";
import { composeReply } from "./reply-render.mjs";

/**
 * @typedef {{ resolve(ref: string, binding: { sessionKey: string, turnId: string }): { text: string } | null }} CardResolver
 */

/** @type {CardResolver} */
export const nullCardResolver = Object.freeze({ resolve: () => null });

/**
 * The resolver over one ingress's reply store: `{ text }` only for REPLY_REF on a turn
 * whose whole reply renders, otherwise null.
 * @param {{ replySections(binding: unknown): ReadonlyArray<unknown> | null }} ingress
 * @returns {CardResolver}
 */
export function createTurnCardResolver(ingress) {
  if (!ingress || typeof ingress.replySections !== "function") {
    throw new Error("idx-whatsapp-channel: createTurnCardResolver needs an ingress");
  }
  return Object.freeze({
    resolve(ref, binding) {
      if (ref !== REPLY_REF) return null;
      const text = composeReply(ingress.replySections(binding));
      return typeof text === "string" && text !== "" ? { text } : null;
    },
  });
}
