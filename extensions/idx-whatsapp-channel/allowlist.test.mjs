/**
 * Inbound sender allowlist (runbook C3, owned-channel install item 2, 2026-11-07).
 * Synthetic 555 numbers only.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { resolveDmAccess, senderAllowed } from "./allowlist.mjs";
import { createChannelPlugin } from "./channel.mjs";
import { BUSY_TEXT } from "./constants.mjs";
import { createIngress } from "./ingress.mjs";
import { createFakeTransport } from "./test-support/fake-transport.mjs";
import { createFakeHost } from "./test-support/host-emulation.mjs";

const P1 = "+15550000001";
const P2 = "+15550000002";
const P5 = "+15550000005";
const wa = (whatsapp) => ({ plugins: { deny: ["whatsapp"] }, channels: { whatsapp }, session: { dmScope: "per-channel-peer" } });
const CFG = wa({ dmPolicy: "allowlist", allowFrom: [P1, P2] });

/** A channel over the fake host whose every log line is kept. */
async function channel(cfg, { replies = () => "Hello!", hold } = {}) {
  const transport = createFakeTransport();
  const ingress = createIngress();
  const logs = [];
  const calls = { routes: 0 };
  const host = createFakeHost({ replies, hold });
  const plugin = createChannelPlugin({
    transport,
    ingress,
    log: { info: (m) => logs.push(m), warn: (m) => logs.push(m), error: (m) => logs.push(m) },
    resolveRoute: (args) => {
      calls.routes += 1;
      return host.resolveRoute(args);
    },
    runInbound: host.runInbound,
  });
  await plugin.gateway.startAccount({ cfg, accountId: "default" });
  return { transport, ingress, logs, calls, host, plugin };
}

const inbound = (h, peerId, text = "hi there") => h.transport.inbound({ accountId: "default", peerId, text, messageId: "m", receivedAt: 1 });

test("AL-1 resolveDmAccess: a well-formed allowlist resolves to the canonical phone ids", () => {
  const r = resolveDmAccess(CFG, "default");
  assert.equal(r.ok, true);
  assert.deepEqual([...r.allowed].sort(), [P1, P2]);
});

test("AL-2 fail closed: missing, empty, non-array or malformed allowFrom, a policy other than allowlist, or a disabled channel drops everyone", () => {
  const cases = [
    [undefined, "no-channel-config"],
    [{}, "no-channel-config"],
    [{ plugins: {} }, "no-channel-config"],
    [{ channels: { whatsapp: "yes" } }, "no-channel-config"],
    [wa({ allowFrom: [P1] }), "dm-policy-not-allowlist"],
    [wa({ dmPolicy: "open", allowFrom: [P1] }), "dm-policy-not-allowlist"],
    [wa({ dmPolicy: "pairing", allowFrom: [P1] }), "dm-policy-not-allowlist"],
    [wa({ dmPolicy: "Allowlist", allowFrom: [P1] }), "dm-policy-not-allowlist"],
    [wa({ dmPolicy: "allowlist" }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [] }), "allowlist-empty"],
    [wa({ dmPolicy: "allowlist", allowFrom: P1 }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: { 0: P1 } }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "*"] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, ""] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "   "] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, 15550000002] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, null] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "__OWNER_E164__"] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "15550000002@lid"] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "+1555"] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "+1555000000100000"] }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "owner"] }), "allowlist-malformed"],
    [wa({ enabled: false, dmPolicy: "allowlist", allowFrom: [P1] }), "channel-disabled"],
  ];
  for (const [cfg, reason] of cases) {
    assert.deepEqual(resolveDmAccess(cfg, "default"), { ok: false, reason }, JSON.stringify(cfg));
    assert.deepEqual(senderAllowed(cfg, "default", P1), { allowed: false, reason }, JSON.stringify(cfg));
  }
  // a config whose getter throws drops everyone too
  const throwing = { channels: { get whatsapp() { throw new Error("boom"); } } };
  assert.deepEqual(senderAllowed(throwing, "default", P1), { allowed: false, reason: "allowlist-error" });
});

