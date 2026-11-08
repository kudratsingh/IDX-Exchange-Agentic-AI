/**
 * Plugin entry. Hand-written (not defineChannelPluginEntry, which always calls
 * api.registerChannel) so the startup self-check can refuse registration.
 *
 * The verifier is a top-level static import: if the module is missing, this
 * entry fails to import and register() can never run.
 *
 * Host wiring (WO-037 real-host replay, 2026-11-07, OpenClaw 2026.9.5):
 *   - one ingress per process (`processIngress`) is shared by the channel and the
 *     card-tool hook, across every register() call and every loaded copy of this module;
 *   - `resolveRoute` uses `api.runtime.channel.routing.resolveAgentRoute`;
 *   - `runInbound` builds a direct-DM inbound context with
 *     `api.runtime.channel.reply.finalizeInboundContext` and dispatches it through
 *     `api.runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher`, passing the
 *     channel's `replyOptions` (`runId`, `onAgentRunStart`) through unchanged and the
 *     channel's own `deliver` as the dispatcher's deliver;
 *   - `createBeforeToolCallHandler(ingress)` is registered with `api.on("before_tool_call")`
 *     with no matcher, so every tool call reaches it and the card-tool test runs in code;
 *   - `createAfterToolCallHandler(ingress)` is registered with `api.on("after_tool_call")`,
 *     also with no matcher: it renders an admitted card call's trusted outcome into the
 *     turn's reply store (owned-channel install item 3, 2026-11-07; complete reply token,
 *     2026-11-08);
 *   - `createBeforePromptBuildHandler(ingress)` is registered with
 *     `api.on("before_prompt_build")`: it adds REPLY_INSTRUCTION to the system prompt of a
 *     live WhatsApp run only. On 2026.9.5 a non-bundled plugin needs
 *     `plugins.entries.idx-whatsapp-channel.hooks.allowConversationAccess: true` for this
 *     hook (docs/plugins/hooks.md:125-133). Its registration is best effort: if the host
 *     refuses it, the channel still registers (the instruction changes no gate; card turns
 *     then reply SAFE_TEXT) and one `prompt-hook-unavailable` line is logged.
 * When the host runtime surface is missing, the channel is still registered but has no
 * runner (every inbound is dropped "no-runner"), and the hook is not registered only when
 * `api.on` is absent; registration refuses instead if a runtime is present without `api.on`.
 *
 * The default export uses the turn-bound card resolver over the process ingress
 * (`createTurnCardResolver`) and, by default, `unavailableTransport`: with no transport the
 * channel reports unconfigured and the host never starts it. Tests and the host harness
 * build an entry with their own transport (and, if they want, their own card resolver)
 * through `createPluginEntry`.
 *
 * Cloud API wiring (WO-039), OFF by default. The plugin's own config (`api.pluginConfig`,
 * checked by the host against the manifest `configSchema`, and again here) may hold one
 * block, `cloudApi: { enabled, credentialsFile, listen: { host, port } }`, with no secret
 * in it. Without the block, or with `enabled` anything but the boolean `true`, the entry
 * behaves exactly as before. With it, `register` reads and checks the owner's credentials
 * file (`readOwnerCredentialsFile`; again on every register, so a changed file is refused
 * `credentials-changed` instead of being ignored), builds ONE Cloud API transport and ONE
 * loopback webhook listener for the whole process behind a frozen process-wide key
 * (`processCloudApi`), and
 * hands the channel a transport that binds the listener when the account starts and
 * closes it when the account stops (`createListenerBoundTransport`). Every refusal fails
 * closed: the channel registers with `unavailableTransport` (unconfigured, never sends) and
 * one `cloud-api-refused` error line with a fixed reason is logged, never a path or value.
 * `createPluginEntry({ cloudApiDeps: { fetch, now, readCredentials } })` is the test seam
 * (the harness injects a fake Graph API `fetch`); the default export injects nothing.
 */

