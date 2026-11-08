/**
 * Reply renderer (complete reply token, 2026-11-08): pure, deterministic functions from
 * one card tool's result to one reply section, and from a turn's sections to the one
 * reply text that `[[card:reply]]` stands for.
 *
 * `renderToolSection(toolName, result, error)` -> a frozen section, or null.
 *   - The result is read exactly as the card renderer reads it (`resultEnvelope`: the one
 *     text block, with the host's `structuredContent:` label). Only allowlisted fields are
 *     read; listing cards are `renderListingCard`'s, so remarks, coordinates, photos and
 *     every agent or office field are never read, and a deny-listed key fails the section.
 *   - Every caveat the envelope carries is rendered, in fixed wording of our own: the
 *     feature-filter status and its accuracy limitation, card badges and their note, the
 *     narrowing question, the server's warnings (each recognised warning in our words, a
 *     warning the structured data already shows left to that rendering, the silent
 *     no-session warning dropped, and any other warning as one fixed generic line, so a
 *     caveat is never dropped), the similar and recommend stale-index and fewer-than-asked
 *     lines, shared-feature notes, price checks, the market's low-sample state, missing
 *     medians, window fallback and exclusions. Server text is never echoed: a server
 *     string is only compared with the fixed strings in SERVER_MESSAGES (pinned to the
 *     server by tests/test_whatsapp_channel_skeleton.py) to choose our own line.
 *   - Empty results get a fixed line that says nothing matched, plus their caveats.
 *     Clarifications get a fixed question of our own per reason.
 *   - Unavailable results (an `ok: false` envelope, an MCP `isError` result, or an
 *     `after_tool_call` error string) get one fixed line per tool and error class, never
 *     the raw error text.
 *   - Any shape this module does not know gives null: the turn's reply is then withheld.
 *     A listing that does not render (a forbidden key, no whole list price) fails the
 *     whole section rather than vanishing from it.
 *
 * `composeReply(sections)` -> string | null. Sections in the given order (call order),
 * an identical section shown once, paragraphs blank-line apart, at most MAX_TEXT_LENGTH
 * characters. Every lead and caveat paragraph is always shown; listing items fill the
 * rest in order, and once one does not fit, no later item is shown and each section with
 * items left out ends with "K more ... not shown here" (deterministic, and the reader is
 * told). If the fixed paragraphs alone do not fit, null.
 *
 * Imports constants.mjs and card-render.mjs only; no I/O, no clock, no randomness.
 */

import { MAX_TEXT_LENGTH, cardToolBase } from "./constants.mjs";
import {
  cleanText,
  counted,
  dollars,
  grouped,
  isNonNegative,
  isPlainObject,
  isWhole,
  isoDate,
  renderListingCard,
  renderMarketCard,
  resultEnvelope,
  words,
} from "./card-render.mjs";

/** Fixed server strings this module compares against (never echoes). Pinned equal to the
 *  server's constants by the pytest wrapper. */
export const SERVER_MESSAGES = Object.freeze({
  cleared: "Cleared your search. What would you like to look for?",
  lastPage: "That was the last page. Change a filter or start over to search again.",
  notSetUp: "Similar-listing search is not set up on this server yet.",
  notActive: "That listing is not among the current active listings.",
  noSession: "no session: sender id missing or no key configured",
  noPrevious: "no earlier search was found",
  moreIgnores: "mode more repeats the last search one page on; other filters were ignored",
  keyWins: "Both a listing number and a position were given; the listing number was used.",
  noVector: "This listing is not in the description index, so no similar listing could be ranked for it.",
});

