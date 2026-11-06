// Offline tests with node built-ins only: node --test extensions/idx-card-delivery/
// Synthetic cards from tests/fixtures/card_delivery_vectors.json (shared with Python),
// a temporary store directory, and stub hook events. No host, gateway or network.
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import plugin, { CARD_DIRECTORY, createDelivery, deriveBinding } from "./plugin.mjs";
import { readRecord } from "./store.mjs";
import * as v from "./verify.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const VECTORS = JSON.parse(readFileSync(join(ROOT, "tests/fixtures/card_delivery_vectors.json"), "utf8"));
const UID = process.getuid();
const SESSION_KEY = VECTORS.sessions[0].session_key;
const SESSION = VECTORS.sessions[0].digest;
const RUN = "run-current-turn";
const NOW = VECTORS.cases[0].context.now_ms;

function decide(c, text = c.text) {
  const records = new Map();
  for (const name of c.records) {
    const record = v.parseRecord(VECTORS.records[name]);
    if (record) records.set(record.ref, record);
  }
  const x = c.context;
  return v.verifyAndSubstitute(text, {
    channel: x.channel, session: x.session, run: x.run, nowMs: x.now_ms, records,
    boundCalls: x.bound_calls, knownRuns: x.known_runs, runState: x.run_state,
    strict: x.strict ?? false, cardInSession: x.card_in_session ?? false,
  });
}
/** The text of a vector payload, as plugin.mjs reads it. */
const payloadText = (payload) => (typeof payload?.text === "string" ? payload.text : undefined);

test("constants agree with the Python core", () => {
  const k = VECTORS.constants;
  assert.equal(v.ALPHABET, k.alphabet);
  assert.equal(v.TOKEN_HEAD, k.token_head);
  assert.equal(v.TOKEN_TAIL, k.token_tail);
  assert.equal(v.CARD_NOT_DELIVERED_LINE, k.card_not_delivered_line);
});

test("the hook reads the server's default card directory, and only that one", () => {
  const dir = VECTORS.constants.default_card_dir;
  assert.ok(dir.startsWith("~/"));
  assert.equal(CARD_DIRECTORY, join(homedir(), dir.slice(2)));
  // The server's IDX_CARD_DIR is not followed: the hook reads no environment at all.
  assert.doesNotMatch(readFileSync(join(HERE, "plugin.mjs"), "utf8"), /process\.env/);
});

test("tags, tokens, file names and session digests agree", () => {
  for (const item of VECTORS.tags) {
    const record = v.parseRecord(item.record);
    assert.ok(record, item.name);
    assert.equal(v.cardTag(record), item.expect.tag);
    assert.equal(v.mintToken(record), item.expect.token);
    assert.equal(v.fileName(record.ref), item.expect.file_name);
    assert.doesNotMatch(item.expect.token, /[0-9]/);
  }
  for (const s of VECTORS.sessions) assert.equal(v.sessionDigest(s.session_key), s.digest);
});

for (const c of VECTORS.cases) {
  test(`shared vector: ${c.name}`, () => {
    const d = decide(c);
    assert.deepEqual([d.action, d.reason], [c.expect.action, c.expect.reason]);
    assert.equal(d.text ?? null, c.expect.text ?? null);
    if (d.action === "withhold") assert.doesNotMatch(d.text, /[0-9]/);
  });
}

for (const c of VECTORS.malformed_replies) {
  test(`malformed reply vector: ${c.name}`, () => {
    const d = decide(c, payloadText(c.payload));
    assert.deepEqual([d.action, d.reason, d.text], [c.expect.action, c.expect.reason, c.expect.text]);
  });
}