import { createHash } from "node:crypto";

import { verifyReply } from "./verifier.mjs";
import { selfCheck } from "./self-check.mjs";
import { createAfterToolCallHandler, createBeforePromptBuildHandler, createBeforeToolCallHandler, createChannelPlugin } from "./channel.mjs";
import { createIngress } from "./ingress.mjs";
import { createTurnCardResolver } from "./card-resolver.mjs";
import { unavailableTransport } from "./transport.mjs";
import { createCloudApiTransport, readCloudApiConfig } from "./cloud-api-transport.mjs";
import { LOOPBACK_HOSTS, createListenerBoundTransport, createWebhookListener, readOwnerCredentialsFile } from "./cloud-api-wiring.mjs";
import { CHANNEL_ID, PLUGIN_ID, REGISTER_MODES, SKIP_REGISTRATION_MODES } from "./constants.mjs";

/**
 * A logger the real host accepts and that never throws. OpenClaw 2026.9.5's plugin logger
 * takes a string: given an object it threw "text.includes is not a function" (real-host
 * harness, WO-039, 2026-11-08), which turned every Cloud API webhook answer into a 500 and
 * would have dropped every audit line. The plugin logs fixed, content-free fields (never a
 * text, peer, id, path or secret); this hands them to the host logger as they are and, when
 * that throws, sends the same fields once more as one JSON line, and sends JSON lines from
 * then on. A logger that throws on everything is silenced. A missing method is a no-op.
 * @param {any} base the host's `api.logger`
 * @returns {Readonly<{ info: Function, warn: Function, error: Function }>}
 */
export function hostSafeLogger(base) {
  let strings = false;
  const emit = (level) => (message, ...rest) => {
    try {
      const fn = base?.[level];
      if (typeof fn !== "function") return;
      const structured = message !== null && typeof message === "object";
      if (strings && structured) {
        fn.call(base, JSON.stringify(message));
        return;
      }
      try {
        fn.call(base, message, ...rest);
      } catch (err) {
        if (!structured) throw err;
        strings = true;
        fn.call(base, JSON.stringify(message));
      }
    } catch {
      /* a log line never changes registration, a turn, an answer or a send */
    }
  };
  return Object.freeze({ info: emit("info"), warn: emit("warn"), error: emit("error") });
}

/**
 * The host runner pair, or null when the host runtime surface is not there.
 * @param {any} api
 */
export function createHostRunner(api) {
  const rt = api?.runtime?.channel;
  const resolveAgentRoute = rt?.routing?.resolveAgentRoute;
  const finalizeInboundContext = rt?.reply?.finalizeInboundContext;
  const dispatch = rt?.reply?.dispatchReplyWithBufferedBlockDispatcher;
  if (typeof resolveAgentRoute !== "function" || typeof finalizeInboundContext !== "function" || typeof dispatch !== "function") {
    return null;
  }
  /** @type {import("./channel.mjs").RouteResolver} */
  const resolveRoute = ({ cfg, channel, accountId, peer }) => {
    const r = resolveAgentRoute({ cfg, channel, accountId, peer });
    return { agentId: r.agentId, sessionKey: r.sessionKey };
  };
  /** @type {import("./channel.mjs").InboundRunner} */
  const runInbound = async ({ cfg, sessionKey, accountId, peerId, text, messageId, deliver, replyOptions }) => {
    const ctx = finalizeInboundContext({
      Body: text,
      BodyForAgent: text,
      RawBody: text,
      CommandBody: text,
      From: peerId,
      To: peerId,
      SenderId: peerId,
      SessionKey: sessionKey,
      AccountId: accountId,
      ChatType: "direct",
      Provider: CHANNEL_ID,
      Surface: CHANNEL_ID,
      OriginatingChannel: CHANNEL_ID,
      OriginatingTo: peerId,
      ConversationRoutePeerId: peerId,
      NativeDirectUserId: peerId,
      MessageSid: messageId,
      Timestamp: Date.now(),
      CommandAuthorized: false,
    });
    await dispatch({
      ctx,
      cfg,
      replyOptions,
      dispatcherOptions: {
        deliver: (payload, info) => deliver(payload, info),
        onError: () => {
          hostSafeLogger(api?.logger).error({ component: "idx-whatsapp-channel.ingress", event: "dispatch-error" });
        },
      },
    });
  };
  return { resolveRoute, runInbound };
}

