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
 *
 * Every mode also gets T (`evaluateToolNames`, WO-041): the card-tool names the host presents.
 */

import { CARD_TOOL_HOST_NAMES, isCardTool } from "../constants.mjs";

/**
 * @param {{ mode: string, steps: object[], outbound: object[], toolExec: object[], hooks: object[],
 *   expectedCard: string | null, genuineRef: string | undefined, peer: string, safeText: string, replayRef: string }} e
 */
/** Modes with no dashboard replay: L, B and C do not apply. */
const NO_REPLAY_MODES = new Set(["genuine-only", "not-allowlisted", "payloads", "cloud-api", "cloud-api-rollback", "cloud-api-restart", "stock-present", "stock-present-allowlisted"]);

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

/**
 * K: the runbook's own config commands (section 7.2), run with the pinned CLI against the
 * run's temporary state before the gateway starts (owner instruction 2026-11-08: verify the
 * config command offline). Pass only when:
 *   - `config set plugins.entries.idx-whatsapp-channel.config.cloudApi '<block>' --strict-json
 *     --expect-current-absent` exited 0, `config validate` exited 0, and `config get ... --json`
 *     read back exactly the block that was set;
 *   - the same set run again exited non-zero and left the config file byte for byte as it was
 *     (`--expect-current-absent` keeps a second paste from overwriting a live block);
 *   - three real sets (no dry run), a listener host of 0.0.0.0, an extra key and a string
 *     `enabled`, each exited non-zero with the plugin schema's own message and left the file
 *     unchanged (the host checks the plugin's strict schema before it writes).
 * @param {object | null} cli the run's `configCli` step
 */
export function evaluateConfigCli(cli) {
  const refused = (r) => typeof r?.status === "number" && r.status !== 0 && r.schemaRefusal === true && r.fileUnchanged === true;
  const K = {
    pass:
      cli?.set?.status === 0 && cli?.validate?.status === 0 && cli?.readBackEqual === true &&
      typeof cli?.repeat?.status === "number" && cli.repeat.status !== 0 && cli.repeat.fileUnchanged === true &&
      refused(cli?.badHost) && refused(cli?.extraKey) && refused(cli?.stringEnabled),
    setStatus: cli?.set?.status ?? null,
    validateStatus: cli?.validate?.status ?? null,
    readBackEqual: cli?.readBackEqual ?? null,
    repeatRefused: typeof cli?.repeat?.status === "number" ? cli.repeat.status !== 0 && cli.repeat.fileUnchanged === true : null,
    badHostRefused: refused(cli?.badHost),
    extraKeyRefused: refused(cli?.extraKey),
    stringEnabledRefused: refused(cli?.stringEnabled),
  };
  return K;
}

/**
 * Mode cloud-api-rollback (runbook 7.6, owner instruction 2026-11-08). One gateway runs with
 * the block the runbook's command wrote and delivers one genuine reply; then:
 *   H  hot apply: `config set ...cloudApi.enabled false --strict-json` on the RUNNING
 *      gateway (no restart) while a second genuine turn is held live by the model. The
 *      host's hybrid reload replaces the plugin instance and stops the account. H passes
 *      only when the listener is released after the edit (`listener-stopped`, then the port
 *      refuses connections); the held turn's reply either went out once, exactly as the
 *      first genuine reply, before the account stopped (the host deferred the stop until the
 *      turn ended) or not at all, withheld `untrusted-turn` (the host stopped at once); no
 *      request reached the Graph API from the stop on; and a signed DM sent after the edit
 *      reached no model, hook, tool or Graph API.
 *      The listener never starts again after the edit, the port still refuses at the end, and
 *      the whole Graph API log holds exactly the first genuine send and the held turn's.
 *   F  the first gateway exited, and a fresh gateway process started with `enabled: false` (the fast rollback's restart)
 *      registers the plugin, never logs `listener-started`, leaves the port refusing, logs no
 *      `cloud-api-refused` (off is not a refusal) and makes zero Graph API requests.
 *   V  the second gateway exited; then the full rollback's config steps: `config unset
 *      ...cloudApi` exited 0, `config validate` exited 0, `config get ...cloudApi` then exits 1
 *      with the CLI's own "Config path is valid but unset: <path>" message, and
 *      `plugins disable idx-whatsapp-channel` exited 0 with `enabled` read back false.
 * @param {{ steps: object[], graph: object[], modelRequests: object[], hooks: object[], toolExec: object[] }} run
 */