/** Our own lines. Fixed; the reply tests pin each one. */
export const REPLY_LINES = Object.freeze({
  unavailable: Object.freeze({
    search_listings: "The listing search isn't available right now. Please try again in a minute.",
    get_market_stats: "The market figures aren't available right now. Please try again in a minute.",
    find_similar_listings: "Finding similar listings isn't available right now. Please try again in a minute.",
    recommend: "Recommendations aren't available right now. Please try again in a minute.",
  }),
  notSetUp: "Finding listings like a description or a listing isn't set up yet.",
  notActive: "That listing isn't among the current active listings.",
  invalid: "I couldn't use that request as it was. Could you put it another way?",
  refused: "I can't help with that request.",
  cleared: "Your search is cleared. What would you like to look for?",
  lastPage: "That was the last page of this search. Change a filter or start a new search to see more.",
  searchEmpty: "No active listings matched this search.",
  widen: "Widening one filter, such as the price or the city, may find some.",
  featureUnavailable: "I can't search on listing features right now, so no feature search ran. I can search the same area without the features if you like.",
  featureStale: "The listing-feature data is older than the listings, so no feature search ran. I can search the same area without the features if you like.",
  featureLimitation: "Features come from listing descriptions and are sometimes wrong. A home that was not matched may still have the feature: a missing feature is unknown, not absent.",
  narrowing: "That is more than I can show at once. A budget or a home type would narrow it.",
  noPrevious: "There was no earlier search to change, so this is a new search.",
  moreIgnores: "This is the next page of your last search; other changes in the request were not applied.",
  rowCap: "At most 50 listings fit on one page.",
  skippedRows: "Some listings were left out because a required value was missing or invalid.",
  dropped: "Some ranked listings were left out because they no longer show as active, no longer match, or could not be read.",
  keyWins: "Both a listing number and a position were given, so I used the listing number.",
  noVector: "This listing isn't in the description index, so no similar listings could be ranked for it.",
  windowFallback: "The sales data starts later than the window asked for, so these figures use all of it.",
  similarNone: "No active listing close to your description passed these filters. Dropping a filter or describing the home in other words may find some.",
  recommendNone: "No similar active listing was found in the same city and type at a close price.",
  generic: "Some of these results may be incomplete.",
  marketLow: "A longer window or another home type may have enough sales.",
});

/** The noun the "more not shown" line uses, per tool. */
const MORE_NOUN = Object.freeze({
  search_listings: ["listing", "listings"],
  find_similar_listings: ["match", "matches"],
  recommend: ["similar listing", "similar listings"],
});

const FEATURE_NAME_RE = /^[a-z][a-z0-9_]{0,39}$/u;
const FEATURE_WORDS = Object.freeze({
  adu: "ADU",
  near_grocery_mentioned: "grocery store nearby (as stated)",
  near_transit_mentioned: "transit nearby (as stated)",
  single_level: "single level",
  walk_in_closet: "walk-in closet",
});

/** Words for a list of feature names, or "" when any name is not a plain feature name. */
function featureWords(names) {
  if (!Array.isArray(names) || names.length === 0 || names.length > 10) return "";
  const out = [];
  for (const n of names) {
    if (typeof n !== "string" || !FEATURE_NAME_RE.test(n)) return "";
    out.push(FEATURE_WORDS[n] ?? n.replace(/_/gu, " "));
  }
  return out.join(", ");
}

/** The YYYY-MM-DD part of a watermark ("2026-09-18 06:58:44"), or null. */
const stampOf = (v) => (typeof v === "string" ? isoDate(v.slice(0, 10)) : null);

/** @param {string[]} lead @param {string[]} items @param {string[]} after @param {string} tool */
function section(tool, lead, items = [], after = []) {
  const nouns = MORE_NOUN[tool] ?? ["result", "results"];
  return Object.freeze({
    tool,
    lead: Object.freeze([...lead]),
    items: Object.freeze([...items]),
    after: Object.freeze([...after]),
    nouns: Object.freeze([...nouns]),
  });
}

/** One fixed line section. */
const lineSection = (tool, line) => section(tool, [line]);

/** The unavailable line for an `ok: false` envelope, by error class. */
function unavailableLine(tool, env) {
  const error = isPlainObject(env?.error) ? env.error : {};
  const category = typeof error.category === "string" ? error.category : "";
  const message = typeof error.message === "string" ? error.message : "";
  if (category === "not_found" && message === SERVER_MESSAGES.notActive) return REPLY_LINES.notActive;
  if (category === "not_found" && message === SERVER_MESSAGES.notSetUp) return REPLY_LINES.notSetUp;
  if (category === "validation") return REPLY_LINES.invalid;
  if (category === "safety_refusal") return REPLY_LINES.refused;
  return REPLY_LINES.unavailable[tool];
}

// ---- clarifications -----------------------------------------------------------

