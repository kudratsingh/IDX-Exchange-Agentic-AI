/**
 * The committed card-tool payloads (test-support/payloads/*.json), made by the real
 * server code path on synthetic inputs by tests/test_whatsapp_reply_payloads.py, which
 * also checks that regenerating them gives the same bytes. Each holds the host's one
 * labelled `structuredContent:` text block for that call. Tests only; never imported by
 * runtime code.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "payloads");

/** Every payload case name, sorted. */
export const PAYLOAD_CASES = Object.freeze(readdirSync(DIR).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort());

/**
 * One payload, with its result wrapped as the host's after_tool_call `result` (real host
 * 2026-11-08, runbook C9: `{ content, details, terminate }`, one text block).
 * @param {string} name
 * @returns {{ case: string, tool: string, hostToolName: string, arguments: object, result: { content: object[], details: object, terminate: boolean } }}
 */
export function loadPayload(name) {
  const p = JSON.parse(readFileSync(path.join(DIR, `${name}.json`), "utf8"));
  return { ...p, result: { content: p.result.content, details: {}, terminate: false } };
}