test("correlationProblem reads expiry with Number.isSafeInteger, as Python does", () => {
  const known = (expires_ms) => [{ session: "s", run: "r", expires_ms }];
  assert.equal(v.correlationProblem("s", "r", 9, known(10)), undefined);
  assert.equal(v.correlationProblem("s", "r", 10, known(10)), "run_expired");
  for (const bad of [true, "11", 10.5, null, 2 ** 53]) {
    assert.equal(v.correlationProblem("s", "r", 9, known(bad)), "run_expired", String(bad));
  }
  assert.equal(v.correlationProblem("s", "r", 9, known(11.0)), undefined);
  assert.equal(v.correlationProblem("s", "", 9, known(11)), "no_run_id");
  assert.equal(v.correlationProblem("s", "r", 9, undefined), "unknown_run");
});

test("records with extra, missing or loose fields are missing", () => {
  const good = VECTORS.records.s1;
  assert.ok(v.parseRecord(good));
  for (const bad of [
    { ...good, extra: 1 }, { ...good, v: true }, { ...good, ref: good.ref + "b" },
    { ...good, session: "x" + good.session }, { ...good, created_ms: "1" },
    { ...good, expires_ms: good.created_ms }, { ...good, message: "" }, [good], null,
  ]) assert.equal(v.parseRecord(bad), undefined);
  const { call, ...missing } = good;
  assert.ok(call);
  assert.equal(v.parseRecord(missing), undefined);
  for (const bad of [1.5, 2, 0, "1", null, Number.NaN]) {
    assert.equal(v.parseRecord({ ...good, v: bad }), undefined, String(bad));
  }
  for (const bad of [true, 1.5, -1, 2 ** 53, Number.POSITIVE_INFINITY]) {
    assert.equal(v.parseRecord({ ...good, created_ms: bad }), undefined, String(bad));
  }
});

// --- static boundaries: what each module may import or call ---