/** Process-wide key for the one ingress every loaded copy of this entry shares. */
const INGRESS_KEY = Symbol.for("idx-whatsapp-channel.ingress.v1");

/** The ingress members every copy relies on; a value at the key without them is refused. */
const INGRESS_MEMBERS = Object.freeze([
  "key", "record", "forTurn", "confirmRun", "endRun", "hasActiveTurn", "admitCardCall", "captureReply", "replySections", "issuedRun",
  "beginAccountEpoch", "accountEpoch", "endAccountEpoch", "size",
]);

/**
 * The one ingress for this process. The host registers a plugin more than once in one
 * gateway (a "full" and a "discovery" pass were seen on OpenClaw 2026.9.5), from separately
 * loaded copies of the module, and every copy's card-tool hook stays registered while only
 * one copy's channel records turns. With an ingress per register call or per module copy,
 * the other copy's hook refused every genuine card call "unknown-run", and a refusal is
 * sticky (real-host harness, 2026-11-07). A process-wide ingress makes every copy's hook
 * read the run map the active channel writes.
 *
 * The ingress is frozen, and the global property is non-writable and non-configurable, so
 * no member can be replaced and the key cannot be re-pointed once set. A value already at
 * the key that is not a frozen object with every ingress member as a function is refused
 * (registration throws), so a malformed pre-seeded value is not used.
 *
 * Residual (send-boundary review, 2026-11-07): any code running in the gateway process can
 * reach this object through the well-known key and call its methods, for example mint and
 * confirm a run of its own and have the hook admit card calls for it, or pre-seed a
 * well-formed look-alike before the first register. That is the same trust boundary as
 * any in-process plugin code, which can also patch host internals; it is recorded as an
 * install residual, not closed here.
 */
export function processIngress() {
  const g = /** @type {any} */ (globalThis);
  if (!Object.prototype.hasOwnProperty.call(g, INGRESS_KEY)) {
    Object.defineProperty(g, INGRESS_KEY, { value: Object.freeze(createIngress()), writable: false, configurable: false, enumerable: false });
  }
  const found = g[INGRESS_KEY];
  const wellFormed =
    found !== null &&
    typeof found === "object" &&
    Object.isFrozen(found) &&
    INGRESS_MEMBERS.every((m) => typeof found[m] === "function");
  if (!wellFormed) throw new Error(`${PLUGIN_ID}: refusing to register: process ingress malformed`);
  return found;
}

/** @param {any} o */
function deepFreeze(o) {
  if (o !== null && typeof o === "object") {
    for (const v of Object.values(o)) deepFreeze(v);
    Object.freeze(o);
  }
  return o;
}

/** The lowest listener port the config accepts: an unprivileged, fixed port the tunnel targets. */
export const CLOUD_API_MIN_PORT = 1024;
/** The longest credentials-file path the config accepts. */
export const CLOUD_API_MAX_PATH_LENGTH = 4096;

/**
 * The plugin's own config schema; the manifest's `configSchema` is the same object (a test
 * pins them equal). Strict at every level. The `cloudApi` block names where the owner's
 * credentials file is and where the loopback listener binds; it never holds a secret
 * (`pluginConfig` is not a place for secrets).
 */
