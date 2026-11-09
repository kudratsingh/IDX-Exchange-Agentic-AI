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
 *
 * Mode cloud-api (WO-039) adds `evaluateCloudApi`, below: S startup, W signed delivery,
 * G the one Graph API send, U unsigned and tampered POSTs, N a sender outside the
 * allowlist, R a held turn across a channel reload, X gateway shutdown.
 */

/**
 * @param {{ mode: string, steps: object[], outbound: object[], toolExec: object[], hooks: object[],
 *   expectedCard: string | null, genuineRef: string | undefined, peer: string, safeText: string, replayRef: string }} e
 */
/** Modes with no dashboard replay: L, B and C do not apply. */
const NO_REPLAY_MODES = new Set(["genuine-only", "not-allowlisted", "payloads", "cloud-api"]);

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
    NO_REPLAY_MODES.has(mode)
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
    NO_REPLAY_MODES.has(mode)
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
  const C = NO_REPLAY_MODES.has(mode) ? null : { pass: L?.pass === true && genuineReply === "delivered" && !toPeer.some((o) => o.text === safeText), genuineReply, interruptedActiveRun: interrupted };
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

/** The exact Graph API request body for one text reply (WO-038 interface). */
function expectedSendBody(to, body) {
  return JSON.stringify({ messaging_product: "whatsapp", recipient_type: "individual", to, type: "text", text: { preview_url: false, body } });
}

/**
 * Mode cloud-api (WO-039): the production Cloud API wiring on the real host, with a
 * synthetic owner credentials file and a fake Graph API fetch. Pure; every missing or
 * timed-out piece of evidence fails the check it belongs to.
 *
 *   S  startup: the plugin's listener logged `listener-started`, accepted a TCP connection
 *      on its loopback port, answered Meta's verification GET with the challenge, and a
 *      signed statuses-only POST got 200 (not 503) within the deadline, so the account
 *      had started and the transport held the inbound sink;
 *      S also requires that no `cloud-api-refused` line was logged, neither by startup
 *      nor at any point of the run (`refusals`, from the whole audit log): a register that
 *      refused, in any module copy, is the owner smoke's abort signal even when another
 *      copy's channel works;
 *   W  signed delivery: the signed genuine DM got 200, its card call was admitted by the
 *      production hook and the card tool ran exactly once for it;
 *   G  exactly one Graph API request before the reload, a POST to the expected URL with
 *      the synthetic bearer, JSON content type, `redirect: "error"` and an abort signal,
 *      whose body is exactly the expected JSON with `text.body` equal to the
 *      server-approved reply AND to the channel renderer's reply (the payload sweep's two
 *      oracles);
 *   U  the unsigned and the tampered POST each got 401, and neither reached the model, the
 *      card hook or the tool;
 *   N  a signed DM from a sender outside the allowlist got 200 and then nothing: no model
 *      request, no hook call, no Graph API request;
 *   R  reload: a genuine turn was held live by the model when a `channels.whatsapp` edit
 *      asked the host to restart the channel; the listener then stopped and started again,
 *      the account answered 200 again, nothing reached the Graph API while it was down,
 *      and the peer's next DM made exactly one request with the exact expected body. The
 *      held turn's reply must be one of the two correct outcomes, and which one is named:
 *      the host deferred the restart until the turn ended (OpenClaw 2026.9.5 does), so the
 *      reply went out once, exactly, before the stop; or the host restarted at once, so
 *      the reply was withheld `untrusted-turn` with zero requests. R also accounts for the
 *      WHOLE Graph API log before the stop: it must hold exactly the genuine send, the held
 *      turn's sends and the next turn's send, so an extra or duplicate send in any gap
 *      between the recorded windows (after the restart, after the next turn) fails;
 *   X  shutdown: the gateway exited after SIGTERM, the account stop reached the plugin
 *      (`listener-stopped` at or after the SIGTERM), the listener port then refused
 *      connections, and no Graph API request was recorded at or after the SIGTERM.
 * @param {{ steps: object[], graph: object[], modelRequests: object[], hooks: object[], toolExec: object[],
 *   expected: { url: string, authorization: string, peerWa: string, approved: string | null, rendered: string | null },
 *   markers: { unsigned: string, tampered: string, stranger: string }, genuineRef: string | undefined,
 *   refusals: string[] }} e
 */
