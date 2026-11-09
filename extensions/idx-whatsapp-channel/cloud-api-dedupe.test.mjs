// WO-040 persistent dedupe, offline. Every store lives in a fresh OS temp directory (mode
// 700) that is removed after; message ids are synthetic (`wamid.TEST-...`), peers 555
// numbers. A "restart" is a second store (or webhook, or transport) opened on the same
// directory; DD-12 uses real child processes. Nothing here reaches a network.
import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import {
  chmodSync,
  constants as fsConstants,
  linkSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync as openReal,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
  writeSync as writeReal,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  DEDUPE_DIR_NAME,
  DEDUPE_RETENTION_MS,
  DEDUPE_STORE_MAX_ENTRIES,
  DEDUPE_WINDOW_MS,
  DedupeStoreError,
  dedupeDirFor,
  openDedupeStore,
} from "./cloud-api-dedupe.mjs";
import { MAX_CLOCK_SKEW_MS, MAX_INBOUND_AGE_MS, createCloudApiTransport, createCloudApiWebhook } from "./cloud-api-transport.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const T0 = 1_794_200_000_000;
const id = (n) => `wamid.TEST-${String(n).padStart(6, "0")}`;
const noAcl = () => false;

/** A fresh owner-only parent directory and the store directory path in it. */
function sandbox() {
  const parent = mkdtempSync(path.join(tmpdir(), "idx-wa-dd-"));
  chmodSync(parent, 0o700);
  const cleanup = () => {
    for (const p of [parent, path.join(parent, DEDUPE_DIR_NAME)]) {
      try {
        chmodSync(p, 0o700);
      } catch {
        /* not there */
      }
    }
    rmSync(parent, { recursive: true, force: true });
  };
  return { parent, dir: path.join(parent, DEDUPE_DIR_NAME), cleanup };
}
function clock(t = T0) {
  const c = { t, now: () => c.t };
  return c;
}
const KEY_ID = "1000000000040";
const open = (dir, c, extra = {}) => openDedupeStore({ dir, keyId: KEY_ID, now: c.now, hasExtendedAcl: noAcl, ...extra });
/** The marker name for an id, computed independently of the module. */
const keyOf = (m, keyId = KEY_ID) => {
  const k = createHmac("sha256", "idx-whatsapp-channel/cloud-api-dedupe/v1").update(keyId, "utf8").digest();
  return createHmac("sha256", k).update(m, "utf8").digest("hex").slice(0, 32);
};
const reasonIs = (reason) => (e) => e instanceof DedupeStoreError && e.reason === reason && e.message === `idx-whatsapp-channel: dedupe store: ${reason}`;
const markerNames = (dir) => readdirSync(dir).sort();
const listing = (dir) => {
  try {
    return readdirSync(dir).sort().join(",");
  } catch {
    return null;
  }
};

test("DD-1 the first open makes the store: an empty mode-700 directory (no salt file: markers are keyed by the business number); a second open changes nothing; no temporary file is left; a missing key is refused", () => {
  const s = sandbox();
  try {
    open(s.dir, clock());
    assert.equal(lstatSync(s.dir).mode & 0o777, 0o700);
    assert.deepEqual(readdirSync(s.dir), []);
    open(s.dir, clock());
    assert.deepEqual(readdirSync(s.dir), []);
    assert.throws(() => openDedupeStore({ dir: s.dir, hasExtendedAcl: noAcl }), reasonIs("no-key"));
  } finally {
    s.cleanup();
  }
});

