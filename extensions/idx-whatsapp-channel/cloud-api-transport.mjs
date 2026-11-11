/**
 * WhatsApp Cloud API transport (WO-038): the four Transport members over one injected
 * `fetch`, plus a signed-webhook handler for inbound text. The entry builds it only when
 * the plugin's own `cloudApi` block is enabled (WO-039; off by default), from the owner's
 * credentials file. Nothing here holds a credential, a number or an id: every value comes
 * from the injected config object.
 */

import { Buffer } from "node:buffer";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

import { normalizePeerId } from "./ingress.mjs";

/** The only origin a send may reach. Not configurable, so no config value can point the
 *  bearer token at another host. */
export const GRAPH_API_ORIGIN = "https://graph.facebook.com";

/** Meta's customer service window: free-form replies only within 24 hours of the user's
 *  last message (WO-038, Meta sources). The transport refuses a send outside it. */
export const CUSTOMER_SERVICE_WINDOW_MS = 86_400_000;

/** Largest webhook body read. Meta allows up to 3 MB; a reply-only, low-volume number sees
 *  far less, and the host's own webhook default is 1 MiB (owner choice, flagged). */
export const WEBHOOK_MAX_BODY_BYTES = 1_048_576;

/** An inbound older than this (Meta's message timestamp) is acknowledged and dropped, so a
 *  retry delivered after an outage does not start a turn (owner choice, flagged). */
export const MAX_INBOUND_AGE_MS = 1_800_000;
/** An inbound timestamp further than this in the future is dropped as malformed. */
export const MAX_CLOCK_SKEW_MS = 300_000;

/** Message ids remembered to drop Meta's duplicate deliveries: lifetime and capacity, for
 *  a webhook built without a `dedupeStore` (tests and direct use). In memory, per
 *  instance: after a restart an id seen before is new again while its Meta timestamp is
 *  inside the inbound age limit (WO-038 decision 8). The plugin entry always passes the
 *  persistent store of cloud-api-dedupe.mjs (WO-040), which closes that gap. */
export const DEDUPE_TTL_MS = 86_400_000;
export const DEDUPE_MAX_ENTRIES = 4096;
/** Peers whose last inbound time is remembered for the window check. A peer whose inbound
 *  is still being handled by the channel (its turn is running) is never evicted, so a flood
 *  of other senders cannot close its window mid-turn. */
export const WINDOW_MAX_PEERS = 1024;

/** Longest text body Meta accepts for a text message we send [M3]. */
export const CLOUD_TEXT_MAX_LENGTH = 4096;
/** Longest inbound text body handed to the channel. Meta states no maximum for an inbound
 *  `text.body` [M4] (4096 is the send limit only); this cap is ours (owner choice,
 *  flagged), and a longer message is dropped with a `too-long` warning. */
export const CLOUD_INBOUND_TEXT_MAX_LENGTH = 65_536;

/** The only account the channel lists and starts (channel.mjs `listAccountIds`). */
const DEFAULT_ACCOUNT_ID = "default";
/** Meta's error code for a send outside the customer service window. */
const OUTSIDE_WINDOW_API_CODE = 131047;

const PHONE_NUMBER_ID_RE = /^\d{5,32}$/u;
const GRAPH_VERSION_RE = /^v\d{1,3}\.\d{1,3}$/u;
const ACCESS_TOKEN_RE = /^[A-Za-z0-9._~+/=|-]{32,4096}$/u;
const APP_SECRET_RE = /^[A-Za-z0-9]{16,256}$/u;
const VERIFY_TOKEN_RE = /^[\x21-\x7e]{16,256}$/u;
const WEBHOOK_PATH_RE = /^(?:\/[A-Za-z0-9_~-][A-Za-z0-9._~-]{0,63}){1,8}$/u;
/** A canonical phone peer (`normalizePeerId` output for a phone number). */
const CANONICAL_PHONE_RE = /^\+\d{7,15}$/u;
/** Cloud API `from` / `wa_id`: country code and number, digits only. */
const WA_ID_RE = /^\d{7,15}$/u;
const MESSAGE_ID_RE = /^[\x21-\x7e]{1,256}$/u;
const TIMESTAMP_RE = /^\d{1,12}$/u;
const SIGNATURE_RE = /^sha256=([0-9a-fA-F]{64})$/u;
const CHALLENGE_RE = /^[\x21-\x7e]{1,256}$/u;

/** Whether `p` is a webhook path this module accepts in config (absolute, 1-8 plain
 *  segments, no dot segment, query or double slash). Exported for the loopback listener.
 *  @param {unknown} p */
export function isWebhookPath(p) {
  return typeof p === "string" && WEBHOOK_PATH_RE.test(p);
}

