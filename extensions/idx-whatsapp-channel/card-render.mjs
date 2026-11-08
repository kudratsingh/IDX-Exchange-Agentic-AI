/**
 * Card renderer: a pure, deterministic function from a card tool's own result (the JSON
 * the `idx` server returned, as the host hands it to `after_tool_call`) to one card text
 * per listing, each under a ref the model can write as `[[card:<ref>]]`.
 *
 * Rules (WO-037 owned-channel install items, 2026-11-07):
 *   - Source: the result's single text content block, parsed as JSON (with the host's
 *     `structuredContent:` label in front, as OpenClaw 2026.9.5 delivers it). That block is the
 *     one copy of the tool's structured result the model sees (ONE_COPY_TOOLS in
 *     `src/idx_agent/mcp_server/server.py`), so a ref derived from it is a value the model
 *     saw. Nothing else in the result is read. A result that is not an `ok: true`
 *     envelope with an object `data` gives no cards.
 *   - Fields: only the names in RENDERED_LISTING_FIELDS (listings) and
 *     RENDERED_MARKET_FIELDS (market stats) are read, never `remarks`, coordinates,
 *     photos, or any agent or office field. A listing object that carries any deny-listed
 *     or agent-contact key (FORBIDDEN_LISTING_KEYS, mirroring `safety/columns.py`) gives
 *     no card at all: the server's models refuse such keys, so their presence means the
 *     result is not what the server produces.
 *   - Text: plain lines, no markup. Strings lose control and format characters and the
 *     characters markdown or links are built from; a string that still looks like a URL,
 *     an email address or a phone number is left out. Each field and the whole card are
 *     length-bounded; a card over CARD_MAX_LENGTH is not produced.
 *   - Ref: the listing's `listing_id` as it appears in the result, each character outside
 *     the CARD_REF_RE alphabet replaced by "-", cut to 64 characters; `listing_key` when
 *     there is no usable `listing_id`. A market card's ref is `market-<place>`. Two
 *     different card texts under one ref give no card for that ref.
 *   - get_market_stats gets one card (aggregate figures from the sold table, computed by
 *     code; no listing, no deny-listed field). Without it a market-stats turn could never
 *     release anything, since a card turn releases only card tokens (R1b).
 *
 * Node built-ins only; no I/O; same input, same output.
 */

import { CARD_MAX_LENGTH, CARD_MAX_PER_RESULT, cardToolBase } from "./constants.mjs";

/** The listing fields a card may show, by the server's `Listing` names (pinned against
 *  the Python model by tests/test_whatsapp_channel_skeleton.py). */
export const RENDERED_LISTING_FIELDS = Object.freeze([
  "listing_id",
  "listing_key",
  "address",
  "city",
  "postal_code",
  "list_price",
  "bedrooms",
  "bathrooms",
  "living_area",
  "property_subtype",
  "status",
  "year_built",
  "hoa_fee_monthly",
  "days_on_market",
]);

/** The `MarketStats` fields a market card may show (pinned the same way). */
export const RENDERED_MARKET_FIELDS = Object.freeze([
  "geography",
  "property_subtype",
  "window",
  "as_of",
  "sample_count",
  "low_sample",
  "median_close_price",
  "median_price_per_sqft",
  "median_dom",
  "sale_to_list_ratio",
]);

/** Deny-listed and agent-contact names (`DENYLIST` and `AGENT_CONTACT` in
 *  `src/idx_agent/safety/columns.py`; the pytest wrapper pins the two lists equal). A
 *  listing object with any of these keys, compared without case or underscores, gives
 *  no card. */
