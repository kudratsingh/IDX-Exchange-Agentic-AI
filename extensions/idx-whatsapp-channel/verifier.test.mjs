import assert from "node:assert/strict";
import { test } from "node:test";

import { nullCardResolver } from "./card-resolver.mjs";
// Namespace import so the file still loads against a constants module without the card
// exports, and the CARD_TOOLS test below fails on behaviour instead of on module load.
import * as constants from "./constants.mjs";
import { MAX_TEXT_LENGTH } from "./constants.mjs";
import { createInMemoryCardResolver } from "./test-support/fake-card-resolver.mjs";
import { VERIFIER_VERSION, digitRuns, isInboundRecord, isWellFormedVerdict, verifyReply } from "./verifier.mjs";

const SESSION = "agent:idx:whatsapp:direct:+15550000001";
/** An ordinary bound turn: its run was confirmed, no card tool call admitted. */
const inbound = (text, turnId = "t1", sessionKey = SESSION) => ({ sessionKey, turnId, text, receivedAt: 1, cardToolCalled: false, runBound: true });
/** A card turn: a card tool call was admitted on this turn's own run. */
const cardTurn = (text, turnId = "t1", sessionKey = SESSION) => ({ ...inbound(text, turnId, sessionKey), cardToolCalled: true });
/** An unbound turn: the host never confirmed the run id the channel issued for it. */
const unboundTurn = (text, turnId = "t1", sessionKey = SESSION) => ({ ...inbound(text, turnId, sessionKey), runBound: false });
const run = (text, inb, resolver = nullCardResolver) => verifyReply({ text, inbound: inb, resolver });

test("greeting with no figures is released byte-identical", () => {
  const text = "Hello! How can I help you find a home?";
  assert.deepEqual(run(text, inbound("hi")), { kind: "release", rule: "no-figures", text });
});

test("clarification repeating the user's figures is released", () => {
  assert.equal(run("Do you mean 3 or 4 bedrooms?", inbound("3 or 4")).kind, "release");
  assert.equal(run("Do you mean 3 or 4 bedrooms?", inbound("3 or 4")).rule, "user-figures");
});

test("figures are compared as whole runs", () => {
  assert.deepEqual(run("Do you mean 34 bedrooms?", inbound("3 or 4")), {
    kind: "withhold",
    reason: "unverified-figures",
  });
  // Thousands separators make the policy stricter, not looser (documented).
  assert.equal(run("Under 1,240 sqft?", inbound("1240")).reason, "unverified-figures");
  assert.equal(run("Under 1240 sqft?", inbound("1240")).kind, "release");
});

test("invented, changed or copied figures are withheld", () => {
  const inb = inbound("anything in pasadena");
  assert.equal(run("There are 12 homes", inb).reason, "unverified-figures");
  assert.equal(run("Priced at $850,000", inb).reason, "unverified-figures");
  assert.equal(run("1,240 sqft (was 960)", inb).reason, "unverified-figures");
  assert.equal(run("Built in 1998", inb).reason, "unverified-figures");
});

test("known withholds: numbered lists, 24/7, office hours, years", () => {
  const inb = inbound("what can you do");
  assert.equal(run("1. Search 2. Compare 3. Draft", inb).reason, "unverified-figures");
  assert.equal(run("We are available 24/7", inb).reason, "unverified-figures");
  assert.equal(run("Office hours are 9-5", inb).reason, "unverified-figures");
  assert.equal(run("Since 2019", inb).reason, "unverified-figures");
  // Number words are not figures under this policy and pass (documented gap).
  assert.equal(run("There are twelve hundred homes", inb).kind, "release");
});

test("Unicode decimal digits count as figures", () => {
  assert.deepEqual(digitRuns("١٢ homes and 3"), ["١٢", "3"]);
  assert.equal(run("There are ١٢ homes", inbound("hi")).reason, "unverified-figures");
  assert.equal(run("There are ١٢ homes", inbound("١٢ please")).kind, "release");
});

