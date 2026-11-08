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
 *        not-allowlisted (a DM from a sender outside allowFrom gets nothing; the peer still does)
 * Prints one JSON result per mode and exits 0 when every requested mode passes A, B, C.
 */
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, realpathSync } from "node:fs";
import { createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { listingResultFor } from "./cards.mjs";
import { renderCards } from "../card-render.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = process.env.OPENCLAW_PKG ?? join(homedir(), ".npm-global/lib/node_modules/openclaw");
const PEER = "+15555550101";
/** A synthetic sender that is not on the harness allowlist. */
const STRANGER = "+15555550199";
const SAFE_TEXT = "I couldn't send that reply safely. Please ask again.";
/** The card ref the fake model's dashboard script requests (fake-model.mjs). */
const REPLAY_REF = "dashboard-1";
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
  constructor(url, token, headers) {
    this.url = url;
    this.token = token;
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
      ...(this.token ? { auth: { token: this.token } } : {}),
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
    ["-f", profilePath, process.execPath, join(PKG, "openclaw.mjs"), "gateway", "run", "--port", String(gwPort), "--bind", "loopback", ...(rolesMode ? [] : ["--auth", "token", "--token", token]), "--allow-unconfigured", "--verbose"],
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
    if (mode !== "genuine-only" && mode !== "not-allowlisted") {
      op = rolesMode
        ? new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, null, { "x-forwarded-user": "dashboard-user@example.test", "x-forwarded-for": "203.0.113.7", "x-forwarded-proto": "https", "x-forwarded-host": "dashboard.example.test" })
        : new Operator(`ws://127.0.0.1:${gwPort}/gateway/ws`, token);
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
  // The expected bytes come from the channel's own renderer applied to the result the fake
  // server returned, so A checks the production capture, store and resolver end to end.
  const expectedCard = genuineRef ? renderCards("idx__search_listings", listingResultFor(genuineRef))[0]?.text ?? null : null;
  const toPeer = outbound.filter((o) => o.to === PEER);
  result.evidence = {
    outbound: outbound.map((o) => ({ to: o.to, text: o.text })),
    toolExec,
    hooks: hooks.map((h) => ({ toolName: h.toolName, ref: h.params?.ref, eventRunId: h.eventRunId, ctxRunId: h.ctxRunId, sessionKey: h.sessionKey, requester: h.requester, decision: h.decision })),
    modelRequests: modelReqs.map((m) => ({ marker: m.marker, roles: m.roles, action: m.action, hold: m.hold })),
    operatorEvents: op ? op.events.slice(0, 60) : [],
    gatewayLogTail: gwLog.join("").split("\n").filter((l) => /error|warn|idx-whatsapp|whatsapp|denied|sandbox/iu.test(l)).slice(-40),
  };
  // Check A: the genuine card call was admitted, the tool ran exactly once for it, and
  // the peer received exactly the stored card bytes.
  const genuineHooks = hooks.filter((h) => h.params?.ref === genuineRef);
  const genuineExec = toolExec.filter((t) => t.ref === genuineRef);
  const cardDelivered = Boolean(expectedCard) && toPeer.some((o) => o.text === expectedCard);
  const A = {
    pass: Boolean(expectedCard) && genuineHooks.some((h) => h.decision?.block === false && h.decision?.marked === 1) && genuineExec.length === 1 && cardDelivered && !toPeer.some((o) => o.text !== expectedCard),
    admitted: genuineHooks.some((h) => h.decision?.block === false && h.decision?.marked === 1),
    genuineExecutions: genuineExec.length,
    cardDelivered,
  };
  // Check B: zero replay executions AND positive evidence the replay was stopped: an
  // explicit host rejection of the chat.send, or a recorded hook refusal of the replay's
  // own card call. No evidence (timeout, the replay never reached a tool) is a failure.
  const cs = result.steps.find((x) => x.chatSend)?.chatSend ?? null;
  const replayExec = toolExec.filter((t) => t.ref !== genuineRef);
  const replayHooks = hooks.filter((h) => h.params?.ref === REPLAY_REF);
  const hostRejected = cs?.ok === false;
  const hookRefused = replayHooks.length > 0 && replayHooks.every((h) => h.decision?.block === true);
  const B =
    mode === "genuine-only" || mode === "not-allowlisted"
      ? null
      : {
          pass: replayExec.length === 0 && (hostRejected || hookRefused),
          replayExecutions: replayExec.length,
          evidence: hostRejected ? "host-rejected" : hookRefused ? "hook-refused" : replayHooks.length ? "hook-admitted" : "none",
          hookReasons: replayHooks.map((h) => h.decision?.reason ?? (h.decision?.block === false ? "admitted" : "unknown")),
        };
  // Check C: the genuine reply reached the peer and was not replaced by SAFE_TEXT. When the
  // host reports it interrupted the genuine run and nothing reached the peer, the outcome
  // is named "cancelled-by-interrupt" so the case stays visible as a cancelled reply.
  const interrupted = cs?.payload?.interruptedActiveRun === true;
  const genuineReply = cardDelivered ? "delivered" : toPeer.some((o) => o.text === SAFE_TEXT) ? "replaced-by-safe-text" : interrupted && toPeer.length === 0 ? "cancelled-by-interrupt" : "missing";
  const C = mode === "genuine-only" || mode === "not-allowlisted" ? null : { pass: genuineReply === "delivered" && !toPeer.some((o) => o.text === SAFE_TEXT), genuineReply, interruptedActiveRun: interrupted };
  // interrupt-roles also requires the other cancel paths to be rejected and the user to
  // still be able to chat in its own session (positive control).
  if (mode === "interrupt-roles" && C) {
    const st = (k) => result.steps.find((x) => x[k])?.[k];
    C.otherCancelPathsRejected = st("chatAbort")?.ok === false && st("sessionsAbort")?.ok === false;
    C.ownSessionChatAllowed = st("ownSessionChatSend")?.ok === true;
    C.pass = C.pass && C.otherCancelPathsRejected && C.ownSessionChatAllowed;
  }
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
  result.checks = { A, B, C, D };
  result.genuineReply = genuineReply;
  result.pass = A.pass && (B === null || B.pass) && (C === null || C.pass) && (D === null || D.pass);
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