test("AL-3 per-account override: a present accounts.<id> key wins and never falls back; other accounts use the channel-wide list", () => {
  const cfg = wa({ dmPolicy: "allowlist", allowFrom: [P1], accounts: { default: { allowFrom: [P2] }, other: { allowFrom: [] } } });
  assert.deepEqual(senderAllowed(cfg, "default", P2), { allowed: true });
  assert.deepEqual(senderAllowed(cfg, "default", P1), { allowed: false, reason: "sender-not-allowed" });
  assert.deepEqual(senderAllowed(cfg, "other", P1), { allowed: false, reason: "allowlist-empty" });
  assert.deepEqual(senderAllowed(cfg, "third", P1), { allowed: true }, "no account key: the channel-wide list");
  assert.deepEqual(senderAllowed(cfg, undefined, P2), { allowed: true }, "a missing account id is 'default'");
  // the account's own policy wins as well
  const open = wa({ dmPolicy: "allowlist", allowFrom: [P1], accounts: { default: { dmPolicy: "open" } } });
  assert.deepEqual(senderAllowed(open, "default", P1), { allowed: false, reason: "dm-policy-not-allowlist" });
  const disabled = wa({ dmPolicy: "allowlist", allowFrom: [P1], accounts: { default: { enabled: false } } });
  assert.deepEqual(senderAllowed(disabled, "default", P1), { allowed: false, reason: "channel-disabled" });
  for (const bad of [{ accounts: [] }, { accounts: "x" }, { accounts: { default: null } }, { accounts: { default: [P1] } }]) {
    assert.equal(senderAllowed(wa({ dmPolicy: "allowlist", allowFrom: [P1], ...bad }), "default", P1).allowed, false, JSON.stringify(bad));
  }
  // an inherited name is not an account key
  assert.deepEqual(senderAllowed(wa({ dmPolicy: "allowlist", allowFrom: [P1], accounts: {} }), "constructor", P1), { allowed: true });
});

test("AL-4 normalisation equivalences: entries and senders are compared in canonical form", () => {
  const spellings = [P1, "+1 555 000 0001", "whatsapp:+15550000001", "WhatsApp: +15550000001", "15550000001@s.whatsapp.net", "15550000001@c.us", "1-555-000-0001", "+1 (555) 000.0001", " +15550000001 "];
  for (const entry of spellings) {
    for (const sender of spellings) {
      assert.deepEqual(senderAllowed(wa({ dmPolicy: "allowlist", allowFrom: [entry] }), "default", sender), { allowed: true }, `${entry} / ${sender}`);
    }
  }
});

test("AL-5 senders outside the list are dropped: another number, the linked-id form, a prefix or suffix variant of another number, garbage", () => {
  for (const sender of [P5, "15550000001@lid", "+155500000011", "+5550000001", "whatsapp:+15550000003", "15550000004@s.whatsapp.net", "", "   ", undefined, null, 15550000001, {}, "agent:idx:whatsapp:direct:+15550000001"]) {
    assert.deepEqual(senderAllowed(CFG, "default", sender), { allowed: false, reason: "sender-not-allowed" }, String(sender));
  }
});

test("AL-6 channel: an allowed sender runs; a dropped one reaches nothing (no route, no record, no run, no reply) and leaves one audit line with no peer and no text", async () => {
  const h = await channel(CFG);
  await inbound(h, P1);
  assert.deepEqual(h.transport.sent.map((s) => s.text), ["Hello!"]);
  assert.equal(h.host.turns.length, 1);
  assert.equal(h.calls.routes, 1);
  const sizeBefore = h.ingress.size();
  const logsBefore = h.logs.length;
  for (const sender of [P5, "15550000001@lid", "whatsapp:+15550000005", "15550000005@s.whatsapp.net"]) {
    await inbound(h, sender, "secret text 650000");
  }
  assert.equal(h.transport.sent.length, 1, "nothing sent to a dropped sender");
  assert.equal(h.host.turns.length, 1, "no run");
  assert.equal(h.calls.routes, 1, "no route");
  assert.equal(h.ingress.size(), sizeBefore, "no record");
  const dropped = h.logs.slice(logsBefore);
  assert.equal(dropped.length, 4);
  for (const line of dropped) {
    assert.deepEqual(line, { component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason: "sender-not-allowed" });
  }
  assert.ok(!/5550000|secret|650000|lid/.test(JSON.stringify(h.logs)), "no peer, no text in any log line");
});

