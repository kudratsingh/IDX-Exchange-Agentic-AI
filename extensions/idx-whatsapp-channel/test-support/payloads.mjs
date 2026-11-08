/**
 * The committed card-tool payloads (test-support/payloads/*.json), made by the real
 * server code path on synthetic inputs by tests/test_whatsapp_reply_payloads.py, which
 * also checks that regenerating them gives the same bytes. Each holds the host's one
 * labelled `structuredContent:` text block for that call. Tests only; never imported by
 * runtime code.
 *
 * payloads/ holds the cases whose approved reply the channel releases (the host-harness
 * sweep reads only these). payloads-withheld/ holds valid server replies the channel
 * must withhold: longer than one send (MAX_TEXT_LENGTH) or holding a format character
 * from listing data.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, "payloads");
const WITHHELD_DIR = path.join(HERE, "payloads-withheld");

/** @param {string} dir */
const casesIn = (dir) => Object.freeze(readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort());

/** Every released payload case name, sorted. */
export const PAYLOAD_CASES = casesIn(DIR);
/** Every withheld payload case name, sorted (disjoint from PAYLOAD_CASES). */
export const WITHHELD_PAYLOAD_CASES = casesIn(WITHHELD_DIR);

/**
 * One payload, with its result wrapped as the host's after_tool_call `result` (real host
 * 2026-11-08, runbook C9: `{ content, details, terminate }`, one text block).
 * @param {string} name
 * @returns {{ case: string, tool: string, hostToolName: string, arguments: object, result: { content: object[], details: object, terminate: boolean } }}
 */
export function loadPayload(name) {
  const dir = WITHHELD_PAYLOAD_CASES.includes(name) ? WITHHELD_DIR : DIR;
  const p = JSON.parse(readFileSync(path.join(dir, `${name}.json`), "utf8"));
  // The host labels every bundled-MCP result with its source (real host 2026-11-08):
  // details.mcpServer and details.mcpTool. The reply renderer requires both.
  const mcpTool = String(p.hostToolName).replace(/^idx__/u, "");
  return { ...p, result: { content: p.result.content, details: { mcpServer: "idx", mcpTool }, terminate: false } };
}
