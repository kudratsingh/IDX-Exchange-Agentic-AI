#!/usr/bin/env node
/**
 * Real-host replay harness (WO-037 installation prerequisite, owner item 19 (a) / 21).
 *
 * Runs the pinned OpenClaw build (never vendored; path from OPENCLAW_PKG, default the
 * global npm install) as a real gateway in an isolated sandbox:
 *   - `env -i` with temporary HOME, OPENCLAW_HOME, OPENCLAW_STATE_DIR and config path;
 *   - macOS `sandbox-exec` denying every read and write under ~/.openclaw and all
 *     outbound network except loopback;
 *   - a scripted fake model on loopback (fake-model.mjs) and a fake stdio `idx` MCP
 *     server (fake-mcp-idx.mjs); no keys, no paid calls, synthetic data only;
 *   - the harness plugin (plugin/): the production entry with a fake transport.
 *
 * Scenario (one fresh gateway per mode):
 *   1. a genuine WhatsApp DM from +15555550101 runs the card tool `idx__search_listings`;
 *   2. while that run is held live (the fake model holds its second response), a
 *      dashboard operator client sends `chat.send` with the genuine run's id as
 *      `idempotencyKey` and its session key, optionally with a queue mode;
 *   3. the hold is released and the harness waits for the run(s) to settle.
 * Checks: A) the genuine turn delivers exactly the stored card bytes to the peer;
 *         B) the replay does not execute the card tool;
 *         C) the replay does not suppress the genuine reply.
 *
 * Usage: node run.mjs [mode ...]   modes: genuine-only, default, steer, followup, collect, interrupt,
 *        interrupt-fresh (an interrupt that does not replay the run id; not a replay),
 *        interrupt-roles (interrupt-fresh from an identity-authenticated dashboard user under
 *        gateway.roles with sessions.others "none": the host-level control under test),
 *        not-allowlisted (a DM from a sender outside allowFrom gets nothing; the peer still does),
 *        payloads (one genuine turn per committed real-server payload case, exact bytes each),
 *        cloud-api (WO-039: the PRODUCTION Cloud API wiring, enabled by the plugin's cloudApi
 *        block, a synthetic owner credentials file made in the run root (mode 600, removed
 *        after), signed webhook POSTs through the plugin's own loopback listener and a fake
 *        Graph API fetch inside the plugin; checks S, W, G, U, N, R, X in checks.mjs; the block
 *        is written by the runbook's own `openclaw config set` command, check K),
 *        cloud-api-rollback (runbook 7.6 on the real host: the fast rollback's
 *        `enabled false` hot-applied to a running gateway, H; a fresh process with
 *        `enabled false`, F; the full rollback's config commands, V; and K)
 * Prints one JSON result per mode and exits 0 when every requested mode passes A, B, C.
 */
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync, realpathSync } from "node:fs";
import { request } from "node:http";
import { connect, createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHmac, randomBytes } from "node:crypto";
import { PAYLOAD_CASES, WITHHELD_PAYLOAD_CASES, loadPayload } from "../test-support/payloads.mjs";
import { REPLY_LINES, composeReply, renderToolSection } from "../reply-render.mjs";
import { evaluate, evaluateCloudApi, evaluateCloudRollback, evaluateConfigCli, evaluateOwnerChecks } from "./checks.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = process.env.OPENCLAW_PKG ?? join(homedir(), ".npm-global/lib/node_modules/openclaw");
const PEER = "+15555550101";
/** A synthetic sender that is not on the harness allowlist. */
const STRANGER = "+15555550199";
/** The payload case the genuine turn's card call returns (a real-server payload). */
const GENUINE_CASE = "search-features";
/** The reply the peer must receive for a payload case: the channel's own renderer on the payload. */
function expectedReplyFor(caseName) {
  const p = loadPayload(caseName);
  return composeReply([renderToolSection(p.hostToolName, p.result)].filter(Boolean)) ?? null;
}
/** Whether the host handed the channel the payload faithfully. OpenClaw 2026.9.5 cuts the
 *  text block at 8000 characters (+ "\n…(truncated)…") and carries the full structured
 *  result in details.structuredContent with key-like fields redacted to "***"; so a long
 *  payload counts as faithful when its text is exactly the cut form and its details equal
 *  the payload apart from those redactions, and the details name the idx server. */
function hostFaithful(after, payloadText) {
  if (!after || typeof after.contentText !== "string") return false;
  const CUT = 8000;
  const MARK = "\n…(truncated)…";
  if (payloadText.length <= CUT) return after.contentText === payloadText;
  if (after.contentText !== `${payloadText.slice(0, CUT)}${MARK}`) return false;
  if (after.detailsServer !== "idx" || typeof after.detailsStructuredJson !== "string") return false;
  const want = JSON.parse(payloadText.slice("structuredContent:\n".length));
  const redact = (v) => (Array.isArray(v) ? v.map(redact) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, /key/u.test(k) ? "***" : redact(x)])) : v);
  return JSON.stringify(redact(want)) === JSON.stringify(redact(JSON.parse(after.detailsStructuredJson)));
}

/** An oracle independent of the channel's renderer: what the server itself approved for the
 *  case. ok:true -> the envelope's message (plus the server's options line for a
 *  clarification with options); ok:false -> the server's error sentence; a case in
 *  payloads-withheld/ -> SAFE_TEXT (the channel must not release it). */
function serverApprovedFor(caseName) {
  if (WITHHELD_PAYLOAD_CASES.includes(caseName)) return SAFE_TEXT;
  const env = JSON.parse(loadPayload(caseName).result.content[0].text.slice("structuredContent:\n".length));
  if (env.ok === false) return typeof env.error?.message === "string" ? env.error.message : null;
  const opts = env.data && Array.isArray(env.data.options) && env.data.options.length && env.data.question === env.message ? env.data.options : null;
  return opts ? `${env.message}\n\n${REPLY_LINES.options}${opts.join(", ")}` : env.message;
}
const SAFE_TEXT = "I couldn't send that reply safely. Please ask again.";
/** The card ref the fake model's dashboard script requests (fake-model.mjs). */
const REPLAY_REF = "dashboard-1";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- mode cloud-api helpers (WO-039) ------------------------------------------------------
/** The synthetic peer's Cloud API `from` / `to` form (digits only). */
const PEER_WA = PEER.slice(1);
const STRANGER_WA = STRANGER.slice(1);
/** Synthetic Cloud API credentials, fresh per run. Plausible shapes only; none is real. */
function syntheticCredentials() {
  return {
    accessToken: `HARNESS-TOKEN-not-real-${randomBytes(16).toString("hex")}`,
    appSecret: `harnesssecret${randomBytes(12).toString("hex")}`,
    graphApiVersion: "v99.9",
    phoneNumberId: "1000000000555",
    verifyToken: `harness-verify-${randomBytes(8).toString("hex")}`,
    webhookPath: "/idx-harness/cloud-api/webhook",
  };
}
/** Whether a TCP connect to the loopback port succeeds. */
function accepts(port) {
  return new Promise((resolve) => {
    const sock = connect({ host: "127.0.0.1", port });
    sock.once("connect", () => {
      sock.destroy();
      resolve(true);
    });
    sock.once("error", () => resolve(false));
  });
}
/** One request to the plugin's loopback listener: `{ status, body }` or `{ error }`. */
function listenerCall(port, { method = "POST", url, headers = {}, body } = {}) {
  return new Promise((resolve) => {
    const req = request({ host: "127.0.0.1", port, method, path: url, headers, agent: false, timeout: 15000 }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", (e) => resolve({ error: e?.code ?? String(e?.message ?? e) }));
    if (body !== undefined) req.end(body);
    else req.end();
  });
}
/** A Meta-shaped webhook body: one inbound text, or (text null) one delivered status. */
function webhookBytes(creds, { from = PEER_WA, id, text }) {
  const ts = String(Math.floor(Date.now() / 1000));
  const value = { messaging_product: "whatsapp", metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: creds.phoneNumberId } };
  if (text === null) value.statuses = [{ id, status: "delivered", timestamp: ts, recipient_id: from }];
  else {
    value.contacts = [{ profile: { name: "Synthetic Buyer" }, wa_id: from }];
    value.messages = [{ from, id, timestamp: ts, type: "text", text: { body: text } }];
  }
  return Buffer.from(JSON.stringify({ object: "whatsapp_business_account", entry: [{ id: "WABA-HARNESS", changes: [{ field: "messages", value }] }] }), "utf8");
}
const hubSignature = (bytes, secret) => `sha256=${createHmac("sha256", secret).update(bytes).digest("hex")}`;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

