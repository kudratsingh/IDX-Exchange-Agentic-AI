/**
 * Transport seam. The real WhatsApp transport (deferred: Baileys, Cloud API or
 * other, with its credentials) implements this interface later. The runtime may
 * use exactly the four members listed in TRANSPORT_METHODS; a source test and a
 * Proxy test pin that.
 */

/**
 * @typedef {{ accountId: string, peerId: string, text: string, messageId: string, receivedAt: number }} InboundText
 * @typedef {{
 *   start(opts: { accountId: string, signal?: AbortSignal, onInbound: (msg: InboundText) => Promise<void>,
 *     acceptsSender?: (peerId: string) => boolean }): Promise<void>,
 *   sendText(req: { accountId: string, to: string, text: string, signal?: AbortSignal }): Promise<{ messageId: string }>,
 *   stop(): Promise<void>,
 *   isConfigured(): boolean,
 * }} Transport
 */

export const NO_TRANSPORT_MESSAGE = "idx-whatsapp-channel: no transport configured (deferred)";

function unavailable() {
  return Promise.reject(new Error(NO_TRANSPORT_MESSAGE));
}

/** The default. Reports unconfigured, and every operation rejects. */
/** @type {Transport} */
export const unavailableTransport = Object.freeze({
  start: unavailable,
  sendText: unavailable,
  stop: unavailable,
  isConfigured: () => false,
});
