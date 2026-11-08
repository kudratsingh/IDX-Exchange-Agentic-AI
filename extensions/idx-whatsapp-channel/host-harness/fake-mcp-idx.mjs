#!/usr/bin/env node
/**
 * Fake `idx` MCP server for the real-host replay harness. Stdio, newline-delimited
 * JSON-RPC 2.0, Node built-ins only. Synthetic data only.
 *
 * One tool, `search_listings`, named as the real server names it, so the host presents
 * it as `idx__search_listings` and the channel's `isCardTool` treats it as a card tool.
 * Each execution appends one line to `$IDX_HARNESS_DIR/tool-exec.jsonl` (the evidence of
 * whether a call ran) and returns one synthetic listing as the real server's envelope; the
 * channel's own card capture and renderer turn that into the card the peer receives.
 */
import { appendFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { listingEnvelopeFor } from "./cards.mjs";

const DIR = process.env.IDX_HARNESS_DIR;
if (!DIR) {
  process.stderr.write("fake-mcp-idx: IDX_HARNESS_DIR is required\n");
  process.exit(2);
}
const EXEC_LOG = join(DIR, "tool-exec.jsonl");


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
    // The real server's shape (ONE_COPY_TOOLS): structuredContent plus one text block that
    // is exactly JSON.stringify(structuredContent, null, 2) (wire.javascript_json), which
    // the host's duplicate check folds into a single copy.
    const envelope = listingEnvelopeFor(ref);
    send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: JSON.stringify(envelope, null, 2) }], structuredContent: envelope } });
  } else if (method === "ping") {
    send({ jsonrpc: "2.0", id, result: {} });
  } else {
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: "method not found" } });
  }
});