export function evaluateCloudRollback({ steps, graph, modelRequests, hooks, toolExec }) {
  const st = (k) => steps.find((x) => x && typeof x === "object" && k in x)?.[k] ?? null;
  const before = st("beforeRollback");
  const hot = st("hotApply");
  const hotEnd = st("hotApplyEnd");
  const fresh = st("freshOff");
  const full = st("fullRollback");
  const editAt = typeof hot?.editAt === "number" ? hot.editAt : null;
  const marker = typeof hot?.marker === "string" ? hot.marker : null;
  const ref = marker === null ? null : marker.replace(/^GENUINE-/u, "genuine-");
  const reachedAfter =
    marker === null
      ? null
      : modelRequests.filter((m) => m.marker === marker).length +
        hooks.filter((h) => h.params?.ref === ref).length +
        toolExec.filter((t) => t.ref === ref).length;
  // The first genuine reply is the reference: the held turn asks for the same payload case.
  const reference = graph.length > 0 && typeof graph[0].body === "string" ? graph[0].body : null;
  const heldSends = Array.isArray(hot?.heldReplySends) ? hot.heldReplySends : null;
  const heldOutcome =
    heldSends === null || typeof hot?.stoppedWhileHeld !== "boolean"
      ? "missing"
      : hot.stoppedWhileHeld === false
        ? heldSends.length === 1 && reference !== null && heldSends[0] === reference ? "delivered-before-deferred-stop" : "wrong"
        : heldSends.length === 0 && hot?.lateReplyWithheld === "untrusted-turn" ? "voided-by-stop" : "wrong";
  // The whole Graph API log, read after both gateways have exited, holds exactly the first
  // genuine send and the held turn's (0 or 1): an extra or duplicate send anywhere fails.
  const allSendsAccounted = heldSends !== null && graph.length === 1 + heldSends.length;
  const H = {
    pass:
      before?.genuineSends === 1 && hot?.setStatus === 0 && hot?.heldLive === true && editAt !== null &&
      typeof hot?.listenerStoppedAt === "number" && hot.listenerStoppedAt >= editAt &&
      (heldOutcome === "delivered-before-deferred-stop" || heldOutcome === "voided-by-stop") &&
      hot?.sendsAfterStop === 0 && hot?.portRefusedAfter === true && hot?.graphAfterPost === 0 && reachedAfter === 0 &&
      hotEnd?.listenerStartedAfterEdit === 0 && hotEnd?.portRefusedAtEnd === true && allSendsAccounted,
    genuineSendsBefore: before?.genuineSends ?? null,
    setStatus: hot?.setStatus ?? null,
    heldOutcome,
    listenerStopped: typeof hot?.listenerStoppedAt === "number",
    stoppedAfterMs: typeof hot?.listenerStoppedAt === "number" && editAt !== null ? hot.listenerStoppedAt - editAt : null,
    sendsAfterStop: hot?.sendsAfterStop ?? null,
    portRefusedAfter: hot?.portRefusedAfter ?? null,
    postAfterEdit: hot?.postAfterEdit ?? null,
    reachedHostAfterEdit: reachedAfter,
    listenerStartedAfterEdit: hotEnd?.listenerStartedAfterEdit ?? null,
    portRefusedAtEnd: hotEnd?.portRefusedAtEnd ?? null,
    setToStopMs: typeof hot?.listenerStoppedAt === "number" && typeof hot?.setReturnedAt === "number" ? hot.listenerStoppedAt - hot.setReturnedAt : null,
    allSendsAccounted,
  };
  const F = {
    pass:
      fresh?.firstExited === true && fresh?.registered === true && fresh?.listenerStartedLogged === false && fresh?.portRefused === true &&
      Array.isArray(fresh?.refusals) && fresh.refusals.length === 0 && fresh?.graphDuring === 0 && fresh?.offConfirmed === true,
    registered: fresh?.registered ?? null,
    listenerStartedLogged: fresh?.listenerStartedLogged ?? null,
    portRefused: fresh?.portRefused ?? null,
    refusals: fresh?.refusals ?? null,
    graphDuring: fresh?.graphDuring ?? null,
  };
  // "Unset" only from the CLI's own words for it, never from any non-zero exit.
  const unsetConfirmed =
    full?.getAfterUnsetStatus === 1 && typeof full?.getAfterUnsetMessage === "string" &&
    full.getAfterUnsetMessage.startsWith("Config path is valid but unset: plugins.entries.idx-whatsapp-channel.config.cloudApi");
  const V = {
    pass:
      full?.secondExited === true && full?.unsetStatus === 0 && full?.validateStatus === 0 && unsetConfirmed &&
      full?.disableStatus === 0 && full?.enabledAfterDisable === false,
    unsetStatus: full?.unsetStatus ?? null,
    validateStatus: full?.validateStatus ?? null,
    unsetConfirmed,
    disableStatus: full?.disableStatus ?? null,
    enabledAfterDisable: full?.enabledAfterDisable ?? null,
  };
  return { checks: { H, F, V }, pass: H.pass && F.pass && V.pass };
}