test("numerals outside the decimal-digit category count as figures (fractions, circled, superscripts, Roman, digit-with-stop)", () => {
  assert.deepEqual(digitRuns("⑫ homes, ½ bath, ft², Ⅻ, ⒓, １２, 𝟏𝟐"), ["⑫", "½", "²", "Ⅻ", "⒓", "１２", "𝟏𝟐"]);
  const inb = inbound("anything in pasadena");
  for (const text of ["There are ⑫ homes", "There are ½ baths", "Built in ²⁰¹⁹", "Chapter Ⅻ homes", "There are ⒓ homes", "¹²³ Main St", "960 ft²"]) {
    assert.equal(run(text, inb).reason, "unverified-figures", text);
  }
  // and they pass when the user wrote the same run
  assert.equal(run("So a ½ bath is fine?", inbound("½ bath ok")).kind, "release");
  assert.equal(run("960 ft² then", inbound("960 ft²")).kind, "release");
  assert.equal(run("960 ft² then", inbound("960 ft")).reason, "unverified-figures");
});

test("preconditions: not text, empty, too long", () => {
  const inb = inbound("hi");
  assert.equal(run(undefined, inb).reason, "not-text");
  assert.equal(run(42, inb).reason, "not-text");
  assert.equal(run("", inb).reason, "empty");
  assert.equal(run("   \n", inb).reason, "empty");
  assert.equal(run("a".repeat(MAX_TEXT_LENGTH + 1), inb).reason, "too-long");
  assert.equal(run("a".repeat(MAX_TEXT_LENGTH), inb).kind, "release");
});

test("no inbound record: null or missing fields withhold", () => {
  assert.equal(run("Hello", null).reason, "no-inbound-record");
  assert.equal(run("Hello", undefined).reason, "no-inbound-record");
  assert.equal(run("Hello", { turnId: "t", text: "hi", cardToolCalled: false, runBound: true }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, text: "hi", cardToolCalled: false, runBound: true }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, turnId: "t", cardToolCalled: false, runBound: true }).reason, "no-inbound-record");
  assert.equal(run("Hello", "record").reason, "no-inbound-record");
});

// ---- card turns (R1b) --------------------------------------------------------

test("R0: a record without a boolean cardToolCalled is malformed and withheld", () => {
  for (const flag of [undefined, null, "true", 1, 0, "false", {}]) {
    const rec = { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 1, runBound: true };
    if (flag !== undefined) rec.cardToolCalled = flag;
    assert.equal(run("Hello!", rec).reason, "malformed-inbound-record", String(flag));
    assert.equal(isInboundRecord(rec), false, String(flag));
  }
  assert.equal(isInboundRecord(inbound("hi")), true);
  assert.equal(isInboundRecord(cardTurn("hi")), true);
  assert.equal(isInboundRecord(unboundTurn("hi")), true);
  assert.equal(VERIFIER_VERSION, "4");
});

// ---- unbound turns (R0b, owner decision 19 (c)) ---------------------------------

test("R0: a record without a boolean runBound is malformed and withheld, whatever cardToolCalled says", () => {
  for (const flag of [undefined, null, "true", 1, 0, "false", {}, []]) {
    for (const cardToolCalled of [false, true]) {
      const rec = { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 1, cardToolCalled };
      if (flag !== undefined) rec.runBound = flag;
      assert.deepEqual(run("Hello!", rec), { kind: "withhold", reason: "malformed-inbound-record" }, `${String(flag)} card=${cardToolCalled}`);
      assert.equal(isInboundRecord(rec), false, String(flag));
      // the gate's check agrees: no release is well-formed against such a record
      assert.equal(isWellFormedVerdict({ kind: "release", rule: "no-figures", text: "Hello!" }, "Hello!", rec), false, String(flag));
    }
  }
  // the retired taint flag is no substitute: a record carrying only it is malformed
  assert.equal(run("Hello!", { sessionKey: SESSION, turnId: "t1", text: "hi", cardToolCalled: false, toolCallBlocked: false }).reason, "malformed-inbound-record");
});