/** @param {unknown} v @returns {v is Record<string, any>} */
const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * The validated config, read once (each field exactly once, so a getter cannot answer
 * twice), or null when any required value is missing or implausible. Never throws and
 * never reports which field failed, so no value can reach a log or an error.
 * @param {unknown} config
 * @returns {Readonly<{ accountId: string, phoneNumberId: string, graphApiVersion: string,
 *   accessToken: string, appSecret: string, verifyToken: string, webhookPath: string }> | null}
 */
export function readCloudApiConfig(config) {
  try {
    if (!isPlainObject(config)) return null;
    const { accountId = DEFAULT_ACCOUNT_ID, phoneNumberId, graphApiVersion, accessToken, appSecret, verifyToken, webhookPath } = config;
    const ok =
      // The channel lists and starts only "default"; any other id would leave start()
      // refusing and the webhook answering 503 forever while isConfigured() said true.
      accountId === DEFAULT_ACCOUNT_ID &&
      typeof phoneNumberId === "string" && PHONE_NUMBER_ID_RE.test(phoneNumberId) &&
      typeof graphApiVersion === "string" && GRAPH_VERSION_RE.test(graphApiVersion) &&
      typeof accessToken === "string" && ACCESS_TOKEN_RE.test(accessToken) &&
      typeof appSecret === "string" && APP_SECRET_RE.test(appSecret) &&
      typeof verifyToken === "string" && VERIFY_TOKEN_RE.test(verifyToken) &&
      typeof webhookPath === "string" && WEBHOOK_PATH_RE.test(webhookPath) &&
      // The verify token travels in a GET query string (tunnel and proxy logs), so it may
      // not double as either real secret.
      verifyToken !== appSecret && verifyToken !== accessToken && appSecret !== accessToken;
    if (!ok) return null;
    return Object.freeze({ accountId, phoneNumberId, graphApiVersion, accessToken, appSecret, verifyToken, webhookPath });
  } catch {
    return null;
  }
}

/** Constant-time string equality over fixed-length digests, so neither content nor length
 *  leaks through timing. @param {string} a @param {string} b */
function safeEqualStrings(a, b) {
  const da = createHash("sha256").update(a, "utf8").digest();
  const db = createHash("sha256").update(b, "utf8").digest();
  return timingSafeEqual(da, db);
}

/**
 * Whether `header` is a valid `X-Hub-Signature-256` for exactly these raw bytes: HMAC-SHA256
 * keyed with the app secret, compared in constant time on the 32 decoded bytes. A missing,
 * repeated (array), wrongly prefixed or wrong-length header is false. Exported for tests.
 * @param {Uint8Array} rawBody @param {unknown} header @param {string} appSecret
 */
export function signatureValid(rawBody, header, appSecret) {
  if (typeof header !== "string") return false;
  const m = SIGNATURE_RE.exec(header);
  if (!m) return false;
  const given = Buffer.from(m[1], "hex");
  const expected = createHmac("sha256", appSecret).update(rawBody).digest();
  return given.length === expected.length && timingSafeEqual(given, expected);
}

/** A bounded map of key -> time, oldest first, with lazy expiry. Over capacity it evicts
 *  the oldest-touched key that `isPinned` does not protect; pinned keys are bounded by
 *  the caller (one per inbound still being handled). */
function createBoundedTimes(maxEntries, isPinned = () => false) {
  /** @type {Map<string, number>} */
  const map = new Map();
  return {
    get: (k) => map.get(k),
    set(k, t) {
      map.delete(k);
      map.set(k, t);
      if (map.size <= maxEntries) return;
      for (const key of map.keys()) {
        if (map.size <= maxEntries) break;
        if (!isPinned(key)) map.delete(key);
      }
    },
    prune(olderThan) {
      for (const [k, t] of map) {
        if (t >= olderThan) break;
        map.delete(k);
      }
    },
    get size() {
      return map.size;
    },
  };
}

/**
 * The given logger with every method wrapped so a call never throws (WO-039: OpenClaw
 * 2026.9.5's plugin logger threw on object messages, and an unguarded line turned every
 * webhook answer into a 500). A missing method is a no-op.
 * @param {{ info?: Function, warn?: Function, error?: Function } | undefined} log
 */
function quietLog(log) {
  const wrap = (level) => (fields) => {
    try {
      log?.[level]?.(fields);
    } catch {
      /* a log line never changes an answer or a send */
    }
  };
  return Object.freeze({ info: wrap("info"), warn: wrap("warn"), error: wrap("error") });
}

/** @param {unknown} headers @param {string} name the lowercase header name */
function headerOf(headers, name) {
  if (!isPlainObject(headers)) return undefined;
  for (const k of Object.keys(headers)) if (k.toLowerCase() === name) return headers[k];
  return undefined;
}