test("DD-2 a claim is one marker named HMAC-SHA256(number key, id)[0:128 bits] holding Meta's timestamp; claiming again is false; a restart still knows it; no id, peer or text is on disk", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c);
    assert.equal(a.claim(id(1), T0 - 60_000), true);
    assert.equal(a.claim(id(1), T0 - 60_000), false, "a duplicate");
    assert.equal(a.claim(id(2), T0 - 30_000), true);
    const key = keyOf(id(1));
    assert.ok(markerNames(s.dir).includes(key), "named HMAC(key from the phone-number id, id), first 128 bits");
    assert.notEqual(keyOf(id(1), "1000000000041"), key, "another number, another name");
    assert.equal(readFileSync(path.join(s.dir, key), "utf8"), String(T0 - 60_000));
    assert.equal(lstatSync(path.join(s.dir, key)).mode & 0o777, 0o600);
    for (const n of readdirSync(s.dir)) assert.ok(!n.includes("wamid") && !readFileSync(path.join(s.dir, n), "utf8").includes("wamid"), "no id on disk");
    const b = open(s.dir, c); // restart
    assert.equal(b.claim(id(1), T0 - 60_000), false);
    assert.equal(b.claim(id(3), T0), true);
    assert.equal(b.size(), 3);
  } finally {
    s.cleanup();
  }
});

test("DD-3 retention is 24 hours, far past the 35-minute acceptance window: a wall-clock step forward and back keeps the id, in one instance and after a restart; markers older than 24 hours are pruned", () => {
  assert.equal(DEDUPE_WINDOW_MS, MAX_INBOUND_AGE_MS + MAX_CLOCK_SKEW_MS);
  assert.equal(DEDUPE_RETENTION_MS, 86_400_000);
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c, { pruneIntervalMs: 0 });
    assert.equal(a.claim(id(1), T0), true);
    c.t = T0 + 36 * 60_000; // the clock jumps 36 minutes ahead
    assert.equal(a.claim(id(2), c.t), true);
    c.t = T0 + 2 * 60_000; // and is corrected
    assert.equal(a.claim(id(1), T0), false, "Meta's retry after the correction is still a duplicate");
    assert.equal(open(s.dir, c).claim(id(1), T0), false, "and after a restart");
    // A clock more than 24 hours fast at a restart prunes nothing: expiry is measured from
    // no further ahead than the newest marker plus the window (review 2026-11-09).
    c.t = T0 + DEDUPE_RETENTION_MS + 60 * 60_000;
    const fast = open(s.dir, c, { pruneIntervalMs: 0 });
    assert.equal(fast.has(id(1)), true, "the fast clock expired nothing");
    c.t = T0 + 5 * 60_000; // NTP corrects it
    assert.equal(fast.claim(id(1), T0), false, "Meta's retry is still a duplicate");
    // Real traffic moves the reference: a new marker 24 hours on lets the old one expire.
    c.t = T0 + 36 * 60_000 + DEDUPE_RETENTION_MS + 1;
    const b = open(s.dir, c, { pruneIntervalMs: 0 });
    assert.equal(b.claim(id(9), c.t), true);
    b.claim(id(10), c.t);
    assert.equal(b.has(id(1)), false, "pruned once a marker 24 hours newer exists");
    assert.equal(b.has(id(9)), true);
  } finally {
    s.cleanup();
  }
});

