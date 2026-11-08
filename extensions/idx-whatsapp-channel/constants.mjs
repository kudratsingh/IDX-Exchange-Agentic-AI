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

/** The one fixed text sent when a peer writes while their previous turn is still active
 *  (one active turn per peer, owner decision 19 (b), 2026-11-07). The overlapping message
 *  is not recorded and never reaches the host. Digit-free and distinct from SAFE_TEXT;
 *  sent in both withhold modes because it is a fixed constant, not a withheld reply
 *  (owner choice, flagged). The self-check refuses to register if it ever carries a
 *  digit, grows past 200 characters or equals SAFE_TEXT. */
export const BUSY_TEXT = "I'm still working on your last message. Please send this one again after I reply.";

/** The `blockReason` the host shows when a card tool call is refused. Fixed, digit-free,
 *  carries no peer, run id or session key. */
export const CARD_TOOL_BLOCK_REASON = "Listing tools run only inside a verified WhatsApp turn.";

/** "safe-text" sends SAFE_TEXT when the withheld send is bound to a trusted turn (the
 *  verifier ran against its record); a send with no handle, or an untrusted one, is
 *  `{ outcome: "not_sent" }` in either mode, and under "silent" every withhold is.
 *  Owner decision, pending. */
export const WITHHOLD_MODE = "safe-text";

/** Wall-clock budget for one synchronous verifier call, measured around the call. */
export const VERIFIER_DEADLINE_MS = 250;

/** Longest text the gate will release. Without a chunker this is one send unit. */
export const MAX_TEXT_LENGTH = 4000;

/** Ingress record lifetime and capacity (per process). The TTL is also the backstop for
 *  the one-active-turn rule: a turn whose run never settles stops counting as active
 *  once it is older than this (owner choice, flagged). */
export const INGRESS_TTL_MS = 1_800_000;
export const INGRESS_MAX_ENTRIES = 512;
/** Turns kept per peer, newest first, so a reply still in flight when the peer's next
 *  message arrives is verified against its own turn and not the newer one. */
export const INGRESS_TURNS_PER_PEER = 4;

/** Card reference grammar. The owned channel's card store (card-render.mjs) derives each
 *  ref from the listing id in the tool result, in this alphabet. */
export const CARD_REF_RE = /\[\[card:([A-Za-z0-9._-]{1,64})\]\]/gu;
/** A fragment of the grammar: a double bracket, or `card:` inside single brackets. A text
 *  with a fragment but no full match is malformed. Bare `card:` in prose ("discard:",
 *  "credit card:") is not a fragment, so digit-free clarifications keep working. */
export const PARTIAL_TOKEN_RE = /\[\[|\]\]|\[card:|card:[A-Za-z0-9._-]*\]/iu;
/** A figure is one maximal run of Unicode numeric characters (`\p{N}`: decimal digits
 *  in any script, other numerals such as ½ ⑫ ² and letter numerals such as Ⅻ). */
export const DIGIT_RUN_RE = /\p{N}+/gu;

/** Tools whose results carry card values (listing figures). They mirror ONE_COPY_TOOLS in
 *  `src/idx_agent/mcp_server/server.py`, spelled as the server names them; a turn that
 *  called one of them may release only verified card tokens (verifier rule R1b). */
export const CARD_TOOLS = Object.freeze([
  "search_listings",
  "get_market_stats",
  "find_similar_listings",
  "recommend",
]);

/** Namespace separators a host may put in front of the server's tool name. The host
 *  presents MCP tools as `idx__<tool>` (ADR-0003); a dotted, slashed or colon-separated
 *  prefix is accepted on the same footing so the mark cannot be lost to a spelling. */
const TOOL_NAMESPACE_SEPARATOR_RE = /__|[./:]/u;
/** The host's collision suffix on a bundled MCP tool name: `<server>__<tool>-N` when two
 *  sanitised names collide (host trace 2026-11-07, WO-037 install prerequisite 5). */
const TOOL_COLLISION_SUFFIX_RE = /-\d+$/u;

/**
 * Whether a tool name from the host's tool-call event names a card tool. Fails closed on
 * spelling: the exact `CARD_TOOLS` name matches, and so does any spelling whose trimmed,
 * lowercased last segment after a namespace separator (`__`, `.`, `/`, `:`) is one, with
 * or without the host's `-N` collision suffix (`idx__search_listings`,
 * `mcp__idx__search_listings`, `Search_Listings`, ` search_listings `,
 * `idx__search_listings-2`). Over-identifying a card tool is the safe direction: the call
 * then needs a verified WhatsApp turn to run, and a marked turn releases only card
 * tokens. A name that differs in any other way (`search_listing`, `search_listings_v2`,
 * `search_listings-v2`, `get_listing_details`) is not a card tool. A host name cut short
 * inside the tool segment by the host's 64-character cap is not recognised here; the
 * install PR asserts the literal host names of every `CARD_TOOLS` tool at startup.
 * @param {unknown} name @returns {boolean}
 */
export function isCardTool(name) {
  return cardToolBase(name) !== null;
}

/**
 * The `CARD_TOOLS` name a host tool name stands for, by exactly the rule `isCardTool`
 * applies (`idx__search_listings-2` -> `search_listings`), or null. The card renderer
 * picks its result shape by this name.
 * @param {unknown} name @returns {string | null}
 */
export function cardToolBase(name) {
  if (typeof name !== "string") return null;
  if (CARD_TOOLS.includes(name)) return name;
  const segments = name.trim().toLowerCase().split(TOOL_NAMESPACE_SEPARATOR_RE);
  const last = segments[segments.length - 1];
  if (last === "") return null;
  if (CARD_TOOLS.includes(last)) return last;
  const bare = last.replace(TOOL_COLLISION_SUFFIX_RE, "");
  return CARD_TOOLS.includes(bare) ? bare : null;
}

/** Longest card the renderer produces; a longer one is not stored (no card for that ref). */
export const CARD_MAX_LENGTH = 700;
/** Cards rendered from one tool result at most (a search page holds at most 50 listings). */
export const CARD_MAX_PER_RESULT = 50;
/** Cards stored for one turn at most, across all its card tool results. */
export const CARD_MAX_PER_TURN = 100;
/** Admitted card calls remembered per turn for result capture (by tool call id). */
export const CARD_CALLS_PER_TURN = 8;

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
