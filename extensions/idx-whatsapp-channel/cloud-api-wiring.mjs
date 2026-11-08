/**
 * Wiring pieces for the Cloud API transport (WO-038), offline and staged: nothing imports
 * this module yet and the entry still ships `unavailableTransport`. Two owner decisions
 * (2026-11-08) live here:
 *
 *   - `readOwnerCredentialsFile`: the config comes from one owner-created JSON file outside
 *     the repo and outside `~/.openclaw`, owned by the gateway's user, mode 600 or tighter,
 *     read once at start. Every refusal is a fixed reason; no error carries the path, a
 *     value or any of the file's text.
 *   - `createWebhookListener`: a separate `node:http` server bound to loopback only, which
 *     answers exactly the configured webhook path (GET and POST) through the existing
 *     route adapter and nothing else. The owner's tunnel forwards that one path to it, so
 *     the gateway port never faces the internet.
 *
 * Node built-ins only. No network beyond the loopback socket it is told to bind.
 */

import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { closeSync, constants as fsConstants, fstatSync, lstatSync, openSync, readSync, realpathSync } from "node:fs";
import { createServer } from "node:http";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { isWebhookPath, readCloudApiConfig } from "./cloud-api-transport.mjs";

/** Largest credentials file read. The six values fit in well under 8 KiB. */
export const CREDENTIALS_FILE_MAX_BYTES = 16_384;

/** The keys the credentials file must hold, exactly: no extra and none missing. */
export const CREDENTIALS_FILE_KEYS = Object.freeze([
  "accessToken",
  "appSecret",
  "graphApiVersion",
  "phoneNumberId",
  "verifyToken",
  "webhookPath",
]);

/** This module's directory and the repo root it sits in (`<repo>/extensions/<name>/`). */
const MODULE_DIR = fileURLToPath(new URL(".", import.meta.url));
const DEFAULT_REPO_ROOT = fileURLToPath(new URL("../../", import.meta.url));

/** The macOS `ls` that lists a path's access control list with `-le`. */
const LS_BIN = "/bin/ls";
/** An ACL entry line in `ls -led` output, e.g. " 0: group:everyone allow read". */
const ACL_LINE_RE = /^\s*\d+: /m;

/**
 * Whether a path carries an extended access control list that POSIX mode bits do not
 * show. On macOS an ACL can grant other users read access to a mode-600 file, or the
 * right to add and delete files in a mode-700 directory, so the owner-only check asks
 * `/bin/ls -led` (fixed argv, fixed environment, no shell) and refuses any ACL entry. On
 * Linux a POSIX ACL with any entry beyond the owner's raises the group bits (its mask),
 * which the mode test already refuses, so no extra look is needed there. Throws when the
 * look itself fails; the caller turns that into a fixed reason.
 * @param {string} p @returns {boolean}
 */
function defaultHasExtendedAcl(p) {
  if (process.platform !== "darwin") return false;
  const out = execFileSync(LS_BIN, ["-led", p], {
    encoding: "utf8",
    env: { LC_ALL: "C" },
    stdio: ["ignore", "pipe", "ignore"],
    timeout: 5_000,
    maxBuffer: 65_536,
    shell: false,
  });
  return ACL_LINE_RE.test(out);
}

/** A refusal with a fixed reason only. */
class CredentialsFileError extends Error {
  /** @param {string} reason */
  constructor(reason) {
    super(`idx-whatsapp-channel: credentials file: ${reason}`);
    this.name = "CredentialsFileError";
    this.reason = reason;
  }
}

/**
 * The canonical form of a directory for the containment test: its real path when it
 * exists, else the resolved path. Never throws.
 * @param {(p: string) => string} realpath @param {string} dir
 */
function canonicalDir(realpath, dir) {
  try {
    return realpath(dir);
  } catch {
    return path.resolve(dir);
  }
}

/** Whether `child` is `parent` or inside it. Compared as given and lowercased, so a
 *  case-insensitive file system cannot slip a path past it (lowercasing only refuses more).
 *  @param {string} parent @param {string} child */
function within(parent, child) {
  for (const [p, c] of [[parent, child], [parent.toLowerCase(), child.toLowerCase()]]) {
    const rel = path.relative(p, c);
    if (rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel))) return true;
  }
  return false;
}

