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
 * Usage: node run.mjs [mode ...]   modes: genuine-only, default, steer, followup, collect, interrupt
 * Prints one JSON result per mode and exits 0 when every requested mode passes A, B, C.
 */
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, realpathSync } from "node:fs";
import { createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { cardTextFor } from "./cards.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = process.env.OPENCLAW_PKG ?? join(homedir(), ".npm-global/lib/node_modules/openclaw");
const PEER = "+15555550101";
const SAFE_TEXT = "I couldn't send that reply safely. Please ask again.";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

class Operator {
  constructor(url, token) {
    this.url = url;
    this.token = token;
    this.pending = new Map();
    this.events = [];
    this.n = 0;
  }
  async open() {
    this.ws = new WebSocket(this.url);
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
      auth: { token: this.token },
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

async function runMode(mode) {
  const root = realpathSync(mkdtempSync(join(process.env.IDX_HARNESS_ROOT ?? tmpdir(), `idx-replay-${mode}-`)));
  const dirs = Object.fromEntries(["home", "state", "cwd", "ws", "data"].map((k) => [k, join(root, k)]));
  for (const d of Object.values(dirs)) mkdirSync(d, { recursive: true });
  const data = dirs.data;
  const [gwPort, modelPort, transportPort] = [await freePort(), await freePort(), await freePort()];
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
      entries: { "idx-whatsapp-channel": { enabled: true, config: { harnessDir: data, transportPort } } },
    },
    channels: { whatsapp: { enabled: true } },
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
  const cfgPath = join(dirs.state, "openclaw.json");
  writeFileSync(cfgPath, JSON.stringify(config, null, 2));
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
  const model = spawn(process.execPath, [join(HERE, "fake-model.mjs")], {
    env: { ...baseEnv, IDX_FAKE_MODEL_PORT: String(modelPort) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const gwLog = [];
  const gw = spawn(
    "/usr/bin/sandbox-exec",
    ["-f", profilePath, process.execPath, join(PKG, "openclaw.mjs"), "gateway", "run", "--port", String(gwPort), "--bind", "loopback", "--auth", "token", "--token", token, "--allow-unconfigured", "--verbose"],
    {
      cwd: dirs.cwd,
      env: gwEnv,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  gw.stdout.on("data", (b) => gwLog.push(String(b)));
  gw.stderr.on("data", (b) => gwLog.push(String(b)));
  const result = { mode, root, pluginLink: { status: link.status }, openclawVersion: JSON.parse(readFileSync(join(PKG, "package.json"), "utf8")).version, steps: [] };
  const step = (s) => result.steps.push({ at: Date.now(), ...s });
  let op;
  try {
    const started = await waitFor(() => readJsonl(join(data, "transport.jsonl")).find((e) => e.event === "started" || e.event === "register-threw"), 60000, 500);
    step({ channelStarted: Boolean(started) });
    if (!started) throw new Error("channel did not start");

    // 1. genuine WhatsApp DM
    const tag = randomBytes(3).toString("hex");
    const ref = `genuine-${tag}`;
    await fetch(`http://127.0.0.1:${transportPort}/inbound`, {
      method: "POST",
      body: JSON.stringify({ peerId: PEER, text: `GENUINE-${tag} please show me a 3 bed`, messageId: `m-${tag}` }),
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
    if (mode !== "genuine-only") {
      op = new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, token);
      const hello = await op.open();
      step({ operatorConnect: { ok: hello.ok === true, error: hello.error ?? null } });
      const params = { sessionKey: genuineCall.sessionKey, message: "DASHBOARD replay: run the listing search", idempotencyKey: genuineCall.eventRunId };
      if (mode !== "default") params.queueMode = mode;
      const res = await op.req("chat.send", params);
      step({ chatSend: { params: { ...params }, ok: res.ok ?? null, payload: res.payload ?? null, error: res.error ?? null, timeout: res.timeout ?? false } });
      await sleep(4000);
    }

    // 3. release the hold and let everything settle
    await fetch(`http://127.0.0.1:${modelPort}/control/release`, { method: "POST" });
    await waitFor(() => readJsonl(join(data, "outbound.jsonl")).some((o) => o.to === PEER), 45000);
    await sleep(8000); // let a queued or steered dashboard turn run and settle
  } catch (e) {
    step({ error: String(e?.message ?? e) });
  } finally {
    op?.close();
    gw.kill("SIGTERM");
    model.kill("SIGTERM");
    await sleep(1500);
    try {
      gw.kill("SIGKILL");
    } catch {}
  }

  writeFileSync(join(data, "gateway.log"), gwLog.join(""));
  const outbound = readJsonl(join(data, "outbound.jsonl"));
  const toolExec = readJsonl(join(data, "tool-exec.jsonl"));
  const hooks = readJsonl(join(data, "hook.jsonl"));
  const modelReqs = readJsonl(join(data, "model-requests.jsonl"));
  const genuineRef = result.steps.find((s) => s.genuineHook)?.genuineHook?.params?.ref;
  const expectedCard = genuineRef ? cardTextFor(genuineRef) : null;
  const toPeer = outbound.filter((o) => o.to === PEER);
  result.evidence = {
    outbound: outbound.map((o) => ({ to: o.to, text: o.text })),
    toolExec,
    hooks: hooks.map((h) => ({ toolName: h.toolName, ref: h.params?.ref, eventRunId: h.eventRunId, ctxRunId: h.ctxRunId, sessionKey: h.sessionKey, requester: h.requester, decision: h.decision })),
    modelRequests: modelReqs.map((m) => ({ marker: m.marker, roles: m.roles, action: m.action, hold: m.hold })),
    operatorEvents: op ? op.events.slice(0, 60) : [],
    gatewayLogTail: gwLog.join("").split("\n").filter((l) => /error|warn|idx-whatsapp|whatsapp|denied|sandbox/iu.test(l)).slice(-40),
  };
  const replayExec = toolExec.filter((t) => t.ref !== genuineRef);
  result.checks = {
    A_genuineCardDeliveredExactly: Boolean(expectedCard) && toPeer.length >= 1 && toPeer[0].text === expectedCard,
    B_replayDidNotExecuteTool: mode === "genuine-only" ? null : replayExec.length === 0,
    C_replayDidNotSuppressGenuineReply:
      mode === "genuine-only" ? null : Boolean(expectedCard) && toPeer.some((o) => o.text === expectedCard) && !toPeer.some((o) => o.text === SAFE_TEXT),
  };
  result.pass = Object.values(result.checks).every((v) => v === null || v === true);
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
