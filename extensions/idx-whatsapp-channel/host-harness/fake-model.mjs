#!/usr/bin/env node
/**
 * Scripted OpenAI-compatible chat-completions server for the real-host replay harness.
 * Loopback only, Node built-ins only, no outbound calls, no keys checked or stored.
 *
 * Script, decided from the request's messages:
 *   - last user message contains "GENUINE-<tag>" and no tool result follows it: call the
 *     card tool (the offered tool whose name ends in "search_listings") with ref
 *     "genuine-<tag>".
 *   - a tool result follows that GENUINE user message: HOLD the response until
 *     POST /control/release, then answer exactly "[[card:genuine-<tag>]]". The hold keeps
 *     the genuine WhatsApp run live while the harness replays its ids from the dashboard.
 *     (Answer text is the channel's reply token, `[[card:reply]]`; a "CASE=<case>" in the
 *     genuine message picks which committed payload case the tool call asks for.)
 *   - last user message contains "DASHBOARD": call the card tool with ref "dashboard-1";
 *     after its tool result (refused or not) answer "Dashboard run finished."
 *   - anything else: "Hello! How can I help?"
 * Every request is summarised (roles, marker, tool names, stream flag) to
 * `$IDX_HARNESS_DIR/model-requests.jsonl`; message text other than the marker is not logged.
 */
import { createServer } from "node:http";
import { appendFileSync } from "node:fs";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { REPLY_INSTRUCTION, REPLY_TOKEN } from "../constants.mjs";

const SUPPORT = join(dirname(fileURLToPath(import.meta.url)), "..", "test-support");
const PAYLOAD_DIRS = [join(SUPPORT, "payloads"), join(SUPPORT, "payloads-withheld")];
/** The host tool base name a payload case belongs to (`search_listings`, ...), or null. */
function toolOfCase(caseName) {
  try {
    for (const d of PAYLOAD_DIRS) {
      try {
        return String(JSON.parse(readFileSync(join(d, `${caseName}.json`), "utf8")).hostToolName).replace(/^idx__/u, "");
      } catch {}
    }
    return null;
  } catch {
    return null;
  }
}

const DIR = process.env.IDX_HARNESS_DIR;
const PORT = Number(process.env.IDX_FAKE_MODEL_PORT ?? 0);
if (!DIR || !PORT) {
  process.stderr.write("fake-model: IDX_HARNESS_DIR and IDX_FAKE_MODEL_PORT are required\n");
  process.exit(2);
}
const LOG = join(DIR, "model-requests.jsonl");

let releaseWaiters = [];
let released = false;
let held = 0;
let counter = 0;

function textOf(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p?.text === "string" ? p.text : "")).join("\n");
  return "";
}

function plan(body) {
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  const tools = Array.isArray(body?.tools) ? body.tools : [];
  const toolNames = tools.map((t) => t?.function?.name ?? t?.name).filter((n) => typeof n === "string");
  const toolFor = (base) => toolNames.find((n) => new RegExp(`(^|__)${base}(-\\d+)?$`, "u").test(n));
  const cardTool = toolFor("search_listings");
  // The latest user message that carries a marker decides the scenario. The host may add
  // context-only user messages (before the body and after tool results), so those are
  // skipped; "afterTool" means a tool result follows that marker message.
  let lastUser = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role === "user" && /GENUINE-[A-Za-z0-9]+|DASHBOARD/u.test(textOf(messages[i].content))) {
      lastUser = i;
      break;
    }
  }
  const userText = lastUser >= 0 ? textOf(messages[lastUser].content) : "";
  const afterTool = lastUser >= 0 && messages.slice(lastUser + 1).some((m) => m?.role === "tool");
  const genuine = /GENUINE-([A-Za-z0-9]+)/u.exec(userText);
  const dashboard = /DASHBOARD/u.test(userText);
  const marker = genuine ? `GENUINE-${genuine[1]}` : dashboard ? "DASHBOARD" : "none";
  // A genuine turn may name a payload case ("CASE=<case>"); the call then uses that case's tool.
  const caseMatch = /CASE=([a-z0-9-]{1,60})/u.exec(userText);
  const caseName = caseMatch ? caseMatch[1] : "search-features";
  const caseTool = toolFor(toolOfCase(caseName) ?? "search_listings");
  let action;
  if (genuine && !afterTool && caseTool) action = { kind: "tool", name: caseTool, ref: `genuine-${genuine[1]}`, case: caseName };
  else if (genuine && afterTool) action = { kind: "text", text: REPLY_TOKEN, hold: true };
  else if (dashboard && !afterTool && cardTool) action = { kind: "tool", name: cardTool, ref: "dashboard-1", case: "search-features" };
  else if (dashboard && afterTool) action = { kind: "text", text: "Dashboard run finished." };
  else action = { kind: "text", text: "Hello! How can I help?" };
  // Evidence for the token instruction: did the channel's instruction reach this request?
  const hasReplyInstruction = messages.some((m) => (m?.role === "system" || m?.role === "developer") && textOf(m.content).includes(REPLY_INSTRUCTION));
  // Diagnostics: where (if anywhere) the reply token appears in the request.
  const tokenIn = messages.map((m, i) => (textOf(m?.content).includes(REPLY_TOKEN) ? `${i}:${m?.role}` : null)).filter(Boolean);
  return { action, marker, toolNames, roles: messages.map((m) => m?.role), cardTool: cardTool ?? null, hasReplyInstruction, tokenIn };
}

