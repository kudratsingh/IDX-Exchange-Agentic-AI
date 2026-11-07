/**
 * Constants shared by the idx-whatsapp-channel skeleton. Every value is frozen.
 *
 * Node built-ins only. No SDK, vendor or test-support import anywhere in the
 * runtime modules of this directory.
 */

/** Manifest id. Must differ from the stock plugin id so `plugins.deny: ["whatsapp"]`
 *  blocks only the stock plugin (policy ids are the lowercased plugin id). */
export const PLUGIN_ID = "idx-whatsapp-channel";

/** The channel id this plugin claims. */
export const CHANNEL_ID = "whatsapp";

/** The stock plugin's manifest id that the host config must deny. */
export const STOCK_PLUGIN_ID = "whatsapp";

/** The one fixed text sent when a reply is withheld and the peer has an open turn.
 *  Digit-free; the startup self-check refuses to register if this ever changes to
 *  carry a digit or grow past 200 characters. */
export const SAFE_TEXT = "I couldn't send that reply safely. Please ask again.";

/** "safe-text" sends SAFE_TEXT to a peer with a current inbound record; otherwise
 *  (and always under "silent") a withheld reply becomes `{ outcome: "not_sent" }`.
 *  Owner decision, pending. */
export const WITHHOLD_MODE = "safe-text";

/** Wall-clock budget for one synchronous verifier call, measured around the call. */
export const VERIFIER_DEADLINE_MS = 250;

/** Longest text the gate will release. Without a chunker this is one send unit. */
export const MAX_TEXT_LENGTH = 4000;

/** Ingress record lifetime and capacity (per process). */
export const INGRESS_TTL_MS = 1_800_000;
export const INGRESS_MAX_ENTRIES = 512;
/** Turns kept per peer, newest first, so a reply still in flight when the peer's next
 *  message arrives is verified against its own turn and not the newer one. */
export const INGRESS_TURNS_PER_PEER = 4;

/** Card reference grammar. Placeholder until the card resolver of #179 plugs in. */
export const CARD_REF_RE = /\[\[card:([A-Za-z0-9._-]{1,64})\]\]/gu;
/** A fragment of the grammar: a double bracket, or `card:` inside single brackets. A text
 *  with a fragment but no full match is malformed. Bare `card:` in prose ("discard:",
 *  "credit card:") is not a fragment, so digit-free clarifications keep working. */
export const PARTIAL_TOKEN_RE = /\[\[|\]\]|\[card:|card:[A-Za-z0-9._-]*\]/iu;
/** A figure is one maximal run of Unicode numeric characters (`\p{N}`: decimal digits
 *  in any script, other numerals such as ½ ⑫ ² and letter numerals such as Ⅻ). */
export const DIGIT_RUN_RE = /\p{N}+/gu;

/** Registration modes in which register(api) does nothing (no self-check, no channel). */
export const SKIP_REGISTRATION_MODES = Object.freeze(["cli-metadata", "tool-discovery"]);
/** Registration modes in which the self-check runs and the channel is registered. */
export const REGISTER_MODES = Object.freeze([
  "full",
  "discovery",
  "setup-only",
  "setup-runtime",
]);

/** The only Transport members the runtime may use. A source test pins this. */
export const TRANSPORT_METHODS = Object.freeze(["start", "stop", "sendText", "isConfigured"]);