test("R0b: an unbound turn withholds everything as unbound-turn: greetings, user-figure echoes, and card tokens the resolver would resolve, on a card turn too", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a1", "123 Oak Ave | 3 bd | 960 sqft");
  const unbound = unboundTurn("3 or 4");
  for (const text of ["Hi!", "Hello! How can I help you find a home?", "Do you mean 3 or 4 bedrooms?", "There are 12 homes", "Sorry, I couldn't run that search.", "[[card:a1]]", "  [[card:a1]]\n"]) {
    assert.deepEqual(run(text, unbound, resolver), { kind: "withhold", reason: "unbound-turn" }, text);
    assert.deepEqual(run(text, { ...unbound, cardToolCalled: true }, resolver), { kind: "withhold", reason: "unbound-turn" }, `card ${text}`);
  }
  // the same texts on the same turn once bound behave as before
  assert.equal(run("Hi!", inbound("3 or 4"), resolver).kind, "release");
  assert.equal(run("Do you mean 3 or 4 bedrooms?", inbound("3 or 4"), resolver).rule, "user-figures");
  assert.deepEqual(run("[[card:a1]]", cardTurn("3 or 4"), resolver), { kind: "release", rule: "card", viaCard: true, text: "123 Oak Ave | 3 bd | 960 sqft" });
  // only the boolean true binds; the record check runs first for anything else
  assert.equal(run("Hi!", { ...inbound("hi"), runBound: "true" }).reason, "malformed-inbound-record");
  assert.equal(run("Hi!", { ...inbound("hi"), runBound: 1 }).reason, "malformed-inbound-record");
});

test("R0b before R1: a partial, unknown or prose-wrapped token on an unbound turn is unbound-turn, not a token verdict", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a1", "123 Oak Ave | 3 bd | 960 sqft");
  const unbound = unboundTurn("show me");
  assert.equal(run("[[card:a1", unbound, resolver).reason, "unbound-turn");
  assert.equal(run("see [[card:a1", unbound, resolver).reason, "unbound-turn");
  assert.equal(run("Here: [[card:a1]]", unbound, resolver).reason, "unbound-turn");
  assert.equal(run("[[card:zz]]", unbound, resolver).reason, "unbound-turn");
  assert.equal(run("[[card:a1]] [[card:a1]]", unbound, resolver).reason, "unbound-turn");
  // R0 still precedes R0b: a non-text, empty or too-long input keeps its own reason
  assert.equal(run(undefined, unbound).reason, "not-text");
  assert.equal(run("", unbound).reason, "empty");
  assert.equal(run("a".repeat(MAX_TEXT_LENGTH + 1), unbound).reason, "too-long");
  // and the bound card turn still gets the token verdicts
  assert.equal(run("[[card:a1", cardTurn("show me"), resolver).reason, "malformed-token");
  assert.equal(run("[[card:zz]]", cardTurn("show me"), resolver).reason, "unknown-token");
});

test("RS-2 isWellFormedVerdict: no release on runBound false, no card release without cardToolCalled, no non-card release on a card turn; the unbound withhold is well-formed", () => {
  const unbound = unboundTurn("3 or 4");
  const releases = [
    ["no-figures", { kind: "release", rule: "no-figures", text: "Hello there" }, "Hello there"],
    ["user-figures", { kind: "release", rule: "user-figures", text: "Do you mean 3 or 4 bedrooms?" }, "Do you mean 3 or 4 bedrooms?"],
    ["card", { kind: "release", rule: "card", viaCard: true, text: "123 Oak Ave | 3 bd | 960 sqft" }, "[[card:a1]]"],
  ];
  for (const [label, verdict, input] of releases) {
    const okRecord = label === "card" ? cardTurn("3 or 4") : inbound("3 or 4");
    assert.equal(isWellFormedVerdict(verdict, input, okRecord), true, `${label} on its own bound turn`);
    assert.equal(isWellFormedVerdict(verdict, input, unbound), false, `${label} on an unbound turn`);
    assert.equal(isWellFormedVerdict(verdict, input, { ...unbound, cardToolCalled: true }), false, `${label} on an unbound card turn`);
  }
  // a card release on a bound turn with no admitted card call is malformed
  assert.equal(isWellFormedVerdict(releases[2][1], "[[card:a1]]", inbound("3 or 4")), false);
  // a non-card release on a card turn stays malformed
  assert.equal(isWellFormedVerdict(releases[0][1], "Hello there", cardTurn("3 or 4")), false);
  assert.equal(isWellFormedVerdict(releases[1][1], "Do you mean 3 or 4 bedrooms?", cardTurn("3 or 4")), false);
  const w = run("Hello there", unbound);
  assert.deepEqual(w, { kind: "withhold", reason: "unbound-turn" });
  assert.equal(isWellFormedVerdict(w, "Hello there", unbound), true);
});