const readJsonl = (file) => {
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => {
      try {
        return JSON.parse(l);
      } catch {
        return { unparsed: l };
      }
    });
};

async function waitFor(pred, ms, step = 200) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await pred();
    if (v) return v;
    await sleep(step);
  }
  return null;
}

function sandboxProfile() {
  const oc = join(homedir(), ".openclaw");
  return [
    "(version 1)",
    "(allow default)",
    "(deny network-outbound)",
    '(allow network-outbound (remote ip "localhost:*"))',
    "(allow network-outbound (remote unix-socket))",
    `(deny file-read* (subpath "${oc}"))`,
    `(deny file-write* (subpath "${oc}"))`,
  ].join("\n");
}

/**
 * One pinned-CLI command against the run's temporary state, with the gateway's isolation
 * (env -i values, the run's sandbox profile). Returns the exit status and the output; the
 * output carries only the run's synthetic paths and ports.
 */
function ocCli({ profilePath, env, cwd }, args) {
  const r = spawnSync("/usr/bin/sandbox-exec", ["-f", profilePath, process.execPath, join(PKG, "openclaw.mjs"), ...args], { cwd, env, encoding: "utf8", timeout: 120000 });
  return { status: typeof r.status === "number" ? r.status : null, out: `${r.stdout ?? ""}\n${r.stderr ?? ""}` };
}
/** The config path runbook 7.2 sets. */
const CLOUD_BLOCK_PATH = "plugins.entries.idx-whatsapp-channel.config.cloudApi";
/** The first JSON value a `config get --json` printed, or undefined. */
function parseCliJson(out) {
  const lines = String(out).split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const t = lines[i].trimStart();
    if (!t.startsWith("{") && !t.startsWith("[") && t !== "true" && t !== "false") continue;
    for (let j = lines.length; j > i; j -= 1) {
      try {
        return JSON.parse(lines.slice(i, j).join("\n"));
      } catch {}
    }
  }
  return undefined;
}
/** Key-sorted JSON, so a read-back compares by value, not by key order. */
const canonical = (v) => JSON.stringify(v, (_k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x));
/** The last non-empty output line, cut short, for the evidence record. */
const lastLine = (out) => String(out).split("\n").map((l) => l.trim()).filter(Boolean).pop()?.slice(0, 200) ?? null;

/**
 * Runbook 7.2's command, exactly as the owner will type it (with this run's synthetic file
 * and port), then `config validate` and a read-back; then the two refusals check K relies
 * on: the same command again (refused by --expect-current-absent, file unchanged) and a
 * listener on 0.0.0.0, an extra key and a string `enabled`, each a real set refused by the
 * plugin's strict schema with the file unchanged.
 */
function applyCloudBlockByCli(cli, cloud, cfgPath) {
  const block = { enabled: true, credentialsFile: cloud.file, listen: { host: "127.0.0.1", port: cloud.port } };
  const set = ocCli(cli, ["config", "set", CLOUD_BLOCK_PATH, JSON.stringify(block), "--strict-json", "--expect-current-absent"]);
  const validate = ocCli(cli, ["config", "validate"]);
  const get = ocCli(cli, ["config", "get", CLOUD_BLOCK_PATH, "--json"]);
  const readBack = parseCliJson(get.out);
  const bytes = () => readFileSync(cfgPath);
  const b0 = bytes();
  const repeat = ocCli(cli, ["config", "set", CLOUD_BLOCK_PATH, JSON.stringify(block), "--strict-json", "--expect-current-absent"]);
  const repeatUnchanged = b0.equals(bytes());
  // Three refusals by the plugin's strict schema, each a REAL set (no --dry-run): exit
  // non-zero, the schema's own message, and the file byte for byte as it was.
  const refusal = (args, re) => {
    const before = bytes();
    const r = ocCli(cli, ["config", "set", ...args, "--strict-json"]);
    return { status: r.status, schemaRefusal: re.test(r.out), fileUnchanged: before.equals(bytes()), note: lastLine(r.out) };
  };
  const badHost = refusal([`${CLOUD_BLOCK_PATH}.listen.host`, JSON.stringify("0.0.0.0")], /listen\.host: invalid config: must be equal to one of the allowed values/u);
  const extraKey = refusal([`${CLOUD_BLOCK_PATH}.extra`, "true"], /cloudApi: invalid config: must not have additional properties/u);
  const stringEnabled = refusal([`${CLOUD_BLOCK_PATH}.enabled`, JSON.stringify("true")], /cloudApi\.enabled: invalid config: must be boolean/u);
  return {
    set: { status: set.status, note: lastLine(set.out) },
    validate: { status: validate.status, note: lastLine(validate.out) },
    readBackEqual: get.status === 0 && readBack !== undefined && canonical(readBack) === canonical(block),
    repeat: { status: repeat.status, fileUnchanged: repeatUnchanged, note: lastLine(repeat.out) },
    badHost,
    extraKey,
    stringEnabled,
  };
}

/** The runbook (section 7) whose owner-check blocks check O runs verbatim. */
const RUNBOOK = join(HERE, "../../../docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md");
/** The shell block between the runbook's `owner-check:<name>` markers, exactly as written. */
function ownerBlock(name) {
  const text = readFileSync(RUNBOOK, "utf8");
  const body = text.slice(text.indexOf(`<!-- owner-check:${name}:begin -->`), text.indexOf(`<!-- owner-check:${name}:end -->`));
  const open = body.indexOf("```sh\n");
  if (open === -1) throw new Error(`runbook block ${name} not found`);
  return body.slice(open + "```sh\n".length, body.lastIndexOf("```"));
}
/** Local time to the second, as the owner records it (`date +%Y-%m-%dT%H:%M:%S`). */
const localStamp = () => execFileSync("/bin/date", ["+%Y-%m-%dT%H:%M:%S"], { encoding: "utf8" }).trim();
/**
 * Runs a runbook owner-check block with /bin/sh, as the owner would, with an `openclaw` on
 * PATH that is the pinned CLI against this run's sandboxed state, and the real curl.
 * Returns its stdout lines.
 */
function runOwnerBlock(ownerBin, name, vars) {
  const r = spawnSync("/bin/sh", ["-c", ownerBlock(name)], { env: { PATH: `${ownerBin}:${process.env.PATH}`, HOME: tmpdir(), ...vars }, encoding: "utf8", timeout: 120000 });
  return String(r.stdout ?? "").trim().split("\n").filter(Boolean);
}
/** Writes `<dir>/openclaw`: the pinned CLI with the gateway's isolation, for the owner blocks. */
function writeOwnerCli(dir, { profilePath, env, cwd }) {
  mkdirSync(dir, { recursive: true });
  const q = (v) => `'${String(v).replace(/'/g, "'\\''")}'`;
  const envArgs = Object.entries(env).map(([k, v]) => `${k}=${q(v)}`).join(" ");
  writeFileSync(join(dir, "openclaw"), `#!/bin/sh\ncd ${q(cwd)} || exit 1\nexec env -i ${envArgs} /usr/bin/sandbox-exec -f ${q(profilePath)} ${q(process.execPath)} ${q(join(PKG, "openclaw.mjs"))} "$@"\n`, { mode: 0o755 });
  chmodSync(join(dir, "openclaw"), 0o755);
  return dir;
}