export const PLUGIN_CONFIG_SCHEMA = deepFreeze({
  type: "object",
  additionalProperties: false,
  properties: {
    cloudApi: {
      type: "object",
      additionalProperties: false,
      required: ["enabled"],
      properties: {
        enabled: { type: "boolean" },
        credentialsFile: { type: "string", minLength: 2, maxLength: CLOUD_API_MAX_PATH_LENGTH, pattern: "^/" },
        listen: {
          type: "object",
          additionalProperties: false,
          required: ["host", "port"],
          properties: {
            host: { type: "string", enum: [...LOOPBACK_HOSTS] },
            port: { type: "integer", minimum: CLOUD_API_MIN_PORT, maximum: 65535 },
          },
        },
      },
    },
  },
});

/** A plain object (or one with no prototype), never an array or a class instance.
 *  @param {unknown} v @returns {v is Record<string, unknown>} */
const isPlainObject = (v) => {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
};

/** Each own key of `o` read exactly once, so a getter cannot answer twice. @param {Record<string, unknown>} o */
function snapshot(o) {
  /** @type {Record<string, unknown>} */
  const out = {};
  for (const k of Object.keys(o)) out[k] = o[k];
  return out;
}

const CLOUD_API_OFF = Object.freeze({ state: "off" });

/**
 * The `cloudApi` block of the plugin's own config, read once:
 *   - `{ state: "off" }` when `pluginConfig` or the block is absent or not a plain object, or
 *     `enabled` is anything but the boolean `true` (the string "true" included): the entry
 *     then behaves exactly as without the block;
 *   - `{ state: "refused", reason: "bad-config" }` when it is enabled but holds an unknown
 *     key, a `credentialsFile` that is not an absolute path string, or a `listen` that is
 *     not exactly `{ host: "127.0.0.1" | "::1", port: <integer 1024-65535> }`;
 *   - else `{ state: "on", credentialsFile, host, port }`, frozen.
 * Never throws; never reports which field failed.
 * @param {unknown} pluginConfig
 */
export function readCloudApiBlock(pluginConfig) {
  try {
    if (!isPlainObject(pluginConfig) || !Object.prototype.hasOwnProperty.call(pluginConfig, "cloudApi")) return CLOUD_API_OFF;
    const raw = pluginConfig.cloudApi;
    if (!isPlainObject(raw)) return CLOUD_API_OFF;
    const block = snapshot(raw);
    if (block.enabled !== true) return CLOUD_API_OFF;
    const refused = Object.freeze({ state: "refused", reason: "bad-config" });
    const keys = Object.keys(block).sort();
    if (keys.join(",") !== "credentialsFile,enabled,listen") return refused;
    const file = block.credentialsFile;
    if (typeof file !== "string" || file.length < 2 || file.length > CLOUD_API_MAX_PATH_LENGTH || !file.startsWith("/") || file.includes("\0")) return refused;
    if (!isPlainObject(block.listen)) return refused;
    const listen = snapshot(block.listen);
    if (Object.keys(listen).sort().join(",") !== "host,port") return refused;
    const { host, port } = listen;
    if (typeof host !== "string" || !LOOPBACK_HOSTS.includes(host)) return refused;
    if (!Number.isInteger(port) || /** @type {number} */ (port) < CLOUD_API_MIN_PORT || /** @type {number} */ (port) > 65535) return refused;
    return Object.freeze({ state: "on", credentialsFile: file, host, port: /** @type {number} */ (port) });
  } catch {
    return Object.freeze({ state: "refused", reason: "bad-config" });
  }
}

/** Process-wide key for the one Cloud API transport (and its listener) every copy shares. */
const CLOUD_API_KEY = Symbol.for("idx-whatsapp-channel.cloud-api.v1");
/** The members the shared value's transport must have, as functions. */
const TRANSPORT_MEMBERS = Object.freeze(["start", "sendText", "stop", "isConfigured"]);
/** A credentials-file refusal reason as `readOwnerCredentialsFile` writes it. */
const CREDENTIALS_REASON_RE = /^[a-z][a-z-]{0,39}$/u;