export const FORBIDDEN_LISTING_KEYS = Object.freeze([
  "AccessCode",
  "LockBoxSerialNumber",
  "LockBoxLocation",
  "LockBoxType",
  "PrivateRemarks",
  "PrivateOfficeRemarks",
  "ShowingInstructions",
  "OwnerName",
  "OwnerPhone",
  "OccupantName",
  "OccupantPhone",
  "LA1_UserFirstName",
  "LA1_UserLastName",
  "LO1_OrganizationName",
  "ListAgentOfficePhone",
  "ListOfficeEmail",
  "ListAgentEmail",
  "ListAgentDirectPhone",
  "ListAgentAOR",
  "ListAgentFullName",
  "CoListAgentFullName",
  "ListAgentKey",
  "ListAgentFirstName",
  "ListAgentLastName",
  "ListOfficeName",
  "BuyerOfficeName",
  "BuyerAgentFirstName",
  "BuyerAgentLastName",
]);

const foldKey = (k) => String(k).replace(/_/gu, "").toLowerCase();
const FORBIDDEN_FOLDED = new Set(FORBIDDEN_LISTING_KEYS.map(foldKey));

/** Longest JSON text the renderer parses (a 50-listing page is far below this). */
const MAX_RESULT_TEXT = 1_000_000;
const REF_MAX = 64;
const REF_OUTSIDE_RE = /[^A-Za-z0-9._-]/gu;
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/u;
/** Control, format (bidi, zero-width), private-use and unassigned characters, and the
 *  line and paragraph separators: replaced by a space. */