export function evaluateCloudApi({ steps, graph, modelRequests, hooks, toolExec, expected, markers, genuineRef, refusals }) {
  const st = (k) => steps.find((x) => x && typeof x === "object" && k in x)?.[k] ?? null;
  const startup = st("startup");
  const startupRefusals = Array.isArray(startup?.refusals) ? startup.refusals : null;
  const runRefusals = Array.isArray(refusals) ? refusals : null;
  const S = {
    pass:
      startup?.listenerStartedLogged === true && startup?.accepting === true && startup?.verifyStatus === 200 && startup?.verifyEchoed === true && startup?.ready === true &&
      startupRefusals !== null && startupRefusals.length === 0 && runRefusals !== null && runRefusals.length === 0,
    listenerStartedLogged: startup?.listenerStartedLogged ?? null,
    accepting: startup?.accepting ?? null,
    verifyStatus: startup?.verifyStatus ?? null,
    ready: startup?.ready ?? null,
    refusals: runRefusals === null || startupRefusals === null ? null : [...new Set([...startupRefusals, ...runRefusals])],
  };
  const signed = st("signedGenuine");
  const genuineHooks = hooks.filter((h) => genuineRef !== undefined && h.params?.ref === genuineRef);
  const admitted = genuineHooks.some((h) => h.decision?.block === false && h.decision?.marked === 1);
  const genuineExec = toolExec.filter((t) => genuineRef !== undefined && t.ref === genuineRef).length;
  const W = { pass: signed?.status === 200 && admitted && genuineExec === 1, status: signed?.status ?? null, admitted, genuineExecutions: genuineExec };

  const shutdown = st("shutdown");
  const reload = st("reload");
  const stopAt = typeof shutdown?.stopAt === "number" ? shutdown.stopAt : null;
  const reloadAt = typeof reload?.reloadAt === "number" ? reload.reloadAt : null;
  // G judges the genuine phase: everything before the reload (or, without one, the stop).
  const cut = reloadAt ?? stopAt;
  const beforeStop = cut === null ? graph : graph.filter((g) => typeof g.at === "number" && g.at < cut);
  const afterStop = stopAt === null ? [] : graph.filter((g) => typeof g.at !== "number" || g.at >= stopAt);
  const one = beforeStop.length === 1 ? beforeStop[0] : null;
  let body = null;
  try {
    body = one && typeof one.body === "string" ? JSON.parse(one.body) : null;
  } catch {
    body = null;
  }
  const sentText = typeof body?.text?.body === "string" ? body.text.body : null;
  const oraclesAgree = typeof expected?.approved === "string" && expected.approved === expected.rendered;
  const G = {
    pass:
      one !== null && oraclesAgree &&
      one.url === expected.url && one.method === "POST" && one.redirect === "error" && one.hasSignal === true &&
      one.headers?.authorization === expected.authorization && one.headers?.["content-type"] === "application/json" &&
      one.body === expectedSendBody(expected.peerWa, expected.approved) && sentText === expected.approved && sentText === expected.rendered,
    requestsBeforeStop: beforeStop.length,
    urlMatches: one ? one.url === expected?.url : null,
    bearerMatches: one ? one.headers?.authorization === expected?.authorization : null,
    bodyExact: one ? one.body === expectedSendBody(expected?.peerWa, expected?.approved) : null,
    textEqualsApproved: sentText !== null && sentText === expected?.approved,
    textEqualsRendered: sentText !== null && sentText === expected?.rendered,
  };

  const reached = (marker) => ({
    model: modelRequests.filter((m) => m.marker === marker).length,
    hooks: hooks.filter((h) => typeof h.params?.ref === "string" && h.params.ref === marker.replace(/^GENUINE-/u, "genuine-")).length,
    tools: toolExec.filter((t) => typeof t.ref === "string" && t.ref === marker.replace(/^GENUINE-/u, "genuine-")).length,
  });
  const unsigned = st("unsignedPost");
  const tampered = st("tamperedPost");
  const ru = reached(markers.unsigned);
  const rt = reached(markers.tampered);
  const U = {
    pass: unsigned?.status === 401 && tampered?.status === 401 && ru.model + ru.hooks + ru.tools === 0 && rt.model + rt.hooks + rt.tools === 0,
    unsignedStatus: unsigned?.status ?? null,
    tamperedStatus: tampered?.status ?? null,
    reachedHost: ru.model + ru.hooks + ru.tools + rt.model + rt.hooks + rt.tools,
  };
  const stranger = st("strangerPost");
  const rs = reached(markers.stranger);
  const strangerGraph = graph.filter((g) => {
    try {
      return JSON.parse(String(g.body)).to !== expected?.peerWa;
    } catch {
      return true;
    }
  }).length;
  const N = {
    pass: stranger?.status === 200 && rs.model + rs.hooks + rs.tools === 0 && strangerGraph === 0,
    status: stranger?.status ?? null,
    modelRequests: rs.model,
    hookCalls: rs.hooks,
    graphToOthers: strangerGraph,
  };
  const afterSends = Array.isArray(reload?.afterSends) ? reload.afterSends : null;
  const heldSends = Array.isArray(reload?.heldReplySends) ? reload.heldReplySends : null;
  const exactBody = oraclesAgree ? expectedSendBody(expected.peerWa, expected.approved) : null;
  const heldOutcome =
    heldSends === null || typeof reload?.stoppedWhileHeld !== "boolean"
      ? "missing"
      : reload.stoppedWhileHeld === false
        ? heldSends.length === 1 && heldSends[0] === exactBody ? "delivered-before-deferred-restart" : "wrong"
        : heldSends.length === 0 && reload?.lateReplyWithheld === "untrusted-turn" ? "voided-by-restart" : "wrong";
  // Every send before the stop must be one of the recorded ones: the genuine send (G), the
  // held turn's (0 or 1) and the next turn's (1). A send with no numeric time is counted
  // by X (at or after the stop), never here.
  const sendsBeforeStop = graph.length - afterStop.length;
  const expectedBeforeStop = heldSends === null || afterSends === null ? null : 1 + heldSends.length + afterSends.length;
  const allSendsAccounted = expectedBeforeStop !== null && sendsBeforeStop === expectedBeforeStop;
  const R = {
    pass:
      allSendsAccounted &&
      reload?.lateTurnHeld === true && typeof reload?.listenerStoppedAt === "number" && typeof reload?.listenerRestartedAt === "number" &&
      reload.listenerRestartedAt >= reload.listenerStoppedAt && reload?.readyAgain === true && reload?.sendsWhileDown === 0 &&
      (heldOutcome === "delivered-before-deferred-restart" || heldOutcome === "voided-by-restart") &&
      reload?.afterStatus === 200 && afterSends !== null && afterSends.length === 1 && exactBody !== null && afterSends[0] === exactBody,
    lateTurnHeld: reload?.lateTurnHeld ?? null,
    heldOutcome,
    listenerRestarted: typeof reload?.listenerStoppedAt === "number" && typeof reload?.listenerRestartedAt === "number",
    sendsWhileDown: reload?.sendsWhileDown ?? null,
    nextTurnSends: afterSends?.length ?? null,
    sendsBeforeStop,
    allSendsAccounted,
  };
  const X = {
    pass:
      shutdown?.exited === true && shutdown?.portReleased === true && stopAt !== null &&
      typeof shutdown?.accountStoppedAt === "number" && shutdown.accountStoppedAt >= stopAt && afterStop.length === 0,
    exited: shutdown?.exited ?? null,
    accountStopped: typeof shutdown?.accountStoppedAt === "number",
    portReleased: shutdown?.portReleased ?? null,
    graphAtOrAfterStop: stopAt === null ? null : afterStop.length,
  };
  const pass = S.pass && W.pass && G.pass && U.pass && N.pass && R.pass && X.pass;
  return { checks: { S, W, G, U, N, R, X }, pass };
}
