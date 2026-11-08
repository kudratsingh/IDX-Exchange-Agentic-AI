// WO-039 Cloud API wiring in the plugin entry, offline. The host is a fake with the traced
// shapes of OpenClaw 2026.9.5 (the real host runs in host-harness/run.mjs, mode cloud-api).
// Graph API answers come from an injected fake fetch; no request leaves the machine. Every
// credentials file is synthetic, written at test time into a fresh OS temp directory (mode
// 600 in a 700 directory) and removed after; the listener binds 127.0.0.1 only; synthetic
// 555 numbers only.
//
// ORDER MATTERS in this file. The entry keeps ONE Cloud API transport per process behind a
// frozen, non-configurable global key, and node --test runs this file in its own process.
// CE-1 to CE-5 run while that key is still absent (each asserts it); CE-6 sets it, and
// CE-7 to CE-9 and CE-13 run against the transport CE-6 built. Scenarios that need a
// pre-seeded key run in a child process (CE-5).
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { request } from "node:http";
import { connect, createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import entry, { CLOUD_API_MIN_PORT, PLUGIN_CONFIG_SCHEMA, createPluginEntry, hostSafeLogger, processCloudApi, readCloudApiBlock } from "./index.mjs";
import { GRAPH_API_ORIGIN } from "./cloud-api-transport.mjs";
import { LISTENER_START_FAILED_MESSAGE, createListenerBoundTransport, readOwnerCredentialsFile } from "./cloud-api-wiring.mjs";
import { composeReply, renderToolSection } from "./reply-render.mjs";
import { loadPayload } from "./test-support/payloads.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KEY = Symbol.for("idx-whatsapp-channel.cloud-api.v1");
const PEER = "+15555550101";
const PEER_WA = "15555550101";
const STRANGER_WA = "15555550199";
const CFG = { plugins: { allow: ["idx-whatsapp-channel", "openai"] }, channels: { whatsapp: { dmPolicy: "allowlist", allowFrom: [PEER] } } };

// Synthetic values of plausible shape. None is a real credential, id or number.
const CREDS = Object.freeze({
  accessToken: "TEST-ACCESS-TOKEN-not-a-real-token-0000000039",
  appSecret: "testappsecretnotreal000000000039",
  graphApiVersion: "v99.9",
  phoneNumberId: "1000000000039",
  verifyToken: "test-verify-token-not-real-039",
  webhookPath: "/idx-whatsapp/cloud-api/webhook",
});
const SEND_URL = `${GRAPH_API_ORIGIN}/${CREDS.graphApiVersion}/${CREDS.phoneNumberId}/messages`;

/** The payload case the genuine turn's card call returns, and the reply it must produce. */
const PAYLOAD = loadPayload("search-features");
const APPROVED = (() => {
  const env = JSON.parse(PAYLOAD.result.content[0].text.slice("structuredContent:\n".length));
  return env.message;
})();
const RENDERED = composeReply([renderToolSection(PAYLOAD.hostToolName, PAYLOAD.result)].filter(Boolean));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(pred, ms = 3000, step = 10) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await pred();
    if (v) return v;
    await sleep(step);
  }
  return null;
}

/** A private temp dir with one credentials file in it; `cleanup` removes both. */
function credentialsFile(content = CREDS, mode = 0o600) {
  const dir = mkdtempSync(path.join(tmpdir(), "idx-wa-ce-"));
  chmodSync(dir, 0o700);
  const file = path.join(dir, "cloud-api.json");
  writeFileSync(file, typeof content === "string" ? content : JSON.stringify(content));
  chmodSync(file, mode);
  return { dir, file, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

/** A port that was free a moment ago. */
function freePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

/** Whether a TCP connect to the loopback port is refused (nothing listening). */
function refused(port) {
  return new Promise((resolve) => {
    const sock = connect({ host: "127.0.0.1", port });
    sock.once("connect", () => {
      sock.destroy();
      resolve(false);
    });
    sock.once("error", () => resolve(true));
  });
}

/** One HTTP request to the loopback listener: `{ status, body }`, or `{ error }` when refused. */
function call(port, { method = "POST", url = CREDS.webhookPath, headers = {}, body } = {}) {
  return new Promise((resolve) => {
    const req = request({ host: "127.0.0.1", port, method, path: url, headers, agent: false }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("error", (e) => resolve({ error: e.code ?? "error" }));
    if (body !== undefined) req.end(body);
    else req.end();
  });
}

/** A Meta-shaped inbound text webhook body. */
function inboundBytes({ from = PEER_WA, id, text = "show me a 3 bed in Pasadena", phoneNumberId = CREDS.phoneNumberId }) {
  const payload = {
    object: "whatsapp_business_account",
    entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: {
      messaging_product: "whatsapp",
      metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: phoneNumberId },
      contacts: [{ profile: { name: "Test Buyer" }, wa_id: from }],
      messages: [{ from, id, timestamp: String(Math.floor(Date.now() / 1000)), type: "text", text: { body: text } }],
    } }] }],
  };
  return Buffer.from(JSON.stringify(payload), "utf8");
}
const sign = (bytes, secret = CREDS.appSecret) => `sha256=${createHmac("sha256", secret).update(bytes).digest("hex")}`;
const signedPost = (port, bytes) => call(port, { headers: { "content-type": "application/json", "x-hub-signature-256": sign(bytes) }, body: bytes });

/** The fake Graph API: records every request and answers like Meta. One per file, since the
 *  process transport keeps the fetch it was built with. */
const graph = { calls: [] };
async function fakeGraphFetch(url, init) {
  graph.calls.push({ url, method: init?.method, headers: { ...(init?.headers ?? {}) }, body: init?.body, redirect: init?.redirect, hasSignal: init?.signal instanceof AbortSignal });
  const to = JSON.parse(init.body).to;
  return new Response(JSON.stringify({ messaging_product: "whatsapp", contacts: [{ input: to, wa_id: to }], messages: [{ id: `wamid.FAKE-${graph.calls.length}` }] }), { status: 200, headers: { "content-type": "application/json" } });
}

/**
 * A fake host: the traced runtime shapes, the hooks the entry registers, and a dispatcher
 * that runs one card turn (run start, the card call through both hooks with the committed
 * payload, then the reply token through the channel's deliver). `hold` makes the next turn
 * wait before it delivers, until `release()`.
 */
