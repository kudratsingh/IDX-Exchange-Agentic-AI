/**
 * Offline tests of the harness's evidence rules (checks.mjs). Synthetic evidence only; no
 * host runs here. Each test changes one piece of a passing record and shows the check fails.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { evaluate, evaluateCloudApi, evaluateCloudRestart, evaluateCloudRollback, evaluateConfigCli, evaluateOwnerChecks, evaluateStockPresent, evaluateToolNames } from "./checks.mjs";

const PEER = "+15555550101";
const SAFE_TEXT = "I couldn't send that reply safely. Please ask again.";
const CARD = "Synthetic listing genuine-a1: card bytes";

/** A passing default-mode record: live genuine run, replay refused by the hook and settled. */
function passing() {
  return {
    mode: "default",
    peer: PEER,
    safeText: SAFE_TEXT,
    replayRef: "dashboard-1",
    genuineRef: "genuine-a1",
    expectedCard: CARD,
    outbound: [{ to: PEER, text: CARD }],
    toolExec: [{ ref: "genuine-a1" }],
    hooks: [
      { params: { ref: "genuine-a1" }, eventRunId: "g-run", decision: { block: false, marked: 1 } },
      { params: { ref: "dashboard-1" }, eventRunId: "r-run", decision: { block: true, reason: "unknown-run", withheld: 0 } },
    ],
    steps: [
      { replaySent: { sentAt: 1500, modelHeld: 1, peerOutboundBefore: 0 } },
      { chatSend: { ok: true, payload: { runId: "g-run", status: "started" } } },
      { genuineTerminal: { ok: true, payload: { status: "ok", startedAt: 1000, endedAt: 5000 } } },
      { replayTerminal: { runId: "r-run", ok: true, payload: { status: "ok", startedAt: 5100, endedAt: 5300 } } },
    ],
  };
}

const withStep = (e, key, value) => ({ ...e, steps: e.steps.map((s) => (key in s ? { [key]: value } : s)) });
const withoutStep = (e, key) => ({ ...e, steps: e.steps.filter((s) => !(key in s)) });

test("HC-0 the passing record passes L, A, B and C", () => {
  const r = evaluate(passing());
  assert.equal(r.pass, true);
  assert.equal(r.checks.L.pass, true);
  assert.equal(r.checks.B.pass, true);
  assert.equal(r.checks.B.evidence, "hook-refused");
  assert.equal(r.genuineReply, "delivered");
});

test("HC-1 a replay whose run the host still reports as running fails B even though the hook refusal is logged", () => {
  const e = withStep(passing(), "replayTerminal", { runId: "r-run", ok: true, payload: { status: "timeout" } });
  const r = evaluate(e);
  assert.equal(r.checks.B.evidence, "hook-refused", "the refusal is in the log");
  assert.equal(r.checks.B.replaySettled, false);
  assert.equal(r.checks.B.pass, false);
  assert.equal(r.pass, false);
});

test("HC-2 a replay-settle probe that timed out, or never ran, fails B even though the hook refusal is logged", () => {
  for (const e of [
    withStep(passing(), "replayTerminal", { runId: "r-run", timeout: true }),
    withStep(passing(), "replayTerminal", { runId: "r-run", ok: false, error: { code: "INVALID_REQUEST" } }),
    withoutStep(passing(), "replayTerminal"),
  ]) {
    const r = evaluate(e);
    assert.equal(r.checks.B.pass, false, JSON.stringify(e.steps.at(-1)));
    assert.equal(r.pass, false);
  }
});

test("HC-3 no proof the genuine turn was live at the replay fails L, B and C", () => {
  const cases = {
    "sent after the host run ended": withStep(passing(), "replaySent", { sentAt: 6000, modelHeld: 1, peerOutboundBefore: 0 }),
    "sent before the host run started": withStep(passing(), "replaySent", { sentAt: 900, modelHeld: 1, peerOutboundBefore: 0 }),
    "model no longer holding the genuine request": withStep(passing(), "replaySent", { sentAt: 1500, modelHeld: 0, peerOutboundBefore: 0 }),
    "peer already had a reply": withStep(passing(), "replaySent", { sentAt: 1500, modelHeld: 1, peerOutboundBefore: 1 }),
    "host terminal record missing": withoutStep(passing(), "genuineTerminal"),
    "host terminal probe timed out": withStep(passing(), "genuineTerminal", { timeout: true }),
    "host record without timestamps": withStep(passing(), "genuineTerminal", { ok: true, payload: { status: "ok" } }),
    "send time not recorded": withoutStep(passing(), "replaySent"),
  };
  for (const [name, e] of Object.entries(cases)) {
    const r = evaluate(e);
    assert.equal(r.checks.L.pass, false, name);
    assert.equal(r.checks.B.pass, false, name);
    assert.equal(r.checks.C.pass, false, name);
    assert.equal(r.pass, false, name);
  }
});

test("HC-4 an explicit host rejection is B evidence without a replay run, but never with a replay execution", () => {
  const rejected = {
    ...withStep(withoutStep(passing(), "replayTerminal"), "chatSend", { ok: false, error: { code: "INVALID_REQUEST" } }),
    hooks: passing().hooks.slice(0, 1),
  };
  assert.equal(evaluate(rejected).checks.B.pass, true);
  assert.equal(evaluate(rejected).checks.B.evidence, "host-rejected");
  const executed = { ...rejected, toolExec: [...rejected.toolExec, { ref: "dashboard-1" }] };
  assert.equal(evaluate(executed).checks.B.pass, false);
});

