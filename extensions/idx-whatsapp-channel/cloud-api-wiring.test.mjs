// WO-038 wiring pieces (owner decisions 2026-11-08), offline: the owner-only credentials
// file reader and the separate loopback webhook listener. Every credentials file here is
// synthetic, written at test time into a fresh OS temp directory and removed after; the
// only sockets are on 127.0.0.1 with an ephemeral port. No network, no real credential.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { chmodSync, fstatSync, linkSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { request } from "node:http";
import { connect } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { createCloudApiTransport, readCloudApiConfig } from "./cloud-api-transport.mjs";
import {
  CREDENTIALS_FILE_KEYS,
  CREDENTIALS_FILE_MAX_BYTES,
  LOOPBACK_HOSTS,
  createWebhookListener,
  readOwnerCredentialsFile,
} from "./cloud-api-wiring.mjs";

// Synthetic values of plausible shape. None is a real credential, id or number.
const CONFIG = Object.freeze({
  phoneNumberId: "1000000000001",
  graphApiVersion: "v99.9",
  accessToken: "TEST-ACCESS-TOKEN-not-a-real-token-0000000000",
  appSecret: "testappsecretnotreal000000000000",
  verifyToken: "test-verify-token-not-real",
  webhookPath: "/idx-whatsapp/cloud-api/webhook",
});
const PATH = CONFIG.webhookPath;
const WA_ID = "15550000001";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REASON_RE = /^idx-whatsapp-channel: credentials file: [a-z-]+$/;

