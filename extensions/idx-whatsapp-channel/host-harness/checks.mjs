/**
 * Pure evaluation of one harness run's evidence (WO-037 real-host replay). No I/O; the
 * runner collects the evidence and this decides. Unit-tested in checks.test.mjs so the
 * rules hold without a live host: missing or timed-out evidence always fails.
 *
 *   L  the genuine WhatsApp turn was live when the replay was sent: the host's terminal
 *      record of the genuine run brackets the send time (startedAt <= sentAt <= endedAt),
 *      the fake model was still holding the genuine run's request, and the peer had
 *      received nothing yet;
 *   A  the genuine card call was admitted, ran exactly once, and exactly the expected card
 *      bytes (and nothing else) reached the peer;
 *   B  zero replay tool executions, L, and either an explicit host rejection of the
 *      chat.send or a recorded hook refusal of the replay's own card call whose run the
 *      host reports terminal within the deadline (a refusal in the log does not excuse a
 *      replay that never settled);
 *   C  L, and the genuine reply was delivered; the outcome is always named
 *      (delivered / cancelled-by-interrupt / replaced-by-safe-text / missing).
 */

/**
 * @param {{ mode: string, steps: object[], outbound: object[], toolExec: object[], hooks: object[],
 *   expectedCard: string | null, genuineRef: string | undefined, peer: string, safeText: string, replayRef: string }} e
 */
export function evaluate({ mode, steps, outbound, toolExec, hooks, expectedCard, genuineRef, peer, safeText, replayRef }) {
  const toPeer = outbound.filter((o) => o.to === peer);
  // Check A: the genuine card call was admitted, the tool ran exactly once for it, and
  // the peer received exactly the stored card bytes.
  const genuineHooks = hooks.filter((h) => h.params?.ref === genuineRef);
  const genuineExec = toolExec.filter((t) => t.ref === genuineRef);
  const cardDelivered = Boolean(expectedCard) && toPeer.some((o) => o.text === expectedCard);
  const A = {
    pass: Boolean(expectedCard) && genuineHooks.some((h) => h.decision?.block === false && h.decision?.marked === 1) && genuineExec.length === 1 && cardDelivered && !toPeer.some((o) => o.text !== expectedCard),
    admitted: genuineHooks.some((h) => h.decision?.block === false && h.decision?.marked === 1),
    genuineExecutions: genuineExec.length,
    cardDelivered,
  };
  // Check B: zero replay executions AND positive evidence the replay was stopped: an
  // explicit host rejection of the chat.send, or a recorded hook refusal of the replay's
  // own card call. No evidence (timeout, the replay never reached a tool) is a failure.
  const cs = steps.find((x) => x.chatSend)?.chatSend ?? null;
  const replayExec = toolExec.filter((t) => t.ref !== genuineRef);
  const replayHooks = hooks.filter((h) => h.params?.ref === replayRef);
  const hostRejected = cs?.ok === false;
  const hookRefused = replayHooks.length > 0 && replayHooks.every((h) => h.decision?.block === true);
  // L: the genuine WhatsApp turn was live when the replay was sent. Host side: the genuine
  // run's terminal record brackets the send time (startedAt <= sentAt <= endedAt). Harness
  // side: the fake model was holding its request and the peer had received nothing yet.
  const sent = steps.find((x) => x.replaySent)?.replaySent ?? null;
  const gt = steps.find((x) => x.genuineTerminal)?.genuineTerminal ?? null;
  const gtp = gt?.payload ?? null;
  const L =
    mode === "genuine-only"
      ? null
      : {
          pass:
            Boolean(sent) && sent.modelHeld >= 1 && sent.peerOutboundBefore === 0 &&
            typeof gtp?.startedAt === "number" && typeof gtp?.endedAt === "number" &&
            gtp.startedAt <= sent.sentAt && sent.sentAt <= gtp.endedAt,
          sentAt: sent?.sentAt ?? null,
          hostRunStartedAt: gtp?.startedAt ?? null,
          hostRunEndedAt: gtp?.endedAt ?? null,
          hostRunStatus: gtp?.status ?? (gt?.timeout ? "probe-timeout" : null),
          modelHeldAtSend: sent?.modelHeld ?? null,
          peerOutboundBeforeSend: sent?.peerOutboundBefore ?? null,
        };
  // The replay's own run must reach a terminal state the host reports within the deadline;
  // a logged hook refusal does not excuse a replay that never settled.
  const rt = steps.find((x) => x.replayTerminal)?.replayTerminal ?? null;
  const replaySettled = hostRejected || (rt?.ok === true && Boolean(rt?.payload) && rt.payload.status !== "timeout" && typeof rt.payload.endedAt === "number");
  const B =
    mode === "genuine-only"
      ? null
      : {
          pass: replayExec.length === 0 && L?.pass === true && (hostRejected || (hookRefused && replaySettled)),
          replaySettled,
          replayRunStatus: rt?.payload?.status ?? (rt?.timeout ? "probe-timeout" : rt ? "error" : hostRejected ? "rejected" : "never-ran"),
          replayExecutions: replayExec.length,
          evidence: hostRejected ? "host-rejected" : hookRefused ? "hook-refused" : replayHooks.length ? "hook-admitted" : "none",
          hookReasons: replayHooks.map((h) => h.decision?.reason ?? (h.decision?.block === false ? "admitted" : "unknown")),
        };
  // Check C: the genuine reply reached the peer and was not replaced by safeText. When the
  // host reports it interrupted the genuine run and nothing reached the peer, the outcome
  // is named "cancelled-by-interrupt" so the case stays visible as a cancelled reply.
  const interrupted = cs?.payload?.interruptedActiveRun === true;
  const genuineReply = cardDelivered ? "delivered" : toPeer.some((o) => o.text === safeText) ? "replaced-by-safe-text" : interrupted && toPeer.length === 0 ? "cancelled-by-interrupt" : "missing";
  const C = mode === "genuine-only" ? null : { pass: L?.pass === true && genuineReply === "delivered" && !toPeer.some((o) => o.text === safeText), genuineReply, interruptedActiveRun: interrupted };
  // interrupt-roles also requires the other cancel paths to be rejected and the user to
  // still be able to chat in its own session (positive control).
  if (mode === "interrupt-roles" && C) {
    const st = (k) => steps.find((x) => x[k])?.[k];
    C.otherCancelPathsRejected = st("chatAbort")?.ok === false && st("sessionsAbort")?.ok === false;
    C.ownSessionChatAllowed = st("ownSessionChatSend")?.ok === true;
    C.pass = C.pass && C.otherCancelPathsRejected && C.ownSessionChatAllowed;
  }
  const pass = A.pass && (L === null || L.pass) && (B === null || B.pass) && (C === null || C.pass);
  return { checks: { L, A, B, C }, genuineReply, pass };
}