test("DD-4 bounded and fail-closed: when full, markers past the acceptance window go first (oldest first); full of markers inside it, a claim is refused (`full`) and nothing is removed; a store over the cap is refused at open", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c, { maxEntries: 3 });
    a.claim(id(1), T0 - 3);
    a.claim(id(2), T0 - 2);
    a.claim(id(3), T0 - 1);
    const before = markerNames(s.dir);
    assert.throws(() => a.claim(id(4), T0), reasonIs("full"));
    assert.deepEqual(markerNames(s.dir), before);
    assert.equal(a.has(id(4)), false);
    c.t = T0 - 3 + DEDUPE_WINDOW_MS + 1; // only id 1 is past the window now
    assert.equal(a.claim(id(4), c.t), true);
    assert.equal(a.has(id(1)), false);
    assert.equal(a.has(id(2)), true);
    assert.equal(DEDUPE_STORE_MAX_ENTRIES, 4096);
    // Open prunes before it counts; only a store still far over the cap is refused.
    assert.throws(() => open(s.dir, c, { maxEntries: 1, capSlack: 0 }), reasonIs("too-many-entries"));
    assert.doesNotThrow(() => open(s.dir, c, { maxEntries: 2, capSlack: 1 }));
    // A clock a day fast evicts nothing from a full store (review round 4): eviction inside
    // the retention needs a Meta time showing the marker can no longer be accepted.
    c.t = T0 + DEDUPE_RETENTION_MS + DEDUPE_WINDOW_MS;
    const later = open(s.dir, c, { maxEntries: 3 });
    assert.equal(later.size(), 3, "nothing evicted at open");
    assert.throws(() => later.claim(id(5), T0 - 3 + DEDUPE_WINDOW_MS + 1), reasonIs("full"), "a message no newer than the newest marker frees nothing");
    assert.equal(later.claim(id(6), T0 + DEDUPE_WINDOW_MS + 10), true, "a message whose Meta time puts the oldest past the window frees room");
    assert.equal(later.has(id(2)), false);
  } finally {
    s.cleanup();
  }
});

test("DD-5 open refuses an unsafe or unexpected store with a fixed reason and changes nothing", () => {
  const firstMarker = (s) => path.join(s.dir, markerNames(s.dir).find((n) => /^[0-9a-f]{32}$/.test(n)));
  const cases = [
    ["symlink", (s) => { mkdirSync(path.join(s.parent, "real"), { mode: 0o700 }); symlinkSync(path.join(s.parent, "real"), s.dir); }],
    ["not-directory", (s) => writeFileSync(s.dir, "x", { mode: 0o600 })],
    ["permissions-too-open", (s) => { open(s.dir, clock()); chmodSync(s.dir, 0o750); }],
    ["unexpected-file", (s) => { open(s.dir, clock()); writeFileSync(path.join(s.dir, "notes.txt"), "x", { mode: 0o600 }); }],
    ["unexpected-file", (s) => { open(s.dir, clock()); writeFileSync(path.join(s.dir, "salt"), "00".repeat(32), { mode: 0o600 }); }],
    ["symlink", (s) => { open(s.dir, clock()); writeFileSync(path.join(s.parent, "elsewhere"), "x", { mode: 0o600 }); symlinkSync(path.join(s.parent, "elsewhere"), path.join(s.dir, keyOf(id(9)))); }],
    ["hard-linked", (s) => { open(s.dir, clock()).claim(id(1), T0); linkSync(firstMarker(s), path.join(s.parent, "copy")); }],
    ["permissions-too-open", (s) => { open(s.dir, clock()).claim(id(1), T0); chmodSync(firstMarker(s), 0o644); }],
    ["unsafe-directory", (s) => chmodSync(s.parent, 0o770)],
  ];
  for (const [reason, setup] of cases) {
    const s = sandbox();
    try {
      setup(s);
      const before = listing(s.dir);
      assert.throws(() => open(s.dir, clock()), reasonIs(reason), reason);
      assert.equal(listing(s.dir), before, `${reason}: nothing changed`);
    } finally {
      s.cleanup();
    }
  }
  const s = sandbox();
  try {
    open(s.dir, clock());
    assert.throws(() => open(s.dir, clock(), { uid: (process.getuid?.() ?? 0) + 1 }), reasonIs("unsafe-directory"), "another user's parent");
    assert.throws(() => open(s.dir, clock(), { hasExtendedAcl: (p) => p === s.dir }), reasonIs("acl-present"));
    assert.throws(() => open(s.dir, clock(), { hasExtendedAcl: () => { throw new Error("ls failed"); } }), reasonIs("acl-unknown"));
    assert.throws(() => openDedupeStore({ dir: "relative", hasExtendedAcl: noAcl }), reasonIs("not-absolute"));
    assert.throws(() => open(path.join(s.parent, "missing", DEDUPE_DIR_NAME), clock()), reasonIs("unsafe-directory"));
  } finally {
    s.cleanup();
  }
});