test("RS-1 (verifier): a resolvable card token on a bound turn with no admitted card call is withheld card-without-trusted-call, before the resolver is asked", () => {
  let asked = 0;
  const resolver = { resolve: () => { asked += 1; return { text: "123 Oak Ave | 3 bd | 960 sqft" }; } };
  for (const text of ["[[card:a1]]", "  [[card:a1]]\n", "[[card:a1]]\n[[card:b2]]"]) {
    assert.deepEqual(run(text, inbound("show me"), resolver), { kind: "withhold", reason: "card-without-trusted-call" }, text);
  }
  assert.equal(asked, 0);
  // the structural token checks still come first on an ordinary turn
  assert.equal(run("[[card:a1", inbound("show me"), resolver).reason, "malformed-token");
  assert.equal(run("Here: [[card:a1]]", inbound("show me"), resolver).reason, "prose-around-card");
  assert.equal(run("[[card:a1]] [[card:a1]]", inbound("show me"), resolver).reason, "duplicate-token");
  // the same token on the card turn resolves
  assert.equal(run("[[card:a1]]", cardTurn("show me"), resolver).rule, "card");
  assert.equal(asked, 1);
});

test("R1b: on a card turn any prose is withheld card-turn-requires-tokens; an ordinary turn releases the same text", () => {
  const prose = [
    "Here are some great homes for you.",
    "Hello! How can I help you find a home?",
    "There are 12 homes",
    "Do you mean 3 or 4 bedrooms?",
    "Do you want to pay by credit card: yes or no?",
  ];
  for (const text of prose) {
    assert.deepEqual(run(text, cardTurn("3 or 4")), { kind: "withhold", reason: "card-turn-requires-tokens" }, text);
  }
  // the ordinary turn keeps its greeting and its clarification echoing the user's figures
  assert.deepEqual(run("Hello! How can I help you find a home?", inbound("3 or 4")), { kind: "release", rule: "no-figures", text: "Hello! How can I help you find a home?" });
  assert.deepEqual(run("Do you mean 3 or 4 bedrooms?", inbound("3 or 4")), { kind: "release", rule: "user-figures", text: "Do you mean 3 or 4 bedrooms?" });
  assert.equal(run("There are 12 homes", inbound("3 or 4")).reason, "unverified-figures");
});

test("R1 before R1b: on a card turn a partial token is malformed-token, an unknown token unknown-token, and a resolving token releases rule card", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a1", "123 Oak Ave | 3 bd | 960 sqft");
  assert.equal(run("[[card:a1", cardTurn("show me"), resolver).reason, "malformed-token");
  assert.equal(run("see [[card:a1", cardTurn("show me"), resolver).reason, "malformed-token");
  assert.equal(run("Here: [[card:a1]]", cardTurn("show me"), resolver).reason, "prose-around-card");
  assert.equal(run("[[card:zz]]", cardTurn("show me"), resolver).reason, "unknown-token");
  assert.deepEqual(run("[[card:a1]]", cardTurn("show me"), resolver), { kind: "release", rule: "card", viaCard: true, text: "123 Oak Ave | 3 bd | 960 sqft" });
  // the same token on an ordinary bound turn is not supported by any admitted card call
  assert.equal(run("[[card:a1]]", inbound("show me"), resolver).reason, "card-without-trusted-call");
});

test("CARD_TOOLS mirrors the server's one-copy tools; isCardTool fails closed on spelling: the host's namespaced, cased or padded forms mark, a different name never does", () => {
  const { CARD_TOOLS, isCardTool } = constants;
  assert.ok(Array.isArray(CARD_TOOLS), "CARD_TOOLS is exported");
  assert.equal(typeof isCardTool, "function", "isCardTool is exported");
  assert.deepEqual([...CARD_TOOLS].sort(), ["find_similar_listings", "get_market_stats", "recommend", "search_listings"]);
  assert.ok(Object.isFrozen(CARD_TOOLS));
  for (const name of CARD_TOOLS) {
    assert.equal(isCardTool(name), true, name);
    // the host presents MCP tools as idx__<tool> (ADR-0003); every spelling that still names
    // the tool marks, since over-marking is the safe direction
    // the host spells bundled MCP tools `<server>__<tool>`, capped at 64 characters, with a
    // `-N` suffix on a collision (WO-037 install prerequisite 5): a 64-character name whose
    // tool segment survives the cap still marks, with or without the suffix
    const at64 = (suffix) => `${"s".repeat(64 - 2 - name.length - suffix.length)}__${name}${suffix}`;
    for (const spelled of [`idx__${name}`, `mcp__idx__${name}`, `idx.${name}`, `idx/${name}`, `idx:${name}`, ` ${name}`, `${name} `, name.toUpperCase(), `IDX__${name.replace(/^./u, (c) => c.toUpperCase())}`, `idx__${name}-2`, `idx__${name}-10`, `mcp__idx__${name}-3`, `${name}-1`, `IDX__${name.toUpperCase()}-2`, at64(""), at64("-2")]) {
      assert.equal(isCardTool(spelled), true, JSON.stringify(spelled));
    }
    assert.equal(at64("").length, 64);
    assert.equal(at64("-2").length, 64);
  }
  for (const bad of ["get_listing_details", "health", "draft_email", "search_listing", "searchlistings", "search_listings_v2", "idx__search_listings_v2", "search_listings__idx", "recommendations", "idx__", "", "search_listings-", "search_listings-v2", "search_listings-2x", "idx__search_listings_v2-2", "idx__get_listing_details-2", "-2", undefined, null, 42, ["search_listings"], { name: "search_listings" }, { toString: () => "search_listings" }]) {
    assert.equal(isCardTool(bad), false, String(bad));
  }
});