/**
 * Reads the owner's Cloud API credentials file once and returns the config object for
 * `createCloudApiTransport` (frozen: the six keys, each a plausible non-empty string).
 * Refuses, with a `CredentialsFileError` whose message is a fixed reason, unless:
 *   - `filePath` is an absolute path ("not-absolute");
 *   - its real location is outside the repo root, this module's directory
 *     ("inside-repo") and `~/.openclaw` ("inside-openclaw"); real paths are compared, so a
 *     symlinked parent cannot hide either;
 *   - `lstat` finds it ("missing"), and it is a regular file, not a symlink ("symlink",
 *     "not-regular-file"); it is then opened with O_NOFOLLOW and every later check is made
 *     on the open descriptor, so a swap after the first look is caught ("changed");
 *   - it has exactly one link ("hard-linked"), so no other name, inside the repo or
 *     anywhere, reaches the same bytes; checked on the first look and the open descriptor;
 *   - it is owned by the current user ("wrong-owner") and its mode has no group or other
 *     bit ("permissions-too-open"); its directory is owned by the current user and not
 *     group- or world-writable ("unsafe-directory");
 *   - on macOS, neither the file nor its directory carries an extended ACL, which could
 *     grant other users access the mode bits do not show ("acl-present"; "acl-unknown"
 *     when the look fails);
 *   - it is at most `maxBytes` (default 16 KiB, "too-large"), UTF-8 JSON ("not-json"), a
 *     plain object with exactly CREDENTIALS_FILE_KEYS ("wrong-keys"), each a non-empty
 *     string ("implausible-value"), and `readCloudApiConfig` accepts it ("implausible-value").
 * Read errors are "unreadable". The file is never written, and nothing is logged.
 * @param {unknown} filePath
 * @param {{ repoRoot?: string, home?: string, uid?: number, maxBytes?: number,
 *   hasExtendedAcl?: (p: string) => boolean,
 *   fs?: { lstatSync?: Function, realpathSync?: Function, openSync?: Function, fstatSync?: Function,
 *     readSync?: Function, closeSync?: Function } }} [deps]
 * @returns {Readonly<Record<string, string>>}
 */
