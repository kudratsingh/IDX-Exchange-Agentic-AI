/**
 * Fake transport for tests. Records every send and serves synthetic inbound
 * messages. Never imported by runtime code (a source test proves it).
 */

/** @typedef {import("../transport.mjs").Transport} Transport */
/** @typedef {import("../transport.mjs").InboundText} InboundText */

/**
 * @returns {Transport & {
 *   sent: Array<{ accountId: string, to: string, text: string }>,
 *   started: boolean,
 *   stopped: boolean,
 *   inbound(msg: InboundText): Promise<void>,
 *   failNextSend(err: Error): void,
 *   emptyReceiptNextSend(): void,
 * }}
 */
export function createFakeTransport() {
  /** @type {((msg: InboundText) => Promise<void>) | null} */
  let handler = null;
  /** @type {Error | null} */
  let nextError = null;
  let emptyReceipt = false;
  let counter = 0;

  const transport = {
    sent: [],
    started: false,
    stopped: false,
    async start({ onInbound }) {
      handler = onInbound;
      transport.started = true;
    },
    async sendText({ accountId, to, text }) {
      if (nextError) {
        const err = nextError;
        nextError = null;
        throw err;
      }
      transport.sent.push({ accountId, to, text });
      if (emptyReceipt) {
        emptyReceipt = false;
        return {};
      }
      counter += 1;
      return { messageId: `fake-${counter}` };
    },
    async stop() {
      transport.stopped = true;
    },
    isConfigured() {
      return true;
    },
    async inbound(msg) {
      if (!handler) throw new Error("fake transport not started");
      await handler(msg);
    },
    failNextSend(err) {
      nextError = err;
    },
    emptyReceiptNextSend() {
      emptyReceipt = true;
    },
  };
  return transport;
}