function fakeHost({ pluginConfig, registrationMode = "full" } = {}) {
  const channels = [];
  const hooks = {};
  const lines = [];
  const dispatches = [];
  const delivered = [];
  let gate = null;
  const host = {
    channels,
    hooks,
    lines,
    dispatches,
    delivered,
    hold() {
      let open;
      const p = new Promise((r) => (open = r));
      gate = { p, open };
      return () => open();
    },
  };
  const runtime = {
    channel: {
      routing: { resolveAgentRoute: ({ peer }) => ({ agentId: "main", sessionKey: `agent:main:whatsapp:direct:${peer.id}` }) },
      reply: {
        finalizeInboundContext: (ctx) => ({ ...ctx }),
        dispatchReplyWithBufferedBlockDispatcher: async ({ ctx, replyOptions, dispatcherOptions }) => {
          dispatches.push(ctx.SessionKey);
          replyOptions.onAgentRunStart(replyOptions.runId);
          const toolCallId = `call-${dispatches.length}`;
          const event = { toolName: PAYLOAD.hostToolName, params: {}, runId: replyOptions.runId, toolCallId };
          const hctx = { runId: replyOptions.runId, sessionKey: ctx.SessionKey, toolCallId };
          const decision = hooks.before_tool_call(event, hctx);
          if (decision.block !== false) throw new Error("card call refused");
          hooks.after_tool_call({ ...event, result: PAYLOAD.result, durationMs: 1 }, hctx);
          const g = gate;
          gate = null;
          if (g) await g.p;
          delivered.push(await dispatcherOptions.deliver({ text: "[[card:reply]]" }, { kind: "final" }));
        },
      },
    },
  };
  host.api = {
    id: "idx-whatsapp-channel",
    config: CFG,
    pluginConfig,
    registrationMode,
    logger: { error: (m) => lines.push({ level: "error", m }), warn: (m) => lines.push({ level: "warn", m }), info: (m) => lines.push({ level: "info", m }) },
    registerChannel: (x) => channels.push(x),
    on: (name, handler) => {
      hooks[name] = handler;
    },
    runtime,
  };
  return host;
}

const block = (file, port, extra = {}) => ({ cloudApi: { enabled: true, credentialsFile: file, listen: { host: "127.0.0.1", port }, ...extra } });
const refusalLines = (host) => host.lines.filter((l) => l.m?.event === "cloud-api-refused");

/**
 * A minimal JSON Schema check for the keywords the manifest uses (type object, boolean,
 * string, integer; properties, additionalProperties false, required, enum, minimum, maximum,
 * minLength, maxLength, pattern). Test-only, so the schema's meaning is pinned offline.
 */
function schemaAccepts(schema, v) {
  if (schema.type === "object") {
    if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
    for (const k of schema.required ?? []) if (!(k in v)) return false;
    for (const [k, x] of Object.entries(v)) {
      const sub = schema.properties?.[k];
      if (!sub) {
        if (schema.additionalProperties === false) return false;
        continue;
      }
      if (!schemaAccepts(sub, x)) return false;
    }
    return true;
  }
  if (schema.type === "boolean") return typeof v === "boolean";
  if (schema.type === "integer" && !Number.isInteger(v)) return false;
  if (schema.type === "string" && typeof v !== "string") return false;
  if (schema.enum && !schema.enum.includes(v)) return false;
  if (schema.minimum !== undefined && v < schema.minimum) return false;
  if (schema.maximum !== undefined && v > schema.maximum) return false;
  if (schema.minLength !== undefined && v.length < schema.minLength) return false;
  if (schema.maxLength !== undefined && v.length > schema.maxLength) return false;
  if (schema.pattern !== undefined && !new RegExp(schema.pattern, "u").test(v)) return false;
  return true;
}

// ---- off by default (process key absent) ---------------------------------------------

test("CE-1 config schema: the manifest's configSchema is the entry's, strict at every level; the harness manifest carries the same cloudApi block; extra keys, a string enabled, non-loopback hosts and bad ports are refused", () => {
  const manifest = JSON.parse(readFileSync(path.join(HERE, "openclaw.plugin.json"), "utf8"));
  assert.deepEqual(manifest.configSchema, JSON.parse(JSON.stringify(PLUGIN_CONFIG_SCHEMA)));
  assert.equal(entry.configSchema, PLUGIN_CONFIG_SCHEMA);
  assert.equal(createPluginEntry().configSchema, PLUGIN_CONFIG_SCHEMA);
  assert.ok(Object.isFrozen(PLUGIN_CONFIG_SCHEMA.properties.cloudApi.properties.listen.properties.port));
  const harness = JSON.parse(readFileSync(path.join(HERE, "host-harness/plugin/openclaw.plugin.json"), "utf8"));
  assert.deepEqual(harness.configSchema.properties.cloudApi, manifest.configSchema.properties.cloudApi, "the harness exercises the production block");
  const s = manifest.configSchema;
  const good = { enabled: true, credentialsFile: "/Users/owner/idx-secrets/cloud-api.json", listen: { host: "127.0.0.1", port: 8443 } };
  for (const v of [{}, { cloudApi: { enabled: false } }, { cloudApi: good }, { cloudApi: { ...good, listen: { host: "::1", port: CLOUD_API_MIN_PORT } } }, { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 65535 } } }]) {
    assert.equal(schemaAccepts(s, v), true, JSON.stringify(v));
  }
  const bad = {
    "an extra top-level key": { cloudApi: good, other: 1 },
    "a secret in the block": { cloudApi: { ...good, accessToken: "x" } },
    "an extra listen key": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 8443, tls: true } } },
    "enabled as a string": { cloudApi: { ...good, enabled: "true" } },
    "enabled missing": { cloudApi: { credentialsFile: good.credentialsFile, listen: good.listen } },
    "a relative path": { cloudApi: { ...good, credentialsFile: "secrets/cloud-api.json" } },
    "localhost": { cloudApi: { ...good, listen: { host: "localhost", port: 8443 } } },
    "all interfaces": { cloudApi: { ...good, listen: { host: "0.0.0.0", port: 8443 } } },
    "a privileged port": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 443 } } },
    "port zero": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 0 } } },
    "port too high": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 70000 } } },
    "port as a string": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: "8443" } } },
    "a fractional port": { cloudApi: { ...good, listen: { host: "127.0.0.1", port: 8443.5 } } },
    "listen without a port": { cloudApi: { ...good, listen: { host: "127.0.0.1" } } },
  };
  for (const [name, v] of Object.entries(bad)) assert.equal(schemaAccepts(s, v), false, name);
});