export function readOwnerCredentialsFile(filePath, deps = {}) {
  const fs = {
    lstatSync,
    realpathSync: realpathSync.native,
    openSync,
    fstatSync,
    readSync,
    closeSync,
    ...(deps.fs ?? {}),
  };
  const uid = deps.uid ?? process.getuid?.();
  const home = deps.home ?? homedir();
  const repoRoot = deps.repoRoot ?? DEFAULT_REPO_ROOT;
  const maxBytes = deps.maxBytes ?? CREDENTIALS_FILE_MAX_BYTES;
  const hasExtendedAcl = deps.hasExtendedAcl ?? defaultHasExtendedAcl;
  if (typeof uid !== "number") throw new CredentialsFileError("no-user-id");

  if (typeof filePath !== "string" || filePath === "" || !path.isAbsolute(filePath)) {
    throw new CredentialsFileError("not-absolute");
  }
  const resolved = path.resolve(filePath);
  let st;
  try {
    st = fs.lstatSync(resolved);
  } catch {
    throw new CredentialsFileError("missing");
  }
  if (st.isSymbolicLink()) throw new CredentialsFileError("symlink");
  if (!st.isFile()) throw new CredentialsFileError("not-regular-file");
  if (st.nlink !== 1) throw new CredentialsFileError("hard-linked");

  // Where the file really is: the directory's real path plus the (non-symlink) name.
  const dir = canonicalDir(fs.realpathSync, path.dirname(resolved));
  const real = path.join(dir, path.basename(resolved));
  for (const root of [repoRoot, MODULE_DIR]) {
    if (within(canonicalDir(fs.realpathSync, root), real)) throw new CredentialsFileError("inside-repo");
  }
  if (within(canonicalDir(fs.realpathSync, path.join(home, ".openclaw")), real)) {
    throw new CredentialsFileError("inside-openclaw");
  }
  // First look from lstat; the open descriptor is checked again below.
  if (st.uid !== uid) throw new CredentialsFileError("wrong-owner");
  if ((st.mode & 0o077) !== 0) throw new CredentialsFileError("permissions-too-open");
  let dirStat;
  try {
    dirStat = fs.lstatSync(dir);
  } catch {
    throw new CredentialsFileError("unsafe-directory");
  }
  if (!dirStat.isDirectory() || dirStat.uid !== uid || (dirStat.mode & 0o022) !== 0) {
    throw new CredentialsFileError("unsafe-directory");
  }
  for (const p of [resolved, dir]) {
    let acl;
    try {
      acl = hasExtendedAcl(p);
    } catch {
      throw new CredentialsFileError("acl-unknown");
    }
    if (acl !== false) throw new CredentialsFileError("acl-present");
  }

  const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0);
  let fd;
  try {
    fd = fs.openSync(resolved, flags);
  } catch {
    throw new CredentialsFileError("unreadable");
  }
  let bytes;
  try {
    const fst = fs.fstatSync(fd);
    if (!fst.isFile() || fst.ino !== st.ino || fst.dev !== st.dev) throw new CredentialsFileError("changed");
    if (fst.nlink !== 1) throw new CredentialsFileError("hard-linked");
    if (fst.uid !== uid) throw new CredentialsFileError("wrong-owner");
    if ((fst.mode & 0o077) !== 0) throw new CredentialsFileError("permissions-too-open");
    if (fst.size > maxBytes) throw new CredentialsFileError("too-large");
    const buf = Buffer.alloc(maxBytes + 1);
    let n = 0;
    try {
      for (;;) {
        const got = fs.readSync(fd, buf, n, buf.length - n, null);
        if (got === 0) break;
        n += got;
        if (n > maxBytes) break;
      }
    } catch {
      throw new CredentialsFileError("unreadable");
    }
    if (n > maxBytes) throw new CredentialsFileError("too-large");
    bytes = buf.subarray(0, n);
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      /* the descriptor is gone either way */
    }
  }

  let parsed;
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new CredentialsFileError("not-json");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed) || Object.getPrototypeOf(parsed) !== Object.prototype) {
    throw new CredentialsFileError("wrong-keys");
  }
  const keys = Object.keys(parsed).sort();
  if (keys.length !== CREDENTIALS_FILE_KEYS.length || keys.some((k, i) => k !== CREDENTIALS_FILE_KEYS[i])) {
    throw new CredentialsFileError("wrong-keys");
  }
  /** @type {Record<string, string>} */
  const out = {};
  for (const k of CREDENTIALS_FILE_KEYS) {
    const v = parsed[k];
    if (typeof v !== "string" || v === "") throw new CredentialsFileError("implausible-value");
    out[k] = v;
  }
  if (readCloudApiConfig(out) === null) throw new CredentialsFileError("implausible-value");
  return Object.freeze(out);
}

/** The only hosts the listener binds: IPv4 and IPv6 loopback, as literals. */
export const LOOPBACK_HOSTS = Object.freeze(["127.0.0.1", "::1"]);
/** Header bytes accepted per request (Node's default is 16 KiB; Meta's are small). */
export const LISTENER_MAX_HEADER_BYTES = 8_192;
/** Time allowed for the request headers to arrive. */
export const LISTENER_HEADERS_TIMEOUT_MS = 5_000;
/** Time allowed for a whole request; above the route adapter's own 10 s body deadline. */
export const LISTENER_REQUEST_TIMEOUT_MS = 15_000;
/** Idle time a kept-alive socket may wait for its next request. */
export const LISTENER_KEEP_ALIVE_TIMEOUT_MS = 5_000;
/** How often Node checks open requests against the two timeouts above. */
export const LISTENER_TIMEOUT_CHECK_MS = 1_000;
/** Open sockets at once. */
export const LISTENER_MAX_CONNECTIONS = 64;

const NO_BODY_HEADERS = Object.freeze({
  connection: "close",
  "content-length": "0",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
});

