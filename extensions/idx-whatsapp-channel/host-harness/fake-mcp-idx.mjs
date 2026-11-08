#!/usr/bin/env node
/**
 * Fake `idx` MCP server for the real-host replay harness. Stdio, newline-delimited
 * JSON-RPC 2.0, Node built-ins only. Synthetic data only.
 *
 * One tool, `search_listings`, named as the real server names it, so the host presents
 * it as `idx__search_listings` and the channel's `isCardTool` treats it as a card tool.
 * Each execution appends one line to `$IDX_HARNESS_DIR/tool-exec.jsonl` and stores a
 * fixed synthetic card under the requested ref in `$IDX_HARNESS_DIR/cards.json`, which the
 * harness card resolver reads. The execution log is the evidence of whether a call ran.
 */
import { appendFileSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { cardTextFor } from "./cards.mjs";

const DIR = process.env.IDX_HARNESS_DIR;
if (!DIR) {
  process.stderr.write("fake-mcp-idx: IDX_HARNESS_DIR is required\n");
  process.exit(2);
}
const EXEC_LOG = join(DIR, "tool-exec.jsonl");
const CARDS = join(DIR, "cards.json");


function storeCard(ref) {
  let cards = {};
  try {
    cards = JSON.parse(readFileSync(CARDS, "utf8"));
  } catch {
    cards = {};
  }
  cards[ref] = cardTextFor(ref);
  const tmp = `${CARDS}.tmp-${process.pid}`;
  writeFileSync(tmp, JSON.stringify(cards));
  renameSync(tmp, CARDS);
}

const TOOLS = [
  {
    name: "search_listings",
    description: "Harness stand-in for the IDX listing search. Stores one synthetic card.",
    inputSchema: {
      type: "object",
      properties: { ref: { type: "string", description: "card ref to store" } },
      required: ["ref"],
      additionalProperties: false,
    },
  },
];

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
    send({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: params?.protocolVersion ?? "2025-06-18",
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "idx", version: "0.0.0-harness" },
      },
    });
  } else if (method === "tools/list") {
    send({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
  } else if (method === "tools/call") {
    const name = params?.name;
    const ref = typeof params?.arguments?.ref === "string" ? params.arguments.ref : "";
    if (name !== "search_listings" || !/^[A-Za-z0-9._-]{1,64}$/u.test(ref)) {
      send({ jsonrpc: "2.0", id, result: { isError: true, content: [{ type: "text", text: "bad call" }] } });
      return;
    }
    appendFileSync(EXEC_LOG, JSON.stringify({ at: Date.now(), tool: name, ref }) + "\n");
    storeCard(ref);
    send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: `Stored card ${ref}. Reply with exactly [[card:${ref}]]` }] } });
  } else if (method === "ping") {
    send({ jsonrpc: "2.0", id, result: {} });
  } else {
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } });
  }
});