test("HC-5 a replay that never reached a tool and was not rejected has no evidence and fails B", () => {
  const e = { ...withoutStep(passing(), "replayTerminal"), hooks: passing().hooks.slice(0, 1) };
  const r = evaluate(e);
  assert.equal(r.checks.B.evidence, "none");
  assert.equal(r.checks.B.pass, false);
});

test("HC-6 an interrupted genuine run stays visible as a cancelled reply and fails C", () => {
  const e = {
    ...withStep(passing(), "chatSend", { ok: true, payload: { runId: "g-run", status: "started", interruptedActiveRun: true } }),
    outbound: [],
  };
  const r = evaluate(e);
  assert.equal(r.genuineReply, "cancelled-by-interrupt");
  assert.equal(r.checks.C.pass, false);
  assert.equal(r.checks.A.pass, false);
});

test("HC-7 genuine-only needs no replay evidence; extra or different bytes to the peer fail A", () => {
  const g = { ...passing(), mode: "genuine-only", hooks: passing().hooks.slice(0, 1), steps: [] };
  assert.equal(evaluate(g).pass, true);
  assert.equal(evaluate({ ...g, outbound: [{ to: PEER, text: CARD }, { to: PEER, text: "extra" }] }).checks.A.pass, false);
  assert.equal(evaluate({ ...g, outbound: [{ to: PEER, text: SAFE_TEXT }] }).checks.A.pass, false);
  assert.equal(evaluate({ ...g, toolExec: [{ ref: "genuine-a1" }, { ref: "genuine-a1" }] }).checks.A.pass, false);
});

// ---- mode cloud-api (WO-039) -----------------------------------------------------------

const URL_ = "https://graph.facebook.com/v99.9/1000000000555/messages";
const BEARER = "Bearer synthetic-token-not-real";
const APPROVED = "Showing 1 active listing on page 1\n\n*Irvine 92618*";
const sendBody = (to, text) => JSON.stringify({ messaging_product: "whatsapp", recipient_type: "individual", to, type: "text", text: { preview_url: false, body: text } });

/** A passing cloud-api record: started, one signed turn, one exact send, refusals, a clean stop. */
function cloudPassing() {
  return {
    genuineRef: "genuine-a1",
    expected: { url: URL_, authorization: BEARER, peerWa: "15555550101", approved: APPROVED, rendered: APPROVED },
    markers: { unsigned: "GENUINE-unsignedb2", tampered: "GENUINE-tamperedb2", stranger: "GENUINE-stranger" },
    // the genuine send, the held turn's send before the deferred restart (3000-3100), and
    // the next turn's send after the listener came back (3200)
    graph: [
      { at: 2000, url: URL_, method: "POST", redirect: "error", hasSignal: true, headers: { authorization: BEARER, "content-type": "application/json" }, body: sendBody("15555550101", APPROVED) },
      { at: 3050, url: URL_, method: "POST", redirect: "error", hasSignal: true, headers: { authorization: BEARER, "content-type": "application/json" }, body: sendBody("15555550101", APPROVED) },
      { at: 3500, url: URL_, method: "POST", redirect: "error", hasSignal: true, headers: { authorization: BEARER, "content-type": "application/json" }, body: sendBody("15555550101", APPROVED) },
    ],
    refusals: [],
    modelRequests: [{ marker: "GENUINE-a1" }, { marker: "GENUINE-a1" }, { marker: "GENUINE-late1" }],
    hooks: [
      { params: { ref: "genuine-a1" }, decision: { block: false, marked: 1 } },
      { params: { ref: "genuine-late1" }, decision: { block: false, marked: 1 } },
    ],
    toolExec: [{ ref: "genuine-a1" }, { ref: "genuine-late1" }],
    steps: [
      { startup: { listenerStartedLogged: true, accepting: true, verifyStatus: 200, verifyEchoed: true, ready: true, refusals: [] } },
      { signedGenuine: { status: 200 } },
      { unsignedPost: { status: 401 } },
      { tamperedPost: { status: 401 } },
      { strangerPost: { status: 200 } },
      { reload: { lateTurnHeld: true, reloadAt: 3000, stoppedWhileHeld: false, listenerStoppedAt: 3100, listenerRestartedAt: 3200, readyAgain: true, heldReplySends: [sendBody("15555550101", APPROVED)], sendsWhileDown: 0, lateReplyWithheld: null, afterStatus: 200, afterSends: [sendBody("15555550101", APPROVED)] } },
      { shutdown: { stopAt: 5000, accountStoppedAt: 5100, exited: true, portReleased: true } },
    ],
  };
}
const withCloudStep = (e, key, value) => ({ ...e, steps: e.steps.map((x) => (key in x ? { [key]: value } : x)) });
const withoutCloudStep = (e, key) => ({ ...e, steps: e.steps.filter((x) => !(key in x)) });

test("HC-8 the passing cloud-api record passes S, W, G, U, N, R and X", () => {
  const r = evaluateCloudApi(cloudPassing());
  for (const k of ["S", "W", "G", "U", "N", "R", "X"]) assert.equal(r.checks[k].pass, true, k);
  assert.equal(r.pass, true);
});