test("DD-6 writes: a claim whose create fails throws `write-failed` and claims nothing; once the marker exists, a failure stamping it still counts as claimed (an empty marker is a claim, and expires by its file time); a store that cannot be written is refused at open (`unwritable`), new or existing", () => {
  const s = sandbox();
  try {
    const c = clock();
    let failCreate = false;
    let failWrite = false;
    const fs = {
      openSync: (p, f, m) => {
        if (failCreate && path.basename(p).length === 32) throw Object.assign(new Error("ENOSPC"), { code: "ENOSPC" });
        return openReal(p, f, m);
      },
      writeSync: (...args) => {
        if (failWrite) throw Object.assign(new Error("EIO"), { code: "EIO" });
        return writeReal(...args);
      },
    };
    const a = open(s.dir, c, { fs, pruneIntervalMs: 0 });
    failCreate = true;
    assert.throws(() => a.claim(id(1), T0), reasonIs("write-failed"));
    failCreate = false;
    assert.equal(a.has(id(1)), false);
    failWrite = true;
    assert.equal(a.claim(id(2), T0), true, "claimed by the create");
    failWrite = false;
    assert.ok(markerNames(s.dir).some((n) => readFileSync(path.join(s.dir, n), "utf8") === ""), "an empty marker");
    assert.equal(open(s.dir, c).claim(id(2), T0), false, "an empty marker is a claim, also after a restart");
    // ... and it expires by its file time, so it cannot pin a slot for ever
    c.t = Date.now() + DEDUPE_RETENTION_MS + 60_000;
    const b = open(s.dir, c, { pruneIntervalMs: 0 });
    b.claim(id(3), c.t);
    b.claim(id(4), c.t);
    assert.equal(b.has(id(2)), false, "expired 24 hours after it was made");
    const r = sandbox();
    try {
      chmodSync(r.parent, 0o500);
      assert.throws(() => open(r.dir, c), reasonIs("unwritable"), "a new store in a read-only parent");
      chmodSync(r.parent, 0o700);
      open(r.dir, c);
      chmodSync(r.dir, 0o500);
      assert.doesNotThrow(() => open(r.dir, c), "a store of ours missing only the owner's bits gets them back");
      assert.equal(lstatSync(r.dir).mode & 0o777, 0o700);
      const full = { openSync: (p, f, m) => { if (path.basename(p).startsWith(".tmp.")) throw Object.assign(new Error("ENOSPC"), { code: "ENOSPC" }); return openReal(p, f, m); } };
      assert.throws(() => open(r.dir, c, { fs: full }), reasonIs("unwritable"), "an existing store whose probe write fails (a full disk)");
    } finally {
      r.cleanup();
    }
  } finally {
    s.cleanup();
  }
});

test("DD-7 two stores on one directory see each other's claims at once, and exactly one of them wins a race for the same id", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c);
    const b = open(s.dir, c);
    assert.equal(a.claim(id(1), T0), true);
    assert.equal(b.claim(id(1), T0), false, "b sees a's claim");
    assert.equal(b.claim(id(2), T0), true);
    assert.equal(a.claim(id(2), T0), false, "a sees b's claim");
    // a race: the loser's lookup finds nothing, then a creates first; the loser's exclusive create fails
    // Armed only after the open, and only for a marker create, so the other claim lands in
    // the gap between the loser's lookup and its create.
    let armed = false;
    let raced = false;
    const racing = open(s.dir, c, {
      fs: {
        openSync: (p, f, m) => {
          if (armed && !raced && path.basename(p).length === 32 && (f & fsConstants.O_CREAT) !== 0) {
            raced = true;
            assert.equal(a.claim(id(3), T0), true, "a wins");
          }
          return openReal(p, f, m);
        },
      },
    });
    armed = true;
    assert.equal(racing.claim(id(3), T0), false, "the loser is told it is a duplicate");
    assert.equal(raced, true, "the race happened");
    assert.equal(open(s.dir, c).size(), 3);
  } finally {
    s.cleanup();
  }
});