class Operator {
  constructor(url, auth, headers) {
    this.url = url;
    this.auth = auth; // { token } | { password } | null
    this.headers = headers;
    this.pending = new Map();
    this.events = [];
    this.n = 0;
  }
  async open() {
    // Node's WebSocket (undici) accepts request headers in its init object; the
    // interrupt-roles mode uses them to present a trusted-proxy identity.
    this.ws = this.headers ? new WebSocket(this.url, { headers: this.headers }) : new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = (e) => reject(new Error(`ws error ${e?.message ?? ""}`));
    });
    this.ws.onmessage = (m) => {
      let f;
      try {
        f = JSON.parse(String(m.data));
      } catch {
        return;
      }
      if (f.type === "res" && this.pending.has(f.id)) {
        this.pending.get(f.id)(f);
        this.pending.delete(f.id);
      } else if (f.type === "event") {
        this.events.push({ at: Date.now(), event: f.event, runId: f.payload?.runId, sessionKey: f.payload?.sessionKey, state: f.payload?.state ?? f.payload?.status });
      }
    };
    return this.req("connect", {
      minProtocol: 4,
      maxProtocol: 4,
      client: { id: "cli", mode: "cli", version: "harness", platform: "node" },
      role: "operator",
      scopes: ["operator.admin", "operator.read", "operator.write"],
      ...(this.auth ? { auth: this.auth } : {}),
    });
  }
  req(method, params, ms = 20000) {
    const id = String(++this.n);
    return new Promise((resolve) => {
      const t = setTimeout(() => {
        this.pending.delete(id);
        resolve({ timeout: true, method });
      }, ms);
      this.pending.set(id, (f) => {
        clearTimeout(t);
        resolve(f);
      });
      this.ws.send(JSON.stringify({ type: "req", id, method, params }));
    });
  }
  close() {
    try {
      this.ws.close();
    } catch {}
  }
}

/** Thrown to leave the shared flow once the cloud-api scenario has run. */
class CloudDone extends Error {}

/**
 * Mode cloud-api (WO-039). The plugin runs the production Cloud API wiring; the harness
 * talks to it only through its loopback listener, as the owner's tunnel would. Every
 * piece of evidence is waited for with a deadline and recorded, never assumed.
 */
