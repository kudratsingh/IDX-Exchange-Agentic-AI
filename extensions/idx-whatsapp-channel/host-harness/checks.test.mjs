/**
 * Offline tests of the harness's evidence rules (checks.mjs). Synthetic evidence only; no
 * host runs here. Each test changes one piece of a passing record and shows the check fails.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { evaluate } from "./checks.mjs";

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