/**
 * O: the runbook's owner checks (7.5 log check, 7.6 rollback confirmation), extracted from
 * the runbook and run verbatim with /bin/sh against the real gateway (owner instruction
 * 2026-11-08: never print clean or confirmed without a good log read and the expected
 * events). Mode cloud-api: over one genuine turn the 7.5 check prints exactly the two clean
 * verdicts; with one inbound too many expected it prints that REVIEW line and checks
 * nothing; with a pattern that is in the log it reports the leak. Mode cloud-api-rollback:
 * before the edit (listener running) the 7.6 block does not confirm and says why (no
 * listener-stopped, the port answered); after the edit it prints only the confirmation.
 * @param {{ mode: string, steps: object[] }} run
 */
export function evaluateOwnerChecks({ mode, steps }) {
  const st = (k) => steps.find((x) => x && typeof x === "object" && k in x)?.[k] ?? null;
  const same = (a, b) => Array.isArray(a) && a.length === b.length && a.every((x, i) => x === b[i]);
  if (mode === "cloud-api") {
    const o = st("ownerSmoke");
    const wrong = Array.isArray(o?.wrongCount) ? o.wrongCount : [];
    const O = {
      pass:
        same(o?.pass, ["leaks: clean", "failures: clean"]) &&
        wrong.includes("REVIEW: inbound messages: 1, expected 2") && same(wrong.slice(-2), ["leaks: not checked", "failures: not checked"]) &&
        Array.isArray(o?.leakProbe) && o.leakProbe[0] === "leaks: REVIEW: abort",
      smoke: o?.pass ?? null,
      wrongCount: o?.wrongCount ?? null,
      leakProbe: o?.leakProbe ?? null,
    };
    return O;
  }
  if (mode === "cloud-api-rollback") {
    const o = st("ownerRollback");
    const before = Array.isArray(o?.before) ? o.before : [];
    const confirmed = "rollback confirmed: listener-stopped logged and the port is closed";
    const O = {
      pass:
        before.includes("NOT CONFIRMED: no listener-stopped since ROLLBACK_START") &&
        before.some((l) => l.startsWith("NOT CONFIRMED: the listener's port did not refuse")) && !before.includes(confirmed) &&
        same(o?.after, [confirmed]),
      before: o?.before ?? null,
      after: o?.after ?? null,
    };
    return O;
  }
  return null;
}

/**
 * E (mode cloud-api-restart, WO-040): persistent dedupe across a gateway restart. Pass
 * only when the first gateway delivered the genuine DM (one exact Graph API request) and
 * exited; its dedupe store is on disk, a mode-700 directory with at least one marker and
 * no message id or marker text in any name or file; a fresh gateway process became ready; the exact signed bytes of the
 * first DM sent again (Meta's retry, timestamp still fresh) answered 200 and were counted
 * ignored (`webhook-accepted` delivered 0, ignored 1), reached no model request, made no
 * Graph API request, and the
 * first DM's card tool ran and was hooked exactly once in all; a new DM after the restart
 * reached the hook and made exactly one more request with the exact expected body; and
 * no `cloud-api-refused` or `dedupe-store-failed` line appeared.
 * @param {{ steps: object[], graph: object[], hooks: object[], toolExec: object[], expected: { peerWa: string, approved: string | null } }} run
 */