const TEXT_PLAIN = Object.freeze({ "content-type": "text/plain; charset=utf-8", "x-content-type-options": "nosniff", "cache-control": "no-store" });
/** @param {number} status @param {string} [body] @param {Record<string, string>} [extra] */
const reply = (status, body = "", extra = {}) => ({ status, headers: { ...TEXT_PLAIN, ...extra }, body });

/**
 * Pure webhook handler for the Cloud API callback URL. `handle(req)` takes `{ method, url,
 * headers, body }` (body: the raw request bytes) and returns `{ status, headers, body }`
 * synchronously; it never awaits `onInbound`, so the agent run never holds the response.
 *
 *   - GET: 200 with `hub.challenge` (as plain text) only when `hub.mode` is "subscribe"
 *     and `hub.verify_token` equals the configured token (constant time); else 403.
 *   - POST: 413 over the body limit; 401 unless `X-Hub-Signature-256` verifies over the
 *     raw bytes (checked before any decode or parse); 503 when `isReady()` is false (Meta
 *     retries; the age limit bounds what a retry can start); 400 for bytes that are not
 *     UTF-8 JSON; else 200. Only `messages` changes for the configured phone-number id
 *     are read, and from them only `type: "text"` messages from a phone-number sender
 *     with a fresh timestamp and an id not seen before. Every message goes through the
 *     in-memory dedupe (TTL, capacity); with a `dedupeStore`, a message from a sender
 *     `acceptsSender` admits is also claimed in the store (recorded on disk BEFORE its turn
 *     starts, so a restart cannot forget it) and dropped when the claim says it was seen
 *     before. A store that cannot claim answers 503 (`webhook-deferred`) so Meta retries,
 *     with nothing started for that message or any after it in the same POST. A sender it
 *     does not admit never touches the store (the channel drops it, so no turn and no reply
 *     can follow), so strangers cannot fill it. Statuses, other
 *     types, group or username-only senders and stale messages are acknowledged and
 *     dropped; a text over CLOUD_INBOUND_TEXT_MAX_LENGTH is dropped with a `too-long`
 *     warning. A `failed` status is Meta reporting, after a 2xx send, that a reply was
 *     not delivered: it warns `send-failed-async` with Meta's numeric code at most.
 *     Each kept message goes to `onInbound({ accountId, peerId, text, messageId,
 *     receivedAt })` with `peerId` canonical (`+<digits>`) and `receivedAt` Meta's time.
 *   - any other method 405; any other path 404; an unusable config 404 for everything.
 * Logs carry an event name, a reason and counts only: never text, peer, id, token,
 * signature or body.
 * @param {{ config: unknown, onInbound: (msg: import("./transport.mjs").InboundText) => unknown,
 *   now?: () => number, log?: { info?: Function, warn?: Function, error?: Function },
 *   isReady?: () => boolean, maxBodyBytes?: number, maxInboundAgeMs?: number,
 *   dedupeTtlMs?: number, dedupeMaxEntries?: number,
 *   dedupeStore?: { claim: (id: string, t: number) => boolean },
 *   acceptsSender?: (peerId: string) => boolean }} deps
 */