const source = (name) => readFileSync(join(HERE, name), "utf8");
const imports = (text) => [...text.matchAll(/^import[^"']*["']([^"']+)["']/gm)].map((m) => m[1]).sort();

test("verify.mjs imports node:crypto only; store.mjs reads and never writes", () => {
  assert.deepEqual(imports(source("verify.mjs")), ["node:crypto"]);
  assert.doesNotMatch(source("verify.mjs"), /\bprocess\.|\bfetch\(|require\(|import\(/);
  assert.deepEqual(imports(source("store.mjs")), ["./verify.mjs", "node:fs", "node:path"]);
  assert.doesNotMatch(
    source("store.mjs"),
    /\b(write|unlink|rename|mkdir|rm|chmod|chown|symlink|appendFile|copyFile|truncate|link)\w*\s*\(|O_CREAT|O_WRONLY|O_RDWR|O_TRUNC|O_APPEND/,
  );
  assert.deepEqual(imports(source("plugin.mjs")), ["./store.mjs", "./verify.mjs", "node:os", "node:path"]);
  for (const name of ["plugin.mjs", "store.mjs", "verify.mjs"]) {
    assert.doesNotMatch(source(name), /child_process|node:net|node:http|fetch\(|openclaw\//, name);
  }
});

// --- the store adapter ---

function tempStore() {
  const root = mkdtempSync(join(tmpdir(), "idx-card-test-"));
  const directory = join(root, "idx-cards");
  mkdirSync(directory, { mode: 0o700 });
  chmodSync(directory, 0o700);
  return { root, directory };
}

function put(directory, record, mode = 0o600) {
  const path = join(directory, v.fileName(record.ref));
  writeFileSync(path, JSON.stringify(record), { mode });
  chmodSync(path, mode);
  return path;
}

test("readRecord reads an owner-only record and refuses everything doubtful", () => {
  const { root, directory } = tempStore();
  try {
    const record = VECTORS.records.s1;
    const path = put(directory, record);
    assert.deepEqual(readRecord(directory, record.ref, UID), record);
    assert.equal(readRecord(directory, record.ref, UID + 1), undefined);
    assert.equal(readRecord(directory, VECTORS.records.s2.ref, UID), undefined);
    assert.equal(readRecord(join(root, "cards"), record.ref, UID), undefined);
    assert.equal(readRecord("relative/idx-cards", record.ref, UID), undefined);
    chmodSync(path, 0o644);
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    chmodSync(path, 0o600);
    chmodSync(directory, 0o755);
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    chmodSync(directory, 0o700);
    writeFileSync(path, "{" + " ".repeat(70_000) + "}");
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    writeFileSync(path, "not json");
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    writeFileSync(path, JSON.stringify(VECTORS.records.s2)); // a record under the wrong name
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    // 1.0-style numbers read as integers, as in Python's parse_record (review of #176).
    writeFileSync(path, JSON.stringify(record).replace('"v":1,', '"v":1.0,'));
    assert.match(readFileSync(path, "utf8"), /"v":1\.0,/);
    assert.deepEqual(readRecord(directory, record.ref, UID), record);
    writeFileSync(path, JSON.stringify(record).replace('"v":1,', '"v":true,'));
    assert.equal(readRecord(directory, record.ref, UID), undefined);
    rmSync(path);
    const planted = join(root, "planted.json");
    writeFileSync(planted, JSON.stringify(record), { mode: 0o600 });
    symlinkSync(planted, path);
    assert.equal(readRecord(directory, record.ref, UID), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("readRecord refuses a symlinked directory", () => {
  const { root, directory } = tempStore();
  try {
    put(directory, VECTORS.records.s1);
    const linked = join(root, "other", "idx-cards");
    mkdirSync(dirname(linked));
    symlinkSync(directory, linked);
    assert.equal(readRecord(linked, VECTORS.records.s1.ref, UID), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// --- the two hooks, with host-shaped stub events ---

const waCtx = (over = {}) => ({
  agentId: "idx", sessionKey: SESSION_KEY, runId: RUN, toolCallId: "call-s1",
  channelId: "synthetic-peer-alpha", toolName: "idx__search_listings", ...over,
});
const toolEvent = (over = {}) => ({
  toolName: "idx__search_listings", params: { city: "Pasadena" }, runId: RUN,
  toolCallId: "call-s1", ...over,
});
const sendEvent = (text, over = {}) => ({
  payload: { text }, kind: "final", channel: "whatsapp", sessionKey: SESSION_KEY, runId: RUN, ...over,
});
const sendCtx = (over = {}) => ({ channelId: "whatsapp", sessionKey: SESSION_KEY, runId: RUN, ...over });

test("before_tool_call binds a WhatsApp direct chat from host fields only", () => {
  const b = deriveBinding(toolEvent(), waCtx());
  assert.deepEqual(b, { v: 1, channel: "wa", session: SESSION, run: RUN, call: "call-s1" });
  assert.ok(!JSON.stringify(b).includes("synthetic-peer"));
});

for (const [name, ctx, event] of [
  ["dashboard turn into the WhatsApp session (channelId is the session key)", waCtx({ channelId: SESSION_KEY }), toolEvent()],
  ["dashboard main session", waCtx({ sessionKey: "agent:idx:main", channelId: "agent:idx:main" }), toolEvent()],
  ["dmScope main", waCtx({ sessionKey: "agent:idx:main" }), toolEvent()],
  ["account-scoped key", waCtx({ sessionKey: "agent:idx:whatsapp:acct:direct:peer" }), toolEvent()],
  ["another channel's direct chat", waCtx({ sessionKey: "agent:idx:telegram:direct:peer" }), toolEvent()],
  ["another agent", waCtx({ agentId: "main" }), toolEvent()],
  ["no channel id", waCtx({ channelId: undefined }), toolEvent()],
  ["no session key", waCtx({ sessionKey: undefined }), toolEvent()],
  ["no run id", waCtx({ runId: undefined }), toolEvent({ runId: undefined })],
  ["run ids disagree", waCtx(), toolEvent({ runId: "run-other" })],
  ["no tool call id", waCtx({ toolCallId: undefined }), toolEvent({ toolCallId: undefined })],
  ["requester on another channel", waCtx({ requester: { channel: "telegram" } }), toolEvent()],
]) {
  test(`before_tool_call refuses to bind: ${name}`, () => {
    assert.deepEqual(deriveBinding(event, ctx), { v: 1, channel: "none" });
  });
}

test("before_tool_call overwrites a model-supplied binding and ignores other tools", () => {
  const d = createDelivery({ directory: "/nonexistent/idx-cards", uid: UID, now: () => NOW });
  const forged = toolEvent({ params: { city: "Pasadena", idx_delivery: { v: 1, channel: "wa", session: "f".repeat(64), run: RUN, call: "x" } } });
  const result = d.beforeToolCall(forged, waCtx({ channelId: SESSION_KEY }));
  const merged = { ...forged.params, ...result.params }; // the host's shallow merge
  assert.deepEqual(merged.idx_delivery, { v: 1, channel: "none" });
  assert.equal(d.beforeToolCall(toolEvent({ toolName: "idx__rag_answer" }), waCtx()), undefined);
  assert.equal(d.beforeToolCall(toolEvent({ toolName: "read" }), waCtx()), undefined);
});

test("before_tool_call registers the run on any tool call, never changing other tools", () => {
  const d = createDelivery({ directory: "/nonexistent/idx-cards", uid: UID, now: () => NOW });
  assert.equal(d.beforeToolCall(toolEvent({ toolName: "idx__rag_answer" }), waCtx()), undefined);
  assert.deepEqual(d.ledger.knownRuns(), [{ session: SESSION, run: RUN, expires_ms: NOW + 30 * 60_000 }]);
  assert.deepEqual(d.ledger.get(SESSION, RUN).calls, []);
  assert.equal(d.ledger.cardInSession(SESSION), false);
  // Off a WhatsApp direct chat nothing is registered.
  d.beforeToolCall(toolEvent({ toolName: "read", runId: "r-dash" }), waCtx({ runId: "r-dash", channelId: SESSION_KEY }));
  assert.equal(d.ledger.knownRuns().length, 1);
});

test("a full ledger leaves a non-card run unregistered (its reply withheld), never blocks it", () => {
  const d = createDelivery({ directory: "/nonexistent/idx-cards", uid: UID, now: () => NOW });
  for (let i = 0; i < 256; i++) d.beforeToolCall(toolEvent({ toolName: "read", runId: `r${i}` }), waCtx({ runId: `r${i}` }));
  assert.equal(d.beforeToolCall(toolEvent({ toolName: "read", runId: "late" }), waCtx({ runId: "late" })), undefined);
  const out = d.replyPayloadSending(sendEvent("Which city?", { runId: "late" }), sendCtx({ runId: "late" }));
  assert.deepEqual([out.payload.text, out.reason], [v.CARD_NOT_DELIVERED_LINE, "unknown_run"]);
});

test("a full ledger blocks the card tool instead of letting it through unbound", () => {
  const d = createDelivery({ directory: "/nonexistent/idx-cards", uid: UID, now: () => NOW });
  for (let i = 0; i < 256; i++) assert.ok(d.beforeToolCall(toolEvent({ runId: `r${i}` }), waCtx({ runId: `r${i}` })).params);
  assert.equal(d.beforeToolCall(toolEvent({ runId: "late" }), waCtx({ runId: "late" })).block, true);
});

function flow(records, { now = NOW } = {}) {
  const { root, directory } = tempStore();
  for (const r of records) put(directory, r);
  const d = createDelivery({ directory, uid: UID, now: () => now });
  return { d, root };
}

test("happy path: the stored card replaces the token, byte for byte", () => {
  const record = VECTORS.records.s1;
  const { d, root } = flow([record]);
  try {
    d.beforeToolCall(toolEvent({ toolCallId: record.call }), waCtx({ toolCallId: record.call }));
    const token = v.mintToken(record);
    const out = d.replyPayloadSending(sendEvent(token), sendCtx());
    assert.equal(out.payload.text, record.message);
    assert.equal(Buffer.compare(Buffer.from(out.payload.text), Buffer.from(record.message)), 0);
    // A later payload repeating the token is cancelled, not sent twice.
    assert.deepEqual(d.replyPayloadSending(sendEvent(token), sendCtx()), { cancel: true, reason: "already_released" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the P1-4 rewrite (changed sqft) is withheld, and the run stays withheld", () => {
  const record = VECTORS.records.s1;
  const { d, root } = flow([record]);
  try {
    d.beforeToolCall(toolEvent({ toolCallId: record.call }), waCtx({ toolCallId: record.call }));
    const rewritten = record.message.replace("1,860 sqft", "1,240 sqft");
    const out = d.replyPayloadSending(sendEvent(rewritten), sendCtx());
    assert.deepEqual(out.payload, { text: v.CARD_NOT_DELIVERED_LINE });
    assert.doesNotMatch(out.payload.text, /[0-9]/);
    assert.deepEqual(d.replyPayloadSending(sendEvent(v.mintToken(record)), sendCtx()), { cancel: true, reason: "run_failed" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("switch off with the plugin on: the model's own card copy is withheld", () => {
  const { d, root } = flow([]);
  try {
    d.beforeToolCall(toolEvent(), waCtx());
    const out = d.replyPayloadSending(sendEvent(VECTORS.records.s1.message), sendCtx());
    assert.equal(out.payload.text, v.CARD_NOT_DELIVERED_LINE);
    assert.equal(out.reason, "unreferenced");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a cross-session token is withheld even with a valid record", () => {
  const other = VECTORS.records.other_session;
  const { d, root } = flow([other]);
  try {
    d.beforeToolCall(toolEvent({ toolCallId: other.call }), waCtx({ toolCallId: other.call }));
    const out = d.replyPayloadSending(sendEvent(v.mintToken(other)), sendCtx());
    assert.equal(out.reason, "wrong_session");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("off WhatsApp the release hook does nothing, so it never substitutes", () => {
  const record = VECTORS.records.s1;
  const { d, root } = flow([record]);
  try {
    const token = v.mintToken(record);
    assert.equal(d.replyPayloadSending(sendEvent(token, { channel: "webchat" }), sendCtx({ channelId: "webchat" })), undefined);
    assert.equal(d.replyPayloadSending(sendEvent(token), sendCtx({ channelId: "webchat" })), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a payload without a run id is withheld while a card run is open", () => {
  const { d, root } = flow([VECTORS.records.s1]);
  try {
    d.beforeToolCall(toolEvent(), waCtx());
    const out = d.replyPayloadSending(sendEvent("Here you go", { runId: undefined }), sendCtx({ runId: undefined }));
    assert.equal(out.reason, "no_run_id");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a plain reply in a registered run with no card call passes unchanged (strict off)", () => {
  const { d, root } = flow([]);
  try {
    d.beforeToolCall(toolEvent({ toolName: "idx__rag_answer" }), waCtx());
    assert.equal(d.replyPayloadSending(sendEvent("Which city?"), sendCtx()), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// --- unknown correlation withholds, whatever the text (owner, 2026-11-06) ---

const INVENTED = VECTORS.cases.find((c) => c.name === "unmatched_unknown_run_invented_figures").text;
const SESSION_KEY_B = VECTORS.sessions[1].session_key;

test("unmatched reply runs with invented figures are withheld", () => {
  let clock = NOW;
  const { root, directory } = tempStore();
  const d = createDelivery({ directory, uid: UID, now: () => clock, ttlMs: 60_000 });
  try {
    d.beforeToolCall(toolEvent({ toolName: "idx__rag_answer" }), waCtx());
    const withheld = (event, ctx, reason) => {
      const out = d.replyPayloadSending(event, ctx);
      assert.deepEqual(out, { payload: { text: v.CARD_NOT_DELIVERED_LINE }, reason });
      assert.ok(!out.payload.text.includes("1,250,000"));
    };
    withheld(sendEvent(INVENTED, { runId: undefined }), sendCtx({ runId: undefined }), "no_run_id");
    withheld(sendEvent(INVENTED, { runId: "run-never-registered" }), sendCtx({ runId: "run-never-registered" }), "unknown_run");
    withheld(sendEvent("Which city?", { runId: "run-never-registered" }), sendCtx({ runId: "run-never-registered" }), "unknown_run");
    withheld(sendEvent(INVENTED, { runId: "run-other" }), sendCtx(), "no_run_id"); // ids disagree
    // A run registered for session B, released in session A.
    d.beforeToolCall(toolEvent({ toolName: "read", runId: "run-b" }), waCtx({ runId: "run-b", sessionKey: SESSION_KEY_B }));
    withheld(sendEvent(INVENTED, { runId: "run-b" }), sendCtx({ runId: "run-b" }), "run_wrong_session");
    // The registration expires: the same run's next reply is unknown.
    clock = NOW + 60_000;
    withheld(sendEvent(INVENTED), sendCtx(), "unknown_run");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a plain reply in a run that made no tool call is withheld (before_tool_call-only correlation)", () => {
  const { d, root } = flow([]);
  try {
    const out = d.replyPayloadSending(sendEvent("Hello! How can I help?"), sendCtx());
    assert.deepEqual(out, { payload: { text: v.CARD_NOT_DELIVERED_LINE }, reason: "unknown_run" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// --- malformed model replies through the release handler ---

function malformedFlow(c, options = {}) {
  const { root, directory } = tempStore();
  for (const name of c.records) put(directory, VECTORS.records[name]);
  const d = createDelivery({ directory, uid: UID, now: () => NOW, ...options });
  for (const call of c.context.bound_calls) d.beforeToolCall(toolEvent({ toolCallId: call }), waCtx({ toolCallId: call }));
  const event = { payload: c.payload, kind: "final", channel: "whatsapp", sessionKey: SESSION_KEY, runId: c.context.run };
  return { d, root, event, ctx: sendCtx({ runId: c.context.run }) };
}

for (const c of VECTORS.malformed_replies) {
  test(`malformed reply through the handler is withheld: ${c.name}`, () => {
    const { d, root, event, ctx } = malformedFlow(c);
    try {
      assert.deepEqual(d.replyPayloadSending(event, ctx), { payload: { text: c.expect.text }, reason: c.expect.reason });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
  test(`malformed reply when the release handler throws is cancelled: ${c.name}`, () => {
    const verify = () => { throw new Error("synthetic release failure"); };
    const { d, root, event, ctx } = malformedFlow(c, { verify });
    try {
      assert.equal(c.expect_on_throw.action, "drop");
      assert.deepEqual(d.replyPayloadSending(event, ctx), { cancel: true });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

// --- host emulation: OpenClaw 2026.9.5's documented reply_payload_sending semantics ---
// Modelled, not copied, on deliver-prepare-BRk062mg.mjs:26-39, 121-141 (03f60ee0178f)
// and hooks-Jjh3afyP.mjs:441, 780-788 (94e01df2379f): no handler means the payload is
// sent unchanged; a throw or timeout is logged and skipped (fail-open); only
// cancel === true withholds, and only a payload object replaces.

/** What the host sends for one payload; null means withheld. */
async function hostSend(handler, event, ctx, { timeoutMs = 50 } = {}) {
  if (!handler) return event.payload; // no handler registered
  let result;
  let timer;
  try {
    result = await Promise.race([
      Promise.resolve().then(() => handler(event, ctx)),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), timeoutMs); }),
    ]);
  } catch {
    result = undefined; // fail-open: logged and skipped
  } finally {
    clearTimeout(timer);
  }
  if (result?.cancel === true) return null;
  if (result?.payload && typeof result.payload === "object") return result.payload;
  return event.payload;
}

test("host blocker on a token reply: an absent, escaping or timed-out hook sends the raw token, which holds no card value", async () => {
  const record = VECTORS.records.s1;
  const token = v.mintToken(record);
  const event = sendEvent(token);
  const cases = {
    absent: undefined,
    throws: () => { throw new Error("synthetic"); },
    timeout: () => new Promise(() => {}),
  };
  for (const [name, handler] of Object.entries(cases)) {
    const sent = await hostSend(handler, event, sendCtx());
    assert.equal(sent.text, token, name);
    assert.doesNotMatch(sent.text, /[0-9]/, name);
    assert.ok(!sent.text.includes("1,860"), name);
  }
});

test("a throw inside the handler cancels the payload", async () => {
  const d = createDelivery({
    directory: "/nonexistent/idx-cards", uid: UID, now: () => NOW,
    read: () => { throw new Error("synthetic read failure"); },
  });
  d.beforeToolCall(toolEvent(), waCtx());
  const event = sendEvent(v.mintToken(VECTORS.records.s1));
  assert.deepEqual(d.replyPayloadSending(event, sendCtx()), { cancel: true });
  assert.equal(await hostSend(d.replyPayloadSending, event, sendCtx()), null);
});

// BLOCKER tests (WO-036 "Architectural blocker"). Our code cannot run in these cases,
// so they ASSERT TODAY'S OUTCOME: the model's malformed reply is delivered unchanged.
// They document the gap; they are not guarantees.

const BLOCKER_CASES = VECTORS.malformed_replies.filter((c) => c.name.endsWith("_card_run"));

test("host blocker: release hook absent delivers the model's text unchanged", async () => {
  for (const c of BLOCKER_CASES) {
    const { root, event, ctx } = malformedFlow(c);
    try {
      assert.deepEqual(await hostSend(undefined, event, ctx), c.payload, c.name);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
  const invented = sendEvent(INVENTED, { runId: "run-never-registered" });
  assert.deepEqual(await hostSend(undefined, invented, sendCtx()), { text: INVENTED });
});

test("host blocker: release hook timeout delivers the model's text unchanged", async () => {
  for (const c of BLOCKER_CASES) {
    const { d, root, event, ctx } = malformedFlow(c);
    try {
      const slow = (e, x) => new Promise((resolve) => setTimeout(() => resolve(d.replyPayloadSending(e, x)), 200));
      assert.deepEqual(await hostSend(slow, event, ctx, { timeoutMs: 20 }), c.payload, c.name);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
});

test("host blocker: a throw that escapes, or a result shape the host rejects, delivers the text", async () => {
  const event = sendEvent(INVENTED, { runId: "run-never-registered" });
  const escapes = () => { throw new RangeError("synthetic failure outside the handler's catch"); };
  assert.deepEqual(await hostSend(escapes, event, sendCtx()), { text: INVENTED });
  for (const result of [{ cancel: "yes" }, { payload: null }, "cancel", ["cancel"], { withhold: true }]) {
    assert.deepEqual(await hostSend(() => result, event, sendCtx()), { text: INVENTED }, JSON.stringify(result));
  }
});

test("while the handler runs, a malformed reply never reaches the user", async () => {
  for (const c of VECTORS.malformed_replies) {
    const { d, root, event, ctx } = malformedFlow(c);
    try {
      assert.deepEqual(await hostSend(d.replyPayloadSending, event, ctx), { text: v.CARD_NOT_DELIVERED_LINE }, c.name);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
});

test("mitigation that holds: with the plugin absent no card call is ever bound", () => {
  // The host passes tool params through unchanged when no before_tool_call handler
  // exists, so a card call carries no idx_delivery and the server refuses it under
  // IDX_CARD_DELIVERY=1 (tests/test_card_delivery_host_blockers.py checks the server).
  const params = toolEvent().params;
  const hostToolParams = (handler, event, ctx) => ({ ...event.params, ...(handler?.(event, ctx)?.params ?? {}) });
  assert.equal(hostToolParams(undefined, toolEvent(), waCtx()).idx_delivery, undefined);
  assert.deepEqual(hostToolParams(undefined, toolEvent(), waCtx()), params);
});

test("the default export registers exactly the two hooks and never installs", () => {
  const seen = [];
  plugin.register({ on: (name, handler) => seen.push([name, typeof handler]) });
  assert.deepEqual(seen, [["before_tool_call", "function"], ["reply_payload_sending", "function"]]);
  assert.ok(plugin.name.includes("OFFLINE PROTOTYPE"));
});
