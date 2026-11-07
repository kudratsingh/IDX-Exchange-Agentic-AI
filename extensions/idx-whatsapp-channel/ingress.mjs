/**
 * Ingress records: the current inbound turn per (accountId, peer), kept in process
 * memory so the outbound gate can verify a reply against what the user wrote.
 * Stores only what the verifier needs; never logs text or peer ids.
 */

import { INGRESS_MAX_ENTRIES, INGRESS_TTL_MS } from "./constants.mjs";

/** @typedef {import("./verifier.mjs").InboundRecord} InboundRecord */

const PREFIX_RE = /^whatsapp:/iu;
const JID_SUFFIX_RE = /@(s\.whatsapp\.net|lid|c\.us)$/iu;
const PHONE_SHAPE_RE = /^\+?[\d\s().-]+$/u;

/**
 * Canonical peer id. Strips a `whatsapp:` prefix and a JID suffix; a phone-shaped
 * remainder (digits with spaces, dots, dashes, parens, optional leading +) becomes
 * `+<digits>`; anything else is the trimmed, lowercased string.
 * @param {unknown} to
 * @returns {string}
 */
export function normalizePeerId(to) {
  let s = String(to ?? "").trim().replace(PREFIX_RE, "").trim();
  s = s.replace(JID_SUFFIX_RE, "");
  if (s !== "" && PHONE_SHAPE_RE.test(s)) {
    const digits = s.replace(/\D/gu, "");
    if (digits !== "") return "+" + digits;
  }
  return s.toLowerCase();
}

/**
 * @param {{ now?: () => number, ttlMs?: number, maxEntries?: number }} [opts]
 */
export function createIngress({
  now = Date.now,
  ttlMs = INGRESS_TTL_MS,
  maxEntries = INGRESS_MAX_ENTRIES,
} = {}) {
  /** @type {Map<string, { rec: InboundRecord, storedAt: number }>} */
  const map = new Map();

  return {
    /** @param {string} accountId @param {unknown} to */
    key(accountId, to) {
      return `${String(accountId ?? "default")}\u0000${normalizePeerId(to)}`;
    },
    /** @param {string} key @param {InboundRecord} rec */
    record(key, rec) {
      map.delete(key); // re-insert so the newest record is last in iteration order
      map.set(key, {
        rec: {
          sessionKey: rec.sessionKey,
          turnId: rec.turnId,
          text: rec.text,
          receivedAt: rec.receivedAt,
        },
        storedAt: now(),
      });
      while (map.size > maxEntries) {
        const oldest = map.keys().next().value;
        map.delete(oldest);
      }
    },
    /** @param {string} key @returns {InboundRecord | null} */
    current(key) {
      const entry = map.get(key);
      if (!entry) return null;
      if (now() - entry.storedAt > ttlMs) {
        map.delete(key);
        return null;
      }
      return entry.rec;
    },
    size() {
      return map.size;
    },
  };
}