test("CE-2 off by default: no block, enabled false, absent, the string \"true\" or any non-true value leaves the entry exactly as before (unconfigured, nothing read, nothing logged, no port bound, no Graph call)", async () => {
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false, "CE-2 must run before CE-6 sets the process key");
  const port = await freePort();
  let reads = 0;
  const readCredentials = () => {
    reads += 1;
    return CREDS;
  };
  const enabledValues = [false, "true", 1, null, undefined, "yes", {}, [true]];
  const configs = [
    undefined,
    null,
    {},
    { cloudApi: null },
    { cloudApi: true },
    { cloudApi: "on" },
    { cloudApi: [] },
    ...enabledValues.map((enabled) => ({ cloudApi: { enabled, credentialsFile: "/nonexistent/cloud-api.json", listen: { host: "127.0.0.1", port } } })),
    { cloudApi: { credentialsFile: "/nonexistent/cloud-api.json", listen: { host: "127.0.0.1", port } } },
  ];
  for (const pluginConfig of configs) {
    for (const make of [() => entry, () => createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch, readCredentials } })]) {
      const host = fakeHost({ pluginConfig });
      make().register(host.api);
      assert.equal(host.channels.length, 1);
      assert.equal(host.channels[0].plugin.config.isConfigured(), false, JSON.stringify(pluginConfig));
      assert.deepEqual(host.lines, [], "nothing logged");
      assert.deepEqual(readCloudApiBlock(pluginConfig), { state: "off" });
    }
  }
  assert.equal(reads, 0);
  assert.equal(graph.calls.length, 0);
  assert.equal(await refused(port), true);
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false);
  // An injected transport and cloudApiDeps together are a programming error.
  assert.throws(() => createPluginEntry({ transport: {}, cloudApiDeps: {} }), /a transport or cloudApiDeps, not both/);
});

test("CE-3 an enabled block with a bad shape fails closed: unconfigured, one cloud-api-refused bad-config line, the credentials file never read", async () => {
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false);
  const port = await freePort();
  let reads = 0;
  const readCredentials = () => {
    reads += 1;
    return CREDS;
  };
  const file = "/nonexistent/cloud-api.json";
  const cases = {
    "unknown key": block(file, port, { accessToken: CREDS.accessToken }),
    "relative path": block("cloud-api.json", port),
    "empty path": block("", port),
    "non-string path": block(42, port),
    "path with NUL": block("/a\0b", port),
    "no listen": { cloudApi: { enabled: true, credentialsFile: file } },
    "no path": { cloudApi: { enabled: true, listen: { host: "127.0.0.1", port } } },
    "localhost": { cloudApi: { enabled: true, credentialsFile: file, listen: { host: "localhost", port } } },
    "all interfaces": { cloudApi: { enabled: true, credentialsFile: file, listen: { host: "0.0.0.0", port } } },
    "privileged port": block(file, 443),
    "string port": block(file, String(port)),
    "extra listen key": { cloudApi: { enabled: true, credentialsFile: file, listen: { host: "127.0.0.1", port, backlog: 1 } } },
    "listen array": { cloudApi: { enabled: true, credentialsFile: file, listen: ["127.0.0.1", port] } },
  };
  for (const [name, pluginConfig] of Object.entries(cases)) {
    const host = fakeHost({ pluginConfig });
    createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch, readCredentials } }).register(host.api);
    assert.equal(host.channels[0].plugin.config.isConfigured(), false, name);
    assert.deepEqual(host.lines, [{ level: "error", m: { component: "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason: "bad-config" } }], name);
  }
  // A getter that throws while the block is read is a bad config too, never a throw.
  const hostile = { cloudApi: { enabled: true, get credentialsFile() { throw new Error(CREDS.appSecret); }, listen: { host: "127.0.0.1", port } } };
  assert.deepEqual(readCloudApiBlock(hostile), { state: "refused", reason: "bad-config" });
  assert.equal(reads, 0);
  assert.equal(graph.calls.length, 0);
  assert.equal(await refused(port), true);
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false);
});

test("CE-4 a credentials refusal fails closed: unconfigured, one fixed-reason line with no path or value, no port bound, zero Graph calls, and a later register tries again", async () => {
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false);
  const port = await freePort();
  const loose = credentialsFile(CREDS, 0o644);
  const extra = credentialsFile({ ...CREDS, accountId: "default" });
  const notJson = credentialsFile(`{ "accessToken": "${CREDS.accessToken}",`);
  const implausible = credentialsFile({ ...CREDS, phoneNumberId: "12" });
  const missingDir = credentialsFile();
  const missing = path.join(missingDir.dir, "absent.json");
  try {
    const cases = [
      [missing, undefined, "credentials-missing"],
      [loose.file, undefined, "credentials-permissions-too-open"],
      [extra.file, undefined, "credentials-wrong-keys"],
      [notJson.file, undefined, "credentials-not-json"],
      [implausible.file, undefined, "credentials-implausible-value"],
      // an injected reader whose error carries a value: only the fixed fallback reason is logged
      [missingDir.file, () => { throw new Error(`bad ${CREDS.accessToken}`); }, "credentials-unreadable"],
      [missingDir.file, () => { const e = new Error("x"); e.name = "CredentialsFileError"; e.reason = `Leak ${CREDS.appSecret}`; throw e; }, "credentials-unreadable"],
      // a reader that returns an implausible config, and a fetch that is not a function
      [missingDir.file, () => ({ ...CREDS, appSecret: CREDS.accessToken }), "implausible-credentials"],
    ];
    for (const [file, readCredentials, reason] of cases) {
      const host = fakeHost({ pluginConfig: block(file, port) });
      createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch, ...(readCredentials ? { readCredentials } : {}) } }).register(host.api);
      const plugin = host.channels[0].plugin;
      assert.equal(plugin.config.isConfigured(), false, reason);
      assert.deepEqual(host.lines, [{ level: "error", m: { component: "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason } }]);
      const text = JSON.stringify(host.lines);
      for (const leak of [file, path.basename(file), missingDir.dir, CREDS.accessToken, CREDS.appSecret, CREDS.verifyToken, CREDS.phoneNumberId]) {
        assert.ok(!text.includes(leak), `log exposes ${leak}`);
      }
      // even if the host started it anyway, the unconfigured channel cannot send or bind
      await assert.rejects(plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: new AbortController().signal }), /no transport configured/);
    }
    const noFetch = fakeHost({ pluginConfig: block(missingDir.file, port) });
    createPluginEntry({ cloudApiDeps: { fetch: "not a function" } }).register(noFetch.api);
    assert.equal(noFetch.channels[0].plugin.config.isConfigured(), false);
    assert.deepEqual(refusalLines(noFetch).map((l) => l.m.reason), ["no-fetch"]);
    assert.equal(graph.calls.length, 0);
    assert.equal(await refused(port), true);
    assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false, "a refusal stores nothing");
  } finally {
    for (const f of [loose, extra, notJson, implausible, missingDir]) f.cleanup();
  }
});