// ---- cards ---------------------------------------------------------------

test("null resolver withholds any token as unknown", () => {
  assert.equal(run("[[card:abc]]", cardTurn("show me")).reason, "unknown-token");
});

test("fake resolver substitutes stored bytes exactly, whitespace preserved", () => {
  const resolver = createInMemoryCardResolver();
  const card = "123 Main St\n3 bd | 2 ba | 1,240 sqft 🏠\nBuilt 1998\n";
  resolver.store(SESSION, "t7", "c1", card);
  const v = run("  [[card:c1]]\n\n", cardTurn("show me the first one", "t7"), resolver);
  assert.equal(v.kind, "release");
  assert.equal(v.rule, "card");
  assert.equal(v.viaCard, true);
  assert.equal(Buffer.compare(Buffer.from(v.text, "utf8"), Buffer.from("  " + card + "\n\n", "utf8")), 0);
});

test("two distinct tokens substitute in order", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a", "A");
  resolver.store(SESSION, "t1", "b", "B");
  assert.equal(run("[[card:a]]\n[[card:b]]", cardTurn("x"), resolver).text, "A\nB");
});

test("tokens bound to another session, turn or removed withhold", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "c1", "card");
  assert.equal(run("[[card:c1]]", cardTurn("x", "t2"), resolver).reason, "unknown-token");
  assert.equal(run("[[card:c1]]", cardTurn("x", "t1", "agent:idx:whatsapp:direct:+15550000002"), resolver).reason, "unknown-token");
  resolver.remove(SESSION, "t1", "c1");
  assert.equal(run("[[card:c1]]", cardTurn("x", "t1"), resolver).reason, "unknown-token");
});

test("malformed, partial, re-spelled tokens withhold", () => {
  const inb = inbound("x");
  for (const text of ["[[card:abc", "card:abc]]", "[[card:ab c]]", "[[CARD:abc]]", "[[card:]]", "see [[card:abc"]) {
    assert.equal(run(text, inb).reason, "malformed-token", text);
  }
});

test("'card:' inside ordinary prose is not a token fragment; bracketed fragments are", () => {
  const inb = inbound("hi");
  for (const text of [
    "Discard: sure, let's move on.",
    "Would you like to discard: the condo or the house?",
    "Do you want to pay by credit card: yes or no?",
    "Send me your scorecard: when ready.",
    "I'll bring my business card: see you then.",
    "Great! Tell me about the card: what is on it?",
  ]) {
    assert.deepEqual(run(text, inb), { kind: "release", rule: "no-figures", text }, text);
  }
  for (const text of ["[card:abc]", "see card:abc]", "[[note]]", "[[card:abc", "card:abc]]"]) {
    assert.equal(run(text, inb).reason, "malformed-token", text);
  }
});