export function createCloudApiWebhook({
  config,
  onInbound,
  now = Date.now,
  log: rawLog,
  isReady = () => true,
  maxBodyBytes = WEBHOOK_MAX_BODY_BYTES,
  maxInboundAgeMs = MAX_INBOUND_AGE_MS,
  dedupeTtlMs = DEDUPE_TTL_MS,
  dedupeMaxEntries = DEDUPE_MAX_ENTRIES,
  dedupeStore,
  acceptsSender = () => true,
}) {
  if (typeof onInbound !== "function") throw new Error("idx-whatsapp-channel: cloud api webhook needs onInbound");
  if (dedupeStore !== undefined && typeof dedupeStore?.claim !== "function") {
    throw new Error("idx-whatsapp-channel: cloud api webhook: bad dedupe store");
  }
  const cfg = readCloudApiConfig(config);
  const log = quietLog(rawLog);
  const seen = createBoundedTimes(dedupeMaxEntries);
  const warn = (event, reason) => log?.warn?.({ component: "idx-whatsapp-channel.cloud-api", event, reason });

  /** @param {any} msg @param {number} t @returns {import("./transport.mjs").InboundText | string} the inbound, or a drop reason */
  function inboundOf(msg, t) {
    if (!isPlainObject(msg)) return "malformed";
    if (msg.type !== "text") return "non-text";
    if ("group_id" in msg) return "group";
    const { from, id, timestamp, text } = msg;
    if (typeof from !== "string" || !WA_ID_RE.test(from)) return "no-phone-sender";
    if (typeof id !== "string" || !MESSAGE_ID_RE.test(id)) return "malformed";
    const body = isPlainObject(text) ? text.body : undefined;
    if (typeof body !== "string" || body.trim() === "") return "malformed";
    if (body.length > CLOUD_INBOUND_TEXT_MAX_LENGTH) return "too-long";
    if (typeof timestamp !== "string" || !TIMESTAMP_RE.test(timestamp)) return "malformed";
    const receivedAt = Number(timestamp) * 1000;
    if (receivedAt > t + MAX_CLOCK_SKEW_MS) return "malformed";
    if (t - receivedAt > maxInboundAgeMs) return "stale";
    const peerId = normalizePeerId(`+${from}`);
    if (!CANONICAL_PHONE_RE.test(peerId)) return "no-phone-sender";
    return { accountId: /** @type {any} */ (cfg).accountId, peerId, text: body, messageId: id, receivedAt };
  }

  /** @param {import("./transport.mjs").InboundText} msg */
  function dispatch(msg) {
    try {
      Promise.resolve(onInbound(msg)).catch(() => warn("inbound-handler-error", "rejected"));
    } catch {
      warn("inbound-handler-error", "threw");
    }
  }

  /** @param {Uint8Array} raw */
  function post(raw) {
    let payload;
    try {
      payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {
      warn("webhook-rejected", "unparseable");
      return reply(400);
    }
    const t = now();
    seen.prune(t - dedupeTtlMs);
    let delivered = 0;
    let ignored = 0;
    const entries = isPlainObject(payload) && payload.object === "whatsapp_business_account" && Array.isArray(payload.entry) ? payload.entry : [];
    for (const entry of entries) {
      const changes = isPlainObject(entry) && Array.isArray(entry.changes) ? entry.changes : [];
      for (const change of changes) {
        const value = isPlainObject(change) && change.field === "messages" ? change.value : undefined;
        if (!isPlainObject(value) || value.messaging_product !== "whatsapp") { ignored += 1; continue; }
        const meta = value.metadata;
        if (!isPlainObject(meta) || meta.phone_number_id !== cfg?.phoneNumberId) { ignored += 1; continue; }
        // statuses (sent, delivered, read, failed) and every other field are not inbound
        const messages = Array.isArray(value.messages) ? value.messages : [];
        const statuses = Array.isArray(value.statuses) ? value.statuses : [];
        ignored += statuses.length;
        for (const s of statuses) {
          // Meta reports some send failures (131047 among them) only here, after the send
          // answered 2xx and the gate audited it as sent [M5, M6]. Warn without the wamid,
          // the recipient or Meta's text.
          if (!isPlainObject(s) || s.status !== "failed") continue;
          const first = Array.isArray(s.errors) && isPlainObject(s.errors[0]) ? s.errors[0].code : undefined;
          const apiCode = Number.isSafeInteger(first) ? first : undefined;
          const reason = apiCode === OUTSIDE_WINDOW_API_CODE ? "outside-customer-service-window" : "delivery-failed";
          log?.warn?.({ component: "idx-whatsapp-channel.cloud-api", event: "send-failed-async", reason, ...(apiCode !== undefined ? { apiCode } : {}) });
        }
        for (const msg of messages) {
          const inbound = inboundOf(msg, t);
          if (inbound === "too-long") warn("inbound-dropped", "too-long");
          if (typeof inbound === "string") { ignored += 1; continue; }
          const last = seen.get(inbound.messageId);
          if (last !== undefined && t - last <= dedupeTtlMs) { ignored += 1; continue; }
          let admitted = false;
          try {
            admitted = acceptsSender(inbound.peerId) === true;
          } catch {
            admitted = false;
          }
          if (dedupeStore && admitted) {
            // Claimed on disk before the turn starts, so a restart cannot forget it.
            let known;
            try {
              known = dedupeStore.claim(inbound.messageId, inbound.receivedAt) !== true;
            } catch (err) {
              const r = /** @type {any} */ (err)?.reason;
              warn("dedupe-store-failed", typeof r === "string" && /^[a-z][a-z-]{0,39}$/u.test(r) ? r : "error");
              // Not "webhook-accepted": Meta gets 503 for this POST and retries it.
              log?.info?.({ component: "idx-whatsapp-channel.cloud-api", event: "webhook-deferred", delivered, ignored });
              return reply(503, "", { "retry-after": "30" });
            }
            if (known) { ignored += 1; continue; }
          }
          seen.set(inbound.messageId, t);
          delivered += 1;
          dispatch(Object.freeze(inbound));
        }
      }
    }
    log?.info?.({ component: "idx-whatsapp-channel.cloud-api", event: "webhook-accepted", delivered, ignored });
    return reply(200);
  }

  return Object.freeze({
    path: cfg ? cfg.webhookPath : undefined,
    maxBodyBytes,
    /** @param {{ method?: unknown, url?: unknown, headers?: unknown, body?: unknown }} req */
    handle(req) {
      try {
        if (!cfg) return reply(404);
        const method = isPlainObject(req) ? req.method : undefined;
        const url = isPlainObject(req) && typeof req.url === "string" ? req.url : "";
        const q = url.indexOf("?");
        const pathname = q === -1 ? url : url.slice(0, q);
        if (pathname !== cfg.webhookPath) return reply(404);
        if (method === "GET") {
          const params = new URLSearchParams(q === -1 ? "" : url.slice(q + 1));
          const mode = params.get("hub.mode");
          const token = params.get("hub.verify_token");
          const challenge = params.get("hub.challenge");
          const tokenOk = typeof token === "string" && safeEqualStrings(token, cfg.verifyToken);
          if (mode === "subscribe" && tokenOk && typeof challenge === "string" && CHALLENGE_RE.test(challenge)) {
            log?.info?.({ component: "idx-whatsapp-channel.cloud-api", event: "webhook-verified" });
            return reply(200, challenge);
          }
          warn("webhook-verify-refused", "mismatch");
          return reply(403);
        }
        if (method !== "POST") return reply(405, "", { allow: "GET, POST" });
        const raw = req.body;
        if (!(raw instanceof Uint8Array)) return reply(400);
        if (raw.byteLength > maxBodyBytes) {
          warn("webhook-rejected", "too-large");
          return reply(413);
        }
        if (!signatureValid(raw, headerOf(req.headers, "x-hub-signature-256"), cfg.appSecret)) {
          warn("webhook-rejected", "bad-signature");
          return reply(401);
        }
        if (isReady() !== true) {
          warn("webhook-deferred", "not-started");
          return reply(503, "", { "retry-after": "30" });
        }
        return post(raw);
      } catch {
        warn("webhook-error", "handler");
        return reply(500);
      }
    },
  });
}

/** Body read deadline for the route adapter, so a body that never ends cannot hold a
 *  request open. */
export const WEBHOOK_READ_TIMEOUT_MS = 10_000;
/** Longest gap between two body chunks before the read gives up (408), so a slow sender
 *  cannot hold a read for the whole deadline. */
export const WEBHOOK_IDLE_TIMEOUT_MS = 2_000;
/** Body reads in flight at once; above it a POST is 503 with `retry-after` before any
 *  byte is read, so open connections cannot hold more than this many bodies in memory. */
export const WEBHOOK_MAX_CONCURRENT_READS = 8;

/**
 * Reads a request body up to `maxBytes` with listeners (not async iteration, which would
 * destroy the socket before a 413 could be written). Resolves to the bytes, or to
 * "too-large", "timeout" (overall deadline or idle gap) or "error"; never rejects.
 * @param {any} req @param {number} maxBytes @param {number} timeoutMs @param {number} idleMs
 * @returns {Promise<Buffer | "too-large" | "timeout" | "error">}
 */
function readBody(req, maxBytes, timeoutMs, idleMs) {
  return new Promise((resolve) => {
    /** @type {Buffer[]} */
    let chunks = [];
    let size = 0;
    let settled = false;
    /** @type {ReturnType<typeof setTimeout> | undefined} */
    let idle;
    const finish = (v) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearTimeout(idle);
      req.off?.("data", onData);
      req.off?.("end", onEnd);
      req.off?.("error", onError);
      chunks = [];
      resolve(v);
    };
    const armIdle = () => {
      clearTimeout(idle);
      idle = setTimeout(() => finish("timeout"), idleMs);
      idle.unref?.();
    };
    const onData = (chunk) => {
      if (settled) return;
      const buf = typeof chunk === "string" ? Buffer.from(chunk, "utf8") : Buffer.from(chunk);
      size += buf.byteLength;
      if (size > maxBytes) {
        req.pause?.();
        finish("too-large");
        return;
      }
      chunks.push(buf);
      armIdle();
    };
    const onEnd = () => finish(Buffer.concat(chunks));
    const onError = () => finish("error");
    const timer = setTimeout(() => finish("timeout"), timeoutMs);
    timer.unref?.();
    armIdle();
    req.on("data", onData);
    req.on("end", onEnd);
    req.on("error", onError);
  });
}