test("CE-5 a pre-seeded value at the process key is validated: a malformed one, and a well-formed one for another file, host or port, each leave the channel unconfigured with a fixed reason and the file unread; one for the same block but other credential values is refused credentials-changed after one read (child processes)", () => {
  const index = pathToFileURL(path.join(HERE, "index.mjs")).href;
  const run = (seed) =>
    JSON.parse(
      execFileSync(process.execPath, ["--input-type=module", "-e", `
        const KEY = Symbol.for("idx-whatsapp-channel.cloud-api.v1");
        ${seed}
        const { createPluginEntry } = await import(${JSON.stringify(index)});
        let reads = 0;
        const lines = [];
        const channels = [];
        const api = { config: ${JSON.stringify(CFG)}, registrationMode: "full",
          pluginConfig: { cloudApi: { enabled: true, credentialsFile: "/nonexistent/cloud-api.json", listen: { host: "127.0.0.1", port: 18443 } } },
          logger: { error: (m) => lines.push(m), warn() {}, info() {} }, registerChannel: (x) => channels.push(x) };
        createPluginEntry({ cloudApiDeps: { fetch: async () => { throw new Error("no fetch"); }, readCredentials: () => { reads += 1; return ${JSON.stringify(CREDS)}; } } }).register(api);
        process.stdout.write(JSON.stringify({ reads, lines, configured: channels[0].plugin.config.isConfigured() }));
      `], { cwd: HERE, encoding: "utf8", timeout: 20_000 }),
    );
  const fourMembers = "{ start: async () => {}, sendText: async () => ({}), stop: async () => {}, isConfigured: () => true }";
  const define = (value) => `Object.defineProperty(globalThis, KEY, { value: ${value}, writable: false, configurable: false });`;
  const same = 'JSON.stringify(["/nonexistent/cloud-api.json", "127.0.0.1", 18443])';
  for (const [name, seed, reason, reads = 0] of [
    ["not frozen", define(`{ fingerprint: "x", credentialsDigest: "x", sendPath: Object.freeze(${fourMembers}) }`), "process-state-malformed"],
    ["no sendPath", define(`Object.freeze({ fingerprint: "x", credentialsDigest: "x" })`), "process-state-malformed"],
    ["no credentialsDigest", define(`Object.freeze({ fingerprint: ${same}, sendPath: Object.freeze(${fourMembers}) })`), "process-state-malformed"],
    ["sendPath not frozen", define(`Object.freeze({ fingerprint: "x", credentialsDigest: "x", sendPath: ${fourMembers} })`), "process-state-malformed"],
    ["a member missing", define(`Object.freeze({ fingerprint: "x", credentialsDigest: "x", sendPath: Object.freeze({ start() {}, sendText() {}, stop() {} }) })`), "process-state-malformed"],
    ["a string", define(`"cloud"`), "process-state-malformed"],
    ["another file", define(`Object.freeze({ fingerprint: JSON.stringify(["/other/cloud-api.json", "127.0.0.1", 18443]), credentialsDigest: "x", sendPath: Object.freeze(${fourMembers}) })`), "config-mismatch"],
    ["another port", define(`Object.freeze({ fingerprint: JSON.stringify(["/nonexistent/cloud-api.json", "127.0.0.1", 18444]), credentialsDigest: "x", sendPath: Object.freeze(${fourMembers}) })`), "config-mismatch"],
    ["same block, other credential values", define(`Object.freeze({ fingerprint: ${same}, credentialsDigest: "0".repeat(64), sendPath: Object.freeze(${fourMembers}) })`), "credentials-changed", 1],
  ]) {
    const out = run(seed);
    assert.equal(out.configured, false, name);
    assert.equal(out.reads, reads, name);
    assert.deepEqual(out.lines, [{ component: "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason }], name);
  }
});

// ---- enabled (sets the process key) ----------------------------------------------------

/** Shared by CE-6 to CE-9: one synthetic credentials file and one listener port. */
const live = { creds: null, port: 0, reads: 0, firstLines: [] };
const countingReader = (p) => {
  live.reads += 1;
  return readOwnerCredentialsFile(p);
};
process.on("exit", () => live.creds?.cleanup());

/** Registers a production entry with the shared block and starts its account. */
async function startedHost({ entryFactory = createPluginEntry, deps = { fetch: fakeGraphFetch, readCredentials: countingReader }, pluginConfig } = {}) {
  const host = fakeHost({ pluginConfig: pluginConfig ?? block(live.creds.file, live.port) });
  entryFactory({ cloudApiDeps: deps }).register(host.api);
  const plugin = host.channels[0].plugin;
  const ac = new AbortController();
  host.ac = ac;
  host.running = plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: ac.signal });
  host.running.catch(() => {});
  return host;
}

test("CE-6 enabled: the owner file is read once, isConfigured is true, the listener binds 127.0.0.1 only when the account starts, a signed POST runs a real channel turn, and the fake Graph API gets exactly one POST whose text is the approved reply exactly", async () => {
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), false);
  live.creds = credentialsFile();
  live.port = await freePort();
  const host = fakeHost({ pluginConfig: block(live.creds.file, live.port) });
  createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch, readCredentials: countingReader } }).register(host.api);
  const plugin = host.channels[0].plugin;
  live.firstLines = host.lines;
  assert.equal(plugin.config.isConfigured(), true);
  assert.equal(live.reads, 1);
  assert.deepEqual(refusalLines(host), []);
  const desc = Object.getOwnPropertyDescriptor(globalThis, KEY);
  assert.equal(desc.writable, false);
  assert.equal(desc.configurable, false);
  assert.equal(desc.enumerable, false);
  assert.ok(Object.isFrozen(desc.value) && Object.isFrozen(desc.value.sendPath));
  assert.deepEqual(Object.keys(desc.value).sort(), ["credentialsDigest", "fingerprint", "sendPath"]);
  assert.match(desc.value.credentialsDigest, /^[0-9a-f]{64}$/u, "a digest, never a value");
  for (const v of Object.values(CREDS)) assert.ok(!JSON.stringify([desc.value.fingerprint, desc.value.credentialsDigest]).includes(v));
  assert.deepEqual(Object.keys(desc.value.sendPath).sort(), ["isConfigured", "sendText", "start", "stop"]);
  // nothing is bound until the account starts
  assert.equal(await refused(live.port), true, "no port before startAccount");
  const ac = new AbortController();
  const running = plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: ac.signal });
  assert.ok(await waitFor(async () => !(await refused(live.port))), "the listener accepts after startAccount");
  assert.ok(host.lines.some((l) => l.m?.component === "idx-whatsapp-channel.cloud-api-listener" && l.m.event === "listener-started"));
  // Meta's verification GET, and a path the tunnel must never forward
  const challenge = await call(live.port, { method: "GET", url: `${CREDS.webhookPath}?hub.mode=subscribe&hub.verify_token=${CREDS.verifyToken}&hub.challenge=ce6-challenge` });
  assert.deepEqual(challenge, { status: 200, body: "ce6-challenge" });
  assert.equal((await call(live.port, { method: "GET", url: "/" })).status, 404);
  // a signed genuine DM from the allowlisted peer
  const res = await signedPost(live.port, inboundBytes({ id: "wamid.CE6-1" }));
  assert.equal(res.status, 200);
  assert.ok(await waitFor(() => graph.calls.length >= 1), "the reply reached the Graph API");
  await sleep(50);
  assert.equal(host.dispatches.length, 1, "one turn");
  assert.equal(graph.calls.length, 1, "exactly one Graph API request");
  const [sent] = graph.calls;
  assert.equal(sent.url, SEND_URL);
  assert.equal(sent.method, "POST");
  assert.equal(sent.redirect, "error");
  assert.equal(sent.hasSignal, true);
  assert.deepEqual(sent.headers, { authorization: `Bearer ${CREDS.accessToken}`, "content-type": "application/json" });
  const body = JSON.parse(sent.body);
  assert.deepEqual(body, { messaging_product: "whatsapp", recipient_type: "individual", to: PEER_WA, type: "text", text: { preview_url: false, body: APPROVED } });
  assert.equal(body.text.body, APPROVED, "the server's approved reply, exactly");
  assert.equal(body.text.body, RENDERED, "and the channel renderer's reply");
  assert.deepEqual(host.delivered, [{ messageId: "wamid.FAKE-1", visibleReplySent: true }]);
  const outbound = host.lines.filter((l) => l.m?.component === "idx-whatsapp-channel.outbound");
  assert.deepEqual(outbound.map((l) => l.m.outcome), ["sent"]);
  // logs carry no text, peer, id, token, secret, path or port
  const text = JSON.stringify(host.lines);
  for (const leak of [PEER_WA, PEER, "wamid.CE6-1", "show me a 3 bed", CREDS.accessToken, CREDS.appSecret, CREDS.verifyToken, CREDS.phoneNumberId, live.creds.file, CREDS.webhookPath, String(live.port)]) {
    assert.ok(!text.includes(leak), `log exposes ${leak}`);
  }
  // the account stop releases the port (abort only, no stop() call)
  ac.abort();
  await running;
  assert.equal(await refused(live.port), true, "the abort released the port before startAccount settled");
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE6-2" }))).error, "ECONNREFUSED");
  assert.equal(graph.calls.length, 1);
});

