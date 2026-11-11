/**
 * In-memory card resolver for tests only. Proves byte-identical substitution of a
 * stored card bound to (sessionKey, turnId, ref). Never imported by runtime code.
 */

/** @typedef {import("../card-resolver.mjs").CardResolver} CardResolver */

/** @returns {CardResolver & { store(sessionKey: string, turnId: string, ref: string, text: string): void, remove(sessionKey: string, turnId: string, ref: string): void }} */
export function createInMemoryCardResolver() {
  /** @type {Map<string, string>} */
  const cards = new Map();
  const key = (s, t, r) => `${s}\u0000${t}\u0000${r}`;
  return {
    store(sessionKey, turnId, ref, text) {
      cards.set(key(sessionKey, turnId, ref), text);
    },
    remove(sessionKey, turnId, ref) {
      cards.delete(key(sessionKey, turnId, ref));
    },
    resolve(ref, binding) {
      const text = cards.get(key(binding.sessionKey, binding.turnId, ref));
      return text === undefined ? null : { text };
    },
  };
}