/**
 * Adapts a webhook to the host's route handler, `(req: IncomingMessage, res:
 * ServerResponse) => Promise<boolean>` (OpenClaw 2026.9.5 `OpenClawPluginHttpRouteHandler`).
 * Before reading a POST body it answers 413 for a declared oversize body, 401 when
 * `X-Hub-Signature-256` is missing or not `sha256=<64 hex>`, and 503 with `retry-after`
 * when `maxConcurrentReads` bodies are already being read. It then reads the raw body: a
 * streamed body over the limit is 413, one not finished within `readTimeoutMs` or idle for
 * `idleTimeoutMs` is 408. Every early answer carries `connection: close`. Then it answers
 * from `webhook.handle`, which verifies the signature. Always returns true; never throws.
 * @param {ReturnType<typeof createCloudApiWebhook>} webhook
 * @param {{ readTimeoutMs?: number, idleTimeoutMs?: number, maxConcurrentReads?: number }} [opts]
 */
export function createHttpRouteHandler(webhook, {
  readTimeoutMs = WEBHOOK_READ_TIMEOUT_MS,
  idleTimeoutMs = WEBHOOK_IDLE_TIMEOUT_MS,
  maxConcurrentReads = WEBHOOK_MAX_CONCURRENT_READS,
} = {}) {
  let reading = 0;
  return async (req, res) => {
    const send = (r) => {
      res.statusCode = r.status;
      for (const [k, v] of Object.entries(r.headers)) res.setHeader(k, v);
      res.end(r.body);
    };
    try {
      let body;
      if (req.method === "POST") {
        const declared = Number(headerOf(req.headers, "content-length"));
        if (Number.isFinite(declared) && declared > webhook.maxBodyBytes) {
          send(reply(413, "", { connection: "close" }));
          return true;
        }
        // Only the shape is checked here (the HMAC needs the body); an unsigned request
        // is refused before a single byte of it is buffered.
        const signature = headerOf(req.headers, "x-hub-signature-256");
        if (typeof signature !== "string" || !SIGNATURE_RE.test(signature)) {
          send(reply(401, "", { connection: "close" }));
          return true;
        }
        if (reading >= maxConcurrentReads) {
          send(reply(503, "", { connection: "close", "retry-after": "5" }));
          return true;
        }
        reading += 1;
        let read;
        try {
          read = await readBody(req, webhook.maxBodyBytes, readTimeoutMs, idleTimeoutMs);
        } finally {
          reading -= 1;
        }
        if (read === "too-large") {
          send(reply(413, "", { connection: "close" }));
          return true;
        }
        if (read === "timeout") {
          send(reply(408, "", { connection: "close" }));
          return true;
        }
        if (read === "error") {
          send(reply(400, "", { connection: "close" }));
          return true;
        }
        body = read;
      }
      send(webhook.handle({ method: req.method, url: req.url, headers: req.headers, body }));
    } catch {
      try {
        send(reply(500));
      } catch {
        /* the response is already gone */
      }
    }
    return true;
  };
}