test("HC-9 cloud-api: every missing or timed-out piece of evidence fails its check", () => {
  const cases = {
    S: [
      withoutCloudStep(cloudPassing(), "startup"),
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: true, accepting: true, verifyStatus: 200, verifyEchoed: true, ready: false, refusals: [] }),
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: true, accepting: false, verifyStatus: 200, verifyEchoed: true, ready: true, refusals: [] }),
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: false, accepting: true, verifyStatus: 200, verifyEchoed: true, ready: true, refusals: [] }),
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: true, accepting: true, verifyStatus: 403, verifyEchoed: false, ready: true, refusals: [] }),
      // a refusal logged by any register (a discovery copy, a later reload) fails S
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: true, accepting: true, verifyStatus: 200, verifyEchoed: true, ready: true, refusals: ["config-mismatch"] }),
      withCloudStep(cloudPassing(), "startup", { listenerStartedLogged: true, accepting: true, verifyStatus: 200, verifyEchoed: true, ready: true }),
      { ...cloudPassing(), refusals: ["credentials-changed"] },
      { ...cloudPassing(), refusals: undefined },
    ],
    W: [
      withoutCloudStep(cloudPassing(), "signedGenuine"),
      withCloudStep(cloudPassing(), "signedGenuine", { status: 503 }),
      { ...cloudPassing(), hooks: cloudPassing().hooks.slice(1) },
      { ...cloudPassing(), toolExec: [{ ref: "genuine-a1" }, { ref: "genuine-a1" }] },
      { ...cloudPassing(), genuineRef: undefined },
    ],
    U: [
      withoutCloudStep(cloudPassing(), "unsignedPost"),
      withCloudStep(cloudPassing(), "unsignedPost", { status: 200 }),
      withCloudStep(cloudPassing(), "tamperedPost", { status: 200 }),
      withoutCloudStep(cloudPassing(), "tamperedPost"),
      { ...cloudPassing(), modelRequests: [...cloudPassing().modelRequests, { marker: "GENUINE-tamperedb2" }] },
      { ...cloudPassing(), toolExec: [...cloudPassing().toolExec, { ref: "genuine-unsignedb2" }] },
    ],
    N: [
      withoutCloudStep(cloudPassing(), "strangerPost"),
      withCloudStep(cloudPassing(), "strangerPost", { status: 401 }),
      { ...cloudPassing(), modelRequests: [...cloudPassing().modelRequests, { marker: "GENUINE-stranger" }] },
      { ...cloudPassing(), hooks: [...cloudPassing().hooks, { params: { ref: "genuine-stranger" }, decision: { block: false, marked: 1 } }] },
    ],
    R: [
      withoutCloudStep(cloudPassing(), "reload"),
      ...[
        { lateTurnHeld: false },
        { listenerStoppedAt: null },
        { listenerRestartedAt: null },
        { listenerRestartedAt: 3050 },
        { readyAgain: false },
        { sendsWhileDown: 1 },
        { heldReplySends: [] },
        { heldReplySends: [sendBody("15555550101", APPROVED), sendBody("15555550101", APPROVED)] },
        { heldReplySends: [sendBody("15555550101", "other")] },
        { heldReplySends: undefined },
        { stoppedWhileHeld: undefined },
        { stoppedWhileHeld: true },
        { stoppedWhileHeld: true, heldReplySends: [], lateReplyWithheld: "no-turn-handle" },
        { stoppedWhileHeld: true, heldReplySends: [sendBody("15555550101", APPROVED)], lateReplyWithheld: "untrusted-turn" },
        { afterStatus: 503 },
        { afterSends: [] },
        { afterSends: [sendBody("15555550101", APPROVED), sendBody("15555550101", APPROVED)] },
        { afterSends: [sendBody("15555550101", "something else")] },
        { afterSends: undefined },
      ].map((patch) => withCloudStep(cloudPassing(), "reload", { ...cloudPassing().steps.find((x) => x.reload).reload, ...patch })),
    ],
    X: [
      withoutCloudStep(cloudPassing(), "shutdown"),
      withCloudStep(cloudPassing(), "shutdown", { stopAt: 5000, accountStoppedAt: 5100, exited: true, portReleased: false }),
      withCloudStep(cloudPassing(), "shutdown", { stopAt: 5000, accountStoppedAt: null, exited: true, portReleased: true }),
      withCloudStep(cloudPassing(), "shutdown", { stopAt: 5000, accountStoppedAt: 4000, exited: true, portReleased: true }),
      withCloudStep(cloudPassing(), "shutdown", { stopAt: 5000, accountStoppedAt: 5100, exited: false, portReleased: true }),
      withCloudStep(cloudPassing(), "shutdown", { accountStoppedAt: 5100, exited: true, portReleased: true }),
    ],
  };
  for (const [check, records] of Object.entries(cases)) {
    for (const e of records) {
      const r = evaluateCloudApi(e);
      assert.equal(r.checks[check].pass, false, `${check}: ${JSON.stringify(e.steps.find((x) => true))}`);
      assert.equal(r.pass, false, check);
    }
  }
});

