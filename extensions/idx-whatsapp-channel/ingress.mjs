/**
 * Ingress records: the newest inbound turns per (accountId, peer), kept in process
 * memory so the outbound gate can verify a reply against what the user wrote.
 * Stores only what the verifier needs; never logs text, peer ids, session keys or run ids.
 *
 * Trusted turn handles: `record` returns a frozen `{ turnId, key }` whose identity is the
 * key of a WeakMap private to this instance, mapping the handle to the stored entry it
 * was minted for. Only that object names a turn to `forTurn`, `confirmRun` and `endRun`;
 * a string, or a plain object with the same fields, is not a handle, and a second record
 * that happens to carry the same turn id is a different entry with its own handle. The
 * channel keeps the handle in the closure of the turn it minted it for and never hands
 * it to the host runner. There is no lookup of a record by key alone (owner decision 17).
 *
 * Run binding (owner decision 19, 2026-11-07). A turn may carry one run id, chosen by
 * the channel (`randomUUID`) and handed to the host as `replyOptions.runId`. It is
 * stored privately with the entry, one run id to one entry, and never appears in a
 * record snapshot. The run is confirmed (`runBound`, monotonic) only when the host's
 * run-start callback reports exactly that id while the turn is stored, unexpired and
 * its run not ended; it ends when the channel's `runInbound` call settles (`endRun`).
 *
 * `admitCardCall` is the only way a turn is marked `cardToolCalled` (monotonic, never
 * cleared, never inherited by a later turn). It names the turn by the host's run id and
 * admits a card tool call only for a stored, unexpired turn whose run is confirmed and
 * not ended, whose stored session key equals the call's, and, when the host supplies a
 * requester, whose peer and account the requester names.
 *
 * Tied refusals (owner decision 21, 2026-11-07). A refused card call is tied to a turn
 * only when every run-binding check that admission uses has passed for that turn: the run
 * id names a stored, unexpired entry whose run is confirmed and not ended, and the call's
 * session key is that entry's. Today the only refusal reached after those checks is
 * `requester-mismatch` (a requester check that throws included). A tied refusal sets
 * `cardCallRefused` on that one entry (monotonic, never cleared, never inherited by a
 * later turn) and returns `withheld: true`; the verifier then withholds every later reply
 * on that turn. Every earlier refusal is of unknown origin: it refuses the call only and
 * changes nothing. A session key alone (no run id, a foreign, unconfirmed or ended run)
 * ties nothing, so it can never suppress another turn.
 *
 * A turn is active from `record` until its run ends; the TTL is the backstop when a run
 * never settles. `hasActiveTurn` answers that for one peer key (one active turn per
 * peer). Active turns are tracked apart from the record store, so capacity eviction of a
 * peer's records never ends that peer's active turn: an evicted turn whose run is still
 * open keeps the peer busy until the run ends or the TTL passes (its card calls are
 * refused `turn-expired` and its replies are untrusted meanwhile, both fail-closed).
 * Lookups return frozen copies, so a caller cannot flip a stored flag.
 *
 * Turn-bound card store (owned-channel install item 3, 2026-11-07). An admitted card call
 * that carries the host's tool call id is remembered on its entry (at most
 * CARD_CALLS_PER_TURN). `captureCards` stores the cards rendered from that call's result
 * on the same entry, only for exactly that run id, session key, tool name and tool call
 * id, while the entry is stored, unexpired, confirmed and its run not ended; each call id
 * is captured once. `resolveCard(ref, { sessionKey, turnId })` returns `{ text }` only
 * for a card stored on the one stored, unexpired entry with that session key and turn id
 * (two such entries: ambiguous, null). Cards live and die with their entry: eviction or
 * the TTL removes them. At most CARD_MAX_PER_TURN cards per turn; a ref captured twice
 * with different texts resolves to nothing.
 */