/** A transport failure: a fixed message with the HTTP status and Meta's numeric error code at
 *  most. Never the token, the body, the recipient or Meta's error text. */
class CloudApiError extends Error {
  /** @param {string} reason @param {{ status?: number, apiCode?: number }} [info] */
  constructor(reason, { status, apiCode } = {}) {
    const parts = [status !== undefined ? `http ${status}` : "", apiCode !== undefined ? `code ${apiCode}` : ""].filter(Boolean);
    super(`idx-whatsapp-channel: cloud api: ${reason}${parts.length ? ` (${parts.join(", ")})` : ""}`);
    this.name = "CloudApiError";
    this.reason = reason;
    if (status !== undefined) this.status = status;
    if (apiCode !== undefined) this.apiCode = apiCode;
  }
}

const MAX_RESPONSE_CHARS = 65_536;

/**
 * Joins the caller's signal (if any) and the running start's own signal into the one
 * signal handed to `fetch`, so either can abort the request. Returns the signal and a
 * `release` that removes the listeners once the request is over.
 * @param {AbortSignal | undefined} caller @param {AbortSignal} life
 * @returns {{ signal: AbortSignal, release: () => void }}
 */
function joinSignals(caller, life) {
  const ac = new AbortController();
  const abort = () => ac.abort();
  if (caller?.aborted || life.aborted) {
    ac.abort();
    return { signal: ac.signal, release: () => {} };
  }
  caller?.addEventListener?.("abort", abort, { once: true });
  life.addEventListener("abort", abort, { once: true });
  return {
    signal: ac.signal,
    release: () => {
      caller?.removeEventListener?.("abort", abort);
      life.removeEventListener("abort", abort);
    },
  };
}