test("HC-11 cloud-api R names the held turn's outcome: delivered once before a deferred restart (OpenClaw 2026.9.5), or voided with zero requests by an immediate one; both pass", () => {
  const base = cloudPassing();
  const rl = base.steps.find((x) => x.reload).reload;
  const deferred = evaluateCloudApi(base);
  assert.equal(deferred.checks.R.heldOutcome, "delivered-before-deferred-restart");
  assert.equal(deferred.checks.R.pass, true);
  const voidedRecord = { ...withCloudStep(base, "reload", { ...rl, stoppedWhileHeld: true, heldReplySends: [], lateReplyWithheld: "untrusted-turn" }), graph: [base.graph[0], base.graph[2]] };
  const voided = evaluateCloudApi(voidedRecord);
  assert.equal(voided.checks.R.heldOutcome, "voided-by-restart");
  assert.equal(voided.checks.R.pass, true);
  // the voided branch with the late reply delivered anyway, after the restart: fails R
  const lateAnyway = evaluateCloudApi({ ...voidedRecord, graph: [base.graph[0], { ...base.graph[0], at: 3300 }, base.graph[2]] });
  assert.equal(lateAnyway.checks.R.heldOutcome, "voided-by-restart");
  assert.equal(lateAnyway.checks.R.allSendsAccounted, false);
  assert.equal(lateAnyway.checks.R.pass, false);
  assert.equal(lateAnyway.pass, false);
});

test("HC-10 cloud-api G: no send, a second send, a send after the stop, another body, another URL or bearer, a followed redirect, and disagreeing oracles each fail", () => {
  const base = cloudPassing();
  const g0 = base.graph[0];
  const variants = {
    "no send": { ...base, graph: [] },
    "two sends before the reload": { ...base, graph: [g0, { ...g0, at: 2100 }, ...base.graph.slice(1)] },
    "different text": { ...base, graph: [{ ...g0, body: sendBody("15555550101", `${APPROVED} `) }] },
    "link previews on": { ...base, graph: [{ ...g0, body: g0.body.replace('"preview_url":false', '"preview_url":true') }] },
    "another recipient": { ...base, graph: [{ ...g0, body: sendBody("15555550102", APPROVED) }] },
    "another url": { ...base, graph: [{ ...g0, url: URL_.replace("v99.9", "v1.0") }] },
    "another bearer": { ...base, graph: [{ ...g0, headers: { ...g0.headers, authorization: "Bearer other" } }] },
    "redirects followed": { ...base, graph: [{ ...g0, redirect: "follow" }] },
    "no abort signal": { ...base, graph: [{ ...g0, hasSignal: false }] },
    "oracles disagree": { ...base, expected: { ...base.expected, rendered: `${APPROVED}!` } },
    "no oracle": { ...base, expected: { ...base.expected, approved: null } },
  };
  for (const [name, e] of Object.entries(variants)) {
    const r = evaluateCloudApi(e);
    assert.equal(r.checks.G.pass, false, name);
    assert.equal(r.pass, false, name);
  }
  // a send at or after the stop fails X (and is not counted as the genuine send)
  const late = evaluateCloudApi({ ...base, graph: [...base.graph, { ...g0, at: 5000 }] });
  assert.equal(late.checks.G.pass, true);
  assert.equal(late.checks.X.pass, false);
  assert.equal(late.checks.X.graphAtOrAfterStop, 1);
  // a send to anyone else fails N
  const other = evaluateCloudApi({ ...base, graph: [...base.graph, { ...g0, at: 4000, body: sendBody("15555550199", "hi") }] });
  assert.equal(other.checks.N.pass, false);
});

test("HC-12 cloud-api R accounts for the whole Graph API log before the stop: an extra or duplicate send in a gap between the recorded windows (after the listener restarted and before the next DM, or after the next turn and before SIGTERM) fails R; the passing record accounts for every send", () => {
  const base = cloudPassing();
  const ok = evaluateCloudApi(base);
  assert.equal(ok.checks.R.allSendsAccounted, true);
  assert.equal(ok.checks.R.sendsBeforeStop, 3);
  const held = base.graph[1];
  for (const [name, extra] of [
    ["duplicate of the held reply after the restart, before the next DM", { ...held, at: 3250 }],
    ["duplicate of the next reply after the next turn, before SIGTERM", { ...base.graph[2], at: 4500 }],
  ]) {
    const r = evaluateCloudApi({ ...base, graph: [...base.graph, extra].sort((a, b) => (a.at ?? 0) - (b.at ?? 0)) });
    assert.equal(r.checks.R.allSendsAccounted, false, name);
    assert.equal(r.checks.R.pass, false, name);
    assert.equal(r.pass, false, name);
  }
  // a send with no time is never taken as before the stop: X counts it
  const untimed = evaluateCloudApi({ ...base, graph: [...base.graph, { ...held, at: undefined }] });
  assert.equal(untimed.checks.X.pass, false);
  assert.equal(untimed.pass, false);
  // the duplicate passes every other check, which is why R must count
  const dup = evaluateCloudApi({ ...base, graph: [...base.graph.slice(0, 2), { ...held, at: 3250 }, base.graph[2]] });
  for (const k of ["S", "W", "G", "U", "N", "X"]) assert.equal(dup.checks[k].pass, true, k);
});

// ---- runbook 7.2 and 7.6 commands on the real host (owner instruction 2026-11-08) ----------

/** A passing configCli step: the runbook's set, validate and read-back, and both refusals. */
function cliPassing() {
  return {
    set: { status: 0 },
    validate: { status: 0 },
    readBackEqual: true,
    repeat: { status: 1, fileUnchanged: true },
    badHost: { status: 1, schemaRefusal: true, fileUnchanged: true },
    extraKey: { status: 1, schemaRefusal: true, fileUnchanged: true },
    stringEnabled: { status: 1, schemaRefusal: true, fileUnchanged: true },
  };
}