export function evaluateCloudRestart({ steps, graph, hooks, toolExec, expected }) {
  const st = (k) => steps.find((x) => x && typeof x === "object" && k in x)?.[k] ?? null;
  const before = st("beforeRestart");
  const r = st("restart");
  const ref = typeof r?.marker === "string" ? r.marker.replace(/^GENUINE-/u, "genuine-") : null;
  const hookCount = ref === null ? null : hooks.filter((h) => h.params?.ref === ref).length;
  const execCount = ref === null ? null : toolExec.filter((t) => t.ref === ref).length;
  const accepted = Array.isArray(r?.acceptedAfter) ? r.acceptedAfter : null;
  const exact = typeof expected?.approved === "string" ? expectedSendBody(expected.peerWa, expected.approved) : null;
  const E = {
    pass:
      before?.status === 200 && before?.reachedHook === true && before?.graph === 1 &&
      r?.firstExited === true && r?.store !== null && typeof r?.store === "object" && r.store.mode === 0o700 && r.store.entries >= 1 && r.store.holdsId === false &&
      r?.readyAgain === true && r?.replayStatus === 200 &&
      accepted !== null && accepted.length >= 1 && accepted[0][0] === 0 && accepted[0][1] === 1 &&
      r?.graphAfterReplay === 0 && r?.modelAfterReplay === 0 && hookCount === 1 && execCount === 1 &&
      r?.next?.status === 200 && r?.next?.reachedHook === true && graph.length === 2 && exact !== null && graph[1]?.body === exact &&
      Array.isArray(r?.refusals) && r.refusals.length === 0,
    firstDelivered: before?.graph ?? null,
    store: r?.store ?? null,
    readyAgain: r?.readyAgain ?? null,
    replayStatus: r?.replayStatus ?? null,
    replayCounted: accepted?.[0] ?? null,
    graphAfterReplay: r?.graphAfterReplay ?? null,
    modelAfterReplay: r?.modelAfterReplay ?? null,
    firstTurnHooks: hookCount,
    firstTurnToolRuns: execCount,
    nextDelivered: graph.length === 2 && exact !== null ? graph[1]?.body === exact : false,
    refusals: r?.refusals ?? null,
  };
  return { checks: { E }, pass: E.pass };
}

/**
 * T (WO-041, runbook C4): the card-tool names the pinned host really presents. The host gives
 * a plugin no tool list at register, so the startup self-check can only check our own pins
 * (`cardToolHostNamesValid`); T checks them against the host. Passes only when:
 *   - at least one model request carried a tool list;
 *   - in every such list, the names `isCardTool` accepts are exactly the
 *     `CARD_TOOL_HOST_NAMES` keys, each present literally (no suffixed, cut or other spelling);
 *   - every card call the before_tool_call hook admitted (`marked: 1`) used one of those keys;
 *   - with `requireAllCalled` (mode payloads), each key was admitted at least once.
 * @param {{ modelRequests: object[], hooks: object[], requireAllCalled?: boolean,
 *   hostNames?: Readonly<Record<string, string>>, isCard?: (n: unknown) => boolean }} e
 */
export function evaluateToolNames({ modelRequests, hooks, requireAllCalled = false, hostNames = CARD_TOOL_HOST_NAMES, isCard = isCardTool }) {
  const pinned = Object.keys(hostNames).sort();
  const lists = (modelRequests ?? []).map((m) => m?.toolNames).filter((l) => Array.isArray(l) && l.length > 0);
  const presented = lists.map((l) => [...new Set(l.filter((n) => isCard(n)))].sort());
  const listsMatch = lists.length > 0 && presented.every((p) => p.length === pinned.length && p.every((n, i) => n === pinned[i]));
  const admitted = (hooks ?? []).filter((h) => h?.decision?.block === false && h?.decision?.marked === 1).map((h) => h.toolName);
  const admittedPinned = admitted.length > 0 && admitted.every((n) => Object.prototype.hasOwnProperty.call(hostNames, n));
  const called = [...new Set(admitted)].sort();
  const allCalled = !requireAllCalled || pinned.every((n) => called.includes(n));
  return {
    pass: listsMatch && admittedPinned && allCalled,
    toolLists: lists.length,
    presentedCardTools: [...new Set(presented.flat())].sort(),
    admittedCardTools: called,
    requireAllCalled,
  };
}