const CLARIFY = Object.freeze({
  missing_location: "Which city or ZIP code should I look in?",
  unknown_city: "I couldn't match that city. Which city should I use?",
  unknown_subtype: "Which home type do you mean? Please pick one of the options.",
  min_above_max: "The minimum price is above the maximum. What price range should I use?",
  not_half_step: "Bathrooms count in whole or half steps. What minimum should I use?",
  unsupported_filter: "I can't search on that. Which of the usual filters should I use instead, such as city, price, bedrooms or home type?",
  unknown_feature: "I can only filter on the listing features in the options. Which should I use?",
  too_many_features: "I can filter on only a few listing features at once. Which matter most?",
  missing_listing: "Which listing do you mean? Send its listing number or pick one from a search.",
  no_session: "I no longer have that result. Which listing do you mean?",
});
const CLARIFY_TEXT = Object.freeze({
  below_minimum: "Could you describe the home in a few more words, such as its style, its setting or the features you want?",
  above_maximum: "That description is longer than I can use. Could you say it more briefly?",
});

/** @param {Record<string, unknown>} data */
const isClarification = (data) =>
  typeof data.field === "string" && typeof data.reason === "string" && typeof data.question === "string";

function clarificationSection(tool, data) {
  const reason = data.reason;
  let line;
  if (data.field === "text" && reason in CLARIFY_TEXT) line = CLARIFY_TEXT[reason];
  else if (data.field === "postal_code" && reason === "invalid_format") line = "ZIP codes have five digits. Which ZIP code should I use?";
  else if (Object.prototype.hasOwnProperty.call(CLARIFY, reason)) line = CLARIFY[reason];
  else line = REPLY_LINES.invalid;
  const lead = [line];
  if (Array.isArray(data.options) && (reason === "unknown_subtype" || reason === "unknown_feature")) {
    const opts = [];
    for (const o of data.options.slice(0, 30)) {
      if (reason === "unknown_subtype" && typeof o === "string" && /^[A-Za-z]{1,40}$/u.test(o)) opts.push(words(o));
      else if (reason === "unknown_feature") {
        const w = featureWords([o]);
        if (w) opts.push(w);
      }
    }
    if (opts.length) lead.push(`Options: ${opts.join(", ")}`);
  }
  return section(tool, lead);
}

// ---- warnings -----------------------------------------------------------------

/** "covered": the structured data already renders it; "silent": not for the user. */
const WARNINGS = Object.freeze({
  search_listings: [
    [(w) => w === SERVER_MESSAGES.noSession, "silent"],
    [(w) => w === SERVER_MESSAGES.noPrevious, REPLY_LINES.noPrevious],
    [(w) => w === SERVER_MESSAGES.moreIgnores, REPLY_LINES.moreIgnores],
    [(w) => /^limit \d+ is above the \d+-row cap; returning at most \d+ rows$/u.test(w), REPLY_LINES.rowCap],
    [(w) => /^\d+ row\(s\) skipped because a required value was missing or invalid$/u.test(w), REPLY_LINES.skippedRows],
  ],
  find_similar_listings: [
    [(w) => w.startsWith("The description index was built from listings as of "), "covered"],
    [(w) => /^Only \d+ of the \d+ matches asked for came back\./u.test(w), "covered"],
    [(w) => /^\d+ ranked listings? (was|were) left out because /u.test(w), REPLY_LINES.dropped],
  ],
  recommend: [
    [(w) => w === SERVER_MESSAGES.keyWins, REPLY_LINES.keyWins],
    [(w) => w === SERVER_MESSAGES.noVector, REPLY_LINES.noVector],
    [(w) => w.startsWith("The description index was built from listings as of "), "covered"],
    [(w) => /^Only \d+ of the \d+ similar listings asked for came back\.$/u.test(w), "covered"],
    [(w) => /^\d+ ranked listings? (was|were) left out because /u.test(w), REPLY_LINES.dropped],
  ],
  get_market_stats: [
    [(w) => /^\d+ months? was asked, but the sales data starts on \d{4}-\d{2}-\d{2}; /u.test(w), REPLY_LINES.windowFallback],
    [(w) => /^\d+ (sale\(s\)|repeated sale record\(s\)) /u.test(w), "covered"],
  ],
});