/**
 * A separate loopback HTTP listener for the Cloud API webhook (owner decision 2026-11-08:
 * not `registerHttpRoute` on the gateway). It serves exactly `path`, GET and POST only,
 * through `handler` (the transport's `webhook.routeHandler`, `createHttpRouteHandler`),
 * which keeps every existing check: size first, signature shape before any body read,
 * reads in flight capped, the HMAC over the raw bytes. Every other path is 404 and every
 * other method 405 (`allow: GET, POST`), both with `connection: close` and no body; a
 * malformed request is 400 and its socket is closed. The server binds `host` only, which
 * must be `127.0.0.1` or `::1` (a name such as `localhost` is refused, since it resolves at
 * bind time), with header and request timeouts, a header size cap and a connection cap.
 *
 * `start({ signal })` listens and resolves `{ port }` (port 0 picks a free one); an abort
 * of `signal` stops it, as `stop()` does: the server closes, open sockets are dropped and
 * the port is released. An abort or a `stop()` while the start is still binding cancels
 * it: the port is released as soon as it is bound, the start rejects ("stopped while
 * starting") and `stop()` resolves once the port is free. A second `start()` while one is
 * pending or running is refused. Logs are fixed events only (`listener-started`,
 * `listener-stopped`, `listener-error` with the error code, `request-refused` with
 * `not-found` or `method-not-allowed`), never a path, query, header, address or body.
 * @param {{ handler: (req: any, res: any) => unknown, host: unknown, port: unknown, path: unknown,
 *   log?: { info?: Function, warn?: Function, error?: Function } }} opts
 */
