/**
 * Harness plugin for the real-host replay test. It is the production entry factory
 * (`createPluginEntry` from ../../index.mjs) with two harness parts swapped in:
 *   - a fake transport: a loopback HTTP control port (POST /inbound injects a WhatsApp DM)
 *     and an outbound log of every `sendText` the channel's gate makes;
 *   - a card resolver that reads the cards the fake `idx` MCP server stored.
 * It also records, for evidence, every before_tool_call the production handler decides
 * (tool name, run ids, session key, requester, decision) by wrapping `api.on` for the
 * production registration only. Synthetic data only; files go to $IDX_HARNESS_DIR.
 */
import { appendFileSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { createPluginEntry } from "../../index.mjs";

// Set from the plugin's own config at register time (plugins.entries.<id>.config), since
// the host does not promise a plugin the gateway process environment.
let DIR = process.env.IDX_HARNESS_DIR ?? "";
let TRANSPORT_PORT = Number(process.env.IDX_HARNESS_TRANSPORT_PORT ?? 0);
const log = (file, obj) => {
  if (!DIR) return;
  try {
    appendFileSync(join(DIR, file), JSON.stringify({ at: Date.now(), ...obj }) + "\n");
  } catch {}
};

let sendCount = 0;
const MODULE_COPY = Math.random().toString(36).slice(2, 8); // evidence: which loaded copy logged
const fakeTransport = {
  isConfigured: () => true,
  async start({ accountId, signal, onInbound }) {
    const server = createServer((req, res) => {
      if (req.method !== "POST" || req.url !== "/inbound") {
        res.writeHead(404);
        res.end();
        return;
      }
      let raw = "";
      req.setEncoding("utf8");
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        let msg = {};
        try {
          msg = JSON.parse(raw);
        } catch {}
        const inbound = {
          accountId,
          peerId: String(msg.peerId ?? ""),
          text: String(msg.text ?? ""),
          messageId: String(msg.messageId ?? `harness-${Date.now()}`),
          receivedAt: Date.now(),
        };
        log("inbound.jsonl", { peerId: inbound.peerId, text: inbound.text });
        res.writeHead(202, { "content-type": "application/json" });
        res.end(JSON.stringify({ accepted: true }));
        Promise.resolve()
          .then(() => onInbound(inbound))
          .then(
            () => log("inbound.jsonl", { settled: inbound.text }),
            (e) => log("inbound.jsonl", { failed: inbound.text, error: String(e?.message ?? e) }),
          );
      });
    });
    await new Promise((resolve) => server.listen(TRANSPORT_PORT, "127.0.0.1", resolve));
    log("transport.jsonl", { event: "started", port: TRANSPORT_PORT, moduleCopy: MODULE_COPY });
    // The host restarts a channel whose startAccount returns, so stay pending until abort.
    await new Promise((resolve) => {
      if (signal?.aborted) return resolve();
      signal?.addEventListener("abort", () => resolve(), { once: true });
    });
    await new Promise((resolve) => server.close(() => resolve()));
  },
  async sendText({ accountId, to, text }) {
    const messageId = `harness-out-${++sendCount}`;
    log("outbound.jsonl", { accountId, to, text, messageId });
    return { messageId };
  },
  async stop() {},
};

const fileCardResolver = {
  resolve(ref) {
    try {
      const cards = JSON.parse(readFileSync(join(DIR, "cards.json"), "utf8"));
      const text = cards[ref];
      return typeof text === "string" && text !== "" ? { text } : null;
    } catch {
      return null;
    }
  },
};

const inner = createPluginEntry({ transport: fakeTransport, cardResolver: fileCardResolver });

function observed(handler) {
  return async (event, ctx) => {
    const seen = {
      toolName: event?.toolName,
      eventRunId: event?.runId,
      toolCallId: event?.toolCallId,
      ctxRunId: ctx?.runId,
      sessionKey: ctx?.sessionKey,
      channelId: ctx?.channelId,
      requester: ctx?.requester === undefined ? "absent" : ctx.requester,
      params: event?.params,
    };
    const decision = await handler(event, ctx);
    log("hook.jsonl", { ...seen, decision, moduleCopy: MODULE_COPY });
    return decision;
  };
}

export default {
  ...inner,
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: { harnessDir: { type: "string" }, transportPort: { type: "integer" } },
  },
  register(api) {
    const pc = api?.pluginConfig ?? {};
    if (typeof pc.harnessDir === "string" && pc.harnessDir !== "") DIR = pc.harnessDir;
    if (Number.isInteger(pc.transportPort)) TRANSPORT_PORT = pc.transportPort;
    // Evidence only: record the run id the channel hands the host and every id the host
    // reports back through onAgentRunStart. Nothing here changes a value.
    const rt = api?.runtime;
    const reply = rt?.channel?.reply;
    const runtimeView =
      reply && typeof reply.dispatchReplyWithBufferedBlockDispatcher === "function"
        ? {
            ...rt,
            channel: {
              ...rt.channel,
              reply: {
                ...reply,
                dispatchReplyWithBufferedBlockDispatcher: (args) => {
                  const ro = args?.replyOptions;
                  log("dispatch.jsonl", { event: "dispatch", issuedRunId: ro?.runId, sessionKey: args?.ctx?.SessionKey });
                  const orig = ro?.onAgentRunStart;
                  const replyOptions =
                    typeof orig === "function"
                      ? { ...ro, onAgentRunStart: (id, ...rest) => { log("dispatch.jsonl", { event: "onAgentRunStart", hostRunId: id, issuedRunId: ro.runId }); return orig(id, ...rest); } }
                      : ro;
                  return reply.dispatchReplyWithBufferedBlockDispatcher({ ...args, replyOptions });
                },
              },
            },
          }
        : rt;
    const wrapped = new Proxy(api, {
      get(target, prop, receiver) {
        if (prop === "runtime") return runtimeView;
        if (prop === "on") {
          return (name, handler, opts) => target.on(name, name === "before_tool_call" ? observed(handler) : handler, opts);
        }
        const v = Reflect.get(target, prop, receiver);
        return typeof v === "function" ? v.bind(target) : v;
      },
    });
    log("transport.jsonl", {
      event: "register-called",
      moduleCopy: MODULE_COPY,
      mode: api?.registrationMode ?? null,
      denySeen: Array.isArray(api?.config?.plugins?.deny) ? api.config.plugins.deny : null,
    });
    try {
      inner.register(wrapped);
    } catch (e) {
      log("transport.jsonl", { event: "register-threw", error: String(e?.message ?? e) });
      throw e;
    }
    log("transport.jsonl", { event: "registered", hasRuntime: Boolean(api?.runtime?.channel), hasOn: typeof api?.on === "function" });
  },
};
