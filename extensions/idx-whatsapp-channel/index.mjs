/**
 * Plugin entry. Hand-written (not defineChannelPluginEntry, which always calls
 * api.registerChannel) so the startup self-check can refuse registration.
 *
 * The verifier is a top-level static import: if the module is missing, this
 * entry fails to import and register() can never run.
 */

import { verifyReply } from "./verifier.mjs";
import { selfCheck } from "./self-check.mjs";
import { createChannelPlugin } from "./channel.mjs";
import { nullCardResolver } from "./card-resolver.mjs";
import { unavailableTransport } from "./transport.mjs";
import { PLUGIN_ID, REGISTER_MODES, SKIP_REGISTRATION_MODES } from "./constants.mjs";

export default {
  id: PLUGIN_ID,
  name: "IDX WhatsApp channel (owned send path)",
  description:
    "Project-owned WhatsApp DM channel on a verified outbound gate. Offline skeleton: no transport, no credentials.",
  configSchema: { type: "object", additionalProperties: false },

  /**
   * @param {{ config?: unknown, pluginConfig?: unknown, registrationMode?: string, logger?: any, registerChannel?: Function }} api
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
    api.registerChannel({
      plugin: createChannelPlugin({
        transport: unavailableTransport,
        cardResolver: nullCardResolver,
        verify: verifyReply,
        log: api.logger,
      }),
    });
  },
};
