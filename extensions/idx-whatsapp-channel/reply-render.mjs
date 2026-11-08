/**
 * Reply renderer (approved reply passthrough, 2026-11-08): pure, deterministic functions
 * from one card tool call's outcome to one reply section, and from a turn's sections to
 * the one reply text that `[[card:reply]]` stands for.
 *
 * The `idx` server already writes the reply for every card tool result in code: an
 * `ok: true` envelope's `message` (src/idx_agent/channels/format.py, called from
 * src/idx_agent/mcp_server/server.py, with every caveat, empty result, clarification and
 * market not-enough-comps step the tool reports). The channel no longer rewords it; it
 * releases exactly that text, so the reply cannot drift from what the server approved.
 *
 * `renderToolSection(toolName, result, error)` -> a frozen `{ tool, text }`, or null.
 *   - Only the exact host names in CARD_TOOL_HOST_NAMES are rendered. Any other name (a
 *     foreign server's `other__search_listings`, a collision-suffixed
 *     `idx__search_listings-2`, a bare `recommend`) gives null, so a result captured under
 *     it withholds the turn's reply (the before_tool_call admission still matches those
 *     names broadly and fails closed).
 *   - The result is read as the card renderer reads it (`resultEnvelope`: the host's one
 *     text block, with its `structuredContent:` label).
 *   - `ok: true`: the section text is `message`, exactly, when it is a safe text: a
 *     non-empty string of at most MAX_TEXT_LENGTH characters with no control character
 *     but the newline and no line or paragraph separator, format (bidi, zero-width, BOM,
 *     soft hyphen), surrogate or private-use character. Anything else gives null
 *     (withheld): a listing whose stored address holds such a character withholds the
 *     whole page (payload search-format-char), and the server's text is never edited.
 *   - A clarification (`data.question` equal to `message`) with a non-empty
 *     `data.options` list: `message`, a blank line, then REPLY_LINES.options and the
 *     options exactly as the server lists them, in its order, joined by ", ". Every card
 *     skill's approved reply is "ask exactly data.question, and list data.options if
 *     present", and the token-only turn leaves the model no room to list them. Each
 *     option must be a closed-list name (OPTION_RE: subtype, feature or filter names);
 *     any other option, or options beside a non-clarification, gives null (withheld).
 *   - `ok: false`: the server's `error.message`, exactly, under the same safe-text rule.
 *     Every error a card tool returns carries a fixed server sentence (a database,
 *     provider, not-set-up, not-active or internal failure, some with "(ref abcdef)"
 *     from the trace id); none carries row data or exception text, which stays in the
 *     internal `detail`. An error without a safe message gets the tool's fixed line.
 *   - An MCP `isError` result or an `after_tool_call` error string (host or transport
 *     text, never the server's) gets the tool's fixed line in REPLY_LINES.unavailable.
 *
 * `composeReply(sections)` -> string | null: the sections' texts in the given order (call
 * order), one blank line apart, nothing merged or dropped; null when a section is not a
 * section or the joined reply is longer than MAX_TEXT_LENGTH (withheld, never cut).
 *
 * Imports constants.mjs and card-render.mjs only; no I/O, no clock, no randomness.
 */

import { CARD_TOOL_HOST_NAMES, HOST_TRUNCATION_MARKER, IDX_MCP_SERVER, MAX_TEXT_LENGTH, hasUnsafeChar } from "./constants.mjs";
import { isPlainObject, resultEnvelope } from "./card-render.mjs";

/** Our own lines: the lead in front of a clarification's options, and the line for an
 *  outcome that carries no server text. Fixed and digit-free; the reply tests pin each
 *  one. */
export const REPLY_LINES = Object.freeze({
  options: "Options: ",
  unavailable: Object.freeze({
    search_listings: "The listing search isn't available right now. Please try again in a minute.",
    get_market_stats: "The market figures aren't available right now. Please try again in a minute.",
    find_similar_listings: "Finding similar listings isn't available right now. Please try again in a minute.",
    recommend: "Recommendations aren't available right now. Please try again in a minute.",
  }),
});

/** A clarification option the channel lists: a closed-list name as the server writes
 *  it (`SingleFamilyResidence`, `walk_in_closet`, `min_price`), never free text. */
const OPTION_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/u;

/**
 * True when `text` may be released as it is.
 * @param {unknown} text @returns {text is string}
 */
export function safeText(text) {
  return (
    typeof text === "string" &&
    text.trim() !== "" &&
    text.length <= MAX_TEXT_LENGTH &&
    !hasUnsafeChar(text)
  );
}

/** The CARD_TOOLS name for an exact card tool host name, or null. @param {unknown} name */
function hostTool(name) {
  return typeof name === "string" && Object.prototype.hasOwnProperty.call(CARD_TOOL_HOST_NAMES, name) ? CARD_TOOL_HOST_NAMES[name] : null;
}