const INVISIBLE_RE = /[\p{Cc}\p{Cf}\p{Co}\p{Cn}\u2028\u2029]/gu;
/** Characters markdown, links and tags are built from: removed. */
const MARKUP_RE = /[[\]()<>*_~`|\\{}#!]/gu;
/** A value that still names a link, an address or a handle after cleaning: left out. */
const LINKISH_RE = /:\/\/|www\.|@|\.(com|net|org|io|co)\b/iu;
/** Ten or more digits with only phone separators between them: left out. */
const PHONEISH_RE = /(?:\d[\s().+-]*){10,}/u;

/** @param {unknown} v @returns {v is Record<string, unknown>} */
const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * A cleaned single-line string, or "" when the value is not a string or must be left out.
 * @param {unknown} value @param {number} max
 */
export function cleanText(value, max) {
  if (typeof value !== "string") return "";
  const s = value.normalize("NFC").replace(INVISIBLE_RE, " ").replace(MARKUP_RE, "").replace(/\s+/gu, " ").trim();
  if (s === "" || LINKISH_RE.test(s) || PHONEISH_RE.test(s)) return "";
  return s.length > max ? s.slice(0, max).trimEnd() : s;
}

/** @param {unknown} n @returns {n is number} */
const isWhole = (n) => typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
/** @param {unknown} n @returns {n is number} */
const isNonNegative = (n) => typeof n === "number" && Number.isFinite(n) && n >= 0;

/** Thousands separators without a locale: 1250000 -> "1,250,000". @param {number} n */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/gu, ",");
/** @param {number} n */
const dollars = (n) => `$${grouped(Math.round(n))}`;
/** @param {number} n @param {string} one @param {string} many */
const counted = (n, one, many) => `${grouped(n)} ${n === 1 ? one : many}`;
/** "SingleFamilyResidence" -> "Single Family Residence". @param {string} s */
const words = (s) => s.replace(/(?<=[a-z])(?=[A-Z])/gu, " ");

/**
 * The card ref for one listing, from the identifier the result shows, or null.
 * @param {unknown} listing @returns {string | null}
 */
export function listingRef(listing) {
  if (!isPlainObject(listing)) return null;
  const id = listing.listing_id;
  if (typeof id === "string" && id.trim() !== "") {
    return id.trim().replace(REF_OUTSIDE_RE, "-").slice(0, REF_MAX);
  }
  const key = listing.listing_key;
  return isWhole(key) ? String(key).slice(0, REF_MAX) : null;
}

/** @param {unknown} v */
const isoDate = (v) => (typeof v === "string" && ISO_DATE_RE.test(v) ? v : null);

/**
 * One listing card, or null. Requires a ref and a whole-dollar list price.
 * @param {unknown} listing @param {string | null} asOf the active table's as-of date
 * @returns {{ ref: string, text: string } | null}
 */
export function renderListingCard(listing, asOf) {
  if (!isPlainObject(listing)) return null;
  for (const k of Object.keys(listing)) if (FORBIDDEN_FOLDED.has(foldKey(k))) return null;
  const ref = listingRef(listing);
  if (ref === null || !isWhole(listing.list_price)) return null;
  const stamp = isoDate(asOf);
  const lines = [];
  const address = cleanText(listing.address, 120);
  const city = cleanText(listing.city, 60);
  const zip = typeof listing.postal_code === "string" && /^\d{5}(-\d{4})?$/u.test(listing.postal_code) ? listing.postal_code : "";
  const place = [city, zip].filter(Boolean).join(" ");
  lines.push(address || place || "Address not shown");
  if (address && place) lines.push(place);
  lines.push(`List price ${dollars(listing.list_price)}`);
  const size = [];
  if (isWhole(listing.bedrooms)) size.push(counted(listing.bedrooms, "bed", "beds"));
  if (isNonNegative(listing.bathrooms) && Number.isInteger(listing.bathrooms * 2)) {
    size.push(`${listing.bathrooms} ${listing.bathrooms === 1 ? "bath" : "baths"}`);
  }
  if (isWhole(listing.living_area)) size.push(`${grouped(listing.living_area)} sq ft`);
  if (size.length) lines.push(size.join(" · "));
  const kind = [];
  const subtype = cleanText(listing.property_subtype, 60);
  if (subtype) kind.push(words(subtype));
  if (isWhole(listing.year_built)) kind.push(`built ${listing.year_built}`);
  if (kind.length) lines.push(kind.join(" · "));
  if (isWhole(listing.hoa_fee_monthly)) lines.push(`HOA ${dollars(listing.hoa_fee_monthly)} per month`);
  const status = cleanText(listing.status, 30);
  const facts = [];
  if (status) facts.push(`Status ${status}`);
  if (isWhole(listing.days_on_market)) facts.push(`${counted(listing.days_on_market, "day", "days")} on market`);
  if (facts.length) lines.push(facts.join(" · "));
  lines.push(`Listing ${ref}${stamp ? ` · data as of ${stamp}` : ""}`);
  const text = lines.join("\n");
  return text.length <= CARD_MAX_LENGTH ? { ref, text } : null;
}

/**
 * The market card for a `get_market_stats` result's data, or null.
 * @param {unknown} data @returns {{ ref: string, text: string } | null}
 */
export function renderMarketCard(data) {
  if (!isPlainObject(data) || !isPlainObject(data.geography) || !isPlainObject(data.window)) return null;
  const city = cleanText(data.geography.city, 60);
  const zip = typeof data.geography.postal_code === "string" && /^\d{5}$/u.test(data.geography.postal_code) ? data.geography.postal_code : "";
  const place = city || zip;
  if (!place) return null;
  const slug = place.toLowerCase().replace(REF_OUTSIDE_RE, "-").replace(/-+/gu, "-").replace(/^-|-$/gu, "");
  if (slug === "") return null;
  const ref = `market-${slug}`.slice(0, REF_MAX);
  const months = data.window.months;
  const start = isoDate(data.window.start);
  const end = isoDate(data.window.end);
  if (!isWhole(months) || months < 1 || !start || !end || !isWhole(data.sample_count)) return null;
  const lines = [];
  const subtype = cleanText(data.property_subtype, 60);
  lines.push(`Market: ${place}${subtype ? ` · ${words(subtype)}` : ""}`);
  lines.push(`Closed sales ${start} to ${end} (${counted(months, "month", "months")}): ${grouped(data.sample_count)}`);
  if (isNonNegative(data.median_close_price)) lines.push(`Median sale price ${dollars(data.median_close_price)}`);
  if (isNonNegative(data.median_price_per_sqft)) lines.push(`Median price per sq ft ${dollars(data.median_price_per_sqft)}`);
  if (isNonNegative(data.median_dom)) lines.push(`Median days on market ${grouped(Math.round(data.median_dom))}`);
  if (isNonNegative(data.sale_to_list_ratio) && data.sale_to_list_ratio > 0) {
    lines.push(`Sale to list price ${(Math.round(data.sale_to_list_ratio * 1000) / 10).toFixed(1)}%`);
  }
  if (data.low_sample === true) lines.push("Few sales in this window, so read these figures with care.");
  const asOf = isoDate(data.as_of);
  if (asOf) lines.push(`Sold data as of ${asOf}`);
  const text = lines.join("\n");
  return text.length <= CARD_MAX_LENGTH ? { ref, text } : null;
}

/** The host's label in front of the structured-content block it hands to the model. */
export const HOST_STRUCTURED_LABEL = "structuredContent:\n";

/**
 * The tool's envelope from a host tool result: the single text content block parsed as
 * a JSON object, or null.
 * @param {unknown} result
 */
export function resultEnvelope(result) {
  if (!isPlainObject(result) || !Array.isArray(result.content)) return null;
  const texts = result.content.filter((c) => isPlainObject(c) && c.type === "text");
  if (texts.length !== 1 || typeof texts[0].text !== "string" || texts[0].text.length > MAX_RESULT_TEXT) return null;
  // On OpenClaw 2026.9.5 the bundled-MCP bridge folds the server's JSON copy into one block
  // of its own, `structuredContent:` + newline + the key-sorted, two-space JSON; that block
  // is the one the model sees and the one after_tool_call carries (real-host harness,
  // 2026-11-08). Exactly that label is accepted in front of the JSON; nothing else is.
  const raw = texts[0].text.startsWith(HOST_STRUCTURED_LABEL) ? texts[0].text.slice(HOST_STRUCTURED_LABEL.length) : texts[0].text;
  let env;
  try {
    env = JSON.parse(raw);
  } catch {
    return null;
  }
  return isPlainObject(env) ? env : null;
}

/** The first items of a result list (bounded work on a malformed, oversized list; a real
 *  page holds at most 50 listings). @param {unknown} v @returns {unknown[]} */
const list = (v) => (Array.isArray(v) ? v.slice(0, CARD_MAX_PER_RESULT * 2) : []);

/**
 * Every card a card tool's result yields, in result order. Refs are unique: when one ref
 * would carry two different texts it is left out entirely. Pure and deterministic; never
 * throws (any unexpected shape gives no cards).
 * @param {unknown} toolName the host's tool name (`idx__search_listings`)
 * @param {unknown} result the host's tool result
 * @returns {ReadonlyArray<Readonly<{ ref: string, text: string }>>}
 */
export function renderCards(toolName, result) {
  try {
    const tool = cardToolBase(toolName);
    const env = tool === null ? null : resultEnvelope(result);
    if (env === null || env.ok !== true || !isPlainObject(env.data)) return Object.freeze([]);
    const data = env.data;
    const asOf = isPlainObject(env.provenance) && isPlainObject(env.provenance.as_of) ? isoDate(env.provenance.as_of.active) : null;
    /** @type {Array<{ ref: string, text: string } | null>} */
    let rendered;
    if (tool === "search_listings") {
      rendered = list(data.listings).map((l) => renderListingCard(l, asOf));
    } else if (tool === "find_similar_listings") {
      rendered = list(data.matches).map((m) => (isPlainObject(m) ? renderListingCard(m.listing, asOf) : null));
    } else if (tool === "recommend") {
      rendered = [renderListingCard(data.subject, asOf), ...list(data.recommendations).map((r) => (isPlainObject(r) ? renderListingCard(r.listing, asOf) : null))];
    } else {
      rendered = [renderMarketCard(data)];
    }
    /** @type {Map<string, string | null>} */
    const byRef = new Map();
    for (const card of rendered) {
      if (card === null) continue;
      if (!byRef.has(card.ref)) byRef.set(card.ref, card.text);
      else if (byRef.get(card.ref) !== card.text) byRef.set(card.ref, null);
    }
    const out = [];
    for (const [ref, text] of byRef) {
      if (text !== null && out.length < CARD_MAX_PER_RESULT) out.push(Object.freeze({ ref, text }));
    }
    return Object.freeze(out);
  } catch {
    return Object.freeze([]);
  }
}
