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

function decide(c) {
  const records = new Map();
  for (const name of c.records) {
    const record = v.parseRecord(VECTORS.records[name]);
    if (record) records.set(record.ref, record);
  }
  const x = c.context;
  return v.verifyAndSubstitute(c.text, {
    channel: x.channel, session: x.session, run: x.run, nowMs: x.now_ms, records,
    boundCalls: x.bound_calls, runState: x.run_state, strict: x.strict ?? false,
    cardInSession: x.card_in_session ?? false,
  });
}

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

test("a plain reply with no card passes unchanged", () => {
  const { d, root } = flow([]);
  try {
    assert.equal(d.replyPayloadSending(sendEvent("Which city?"), sendCtx()), undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// --- simulated hook failures: what reaches the user is never card text ---

/** The host's merge for reply_payload_sending: a throw or timeout skips the handler. */
async function hostSend(handler, event, ctx, { timeoutMs = 50 } = {}) {
  let result;
  try {
    result = await Promise.race([
      Promise.resolve().then(() => handler?.(event, ctx)),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), timeoutMs)),
    ]);
  } catch {
    result = undefined; // fail-open: logged and skipped
  }
  if (result?.cancel) return null;
  return result?.payload ?? event.payload;
}

test("a skipped, throwing or timed-out release hook sends only the raw token", async () => {
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

test("the default export registers exactly the two hooks and never installs", () => {
  const seen = [];
  plugin.register({ on: (name, handler) => seen.push([name, typeof handler]) });
  assert.deepEqual(seen, [["before_tool_call", "function"], ["reply_payload_sending", "function"]]);
  assert.ok(plugin.name.includes("OFFLINE PROTOTYPE"));
});