/** Our lines for an envelope's warnings, each line once, in first-seen order. */
function warningLines(tool, env) {
  const out = [];
  const warnings = Array.isArray(env.warnings) ? env.warnings.slice(0, 50) : [];
  for (const w of warnings) {
    let line = REPLY_LINES.generic;
    if (typeof w === "string") {
      const hit = WARNINGS[tool].find(([match]) => match(w));
      if (hit) line = hit[1];
    }
    if (line !== "silent" && line !== "covered" && !out.includes(line)) out.push(line);
  }
  return out;
}

// ---- listings -----------------------------------------------------------------

/** The active-table as-of date from the envelope's provenance, or null. */
const activeAsOf = (env) => (isPlainObject(env.provenance) && isPlainObject(env.provenance.as_of) ? isoDate(env.provenance.as_of.active) : null);
const soldAsOf = (env) => (isPlainObject(env.provenance) && isPlainObject(env.provenance.as_of) ? isoDate(env.provenance.as_of.sold) : null);

/** A listing card, or null (which fails the section). */
const card = (listing, asOf) => renderListingCard(listing, asOf)?.text ?? null;

function searchSection(tool, env, data) {
  const asOf = activeAsOf(env);
  const stamp = asOf ? `, data as of ${asOf}` : "";
  const notes = warningLines(tool, env);
  const ff = isPlainObject(data.feature_filter) ? data.feature_filter : null;
  if (ff !== null && (ff.status === "unavailable" || ff.status === "stale")) {
    return section(tool, [ff.status === "unavailable" ? REPLY_LINES.featureUnavailable : REPLY_LINES.featureStale], [], notes);
  }
  if (ff !== null && ff.status !== "applied") return null;
  if (!Array.isArray(data.listings) || data.listings.length > 50) return null;
  const listings = data.listings;
  const badges = isPlainObject(data.card_badges) && isPlainObject(data.card_badges.badges) ? data.card_badges.badges : null;
  const items = [];
  let badgeShown = false;
  for (const l of listings) {
    let text = card(l, asOf);
    if (text === null) return null;
    const names = badges && isPlainObject(l) ? badges[String(l.listing_key)] : undefined;
    if (names !== undefined) {
      const w = featureWords(names);
      if (!w) return null;
      text += `\nFrom the description: ${w}`;
      badgeShown = true;
    }
    items.push(text);
  }
  const page = isWhole(data.applied_filters?.page) && data.applied_filters.page >= 1 ? data.applied_filters.page : 1;
  const total = isWhole(data.total_matches) ? data.total_matches : null;
  const lead = [];
  if (listings.length === 0) {
    lead.push(`${REPLY_LINES.searchEmpty.slice(0, -1)}${page > 1 ? ` on page ${page}` : ""}${stamp}.`);
  } else if (total !== null && total > listings.length) {
    lead.push(`Showing ${grouped(listings.length)} of ${grouped(total)} matching active listings (page ${page})${stamp}.`);
  } else {
    const noun = listings.length === 1 ? "matching active listing" : "matching active listings";
    lead.push(`Showing ${grouped(listings.length)} ${noun}${page > 1 ? ` (page ${page})` : ""}${stamp}.`);
  }
  const after = [];
  let limitation = false;
  if (ff !== null) {
    const w = featureWords(ff.features);
    const when = stampOf(ff.snapshot_watermark);
    if (!w || !when) return null;
    const parts = [`Features matched from listing descriptions as of ${when}: ${w}.`];
    if (isWhole(ff.changed_since_snapshot) && ff.changed_since_snapshot > 0) {
      const n = ff.changed_since_snapshot;
      parts.push(`${counted(n, "matching listing", "matching listings")} changed since then and ${n === 1 ? "was" : "were"} not matched on features.`);
    }
    parts.push(REPLY_LINES.featureLimitation);
    after.push(parts.join(" "));
    limitation = true;
  }
  if (badgeShown) {
    const when = stampOf(data.card_badges.snapshot_watermark);
    if (!when) return null;
    after.push(`Lines marked "From the description:" name features found in listing descriptions as of ${when}.${limitation ? "" : ` ${REPLY_LINES.featureLimitation}`}`);
  }
  after.push(...notes);
  if (listings.length === 0) after.push(REPLY_LINES.widen);
  if (typeof data.narrowing_question === "string" && data.narrowing_question !== "") after.push(REPLY_LINES.narrowing);
  return section(tool, lead, items, after);
}

