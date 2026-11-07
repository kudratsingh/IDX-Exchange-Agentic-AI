/**
 * Card resolver seam. The verifier asks it for the bytes behind a card token,
 * bound to a session and a turn. The default resolver verifies nothing and so
 * every token is withheld; the #179 token check plugs in here later.
 */

/**
 * @typedef {{ resolve(ref: string, binding: { sessionKey: string, turnId: string }): { text: string } | null }} CardResolver
 */

/** @type {CardResolver} */
export const nullCardResolver = Object.freeze({ resolve: () => null });
