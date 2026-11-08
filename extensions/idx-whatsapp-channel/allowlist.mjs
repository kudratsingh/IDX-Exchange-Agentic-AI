/**
 * Inbound sender allowlist (runbook item C3; SAFETY_INVARIANTS: "senders outside the
 * allowlist get no reply"). Pure: reads the channel config the host passed to the
 * account (`channels.whatsapp`), never a file or the environment.
 *
 * Source, per account: `channels.whatsapp.accounts.<accountId>.dmPolicy` / `.allowFrom`
 * when that key is present on the account object, else `channels.whatsapp.dmPolicy` /
 * `.allowFrom`. A present account key never falls back to the channel-wide one, so an
 * empty per-account list drops everything for that account.
 *
 * Fail closed. Every inbound is dropped when:
 *   - the channel section (or the account object, when present) is missing or not an object,
 *     or has `enabled: false`;
 *   - `dmPolicy` is not exactly "allowlist". This channel implements no pairing and no
 *     open mode, so "pairing" or "open" (stock WhatsApp values) would be a configuration
 *     this channel cannot honour; it drops instead of guessing;
 *   - `allowFrom` is missing, not an array, empty, or has ANY entry that is not a string
 *     naming a phone number (after `normalizePeerId`, `+` and 7 to 15 digits). A wildcard
 *     ("*"), a linked id (`@lid`), a placeholder or a typo therefore drops everyone rather
 *     than being skipped, so a broken list is noticed at once.
 * Otherwise the sender is admitted only when its canonical id (`normalizePeerId`) equals
 * the canonical id of an entry. A linked-id sender (`<digits>@lid`) never equals a phone
 * entry, so it is dropped.
 */

import { CHANNEL_ID } from "./constants.mjs";
import { normalizePeerId } from "./ingress.mjs";

/** A canonical phone-number peer id: `+` and 7 to 15 digits (E.164 length). */
const CANONICAL_PHONE_RE = /^\+\d{7,15}$/u;

/** @param {unknown} v @returns {v is Record<string, unknown>} */
const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * The access policy in force for one account.
 * @param {unknown} cfg the host config snapshot
 * @param {unknown} accountId
 * @returns {{ ok: true, allowed: ReadonlySet<string> } | { ok: false, reason: "no-channel-config" | "channel-disabled" | "dm-policy-not-allowlist" | "allowlist-empty" | "allowlist-malformed" | "allowlist-error" }}
 */
export function resolveDmAccess(cfg, accountId) {
  try {
    const section = isPlainObject(cfg) && isPlainObject(cfg.channels) ? cfg.channels[CHANNEL_ID] : undefined;
    if (!isPlainObject(section)) return { ok: false, reason: "no-channel-config" };
    if (section.enabled === false) return { ok: false, reason: "channel-disabled" };
    const accounts = section.accounts;
    const id = typeof accountId === "string" && accountId !== "" ? accountId : "default";
    let account;
    if (accounts !== undefined) {
      if (!isPlainObject(accounts)) return { ok: false, reason: "no-channel-config" };
      if (Object.prototype.hasOwnProperty.call(accounts, id)) {
        account = accounts[id];
        if (!isPlainObject(account)) return { ok: false, reason: "no-channel-config" };
        if (account.enabled === false) return { ok: false, reason: "channel-disabled" };
      }
    }
    const pick = (k) => (account && Object.prototype.hasOwnProperty.call(account, k) && account[k] !== undefined ? account[k] : section[k]);
    if (pick("dmPolicy") !== "allowlist") return { ok: false, reason: "dm-policy-not-allowlist" };
    const allowFrom = pick("allowFrom");
    if (!Array.isArray(allowFrom)) return { ok: false, reason: "allowlist-malformed" };
    if (allowFrom.length === 0) return { ok: false, reason: "allowlist-empty" };
    const allowed = new Set();
    for (const entry of allowFrom) {
      if (typeof entry !== "string" || entry.trim() === "") return { ok: false, reason: "allowlist-malformed" };
      const canonical = normalizePeerId(entry);
      if (!CANONICAL_PHONE_RE.test(canonical)) return { ok: false, reason: "allowlist-malformed" };
      allowed.add(canonical);
    }
    return { ok: true, allowed };
  } catch {
    return { ok: false, reason: "allowlist-error" };
  }
}

/**
 * Whether one inbound sender may reach the channel at all.
 * @param {unknown} cfg @param {unknown} accountId @param {unknown} peerId the transport's sender id
 * @returns {{ allowed: true } | { allowed: false, reason: string }}
 */
export function senderAllowed(cfg, accountId, peerId) {
  const access = resolveDmAccess(cfg, accountId);
  if (!access.ok) return { allowed: false, reason: access.reason };
  if (typeof peerId !== "string" || peerId.trim() === "") return { allowed: false, reason: "sender-not-allowed" };
  return access.allowed.has(normalizePeerId(peerId)) ? { allowed: true } : { allowed: false, reason: "sender-not-allowed" };
}