/**
 * The fixed reason for a credentials refusal: the reader's own reason when it is one,
 * else "credentials-unreadable". Never a message, path or value.
 * @param {unknown} err
 */
function credentialsReason(err) {
  const e = /** @type {any} */ (err);
  try {
    if (e?.name === "CredentialsFileError" && typeof e.reason === "string" && CREDENTIALS_REASON_RE.test(e.reason)) return `credentials-${e.reason}`;
  } catch {
    /* fall through */
  }
  return "credentials-unreadable";
}

/**
 * Whether a value at the process key is one this entry would have written: a frozen
 * object holding a string `fingerprint`, a string `credentialsDigest` and a frozen
 * `sendPath` with the four Transport members.
 * @param {unknown} v
 */
function wellFormedCloudApi(v) {
  try {
    const o = /** @type {any} */ (v);
    return (
      o !== null && typeof o === "object" && Object.isFrozen(o) &&
      typeof o.fingerprint === "string" &&
      typeof o.credentialsDigest === "string" &&
      o.sendPath !== null && typeof o.sendPath === "object" && Object.isFrozen(o.sendPath) &&
      TRANSPORT_MEMBERS.every((m) => typeof o.sendPath[m] === "function")
    );
  } catch {
    return false;
  }
}

/** The credential fields a digest covers, in a fixed order. */
const DIGEST_FIELDS = Object.freeze(["accountId", "phoneNumberId", "graphApiVersion", "accessToken", "appSecret", "verifyToken", "webhookPath"]);

/**
 * The owner's credentials file, read and checked now, with a SHA-256 digest of its
 * validated values (never the values themselves leave this function except as the
 * config the transport is built from). Every register calls this, so a file that changed
 * since the process transport was built is noticed (`credentials-changed`, below).
 * @param {string} file
 * @param {{ readCredentials?: (p: string) => unknown }} deps
 * @returns {{ ok: true, config: unknown, digest: string } | { ok: false, reason: string }}
 */
function readCredentialsWithDigest(file, deps) {
  let config;
  try {
    config = (deps.readCredentials ?? readOwnerCredentialsFile)(file);
  } catch (err) {
    return { ok: false, reason: credentialsReason(err) };
  }
  const valid = readCloudApiConfig(config);
  if (valid === null) return { ok: false, reason: "implausible-credentials" };
  const digest = createHash("sha256").update(JSON.stringify(DIGEST_FIELDS.map((k) => valid[k])), "utf8").digest("hex");
  return { ok: true, config, digest };
}

/**
 * The one Cloud API transport for this process, or a refusal. Called from `register` only
 * when the `cloudApi` block is on. The host registers this plugin more than once in one
 * gateway, from separately loaded copies of this module (WO-037), and only one copy's
 * channel starts; a transport and listener per copy would leave the listener feeding a
 * channel that never runs. So the first register that gets this far builds the transport
 * over `fetch` (the global one unless a test injects one), builds the loopback listener on
 * the configured host and port, and stores `{ fingerprint, credentialsDigest, sendPath }`
 * frozen behind a non-writable, non-configurable key, as `processIngress` does. Every later
 * register, in any copy, gets that same transport, provided it names the same file, host
 * and port (`config-mismatch` otherwise) AND the file still holds the same values.
 *
 * Every register reads and checks the credentials file again (WO-039 review): the host
 * can re-register the plugin inside a running process (a hot reload that replaces the
 * plugin instance, an in-process SIGUSR1 or /restart), and the transport keeps the
 * values it was built with. A rotated secret must never stay in force silently, so a
 * file whose validated values differ from the ones the transport holds is refused
 * `credentials-changed` (unconfigured, one line); only a fresh process picks up new
 * values. A file that now fails its checks is refused with its own reason. The
 * fingerprint and the shape of a value already at the key are judged before the file is
 * read, so a malformed or mismatched value is refused with the file unread.
 *
 * A refusal stores nothing, so the next register tries again (and logs again). A value
 * already at the key that is not well formed is refused (`process-state-malformed`).
 * Same residual as the ingress: other code in the gateway process can reach the transport
 * through the well-known key.
 *
 * Reasons: `credentials-<reader reason>` (for example `credentials-permissions-too-open`),
 * `credentials-unreadable`, `credentials-changed`, `no-fetch`, `implausible-credentials`,
 * `listener-refused`, `process-state-malformed`, `config-mismatch`.
 * @param {{ credentialsFile: string, host: string, port: number }} block
 * @param {{ fetch?: Function, now?: () => number, readCredentials?: (p: string) => unknown }} deps
 * @param {any} log
 * @returns {{ ok: true, sendPath: import("./transport.mjs").Transport } | { ok: false, reason: string }}
 */