test("CE-7 refusals on a running listener: unsigned, tampered, wrongly signed and foreign-number POSTs make no turn and no Graph call (401 for the signature cases); a signed DM from a sender outside the allowlist gets nothing", async () => {
  const before = graph.calls.length;
  const badSigBefore = live.firstLines.filter((l) => l.m?.event === "webhook-rejected" && l.m.reason === "bad-signature").length;
  const readsBefore = live.reads;
  const host = await startedHost();
  assert.equal(live.reads, readsBefore + 1, "a later register checks the file again");
  assert.deepEqual(refusalLines(host), [], "the unchanged file is accepted");
  assert.ok(await waitFor(async () => !(await refused(live.port))));
  const bytes = inboundBytes({ id: "wamid.CE7-1", text: "GENUINE unsigned" });
  assert.equal((await call(live.port, { headers: { "content-type": "application/json" }, body: bytes })).status, 401, "unsigned");
  const tampered = Buffer.from(bytes.toString("utf8").replace("GENUINE unsigned", "GENUINE tampered"), "utf8");
  assert.equal((await call(live.port, { headers: { "x-hub-signature-256": sign(bytes) }, body: tampered })).status, 401, "tampered after signing");
  assert.equal((await call(live.port, { headers: { "x-hub-signature-256": sign(bytes, "anothersecretnotreal000000000039") }, body: bytes })).status, 401, "another secret");
  assert.equal((await call(live.port, { headers: { "x-hub-signature-256": "sha256=" + "0".repeat(64) }, body: bytes })).status, 401, "zeros");
  // signed, but for another phone-number id: acknowledged and dropped
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE7-2", phoneNumberId: "1000000000040" }))).status, 200);
  // signed, from a sender outside the allowlist: acknowledged, then dropped by the channel
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE7-3", from: STRANGER_WA }))).status, 200);
  await sleep(150);
  assert.equal(host.dispatches.length, 0, "no turn");
  assert.equal(graph.calls.length, before, "no Graph API call");
  assert.equal(host.lines.filter((l) => l.m?.component === "idx-whatsapp-channel.ingress" && l.m.event === "inbound-dropped" && l.m.reason === "sender-not-allowed").length, 1, "the stranger was dropped by the allowlist");
  // The process transport logs through the logger of the register that built it (CE-6): the
  // unsigned POST is refused by the route adapter before any read, the other three by the HMAC.
  assert.equal(live.firstLines.filter((l) => l.m?.event === "webhook-rejected" && l.m.reason === "bad-signature").length - badSigBefore, 3, "three HMAC refusals");
  host.ac.abort();
  await host.running;
  assert.ok(await waitFor(() => refused(live.port)));
});

