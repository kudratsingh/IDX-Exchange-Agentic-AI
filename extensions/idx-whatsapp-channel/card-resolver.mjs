/**
 * Card resolver seam. The verifier asks it for the bytes behind a card token, bound to a
 * session and a turn.
 *
 * `createTurnCardResolver(ingress)` is the production resolver (owned-channel install
 * item 3, 2026-11-07): it answers only from the ingress's turn-bound card store, which
 * holds the cards code rendered from the trusted result of a card call admitted on that
 * same turn (`after_tool_call`, see channel.mjs). Model text never reaches the store.
 * `nullCardResolver` verifies nothing, so every token is withheld; tests use it.
 */

/**
 * @typedef {{ resolve(ref: string, binding: { sessionKey: string, turnId: string }): { text: string } | null }} CardResolver
 */

/** @type {CardResolver} */
export const nullCardResolver = Object.freeze({ resolve: () => null });

/**
 * The resolver over one ingress's card store: `{ text }` only for a card stored for
 * exactly that session key and turn id, otherwise null.
 * @param {{ resolveCard(ref: unknown, binding: unknown): { text: string } | null }} ingress
 * @returns {CardResolver}
 */
export function createTurnCardResolver(ingress) {
  if (!ingress || typeof ingress.resolveCard !== "function") {
    throw new Error("idx-whatsapp-channel: createTurnCardResolver needs an ingress");
  }
  return Object.freeze({
    resolve(ref, binding) {
      const hit = ingress.resolveCard(ref, binding);
      return hit !== null && typeof hit === "object" && typeof hit.text === "string" ? { text: hit.text } : null;
    },
  });
}
