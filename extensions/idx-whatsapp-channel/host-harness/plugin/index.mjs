/**
 * Harness plugin for the real-host replay test. It is the production entry factory
 * (`createPluginEntry` from ../../index.mjs) with one harness part swapped in:
 *   - every mode but cloud-api: a fake transport, a loopback HTTP control port (POST
 *     /inbound injects a WhatsApp DM) and an outbound log of every `sendText` the
 *     channel's gate makes;
 *   - mode cloud-api (WO-039; the plugin config carries an enabled `cloudApi` block): NO
 *     fake transport. The production Cloud API wiring runs as shipped (the owner-file
 *     reader, the process transport, the loopback webhook listener bound when the account
 *     starts), and only the Graph API `fetch` is a fake (`cloudApiDeps.fetch`) that records
 *     every request to graph.jsonl and answers like Meta (`messages[0].id`). It never
 *     calls any network;
 *   - nothing else: the production card resolver and card capture are used as shipped.
 * It also records, for evidence, every before_tool_call the production handler decides
 * (tool name, run ids, session key, requester, decision) by wrapping `api.on` for the
 * production registration only. Synthetic data only; files go to $IDX_HARNESS_DIR.
 */
import { appendFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { createPluginEntry } from "../../index.mjs";
import { renderToolSection } from "../../reply-render.mjs";

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

/**
 * The fake Graph API for mode cloud-api: records each request (synthetic token, synthetic
 * recipient) and answers 200 with a Meta-shaped body. No network is ever touched.
 * @param {unknown} url @param {any} init
 */
let graphCount = 0;
async function fakeGraphFetch(url, init) {
  const n = ++graphCount;
  let to = null;
  try {
    to = JSON.parse(String(init?.body)).to ?? null;
  } catch {}
  log("graph.jsonl", {
    n,
    moduleCopy: MODULE_COPY,
    url: String(url),
    method: init?.method ?? null,
    headers: init?.headers && typeof init.headers === "object" ? { ...init.headers } : null,
    redirect: init?.redirect ?? null,
    hasSignal: init?.signal instanceof AbortSignal,
    body: typeof init?.body === "string" ? init.body : null,
  });
  return new Response(JSON.stringify({ messaging_product: "whatsapp", contacts: [{ input: to, wa_id: to }], messages: [{ id: `wamid.HARNESS-${MODULE_COPY}-${n}` }] }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

// The production card resolver (the channel's own turn-bound store) is used: no injection.
const inner = createPluginEntry({ transport: fakeTransport });
// Mode cloud-api: the production send path from the plugin's own cloudApi block; only fetch is fake.
const cloudInner = createPluginEntry({ cloudApiDeps: { fetch: fakeGraphFetch } });

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

/** Evidence for runbook C10: each before_prompt_build call, its run, and what we returned. */
function observedPrompt(handler) {
  return async (event, ctx) => {
    const out = await handler(event, ctx);
    log("prompt-hook.jsonl", {
      runId: ctx?.runId,
      sessionKey: ctx?.sessionKey,
      eventKeys: event && typeof event === "object" ? Object.keys(event) : typeof event,
      returned: out && typeof out === "object" ? Object.keys(out) : out === undefined ? "undefined" : typeof out,
      moduleCopy: MODULE_COPY,
    });
    return out;
  };
}

/** Evidence for runbook C9: the shape of each after_tool_call event (types, not values). */
function observedAfter(handler) {
  return async (event, ctx) => {
    const r = event?.result;
    log("after-hook.jsonl", {
      toolName: event?.toolName,
      runId: event?.runId,
      toolCallId: event?.toolCallId,
      ctxRunId: ctx?.runId,
      sessionKey: ctx?.sessionKey,
      hasError: event?.error !== undefined,
      resultKeys: r && typeof r === "object" ? Object.keys(r) : typeof r,
      contentTypes: Array.isArray(r?.content) ? r.content.map((c) => c?.type) : null,
      // Harness data is synthetic; the heads show how the host shaped the result.
      contentHeads: Array.isArray(r?.content) ? r.content.map((c) => (typeof c?.text === "string" ? c.text.slice(0, 120) : null)) : null,
      // Synthetic payloads only: the full first block, to compare with the committed payload.
      contentText: Array.isArray(r?.content) && typeof r.content[0]?.text === "string" ? r.content[0].text.slice(0, 20000) : null,
      ref: event?.params?.ref ?? null,
      // Evidence: whether the host's details carry the full structured result and its source.
      detailsServer: r?.details?.mcpServer ?? null,
      detailsTool: r?.details?.mcpTool ?? null,
      detailsStructuredJson: r?.details?.structuredContent && typeof r.details.structuredContent === "object" ? JSON.stringify(r.details.structuredContent) : null,
      detailsKeys: r?.details && typeof r.details === "object" ? Object.keys(r.details) : typeof r?.details,
      errorType: typeof event?.error,
      errorValue: typeof event?.error === "string" ? event.error.slice(0, 80) : event?.error === undefined ? "undefined" : JSON.stringify(event?.error)?.slice(0, 80),
      rendersSection: renderToolSection(event?.toolName, r, event?.error) !== null,
      moduleCopy: MODULE_COPY,
    });
    return handler(event, ctx);
  };
}

export default {
  ...inner,
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: { harnessDir: { type: "string" }, transportPort: { type: "integer" }, cloudApi: inner.configSchema.properties.cloudApi },
  },
  register(api) {
    const pc = api?.pluginConfig ?? {};
    if (typeof pc.harnessDir === "string" && pc.harnessDir !== "") DIR = pc.harnessDir;
    if (Number.isInteger(pc.transportPort)) TRANSPORT_PORT = pc.transportPort;
    // The production entry sees only its own config: the cloudApi block, when the run has one.
    const cloudMode = pc.cloudApi !== undefined;
    const prodConfig = cloudMode ? { cloudApi: pc.cloudApi } : {};
    const chosen = cloudMode ? cloudInner : inner;
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
        if (prop === "pluginConfig") return prodConfig;
        if (prop === "logger") {
          // Evidence: the channel's structured audit lines (they carry no text and no peer).
          const base = target.logger;
          const tee = (level) => (m, ...rest) => {
            if (m && typeof m === "object") log("audit.jsonl", { level, ...m });
            // The entry's host-safe logger sends the same fields as one JSON line once the
            // host refuses an object (OpenClaw 2026.9.5 does); record those lines too.
            else if (typeof m === "string" && m.startsWith("{\"component\":")) {
              try {
                log("audit.jsonl", { level, asJsonLine: true, ...JSON.parse(m) });
              } catch {}
            }
            try {
              return base?.[level]?.(m, ...rest);
            } catch (e) {
              // Evidence: whether the host's own logger refused this call (it is rethrown).
              log("audit.jsonl", { level, hostLoggerThrew: true, argType: typeof m, error: String(e?.message ?? e).slice(0, 200) });
              throw e;
            }
          };
          return { ...base, info: tee("info"), warn: tee("warn"), error: tee("error") };
        }
        if (prop === "on") {
          return (name, handler, opts) =>
            target.on(
              name,
              name === "before_tool_call" ? observed(handler) : name === "after_tool_call" ? observedAfter(handler) : name === "before_prompt_build" ? observedPrompt(handler) : handler,
              opts,
            );
        }
        const v = Reflect.get(target, prop, receiver);
        return typeof v === "function" ? v.bind(target) : v;
      },
    });
    log("transport.jsonl", {
      event: "register-called",
      moduleCopy: MODULE_COPY,
      cloudMode,
      mode: api?.registrationMode ?? null,
      denySeen: Array.isArray(api?.config?.plugins?.deny) ? api.config.plugins.deny : null,
    });
    try {
      chosen.register(wrapped);
    } catch (e) {
      log("transport.jsonl", { event: "register-threw", error: String(e?.message ?? e) });
      throw e;
    }
    log("transport.jsonl", { event: "registered", hasRuntime: Boolean(api?.runtime?.channel), hasOn: typeof api?.on === "function" });
  },
};