test("CE-8 shutdown and reload: a turn held across an account stop makes zero Graph calls when its reply arrives, and the port is released; across a reload the old turn makes zero calls and the new turn exactly one", async () => {
  // stop
  let before = graph.calls.length;
  const a = await startedHost();
  assert.ok(await waitFor(async () => !(await refused(live.port))));
  const openA = a.hold();
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE8-1" }))).status, 200);
  assert.ok(await waitFor(() => a.dispatches.length === 1), "the turn is running and held");
  a.ac.abort();
  await a.running;
  assert.ok(await waitFor(() => refused(live.port)), "the stop released the port while the turn was held");
  openA();
  assert.ok(await waitFor(() => a.delivered.length === 1));
  assert.deepEqual(a.delivered, [{ visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } }]);
  await sleep(50);
  assert.equal(graph.calls.length, before, "the late reply after the stop made zero Graph API calls");

  // reload: abort, then a new start on the same channel object; the old turn's reply lands after it
  before = graph.calls.length;
  const b = await startedHost();
  assert.ok(await waitFor(async () => !(await refused(live.port))));
  const openOld = b.hold();
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE8-2" }))).status, 200);
  assert.ok(await waitFor(() => b.dispatches.length === 1));
  b.ac.abort();
  await b.running;
  const ac2 = new AbortController();
  const running2 = b.channels[0].plugin.gateway.startAccount({ cfg: CFG, accountId: "default", abortSignal: ac2.signal });
  assert.ok(await waitFor(async () => !(await refused(live.port))), "the listener binds again for the new start");
  openOld();
  assert.ok(await waitFor(() => b.delivered.length === 1));
  assert.deepEqual(b.delivered[0], { visibleReplySent: false, suppression: { reason: "idx-withheld:untrusted-turn" } });
  await sleep(50);
  assert.equal(graph.calls.length, before, "the old turn's late reply made zero Graph API calls");
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE8-3" }))).status, 200);
  assert.ok(await waitFor(() => graph.calls.length === before + 1), "the new turn's reply went out");
  await sleep(50);
  assert.equal(graph.calls.length, before + 1, "exactly one");
  assert.equal(JSON.parse(graph.calls.at(-1).body).text.body, APPROVED);
  ac2.abort();
  await running2;
  assert.ok(await waitFor(() => refused(live.port)));
});

test("CE-9 two module copies (a query-string import) share one transport and one listener: the transport is built once (each register re-checks the file), the second copy's start takes over without a second bind, the older copy's late abort leaves the port open, and the newest abort closes it; another port is refused config-mismatch", async () => {
  const copy = await import("./index.mjs?copy=ce9");
  assert.notEqual(copy.createPluginEntry, createPluginEntry, "a separate module instance");
  let copyReads = 0;
  const copyFetchCalls = [];
  const copyDeps = {
    fetch: async (...args) => {
      copyFetchCalls.push(args);
      return fakeGraphFetch(...args);
    },
    readCredentials: () => {
      copyReads += 1;
      return CREDS;
    },
  };
  const before = graph.calls.length;
  const readsBefore = live.reads;
  const a = await startedHost();
  assert.ok(await waitFor(async () => !(await refused(live.port))));
  const b = await startedHost({ entryFactory: copy.createPluginEntry, deps: copyDeps });
  // B's start took over the sink; A's start still runs on its own signal
  const shared = processCloudApi({ credentialsFile: live.creds.file, host: "127.0.0.1", port: live.port }, {}, undefined);
  const sharedCopy = copy.processCloudApi({ credentialsFile: live.creds.file, host: "127.0.0.1", port: live.port }, {}, undefined);
  assert.equal(shared.ok, true);
  assert.equal(shared.sendPath, sharedCopy.sendPath, "one transport for both copies");
  assert.equal(copyReads, 1, "the copy checked the file once, for its own register");
  assert.equal(live.reads, readsBefore + 1, "one check per register");
  await sleep(50);
  assert.equal(b.lines.filter((l) => l.m?.event === "listener-error").length, 0, "no second bind");
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE9-1" }))).status, 200);
  assert.ok(await waitFor(() => graph.calls.length === before + 1));
  await sleep(50);
  assert.equal(a.dispatches.length, 0, "the superseded copy runs no turn");
  assert.equal(b.dispatches.length, 1, "the newest copy runs the turn");
  assert.equal(graph.calls.length, before + 1, "exactly one Graph API request");
  assert.equal(copyFetchCalls.length, 0, "through the fetch the process transport was built with");
  // the older copy's abort comes late: the listener belongs to the newest start
  a.ac.abort();
  await a.running;
  await sleep(50);
  assert.equal(await refused(live.port), false, "the late abort of the older start leaves the port open");
  assert.equal((await signedPost(live.port, inboundBytes({ id: "wamid.CE9-2" }))).status, 200);
  assert.ok(await waitFor(() => graph.calls.length === before + 2), "the newest start still serves");
  b.ac.abort();
  await b.running;
  assert.ok(await waitFor(() => refused(live.port)), "the newest abort releases the port");
  // a register naming another port (or file) cannot reach the process transport
  const other = fakeHost({ pluginConfig: block(live.creds.file, live.port + 1 > 65535 ? live.port - 1 : live.port + 1) });
  copy.createPluginEntry({ cloudApiDeps: copyDeps }).register(other.api);
  assert.equal(other.channels[0].plugin.config.isConfigured(), false);
  assert.deepEqual(refusalLines(other).map((l) => l.m.reason), ["config-mismatch"]);
  assert.equal(copyReads, 1, "a mismatched block is refused before the file is read");
  // a register with the block off in this process stays unconfigured too
  const off = fakeHost({ pluginConfig: {} });
  entry.register(off.api);
  assert.equal(off.channels[0].plugin.config.isConfigured(), false);
});