test("DD-8 dedupeDirFor names the store directory next to the credentials file's real directory; a relative path or a missing directory is refused", () => {
  const s = sandbox();
  try {
    assert.equal(dedupeDirFor(path.join(s.parent, "cloud-api.json")), path.join(realpathSync.native(s.parent), DEDUPE_DIR_NAME));
    assert.throws(() => dedupeDirFor("cloud-api.json"), reasonIs("not-absolute"));
    assert.throws(() => dedupeDirFor(path.join(s.parent, "nope", "cloud-api.json")), reasonIs("unsafe-directory"));
  } finally {
    s.cleanup();
  }
});

// ---- the webhook and transport with the store ---------------------------------------------

const CONFIG = Object.freeze({
  phoneNumberId: "1000000000040",
  graphApiVersion: "v99.9",
  accessToken: "TEST-ACCESS-TOKEN-not-a-real-token-0000000040",
  appSecret: "testappsecretnotreal000000000040",
  verifyToken: "test-verify-token-not-real-040",
  webhookPath: "/idx-whatsapp/cloud-api/webhook",
});
const WA = "15555550140";

/** A signed POST carrying text messages (each `[messageId, metaSeconds]`) from WA. */
function post(messages) {
  const payload = {
    object: "whatsapp_business_account",
    entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: {
      messaging_product: "whatsapp",
      metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: CONFIG.phoneNumberId },
      contacts: [{ profile: { name: "Test Buyer" }, wa_id: WA }],
      messages: messages.map(([mid, sec]) => ({ from: WA, id: mid, timestamp: String(sec), type: "text", text: { body: "any homes?" } })),
    } }] }],
  };
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  const sig = `sha256=${createHmac("sha256", CONFIG.appSecret).update(body).digest("hex")}`;
  return { method: "POST", url: CONFIG.webhookPath, headers: { "x-hub-signature-256": sig }, body };
}

