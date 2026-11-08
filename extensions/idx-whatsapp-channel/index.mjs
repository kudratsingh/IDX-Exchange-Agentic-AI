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
 *     also with no matcher: it renders an admitted card call's trusted result into the
 *     turn's card store (owned-channel install item 3, 2026-11-07).
 * When the host runtime surface is missing, the channel is still registered but has no
 * runner (every inbound is dropped "no-runner"), and the hook is not registered only when
 * `api.on` is absent; registration refuses instead if a runtime is present without `api.on`.
 *
 * The default export ships `unavailableTransport` and the turn-bound card resolver over the
 * process ingress (`createTurnCardResolver`): with no transport the channel reports
 * unconfigured and the host never starts it. Tests and the host harness build an entry
 * with their own transport (and, if they want, their own card resolver) through
 * `createPluginEntry`.
 */

import { verifyReply } from "./verifier.mjs";
import { selfCheck } from "./self-check.mjs";
import { createAfterToolCallHandler, createBeforeToolCallHandler, createChannelPlugin } from "./channel.mjs";
import { createIngress } from "./ingress.mjs";
import { createTurnCardResolver } from "./card-resolver.mjs";
import { unavailableTransport } from "./transport.mjs";
import { CHANNEL_ID, PLUGIN_ID, REGISTER_MODES, SKIP_REGISTRATION_MODES } from "./constants.mjs";

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
          api?.logger?.error?.({ component: "idx-whatsapp-channel.ingress", event: "dispatch-error" });
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
  "key", "record", "forTurn", "confirmRun", "endRun", "hasActiveTurn", "admitCardCall", "captureCards", "resolveCard", "size",
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

/**
 * `cardResolver` defaults to the turn-bound card store of the process ingress; a test or
 * the host harness may inject its own.
 * @param {{ transport?: import("./transport.mjs").Transport, cardResolver?: import("./card-resolver.mjs").CardResolver }} [deps]
 */
export function createPluginEntry({ transport = unavailableTransport, cardResolver } = {}) {
  return {
    id: PLUGIN_ID,
    name: "IDX WhatsApp channel (owned send path)",
    description:
      "Project-owned WhatsApp DM channel on a verified outbound gate. Offline skeleton: no transport, no credentials.",
    configSchema: { type: "object", additionalProperties: false },

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
      const check = selfCheck(api?.config, { verify: verifyReply });
      if (!check.ok) {
        api?.logger?.error?.(`${PLUGIN_ID}: refusing to register: ${check.reason}`);
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
      }
      api.registerChannel({
        plugin: createChannelPlugin({
          transport,
          cardResolver: cardResolver ?? createTurnCardResolver(ingress),
          verify: verifyReply,
          log: api.logger,
          ingress,
          ...(runner ?? {}),
        }),
      });
    },
  };
}

export default createPluginEntry();