export function processCloudApi(block, deps, log) {
  const g = /** @type {any} */ (globalThis);
  const fingerprint = JSON.stringify([block.credentialsFile, block.host, block.port]);
  if (Object.prototype.hasOwnProperty.call(g, CLOUD_API_KEY)) {
    const found = g[CLOUD_API_KEY];
    if (!wellFormedCloudApi(found)) return { ok: false, reason: "process-state-malformed" };
    if (found.fingerprint !== fingerprint) return { ok: false, reason: "config-mismatch" };
    const read = readCredentialsWithDigest(block.credentialsFile, deps);
    if (!read.ok) return read;
    // Digests of high-entropy values compared in process; no remote party can time this.
    if (read.digest !== found.credentialsDigest) return { ok: false, reason: "credentials-changed" };
    return { ok: true, sendPath: found.sendPath };
  }
  const read = readCredentialsWithDigest(block.credentialsFile, deps);
  if (!read.ok) return read;
  const fetchFn = deps.fetch ?? g.fetch;
  if (typeof fetchFn !== "function") return { ok: false, reason: "no-fetch" };
  let cloud;
  try {
    cloud = createCloudApiTransport({ config: read.config, fetch: fetchFn, log, ...(typeof deps.now === "function" ? { now: deps.now } : {}) });
  } catch {
    return { ok: false, reason: "implausible-credentials" };
  }
  if (cloud.isConfigured() !== true) return { ok: false, reason: "implausible-credentials" };
  let bound;
  try {
    const listener = createWebhookListener({ handler: cloud.webhook.routeHandler, host: block.host, port: block.port, path: cloud.webhook.path, log });
    bound = createListenerBoundTransport({ cloud, listener });
  } catch {
    return { ok: false, reason: "listener-refused" };
  }
  // No await since the hasOwnProperty test, so no other register can have set the key.
  const value = Object.freeze({ fingerprint, credentialsDigest: read.digest, sendPath: bound });
  Object.defineProperty(g, CLOUD_API_KEY, { value, writable: false, configurable: false, enumerable: false });
  return { ok: true, sendPath: value.sendPath };
}

/**
 * The transport for this register call when no transport was injected: the process Cloud
 * API transport when the block is on and nothing refuses, else `unavailableTransport`.
 * Logs one `cloud-api-refused` error line per refusal, with the fixed reason only.
 * @param {any} api @param {{ fetch?: Function, now?: () => number, readCredentials?: (p: string) => unknown }} deps
 * @param {ReturnType<typeof hostSafeLogger>} log
 */