test("HC-13 K passes the runbook's config command record and fails each missing or wrong piece", () => {
  assert.equal(evaluateConfigCli(cliPassing()).pass, true);
  const bad = [
    null,
    { ...cliPassing(), set: { status: 1 } },
    { ...cliPassing(), set: { status: null } },
    { ...cliPassing(), validate: { status: 1 } },
    { ...cliPassing(), readBackEqual: false },
    { ...cliPassing(), repeat: { status: 0, fileUnchanged: true } },
    { ...cliPassing(), repeat: { status: 1, fileUnchanged: false } },
    { ...cliPassing(), repeat: { status: null, fileUnchanged: true } },
    { ...cliPassing(), badHost: { status: 0, schemaRefusal: true, fileUnchanged: true } },
    { ...cliPassing(), badHost: { status: 1, schemaRefusal: false, fileUnchanged: true } },
    { ...cliPassing(), badHost: { status: 1, schemaRefusal: true, fileUnchanged: false } },
    { ...cliPassing(), extraKey: undefined },
    { ...cliPassing(), extraKey: { status: 0, schemaRefusal: true, fileUnchanged: true } },
    { ...cliPassing(), extraKey: { status: 1, schemaRefusal: false, fileUnchanged: true } },
    { ...cliPassing(), stringEnabled: undefined },
    { ...cliPassing(), stringEnabled: { status: 1, schemaRefusal: true, fileUnchanged: false } },
  ];
  for (const [i, c] of bad.entries()) assert.equal(evaluateConfigCli(c).pass, false, `case ${i}`);
});

const REF_BODY = '{"to":"15555550101","text":{"body":"Synthetic approved reply"}}';
/** A passing cloud-api-rollback record (H with the host deferring the stop, F, V). */
function rollbackPassing() {
  return {
    graph: [{ at: 1000, body: REF_BODY }, { at: 3050, body: REF_BODY }],
    modelRequests: [{ marker: "GENUINE-a1" }, { marker: "GENUINE-helda1" }],
    hooks: [{ params: { ref: "genuine-a1" } }, { params: { ref: "genuine-helda1" } }],
    toolExec: [{ ref: "genuine-a1" }, { ref: "genuine-helda1" }],
    steps: [
      { beforeRollback: { ready: true, genuineSends: 1 } },
      { hotApply: { editAt: 3000, setReturnedAt: 3080, setStatus: 0, heldStatus: 200, heldLive: true, stoppedWhileHeld: false, listenerStoppedAt: 3100, heldReplySends: [REF_BODY], lateReplyWithheld: null, sendsAfterStop: 0, graphAfterPost: 0, portRefusedAfter: true, marker: "GENUINE-hotb2", postAfterEdit: "ECONNREFUSED" } },
      { hotApplyEnd: { listenerStartedAfterEdit: 0, portRefusedAtEnd: true } },
      { freshOff: { firstExited: true, registered: true, listenerStartedLogged: false, portRefused: true, refusals: [], graphDuring: 0, offConfirmed: true } },
      { fullRollback: { secondExited: true, unsetStatus: 0, validateStatus: 0, getAfterUnsetStatus: 1, getAfterUnsetMessage: "Config path is valid but unset: plugins.entries.idx-whatsapp-channel.config.cloudApi. The runtime default applies until you set an authored value.", disableStatus: 0, enabledAfterDisable: false } },
    ],
  };
}
const patchStep = (e, key, patch) => ({ ...e, steps: e.steps.map((x) => (key in x ? { [key]: patch === null ? null : { ...x[key], ...patch } } : x)) });

test("HC-14 cloud-api-rollback: the passing record passes H, F and V; H names the held turn's outcome (delivered once before a deferred stop, or voided by an immediate stop) and both pass", () => {
  const r = evaluateCloudRollback(rollbackPassing());
  for (const k of ["H", "F", "V"]) assert.equal(r.checks[k].pass, true, k);
  assert.equal(r.checks.H.heldOutcome, "delivered-before-deferred-stop");
  assert.equal(r.pass, true);
  const voided = patchStep({ ...rollbackPassing(), graph: [{ at: 1000, body: REF_BODY }] }, "hotApply", { stoppedWhileHeld: true, heldReplySends: [], lateReplyWithheld: "untrusted-turn" });
  const v = evaluateCloudRollback(voided);
  assert.equal(v.checks.H.heldOutcome, "voided-by-stop");
  assert.equal(v.checks.H.pass, true);
});