test("DD-9 webhook with the store: a duplicate after a restart starts no turn, a new id does; a store that cannot claim answers 503 (`webhook-deferred`, never `webhook-accepted`) with nothing started at or after the failing message, and Meta's retry starts each once; a sender the channel would not admit never touches the store and is still deduped in memory", () => {
  const s = sandbox();
  try {
    const c = clock();
    const sec = Math.floor(T0 / 1000) - 10;
    const warns = [];
    const infos = [];
    const log = { warn: (m) => warns.push(m), info: (m) => infos.push(m) };
    const seen1 = [];
    const w1 = createCloudApiWebhook({ config: CONFIG, now: c.now, onInbound: (m) => seen1.push(m.messageId), dedupeStore: open(s.dir, c), log });
    assert.equal(w1.handle(post([[id(1), sec]])).status, 200);
    assert.equal(w1.handle(post([[id(1), sec]])).status, 200, "an in-process duplicate");
    assert.deepEqual(seen1, [id(1)]);
    const seen2 = [];
    const w2 = createCloudApiWebhook({ config: CONFIG, now: c.now, onInbound: (m) => seen2.push(m.messageId), dedupeStore: open(s.dir, c), log });
    assert.equal(w2.handle(post([[id(1), sec]])).status, 200);
    assert.deepEqual(seen2, [], "the duplicate after the restart starts nothing");
    assert.equal(w2.handle(post([[id(2), sec]])).status, 200);
    assert.deepEqual(seen2, [id(2)]);
    // a store that fails to claim
    let broken = true;
    const store = open(s.dir, c);
    const flaky = { claim: (m, t) => { if (broken && m === id(4)) throw new DedupeStoreError("write-failed"); return store.claim(m, t); } };
    const seen3 = [];
    const w3 = createCloudApiWebhook({ config: CONFIG, now: c.now, onInbound: (m) => seen3.push(m.messageId), dedupeStore: flaky, log });
    infos.length = 0;
    const r = w3.handle(post([[id(3), sec], [id(4), sec], [id(5), sec]]));
    assert.equal(r.status, 503);
    assert.equal(r.headers["retry-after"], "30");
    assert.deepEqual(seen3, [id(3)], "nothing at or after the failing message started");
    assert.deepEqual(infos.map((m) => m.event), ["webhook-deferred"], "a refused POST is not logged accepted");
    assert.ok(warns.some((m) => m.event === "dedupe-store-failed" && m.reason === "write-failed"));
    assert.ok(warns.every((m) => !JSON.stringify(m).includes("wamid")), "no id in a warning");
    broken = false;
    assert.equal(w3.handle(post([[id(3), sec], [id(4), sec], [id(5), sec]])).status, 200, "Meta's retry of the whole POST");
    assert.deepEqual(seen3, [id(3), id(4), id(5)], "each message started exactly once");
    const stale = Math.floor((T0 - MAX_INBOUND_AGE_MS - 1000) / 1000);
    assert.equal(w3.handle(post([[id(6), stale]])).status, 200);
    assert.equal(store.has(id(6)), false, "a stale message is never claimed");
    // admission: a stranger fills nothing, blocks nobody, and is still deduped in memory
    const small = sandbox();
    try {
      const st = open(small.dir, c, { maxEntries: 2 });
      const got = [];
      const w4 = createCloudApiWebhook({ config: CONFIG, now: c.now, onInbound: (m) => got.push(m.messageId), dedupeStore: st, log, acceptsSender: (peer) => peer === "+15555550199" });
      for (let n = 10; n < 30; n += 1) assert.equal(w4.handle(post([[id(n), sec]])).status, 200, "the stranger's flood");
      assert.equal(st.size(), 0, "no stranger message claimed");
      assert.equal(got.length, 20, "handed to the channel, which drops them");
      w4.handle(post([[id(10), sec]]));
      assert.equal(got.length, 20, "a stranger's duplicate is dropped in memory");
    } finally {
      small.cleanup();
    }
    assert.throws(() => createCloudApiWebhook({ config: CONFIG, onInbound: () => {}, dedupeStore: { has: () => false } }), /bad dedupe store/);
  } finally {
    s.cleanup();
  }
});

test("DD-10 transport with the store (webhookOptions.dedupeStore): after a restart the duplicate makes zero Graph API requests and reaches no sink; a new id is delivered and replied to once", async () => {
  const s = sandbox();
  try {
    const c = clock(Date.now());
    const calls = [];
    const fetch = async (url) => {
      calls.push(url);
      return new Response(JSON.stringify({ messages: [{ id: `wamid.SENT-${calls.length}` }] }), { status: 200 });
    };
    const sec = Math.floor(c.t / 1000) - 5;
    async function life(messages) {
      const t = createCloudApiTransport({ config: CONFIG, fetch, now: c.now, webhookOptions: { dedupeStore: open(s.dir, c) } });
      const ac = new AbortController();
      const got = [];
      const run = t.start({ accountId: "default", signal: ac.signal, acceptsSender: () => true, onInbound: async (m) => { got.push(m.messageId); await t.sendText({ accountId: "default", to: m.peerId, text: "Hello!" }); } });
      for (const m of messages) assert.equal(t.webhook.handle(post([m])).status, 200);
      await new Promise((r) => setTimeout(r, 20));
      ac.abort();
      await run;
      return got;
    }
    assert.deepEqual(await life([[id(1), sec]]), [id(1)]);
    assert.equal(calls.length, 1);
    assert.deepEqual(await life([[id(1), sec], [id(2), sec]]), [id(2)], "restart: the duplicate is dropped, the new id delivered");
    assert.equal(calls.length, 2, "exactly one more Graph API request");
  } finally {
    s.cleanup();
  }
});