export function createWebhookListener({ handler, host, port, path: webhookPath, log }) {
  if (typeof handler !== "function") throw new Error("idx-whatsapp-channel: webhook listener: no handler");
  if (typeof host !== "string" || !LOOPBACK_HOSTS.includes(host)) throw new Error("idx-whatsapp-channel: webhook listener: host not loopback");
  if (!Number.isInteger(port) || /** @type {number} */ (port) < 0 || /** @type {number} */ (port) > 65_535) {
    throw new Error("idx-whatsapp-channel: webhook listener: bad port");
  }
  if (!isWebhookPath(webhookPath)) throw new Error("idx-whatsapp-channel: webhook listener: bad path");
  const note = (level, event, reason) => {
    try {
      log?.[level]?.({ component: "idx-whatsapp-channel.cloud-api-listener", event, ...(reason !== undefined ? { reason } : {}) });
    } catch {
      /* logging never affects serving */
    }
  };

  /** @param {any} res @param {number} status @param {Record<string, string>} [extra] */
  const refuse = (res, status, extra = {}) => {
    res.writeHead(status, { ...NO_BODY_HEADERS, ...extra });
    res.end();
  };

  const server = createServer(
    {
      maxHeaderSize: LISTENER_MAX_HEADER_BYTES,
      headersTimeout: LISTENER_HEADERS_TIMEOUT_MS,
      requestTimeout: LISTENER_REQUEST_TIMEOUT_MS,
      keepAliveTimeout: LISTENER_KEEP_ALIVE_TIMEOUT_MS,
      connectionsCheckingInterval: LISTENER_TIMEOUT_CHECK_MS,
    },
    (req, res) => {
      try {
        const url = typeof req.url === "string" ? req.url : "";
        const q = url.indexOf("?");
        const pathname = q === -1 ? url : url.slice(0, q);
        if (pathname !== webhookPath) {
          note("warn", "request-refused", "not-found");
          refuse(res, 404);
          return;
        }
        if (req.method !== "GET" && req.method !== "POST") {
          note("warn", "request-refused", "method-not-allowed");
          refuse(res, 405, { allow: "GET, POST" });
          return;
        }
        Promise.resolve(handler(req, res)).catch(() => {
          try {
            if (!res.headersSent) refuse(res, 500);
            else res.destroy();
          } catch {
            /* the response is already gone */
          }
        });
      } catch {
        try {
          refuse(res, 500);
        } catch {
          /* the response is already gone */
        }
      }
    },
  );
  server.maxConnections = LISTENER_MAX_CONNECTIONS;
  server.on("clientError", (/** @type {any} */ err, socket) => {
    try {
      const code = err?.code;
      const status =
        code === "HPE_HEADER_OVERFLOW" ? "431 Request Header Fields Too Large"
          : code === "ERR_HTTP_REQUEST_TIMEOUT" || code === "HPE_HEADERS_TIMEOUT" ? "408 Request Timeout"
            : "400 Bad Request";
      if (socket.writable) socket.end(`HTTP/1.1 ${status}\r\nconnection: close\r\ncontent-length: 0\r\n\r\n`);
      else socket.destroy();
    } catch {
      /* nothing left to answer */
    }
  });

  /**
   * "idle" (not bound), "starting" (listen called, "listening" not yet seen) or
   * "listening". A stop or an abort during "starting" cancels that start: the server is
   * closed as soon as it is bound and the start rejects, so a stopped account never
   * leaves the port bound (WO-038 fix review, 2026-11-08).
   */
  let state = "idle";
  /** Bumped on every start and every stop, so a stale start's signal cannot stop a later one. */
  let generation = 0;
  /** @type {Promise<void> | null} the close in progress or last finished */
  let closing = null;
  /** @type {(() => Promise<void>) | null} cancels the pending start; set only while "starting" */
  let cancelPending = null;
  /** @type {(() => void) | null} removes the running start's abort listener */
  let detach = null;

  function closeServer() {
    closing = new Promise((resolve) => {
      server.close(() => {
        note("info", "listener-stopped");
        resolve();
      });
      server.closeAllConnections?.();
    });
    return closing;
  }

  function stop() {
    if (state === "starting" && cancelPending) return cancelPending();
    if (state !== "listening") return closing ?? Promise.resolve();
    state = "idle";
    generation += 1;
    detach?.();
    detach = null;
    return closeServer();
  }

  /** @param {{ signal?: AbortSignal }} [opts] @returns {Promise<{ port: number }>} */
  function start({ signal } = {}) {
    if (signal?.aborted) return Promise.reject(new Error("idx-whatsapp-channel: webhook listener: aborted"));
    if (state !== "idle") return Promise.reject(new Error("idx-whatsapp-channel: webhook listener: already started"));
    state = "starting";
    generation += 1;
    const mine = generation;
    let cancelled = false;
    /** @type {() => void} */
    let released = () => {};
    const releasedP = new Promise((r) => {
      released = () => r(undefined);
    });
    cancelPending = () => {
      cancelled = true;
      return releasedP;
    };
    const onAbort = () => {
      if (generation !== mine) return;
      if (state === "starting") void cancelPending?.();
      else if (state === "listening") void stop();
    };
    signal?.addEventListener?.("abort", onAbort, { once: true });
    detach = () => signal?.removeEventListener?.("abort", onAbort);
    /** Ends a start that will not serve: back to idle, listener detached, waiters released. */
    const abandon = () => {
      state = "idle";
      cancelPending = null;
      detach?.();
      detach = null;
    };
    // A close still in progress from the last stop finishes before the port is bound again.
    const before = closing ?? Promise.resolve();
    return new Promise((resolve, reject) => {
      void before.then(() => {
        if (cancelled || signal?.aborted) {
          abandon();
          released();
          reject(new Error("idx-whatsapp-channel: webhook listener: stopped while starting"));
          return;
        }
        const onError = (/** @type {any} */ err) => {
          server.off("listening", onListening);
          abandon();
          released();
          note("error", "listener-error", typeof err?.code === "string" && /^[A-Z_]{1,32}$/.test(err.code) ? err.code : "error");
          reject(new Error("idx-whatsapp-channel: webhook listener: listen failed"));
        };
        const onListening = () => {
          server.off("error", onError);
          cancelPending = null;
          if (cancelled || signal?.aborted) {
            // Stopped or aborted while binding: release the port, never serve.
            abandon();
            generation += 1;
            void closeServer().then(released);
            reject(new Error("idx-whatsapp-channel: webhook listener: stopped while starting"));
            return;
          }
          state = "listening";
          note("info", "listener-started");
          const addr = server.address();
          resolve({ port: addr !== null && typeof addr === "object" ? addr.port : 0 });
        };
        server.once("error", onError);
        server.once("listening", onListening);
        server.listen({ host, port, exclusive: true });
      });
    });
  }

  return Object.freeze({ start, stop });
}