/**
 * Z (WO-041, runbook 3.1, 3.7, section 4 and C8): the stock modes, the stock
 * @openclaw/whatsapp 2026.9.5 package installed in the sandboxed state, `stock-present` with
 * the recorded allow list set without "whatsapp" and `stock-present-allowlisted` with it.
 * Passes only when every phase holds:
 *   setup    the tarball matched the registry's sha512, was extracted and installed, the
 *            owner's pre-install state was made (allow list by variant, the stock entry as
 *            the install wrote it, an authored stock `channels.whatsapp` with an account),
 *            the runbook's authored-snapshot block saved exactly that block while `config
 *            get` showed a different (defaulted) view, 3.2 ran as the runbook's per-key
 *            commands (each exit 0) and left exactly the accepted keys with every account
 *            list owner-only (read back), and the phase 1 write exited 0;
 *   phase 1  "allow list alone" (the 3.1 allow list, the stock entry still enabled): every
 *            register of ours saw "whatsapp" in the effective allow list (auto-enable added it
 *            back) and refused `stock-whatsapp-not-denied`; none registered, no channel
 *            started, the stock plugin loaded, and the runbook's auto-enable owner check
 *            flagged a change line naming whatsapp (never `clean`);
 *   3.1(b)   from the snapshot again, in the runbook's order: `plugins disable whatsapp`,
 *            the allow list read back, then the conditional write with that value, each exit
 *            0, leaving the 3.1 list (no "whatsapp") and the stock entry `enabled: false`;
 *   phase 2  every register saw neither, none refused, ours registered and its channel
 *            started, the stock plugin never loaded, no ownership conflict, and the owner
 *            check printed exactly `auto-enable: clean`;
 *   rollback the runbook's section 4 order (R3, R4, R5b, the restore order's paired
 *            allowFrom writes, R6, read-backs, validate), every step exit 0; R3 deleted
 *            `channels.whatsapp`; after R5b the authored block was the snapshot with every
 *            allowFrom and groupAllowFrom cut to the owner and groupPolicy "disabled"
 *            (root and accounts); R4b and R4c: after a 3.6b switch to trusted-proxy pruned
 *            the token, the mode went back and the runbook's auth-secret block restored
 *            exactly the original token from the section 2 archive without printing it,
 *            with channels.whatsapp still absent (no whole-file copy); the restore order
 *            wrote each value back; at the end the authored block, read by the same
 *            owner block, equals the snapshot (dmPolicy "allowlist" read back), the allow
 *            list equals the snapshot, and the stock entry is enabled (read back true). In `stock-present`
 *            `plugins enable whatsapp` must also be shown refused "blocked by allowlist",
 *            with the entry left false, before R6's direct write;
 *   phase 3  a fresh gateway loaded the stock plugin, never loaded ours, saw no register of
 *            ours and logged no ownership conflict.
 * The genuine turn of phase 2 is judged by A, I and T.
 * @param {{ steps: object[], phase2: { register: { calls: object[], registered: number, threw: string[], started: number }, activationLog: string[] } }} e
 */
