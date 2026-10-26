// Offline candidate only: not installed, activated or a browser relay guarantee.
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";

type RecordValue = Record<string, unknown>;
type Identity = { agentId?: string; sessionKey?: string; runId?: string };
type ToolEvent = { toolName: string; toolCallId?: string; runId?: string; result?: unknown; error?: string };
type Payload = { text?: string };
type DeliveryEvent = { payload: Payload; kind: string; runId?: string; sessionKey?: string };
type Cards = { expires: number; blocks: Map<string, string> };
const TOOLS = new Set([
  "idx__search_listings", "idx__find_similar_listings", "idx__recommend",
  "idx__get_market_stats", "idx__draft_email",
]);
const MARKER = /\[\[IDX_CARD:([A-Za-z0-9_-]{1,160})\]\]/g;
const object = (value: unknown): RecordValue | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue : undefined;

function envelope(value: unknown): RecordValue | undefined {
  const result = object(value);
  if (!result) return;
  if (result.ok === true) return result;
  if (!Array.isArray(result.content) || result.content.length !== 1) return;
  const part = object(result.content[0]);
  if (part?.type !== "text" || typeof part.text !== "string") return;
  try { return object(JSON.parse(part.text)); } catch { return; }
}

function cardMessage(tool: string, result: unknown): string | undefined {
  const value = envelope(result);
  const data = object(value?.data);
  if (value?.ok !== true || !data || typeof data.question === "string"
      || typeof value.message !== "string" || !value.message) return;
  const list = (key: string) => Array.isArray(data[key]) && (data[key] as unknown[]).length > 0;
  const eligible = tool === "idx__search_listings" ? list("listings")
    : tool === "idx__find_similar_listings" ? list("matches")
    : tool === "idx__recommend" ? !!object(data.subject)
    : tool === "idx__get_market_stats" ? typeof data.sample_count === "number"
      && data.sample_count >= 5 && data.low_sample !== true
    : tool === "idx__draft_email" ? data.state === "pending" && typeof data.body === "string"
    : false;
  return eligible ? value.message : undefined;
}

export function createRelay(now: () => number = Date.now) {
  const runs = new Map<string, Cards>();
  const prune = () => {
    for (const [key, value] of runs) if (value.expires <= now()) runs.delete(key);
  };
  const identity = (ctx: Identity, runId?: string, sessionKey?: string) => {
    if ((ctx.agentId && ctx.agentId !== "idx") || !ctx.runId || !ctx.sessionKey
        || (runId && runId !== ctx.runId) || (sessionKey && sessionKey !== ctx.sessionKey)) return;
    return JSON.stringify([ctx.sessionKey, ctx.runId]);
  };
  const afterTool = (event: ToolEvent, ctx: Identity & { toolCallId?: string }) => {
    prune();
    const key = identity(ctx, event.runId);
    const id = event.toolCallId ?? ctx.toolCallId;
    if (ctx.agentId !== "idx" || !key || event.error || !TOOLS.has(event.toolName) || !id
        || !/^[A-Za-z0-9_-]{1,160}$/.test(id)) return;
    const message = cardMessage(event.toolName, event.result);
    if (!message || message.length > 100_000) return;
    if (!runs.has(key) && runs.size >= 64) return;
    const cards = runs.get(key) ?? { expires: now() + 60_000, blocks: new Map() };
    if (cards.blocks.size >= 3 || cards.blocks.has(id)) return;
    cards.blocks.set(id, message);
    runs.set(key, cards);
  };
  const beforeDelivery = (event: DeliveryEvent, ctx: Identity) => {
    prune();
    const key = identity(ctx, event.runId, event.sessionKey);
    const text = event.payload.text;
    if (typeof text !== "string" || !["block", "final"].includes(event.kind)) return;
    const cards = key ? runs.get(key) : undefined;
    if (!cards) return text.includes("[[IDX_CARD:")
      ? { cancel: true as const, reason: "unresolved_card_reference" } : undefined;
    const references = [...text.matchAll(MARKER)].map(match => match[1]);
    const expected = [...cards.blocks.keys()];
    if (references.length !== expected.length || references.some((id, index) => id !== expected[index])) {
      if (event.kind === "final") runs.delete(key!);
      return { cancel: true as const, reason: "missing_duplicate_or_reordered_card_reference" };
    }
    const rendered = text.replace(MARKER, (_match, id: string) => cards.blocks.get(id)!);
    if (event.kind === "final") runs.delete(key!);
    return { payload: { ...event.payload, text: rendered } };
  };
  return { afterTool, beforeDelivery };
}

export default {
  id: "idx-card-relay",
  name: "IDX card relay OFFLINE SPIKE",
  register(api: OpenClawPluginApi) {
    const relay = createRelay();
    api.on("after_tool_call", relay.afterTool);
    api.on("reply_payload_sending", relay.beforeDelivery);
  },
};