async function cloudScenario({ cloud, data, modelPort, gw, step }) {
  const { port, creds } = cloud;
  const url = creds.webhookPath;
  const signed = (bytes) => listenerCall(port, { url, headers: { "content-type": "application/json", "x-hub-signature-256": hubSignature(bytes, creds.appSecret) }, body: bytes });
  const graphCount = () => readJsonl(join(data, "graph.jsonl")).length;
  const audit = () => readJsonl(join(data, "audit.jsonl"));
  // S: startup. The listener binds when the account starts; a signed statuses-only POST
  // answers 503 until the transport holds the channel's sink, then 200.
  const reg = await waitFor(() => readJsonl(join(data, "transport.jsonl")).find((e) => e.event === "registered" || e.event === "register-threw"), 60000, 500);
  if (!reg || reg.event === "register-threw") throw new Error("plugin did not register");
  const listenerStartedLogged = Boolean(await waitFor(() => audit().some((a) => a.component === "idx-whatsapp-channel.cloud-api-listener" && a.event === "listener-started"), 60000, 250));
  const accepting = Boolean(await waitFor(() => accepts(port), 30000, 250));
  const challenge = `harness-${randomBytes(4).toString("hex")}`;
  const verify = await listenerCall(port, { method: "GET", url: `${url}?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(creds.verifyToken)}&hub.challenge=${challenge}` });
  let probes = 0;
  const ready = Boolean(
    await waitFor(async () => {
      probes += 1;
      const r = await signed(webhookBytes(creds, { id: `wamid.HARNESS-probe-${probes}`, text: null }));
      return r.status === 200;
    }, 60000, 500),
  );
  const refusals = audit().filter((a) => a.event === "cloud-api-refused").map((a) => a.reason);
  step({ startup: { listenerStartedLogged, accepting, verifyStatus: verify.status ?? null, verifyEchoed: verify.body === challenge, ready, readinessProbes: probes, refusals } });
  if (!ready) throw new Error("the Cloud API account never became ready");

  // Check O: the runbook's 7.5 log check runs over the genuine turn below.
  await sleep(1100);
  const smokeStart = localStamp();
  // W and G: one signed genuine DM from the allowlisted peer.
  const tag = randomBytes(3).toString("hex");
  const ref = `genuine-${tag}`;
  const genuine = await signed(webhookBytes(creds, { id: `wamid.HARNESS-${tag}`, text: `GENUINE-${tag} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  step({ signedGenuine: { status: genuine.status ?? null, error: genuine.error ?? null } });
  const genuineCall = await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === ref), 60000);
  step({ genuineHook: genuineCall ?? null });
  if (!genuineCall) throw new Error("genuine card call never reached the hook");
  const held = await waitFor(async () => (await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json()).held >= 1, 60000);
  step({ genuineHeldLive: Boolean(held), graphWhileHeld: graphCount() });
  await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
  const sent = await waitFor(() => graphCount() >= 1, 45000);
  await sleep(3000); // a second send would show here
  step({ graphAfterGenuine: { seen: Boolean(sent), count: graphCount() } });
  {
    // The owner's 7.5 log check, verbatim, against this gateway's real log since the start:
    // one inbound, one reply, no busy reply; the leak pattern holds this run's synthetic
    // identifiers and the DM's words. Then two probes that must not print clean.
    const leakRe = [PEER_WA, creds.phoneNumberId, creds.webhookPath, "wamid\\.", "agent:", "please show me", `GENUINE-${tag}`].join("|");
    const base = { SMOKE_START: smokeStart, SMOKE_LEAK_RE: leakRe, SMOKE_EXPECT_IN: "1", SMOKE_EXPECT_REPLY: "1", SMOKE_EXPECT_BUSY: "0" };
    step({
      ownerSmoke: {
        pass: runOwnerBlock(cloud.ownerBin, "smoke-log", base),
        wrongCount: runOwnerBlock(cloud.ownerBin, "smoke-log", { ...base, SMOKE_EXPECT_IN: "2" }),
        leakProbe: runOwnerBlock(cloud.ownerBin, "smoke-log", { ...base, SMOKE_LEAK_RE: "webhook-accepted" }),
      },
    });
  }

  // U: an unsigned POST and a tampered one (signed, then one word changed): 401, no turn.
  const uTag = randomBytes(3).toString("hex");
  cloud.markers = { unsigned: `GENUINE-unsigned${uTag}`, tampered: `GENUINE-tampered${uTag}`, stranger: "GENUINE-stranger" };
  const unsignedBytes = webhookBytes(creds, { id: `wamid.HARNESS-u-${uTag}`, text: `${cloud.markers.unsigned} CASE=${GENUINE_CASE} unsigned` });
  const unsigned = await listenerCall(port, { url, headers: { "content-type": "application/json" }, body: unsignedBytes });
  step({ unsignedPost: { status: unsigned.status ?? null, error: unsigned.error ?? null } });
  const original = webhookBytes(creds, { id: `wamid.HARNESS-t-${uTag}`, text: `GENUINE-original${uTag} CASE=${GENUINE_CASE} tampered` });
  const tamperedBytes = Buffer.from(original.toString("utf8").replace(`GENUINE-original${uTag}`, cloud.markers.tampered), "utf8");
  const tampered = await listenerCall(port, { url, headers: { "content-type": "application/json", "x-hub-signature-256": hubSignature(original, creds.appSecret) }, body: tamperedBytes });
  step({ tamperedPost: { status: tampered.status ?? null, error: tampered.error ?? null } });

  // N: a signed DM from a synthetic sender outside channels.whatsapp.allowFrom.
  const stranger = await signed(webhookBytes(creds, { from: STRANGER_WA, id: `wamid.HARNESS-s-${uTag}`, text: `GENUINE-stranger CASE=${GENUINE_CASE} please show me a 3 bed` }));
  step({ strangerPost: { status: stranger.status ?? null, error: stranger.error ?? null } });
  await sleep(10000); // anything the refused or dropped posts started would show by now
  step({ graphAfterRefusals: graphCount() });

  // R: a reload while a turn is held. Editing channels.whatsapp in the config makes the host
  // restart the channel (reload.configPrefixes): the account's signal aborts (the listener
  // closes) and startAccount runs again (it binds again). OpenClaw 2026.9.5 defers that
  // restart until live turns finish (gateway log: "deferring until ... embedded run(s)
  // complete"), so the held reply is delivered by a still-running account; a host that
  // restarted at once would void the turn instead (zero Graph API calls, withheld
  // untrusted-turn). R accepts either, names which one happened, and requires the port to
  // be released and bound again and the next DM to make exactly one request.
  await fetch(`http://127.0.0.1:${modelPort}/control/hold`, { method: "POST" });
  const rTag = randomBytes(3).toString("hex");
  const heldPost = await signed(webhookBytes(creds, { id: `wamid.HARNESS-r-${rTag}`, text: `GENUINE-reload${rTag} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  const heldHook = await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === `genuine-reload${rTag}`), 60000);
  const heldLive = await waitFor(async () => (await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json()).held >= 1, 60000);
  const graphAtReload = graphCount();
  const reloadAt = Date.now();
  const cfg = JSON.parse(readFileSync(cloud.cfgPath, "utf8"));
  cfg.channels.whatsapp.allowFrom = [PEER, "+15555550102"];
  writeFileSync(cloud.cfgPath, JSON.stringify(cfg, null, 2));
  const listenerLines = () => audit().filter((a) => a.component === "idx-whatsapp-channel.cloud-api-listener" && a.at >= reloadAt);
  await sleep(5000); // long enough for the host to see the edit and either restart or defer
  const stoppedWhileHeld = listenerLines().some((a) => a.event === "listener-stopped");
  await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
  const stoppedAt = (await waitFor(() => listenerLines().find((a) => a.event === "listener-stopped"), 60000, 250))?.at ?? null;
  const restartedAt = stoppedAt === null ? null : ((await waitFor(() => listenerLines().find((a) => a.event === "listener-started" && a.at >= stoppedAt), 60000, 250))?.at ?? null);
  const readyAgain = restartedAt !== null && Boolean(await waitFor(async () => (await signed(webhookBytes(creds, { id: `wamid.HARNESS-probe-r-${randomBytes(3).toString("hex")}`, text: null }))).status === 200, 30000, 250));
  await sleep(2000);
  const sinceReload = readJsonl(join(data, "graph.jsonl")).slice(graphAtReload);
  const heldReplySends = sinceReload.filter((g) => stoppedAt === null || g.at < stoppedAt).map((g) => g.body);
  const sendsWhileDown = sinceReload.filter((g) => stoppedAt !== null && g.at >= stoppedAt && (restartedAt === null || g.at < restartedAt)).length;
  const withheld = audit().find((a) => a.component === "idx-whatsapp-channel.outbound" && a.at >= reloadAt && a.reason === "untrusted-turn");
  const graphBeforeNext = graphCount();
  const aTag = randomBytes(3).toString("hex");
  const after = await signed(webhookBytes(creds, { id: `wamid.HARNESS-a-${aTag}`, text: `GENUINE-after${aTag} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  await waitFor(() => graphCount() > graphBeforeNext, 45000);
  await sleep(3000);
  step({
    reload: {
      heldStatus: heldPost.status ?? null,
      lateTurnHeld: Boolean(heldHook) && Boolean(heldLive),
      reloadAt,
      stoppedWhileHeld,
      hostDeferredReload: !stoppedWhileHeld,
      listenerStoppedAt: stoppedAt,
      listenerRestartedAt: restartedAt,
      readyAgain,
      heldReplySends,
      sendsWhileDown,
      lateReplyWithheld: withheld ? withheld.reason : null,
      afterStatus: after.status ?? null,
      afterSends: readJsonl(join(data, "graph.jsonl")).slice(graphBeforeNext).map((g) => g.body),
    },
  });

  // X: stop the gateway. On 2026.9.5 the host drains active work first and then aborts the
  // account (the listener logs listener-stopped); after that the port must be free, and
  // nothing may reach the Graph API from the stop on.
  await sleep(2000);
  const graphBeforeStop = graphCount();
  const exited = new Promise((resolve) => {
    if (gw.exitCode !== null || gw.signalCode !== null) resolve({ code: gw.exitCode, signal: gw.signalCode });
    else gw.once("exit", (code, signal) => resolve({ code, signal }));
  });
  const stopAt = Date.now();
  gw.kill("SIGTERM");
  const exit = await Promise.race([exited, sleep(30000).then(() => null)]);
  const exitedAt = Date.now();
  const portReleased = Boolean(await waitFor(async () => !(await accepts(port)), 10000, 200));
  const accountStoppedAt = audit().find((a) => a.component === "idx-whatsapp-channel.cloud-api-listener" && a.event === "listener-stopped" && a.at >= stopAt)?.at ?? null;
  step({
    shutdown: {
      stopAt,
      accountStoppedAt,
      exited: exit !== null,
      exit,
      exitedAfterMs: exitedAt - stopAt,
      portReleased,
      graphBeforeStop,
      graphAfterExit: graphCount(),
    },
  });
}

/**
 * Mode cloud-api-rollback (runbook 7.6). See evaluateCloudRollback in checks.mjs for H, F
 * and V. `gwRef.get()` is the running gateway; `gwRef.respawn()` starts a fresh process on
 * the same temporary state.
 */
async function rollbackScenario({ cloud, data, modelPort, step, cli, gwRef }) {
  const { port, creds } = cloud;
  const url = creds.webhookPath;
  const signed = (bytes) => listenerCall(port, { url, headers: { "content-type": "application/json", "x-hub-signature-256": hubSignature(bytes, creds.appSecret) }, body: bytes });
  const graphCount = () => readJsonl(join(data, "graph.jsonl")).length;
  const audit = () => readJsonl(join(data, "audit.jsonl"));
  const listenerEvent = (event, since) => audit().find((a) => a.component === "idx-whatsapp-channel.cloud-api-listener" && a.event === event && a.at >= since);
  const stopGateway = async () => {
    const gw = gwRef.get();
    const exited = new Promise((resolve) => {
      if (gw.exitCode !== null || gw.signalCode !== null) resolve(true);
      else gw.once("exit", () => resolve(true));
    });
    gw.kill("SIGTERM");
    if (await Promise.race([exited, sleep(30000).then(() => false)])) return true;
    // Never leave a gateway running behind the next step: kill it, wait, and report false.
    try {
      gw.kill("SIGKILL");
    } catch {}
    await Promise.race([exited, sleep(10000)]);
    return false;
  };

  // The block the runbook's command wrote is live: ready, then one genuine reply.
  const reg = await waitFor(() => readJsonl(join(data, "transport.jsonl")).find((e) => e.event === "registered" || e.event === "register-threw"), 60000, 500);
  if (!reg || reg.event === "register-threw") throw new Error("plugin did not register");
  let probes = 0;
  const ready = Boolean(await waitFor(async () => (await signed(webhookBytes(creds, { id: `wamid.HARNESS-probe-${++probes}`, text: null }))).status === 200, 60000, 500));
  if (!ready) throw new Error("the Cloud API account never became ready");
  const tag = randomBytes(3).toString("hex");
  await signed(webhookBytes(creds, { id: `wamid.HARNESS-${tag}`, text: `GENUINE-${tag} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  const genuineCall = await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === `genuine-${tag}`), 60000);
  step({ genuineHook: genuineCall ?? null });
  if (!genuineCall) throw new Error("genuine card call never reached the hook");
  await waitFor(async () => (await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json()).held >= 1, 60000);
  await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
  await waitFor(() => graphCount() >= 1, 45000);
  await sleep(3000);
  step({ beforeRollback: { ready, genuineSends: graphCount() } });

  // H: the fast rollback's config edit on the RUNNING gateway, before any restart, while a
  // second genuine turn is held live by the model (a reply "already being written").
  await fetch(`http://127.0.0.1:${modelPort}/control/hold`, { method: "POST" });
  const kTag = randomBytes(3).toString("hex");
  const heldPost = await signed(webhookBytes(creds, { id: `wamid.HARNESS-k-${kTag}`, text: `GENUINE-held${kTag} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  const heldHook = await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === `genuine-held${kTag}`), 60000);
  const heldLive = await waitFor(async () => (await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json()).held >= 1, 60000);
  // Check O: the runbook's 7.6 confirmation, verbatim, before the edit (it must not confirm:
  // the listener runs) and after it (it must confirm).
  await sleep(1100);
  const rollbackVars = { ROLLBACK_START: localStamp(), OWNER_LISTEN_URL: `http://127.0.0.1:${port}/` };
  const confirmBefore = runOwnerBlock(cloud.ownerBin, "rollback", rollbackVars);
  const editAt = Date.now();
  const set = ocCli(cli, ["config", "set", `${CLOUD_BLOCK_PATH}.enabled`, "false", "--strict-json"]);
  const setReturnedAt = Date.now();
  await sleep(5000); // long enough for the host to apply the edit or defer it
  const stoppedWhileHeld = Boolean(listenerEvent("listener-stopped", editAt));
  await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
  const stopped = await waitFor(() => listenerEvent("listener-stopped", editAt), 60000, 250);
  await sleep(3000);
  step({ ownerRollback: { before: confirmBefore, after: runOwnerBlock(cloud.ownerBin, "rollback", rollbackVars) } });
  const sinceEdit = readJsonl(join(data, "graph.jsonl")).filter((g) => g.at >= editAt);
  const stoppedAt = stopped?.at ?? null;
  const heldReplySends = sinceEdit.filter((g) => stoppedAt === null || g.at < stoppedAt).map((g) => g.body);
  const withheld = audit().find((a) => a.component === "idx-whatsapp-channel.outbound" && a.at >= editAt && a.reason === "untrusted-turn");
  const portRefusedAfter = !(await accepts(port));
  const hTag = randomBytes(3).toString("hex");
  const marker = `GENUINE-hot${hTag}`;
  const graphBeforePost = graphCount();
  const post = await signed(webhookBytes(creds, { id: `wamid.HARNESS-h-${hTag}`, text: `${marker} CASE=${GENUINE_CASE} please show me a 3 bed` }));
  await sleep(15000); // a turn the post started would have reached the model and Graph by now
  step({
    hotApply: {
      editAt,
      setReturnedAt,
      setStatus: set.status,
      setNote: lastLine(set.out),
      heldStatus: heldPost.status ?? null,
      heldLive: Boolean(heldHook) && Boolean(heldLive),
      stoppedWhileHeld,
      listenerStoppedAt: stoppedAt,
      heldReplySends,
      lateReplyWithheld: withheld ? withheld.reason : null,
      sendsAfterStop: stoppedAt === null ? null : readJsonl(join(data, "graph.jsonl")).filter((g) => g.at >= stoppedAt).length,
      graphAfterPost: graphCount() - graphBeforePost,
      portRefusedAfter,
      marker,
      postAfterEdit: post.status ?? post.error ?? null,
      registersAfterEdit: readJsonl(join(data, "transport.jsonl")).filter((e) => e.event === "registered" && e.at >= editAt).length,
    },
  });

  // H, last look before the stop: the listener never came back after the edit.
  step({
    hotApplyEnd: {
      listenerStartedAfterEdit: audit().filter((a) => a.component === "idx-whatsapp-channel.cloud-api-listener" && a.event === "listener-started" && a.at >= editAt).length,
      portRefusedAtEnd: !(await accepts(port)),
    },
  });

  // F: the fast rollback's restart as a fresh process (gateway stop, then start), enabled false.
  const firstExited = await stopGateway();
  if (!firstExited) throw new Error("the first gateway did not exit");
  const graphAtFresh = graphCount();
  const freshAt = Date.now();
  gwRef.respawn();
  const registered = Boolean(await waitFor(() => readJsonl(join(data, "transport.jsonl")).find((e) => e.event === "registered" && e.at >= freshAt), 60000, 500));
  await sleep(20000); // a listener that was going to bind would have bound by now
  const getEnabled = ocCli(cli, ["config", "get", `${CLOUD_BLOCK_PATH}.enabled`, "--json"]);
  step({
    freshOff: {
      firstExited,
      registered,
      listenerStartedLogged: Boolean(listenerEvent("listener-started", freshAt)),
      portRefused: !(await accepts(port)),
      refusals: audit().filter((a) => a.event === "cloud-api-refused" && a.at >= freshAt).map((a) => a.reason),
      graphDuring: graphCount() - graphAtFresh,
      offConfirmed: getEnabled.status === 0 && parseCliJson(getEnabled.out) === false,
    },
  });

  // V: the full rollback's config commands, gateway stopped.
  const secondExited = await stopGateway();
  if (!secondExited) throw new Error("the second gateway did not exit");
  const unset = ocCli(cli, ["config", "unset", CLOUD_BLOCK_PATH]);
  const validate = ocCli(cli, ["config", "validate"]);
  const getAfter = ocCli(cli, ["config", "get", CLOUD_BLOCK_PATH, "--json"]);
  const disable = ocCli(cli, ["plugins", "disable", "idx-whatsapp-channel"]);
  const enabledAfter = ocCli(cli, ["config", "get", "plugins.entries.idx-whatsapp-channel.enabled", "--json"]);
  step({
    fullRollback: {
      secondExited,
      unsetStatus: unset.status,
      validateStatus: validate.status,
      getAfterUnsetStatus: getAfter.status,
      getAfterUnsetMessage: (() => {
        const env = parseCliJson(getAfter.out);
        return env && env.ok === false && typeof env.error?.message === "string" ? env.error.message.slice(0, 300) : null;
      })(),
      disableStatus: disable.status,
      enabledAfterDisable: enabledAfter.status === 0 ? parseCliJson(enabledAfter.out) : null,
    },
  });
}

async function runMode(mode) {
  const root = realpathSync(mkdtempSync(join(process.env.IDX_HARNESS_ROOT ?? tmpdir(), `idx-replay-${mode}-`)));
  const dirs = Object.fromEntries(["home", "state", "cwd", "ws", "data"].map((k) => [k, join(root, k)]));
  for (const d of Object.values(dirs)) mkdirSync(d, { recursive: true });
  const data = dirs.data;
  const [gwPort, modelPort, transportPort] = [await freePort(), await freePort(), await freePort()];
  // Mode cloud-api: the plugin's own loopback listener port and the owner credentials file,
  // synthetic, in a 0700 directory of the run root (outside the repo and outside the
  // sandboxed HOME's .openclaw), mode 600; removed after the run.
  const cloudMode = mode === "cloud-api" || mode === "cloud-api-rollback";
  const cloud = cloudMode ? { port: await freePort(), creds: syntheticCredentials(), dir: join(root, "owner-secrets") } : null;
  if (cloud) {
    mkdirSync(cloud.dir, { mode: 0o700 });
    chmodSync(cloud.dir, 0o700);
    cloud.file = join(cloud.dir, "cloud-api.json");
    writeFileSync(cloud.file, JSON.stringify(cloud.creds), { mode: 0o600 });
    chmodSync(cloud.file, 0o600);
  }
  const token = randomBytes(16).toString("hex"); // throwaway loopback token, not a credential
  const config = {
    gateway: { mode: "local", port: gwPort, bind: "loopback", auth: { mode: "token", token } },
    update: { checkOnStart: false, auto: { enabled: false } },
    logging: { file: join(dirs.data, "openclaw.log"), level: "debug" },
    discovery: { mdns: { mode: "off" } },
    plugins: {
      load: { paths: [join(HERE, "plugin")] },
      // A path-loaded plugin has no install record, so the host loads it only when listed
      // in plugins.allow; an allow list then has to name every plugin the run needs
      // (the bundled set this build loads with no allow list, plus ours).
      allow: [
        "idx-whatsapp-channel", "anthropic", "browser", "canvas", "cua-computer", "device-pair", "file-transfer",
        "geolocation", "linux-node", "memory-core", "ollama", "openai", "talk-voice", "xai",
      ],
      // No "whatsapp" deny: on 2026.9.5 the host resolves that id to this channel's owner
      // (ours) and leaves it out of startup. The allow list above, which does not name
      // "whatsapp", is what keeps a stock WhatsApp plugin out (self-check allow-list form).
      deny: ["bonjour", "active-memory"],
      // The token instruction hook (before_prompt_build) needs conversation access granted
      // to a non-bundled plugin on 2026.9.5 (runbook C10).
      entries: {
        "idx-whatsapp-channel": {
          enabled: true,
          hooks: { allowConversationAccess: true },
          config: {
            harnessDir: data,
            transportPort,
            // Modes cloud-api*: no cloudApi block here. The runbook's own `config set`
            // command writes it after the plugin is linked (check K).
          },
        },
      },
    },
    channels: { whatsapp: { enabled: true, dmPolicy: "allowlist", allowFrom: [PEER] } },
    session: { dmScope: "per-channel-peer" },
    models: {
      catalogRefresh: { enabled: false },
      providers: {
        fake: {
          baseUrl: `http://127.0.0.1:${modelPort}/v1`,
          api: "openai-completions",
          apiKey: "fake-local",
          agentRuntime: { id: "openclaw" },
          models: [
            {
              id: "fake-1",
              name: "Fake",
              reasoning: false,
              input: ["text"],
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
              contextWindow: 128000,
              maxTokens: 4096,
            },
          ],
        },
      },
    },
    agents: { defaults: { model: { primary: "fake/fake-1" }, workspace: dirs.ws, skipBootstrap: true } },
    tools: { profile: "messaging", toolSearch: false },
    mcp: { servers: { idx: { command: process.execPath, args: [join(HERE, "fake-mcp-idx.mjs")], env: { IDX_HARNESS_DIR: data } } } },
  };
  // interrupt-roles: the host-level control under test. Dashboard users authenticate by
  // identity (trusted proxy; here a same-host proxy is simulated with allowLoopback and a
  // TEST-NET forwarded address) and get a role without admin that cannot see sessions they
  // did not create. The shared token is not configured in this mode.
  const rolesMode = mode === "interrupt-roles";
  if (rolesMode) {
    // The dashboard user holds read and write, so it is an ordinary user who can chat; the
    // control must refuse the WhatsApp session by ownership, not for a missing scope.
    config.gateway.auth = {
      mode: "trusted-proxy",
      // Internal clients that do not come through the proxy use a password (host docs); the
      // harness's probe client uses it to read the genuine run's terminal record.
      password: token,
      identityScopes: { "dashboard-user@example.test": ["operator.read", "operator.write"] },
      trustedProxy: { userHeader: "x-forwarded-user", allowLoopback: true },
    };
    config.gateway.trustedProxies = ["127.0.0.1"];
    config.gateway.roles = {
      default: "dashboard",
      definitions: {
        dashboard: { sessions: { others: "none" }, agents: ["main"], scopes: ["operator.read", "operator.write"] },
      },
    };
  }
  const cfgPath = join(dirs.state, "openclaw.json");
  writeFileSync(cfgPath, JSON.stringify(config, null, 2));
  if (cloud) cloud.cfgPath = cfgPath;
  const profilePath = join(root, "sandbox.sb");
  writeFileSync(profilePath, sandboxProfile());

  const baseEnv = {
    PATH: process.env.PATH,
    HOME: dirs.home,
    TMPDIR: join(root, "cwd"),
    IDX_HARNESS_DIR: data,
  };
  const gwEnv = {
    ...baseEnv,
    OPENCLAW_HOME: dirs.home,
    OPENCLAW_STATE_DIR: dirs.state,
    OPENCLAW_CONFIG_PATH: cfgPath,
    OPENCLAW_NO_AUTO_UPDATE: "1",
    OPENCLAW_DISABLE_BONJOUR: "1",
    OPENCLAW_OFFLINE: "1",
    OPENCLAW_NO_RESPAWN: "1",
    DO_NOT_TRACK: "1",
  };
  // A path-loaded plugin has no install record, and the gateway starts only plugins in its
  // installed index, so link-install the harness plugin into the temporary state first.
  // `--link` copies nothing; `--force` confirms the local source noninteractively.
  const link = spawnSync(
    "/usr/bin/sandbox-exec",
    ["-f", profilePath, process.execPath, join(PKG, "openclaw.mjs"), "plugins", "install", "--link", join(HERE, "plugin"), "--force", "--accept-capabilities"],
    { cwd: dirs.cwd, env: gwEnv, encoding: "utf8", timeout: 120000 },
  );
  writeFileSync(join(data, "plugin-link.log"), `${link.stdout ?? ""}\n${link.stderr ?? ""}`);
  const cli = { profilePath, env: gwEnv, cwd: dirs.cwd };
  const configCli = cloud ? applyCloudBlockByCli(cli, cloud, cfgPath) : null;
  if (cloud) cloud.ownerBin = writeOwnerCli(join(root, "owner-bin"), cli);
  const model = spawn(process.execPath, [join(HERE, "fake-model.mjs")], {
    env: { ...baseEnv, IDX_FAKE_MODEL_PORT: String(modelPort) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const gwLog = [];
  /** Every gateway this run started; the finally block kills each one. */
  const gateways = [];
  const spawnGateway = () => {
    const child = spawn(
      "/usr/bin/sandbox-exec",
      ["-f", profilePath, process.execPath, join(PKG, "openclaw.mjs"), "gateway", "run", "--port", String(gwPort), "--bind", "loopback", ...(rolesMode ? [] : ["--auth", "token", "--token", token]), "--allow-unconfigured", "--verbose"],
      {
        cwd: dirs.cwd,
        env: gwEnv,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    child.stdout.on("data", (b) => gwLog.push(String(b)));
    child.stderr.on("data", (b) => gwLog.push(String(b)));
    gateways.push(child);
    return child;
  };
  let gw = spawnGateway();
  const result = { mode, root, pluginLink: { status: link.status }, openclawVersion: JSON.parse(readFileSync(join(PKG, "package.json"), "utf8")).version, steps: [] };
  const step = (s) => result.steps.push({ at: Date.now(), ...s });
  if (configCli) step({ configCli });
  let op;
  let probeOp;
  try {
    if (cloud && mode === "cloud-api-rollback") {
      await rollbackScenario({ cloud, data, modelPort, step, cli, gwRef: { get: () => gw, respawn: () => (gw = spawnGateway()) } });
      throw new CloudDone();
    }
    if (cloud) {
      await cloudScenario({ cloud, data, modelPort, gw, step });
      throw new CloudDone();
    }
    const started = await waitFor(() => readJsonl(join(data, "transport.jsonl")).find((e) => e.event === "started" || e.event === "register-threw"), 60000, 500);
    step({ channelStarted: Boolean(started) });
    if (!started) throw new Error("channel did not start");

    if (mode === "not-allowlisted") {
      // A DM from a sender outside channels.whatsapp.allowFrom must get nothing: no reply,
      // no model call, no tool call. Then the allowlisted peer still gets its card.
      await fetch(`http://127.0.0.1:${transportPort}/inbound`, {
        method: "POST",
        body: JSON.stringify({ peerId: STRANGER, text: "GENUINE-stranger please show me a 3 bed", messageId: "m-stranger" }),
      });
      await sleep(12000);
      step({ strangerWindowClosed: true });
    }

    // 1. genuine WhatsApp DM
    const tag = randomBytes(3).toString("hex");
    const ref = `genuine-${tag}`;
    await fetch(`http://127.0.0.1:${transportPort}/inbound`, {
      method: "POST",
      body: JSON.stringify({ peerId: PEER, text: `GENUINE-${tag} CASE=${GENUINE_CASE} please show me a 3 bed`, messageId: `m-${tag}` }),
    });
    const genuineCall = await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === ref), 60000);
    step({ genuineHook: genuineCall ?? null });
    if (!genuineCall) throw new Error("genuine card call never reached the hook");
    const held = await waitFor(async () => {
      const s = await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json();
      return s.held >= 1 ? s : null;
    }, 60000);
    step({ genuineHeldLive: Boolean(held) });

    // 2. dashboard replay of both live ids while the genuine run is held
    if (mode !== "genuine-only" && mode !== "not-allowlisted") {
      op = rolesMode
        ? new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, null, { "x-forwarded-user": "dashboard-user@example.test", "x-forwarded-for": "203.0.113.7", "x-forwarded-proto": "https", "x-forwarded-host": "dashboard.example.test" })
        : new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, { token });
      const hello = await op.open();
      step({ operatorConnect: { ok: hello.ok === true, error: hello.error ?? null } });
      // "interrupt-fresh" interrupts with a new idempotencyKey instead of the replayed run id,
      // to show whether cancelling the genuine reply needs the live ids at all.
      const fresh = mode === "interrupt-fresh" || rolesMode;
      const params = {
        sessionKey: genuineCall.sessionKey,
        message: "DASHBOARD replay: run the listing search",
        idempotencyKey: fresh ? `dash-${randomBytes(8).toString("hex")}` : genuineCall.eventRunId,
      };
      if (mode !== "default") params.queueMode = fresh ? "interrupt" : mode;
      if (hello.ok !== true) throw new Error(`operator connect refused: ${JSON.stringify(hello.error ?? null)}`);
      // Liveness at the moment of the replay, harness side: the fake model is still holding
      // the genuine run's second request, and nothing has reached the peer yet.
      const heldNow = await (await fetch(`http://127.0.0.1:${modelPort}/control/state`)).json();
      const peerOutBefore = readJsonl(join(data, "outbound.jsonl")).filter((o) => o.to === PEER).length;
      const sentAt = Date.now();
      step({ replaySent: { sentAt, modelHeld: heldNow.held, peerOutboundBefore: peerOutBefore } });
      const res = await op.req("chat.send", params);
      step({ chatSend: { params: { ...params }, ok: res.ok ?? null, payload: res.payload ?? null, error: res.error ?? null, timeout: res.timeout ?? false } });
      if (res.timeout) throw new Error("chat.send timed out");
      if (rolesMode) {
        // Positive control: the same user can still chat in a session of its own, so the
        // refusal above is about the WhatsApp session, not a user who cannot chat at all.
        const own = await op.req("chat.send", { sessionKey: `agent:main:dashboard:harness-${randomBytes(4).toString("hex")}`, message: "hello from the dashboard", idempotencyKey: `own-${randomBytes(6).toString("hex")}` });
        step({ ownSessionChatSend: { ok: own.ok ?? null, payload: own.payload ?? null, error: own.error ?? null, timeout: own.timeout ?? false } });
        // The other two cancel paths, with the live run id as a worst case (the user knows it).
        const ab = await op.req("chat.abort", { sessionKey: genuineCall.sessionKey, runId: genuineCall.eventRunId });
        step({ chatAbort: { ok: ab.ok ?? null, payload: ab.payload ?? null, error: ab.error ?? null, timeout: ab.timeout ?? false } });
        const sa = await op.req("sessions.abort", { key: genuineCall.sessionKey, runId: genuineCall.eventRunId });
        step({ sessionsAbort: { ok: sa.ok ?? null, payload: sa.payload ?? null, error: sa.error ?? null, timeout: sa.timeout ?? false } });
      }
      await sleep(4000);
    }

    // 3. release the hold, then wait for each piece of evidence with a deadline. A missing
    //    piece is recorded, never assumed: a timeout fails the check it belongs to.
    await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
    const genuineSent = await waitFor(() => readJsonl(join(data, "outbound.jsonl")).some((o) => o.to === PEER), 45000);
    step({ genuineOutboundSeen: Boolean(genuineSent) });
    if (mode !== "genuine-only" && mode !== "not-allowlisted") {
      const cs = result.steps.find((x) => x.chatSend)?.chatSend;
      const hostRejected = cs?.ok === false;
      // Replay evidence: an explicit host rejection, or the hook recording a decision on
      // the replay's own card call. Either way, wait for the replayed run to settle too.
      const replayHook = hostRejected
        ? null
        : await waitFor(() => readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === REPLAY_REF), 60000);
      step({ replayEvidence: { hostRejected, replayHookSeen: Boolean(replayHook) } });
    }
    await sleep(5000); // let a replay tool call that slipped through reach the execution log
    if (mode === "payloads") {
      // One genuine turn per committed real-server payload case, each after the previous one
      // settled (one active turn per peer): the peer must receive exactly the renderer's reply.
      const sweep = [];
      // IDX_HARNESS_CASES (comma-separated) narrows the sweep for diagnosis; P then fails,
      // because it requires every case.
      const only = (process.env.IDX_HARNESS_CASES ?? "").split(",").filter(Boolean);
      for (const caseName of [...PAYLOAD_CASES, ...WITHHELD_PAYLOAD_CASES].filter((c) => only.length === 0 || only.includes(c))) {
        const before = readJsonl(join(data, "outbound.jsonl")).filter((o) => o.to === PEER).length;
        const t2 = randomBytes(3).toString("hex");
        const text = `GENUINE-${t2} CASE=${caseName} payload sweep`;
        await fetch(`http://127.0.0.1:${transportPort}/inbound`, { method: "POST", body: JSON.stringify({ peerId: PEER, text, messageId: `m-${t2}` }) });
        const got = await waitFor(() => {
          const out = readJsonl(join(data, "outbound.jsonl")).filter((o) => o.to === PEER);
          return out.length > before ? out[before] : null;
        }, 45000);
        await waitFor(() => readJsonl(join(data, "inbound.jsonl")).some((e) => e.settled === text || e.failed === text), 30000);
        const after = readJsonl(join(data, "after-hook.jsonl")).find((a) => a.ref === `genuine-${t2}`);
        const withheldCase = WITHHELD_PAYLOAD_CASES.includes(caseName);
        const expected = withheldCase ? SAFE_TEXT : expectedReplyFor(caseName);
        const approved = serverApprovedFor(caseName);
        sweep.push({
          case: caseName,
          withheldCase,
          delivered: got?.text ?? null,
          expected,
          approved,
          // exact: equals the channel renderer's output AND the server's own approved reply.
          exact: got !== null && expected !== null && got.text === expected && got.text === approved,
          hostBlockEqualsPayload: hostFaithful(after, loadPayload(caseName).result.content[0].text),
        });
      }
      step({ payloadSweep: sweep });
    }
    // Host-side records, read by an operator that can see every run (a shared-token client;
    // in interrupt-roles an internal password client, since the dashboard role cannot see
    // the WhatsApp run). agent.wait with timeoutMs 0 answers "timeout" for a live run AND
    // for an id never issued, so it is never read as liveness; the terminal record's
    // startedAt/endedAt are.
    if (mode !== "genuine-only") {
      probeOp = new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, rolesMode ? { password: token } : { token });
      const ph = await probeOp.open();
      if (ph.ok !== true) throw new Error(`probe operator connect refused: ${JSON.stringify(ph.error ?? null)}`);
      const gw = await probeOp.req("agent.wait", { runId: genuineCall.eventRunId, timeoutMs: 30000 }, 40000);
      step({ genuineTerminal: { ok: gw.ok ?? null, payload: gw.payload ? { status: gw.payload.status, startedAt: gw.payload.startedAt, endedAt: gw.payload.endedAt, stopReason: gw.payload.stopReason } : null, error: gw.error ?? null, timeout: gw.timeout ?? false } });
      const replayHook = readJsonl(join(data, "hook.jsonl")).find((h) => h.params?.ref === REPLAY_REF);
      if (replayHook?.eventRunId) {
        const rw = await probeOp.req("agent.wait", { runId: replayHook.eventRunId, timeoutMs: 30000 }, 40000);
        step({ replayTerminal: { runId: replayHook.eventRunId, ok: rw.ok ?? null, payload: rw.payload ? { status: rw.payload.status, startedAt: rw.payload.startedAt, endedAt: rw.payload.endedAt } : null, error: rw.error ?? null, timeout: rw.timeout ?? false } });
      }
    }
  } catch (e) {
    if (!(e instanceof CloudDone)) step({ error: String(e?.message ?? e) });
  } finally {
    op?.close();
    probeOp?.close();
    for (const g of gateways) g.kill("SIGTERM");
    model.kill("SIGTERM");
    await sleep(1500);
    for (const g of gateways) {
      try {
        g.kill("SIGKILL");
      } catch {}
    }
    // The synthetic credentials file and its directory never outlive the run.
    if (cloud) rmSync(cloud.dir, { recursive: true, force: true });
  }

  writeFileSync(join(data, "gateway.log"), gwLog.join(""));
  const outbound = readJsonl(join(data, "outbound.jsonl"));
  const toolExec = readJsonl(join(data, "tool-exec.jsonl"));
  const hooks = readJsonl(join(data, "hook.jsonl"));
  const modelReqs = readJsonl(join(data, "model-requests.jsonl"));
  const genuineRef = result.steps.find((s) => s.genuineHook)?.genuineHook?.params?.ref;
  // The expected bytes come from the channel's own renderer applied to the result the fake
  // server returned, so A checks the production capture, store and resolver end to end.
  const expectedCard = genuineRef ? expectedReplyFor(GENUINE_CASE) : null;
  const toPeer = outbound.filter((o) => o.to === PEER);
  result.evidence = {
    outbound: outbound.map((o) => ({ to: o.to, text: o.text })),
    toolExec,
    hooks: hooks.map((h) => ({ toolName: h.toolName, ref: h.params?.ref, eventRunId: h.eventRunId, ctxRunId: h.ctxRunId, sessionKey: h.sessionKey, requester: h.requester, decision: h.decision })),
    modelRequests: modelReqs.map((m) => ({ marker: m.marker, roles: m.roles, action: m.action, hold: m.hold, hasReplyInstruction: m.hasReplyInstruction, case: m.case })),
    operatorEvents: op ? op.events.slice(0, 60) : [],
    gatewayLogTail: gwLog.join("").split("\n").filter((l) => /error|warn|idx-whatsapp|whatsapp|denied|sandbox/iu.test(l)).slice(-40),
  };
  // Mode cloud-api: what reached the fake Graph API is the outbound. A requires every send to
  // the peer to be the expected reply (the genuine turn's and, after the reload, the next
  // turn's; the held turn's late reply must not be there at all).
  const graph = readJsonl(join(data, "graph.jsonl"));
  const graphOutbound = graph
    .map((g) => {
      try {
        const b = JSON.parse(String(g.body));
        return { to: `+${b.to}`, text: b.text?.body ?? null };
      } catch {
        return { to: null, text: null };
      }
    });
  if (cloud) result.evidence.graph = graph.map((g) => ({ at: g.at, url: g.url, method: g.method, redirect: g.redirect, hasSignal: g.hasSignal, moduleCopy: g.moduleCopy, body: g.body }));
  // In the payload sweep A judges the first genuine turn; the sweep is judged by P below.
  const evalOutbound = mode === "payloads" ? outbound.filter((o) => o.to === PEER).slice(0, 1) : cloud ? graphOutbound : outbound;
  const evaluated = evaluate({ mode, steps: result.steps, outbound: evalOutbound, toolExec, hooks, expectedCard, genuineRef, peer: PEER, safeText: SAFE_TEXT, replayRef: REPLAY_REF });
  result.checks = evaluated.checks;
  result.genuineReply = evaluated.genuineReply;
  // not-allowlisted: the stranger's DM produced nothing at all.
  const D =
    mode === "not-allowlisted"
      ? (() => {
          const strangerOut = outbound.filter((o) => o.to === STRANGER).length;
          const strangerModel = modelReqs.filter((m) => m.marker === "GENUINE-stranger").length;
          const strangerHooks = hooks.filter((h) => String(h.params?.ref ?? "").includes("stranger")).length;
          return { pass: strangerOut === 0 && strangerModel === 0 && strangerHooks === 0, strangerOutbound: strangerOut, strangerModelRequests: strangerModel, strangerHookCalls: strangerHooks };
        })()
      : null;
  result.checks.D = D;
  // I: the channel's token instruction reached every genuine WhatsApp model request and no
  // dashboard model request.
  const genuineReqs = modelReqs.filter((m) => String(m.marker).startsWith("GENUINE-") && m.marker !== "GENUINE-stranger");
  const dashReqs = modelReqs.filter((m) => m.marker === "DASHBOARD");
  const I = {
    pass: genuineReqs.length > 0 && genuineReqs.every((m) => m.hasReplyInstruction === true) && dashReqs.every((m) => m.hasReplyInstruction !== true),
    genuineRequests: genuineReqs.length,
    genuineWithInstruction: genuineReqs.filter((m) => m.hasReplyInstruction === true).length,
    dashboardRequests: dashReqs.length,
    dashboardWithInstruction: dashReqs.filter((m) => m.hasReplyInstruction === true).length,
  };
  result.checks.I = I;
  // P: every real-server payload case reached the peer as exactly the renderer's reply, and
  // the host handed the channel the payload's own labelled block unchanged.
  const sweep = result.steps.find((x) => x.payloadSweep)?.payloadSweep ?? null;
  const P =
    mode === "payloads"
      ? {
          pass: Array.isArray(sweep) && sweep.length === PAYLOAD_CASES.length + WITHHELD_PAYLOAD_CASES.length && sweep.every((x) => x.exact && x.hostBlockEqualsPayload),
          released: sweep?.filter((x) => !x.withheldCase && x.exact).length ?? 0,
          withheldAsExpected: sweep?.filter((x) => x.withheldCase && x.exact).length ?? 0,
          cases: sweep?.map((x) => ({ case: x.case, withheldCase: x.withheldCase, exact: x.exact, hostBlockEqualsPayload: x.hostBlockEqualsPayload })) ?? [],
        }
      : null;
  result.checks.P = P;
  const cloudEval = cloud && mode === "cloud-api"
    ? evaluateCloudApi({
        steps: result.steps,
        graph,
        modelRequests: modelReqs,
        hooks,
        toolExec,
        expected: {
          url: `https://graph.facebook.com/${cloud.creds.graphApiVersion}/${cloud.creds.phoneNumberId}/messages`,
          authorization: `Bearer ${cloud.creds.accessToken}`,
          peerWa: PEER_WA,
          approved: serverApprovedFor(GENUINE_CASE),
          rendered: expectedReplyFor(GENUINE_CASE),
        },
        markers: cloud.markers ?? { unsigned: "none", tampered: "none", stranger: "GENUINE-stranger" },
        genuineRef,
        refusals: readJsonl(join(data, "audit.jsonl")).filter((a) => a.event === "cloud-api-refused").map((a) => a.reason),
      })
    : null;
  if (cloudEval) Object.assign(result.checks, cloudEval.checks);
  const rollbackEval = cloud && mode === "cloud-api-rollback" ? evaluateCloudRollback({ steps: result.steps, graph, modelRequests: modelReqs, hooks, toolExec }) : null;
  if (rollbackEval) Object.assign(result.checks, rollbackEval.checks);
  const K = cloud ? evaluateConfigCli(configCli) : null;
  result.checks.K = K;
  const O = cloud ? evaluateOwnerChecks({ mode, steps: result.steps }) : null;
  result.checks.O = O;
  result.pass =
    evaluated.pass && (D === null || D.pass) && I.pass && (P === null || P.pass) && (cloudEval === null || cloudEval.pass) &&
    (rollbackEval === null || rollbackEval.pass) && (K === null || K.pass) && (O === null || O.pass);
  writeFileSync(join(data, "result.json"), JSON.stringify(result, null, 2));
  return result;
}

const modes = process.argv.slice(2).length ? process.argv.slice(2) : ["genuine-only", "default", "followup", "interrupt"];
let allPass = true;
for (const m of modes) {
  const r = await runMode(m);
  allPass &&= r.pass;
  process.stdout.write(JSON.stringify(r) + "\n");
}
process.exit(allPass ? 0 : 1);