/**
 * The Cloud API transport. `config` is an injected object (never a file or the
 * environment): `phoneNumberId`, `graphApiVersion`, `accessToken`, `appSecret`,
 * `verifyToken`, `webhookPath`, optional `accountId` (only "default", the one account the
 * channel lists and starts). Returns a frozen object with the four Transport members and
 * `webhook` (`path`, `handle`, `routeHandler`) for the install to register as an HTTP
 * route. The channel uses the four members only; the webhook feeds the sink `start`
 * registered and stamps each peer's last inbound time, which `sendText` checks against
 * `windowMs` (default 24 h). A peer whose inbound the sink is still handling is pinned in
 * that table, so senders the allowlist drops cannot evict it mid-turn.
 *
 * Lifecycle (owner instruction 2026-11-08): the transport is running only between a
 * `start` that registered its sink and that start's end (its signal aborts, or `stop()`).
 * `sendText` refuses `transport-not-running` with no request at any other time: before the
 * first start, after a stop, and between a stop and the next start. Each start has its own
 * abort controller, joined with the caller's signal on every `fetch`; when that start ends
 * or a newer start takes over, the controller aborts, so a request still in flight is
 * aborted (`aborted`, never retried; Meta may still have accepted it). Pins belong to the
 * start that took the inbound, so a stop releases them and a late settle from an old turn
 * cannot unpin a peer for the new start. Last-inbound times are Meta's facts about the
 * user and survive a restart, as dedupe does.
 * @param {{ config: unknown, fetch: typeof globalThis.fetch, now?: () => number,
 *   log?: { info?: Function, warn?: Function, error?: Function }, windowMs?: number,
 *   webhookOptions?: { maxBodyBytes?: number, maxInboundAgeMs?: number, dedupeTtlMs?: number, dedupeMaxEntries?: number,
 *     dedupeStore?: { has: Function, record: Function } } }} deps
 */