// ---- the listener-bound transport alone --------------------------------------------------

/** A counting fake listener and Cloud API transport for createListenerBoundTransport. */
function fakeParts({ failStart = false } = {}) {
  const ev = [];
  let listening = false;
  const listener = {
    async start() {
      ev.push("listen");
      await sleep(5);
      if (failStart) throw new Error("listen failed");
      listening = true;
      return { port: 1 };
    },
    async stop() {
      ev.push("close");
      listening = false;
    },
  };
  const cloud = {
    start: (opts) =>
      new Promise((resolve) => {
        ev.push("sink");
        if (opts.signal?.aborted) return resolve();
        opts.signal?.addEventListener("abort", () => resolve(), { once: true });
      }),
    sendText: async () => ({ messageId: "x" }),
    stop: async () => {
      ev.push("cloud-stop");
    },
    isConfigured: () => true,
  };
  return { ev, listener, cloud, isListening: () => listening };
}

test("CE-10 listener-bound transport: the sink is taken in the same tick as start, the newest start owns the listener, an already-aborted start binds nothing, a bind failure rejects with a fixed message, and the member set is the four Transport members", async () => {
  const p = fakeParts();
  const t = createListenerBoundTransport({ cloud: p.cloud, listener: p.listener });
  assert.deepEqual(Object.keys(t).sort(), ["isConfigured", "sendText", "start", "stop"]);
  assert.ok(Object.isFrozen(t));
  const a = new AbortController();
  const ra = t.start({ accountId: "default", signal: a.signal, onInbound: async () => {} });
  assert.deepEqual(p.ev, ["sink"], "the sink before any await");
  await sleep(20);
  assert.equal(p.isListening(), true);
  const b = new AbortController();
  const rb = t.start({ accountId: "default", signal: b.signal, onInbound: async () => {} });
  await sleep(20);
  assert.deepEqual(p.ev, ["sink", "listen", "sink"], "a takeover does not bind again");
  a.abort();
  await ra;
  assert.equal(p.isListening(), true, "the older start's abort leaves the listener");
  b.abort();
  await rb;
  assert.equal(p.isListening(), false, "the newest start's abort closes it, before that start settles");
  const dead = new AbortController();
  dead.abort();
  const before = p.ev.length;
  await t.start({ accountId: "default", signal: dead.signal, onInbound: async () => {} });
  assert.deepEqual(p.ev.slice(before), ["sink"], "an aborted start binds nothing");
  const f = fakeParts({ failStart: true });
  const tf = createListenerBoundTransport({ cloud: f.cloud, listener: f.listener });
  await assert.rejects(tf.start({ accountId: "default", signal: new AbortController().signal, onInbound: async () => {} }), (e) => e.message === LISTENER_START_FAILED_MESSAGE);
  // a refusal of the Cloud API start ends the hold on the port
  const r = fakeParts();
  r.cloud.start = async () => {
    throw new Error("idx-whatsapp-channel: cloud api: unknown-account");
  };
  const tr = createListenerBoundTransport({ cloud: r.cloud, listener: r.listener });
  await assert.rejects(tr.start({ accountId: "x", signal: new AbortController().signal, onInbound: async () => {} }), /unknown-account/);
  await sleep(20);
  assert.equal(r.isListening(), false);
  for (const bad of [{}, { cloud: p.cloud }, { listener: p.listener }, { cloud: { start() {} }, listener: p.listener }]) {
    assert.throws(() => createListenerBoundTransport(bad), /listener-bound transport/);
  }
});

// ---- the host's string-only logger (real-host finding, 2026-11-08) ------------------------

/** A logger shaped like OpenClaw 2026.9.5's plugin logger: strings only, else it throws. */
function stringOnlyLogger(lines) {
  const take = (level) => (text) => {
    if (typeof text !== "string") throw new TypeError("text.includes is not a function");
    lines.push({ level, text });
  };
  return { info: take("info"), warn: take("warn"), error: take("error") };
}

test("CE-11 hostSafeLogger: fields reach a string-only host logger as one JSON line, an object logger gets them unchanged, and no logger failure ever throws", () => {
  const lines = [];
  const strict = stringOnlyLogger(lines);
  let calls = 0;
  const counted = { info: (t) => { calls += 1; return strict.info(t); }, warn: strict.warn, error: strict.error };
  const log = hostSafeLogger(counted);
  assert.ok(Object.isFrozen(log));
  log.info({ component: "idx-whatsapp-channel.cloud-api", event: "webhook-accepted", delivered: 1, ignored: 0 });
  log.info({ component: "idx-whatsapp-channel.cloud-api", event: "webhook-verified" });
  log.warn("idx-whatsapp-channel: a plain line");
  assert.deepEqual(lines, [
    { level: "info", text: '{"component":"idx-whatsapp-channel.cloud-api","event":"webhook-accepted","delivered":1,"ignored":0}' },
    { level: "info", text: '{"component":"idx-whatsapp-channel.cloud-api","event":"webhook-verified"}' },
    { level: "warn", text: "idx-whatsapp-channel: a plain line" },
  ]);
  assert.equal(calls, 3, "one refused object call, then JSON lines directly");
  const objects = [];
  hostSafeLogger({ warn: (m) => objects.push(m) }).warn({ component: "c", event: "e" });
  assert.deepEqual(objects, [{ component: "c", event: "e" }]);
  for (const base of [undefined, null, {}, { info: 1 }, { info() { throw new Error("down"); } }, { get info() { throw new Error("getter"); } }]) {
    const quiet = hostSafeLogger(base);
    assert.doesNotThrow(() => quiet.info({ component: "c", event: "e" }));
    assert.doesNotThrow(() => quiet.info("plain"));
  }
});

