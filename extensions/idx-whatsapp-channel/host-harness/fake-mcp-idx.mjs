#!/usr/bin/env node
/**
 * Fake `idx` MCP server for the real-host replay harness. Stdio, newline-delimited
 * JSON-RPC 2.0, Node built-ins only. Synthetic data only.
 *
 * It serves the four card tools under the real server's names, so the host presents them
 * as `idx__<tool>`. Each call returns one of the committed payloads
 * (`../test-support/payloads/<case>.json`, made by the REAL server code on synthetic
 * inputs, see tests/test_whatsapp_reply_payloads.py), in the real server's wire shape:
 * structuredContent plus one text block equal to `JSON.stringify(structuredContent, null, 2)`
 * (wire.javascript_json), which the host folds into its own labelled block. Every execution
 * appends one line to `$IDX_HARNESS_DIR/tool-exec.jsonl`: the evidence of whether a call ran.
 */
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const DIR = process.env.IDX_HARNESS_DIR;
if (!DIR) {
  process.stderr.write("fake-mcp-idx: IDX_HARNESS_DIR is required\n");
  process.exit(2);
}
const EXEC_LOG = join(DIR, "tool-exec.jsonl");
const SUPPORT = join(dirname(fileURLToPath(import.meta.url)), "..", "test-support");
/** Released cases live in payloads/, cases the channel must withhold in payloads-withheld/. */
const PAYLOAD_DIRS = [join(SUPPORT, "payloads"), join(SUPPORT, "payloads-withheld")];
const LABEL = "structuredContent:\n";
const DEFAULT_CASE = Object.freeze({
  search_listings: "search-features",
  find_similar_listings: "similar",
  recommend: "recommend",
  get_market_stats: "market",
});

/** The structured content of one payload case, or null. */
function structuredFor(caseName) {
  try {
    const dir = PAYLOAD_DIRS.find((d) => existsSync(join(d, `${caseName}.json`)));
    if (!dir) return null;
    const p = JSON.parse(readFileSync(join(dir, `${caseName}.json`), "utf8"));
    const text = p?.result?.content?.[0]?.text;
    if (typeof text !== "string" || !text.startsWith(LABEL)) return null;
    return { tool: String(p.hostToolName ?? "").replace(/^idx__/u, ""), structured: JSON.parse(text.slice(LABEL.length)) };
  } catch {
    return null;
  }
}

const schema = {
  type: "object",
  properties: { ref: { type: "string" }, case: { type: "string" } },
  required: ["ref"],
  additionalProperties: false,
};
const TOOLS = Object.keys(DEFAULT_CASE).map((name) => ({ name, description: `Harness stand-in for the IDX ${name} tool.`, inputSchema: schema }));

function send(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  if (line.trim() === "") return;
  let req;
  try {
    req = JSON.parse(line);
  } catch {
    return;
  }
  const { id, method, params } = req;
  if (id === undefined || id === null) return; // notification
  if (method === "initialize") {
    send({ jsonrpc: "2.0", id, result: { protocolVersion: params?.protocolVersion ?? "2025-06-18", capabilities: { tools: { listChanged: false } }, serverInfo: { name: "idx", version: "0.0.0-harness" } } });
  } else if (method === "tools/list") {
    send({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
  } else if (method === "tools/call") {
    const name = params?.name;
    const ref = typeof params?.arguments?.ref === "string" ? params.arguments.ref : "";
    const caseName = typeof params?.arguments?.case === "string" && params.arguments.case !== "" ? params.arguments.case : DEFAULT_CASE[name];
    const payload = /^[a-z0-9-]{1,60}$/u.test(caseName ?? "") ? structuredFor(caseName) : null;
    if (!(name in DEFAULT_CASE) || !/^[A-Za-z0-9._-]{1,64}$/u.test(ref) || !payload || payload.tool !== name) {
      send({ jsonrpc: "2.0", id, result: { isError: true, content: [{ type: "text", text: "bad call" }] } });
      return;
    }
    appendFileSync(EXEC_LOG, JSON.stringify({ at: Date.now(), tool: name, ref, case: caseName }) + "\n");
    send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: JSON.stringify(payload.structured, null, 2) }], structuredContent: payload.structured } });
  } else if (method === "ping") {
    send({ jsonrpc: "2.0", id, result: {} });
  } else {
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } });
  }
});