import {
  CARD_CALLS_PER_TURN,
  CARD_MAX_LENGTH,
  CARD_MAX_PER_TURN,
  INGRESS_MAX_ENTRIES,
  INGRESS_TTL_MS,
  INGRESS_TURNS_PER_PEER,
  isCardTool,
} from "./constants.mjs";

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
  /**
   * @typedef {{ rec: InboundRecord, storedAt: number, key: string,
   *   runId: string | undefined, runEnded: boolean, accountId: string, peer: string,
   *   admittedCalls: Map<string, { toolName: string, captured: boolean }>, cards: Map<string, string | null> }} Entry
   */
  /** @type {Map<string, Entry[]>} */
  const map = new Map();
  /** Every handle this instance minted, by identity, to the one entry it names. Module-private; nothing exposes it. */
  const handles = new WeakMap();
  /** Run id -> the one entry it was issued for. Instance-private; never exposed or logged.
   *  Kept for a while after an entry is evicted so a late call reports `turn-expired`;
   *  bounded by `runCap` (oldest evicted runs are forgotten first). */
  /** @type {Map<string, Entry>} */
  const runs = new Map();
  const runCap = Math.max(1, maxEntries) * Math.max(1, turnsPerPeer) * 2;
  /** Peer key -> the entries recorded for it whose run has not ended. Independent of
   *  `map`: capacity eviction never removes an entry here, only `endRun` or the TTL does,
   *  so eviction cannot open a second concurrent turn for a peer whose run is still open
   *  (owner decision 19 (b)). Bounded by the TTL: expired entries are swept lazily. */
  /** @type {Map<string, Set<Entry>>} */
  const active = new Map();

  /** @param {Entry} entry */
  const expired = (entry) => now() - entry.storedAt > ttlMs;

  /** @param {Entry} entry */
  const stored = (entry) => {
    const turns = map.get(entry.key);
    return Boolean(turns && turns.includes(entry));
  };

  /** @param {unknown} accountId @param {unknown} to */
  const keyOf = (accountId, to) => `${String(accountId ?? "default")}\u0000${normalizePeerId(to)}`;

  /** @param {InboundRecord} rec */
  const snapshot = (rec) => Object.freeze({ ...rec });

  /**
   * The stored, unexpired entry a trusted handle names, or null. Identity first (the
   * WeakMap gives the one entry minted with this handle, never a later entry with the
   * same turn id), then the key the handle was minted for, then presence of that very
   * entry in the store (it may have been evicted), then the TTL.
   * @param {string} key @param {unknown} handle @returns {Entry | null}
   */
  function entryFor(key, handle) {
    if (handle === null || typeof handle !== "object") return null;
    const entry = handles.get(handle);
    if (!entry || entry.key !== key || /** @type {TurnHandle} */ (handle).key !== key) return null;
    if (!stored(entry)) return null;
    if (expired(entry)) return null;
    return entry;
  }

  /** @param {Entry} entry */
  const dropActive = (entry) => {
    const set = active.get(entry.key);
    if (!set) return;
    set.delete(entry);
    if (set.size === 0) active.delete(entry.key);
  };

  /** Drops expired entries from the active index once it outgrows the record store. */
  function sweepActive() {
    if (active.size <= maxEntries) return;
    for (const set of [...active.values()]) {
      for (const entry of [...set]) if (expired(entry)) dropActive(entry);
    }
  }

  /** Forgets the oldest run ids whose entries are no longer stored, down to `runCap`. */
  function pruneRuns() {
    if (runs.size <= runCap) return;
    for (const [id, entry] of runs) {
      if (runs.size <= runCap) break;
      if (!stored(entry)) runs.delete(id);
    }
  }

  return {
    /** @param {string} accountId @param {unknown} to */
    key(accountId, to) {
      return keyOf(accountId, to);
    },
    /**
     * Stores a new turn and returns its trusted handle. `cardToolCalled`, `runBound` and
     * `cardCallRefused` always start false, whatever `rec` carries. With `run`, the turn carries that run
     * id (stored privately) and the account and peer it belongs to; the record is refused
     * (null, nothing stored) when the run id is not a non-empty string or was already
     * issued to another stored entry, or when the account and peer do not give `key`.
     * Without `run` the turn has no run: it can never be confirmed, so every reply bound
     * to it is withheld `unbound-turn` and no card call is ever admitted for it.
     * @param {string} key
     * @param {Omit<InboundRecord, "cardToolCalled" | "runBound" | "cardCallRefused">} rec
     * @param {{ runId: string, accountId: string, peerId: string }} [run]
     * @returns {TurnHandle | null}
     */
    record(key, rec, run) {
      let runId;
      let accountId = "";
      let peer = "";
      if (run !== undefined) {
        if (run === null || typeof run !== "object") return null;
        const { runId: id, accountId: acct, peerId } = run;
        if (typeof id !== "string" || id === "") return null;
        if (typeof acct !== "string" || typeof peerId !== "string") return null;
        if (runs.has(id)) return null; // one run id, one entry
        if (keyOf(acct, peerId) !== key) return null;
        runId = id;
        accountId = acct;
        peer = normalizePeerId(peerId);
      }
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
          runBound: false,
          cardCallRefused: false,
        },
        storedAt: now(),
        key,
        runId,
        runEnded: false,
        accountId,
        peer,
        admittedCalls: new Map(),
        cards: new Map(),
      };
      map.set(key, [entry, ...previous].slice(0, Math.max(1, turnsPerPeer)));
      while (map.size > maxEntries) {
        const oldest = map.keys().next().value;
        map.delete(oldest);
      }
      if (runId !== undefined) runs.set(runId, entry);
      const set = active.get(key) ?? new Set();
      set.add(entry);
      active.set(key, set);
      sweepActive();
      pruneRuns();
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
      if (!hit) return null;
      return snapshot(hit.rec);
    },
    /**
     * Confirms the run of the turn a trusted handle names. True only when `runId` is
     * exactly the run id issued for that turn and the turn is stored, unexpired and its
     * run not ended; it then sets `runBound` (monotonic: a later call with another value
     * returns false and changes nothing).
     * @param {unknown} handle @param {unknown} runId @returns {boolean}
     */
    confirmRun(handle, runId) {
      if (handle === null || typeof handle !== "object" || !handles.has(handle)) return false;
      const hit = entryFor(handles.get(handle).key, handle);
      if (!hit || hit.runId === undefined || typeof runId !== "string" || runId !== hit.runId) return false;
      if (hit.runEnded) return false;
      hit.rec.runBound = true;
      return true;
    },
    /**
     * Ends the run of the turn a trusted handle names: its run id no longer admits card
     * calls and the turn stops being active. Idempotent; works on an evicted or expired
     * turn too. Replies bound by the handle are unaffected.
     * @param {unknown} handle @returns {boolean}
     */
    endRun(handle) {
      if (handle === null || typeof handle !== "object" || !handles.has(handle)) return false;
      const entry = handles.get(handle);
      entry.runEnded = true;
      dropActive(entry);
      return true;
    },
    /**
     * Whether the peer key has an active turn: recorded, unexpired, its run not ended.
     * Reads the active index, not the record store, so a turn evicted for capacity while
     * its run is still open still counts until the run ends or the TTL passes.
     * @param {string} key @returns {boolean}
     */
    hasActiveTurn(key) {
      const set = active.get(key);
      if (!set) return false;
      for (const entry of [...set]) {
        if (entry.runEnded || expired(entry)) dropActive(entry);
      }
      return active.has(key);
    },
    /**
     * Admits one card tool call for the turn its run id names and marks THAT turn only.
     * Checks in order: card tool name; run id known ("unknown-run"); turn stored and
     * unexpired ("turn-expired"); run not ended ("run-ended"); run confirmed
     * ("run-unconfirmed"); session key equal to the turn's ("session-mismatch"); and, when
     * `requesterMatches` is given, that it returns true for the turn's canonical peer and
     * account id ("requester-mismatch").
     *
     * A refusal reached after the session-key check is TIED to the entry the run id names
     * (owner decision 21): it sets that entry's `cardCallRefused` and returns
     * `{ admitted: false, reason, withheld: true }`. Every earlier refusal is of unknown
     * origin and returns `{ admitted: false, reason }` (no `withheld` key) with nothing
     * changed. No other entry is ever touched.
     * `toolCallId` (the host's id for this call) plays no part in admission; when it is a
     * non-empty string, an admitted call is remembered under it so `captureCards` can
     * accept that call's result.
     * @param {{ runId: unknown, sessionKey: unknown, toolName: unknown,
     *   requesterMatches?: (peer: string, accountId: string) => boolean, toolCallId?: unknown }} call
     * @returns {{ admitted: true } | { admitted: false, reason: string }
     *   | { admitted: false, reason: "requester-mismatch", withheld: true }}
     */
    admitCardCall({ runId, sessionKey, toolName, requesterMatches, toolCallId }) {
      if (!isCardTool(toolName)) return { admitted: false, reason: "not-card-tool" };
      if (typeof runId !== "string" || runId === "") return { admitted: false, reason: "unknown-run" };
      const entry = runs.get(runId);
      if (!entry) return { admitted: false, reason: "unknown-run" };
      if (!stored(entry) || expired(entry)) return { admitted: false, reason: "turn-expired" };
      if (entry.runEnded) return { admitted: false, reason: "run-ended" };
      if (entry.rec.runBound !== true) return { admitted: false, reason: "run-unconfirmed" };
      if (typeof sessionKey !== "string" || sessionKey !== entry.rec.sessionKey) {
        return { admitted: false, reason: "session-mismatch" };
      }
      if (requesterMatches !== undefined) {
        let ok = false;
        try {
          ok = typeof requesterMatches === "function" && requesterMatches(entry.peer, entry.accountId) === true;
        } catch {
          ok = false;
        }
        if (!ok) {
          // Tied: the run id and session key bind this call to this live, confirmed turn, so
          // it is that turn's own call with inconsistent peer data. Withhold that turn only.
          entry.rec.cardCallRefused = true;
          return { admitted: false, reason: "requester-mismatch", withheld: true };
        }
      }
      entry.rec.cardToolCalled = true;
      // Remember the admitted call by the host's tool call id, so its result (and only
      // its result) can later be captured as this turn's cards. Without an id the call is
      // still admitted, but nothing it returns can become a card.
      if (typeof toolCallId === "string" && toolCallId !== "" && entry.admittedCalls.size < CARD_CALLS_PER_TURN) {
        if (!entry.admittedCalls.has(toolCallId)) entry.admittedCalls.set(toolCallId, { toolName, captured: false });
      }
      return { admitted: true };
    },
    /**
     * Stores the cards rendered from one admitted card call's result on that call's turn.
     * Checks: run id names a stored, unexpired entry whose run is confirmed and not ended;
     * the session key is the entry's; the tool call id was admitted for this entry with
     * exactly this tool name and has not been captured yet. Then the call id is consumed
     * and each `{ ref, text }` (string ref, non-empty string text within CARD_MAX_LENGTH)
     * is stored, up to CARD_MAX_PER_TURN refs per turn; a ref already stored with a
     * different text is poisoned (resolves to nothing). Returns the number of cards now
     * resolvable from this capture, or a refusal code; never throws on odd input.
     * @param {{ runId: unknown, sessionKey: unknown, toolName: unknown, toolCallId: unknown,
     *   cards: unknown }} capture
     * @returns {{ stored: number } | { stored: 0, reason: string }}
     */
    captureCards({ runId, sessionKey, toolName, toolCallId, cards }) {
      if (typeof runId !== "string" || runId === "") return { stored: 0, reason: "unknown-run" };
      const entry = runs.get(runId);
      if (!entry) return { stored: 0, reason: "unknown-run" };
      if (!stored(entry) || expired(entry)) return { stored: 0, reason: "turn-expired" };
      if (entry.runEnded) return { stored: 0, reason: "run-ended" };
      if (entry.rec.runBound !== true) return { stored: 0, reason: "run-unconfirmed" };
      if (typeof sessionKey !== "string" || sessionKey !== entry.rec.sessionKey) return { stored: 0, reason: "session-mismatch" };
      const call = typeof toolCallId === "string" ? entry.admittedCalls.get(toolCallId) : undefined;
      if (!call || call.toolName !== toolName) return { stored: 0, reason: "call-not-admitted" };
      if (call.captured) return { stored: 0, reason: "already-captured" };
      // Consumed before anything is stored: a second result for the same call stores nothing.
      call.captured = true;
      if (!Array.isArray(cards)) return { stored: 0, reason: "no-cards" };
      let count = 0;
      for (const card of cards) {
        if (card === null || typeof card !== "object") continue;
        const { ref, text } = card;
        if (typeof ref !== "string" || ref === "" || typeof text !== "string" || text === "" || text.length > CARD_MAX_LENGTH) continue;
        if (entry.cards.has(ref)) {
          if (entry.cards.get(ref) !== text) entry.cards.set(ref, null);
          else count += 1;
          continue;
        }
        if (entry.cards.size >= CARD_MAX_PER_TURN) continue;
        entry.cards.set(ref, text);
        count += 1;
      }
      return { stored: count };
    },
    /**
     * The card stored under `ref` for the one stored, unexpired turn with this session
     * key and turn id, as a fresh frozen `{ text }`; otherwise null.
     * @param {unknown} ref @param {unknown} binding
     * @returns {Readonly<{ text: string }> | null}
     */
    resolveCard(ref, binding) {
      if (typeof ref !== "string" || ref === "" || binding === null || typeof binding !== "object") return null;
      const { sessionKey, turnId } = /** @type {any} */ (binding);
      if (typeof sessionKey !== "string" || typeof turnId !== "string") return null;
      let hit = null;
      for (const turns of map.values()) {
        for (const entry of turns) {
          if (entry.rec.turnId !== turnId || entry.rec.sessionKey !== sessionKey || expired(entry)) continue;
          if (hit !== null) return null; // two live turns share the binding: ambiguous
          hit = entry;
        }
      }
      if (hit === null) return null;
      const text = hit.cards.get(ref);
      return typeof text === "string" ? Object.freeze({ text }) : null;
    },
    size() {
      return map.size;
    },
  };
}