test("CE-12 real-host regression: with a string-only host logger the enabled entry still answers Meta's GET 200 and a signed POST 200 (both were 500 when a log line threw), and every line it logs is a JSON string (child process)", async () => {
  const creds = credentialsFile();
  try {
    const port = await freePort();
    const index = pathToFileURL(path.join(HERE, "index.mjs")).href;
    const status = Buffer.from(JSON.stringify({ object: "whatsapp_business_account", entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: { messaging_product: "whatsapp", metadata: { phone_number_id: CREDS.phoneNumberId }, statuses: [{ id: "wamid.CE12", status: "delivered", timestamp: String(Math.floor(Date.now() / 1000)), recipient_id: PEER_WA }] } }] }] }), "utf8");
    const out = JSON.parse(
      execFileSync(process.execPath, ["--input-type=module", "-e", `
        import { request } from "node:http";
        const { createPluginEntry } = await import(${JSON.stringify(index)});
        const lines = [];
        const take = (level) => (text) => { if (typeof text !== "string") throw new TypeError("text.includes is not a function"); lines.push(text); };
        const channels = [];
        const api = { config: ${JSON.stringify(CFG)}, registrationMode: "full",
          pluginConfig: ${JSON.stringify(block(creds.file, port))},
          logger: { info: take("info"), warn: take("warn"), error: take("error") }, registerChannel: (x) => channels.push(x) };
        createPluginEntry({ cloudApiDeps: { fetch: async () => { throw new Error("no send expected"); } } }).register(api);
        const plugin = channels[0].plugin;
        const ac = new AbortController();
        const running = plugin.gateway.startAccount({ cfg: api.config, accountId: "default", abortSignal: ac.signal });
        const call = (method, path, headers, body) => new Promise((resolve) => {
          const req = request({ host: "127.0.0.1", port: ${port}, method, path, headers, agent: false }, (res) => { const c = []; res.on("data", (d) => c.push(d)); res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(c).toString("utf8") })); });
          req.on("error", (e) => resolve({ error: e.code }));
          body === undefined ? req.end() : req.end(body);
        });
        let get = { error: "never" };
        for (let i = 0; i < 100 && get.error; i += 1) { get = await call("GET", ${JSON.stringify(`${CREDS.webhookPath}?hub.mode=subscribe&hub.verify_token=${CREDS.verifyToken}&hub.challenge=ce12`)}); if (get.error) await new Promise((r) => setTimeout(r, 20)); }
        const body = Buffer.from(${JSON.stringify(status.toString("base64"))}, "base64");
        const post = await call("POST", ${JSON.stringify(CREDS.webhookPath)}, { "content-type": "application/json", "x-hub-signature-256": ${JSON.stringify(sign(status))} }, body);
        ac.abort();
        await running;
        process.stdout.write(JSON.stringify({ configured: plugin.config.isConfigured(), get, post, lines }));
      `], { cwd: HERE, encoding: "utf8", timeout: 20_000 }),
    );
    assert.equal(out.configured, true);
    assert.deepEqual(out.get, { status: 200, body: "ce12" });
    assert.equal(out.post.status, 200);
    const events = out.lines.map((l) => JSON.parse(l)).map((o) => `${o.component}:${o.event}`);
    for (const e of ["idx-whatsapp-channel.cloud-api-listener:listener-started", "idx-whatsapp-channel.cloud-api:webhook-verified", "idx-whatsapp-channel.cloud-api:webhook-accepted", "idx-whatsapp-channel.cloud-api-listener:listener-stopped"]) {
      assert.ok(events.includes(e), `${e} in ${JSON.stringify(events)}`);
    }
    for (const leak of [CREDS.accessToken, CREDS.appSecret, CREDS.verifyToken, creds.file, String(port)]) assert.ok(!out.lines.join("\n").includes(leak), leak);
  } finally {
    creds.cleanup();
  }
});

test("CE-13 a credentials file changed after the process transport was built (a rotated secret, a hot reload in the same process) is refused credentials-changed: unconfigured, one fixed line with no value, the running transport untouched; a file that now fails its checks is refused with its own reason; restoring the original values is accepted again", async () => {
  assert.equal(Object.prototype.hasOwnProperty.call(globalThis, KEY), true, "runs after CE-6");
  const original = readFileSync(live.creds.file, "utf8");
  const built = Object.getOwnPropertyDescriptor(globalThis, KEY).value;
  const rotated = { ...CREDS, appSecret: "rotatedappsecretnotreal000000039" };
  const rewrite = (content, mode = 0o600) => {
    writeFileSync(live.creds.file, content);
    chmodSync(live.creds.file, mode);
  };
  try {
    for (const [name, content, reason, mode] of [
      ["rotated app secret", JSON.stringify(rotated), "credentials-changed"],
      ["rotated access token", JSON.stringify({ ...CREDS, accessToken: "TEST-ACCESS-TOKEN-rotated-not-real-00000039" }), "credentials-changed"],
      ["rotated verify token", JSON.stringify({ ...CREDS, verifyToken: "test-verify-token-rotated-039" }), "credentials-changed"],
      ["now too open", original, "credentials-permissions-too-open", 0o644],
      ["now not json", "{", "credentials-not-json"],
    ]) {
      rewrite(content, mode);
      for (const make of [createPluginEntry, (await import("./index.mjs?copy=ce13")).createPluginEntry]) {
        const host = fakeHost({ pluginConfig: block(live.creds.file, live.port) });
        make({ cloudApiDeps: { fetch: fakeGraphFetch } }).register(host.api);
        assert.equal(host.channels[0].plugin.config.isConfigured(), false, name);
        assert.deepEqual(host.lines, [{ level: "error", m: { component: "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason } }], name);
        const text = JSON.stringify(host.lines);
        for (const leak of [live.creds.file, rotated.appSecret, CREDS.appSecret, CREDS.accessToken, CREDS.verifyToken]) assert.ok(!text.includes(leak), `${name}: log exposes ${leak}`);
      }
      assert.equal(Object.getOwnPropertyDescriptor(globalThis, KEY).value, built, `${name}: the stored transport is unchanged`);
    }
    // the old secret no longer reaches a configured channel: a register is refused, so no
    // account of it can start, and the port stays closed
    assert.equal(await refused(live.port), true);
    rewrite(original);
    const host = fakeHost({ pluginConfig: block(live.creds.file, live.port) });
    createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch } }).register(host.api);
    assert.equal(host.channels[0].plugin.config.isConfigured(), true, "the original values are accepted again");
    assert.deepEqual(refusalLines(host), []);
  } finally {
    rewrite(original);
  }
});
