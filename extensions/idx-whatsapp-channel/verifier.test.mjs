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
/** An ordinary turn: no card tool called. */
const inbound = (text, turnId = "t1", sessionKey = SESSION) => ({ sessionKey, turnId, text, receivedAt: 1, cardToolCalled: false });
/** A card turn: a card tool ran during this turn. */
const cardTurn = (text, turnId = "t1", sessionKey = SESSION) => ({ ...inbound(text, turnId, sessionKey), cardToolCalled: true });
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
  assert.equal(run("Hello", { turnId: "t", text: "hi", cardToolCalled: false }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, text: "hi", cardToolCalled: false }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, turnId: "t", cardToolCalled: false }).reason, "no-inbound-record");
  assert.equal(run("Hello", "record").reason, "no-inbound-record");
});

// ---- card turns (R1b) --------------------------------------------------------

test("R0: a record without a boolean cardToolCalled is malformed and withheld", () => {
  for (const flag of [undefined, null, "true", 1, 0, "false", {}]) {
    const rec = { sessionKey: SESSION, turnId: "t1", text: "hi", receivedAt: 1 };
    if (flag !== undefined) rec.cardToolCalled = flag;
    assert.equal(run("Hello!", rec).reason, "malformed-inbound-record", String(flag));
    assert.equal(isInboundRecord(rec), false, String(flag));
  }
  assert.equal(isInboundRecord(inbound("hi")), true);
  assert.equal(isInboundRecord(cardTurn("hi")), true);
  assert.equal(VERIFIER_VERSION, "2");
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
  // the same token on an ordinary turn resolves the same way
  assert.equal(run("[[card:a1]]", inbound("show me"), resolver).rule, "card");
});

test("CARD_TOOLS mirrors the server's one-copy tools; isCardTool is exact and case-sensitive", () => {
  const { CARD_TOOLS, isCardTool } = constants;
  assert.ok(Array.isArray(CARD_TOOLS), "CARD_TOOLS is exported");
  assert.equal(typeof isCardTool, "function", "isCardTool is exported");
  assert.deepEqual([...CARD_TOOLS].sort(), ["find_similar_listings", "get_market_stats", "recommend", "search_listings"]);
  assert.ok(Object.isFrozen(CARD_TOOLS));
  for (const name of CARD_TOOLS) assert.equal(isCardTool(name), true, name);
  for (const bad of ["get_listing_details", "Search_Listings", "search_listings ", "recommendations", "", undefined, null, 42, ["search_listings"], { name: "search_listings" }]) {
    assert.equal(isCardTool(bad), false, String(bad));
  }
});

// ---- cards ---------------------------------------------------------------

test("null resolver withholds any token as unknown", () => {
  assert.equal(run("[[card:abc]]", inbound("show me")).reason, "unknown-token");
});

test("fake resolver substitutes stored bytes exactly, whitespace preserved", () => {
  const resolver = createInMemoryCardResolver();
  const card = "123 Main St\n3 bd | 2 ba | 1,240 sqft 🏠\nBuilt 1998\n";
  resolver.store(SESSION, "t7", "c1", card);
  const v = run("  [[card:c1]]\n\n", inbound("show me the first one", "t7"), resolver);
  assert.equal(v.kind, "release");
  assert.equal(v.rule, "card");
  assert.equal(v.viaCard, true);
  assert.equal(Buffer.compare(Buffer.from(v.text, "utf8"), Buffer.from("  " + card + "\n\n", "utf8")), 0);
});

test("two distinct tokens substitute in order", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "a", "A");
  resolver.store(SESSION, "t1", "b", "B");
  assert.equal(run("[[card:a]]\n[[card:b]]", inbound("x"), resolver).text, "A\nB");
});

test("tokens bound to another session, turn or removed withhold", () => {
  const resolver = createInMemoryCardResolver();
  resolver.store(SESSION, "t1", "c1", "card");
  assert.equal(run("[[card:c1]]", inbound("x", "t2"), resolver).reason, "unknown-token");
  assert.equal(run("[[card:c1]]", inbound("x", "t1", "agent:idx:whatsapp:direct:+15550000002"), resolver).reason, "unknown-token");
  resolver.remove(SESSION, "t1", "c1");
  assert.equal(run("[[card:c1]]", inbound("x", "t1"), resolver).reason, "unknown-token");
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
  const inb = inbound("show me");
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
  const inb = inbound("x");
  assert.equal(run("[[card:a]]", inb, { resolve: () => ({ text: "" }) }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => "A" }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => ({ body: "A" }) }).reason, "resolver-malformed");
  assert.equal(run("[[card:a]]", inb, { resolve: () => undefined }).reason, "unknown-token");
});

test("a resolver throw propagates (the gate maps it to verifier-threw)", () => {
  assert.throws(() => run("[[card:a]]", inbound("x"), { resolve: () => { throw new Error("boom"); } }), /boom/);
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
  // viaCard is accepted only for a card rule on a token-only input.
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]", rec), true);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "x [[card:a]]", rec), false);
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
    ["release against a record missing the flag", { kind: "release", rule: "no-figures", text: digitFree }, digitFree, { sessionKey: SESSION, turnId: "t1", text: "hi" }],
    ["card release on prose input", { kind: "release", rule: "card", viaCard: true, text: "card body" }, "show me", rec],
    ["card release with empty text", { kind: "release", rule: "card", viaCard: true, text: "   " }, "[[card:a]]", rec],
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
    ["[[card:a]]", rec, resolver, "card"],
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
