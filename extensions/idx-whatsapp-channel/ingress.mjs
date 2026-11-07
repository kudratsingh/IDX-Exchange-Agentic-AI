/**
 * Ingress records: the newest inbound turns per (accountId, peer), kept in process
 * memory so the outbound gate can verify a reply against what the user wrote.
 * Stores only what the verifier needs; never logs text or peer ids.
 *
 * Trusted turn handles: `record` returns a frozen `{ turnId, key }` whose identity is the
 * key of a WeakMap private to this instance, mapping the handle to the stored entry it
 * was minted for. Only that object names a turn to `forTurn` and `markCardTool`; a
 * string, or a plain object with the same fields, is not a handle, and a second record
 * that happens to carry the same turn id is a different entry with its own handle. The
 * channel keeps the handle in the closure of the turn it minted it for and never hands
 * it to the host runner, so no other caller can bind a send to a turn. There is no
 * lookup by key alone: a record is reachable only through its handle (owner decision
 * 17), so a caller that holds no handle has no record to send against.
 *
 * `cardToolCalled` is monotonic: false at record time, set to true by `markCardTool` or
 * `markCardToolForSession`, never cleared, never inherited by a later turn. Lookups
 * return frozen copies, so a caller cannot flip the stored flag either.
 */

import { INGRESS_MAX_ENTRIES, INGRESS_TTL_MS, INGRESS_TURNS_PER_PEER, isCardTool } from "./constants.mjs";

/** @typedef {import("./verifier.mjs").InboundRecord} InboundRecord */
/** @typedef {Readonly<{ turnId: string, key: string }>} TurnHandle */

const PREFIX_RE = /^whatsapp:/iu;
/** Phone-number JID suffixes: the local part is the phone number. */
const PHONE_JID_SUFFIX_RE = /@(s\.whatsapp\.net|c\.us)$/iu;
/** The linked-id namespace. Not a phone number, so it never folds into `+<digits>`. */
const LID_SUFFIX_RE = /@lid$/iu;
const PHONE_SHAPE_RE = /^\+?[\d\s().-]+$/u;

/** @param {string} s @returns {string | null} `+<digits>` for a phone-shaped string. */
function phoneDigits(s) {
  if (s === "" || !PHONE_SHAPE_RE.test(s)) return null;
  const digits = s.replace(/\D/gu, "");
  return digits === "" ? null : "+" + digits;
}

/**
 * Canonical peer id. Strips a `whatsapp:` prefix and a phone-number JID suffix
 * (`@s.whatsapp.net`, `@c.us`); a phone-shaped remainder (digits with spaces, dots,
 * dashes, parens, optional leading +) becomes `+<digits>`. A linked id (`@lid`) is a
 * separate identifier namespace and stays `<local>@lid` (digits only when the local part
 * is phone-shaped), so it never shares a record with the `+<digits>` peer. Anything else
 * is the trimmed, lowercased string. Idempotent: a canonical id canonicalises to itself.
 * @param {unknown} to
 * @returns {string}
 */
export function normalizePeerId(to) {
  const s = String(to ?? "").trim().replace(PREFIX_RE, "").trim();
  if (LID_SUFFIX_RE.test(s)) {
    const local = s.replace(LID_SUFFIX_RE, "").trim();
    const phone = phoneDigits(local);
    return (phone ? phone.slice(1) : local.toLowerCase()) + "@lid";
  }
  const bare = s.replace(PHONE_JID_SUFFIX_RE, "");
  return phoneDigits(bare) ?? bare.toLowerCase();
}

/**
 * Per peer the newest `turnsPerPeer` turns are kept, newest first, so a reply still in
 * flight when the peer's next message arrives is verified against the turn it answers.
 * `forTurn` is the only read of a record and answers only to the trusted handle minted
 * for it; nothing returns the newest turn by key. Every lookup applies the TTL.
 * @param {{ now?: () => number, ttlMs?: number, maxEntries?: number, turnsPerPeer?: number }} [opts]
 */