test("resolver text is read exactly once: the value checked is the value substituted", () => {
  const inb = cardTurn("show me");
  let getterReads = 0;
  const getter = { resolve: () => ({ get text() { getterReads += 1; return getterReads <= 2 ? "123 Oak Ave | 3 bd | 960 sqft" : "123 Oak Ave | 3 bd | 2960 sqft"; } }) };
  const a = run("[[card:c1]]", inb, getter);
  assert.deepEqual(a, { kind: "release", rule: "card", viaCard: true, text: "123 Oak Ave | 3 bd | 960 sqft" });
  assert.equal(getterReads, 1);
  let proxyReads = 0;
  const proxy = { resolve: () => new Proxy({}, { get: (_, p) => (p === "text" ? (++proxyReads <= 2 ? "960 sqft" : "FORGED 999 sqft") : undefined) }) };
  assert.equal(run("[[card:c1]]", inb, proxy).text, "960 sqft");
  assert.equal(proxyReads, 1);
  // a getter that answers a string once and then a non-string is still one read, so the first value stands
  let flip = 0;
  const flipping = { resolve: () => ({ get text() { flip += 1; return flip === 1 ? 42 : "later"; } }) };
  assert.equal(run("[[card:c1]]", inb, flipping).reason, "resolver-malformed");
  assert.equal(flip, 1);
});

test("duplicate refs and prose beside a token withhold", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a", "A");
  assert.equal(run("[[card:a]] [[card:a]]", inbound("x"), resolver).reason, "duplicate-token");
  assert.equal(run("Here you go: [[card:a]]", inbound("x"), resolver).reason, "prose-around-card");
  assert.equal(run("[[card:a]] Let me know!", inbound("x"), resolver).reason, "prose-around-card");
});

test("resolver results that are not { text: non-empty string } withhold", () => {
  const inb = cardTurn("x");
  assert.equal(run("[[card:a]]", inb, { resolve: () => ({ text: "" }) }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => "A" }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => ({ body: "A" }) }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => undefined }).reason, "unknown-token");
});

test("a resolver throw propagates (the gate maps it to verifier-threw)", () => {
  assert.throws(() => run("[[card:a]]", cardTurn("x"), { resolve: () => { throw new Error("boom"); } }), /boom/);
});

// ---- well-formedness ------------------------------------------------------

test("isWellFormedVerdict accepts only sane verdicts", () => {
  const text = "Hello";
  const rec = inbound("hi");
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "no-figures", text }, text, rec), true);
  assert.equal(isWellFormedVerdict({ kind: "withhold", reason: "x" }, text, rec), true);
  for (const bad of [
    undefined,
    null,
    "release",
    42,
    [],
    { kind: "release" },
    { kind: "release", text: 7 },
    { kind: "release", text: "altered text" },
    { kind: "release", rule: "no-figures", text: "altered text" },
    { kind: "release", text, viaCard: true },
    { kind: "release", viaCard: true, rule: "card", text: "invented 12 homes" },
    { kind: "other", text },
    { kind: "withhold" },
    { kind: "withhold", reason: "" },
    Promise.resolve({ kind: "release", text }),
    { kind: "release", text, then: () => {} },
    { kind: "release", rule: "no-figures", text, then: () => {} },
  ]) {
    assert.equal(isWellFormedVerdict(bad, text, rec), false, String(bad));
  }
  // viaCard is accepted only for a card rule on a token-only input, on a card turn.
  const card = cardTurn("hi");
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]", card), true);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]", rec), false);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "x [[card:a]]", card), false);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "no-figures", viaCard: true, text: "card body" }, "[[card:a]]", rec), false);
});