/** @param {string} tool @param {string} text */
const section = (tool, text) => Object.freeze({ tool, text });

/**
 * The approved reply of an `ok: true` envelope: `message`, plus a clarification's
 * options when it lists any; null when it cannot be released as it is.
 * @param {Record<string, unknown>} env @returns {string | null}
 */
function okReply(env) {
  const { message, data } = env;
  if (!safeText(message)) return null;
  const options = isPlainObject(data) ? data.options : undefined;
  if (options === undefined || options === null) return message;
  if (!Array.isArray(options) || data.question !== message) return null;
  if (options.length === 0) return message;
  if (!options.every((o) => typeof o === "string" && OPTION_RE.test(o))) return null;
  const text = `${message}\n\n${REPLY_LINES.options}${options.join(", ")}`;
  return safeText(text) ? text : null;
}

/** The approved reply text of an envelope (ok:true message, ok:false server error sentence),
 *  the fixed unavailable line when an ok:false envelope has no usable sentence, or null. */
function approvedText(tool, env) {
  if (!isPlainObject(env)) return null;
  if (env.ok === true) return okReply(env);
  if (env.ok === false) {
    const message = isPlainObject(env.error) ? env.error.message : undefined;
    return safeText(message) ? message : REPLY_LINES.unavailable[tool];
  }
  return null;
}

/**
 * The envelope to release from, read from what the host handed `after_tool_call`.
 *
 * Real host (OpenClaw 2026.9.5, harness 2026-11-08): the text block is cut at 8000
 * characters with HOST_TRUNCATION_MARKER, so a long result's text no longer parses; the
 * full structured result rides in `result.details.structuredContent`, with
 * `details.mcpServer` and `details.mcpTool` naming its source (the host redacts key-like
 * fields there, e.g. `listing_key` -> "***", which the approved reply does not use).
 *
 *   - details with a structured result: it must come from the idx server and this very tool,
 *     else null (a foreign server's result never becomes the reply). When the text block is
 *     also complete (not truncated) and parses, both must give the same approved reply, else
 *     null. The details envelope is returned.
 *   - no structured details: the single labelled text block, only when not truncated.
 * @param {string} tool @param {unknown} result @returns {Record<string, unknown> | null}
 */
function sourceEnvelope(tool, result) {
  if (!isPlainObject(result)) return null;
  const texts = Array.isArray(result.content) ? result.content.filter((c) => isPlainObject(c) && c.type === "text") : [];
  const text = texts.length === 1 && typeof texts[0].text === "string" ? texts[0].text : null;
  const truncated = text !== null && text.endsWith(HOST_TRUNCATION_MARKER);
  const details = result.details;
  const structured = isPlainObject(details) ? details.structuredContent : undefined;
  if (isPlainObject(structured)) {
    if (details.mcpServer !== IDX_MCP_SERVER || details.mcpTool !== tool) return null;
    if (text !== null && !truncated) {
      const fromText = resultEnvelope(result);
      if (fromText === null || approvedText(tool, fromText) !== approvedText(tool, structured)) return null;
    }
    return structured;
  }
  if (structured !== undefined || truncated) return null;
  return resultEnvelope(result);
}

/**
 * The reply section for one card tool call's outcome, or null (withheld).
 * @param {unknown} toolName the host's tool name
 * @param {unknown} result the host's tool result (`after_tool_call` event.result)
 * @param {unknown} [error] the host's `after_tool_call` event.error
 * @returns {Readonly<{ tool: string, text: string }> | null}
 */
export function renderToolSection(toolName, result, error) {
  try {
    const tool = hostTool(toolName);
    if (tool === null) return null;
    const unavailable = section(tool, REPLY_LINES.unavailable[tool]);
    if (typeof error === "string" && error !== "") return unavailable;
    if (isPlainObject(result) && result.isError === true) return unavailable;
    const env = sourceEnvelope(tool, result);
    if (env === null) return null;
    const text = approvedText(tool, env);
    return text === null ? null : section(tool, text);
  } catch {
    return null;
  }
}

const PARA = "\n\n";

/** @param {unknown} s */
const isSection = (s) => isPlainObject(s) && typeof s.tool === "string" && safeText(s.text);

/**
 * The one reply for a turn's sections, in order, or null.
 * @param {unknown} sections
 * @returns {string | null}
 */
export function composeReply(sections) {
  try {
    if (!Array.isArray(sections) || sections.length === 0 || !sections.every(isSection)) return null;
    const text = sections.map((s) => s.text).join(PARA);
    return text.length <= MAX_TEXT_LENGTH ? text : null;
  } catch {
    return null;
  }
}