test("DD-11 a leftover temporary file is ignored (and removed once it is a minute old); a marker that is a symlink or a directory is refused at claim (`unsafe-marker`)", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c);
    writeFileSync(path.join(s.dir, ".tmp.4242.0123456789ab"), "x", { mode: 0o600 });
    const b = open(s.dir, c);
    assert.equal(b.claim(id(1), T0), true);
    const old = (Date.now() - 120_000) / 1000;
    utimesSync(path.join(s.dir, ".tmp.4242.0123456789ab"), old, old);
    open(s.dir, c);
    assert.ok(!readdirSync(s.dir).includes(".tmp.4242.0123456789ab"), "its own stale temporary file removed at open");
    symlinkSync(path.join(s.parent, "elsewhere"), path.join(s.dir, keyOf(id(2))));
    assert.throws(() => a.claim(id(2), T0), reasonIs("unsafe-marker"));
    mkdirSync(path.join(s.dir, keyOf(id(3))));
    assert.throws(() => a.claim(id(3), T0), reasonIs("unsafe-marker"));
  } finally {
    s.cleanup();
  }
});

test("DD-12 real processes racing on one store: eight child processes claim the same synthetic id at once and exactly one wins; each also claims its own id, and all of them are on disk after", async () => {
  const s = sandbox();
  try {
    open(s.dir, clock(Date.now()));
    const mod = pathToFileURL(path.join(HERE, "cloud-api-dedupe.mjs")).href;
    const child = (n) =>
      new Promise((resolve, reject) => {
        execFile(process.execPath, ["--input-type=module", "-e", `
          const { openDedupeStore } = await import(${JSON.stringify(mod)});
          const st = openDedupeStore({ dir: ${JSON.stringify(s.dir)}, keyId: ${JSON.stringify(KEY_ID)}, hasExtendedAcl: () => false });
          const shared = st.claim("wamid.TEST-SHARED", Date.now());
          const own = st.claim("wamid.TEST-OWN-${n}", Date.now());
          process.stdout.write(JSON.stringify({ shared, own }));
        `], { timeout: 30_000 }, (err, out) => (err ? reject(err) : resolve(JSON.parse(out))));
      });
    const results = await Promise.all(Array.from({ length: 8 }, (_, n) => child(n)));
    assert.equal(results.filter((r) => r.shared).length, 1, "exactly one winner");
    assert.ok(results.every((r) => r.own), "every process claims its own id");
    const st = open(s.dir, clock(Date.now()));
    assert.equal(st.size(), 9);
    for (let n = 0; n < 8; n += 1) assert.equal(st.has(`wamid.TEST-OWN-${n}`), true);
  } finally {
    s.cleanup();
  }
});