export function createIngress({
  now = Date.now,
  ttlMs = INGRESS_TTL_MS,
  maxEntries = INGRESS_MAX_ENTRIES,
  turnsPerPeer = INGRESS_TURNS_PER_PEER,
} = {}) {
  /** @typedef {{ rec: InboundRecord, storedAt: number, key: string }} Entry */
  /** @type {Map<string, Entry[]>} */
  const map = new Map();
  /** Every handle this instance minted, by identity, to the one entry it names. Module-private; nothing exposes it. */
  const handles = new WeakMap();

  /** @param {Entry} entry */
  const expired = (entry) => now() - entry.storedAt > ttlMs;

  /** @param {InboundRecord} rec */
  const snapshot = (rec) => Object.freeze({ ...rec });

  /**
   * The stored entry a trusted handle names, or null. Identity first (the WeakMap gives
   * the one entry minted with this handle, never a later entry with the same turn id),
   * then the key the handle was minted for, then presence of that very entry in the
   * store (it may have been evicted); expiry is the caller's concern.
   * @param {string} key @param {unknown} handle @returns {Entry | null}
   */
  function entryFor(key, handle) {
    if (handle === null || typeof handle !== "object") return null;
    const entry = handles.get(handle);
    if (!entry || entry.key !== key || /** @type {TurnHandle} */ (handle).key !== key) return null;
    const turns = map.get(key);
    if (!turns || !turns.includes(entry)) return null;
    return entry;
  }

  return {
    /** @param {string} accountId @param {unknown} to */
    key(accountId, to) {
      return `${String(accountId ?? "default")}\u0000${normalizePeerId(to)}`;
    },
    /**
     * Stores a new turn (cardToolCalled always starts false, whatever `rec` carries) and
     * returns its trusted handle.
     * @param {string} key @param {Omit<InboundRecord, "cardToolCalled">} rec
     * @returns {TurnHandle}
     */
    record(key, rec) {
      const previous = map.get(key) ?? [];
      map.delete(key); // re-insert so the most recently active peer is last in iteration order
      /** @type {Entry} */
      const entry = {
        rec: {
          sessionKey: rec.sessionKey,
          turnId: rec.turnId,
          text: rec.text,
          receivedAt: rec.receivedAt,
          cardToolCalled: false,
        },
        storedAt: now(),
        key,
      };
      map.set(key, [entry, ...previous].slice(0, Math.max(1, turnsPerPeer)));
      while (map.size > maxEntries) {
        const oldest = map.keys().next().value;
        map.delete(oldest);
      }
      const handle = Object.freeze({ turnId: rec.turnId, key });
      handles.set(handle, entry);
      return handle;
    },
    /**
     * The record a trusted handle names, when the handle was minted by this instance for
     * this key and the turn is still stored and unexpired; otherwise null. A turn id
     * string or a look-alike object is not a handle.
     * @param {string} key @param {unknown} handle @returns {InboundRecord | null}
     */
    forTurn(key, handle) {
      const hit = entryFor(key, handle);
      if (!hit || expired(hit)) return null;
      return snapshot(hit.rec);
    },
    /**
     * Marks the turn a trusted handle names as having called a card tool. Returns true
     * when the mark was applied (or already stood); false, with nothing changed, for an
     * untrusted handle, a non-card tool name or a turn that is no longer stored.
     * @param {unknown} handle @param {unknown} toolName @returns {boolean}
     */
    markCardTool(handle, toolName) {
      if (!isCardTool(toolName)) return false;
      if (handle === null || typeof handle !== "object" || !handles.has(handle)) return false;
      const hit = entryFor(handles.get(handle).key, handle);
      if (!hit) return false;
      hit.rec.cardToolCalled = true;
      return true;
    },
    /**
     * Marks every stored, unexpired turn of a session. Fail closed: marking a concurrent
     * turn of the same session as well is acceptable, missing one is not. Returns the
     * number of turns marked; 0 for a non-string session key or a non-card tool name.
     * @param {unknown} sessionKey @param {unknown} toolName @returns {number}
     */
    markCardToolForSession(sessionKey, toolName) {
      if (typeof sessionKey !== "string" || !isCardTool(toolName)) return 0;
      let marked = 0;
      for (const turns of map.values()) {
        for (const entry of turns) {
          if (entry.rec.sessionKey === sessionKey && !expired(entry)) {
            entry.rec.cardToolCalled = true;
            marked += 1;
          }
        }
      }
      return marked;
    },
    size() {
      return map.size;
    },
  };
}