test("HC-15 cloud-api-rollback: each missing or wrong piece of evidence fails its check", () => {
  const H = [
    patchStep(rollbackPassing(), "hotApply", null),
    patchStep(rollbackPassing(), "beforeRollback", { genuineSends: 0 }),
    patchStep(rollbackPassing(), "hotApply", { setStatus: 1 }),
    patchStep(rollbackPassing(), "hotApply", { heldLive: false }),
    patchStep(rollbackPassing(), "hotApply", { listenerStoppedAt: null }),
    patchStep(rollbackPassing(), "hotApply", { listenerStoppedAt: 2900 }),
    patchStep(rollbackPassing(), "hotApply", { heldReplySends: [REF_BODY, REF_BODY] }),
    patchStep(rollbackPassing(), "hotApply", { heldReplySends: ['{"to":"15555550101","text":{"body":"other"}}'] }),
    patchStep(rollbackPassing(), "hotApply", { stoppedWhileHeld: true }),
    patchStep(rollbackPassing(), "hotApply", { stoppedWhileHeld: true, heldReplySends: [], lateReplyWithheld: null }),
    patchStep(rollbackPassing(), "hotApply", { stoppedWhileHeld: undefined }),
    patchStep(rollbackPassing(), "hotApply", { sendsAfterStop: 1 }),
    patchStep(rollbackPassing(), "hotApply", { sendsAfterStop: null }),
    patchStep(rollbackPassing(), "hotApply", { portRefusedAfter: false }),
    patchStep(rollbackPassing(), "hotApply", { graphAfterPost: 1 }),
    { ...rollbackPassing(), modelRequests: [...rollbackPassing().modelRequests, { marker: "GENUINE-hotb2" }] },
    { ...rollbackPassing(), hooks: [...rollbackPassing().hooks, { params: { ref: "genuine-hotb2" } }] },
    patchStep(rollbackPassing(), "hotApplyEnd", null),
    patchStep(rollbackPassing(), "hotApplyEnd", { listenerStartedAfterEdit: 1 }),
    patchStep(rollbackPassing(), "hotApplyEnd", { listenerStartedAfterEdit: undefined }),
    patchStep(rollbackPassing(), "hotApplyEnd", { portRefusedAtEnd: false }),
    // a send no window recorded (a duplicate, or a late one before the final read)
    { ...rollbackPassing(), graph: [...rollbackPassing().graph, { at: 9000, body: REF_BODY }] },
  ];
  for (const [i, e] of H.entries()) assert.equal(evaluateCloudRollback(e).checks.H.pass, false, `H case ${i}`);
  const F = [
    patchStep(rollbackPassing(), "freshOff", null),
    patchStep(rollbackPassing(), "freshOff", { registered: false }),
    patchStep(rollbackPassing(), "freshOff", { listenerStartedLogged: true }),
    patchStep(rollbackPassing(), "freshOff", { portRefused: false }),
    patchStep(rollbackPassing(), "freshOff", { refusals: ["bad-config"] }),
    patchStep(rollbackPassing(), "freshOff", { refusals: null }),
    patchStep(rollbackPassing(), "freshOff", { graphDuring: 1 }),
    patchStep(rollbackPassing(), "freshOff", { offConfirmed: false }),
    patchStep(rollbackPassing(), "freshOff", { firstExited: false }),
  ];
  for (const [i, e] of F.entries()) assert.equal(evaluateCloudRollback(e).checks.F.pass, false, `F case ${i}`);
  const V = [
    patchStep(rollbackPassing(), "fullRollback", null),
    patchStep(rollbackPassing(), "fullRollback", { unsetStatus: 1 }),
    patchStep(rollbackPassing(), "fullRollback", { validateStatus: 1 }),
    patchStep(rollbackPassing(), "fullRollback", { getAfterUnsetStatus: 0 }),
    patchStep(rollbackPassing(), "fullRollback", { disableStatus: 1 }),
    patchStep(rollbackPassing(), "fullRollback", { enabledAfterDisable: true }),
    patchStep(rollbackPassing(), "fullRollback", { enabledAfterDisable: null }),
    patchStep(rollbackPassing(), "fullRollback", { secondExited: false }),
    patchStep(rollbackPassing(), "fullRollback", { getAfterUnsetStatus: 2 }),
    patchStep(rollbackPassing(), "fullRollback", { getAfterUnsetMessage: null }),
    patchStep(rollbackPassing(), "fullRollback", { getAfterUnsetMessage: "Unknown config path: plugins.entries.idx-whatsapp-channel.config.cloudApi" }),
  ];
  for (const [i, e] of V.entries()) assert.equal(evaluateCloudRollback(e).checks.V.pass, false, `V case ${i}`);
});

test("HC-16 O: the runbook's owner checks pass only on the exact clean or confirmed output, and the negative probes must not print it", () => {
  const smoke = { pass: ["leaks: clean", "failures: clean"], wrongCount: ["REVIEW: inbound messages: 1, expected 2", "leaks: not checked", "failures: not checked"], leakProbe: ["leaks: REVIEW: abort", "failures: clean"] };
  const S = (o) => evaluateOwnerChecks({ mode: "cloud-api", steps: [{ ownerSmoke: o }] }).pass;
  assert.equal(S(smoke), true);
  for (const bad of [
    null,
    { ...smoke, pass: ["leaks: clean"] },
    { ...smoke, pass: ["leaks: REVIEW: abort", "failures: clean"] },
    { ...smoke, pass: ["REVIEW: the log read failed", "leaks: not checked", "failures: not checked"] },
    { ...smoke, wrongCount: ["leaks: clean", "failures: clean"] },
    { ...smoke, wrongCount: ["REVIEW: inbound messages: 1, expected 2", "leaks: clean", "failures: clean"] },
    { ...smoke, leakProbe: ["leaks: clean", "failures: clean"] },
  ]) assert.equal(S(bad), false, JSON.stringify(bad));
  const confirmed = "rollback confirmed: listener-stopped logged and the port is closed";
  const roll = { before: ["NOT CONFIRMED: no listener-stopped since ROLLBACK_START", "NOT CONFIRMED: the listener's port did not refuse (curl exit 0, HTTP code 404)"], after: [confirmed] };
  const R = (o) => evaluateOwnerChecks({ mode: "cloud-api-rollback", steps: [{ ownerRollback: o }] }).pass;
  assert.equal(R(roll), true);
  for (const bad of [
    null,
    { ...roll, after: [] },
    { ...roll, after: ["NOT CONFIRMED: the log read failed", confirmed] },
    { ...roll, before: [confirmed] },
    { ...roll, before: ["NOT CONFIRMED: no listener-stopped since ROLLBACK_START"] },
    { ...roll, before: [...roll.before, confirmed] },
  ]) assert.equal(R(bad), false, JSON.stringify(bad));
  assert.equal(evaluateOwnerChecks({ mode: "default", steps: [] }), null);
});