export function evaluateStockPresent({ steps, phase2 }) {
  const st = (k) => steps.find((s) => s[k] !== undefined)?.[k];
  const setup = st("stockSetup");
  const p1 = st("stockPhase1");
  const b = st("stock31b");
  const p2check = st("stockPhase2Check");
  const rb = st("stockRollback");
  const p3 = st("stockPhase3");
  const allowlisted = setup?.variant === "stock-present-allowlisted";
  const loadsStock = (lines) => (lines ?? []).some((l) => /\[plugins\] loading whatsapp from /u.test(l));
  const conflict = (lines) => (lines ?? []).some((l) => /already registered/iu.test(l));
  const setupOk =
    Boolean(setup) && setup.integrityOk === true && setup.extracted === true && setup.install?.status === 0 &&
    setup.baseline?.setAllow === 0 && setup.baseline?.channelsWritten === true && setup.snapshot?.channelsMatch === true &&
    Array.isArray(setup.authoredCheck) && setup.authoredCheck.join("|") === "authored: saved" && setup.snapshot?.runtimeViewDiffers === true &&
    setup.set32?.status === 0 && setup.set32?.accountOwnerOnly === true && setup.set32?.resultMatches === true &&
    setup.backup?.status === 0 && setup.backup?.verified === true &&
    setup.snapshot?.allowHasStock === allowlisted && setup.allowOnly?.status === 0;
  const r1 = p1?.register;
  const flagged = Array.isArray(p1?.autoEnableCheck) && p1.autoEnableCheck.some((l) => /^auto-enable: REVIEW: .*whatsapp/iu.test(l)) && !p1.autoEnableCheck.includes("auto-enable: clean");
  const phase1Ok =
    Boolean(r1) && loadsStock(p1?.activationLog) && flagged && r1.calls.length > 0 && r1.calls.every((c) => c.allowHasStock === true) &&
    r1.registered === 0 && r1.started === 0 && r1.threw.length === r1.calls.length && r1.threw.every((t) => t === "stock-whatsapp-not-denied");
  const b31Ok =
    Boolean(b) && b.reset?.status === 0 && b.disable?.status === 0 && b.write?.status === 0 &&
    b.allowHasStock === false && b.allowEqualsTarget === true && b.stockEntryEnabled === false;
  const r2 = phase2?.register;
  const phase2Ok =
    Boolean(r2) && r2.calls.length > 0 && r2.calls.every((c) => c.allowHasStock === false && c.allowHasOurs === true && c.stockEntryEnabledSeen === false) &&
    r2.threw.length === 0 && r2.registered > 0 && r2.started > 0 && !conflict(phase2?.activationLog) && !loadsStock(phase2?.activationLog) &&
    Array.isArray(p2check) && p2check.length === 1 && p2check[0] === "auto-enable: clean";
  const refusedShown = allowlisted || (rb?.enableRefused?.status !== 0 && rb?.enableRefused?.status !== undefined && rb?.enableRefused?.blockedByAllowlist === true && rb?.enableRefused?.entryAfter === false);
  const rollbackOk =
    Boolean(rb) && rb.allExitZero === true && rb.steps.length >= 6 && rb.steps.filter((x) => String(x.label).startsWith("restore order")).length >= 6 && rb.channelsDeletedByR3 === true && rb.dmPolicyReadBack === "allowlist" &&
    rb.cutVerified === true && rb.finalAuthoredSaved === true &&
    rb.authSwitch?.modeStatus === 0 && rb.authSwitch?.tokenPruned === true &&
    rb.r4c?.tokenAbsentBefore === true && rb.r4c?.restored === true && rb.r4c?.tokenEqualsOriginal === true &&
    rb.r4c?.secretNotPrinted === true && rb.r4c?.channelsStillAbsent === true &&
    rb.entryReadBack === true && rb.channelsEqualSnapshot === true && rb.allowEqualsSnapshot === true && rb.stockEntryEnabled === true && refusedShown;
  const phase3Ok = Boolean(p3) && p3.stockLoaded === true && p3.oursLoaded === false && p3.oursRegisterCalls === 0 && !conflict(p3.activationLog);
  return {
    pass: setupOk && phase1Ok && b31Ok && phase2Ok && rollbackOk && phase3Ok,
    variant: setup?.variant ?? null,
    setupOk,
    phase1Ok,
    b31Ok,
    phase2Ok,
    rollbackOk,
    phase3Ok,
    installWrote: setup?.configAfterInstall ?? null,
    phase1: r1 ? { calls: r1.calls.length, allowHadStock: r1.calls.filter((c) => c.allowHasStock === true).length, refused: r1.threw, registered: r1.registered, stockLoaded: loadsStock(p1?.activationLog), ownerCheckFlagged: flagged } : null,
    phase2: r2 ? { calls: r2.calls.length, registered: r2.registered, started: r2.started, refused: r2.threw, ownershipConflictLogged: conflict(phase2?.activationLog), stockLoaded: loadsStock(phase2?.activationLog), ownerCheck: p2check ?? null } : null,
    snapshot: setup?.snapshot ? { runtimeViewDiffers: setup.snapshot.runtimeViewDiffers, runtimeViewAddedKeys: setup.snapshot.runtimeViewAddedKeys ?? null, authoredCheck: setup.authoredCheck ?? null } : null,
    rollback: rb ? { steps: rb.steps.map((x) => `${x.label}: ${x.status}`), authSwitch: rb.authSwitch ?? null, r4c: rb.r4c ? { ...rb.r4c } : null, channelsDeletedByR3: rb.channelsDeletedByR3, cutVerified: rb.cutVerified, runtimeViewAfterRestore: rb.runtimeViewAfterRestore ?? null, channelsEqualSnapshot: rb.channelsEqualSnapshot, dmPolicyReadBack: rb.dmPolicyReadBack, allowEqualsSnapshot: rb.allowEqualsSnapshot, entryReadBack: rb.entryReadBack, enableRefused: rb.enableRefused ? { status: rb.enableRefused.status, blockedByAllowlist: rb.enableRefused.blockedByAllowlist } : null } : null,
    phase3: p3 ? { stockLoaded: p3.stockLoaded, oursLoaded: p3.oursLoaded, oursRegisterCalls: p3.oursRegisterCalls } : null,
  };
}