/** A fresh private temp tree: `base/` (0700) with a fake home, a fake repo and a secrets dir. */
function sandbox() {
  const base = mkdtempSync(path.join(tmpdir(), "idx-wa-cred-"));
  chmodSync(base, 0o700);
  const home = path.join(base, "home");
  const repo = path.join(base, "repo");
  const secrets = path.join(base, "secrets");
  for (const d of [home, path.join(home, ".openclaw"), repo, secrets]) {
    mkdirSync(d);
    chmodSync(d, 0o700);
  }
  const write = (dir, name, content, mode = 0o600) => {
    const p = path.join(dir, name);
    writeFileSync(p, content);
    chmodSync(p, mode);
    return p;
  };
  return { base, home, repo, secrets, write, deps: { home, repoRoot: repo }, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

/**
 * What an error shows beyond the code locations: its message, its own properties and the
 * stack with the `at ...` frame lines removed. The frames name this test file and the
 * module by their absolute paths, which depend on where the checkout lives, so they are
 * never matched against (a checkout under a "scratchpad" or "secrets" folder must not make
 * the leak check fail).
 * @param {any} err
 */
function exposedBy(err) {
  const stackHead = String(err?.stack ?? "").split("\n").filter((l) => !/^\s+at /.test(l)).join("\n");
  return `${err?.message} ${stackHead} ${JSON.stringify(err)}`;
}

/** The refusal reason, after checking the error carries the fixed reason and nothing else.
 *  `leaks` are specific markers (the sandbox's own mkdtemp path, a padding value). */
function reasonOf(fn, leaks = []) {
  try {
    fn();
  } catch (err) {
    assert.match(err.message, REASON_RE);
    assert.equal(err.cause, undefined);
    const exposed = exposedBy(err);
    for (const s of [...leaks, CONFIG.accessToken, CONFIG.appSecret, CONFIG.verifyToken, CONFIG.phoneNumberId]) {
      assert.ok(!exposed.includes(s), `error exposes ${s}`);
    }
    return err.reason;
  }
  return "accepted";
}

/** Whether `chmod +a` works here (macOS); elsewhere the ACL cases use the injected look. */
function aclSupported() {
  return process.platform === "darwin";
}

// ---- the credentials file -------------------------------------------------------------

test("CW-1 credentials file: a good owner-only file outside the repo and ~/.openclaw is read once into a frozen config the transport accepts", () => {
  const s = sandbox();
  try {
    const file = s.write(s.secrets, "cloud-api.json", JSON.stringify(CONFIG, null, 2));
    let opens = 0;
    let reads = 0;
    const counting = {
      openSync: (...a) => { opens += 1; return openSync(...a); },
      readSync: (...a) => { reads += 1; return readSync(...a); },
    };
    const cfg = readOwnerCredentialsFile(file, { ...s.deps, fs: counting });
    assert.equal(opens, 1, "opened once");
    assert.ok(reads >= 1 && reads <= 3);
    assert.deepEqual({ ...cfg }, { ...CONFIG });
    assert.ok(Object.isFrozen(cfg));
    assert.deepEqual(Object.keys(cfg).sort(), [...CREDENTIALS_FILE_KEYS]);
    assert.ok(readCloudApiConfig(cfg));
    assert.equal(createCloudApiTransport({ config: cfg, fetch: async () => new Response("{}") }).isConfigured(), true);
    // read once: a later change to the file does not reach the object already returned
    writeFileSync(file, JSON.stringify({ ...CONFIG, verifyToken: "another-verify-token-000" }));
    assert.equal(cfg.verifyToken, CONFIG.verifyToken);
    // mode 0400 is owner-only too
    chmodSync(file, 0o400);
    assert.equal(reasonOf(() => readOwnerCredentialsFile(file, s.deps), [s.base]), "accepted");
  } finally {
    s.cleanup();
  }
});

test("CW-2 credentials file refusals, each a fixed reason with no path or value: relative, missing, directory, inside the repo (default root and injected), inside ~/.openclaw, symlink, symlinked parent into the repo, group or world bits, wrong owner, unsafe directory, oversize, bad JSON, wrong keys, implausible values", () => {
  const s = sandbox();
  try {
    const body = JSON.stringify(CONFIG);
    const ok = s.write(s.secrets, "ok.json", body);
    const cases = [];
    const want = (name, reason, fn) => cases.push([name, reason, fn]);
    const read = (p, deps = {}) => () => readOwnerCredentialsFile(p, { ...s.deps, ...deps });

    want("relative path", "not-absolute", read("secrets/ok.json"));
    want("dot-relative path", "not-absolute", read("./ok.json"));
    want("empty path", "not-absolute", read(""));
    want("non-string path", "not-absolute", read(/** @type {any} */ (42)));
    want("missing file", "missing", read(path.join(s.secrets, "absent.json")));
    want("a directory", "not-regular-file", read(s.secrets));
    // the real repo root (default): this package's own manifest is inside it; refused before any read
    want("inside the repo (default root)", "inside-repo", () => readOwnerCredentialsFile(path.join(HERE, "package.json"), { home: s.home }));
    want("inside the repo (injected root)", "inside-repo", read(s.write(s.repo, "creds.json", body)));
    want("inside ~/.openclaw (injected home)", "inside-openclaw", read(s.write(path.join(s.home, ".openclaw"), "creds.json", body)));
    const link = path.join(s.secrets, "link.json");
    symlinkSync(ok, link);
    want("a symlink to a good file", "symlink", read(link));
    const linkedDir = path.join(s.base, "linked-repo");
    symlinkSync(s.repo, linkedDir);
    s.write(s.repo, "via-link.json", body);
    want("a symlinked parent that lands in the repo", "inside-repo", read(path.join(linkedDir, "via-link.json")));
    for (const mode of [0o640, 0o604, 0o620, 0o602, 0o610, 0o601, 0o644, 0o666]) {
      want(`mode ${mode.toString(8)}`, "permissions-too-open", read(s.write(s.secrets, `mode-${mode.toString(8)}.json`, body, mode)));
    }
    want("wrong owner (injected uid)", "wrong-owner", read(ok, { uid: process.getuid() + 1 }));
    const openDir = path.join(s.base, "open-dir");
    mkdirSync(openDir);
    const inOpenDir = s.write(openDir, "creds.json", body);
    chmodSync(openDir, 0o777);
    want("a group- and world-writable directory", "unsafe-directory", read(inOpenDir));
    want("oversize (default 16 KiB)", "too-large", read(s.write(s.secrets, "big.json", JSON.stringify({ ...CONFIG, padQ7marker: "x".repeat(CREDENTIALS_FILE_MAX_BYTES) }))));
    want("oversize (injected limit)", "too-large", read(ok, { maxBytes: 64 }));
    // a hard link: both names reach the same inode, so neither is accepted, wherever the other lives
    const linkedRepoFile = s.write(s.repo, "linked.json", body);
    const hardOutside = path.join(s.secrets, "hard-outside.json");
    linkSync(linkedRepoFile, hardOutside);
    want("a hard link (outside name) to a file inside the repo", "hard-linked", read(hardOutside));
    const twin = s.write(s.secrets, "twin-a.json", body);
    linkSync(twin, path.join(s.secrets, "twin-b.json"));
    want("a hard-linked file, both names outside the repo", "hard-linked", read(twin));
    want("a hard link found only on the open descriptor", "hard-linked", read(ok, { fs: { fstatSync: (fd) => { const st = fstatSync(fd); return Object.assign(Object.create(Object.getPrototypeOf(st)), st, { nlink: 2 }); } } }));
    // extended ACLs: an injected look (every platform), then a real ACL on macOS
    want("an ACL on the file or directory (injected look)", "acl-present", read(ok, { hasExtendedAcl: () => true }));
    want("an ACL on the directory only (injected look)", "acl-present", read(ok, { hasExtendedAcl: (p) => p !== ok }));
    want("an ACL look that fails (injected)", "acl-unknown", read(ok, { hasExtendedAcl: () => { throw new Error(`ls failed for ${ok}`); } }));
    want("an ACL look with a non-boolean answer (injected)", "acl-present", read(ok, { hasExtendedAcl: () => /** @type {any} */ ("maybe") }));
    if (aclSupported()) {
      const aclFile = s.write(s.secrets, "acl-file.json", body);
      execFileSync("/bin/chmod", ["+a", "everyone allow read", aclFile]);
      want("mode 600 with an ACL granting everyone read (real)", "acl-present", read(aclFile));
      const aclDir = path.join(s.base, "acl-dir");
      mkdirSync(aclDir);
      chmodSync(aclDir, 0o700);
      const inAclDir = s.write(aclDir, "creds.json", body);
      execFileSync("/bin/chmod", ["+a", "everyone allow add_file,delete_child", aclDir]);
      want("a mode 700 directory with an ACL letting everyone add and delete files (real)", "acl-present", read(inAclDir));
    }
    want("bad JSON", "not-json", read(s.write(s.secrets, "bad.json", `{"accessToken": "${CONFIG.accessToken}",`)));
    want("invalid UTF-8", "not-json", read(s.write(s.secrets, "bytes.json", Buffer.from([0x7b, 0xff, 0x7d]))));
    want("empty file", "not-json", read(s.write(s.secrets, "empty.json", "")));
    want("a JSON array", "wrong-keys", read(s.write(s.secrets, "array.json", JSON.stringify([CONFIG]))));
    want("a JSON string", "wrong-keys", read(s.write(s.secrets, "string.json", JSON.stringify("x"))));
    want("an extra key", "wrong-keys", read(s.write(s.secrets, "extra.json", JSON.stringify({ ...CONFIG, accountId: "default" }))));
    want("a __proto__ key", "wrong-keys", read(s.write(s.secrets, "proto.json", body.replace(/^\{/, '{"__proto__":{"x":1},'))));
    for (const k of CREDENTIALS_FILE_KEYS) {
      const missing = { ...CONFIG };
      delete missing[k];
      want(`missing ${k}`, "wrong-keys", read(s.write(s.secrets, `missing-${k}.json`, JSON.stringify(missing))));
      want(`empty ${k}`, "implausible-value", read(s.write(s.secrets, `empty-${k}.json`, JSON.stringify({ ...CONFIG, [k]: "" }))));
      want(`non-string ${k}`, "implausible-value", read(s.write(s.secrets, `num-${k}.json`, JSON.stringify({ ...CONFIG, [k]: 12345 }))));
    }
    want("implausible phone-number id", "implausible-value", read(s.write(s.secrets, "phone.json", JSON.stringify({ ...CONFIG, phoneNumberId: "<PHONE_NUMBER_ID>" }))));
    want("a reused secret", "implausible-value", read(s.write(s.secrets, "reuse.json", JSON.stringify({ ...CONFIG, verifyToken: CONFIG.appSecret }))));
    want("an unsafe webhook path", "implausible-value", read(s.write(s.secrets, "path.json", JSON.stringify({ ...CONFIG, webhookPath: "/a/../b" }))));

    for (const [name, reason, fn] of cases) assert.equal(reasonOf(fn, [s.base, "padQ7marker", "xxxxxxxx", "ls failed"]), reason, name);
    // the good file is still accepted beside all of these (on macOS through the real ACL look)
    assert.equal(reasonOf(read(ok), [s.base]), "accepted");
  } finally {
    s.cleanup();
  }
});

test("CW-3 credentials file: a swap between the first look and the open is caught on the open descriptor", () => {
  const s = sandbox();
  try {
    const file = s.write(s.secrets, "ok.json", JSON.stringify(CONFIG));
    const other = s.write(s.secrets, "other.json", JSON.stringify(CONFIG));
    // the open lands on another inode than the one lstat saw
    const swapped = { openSync: (_p, flags) => openSync(other, flags) };
    assert.equal(reasonOf(() => readOwnerCredentialsFile(file, { ...s.deps, fs: swapped }), [s.base]), "changed");
  } finally {
    s.cleanup();
  }
});

test("CW-4 source: the wiring module imports Node built-ins and the transport module only, reads no environment, writes no file, calls no fetch, and is staged (not imported by the entry, not in files)", () => {
  const src = readFileSync(new URL("./cloud-api-wiring.mjs", import.meta.url), "utf8");
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const imports = [...code.matchAll(/^\s*import\b[^;]*?\bfrom\s+"([^"]+)"/gms)].map((m) => m[1]);
  assert.deepEqual(imports, ["node:buffer", "node:child_process", "node:fs", "node:http", "node:os", "node:path", "node:url", "./cloud-api-transport.mjs"]);
  // the one child process is the macOS ACL look: execFileSync of the fixed /bin/ls path with
  // a fixed flag, no shell and a fixed environment
  assert.match(code, /import \{ execFileSync \} from "node:child_process";/);
  assert.equal((code.match(/\bexecFileSync\(/g) ?? []).length, 1);
  assert.match(code, /execFileSync\(LS_BIN, \["-led", p\], \{/);
  assert.match(code, /const LS_BIN = "\/bin\/ls";/);
  assert.match(code, /env: \{ LC_ALL: "C" \}/);
  assert.match(code, /shell: false/);
  for (const banned of [/\bspawn\w*\(/, /\bexec\(/, /\bexecSync\(/, /\bfork\(/, /\bexecFile\(/]) assert.ok(!banned.test(code), String(banned));
  for (const banned of [/process\.env/, /writeFile/, /appendFile/, /\bfetch\b/, /\bhttps\b/, /\brequest\s*\(/, /\bimport\s*\(/, /\brequire\s*\(/, /\bexport\s+default\b/, /0\.0\.0\.0/, /console\./]) {
    assert.ok(!banned.test(code), String(banned));
  }
  assert.ok(!/https?:\/\//.test(src), "no URL literal");
  // the server carries header and request timeouts, a header size cap and a connection cap
  for (const opt of ["maxHeaderSize: LISTENER_MAX_HEADER_BYTES", "headersTimeout: LISTENER_HEADERS_TIMEOUT_MS", "requestTimeout: LISTENER_REQUEST_TIMEOUT_MS", "keepAliveTimeout: LISTENER_KEEP_ALIVE_TIMEOUT_MS", "connectionsCheckingInterval: LISTENER_TIMEOUT_CHECK_MS", "server.maxConnections = LISTENER_MAX_CONNECTIONS"]) {
    assert.ok(code.includes(opt), opt);
  }
  assert.equal((code.match(/\.listen\(/g) ?? []).length, 1);
  assert.match(code, /server\.listen\(\{ host, port, exclusive: true \}\)/);
  const index = readFileSync(new URL("./index.mjs", import.meta.url), "utf8");
  assert.ok(!index.includes("cloud-api-wiring"));
  assert.ok(!index.includes("cloud-api-transport"));
  const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
  assert.ok(!pkg.files.includes("cloud-api-wiring.mjs"), "staged, not shipped");
});

// ---- the loopback listener -------------------------------------------------------------

/** One request to the loopback listener; resolves `{ status, headers, body }`. */
function call(port, { method = "GET", url = PATH, headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, method, path: url, headers, agent: false }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString("utf8") }));
    });
    req.on("error", reject);
    if (body !== undefined) req.end(body);
    else req.end();
  });
}

/** Whether a TCP connect to the port is refused (nothing listening). */
function refused(port) {
  return new Promise((resolve) => {
    const sock = connect({ host: "127.0.0.1", port });
    sock.once("connect", () => { sock.destroy(); resolve(false); });
    sock.once("error", () => resolve(true));
  });
}

/** Polls until a connect to the port is refused, without calling stop(); false if it never is. */
async function releasedWithin(port, tries = 100) {
  for (let i = 0; i < tries; i += 1) {
    if (await refused(port)) return true;
    await new Promise((r) => setTimeout(r, 10));
  }
  return false;
}

/** A port that was free a moment ago (bound on 0 by a throwaway listener, then released). */
async function freePort() {
  const probe = createWebhookListener({ handler: async () => true, host: "127.0.0.1", port: 0, path: PATH });
  const { port } = await probe.start();
  await probe.stop();
  return port;
}

/** A Cloud API transport on a fake fetch, started, with its route handler behind a listener. */
async function served() {
  const got = [];
  const lines = [];
  const log = { info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
  const t = createCloudApiTransport({ config: CONFIG, fetch: async () => { throw new Error("no send expected"); } });
  const ac = new AbortController();
  const running = t.start({ accountId: "default", signal: ac.signal, onInbound: async (m) => { got.push(m); } });
  const listener = createWebhookListener({ handler: t.webhook.routeHandler, host: "127.0.0.1", port: 0, path: t.webhook.path, log });
  const { port } = await listener.start({ signal: ac.signal });
  return { t, got, lines, ac, running, listener, port };
}

function signedPost() {
  const payload = {
    object: "whatsapp_business_account",
    entry: [{ id: "WABA-TEST", changes: [{ field: "messages", value: {
      messaging_product: "whatsapp",
      metadata: { display_phone_number: "<DISPLAY_NUMBER>", phone_number_id: CONFIG.phoneNumberId },
      contacts: [{ profile: { name: "Test Buyer" }, wa_id: WA_ID }],
      messages: [{ from: WA_ID, id: "wamid.LISTEN-1", timestamp: String(Math.floor(Date.now() / 1000)), type: "text", text: { body: "hello from the tunnel" } }],
    } }] }],
  };
  const bytes = Buffer.from(JSON.stringify(payload), "utf8");
  const sig = `sha256=${createHmac("sha256", CONFIG.appSecret).update(bytes).digest("hex")}`;
  return { bytes, sig };
}

test("CW-5 listener: only loopback literals bind; any other host, a bad port, a bad path or no handler is refused at construction", () => {
  const handler = async () => true;
  for (const host of ["0.0.0.0", "::", "localhost", "192.0.2.10", "127.0.0.2", "", " 127.0.0.1", "::ffff:127.0.0.1", undefined, null, 127]) {
    assert.throws(() => createWebhookListener({ handler, host, port: 0, path: PATH }), /host not loopback/, String(host));
  }
  for (const port of [-1, 65_536, 1.5, "8080", undefined, null]) {
    assert.throws(() => createWebhookListener({ handler, host: "127.0.0.1", port, path: PATH }), /bad port/, String(port));
  }
  for (const p of ["", "/", "/a/../b", "/a//b", "/a?x=1", "relative", undefined]) {
    assert.throws(() => createWebhookListener({ handler, host: "127.0.0.1", port: 0, path: p }), /bad path/, String(p));
  }
  assert.throws(() => createWebhookListener({ host: "127.0.0.1", port: 0, path: PATH }), /no handler/);
  assert.deepEqual([...LOOPBACK_HOSTS], ["127.0.0.1", "::1"]);
  for (const host of LOOPBACK_HOSTS) assert.ok(createWebhookListener({ handler, host, port: 0, path: PATH }));
});

test("CW-6 listener: real loopback requests; the webhook path answers GET verification and a signed POST reaches the sink; other paths are 404 and other methods 405, each with connection close and no body; oversized headers are refused", async () => {
  const s = await served();
  try {
    const challenge = await call(s.port, { url: `${PATH}?hub.mode=subscribe&hub.verify_token=${CONFIG.verifyToken}&hub.challenge=4242` });
    assert.equal(challenge.status, 200);
    assert.equal(challenge.body, "4242");
    assert.equal((await call(s.port, { url: `${PATH}?hub.mode=subscribe&hub.verify_token=wrong-token-0000000&hub.challenge=1` })).status, 403);
    const { bytes, sig } = signedPost();
    const accepted = await call(s.port, { method: "POST", headers: { "x-hub-signature-256": sig, "content-type": "application/json", "content-length": String(bytes.length) }, body: bytes });
    assert.equal(accepted.status, 200);
    assert.equal(s.got.length, 1);
    assert.equal(s.got[0].peerId, `+${WA_ID}`);
    assert.equal((await call(s.port, { method: "POST", headers: { "content-length": String(bytes.length) }, body: bytes })).status, 401, "unsigned");
    assert.equal((await call(s.port, { method: "POST", headers: { "x-hub-signature-256": `sha256=${"0".repeat(64)}`, "content-length": String(bytes.length) }, body: bytes })).status, 401, "wrong signature");
    assert.equal(s.got.length, 1);
    for (const url of ["/", "/health", `${PATH}/`, `${PATH}/x`, PATH.slice(0, -1), `${PATH}x`, PATH.toUpperCase(), "/idx-whatsapp", `//${PATH}`, `/%2e%2e${PATH}`]) {
      for (const method of ["GET", "POST"]) {
        const r = await call(s.port, { method, url, headers: { "x-hub-signature-256": sig } });
        assert.equal(r.status, 404, `${method} ${url}`);
        assert.equal(r.body, "");
        assert.equal(r.headers.connection, "close");
      }
    }
    for (const method of ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]) {
      const r = await call(s.port, { method });
      assert.equal(r.status, 405, method);
      assert.equal(r.body, "");
      assert.equal(r.headers.connection, "close");
      assert.equal(r.headers.allow, "GET, POST");
    }
    const big = await call(s.port, { headers: { "x-filler": "x".repeat(10_000) } });
    assert.equal(big.status, 431, "header size cap");
    // logs: fixed events only, never a path, query, token, body or peer
    const all = JSON.stringify(s.lines);
    for (const leak of [PATH, CONFIG.verifyToken, "4242", "hello from the tunnel", WA_ID, "health", "127.0.0.1", String(s.port)]) assert.ok(!all.includes(leak), `log carries ${leak}`);
    for (const l of s.lines.filter((x) => x.component === "idx-whatsapp-channel.cloud-api-listener")) {
      assert.ok(["listener-started", "listener-stopped", "listener-error", "request-refused"].includes(l.event), l.event);
      assert.deepEqual(Object.keys(l).filter((k) => !["component", "event", "reason"].includes(k)), []);
    }
    assert.ok(s.lines.some((l) => l.event === "request-refused" && l.reason === "not-found"));
    assert.ok(s.lines.some((l) => l.event === "request-refused" && l.reason === "method-not-allowed"));
  } finally {
    s.ac.abort();
    await s.listener.stop();
    await s.running;
  }
});

test("CW-7 listener lifecycle: the account signal stops it and releases the port; stop() is idempotent; the same port can be bound again; a port in use fails to start with a fixed message", async () => {
  const s = await served();
  /** @type {Array<{ stop: () => Promise<void> }>} */
  const opened = [s.listener];
  try {
    assert.equal(await refused(s.port), false, "listening");
    s.ac.abort();
    // the abort alone releases the port: no stop() call before the check
    assert.equal(await releasedWithin(s.port), true, "the port is released by the abort alone");
    await s.running;
    await s.listener.stop();
    await s.listener.stop();
    assert.ok(s.lines.some((l) => l.event === "listener-stopped"));
    // the same port binds again, and stop() alone releases it
    const again = createWebhookListener({ handler: async (_req, res) => { res.end(); return true; }, host: "127.0.0.1", port: s.port, path: PATH });
    opened.push(again);
    const r = await again.start();
    assert.equal(r.port, s.port);
    assert.equal(await refused(s.port), false);
    // a second listener on the busy port refuses to start, with no address in the error
    const lines = [];
    const clash = createWebhookListener({ handler: async () => true, host: "127.0.0.1", port: s.port, path: PATH, log: { error: (m) => lines.push(m) } });
    const err = await clash.start().then(() => null, (e) => e);
    assert.match(err.message, /^idx-whatsapp-channel: webhook listener: listen failed$/);
    assert.deepEqual(lines, [{ component: "idx-whatsapp-channel.cloud-api-listener", event: "listener-error", reason: "EADDRINUSE" }]);
    await again.stop();
    assert.equal(await refused(s.port), true);
    // an already-aborted signal never listens; a stale signal cannot stop a later start
    await assert.rejects(again.start({ signal: AbortSignal.abort() }), /aborted/);
    const stale = new AbortController();
    await again.start({ signal: stale.signal });
    await again.stop();
    const fresh = new AbortController();
    await again.start({ signal: fresh.signal });
    stale.abort();
    assert.equal(await refused(s.port), false, "the stale signal did not stop the later start");
    fresh.abort();
    assert.equal(await releasedWithin(s.port), true, "the fresh signal alone releases the port");
    await again.stop();
    assert.equal(await refused(s.port), true);
  } finally {
    s.ac.abort();
    for (const l of opened) await l.stop().catch(() => {});
  }
});

test("CW-8 listener: an abort or a stop() while start() is still binding cancels it (start rejects, the port is released and stays free); a second start() while one is pending is refused; the listener starts again afterwards", { timeout: 10_000 }, async () => {
  const port = await freePort();
  const lines = [];
  const log = { info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
  const listener = createWebhookListener({ handler: async (_req, res) => { res.end(); return true; }, host: "127.0.0.1", port, path: PATH, log });
  // Stopped in the finally, so a regression fails the test instead of leaving a bound
  // port that keeps the run open.
  try {

    // abort in the same tick as start(), before "listening"
    const ac = new AbortController();
    const p1 = listener.start({ signal: ac.signal });
    ac.abort();
    await assert.rejects(p1, /^Error: idx-whatsapp-channel: webhook listener: stopped while starting$/);
    assert.equal(await refused(port), true, "abort before listening: the port is free");
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(await refused(port), true, "and it stays free");
    assert.ok(!lines.some((l) => l.event === "listener-started"), "never served");

    // stop() while start() is pending: stop resolves once the port is free
    const p2 = listener.start({ signal: new AbortController().signal });
    const stopped = listener.stop();
    await assert.rejects(p2, /stopped while starting$/);
    await stopped;
    assert.equal(await refused(port), true, "stop before listening: the port is free");

    // two starts at once: the second is refused, the first serves and its signal stops it
    const live = new AbortController();
    const p3 = listener.start({ signal: live.signal });
    await assert.rejects(listener.start({ signal: new AbortController().signal }), /already started$/);
    assert.equal((await p3).port, port);
    assert.equal(await refused(port), false, "the one start serves");
    live.abort();
    assert.equal(await releasedWithin(port), true, "its own signal still stops it");

    // the listener starts again after all of this
    const after = await listener.start();
    assert.equal(after.port, port);
    await listener.stop();
    assert.equal(await refused(port), true);
    for (const l of lines) assert.ok(["listener-started", "listener-stopped", "listener-error", "request-refused"].includes(l.event), l.event);
  } finally {
    await listener.stop().catch(() => {});
  }
});

test("CW-9 the leak check reads the message, the error's own fields and the stack head, never the stack's file paths", () => {
  const err = new Error("idx-whatsapp-channel: credentials file: missing");
  err.stack = `${err.message}\n    at reasonOf (/Users/x/scratchpad/secrets/idx-wa-cred-1/cloud-api-wiring.test.mjs:1:1)`;
  const shown = exposedBy(err);
  for (const word of ["scratchpad", "secrets", "idx-wa-cred-", "pad"]) assert.ok(!shown.includes(word), word);
  const leaky = Object.assign(new Error("idx-whatsapp-channel: credentials file: missing"), { detail: "padQ7marker" });
  assert.ok(exposedBy(leaky).includes("padQ7marker"), "an own field is still checked");
  const inMessage = new Error(`credentials file: ${CONFIG.appSecret}`);
  assert.ok(exposedBy(inMessage).includes(CONFIG.appSecret), "the message is still checked");
});