function waitRelease() {
  if (released) return Promise.resolve();
  return new Promise((r) => releaseWaiters.push(r));
}

function sseWrite(res, obj) {
  res.write(`data: ${JSON.stringify(obj)}\n\n`);
}

async function respond(req, res, body) {
  const p = plan(body);
  const n = ++counter;
  const stream = body?.stream === true;
  appendFileSync(
    LOG,
    JSON.stringify({
      n, at: Date.now(), marker: p.marker, roles: p.roles, toolNames: p.toolNames, action: p.action.kind, hold: Boolean(p.action.hold), stream,
      hasReplyInstruction: p.hasReplyInstruction, tokenIn: p.tokenIn, case: p.action.case ?? null,
      // Harness data is synthetic, so the user-message heads are logged to show what the model saw.
      userHeads: (Array.isArray(body?.messages) ? body.messages : []).filter((m) => m?.role === "user").map((m) => textOf(m.content).slice(0, 160)),
      toolResultHeads: (Array.isArray(body?.messages) ? body.messages : []).filter((m) => m?.role === "tool").map((m) => textOf(m.content).slice(0, 160)),
    }) + "\n",
  );
  if (p.action.hold) {
    held++;
    await waitRelease();
    held--;
  }
  const id = `chatcmpl-harness-${n}`;
  const model = body?.model ?? "harness-model";
  const created = Math.floor(Date.now() / 1000);
  const usage = { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 };
  if (p.action.kind === "tool") {
    const call = { id: `call_harness_${n}`, type: "function", function: { name: p.action.name, arguments: JSON.stringify({ ref: p.action.ref, case: p.action.case }) } };
    if (stream) {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: { role: "assistant", content: null, tool_calls: [{ index: 0, ...call }] }, finish_reason: null }] });
      sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] });
      sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [], usage });
      res.end("data: [DONE]\n\n");
    } else {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ id, object: "chat.completion", created, model, choices: [{ index: 0, message: { role: "assistant", content: null, tool_calls: [call] }, finish_reason: "tool_calls" }], usage }));
    }
    return;
  }
  const text = p.action.text;
  if (stream) {
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
    sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: { role: "assistant", content: text }, finish_reason: null }] });
    sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] });
    sseWrite(res, { id, object: "chat.completion.chunk", created, model, choices: [], usage });
    res.end("data: [DONE]\n\n");
  } else {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ id, object: "chat.completion", created, model, choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }], usage }));
  }
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  if (req.method === "GET" && url.pathname === "/control/state") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ held, released, requests: counter }));
    return;
  }
  if (req.method === "POST" && url.pathname === "/control/release") {
    released = true;
    const w = releaseWaiters;
    releaseWaiters = [];
    for (const r of w) r();
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ released: true }));
    return;
  }
  if (req.method === "GET" && /\/models$/u.test(url.pathname)) {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ object: "list", data: [{ id: "harness-model", object: "model", owned_by: "harness" }] }));
    return;
  }
  if (req.method === "POST" && /\/chat\/completions$/u.test(url.pathname)) {
    let raw = "";
    req.setEncoding("utf8");
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      let body = {};
      try {
        body = JSON.parse(raw);
      } catch {
        body = {};
      }
      respond(req, res, body).catch(() => {
        try {
          res.writeHead(500);
          res.end();
        } catch {}
      });
    });
    return;
  }
  appendFileSync(LOG, JSON.stringify({ at: Date.now(), unexpected: `${req.method} ${url.pathname}` }) + "\n");
  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ error: { message: "not found" } }));
});
server.listen(PORT, "127.0.0.1", () => process.stdout.write(`fake-model listening ${PORT}\n`));
