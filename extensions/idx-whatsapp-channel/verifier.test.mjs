import assert from "node:assert/strict";
import { test } from "node:test";

import { nullCardResolver } from "./card-resolver.mjs";
import { MAX_TEXT_LENGTH } from "./constants.mjs";
import { createInMemoryCardResolver } from "./test-support/fake-card-resolver.mjs";
import { digitRuns, isWellFormedVerdict, verifyReply } from "./verifier.mjs";

const SESSION = "agent:idx:whatsapp:direct:+15550000001";
const inbound = (text, turnId = "t1", sessionKey = SESSION) => ({ sessionKey, turnId, text, receivedAt: 1 });
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
  assert.equal(run("Hello", { turnId: "t", text: "hi" }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, text: "hi" }).reason, "no-inbound-record");
  assert.equal(run("Hello", { sessionKey: SESSION, turnId: "t" }).reason, "no-inbound-record");
  assert.equal(run("Hello", "record").reason, "no-inbound-record");
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
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "no-figures", text }, text), true);
  assert.equal(isWellFormedVerdict({ kind: "withhold", reason: "x" }, text), true);
  for (const bad of [
    undefined,
    null,
    "release",
    42,
    [],
    { kind: "release" },
    { kind: "release", text: 7 },
    { kind: "release", text: "altered text" },
    { kind: "release", text, viaCard: true },
    { kind: "release", viaCard: true, rule: "card", text: "invented 12 homes" },
    { kind: "other", text },
    { kind: "withhold" },
    { kind: "withhold", reason: "" },
    Promise.resolve({ kind: "release", text }),
    { kind: "release", text, then: () => {} },
  ]) {
    assert.equal(isWellFormedVerdict(bad, text), false, String(bad));
  }
  // viaCard is accepted only for a card rule on a token-only input.
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "[[card:a]]"), true);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "card", viaCard: true, text: "card body" }, "x [[card:a]]"), false);
  assert.equal(isWellFormedVerdict({ kind: "release", rule: "no-figures", viaCard: true, text: "card body" }, "[[card:a]]"), false);
});