// ---- WO-040: persistent dedupe across a gateway restart ------------------------------------

const RS_APPROVED = "Synthetic approved reply";
const rsBody = (approved) =>
  JSON.stringify({ messaging_product: "whatsapp", recipient_type: "individual", to: "15555550101", type: "text", text: { preview_url: false, body: approved } });
function restartPassing() {
  return {
    graph: [{ at: 1000, body: rsBody(RS_APPROVED) }, { at: 9000, body: rsBody(RS_APPROVED) }],
    hooks: [{ params: { ref: "genuine-a1" } }, { params: { ref: "genuine-b2" } }],
    toolExec: [{ ref: "genuine-a1" }, { ref: "genuine-b2" }],
    expected: { peerWa: "15555550101", approved: RS_APPROVED },
    steps: [
      { beforeRestart: { status: 200, reachedHook: true, graph: 1 } },
      { restart: { firstExited: true, store: { mode: 0o700, entries: 1, holdsId: false }, readyAgain: true, replayStatus: 200, acceptedAfter: [[0, 1], [1, 0]], graphAfterReplay: 0, modelAfterReplay: 0, marker: "GENUINE-a1", next: { status: 200, reachedHook: true }, nextMarker: "GENUINE-b2", graphTotal: 2, refusals: [] } },
    ],
  };
}

test("HC-17 E: the passing restart record passes; a delivered duplicate, a second tool run, a send after the replay, a missing or leaky store, and every missing piece of evidence fail", () => {
  assert.equal(evaluateCloudRestart(restartPassing()).pass, true);
  const fail = [
    patchStep(restartPassing(), "restart", { acceptedAfter: [[1, 0], [1, 0]] }),
    patchStep(restartPassing(), "restart", { acceptedAfter: [] }),
    patchStep(restartPassing(), "restart", { graphAfterReplay: 1 }),
    patchStep(restartPassing(), "restart", { modelAfterReplay: 1 }),
    patchStep(restartPassing(), "restart", { modelAfterReplay: undefined }),
    { ...restartPassing(), toolExec: [...restartPassing().toolExec, { ref: "genuine-a1" }] },
    { ...restartPassing(), hooks: [...restartPassing().hooks, { params: { ref: "genuine-a1" } }] },
    patchStep(restartPassing(), "restart", { store: null }),
    patchStep(restartPassing(), "restart", { store: { mode: 0o755, entries: 1, holdsId: false } }),
    patchStep(restartPassing(), "restart", { store: { mode: 0o700, entries: 0, holdsId: false } }),
    patchStep(restartPassing(), "restart", { store: { mode: 0o700, entries: 1, holdsId: true } }),
    patchStep(restartPassing(), "restart", { firstExited: false }),
    patchStep(restartPassing(), "restart", { readyAgain: false }),
    patchStep(restartPassing(), "restart", { replayStatus: 503 }),
    patchStep(restartPassing(), "restart", { refusals: ["write-failed"] }),
    patchStep(restartPassing(), "restart", { next: { status: 200, reachedHook: false } }),
    patchStep(restartPassing(), "restart", null),
    patchStep(restartPassing(), "beforeRestart", { graph: 0 }),
    { ...restartPassing(), graph: restartPassing().graph.slice(0, 1) },
    { ...restartPassing(), graph: [...restartPassing().graph, { at: 9500, body: rsBody(RS_APPROVED) }] },
    { ...restartPassing(), graph: [restartPassing().graph[0], { at: 9000, body: rsBody("other") }] },
  ];
  for (const [i, e] of fail.entries()) assert.equal(evaluateCloudRestart(e).pass, false, `case ${i}`);
});