test("AL-7 channel: the allowlist runs before the busy check: a dropped sender gets no BUSY_TEXT even while the allowed peer's run is open", async () => {
  let release;
  const held = new Promise((r) => { release = r; });
  const h = await channel(CFG, { hold: () => held });
  const first = inbound(h, P1);
  await new Promise((r) => setImmediate(r));
  assert.ok(h.ingress.hasActiveTurn(h.ingress.key("default", P1)));
  await inbound(h, "15550000001@lid", "are you there?");
  await inbound(h, P5, "are you there?");
  assert.ok(!h.transport.sent.some((s) => s.text === BUSY_TEXT), "no busy reply to a dropped sender");
  // the allowed peer still gets the busy reply
  await inbound(h, P1, "are you there?");
  assert.deepEqual(h.transport.sent.map((s) => s.text), ["Hello!", BUSY_TEXT]);
  release();
  await first;
  assert.equal(h.host.turns.length, 1);
});

test("AL-8 channel: with an empty, missing or malformed list even the owner's number is dropped, and startAccount says so once (reason only)", async () => {
  for (const [cfg, reason] of [
    [wa({ dmPolicy: "allowlist", allowFrom: [] }), "allowlist-empty"],
    [wa({ dmPolicy: "allowlist" }), "allowlist-malformed"],
    [wa({ dmPolicy: "allowlist", allowFrom: [P1, "*"] }), "allowlist-malformed"],
    [{ plugins: { deny: ["whatsapp"] }, session: { dmScope: "per-channel-peer" } }, "no-channel-config"],
    [wa({ dmPolicy: "pairing", allowFrom: [P1] }), "dm-policy-not-allowlist"],
  ]) {
    const h = await channel(cfg);
    assert.deepEqual(h.logs, [{ component: "idx-whatsapp-channel.ingress", event: "allowlist-invalid", reason }]);
    await inbound(h, P1);
    assert.equal(h.transport.sent.length, 0, reason);
    assert.equal(h.host.turns.length, 0, reason);
    assert.equal(h.ingress.size(), 0, reason);
    assert.deepEqual(h.logs.at(-1), { component: "idx-whatsapp-channel.ingress", event: "inbound-dropped", reason });
  }
  // a valid list logs nothing at start
  assert.deepEqual((await channel(CFG)).logs, []);
});

test("AL-9 the channel restarts on a channels.whatsapp change, so the list in force is the current one", () => {
  const plugin = createChannelPlugin({});
  assert.deepEqual(plugin.reload, { configPrefixes: ["channels.whatsapp"] });
});

test("AL-10 (source): in onInbound the allowlist check is the first statement, before the runner check, the busy check, the route, the record and the run", () => {
  const src = readFileSync(new URL("./channel.mjs", import.meta.url), "utf8");
  const body = src.slice(src.indexOf("async function onInbound(scope, msg) {"));
  const at = (s) => {
    const i = body.indexOf(s);
    assert.ok(i >= 0, s);
    return i;
  };
  const check = at("senderAllowed(scope.cfg, scope.accountId, msg?.peerId)");
  for (const later of ["if (!resolveRoute || !runInbound)", "ingress.hasActiveTurn(key)", "resolveRoute({", "ingress.record(", "await runInbound("]) {
    assert.ok(check < at(later), later);
  }
  const code = body.slice(0, check).replace(/\/\/.*$/gm, "").replace(/[\s{]/g, "");
  assert.equal(code, "asyncfunctiononInbound(scope,msg)constaccess=", "nothing runs before the check");
});

test("AL-11 manifest: channels.whatsapp schema names the keys, refuses unknown ones, accepts enabled and only the allowlist policy", () => {
  const manifest = JSON.parse(readFileSync(new URL("./openclaw.plugin.json", import.meta.url), "utf8"));
  const schema = manifest.channelConfigs.whatsapp.schema;
  assert.equal(schema.type, "object");
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(Object.keys(schema.properties).sort(), ["accounts", "allowFrom", "configWrites", "dmPolicy", "enabled", "groupPolicy", "selfChatMode"]);
  assert.deepEqual(schema.properties.enabled, { type: "boolean" });
  assert.deepEqual(schema.properties.dmPolicy.enum, ["allowlist"]);
  assert.equal(schema.properties.allowFrom.type, "array");
  const account = schema.properties.accounts.additionalProperties;
  assert.equal(account.additionalProperties, false);
  assert.deepEqual(Object.keys(account.properties).sort(), ["allowFrom", "dmPolicy", "enabled"]);
});