function similarSection(tool, env, data) {
  if (!Array.isArray(data.matches) || data.matches.length > 50) return null;
  const asOf = activeAsOf(env);
  const n = data.matches.length;
  const items = [];
  for (const [i, m] of data.matches.entries()) {
    const text = isPlainObject(m) ? card(m.listing, asOf) : null;
    if (text === null) return null;
    items.push(`Match ${i + 1} of ${n}\n${text}`);
  }
  const lead = [n > 0 ? `Closest matches to your description${asOf ? `, listings as of ${asOf}` : ""}:` : REPLY_LINES.similarNone];
  const after = [];
  if (n > 0 && isWhole(data.k) && n < data.k) after.push(`Found ${n} of the ${data.k} matches asked for.`);
  const indexAsOf = isoDate(data.index_as_of);
  if (indexAsOf && asOf && indexAsOf !== asOf) after.push(staleLine(indexAsOf, asOf));
  after.push(...warningLines(tool, env));
  return section(tool, lead, items, after);
}

const staleLine = (indexAsOf, asOf) =>
  `The description index was built from listings as of ${indexAsOf}; these listings are as of ${asOf}, so listings added since then are not ranked.`;

/** A price check in our own words from a CompEvidence's structured fields, or null. */
function priceCheck(ev) {
  if (!isPlainObject(ev)) return null;
  if (ev.level === null || ev.level === undefined) return "Price check: not possible, because this listing is missing its size, bedroom count or type.";
  if (ev.level !== "city" && ev.level !== "postal_code") return null;
  const area = cleanText(ev.area, 60);
  const months = isWhole(ev.window_months) && ev.window_months >= 1 ? ev.window_months : null;
  if (!area || months === null || !isWhole(ev.count)) return null;
  const span = `in ${area} over the last ${counted(months, "month", "months")}`;
  const widened = ev.level === "city" ? ` (too few in ${cleanText(ev.widened_from, 20) || "the ZIP code"}, so the city was used)` : "";
  if (ev.sufficient !== true) return `Price check: too few comparable sales ${span} to compare (${counted(ev.count, "sale", "sales")})${widened}.`;
  const d = ev.delta_pct;
  if (typeof d !== "number" || !Number.isInteger(d) || !isWhole(ev.median_price_per_sqft)) return null;
  const where = d === 0 ? "listed at" : `listed ${Math.abs(d)}% ${d > 0 ? "above" : "below"}`;
  let line = `Price check: ${where} the median price per sq ft (${dollars(ev.median_price_per_sqft)}) of ${counted(ev.count, "comparable sale", "comparable sales")} ${span}${widened}.`;
  if (isWhole(ev.range_low_price_per_sqft) && isWhole(ev.range_high_price_per_sqft)) {
    line += ` The middle half of those sales ran from ${dollars(ev.range_low_price_per_sqft)} to ${dollars(ev.range_high_price_per_sqft)} per sq ft.`;
  }
  return line;
}

function recommendSection(tool, env, data) {
  const asOf = activeAsOf(env);
  const subject = card(data.subject, asOf);
  const subjectCheck = priceCheck(data.subject_check);
  if (subject === null || subjectCheck === null || !Array.isArray(data.recommendations) || data.recommendations.length > 50) return null;
  const k = isWhole(data.k) ? data.k : null;
  if (k === null) return null;
  const shared = isPlainObject(data.shared_features) && isPlainObject(data.shared_features.features) ? data.shared_features : null;
  const first = subject.split("\n")[0];
  const n = data.recommendations.length;
  const items = [];
  let sharedShown = false;
  for (const [i, r] of data.recommendations.entries()) {
    if (!isPlainObject(r)) return null;
    const text = card(r.listing, asOf);
    const check = priceCheck(r.comp_evidence);
    if (text === null || check === null) return null;
    let extra = "";
    const names = shared && isPlainObject(r.listing) ? shared.features[String(r.listing.listing_key)] : undefined;
    if (names !== undefined) {
      const w = featureWords(names);
      if (!w) return null;
      extra = `\nBoth descriptions mention: ${w}`;
      sharedShown = true;
    }
    items.push(`Similar ${i + 1} of ${n}\n${text}${extra}\n${check}`);
  }
  const lead = k === 0 ? [subject, subjectCheck] : [`Similar to ${first}:\n${subjectCheck}`];
  const notes = warningLines(tool, env);
  const after = [];
  if (k > 0 && n === 0 && !notes.includes(REPLY_LINES.noVector)) after.push(REPLY_LINES.recommendNone);
  if (n > 0 && n < k) after.push(`Found ${n} of the ${k} similar listings asked for.`);
  const indexAsOf = isoDate(data.index_as_of);
  if (indexAsOf && asOf && indexAsOf !== asOf) after.push(staleLine(indexAsOf, asOf));
  if (sharedShown) {
    const when = stampOf(shared.snapshot_watermark);
    if (!when) return null;
    after.push(`Lines marked "Both descriptions mention:" name features found in the descriptions of both homes as of ${when}; other shared features may go unlisted. ${REPLY_LINES.featureLimitation}`);
  }
  after.push(...notes);
  const sold = soldAsOf(env);
  if (k > 0 && sold && asOf) after.push(`Closed sales to ${sold}; listings as of ${asOf}.`);
  return section(tool, lead, items, after);
}