test("HC-18 T (WO-041): the host-presented card-tool names must be exactly the pinned literal names; a suffixed, cut or missing name, an admitted call under another name, or no tool list fails", () => {
  const PINNED = ["idx__find_similar_listings", "idx__get_market_stats", "idx__recommend", "idx__search_listings"];
  const list = [...PINNED, "idx__get_listing_details", "message"];
  const admit = (toolName) => ({ toolName, decision: { block: false, marked: 1 } });
  const good = { modelRequests: [{ toolNames: list }, { toolNames: list }], hooks: [admit("idx__search_listings"), { toolName: "message", decision: { block: false } }] };
  const t = evaluateToolNames(good);
  assert.equal(t.pass, true);
  assert.deepEqual(t.presentedCardTools, PINNED);
  assert.deepEqual(t.admittedCardTools, ["idx__search_listings"]);
  const swap = (from, to) => list.map((n) => (n === from ? to : n));
  for (const [name, e] of [
    ["no model request", { ...good, modelRequests: [] }],
    ["no tool list", { ...good, modelRequests: [{ toolNames: [] }] }],
    ["the host suffixed a name", { ...good, modelRequests: [{ toolNames: swap("idx__recommend", "idx__recommend-2") }] }],
    ["a pinned name missing", { ...good, modelRequests: [{ toolNames: list.filter((n) => n !== "idx__get_market_stats") }] }],
    ["another spelling beside the pin", { ...good, modelRequests: [{ toolNames: [...list, "mcp__idx__search_listings"] }] }],
    ["one later request differs", { ...good, modelRequests: [{ toolNames: list }, { toolNames: swap("idx__search_listings", "idx__search_listings-2") }] }],
    ["an admitted call under another name", { ...good, hooks: [admit("idx__search_listings-2")] }],
    ["no admitted card call", { ...good, hooks: [] }],
    ["payloads: a pinned tool never admitted", { ...good, requireAllCalled: true }],
  ]) {
    assert.equal(evaluateToolNames(e).pass, false, name);
  }
  assert.equal(evaluateToolNames({ ...good, requireAllCalled: true, hooks: PINNED.map(admit) }).pass, true);
});

test("HC-19 Z (WO-041): stock-present passes only when phase 1 refuses with the stock loaded, the disable lands, and phase 2 loads ours alone; each missing or wrong piece fails", () => {
  const call = (allowHasStock, stockEntryEnabledSeen) => ({ mode: "full", allowHasStock, allowHasOurs: true, stockEntryEnabledSeen, dmScopeSeen: "per-channel-peer" });
  const steps = [
    { stockSetup: { integrityOk: true, extracted: true, install: { status: 0 }, allowRestore: { status: 0 }, configAfterInstall: { allowAddedStock: true, stockEntryEnabled: true }, configBeforePhase1: { allowHasStock: false, stockEntryEnabled: true } } },
    {
      stockPhase1: {
        register: { calls: [call(true, true), call(true, true)], registered: 0, threw: ["stock-whatsapp-not-denied", "stock-whatsapp-not-denied"], started: 0 },
        activationLog: ["- whatsapp plugin config present, added to plugin allowlist.", "[plugins] loading whatsapp from /x/stock/package"],
      },
      stockDisable: { status: 0, allowHasStock: false, stockEntryEnabled: false },
    },
  ];
  const phase2 = { register: { calls: [call(false, false), call(false, false)], registered: 2, threw: [], started: 1 }, activationLog: [] };
  assert.equal(evaluateStockPresent({ steps, phase2 }).pass, true);
  const withStep = (k, v) => steps.map((s) => (s[k] !== undefined ? { ...s, [k]: v } : s));
  const p1 = steps[1].stockPhase1;
  for (const [name, e] of [
    ["no tarball / bad integrity", { steps: withStep("stockSetup", { ...steps[0].stockSetup, integrityOk: false }), phase2 }],
    ["install failed", { steps: withStep("stockSetup", { ...steps[0].stockSetup, install: { status: 1 } }), phase2 }],
    ["allow still names the stock plugin before phase 1", { steps: withStep("stockSetup", { ...steps[0].stockSetup, configBeforePhase1: { allowHasStock: true } }), phase2 }],
    ["phase 1: ours registered", { steps: withStep("stockPhase1", { ...p1, register: { ...p1.register, registered: 1, threw: ["stock-whatsapp-not-denied"] } }), phase2 }],
    ["phase 1: another refusal", { steps: withStep("stockPhase1", { ...p1, register: { ...p1.register, threw: ["config-missing", "stock-whatsapp-not-denied"] } }), phase2 }],
    ["phase 1: the host did not add the stock id", { steps: withStep("stockPhase1", { ...p1, register: { ...p1.register, calls: [call(false, true), call(true, true)] } }), phase2 }],
    ["phase 1: the stock plugin never loaded", { steps: withStep("stockPhase1", { ...p1, activationLog: [] }), phase2 }],
    ["disable failed", { steps: withStep("stockDisable", { status: 1, allowHasStock: false, stockEntryEnabled: false }), phase2 }],
    ["disable left the entry enabled", { steps: withStep("stockDisable", { status: 0, allowHasStock: false, stockEntryEnabled: true }), phase2 }],
    ["phase 2: a register saw the stock id", { steps, phase2: { ...phase2, register: { ...phase2.register, calls: [call(false, false), call(true, false)] } } }],
    ["phase 2: a refusal", { steps, phase2: { ...phase2, register: { ...phase2.register, threw: ["stock-whatsapp-not-denied"] } } }],
    ["phase 2: the channel never started", { steps, phase2: { ...phase2, register: { ...phase2.register, started: 0 } } }],
    ["phase 2: the stock plugin loaded", { steps, phase2: { ...phase2, activationLog: ["[plugins] loading whatsapp from /x"] } }],
    ["phase 2: an ownership conflict", { steps, phase2: { ...phase2, activationLog: ["channel already registered: whatsapp (whatsapp)"] } }],
    ["phase 2: no evidence", { steps, phase2: { register: { calls: [], registered: 0, threw: [], started: 0 }, activationLog: [] } }],
  ]) {
    assert.equal(evaluateStockPresent(e).pass, false, name);
  }
});
