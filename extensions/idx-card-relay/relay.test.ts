import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import plugin, { createRelay } from "./relay.ts";

const context = { agentId: "idx", sessionKey: "agent:idx:synthetic", runId: "run-one" };
const original = "Draft synthetic-preview\n*Example Listing*\n2 beds · 2 baths · 960 sqft\nNothing has been sent.\n";
const draft = { ok: true, data: { state: "pending", body: original }, message: original };
const capture = (relay, tool = "idx__draft_email", result = draft, id = "call_one", ctx = context) =>
  relay.afterTool({ toolName: tool, toolCallId: id, runId: ctx.runId, result }, ctx);
const deliver = (relay, text, ctx = context) => relay.beforeDelivery({
  payload: { text }, kind: "final", runId: ctx.runId, sessionKey: ctx.sessionKey,
}, ctx);

test("exactly two hooks; no tool, file, config or session API is available to registration", () => {
  const names = [];
  plugin.register(Object.freeze({ on(name, handler) { assert.equal(typeof handler, "function"); names.push(name); } }) as never);
  assert.deepEqual(names, ["after_tool_call", "reply_payload_sending"]);
  const source = readFileSync(new URL("./relay.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /node:|process\.|fetch\(|require\(|api\.(?:runtime|config|sessions|registerTool)/);
});

test("WhatsApp stub sends byte-identical card with surrounding model sentence intact", () => {
  const relay = createRelay(); capture(relay);
  const result = deliver(relay, "Here is the preview.\n\n[[IDX_CARD:call_one]]\nPlease review it.");
  assert.ok(result && "payload" in result);
  const expected = "Here is the preview.\n\n" + original + "\nPlease review it.";
  assert.deepEqual(Buffer.from(result.payload.text), Buffer.from(expected));
  const sent = [];
  const whatsapp = { send: (text) => sent.push(text) };
  whatsapp.send(result.payload.text);
  assert.equal(sent[0], expected);
});

test("model field rewrite is rejected, not delivered or treated as authoritative", () => {
  const relay = createRelay(); capture(relay);
  const rewritten = original.replace("960 sqft", "1,240 sqft");
  const result = deliver(relay, rewritten);
  assert.ok(result?.cancel);
  assert.equal("payload" in result, false);
});

test("all five eligible result families preserve bytes", () => {
  const cases = [
    ["idx__search_listings", { listings: [{}] }],
    ["idx__find_similar_listings", { matches: [{}] }],
    ["idx__recommend", { subject: {} }],
    ["idx__get_market_stats", { sample_count: 29, low_sample: false }],
    ["idx__draft_email", { state: "pending", body: original }],
  ];
  for (const [tool, data] of cases) {
    const relay = createRelay();
    capture(relay, tool, { ok: true, data, message: original });
    assert.equal(deliver(relay, "[[IDX_CARD:call_one]]")?.payload?.text, original);
  }
});

test("MCP text envelope works; input tool result remains unmodified", () => {
  const result = Object.freeze({ content: Object.freeze([{ type: "text", text: JSON.stringify(draft) }]) });
  const before = JSON.stringify(result);
  const relay = createRelay(); capture(relay, "idx__draft_email", result);
  assert.equal(deliver(relay, "[[IDX_CARD:call_one]]")?.payload?.text, original);
  assert.equal(JSON.stringify(result), before);
});

test("docs, clarifications, errors, health and saved searches remain model-owned", () => {
  const cases = [
    ["idx__rag_answer", { ok: true, data: { found: true }, message: original }],
    ["idx__search_listings", { ok: true, data: { question: "Which city?" }, message: original }],
    ["idx__search_listings", { ok: true, data: { listings: [] }, message: original }],
    ["idx__get_market_stats", { ok: true, data: { sample_count: 1, low_sample: true }, message: original }],
    ["idx__health", draft], ["idx_alerts__save_search", draft],
    ["idx__draft_email", { ok: false, error: { message: "Unavailable." } }],
  ];
  for (const [tool, result] of cases) {
    const relay = createRelay(); capture(relay, tool, result);
    assert.equal(deliver(relay, "Model-owned response."), undefined);
  }
});

test("mixed document prose and multiple eligible blocks retain their requested positions", () => {
  const relay = createRelay(); capture(relay);
  capture(relay, "idx__get_market_stats", { ok: true, data: { sample_count: 29 }, message: "Market · $774,999\n" }, "call_two");
  const prose = "DOM means days on market.\nSources: synthetic reference.\n";
  assert.equal(deliver(relay, prose + "[[IDX_CARD:call_one]]\n[[IDX_CARD:call_two]]")?.payload?.text,
    prose + original + "\nMarket · $774,999\n");
});

test("cross-run, cross-session and cross-agent references are not resolved", () => {
  const relay = createRelay(); capture(relay);
  for (const other of [{ ...context, runId: "run-two" }, { ...context, sessionKey: "agent:idx:other" }, { ...context, agentId: "other" }]) {
    assert.ok(deliver(relay, "[[IDX_CARD:call_one]]", other)?.cancel);
  }
  assert.equal(deliver(relay, "[[IDX_CARD:call_one]]")?.payload?.text, original);
});

test("expiry, completed reply and duplicate/reordered markers cannot reuse cards", () => {
  let now = 0;
  const relay = createRelay(() => now); capture(relay);
  now = 60_001;
  assert.ok(deliver(relay, "[[IDX_CARD:call_one]]")?.cancel);
  capture(relay);
  assert.equal(deliver(relay, "[[IDX_CARD:call_one]]")?.payload?.text, original);
  assert.ok(deliver(relay, "[[IDX_CARD:call_one]]")?.cancel);
  capture(relay);
  assert.ok(deliver(relay, "[[IDX_CARD:call_one]][[IDX_CARD:call_one]]")?.cancel);
});


test("actual outgoing context needs only the correlated host run and session", () => {
  const relay = createRelay(); capture(relay);
  const outgoingContext = { channelId: "whatsapp", sessionKey: context.sessionKey, runId: context.runId };
  assert.equal(relay.beforeDelivery({ payload: { text: "[[IDX_CARD:call_one]]" }, kind: "final", runId: context.runId, sessionKey: context.sessionKey }, outgoingContext)?.payload?.text, original);
});