// ---- market -------------------------------------------------------------------

const BAND = Object.freeze({ very_low: "very low", low: "low", average: "average", high: "high" });
const LEAN = Object.freeze({
  seller: "The market leans toward sellers.",
  buyer: "The market leans toward buyers.",
  balanced: "The market is balanced between buyers and sellers.",
});
const EXCLUSION = Object.freeze({
  after_active_asof: ["sale dated after the data date", "sales dated after the data date"],
  unreadable_close_date: ["sale with an unreadable close date", "sales with an unreadable close date"],
  close_before_contract: ["sale closing before its contract date", "sales closing before their contract date"],
  price_under_floor: ["sale with a close or list price under $25,000", "sales with a close or list price under $25,000"],
  duplicate_listing_key: ["repeated record counted once", "repeated records counted once"],
  area_under_floor: ["sale without a usable living area (price per sq ft only)", "sales without a usable living area (price per sq ft only)"],
  dom_missing: ["sale without days on market (days median only)", "sales without days on market (days median only)"],
});

const leap = (y) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const monthDays = (y, m) => [31, leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];

/** One trend line, or null. */
function trendLine(row, start, end) {
  if (!isPlainObject(row) || typeof row.month !== "string" || !/^\d{4}-(0[1-9]|1[0-2])$/u.test(row.month) || !isWhole(row.sample_count)) return null;
  const y = Number(row.month.slice(0, 4));
  const m = Number(row.month.slice(5, 7));
  const partial = (row.month === start.slice(0, 7) && Number(start.slice(8)) > 1) || (row.month === end.slice(0, 7) && Number(end.slice(8)) < monthDays(y, m));
  const label = `${row.month}${partial ? " (part month)" : ""}`;
  if (row.sample_count === 0) return `${label}: no sales`;
  const sales = counted(row.sample_count, "sale", "sales");
  if (!isNonNegative(row.median_close_price)) return `${label}: ${sales}, too few for a median`;
  return `${label}: ${sales}, median ${dollars(row.median_close_price)}`;
}

function marketSection(tool, env, data) {
  if (data.analytics !== null && data.analytics !== undefined) return null; // extended figures: not rendered here
  const head = renderMarketCard(data);
  if (head === null) return null;
  const lead = [head.text];
  const after = [];
  if (data.low_sample === true) {
    after.push(REPLY_LINES.marketLow);
  } else {
    const more = [];
    if (!isNonNegative(data.median_price_per_sqft)) more.push("Median price per sq ft not available: too few sales with a usable size.");
    if (!isNonNegative(data.median_dom)) more.push("Median days on market not available: too few sales with days on market.");
    else if (typeof data.dom_band === "string" && BAND[data.dom_band]) more.push(`Days on market are ${BAND[data.dom_band]} for this area.`);
    if (typeof data.market_lean === "string" && LEAN[data.market_lean]) more.push(LEAN[data.market_lean]);
    if (more.length) lead.push(more.join("\n"));
    if (Array.isArray(data.trend) && data.trend.length > 0) {
      if (data.trend.length > 25) return null;
      const lines = data.trend.map((r) => trendLine(r, data.window.start, data.window.end));
      if (lines.includes(null)) return null;
      lead.push(["By month (a median needs a few sales):", ...lines].join("\n"));
    }
  }
  if (Array.isArray(data.exclusions_applied)) {
    const parts = [];
    for (const e of data.exclusions_applied.slice(0, 20)) {
      const m = typeof e === "string" ? /^([a-z_]+): (\d+)$/u.exec(e) : null;
      if (m === null || !Object.prototype.hasOwnProperty.call(EXCLUSION, m[1])) return null;
      const count = Number(m[2]);
      if (count > 0) parts.push(`${grouped(count)} ${EXCLUSION[m[1]][count === 1 ? 0 : 1]}`);
    }
    if (parts.length) after.push(`Left out: ${parts.join("; ")}.`);
  }
  after.push(...warningLines(tool, env));
  return section(tool, lead, [], after);
}