test("DD-13 rounds 3 and 5: Finder's .DS_Store never blocks a claim or an open; a store directory removed and made again under a running process still names markers alike (one key per number, so no two processes can disagree); a short stamp is never read as an ancient time; the directory gets mode 700 under a restrictive umask and an unusable non-empty one is refused (`permissions-too-closed`); a FIFO named like a marker cannot hang anything", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c);
    writeFileSync(path.join(s.dir, ".DS_Store"), "x", { mode: 0o600 });
    assert.equal(a.claim(id(1), T0), true, "a claim with .DS_Store present");
    assert.doesNotThrow(() => open(s.dir, c), "an open with .DS_Store present");
    rmSync(s.dir, { recursive: true, force: true });
    const b = open(s.dir, c, { pruneIntervalMs: 0 });
    assert.equal(b.claim(id(2), T0), true);
    assert.equal(a.claim(id(2), T0), false, "the old process sees the new process's claim");
    writeFileSync(path.join(s.dir, keyOf(id(4))), "17", { mode: 0o600 }); // a torn stamp
    b.claim(id(5), T0);
    assert.equal(b.has(id(4)), true, "a torn stamp is not taken for the year 1970");
    execFileSync("/usr/bin/mkfifo", [path.join(s.dir, keyOf(id(6)))], { stdio: "ignore" });
    assert.throws(() => b.claim(id(6), T0), reasonIs("unsafe-marker"));
    assert.equal(b.claim(id(7), T0), true, "a prune past the FIFO returns");
  } finally {
    s.cleanup();
  }
  const u = sandbox();
  try {
    const old = process.umask(0o277);
    try {
      open(u.dir, clock());
    } finally {
      process.umask(old);
    }
    assert.equal(lstatSync(u.dir).mode & 0o777, 0o700);
    open(u.dir, clock()).claim(id(1), T0);
    chmodSync(u.dir, 0o500);
    assert.doesNotThrow(() => open(u.dir, clock()), "a directory of ours missing only the owner's bits gets them back");
    assert.equal(lstatSync(u.dir).mode & 0o777, 0o700);
    chmodSync(u.dir, 0o750);
    assert.throws(() => open(u.dir, clock()), reasonIs("permissions-too-open"), "group bits are never narrowed for the owner, only refused");
  } finally {
    u.cleanup();
  }
});

test("DD-15 round 5: while our clock is shown to be behind (the newest stored Meta stamp is more than the skew margin ahead of it), claims refuse (`clock-behind`) so a retry of a message evicted earlier cannot start a second turn; once the clock catches up, claims work", () => {
  const s = sandbox();
  try {
    const c = clock();
    const a = open(s.dir, c, { maxEntries: 3, pruneIntervalMs: 0 });
    a.claim(id(1), T0 - 40 * 60_000);
    a.claim(id(2), T0 - 1000);
    a.claim(id(3), T0);
    assert.equal(a.claim(id(4), T0 + 1000), true, "full: the 40-minute-old marker is evicted on Meta's evidence");
    assert.equal(a.has(id(1)), false);
    c.t = T0 - 25 * 60_000; // the clock steps back 25 minutes
    const b = open(s.dir, c, { maxEntries: 3 });
    assert.throws(() => b.claim(id(1), T0 - 40 * 60_000), reasonIs("clock-behind"), "Meta's retry of the evicted message is refused, not a second turn");
    c.t = T0 + 2000;
    assert.equal(open(s.dir, c).claim(id(5), T0 + 2000), true, "claims work again once the clock catches up");
  } finally {
    s.cleanup();
  }
});

test("DD-14 round 4: an empty store directory left without owner bits by a crash is repaired; overlapping processes that overshoot the cap do not wedge the next open, and claims answer full until markers leave the window", () => {
  const c = clock();
  const u = sandbox();
  try {
    mkdirSync(u.dir, { mode: 0o700 });
    chmodSync(u.dir, 0o500);
    assert.doesNotThrow(() => open(u.dir, c), "an empty 500 directory of ours is repaired");
    assert.equal(lstatSync(u.dir).mode & 0o777, 0o700);
  } finally {
    u.cleanup();
  }
  const v = sandbox();
  try {
    const a = open(v.dir, c, { maxEntries: 3 });
    const b = open(v.dir, c, { maxEntries: 3 });
    for (let n = 0; n < 3; n += 1) a.claim(id(100 + n), T0);
    for (let n = 0; n < 3; n += 1) b.claim(id(200 + n), T0); // b counted only its own
    assert.ok(open(v.dir, c).size() >= 5, "past the cap");
    assert.doesNotThrow(() => open(v.dir, c, { maxEntries: 3 }), "the next open is not wedged");
    assert.throws(() => open(v.dir, c, { maxEntries: 3 }).claim(id(300), T0), reasonIs("full"), "claims answer full until markers leave the window");
  } finally {
    v.cleanup();
  }
});