test("isWellFormedVerdict rejects incomplete or inconsistent releases and withholds", () => {
  const rec = inbound("3 or 4");
  const digitFree = "Hello there";
  const echo = "Do you mean 3 or 4 bedrooms?";
  const cases = [
    ["release with no rule", { kind: "release", text: digitFree }, digitFree, rec],
    ["rule card without viaCard", { kind: "release", rule: "card", text: "card body" }, "[[card:a]]", rec],
    ["viaCard true with rule no-figures", { kind: "release", rule: "no-figures", viaCard: true, text: digitFree }, digitFree, rec],
    ["viaCard false", { kind: "release", rule: "no-figures", viaCard: false, text: digitFree }, digitFree, rec],
    ["viaCard null", { kind: "release", rule: "no-figures", viaCard: null, text: digitFree }, digitFree, rec],
    ["viaCard 0 on card", { kind: "release", rule: "card", viaCard: 0, text: "card body" }, "[[card:a]]", rec],
    ["viaCard 1 on card", { kind: "release", rule: "card", viaCard: 1, text: "card body" }, "[[card:a]]", rec],
    ["viaCard '' on no-figures", { kind: "release", rule: "no-figures", viaCard: "", text: digitFree }, digitFree, rec],
    ["rule no-figures on a text with a figure", { kind: "release", rule: "no-figures", text: "There are 12 homes" }, "There are 12 homes", rec],
    ["rule no-figures on the user's own figures", { kind: "release", rule: "no-figures", text: echo }, echo, rec],
    ["rule user-figures whose figure is not in the inbound text", { kind: "release", rule: "user-figures", text: "There are 12 homes" }, "There are 12 homes", rec],
    ["rule user-figures with one figure of two missing", { kind: "release", rule: "user-figures", text: "3 or 5 bedrooms?" }, "3 or 5 bedrooms?", rec],
    ["rule user-figures on a text with no figures", { kind: "release", rule: "user-figures", text: digitFree }, digitFree, rec],
    ["rule user-figures with altered text", { kind: "release", rule: "user-figures", text: "Do you mean 3 bedrooms?" }, echo, rec],
    ["unknown rule trusted", { kind: "release", rule: "trusted", text: digitFree }, digitFree, rec],
    ["unknown rule card-ish", { kind: "release", rule: "cards", viaCard: true, text: "card body" }, "[[card:a]]", rec],
    ["release carrying reason", { kind: "release", rule: "no-figures", text: digitFree, reason: "ok" }, digitFree, rec],
    ["release carrying reason null", { kind: "release", rule: "no-figures", text: digitFree, reason: null }, digitFree, rec],
    ["release of rule no-figures on a card turn", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, cardTurn("3 or 4")],
    ["release of rule user-figures on a card turn", { kind: "release", rule: "user-figures", text: echo }, echo, cardTurn("3 or 4")],
    ["release without a record", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, null],
    ["release against a record missing the flag", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, { sessionKey: SESSION, turnId: "t1", text: "hi", runBound: true }],
    ["release against a record missing the run-bound flag", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, { sessionKey: SESSION, turnId: "t1", text: "hi", cardToolCalled: false }],
    ["release of rule no-figures on an unbound turn", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, unboundTurn("3 or 4")],
    ["release of rule card on an unbound card turn", { kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]", { ...unboundTurn("3 or 4"), cardToolCalled: true }],
    ["release of rule card on a turn with no admitted card call", { kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]", rec],
    ["card release on prose input", { kind: "release", rule: "card", viaCard: true, text: "card body" }, "show me", cardTurn("3 or 4")],
    ["card release with empty text", { kind: "release", rule: "card", viaCard: true, text: "   " }, "[[card:a]]", cardTurn("3 or 4")],
    ["withhold carrying text", { kind: "withhold", reason: "x", text: digitFree }, digitFree, rec],
    ["withhold carrying null text", { kind: "withhold", reason: "x", text: null }, digitFree, rec],
    ["withhold with empty reason", { kind: "withhold", reason: "" }, digitFree, rec],
    ["withhold with non-string reason", { kind: "withhold", reason: 7 }, digitFree, rec],
    ["withhold with a thenable", { kind: "withhold", reason: "x", then: () => {} }, digitFree, rec],
    ["release over the length limit", { kind: "release", rule: "no-figures", text: "a".repeat(MAX_TEXT_LENGTH + 1) }, "a".repeat(MAX_TEXT_LENGTH + 1), rec],
  ];
  for (const [label, verdict, input, inb] of cases) {
    assert.equal(isWellFormedVerdict(verdict, input, inb), false, label);
  }
  // Positive controls: the real verifier's verdicts for each rule pass the check.
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a", "123 Oak Ave | 3 bd | 960 sqft");
  const positives = [
    [digitFree, rec, nullCardResolver, "no-figures"],
    [echo, rec, nullCardResolver, "user-figures"],
    ["[[card:a]]", cardTurn("3 or 4"), resolver, "card"],
    ["  [[card:a]]\n", cardTurn("show me"), resolver, "card"],
  ];
  for (const [input, inb, res, rule] of positives) {
    const v = run(input, inb, res);
    assert.equal(v.kind, "release", input);
    assert.equal(v.rule, rule, input);
    assert.equal(isWellFormedVerdict(v, input, inb), true, input);
  }
  // and a real withhold passes as a withhold
  const w = run("There are 12 homes", rec);
  assert.equal(w.kind, "withhold");
  assert.equal(isWellFormedVerdict(w, "There are 12 homes", rec), true);
  // a withhold is well-formed even without a record (the gate still has something to say)
  assert.equal(isWellFormedVerdict({ kind: "withhold", reason: "no-inbound-record" }, digitFree, null), true);
});