// ---- entry points -------------------------------------------------------------

/**
 * The reply section for one card tool call's outcome, or null (unknown shape: withheld).
 * @param {unknown} toolName the host's tool name
 * @param {unknown} result the host's tool result (`after_tool_call` event.result)
 * @param {unknown} [error] the host's `after_tool_call` event.error
 */
export function renderToolSection(toolName, result, error) {
  try {
    const tool = cardToolBase(toolName);
    if (tool === null) return null;
    if (typeof error === "string" && error !== "") return lineSection(tool, REPLY_LINES.unavailable[tool]);
    if (isPlainObject(result) && result.isError === true) return lineSection(tool, REPLY_LINES.unavailable[tool]);
    const env = resultEnvelope(result);
    if (env === null) return null;
    if (env.ok === false) return lineSection(tool, unavailableLine(tool, env));
    if (env.ok !== true) return null;
    const data = env.data;
    if (data === null) {
      if (tool !== "search_listings") return null;
      if (env.message === SERVER_MESSAGES.cleared) return lineSection(tool, REPLY_LINES.cleared);
      if (env.message === SERVER_MESSAGES.lastPage) return lineSection(tool, REPLY_LINES.lastPage);
      return null;
    }
    if (!isPlainObject(data)) return null;
    if (isClarification(data)) return clarificationSection(tool, data);
    if (tool === "search_listings") return searchSection(tool, env, data);
    if (tool === "find_similar_listings") return similarSection(tool, env, data);
    if (tool === "recommend") return recommendSection(tool, env, data);
    return marketSection(tool, env, data);
  } catch {
    return null;
  }
}

const PARA = "\n\n";
const moreLine = (k, [one, many]) => `${grouped(k)} more ${k === 1 ? one : many} not shown here, to keep this message short. A narrower request shows them.`;

/** @param {ReadonlyArray<any>} sections @param {number[]} shown @param {boolean} reserve */
function paragraphs(sections, shown, reserve) {
  const out = [];
  sections.forEach((s, i) => {
    out.push(...s.lead, ...s.items.slice(0, shown[i]));
    if (shown[i] < s.items.length) out.push(moreLine(reserve ? s.items.length : s.items.length - shown[i], s.nouns));
    out.push(...s.after);
  });
  return out;
}

const isSection = (s) =>
  isPlainObject(s) &&
  ["lead", "items", "after", "nouns"].every((k) => Array.isArray(s[k]) && s[k].every((p) => typeof p === "string" && p !== "")) &&
  s.nouns.length === 2;

/**
 * The one reply for a turn's sections, in order, or null.
 * @param {unknown} sections
 * @returns {string | null}
 */
export function composeReply(sections) {
  try {
    if (!Array.isArray(sections) || sections.length === 0 || !sections.every(isSection)) return null;
    const seen = new Set();
    const unique = sections.filter((s) => {
      const key = JSON.stringify([s.lead, s.items, s.after]);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const fits = (paras) => paras.join(PARA).length <= MAX_TEXT_LENGTH;
    const shown = unique.map(() => 0);
    if (!fits(paragraphs(unique, shown, true))) return null;
    let stopped = false;
    for (let i = 0; i < unique.length && !stopped; i += 1) {
      for (let j = 0; j < unique[i].items.length; j += 1) {
        shown[i] = j + 1;
        if (!fits(paragraphs(unique, shown, true))) {
          shown[i] = j;
          stopped = true;
          break;
        }
      }
    }
    const text = paragraphs(unique, shown, false).join(PARA);
    return text.trim() !== "" && text.length <= MAX_TEXT_LENGTH ? text : null;
  } catch {
    return null;
  }
}