function cloudApiSendPath(api, deps, log) {
  const block = readCloudApiBlock(api?.pluginConfig);
  if (block.state === "off") return unavailableTransport;
  const got = block.state === "on" ? processCloudApi(block, deps, log) : { ok: false, reason: block.reason };
  if (got.ok) return got.sendPath;
  log.error({ component: "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason: got.reason });
  return unavailableTransport;
}

/**
 * `cardResolver` defaults to the turn-bound reply store of the process ingress; a test or
 * the host harness may inject its own. With no `transport`, the send path comes from the
 * plugin's own `cloudApi` block (off by default: `unavailableTransport`); `cloudApiDeps`
 * injects the Graph API `fetch`, the clock and the credentials reader for tests and the
 * harness. An injected `transport` and `cloudApiDeps` together are refused.
 * @param {{ transport?: import("./transport.mjs").Transport, cardResolver?: import("./card-resolver.mjs").CardResolver,
 *   cloudApiDeps?: { fetch?: Function, now?: () => number, readCredentials?: (p: string) => unknown } }} [deps]
 */
export function createPluginEntry({ transport, cardResolver, cloudApiDeps } = {}) {
  if (transport !== undefined && cloudApiDeps !== undefined) {
    throw new Error(`${PLUGIN_ID}: createPluginEntry takes a transport or cloudApiDeps, not both`);
  }
  const cloudDeps = Object.freeze({ ...(cloudApiDeps ?? {}) });
  return {
    id: PLUGIN_ID,
    name: "IDX WhatsApp channel (owned send path)",
    description:
      "Project-owned WhatsApp DM channel on a verified outbound gate. Cloud API send path off unless the plugin config enables it.",
    configSchema: PLUGIN_CONFIG_SCHEMA,

    /**
     * @param {{ config?: unknown, pluginConfig?: unknown, registrationMode?: string, logger?: any,
     *   registerChannel?: Function, on?: Function, runtime?: any }} api
     */
    register(api) {
      const mode = api?.registrationMode ?? "full";
      if (SKIP_REGISTRATION_MODES.includes(mode)) return;
      if (!REGISTER_MODES.includes(mode)) {
        throw new Error(`${PLUGIN_ID}: refusing to register: unknown registration mode`);
      }
      // Every line this plugin logs goes through the host-safe logger (string-only host).
      const log = hostSafeLogger(api?.logger);
      const check = selfCheck(api?.config, { verify: verifyReply });
      if (!check.ok) {
        log.error(`${PLUGIN_ID}: refusing to register: ${check.reason}`);
        throw new Error(`${PLUGIN_ID}: refusing to register: ${check.reason}`);
      }
      if (typeof api?.registerChannel !== "function") {
        throw new Error(`${PLUGIN_ID}: refusing to register: registerChannel unavailable`);
      }
      const runner = createHostRunner(api);
      // A host that can run turns must also take the card-tool hook: a runner without the
      // hook would let card tools execute unbound.
      if (runner && typeof api.on !== "function") {
        throw new Error(`${PLUGIN_ID}: refusing to register: before_tool_call hook unavailable`);
      }
      const ingress = processIngress();
      // The hooks first: if registering one throws, no channel has been registered, so a
      // channel can never run turns with card tools ungated (send-boundary review).
      if (typeof api.on === "function") {
        api.on("before_tool_call", createBeforeToolCallHandler(ingress));
        api.on("after_tool_call", createAfterToolCallHandler(ingress));
        // Best effort, after the two gating hooks: the instruction only tells the model
        // which token to write; every release is still decided by the verifier.
        try {
          api.on("before_prompt_build", createBeforePromptBuildHandler(ingress));
        } catch {
          log.warn({ component: "idx-whatsapp-channel.entry", event: "prompt-hook-unavailable" });
        }
      }
      // After the hooks: a refusal here leaves the channel unconfigured, never ungated.
      const sendPath = transport ?? cloudApiSendPath(api, cloudDeps, log);
      api.registerChannel({
        plugin: createChannelPlugin({
          transport: sendPath,
          cardResolver: cardResolver ?? createTurnCardResolver(ingress),
          verify: verifyReply,
          log,
          ingress,
          ...(runner ?? {}),
        }),
      });
    },
  };
}

export default createPluginEntry();