export function createCloudApiTransport({ config, fetch, now = Date.now, log: rawLog, windowMs = CUSTOMER_SERVICE_WINDOW_MS, webhookOptions = {} }) {
  const cfg = readCloudApiConfig(config);
  const log = quietLog(rawLog);
  const configured = cfg !== null && typeof fetch === "function";
  /**
   * The running start, or null. `pins` counts, per peer, the inbounds this start's sink is
   * still handling: the channel's sink settles at once for a sender its allowlist drops
   * and only after the turn (and its reply) for an admitted one, so only admitted peers
   * stay pinned for long. `life` aborts every request sent under this start.
   * @typedef {{ onInbound: Function, acceptsSender?: (peer: string) => boolean, done: () => void, pins: Map<string, number>, life: AbortController }} Run
   */
  /** @type {Run | null} */
  let active = null;
  const lastInbound = createBoundedTimes(WINDOW_MAX_PEERS, (peer) => active !== null && active.pins.has(peer));
  /** @type {Set<() => void>} */
  const pending = new Set();

  /** @param {Run} run @param {string} peer */
  const unpin = (run, peer) => {
    const n = (run.pins.get(peer) ?? 1) - 1;
    if (n > 0) run.pins.set(peer, n);
    else run.pins.delete(peer);
  };

  /** @param {import("./transport.mjs").InboundText} msg */
  function receive(msg) {
    const peer = msg.peerId;
    const sink = active;
    // Pinned before the stamp, so this peer's own entry cannot be the one evicted.
    if (sink) sink.pins.set(peer, (sink.pins.get(peer) ?? 0) + 1);
    lastInbound.prune(now() - windowMs);
    const prev = lastInbound.get(peer);
    lastInbound.set(peer, prev !== undefined && prev > msg.receivedAt ? prev : msg.receivedAt);
    if (!sink) return undefined;
    let r;
    try {
      r = sink.onInbound(msg);
    } catch (err) {
      unpin(sink, peer);
      throw err;
    }
    // The original promise goes back to the webhook, which reports its rejection.
    Promise.resolve(r).then(() => unpin(sink, peer), () => unpin(sink, peer));
    return r;
  }

  const webhook = createCloudApiWebhook({
    ...webhookOptions,
    config,
    onInbound: receive,
    now,
    log,
    isReady: () => active !== null,
    // The running start's admission rule (the channel's sender allowlist); none admits all.
    acceptsSender: (peer) => (active === null ? false : typeof active.acceptsSender === "function" ? active.acceptsSender(peer) === true : true),
  });
  const routeHandler = createHttpRouteHandler(webhook);

  /** @param {{ accountId?: string, signal?: AbortSignal, onInbound: Function }} opts */
  async function start(opts) {
    if (!configured) throw new CloudApiError("not-configured");
    const onInbound = opts?.onInbound;
    const signal = opts?.signal;
    if (typeof onInbound !== "function") throw new CloudApiError("no-inbound-sink");
    if (opts?.accountId !== undefined && opts.accountId !== cfg.accountId) throw new CloudApiError("unknown-account");
    if (signal?.aborted) return;
    await new Promise((resolve) => {
      /** @type {Run} */
      const me = { onInbound, acceptsSender: typeof opts?.acceptsSender === "function" ? opts.acceptsSender : undefined, done: () => finish(), pins: new Map(), life: new AbortController() };
      const finish = () => {
        if (active === me) active = null;
        pending.delete(me.done);
        signal?.removeEventListener?.("abort", finish);
        // Requests sent under this start are aborted; its pins go with it.
        me.life.abort();
        me.pins.clear();
        resolve(undefined);
      };
      // A newer start takes over the sink and runs fresh: requests still in flight under
      // the older one are aborted now, and the older start stays pending until its own end.
      if (active !== null) {
        active.life.abort();
        active.pins.clear();
      }
      active = me;
      pending.add(me.done);
      signal?.addEventListener?.("abort", finish, { once: true });
    });
  }

  /** @param {{ accountId?: string, to: string, text: string, signal?: AbortSignal }} req */
  async function sendText(req) {
    if (!configured) throw new CloudApiError("not-configured");
    // Only a running start may send: never before the first start, after a stop, or
    // between a stop and the next start. Checked first, before any field is read.
    const run = active;
    if (run === null || run.life.signal.aborted) throw new CloudApiError("transport-not-running");
    const accountId = req?.accountId;
    const to = req?.to;
    const text = req?.text;
    const signal = req?.signal;
    if (accountId !== undefined && accountId !== cfg.accountId) throw new CloudApiError("unknown-account");
    if (typeof text !== "string" || text === "" || text.length > CLOUD_TEXT_MAX_LENGTH) throw new CloudApiError("invalid-text");
    const peer = normalizePeerId(to);
    if (!CANONICAL_PHONE_RE.test(peer)) throw new CloudApiError("unsupported-recipient");
    // Defence in depth: the channel is reply-only, and Meta allows free-form text only
    // within 24 hours of the peer's last message. Unknown or stale peers are refused here.
    const last = lastInbound.get(peer);
    const t = now();
    if (last === undefined || t - last > windowMs || t - last < -MAX_CLOCK_SKEW_MS) throw new CloudApiError("outside-customer-service-window");
    const url = `${GRAPH_API_ORIGIN}/${cfg.graphApiVersion}/${cfg.phoneNumberId}/messages`;
    const body = JSON.stringify({
      messaging_product: "whatsapp",
      recipient_type: "individual",
      to: peer.slice(1),
      type: "text",
      text: { preview_url: false, body: text },
    });
    // The caller's signal and this start's own: a stop or a takeover aborts the request.
    const joined = joinSignals(signal, run.life.signal);
    let res;
    let parsed;
    try {
      try {
        // One request, never retried: a retry could deliver the same reply twice.
        res = await fetch(url, {
          method: "POST",
          headers: { authorization: `Bearer ${cfg.accessToken}`, "content-type": "application/json" },
          body,
          signal: joined.signal,
          redirect: "error",
        });
      } catch (err) {
        const aborted = joined.signal.aborted || /** @type {any} */ (err)?.name === "AbortError";
        log?.warn?.({ component: "idx-whatsapp-channel.cloud-api", event: "send-failed", reason: aborted ? "aborted" : "network" });
        throw new CloudApiError(aborted ? "aborted" : "network-error");
      }
      try {
        const raw = await res.text();
        parsed = raw.length <= MAX_RESPONSE_CHARS ? JSON.parse(raw) : undefined;
      } catch {
        parsed = undefined;
      }
    } finally {
      joined.release();
    }
    const status = typeof res?.status === "number" ? res.status : 0;
    if (!(status >= 200 && status < 300)) {
      const code = isPlainObject(parsed) && isPlainObject(parsed.error) ? parsed.error.code : undefined;
      const apiCode = Number.isSafeInteger(code) ? code : undefined;
      const reason = apiCode === OUTSIDE_WINDOW_API_CODE ? "outside-customer-service-window" : "api-error";
      log?.warn?.({ component: "idx-whatsapp-channel.cloud-api", event: "send-failed", reason, status, apiCode });
      throw new CloudApiError(reason, { status, apiCode });
    }
    const first = isPlainObject(parsed) && Array.isArray(parsed.messages) ? parsed.messages[0] : undefined;
    const id = isPlainObject(first) ? first.id : undefined;
    // A 2xx without a usable id still means the platform took the message; the gate's
    // audit records it as sent and then throws (outbound.mjs transmit).
    return typeof id === "string" && MESSAGE_ID_RE.test(id) ? { messageId: id } : {};
  }

  async function stop() {
    if (active !== null) {
      active.life.abort();
      active.pins.clear();
    }
    active = null;
    for (const done of [...pending]) done();
  }

  return Object.freeze({
    start,
    sendText,
    stop,
    isConfigured: () => configured,
    webhook: Object.freeze({ path: webhook.path, handle: webhook.handle, routeHandler }),
  });
}
