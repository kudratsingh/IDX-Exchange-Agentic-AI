/**
 * Persistent, bounded dedupe for Cloud API inbound messages (WO-040).
 *
 * Meta may deliver the same message more than once, and retries for days. The webhook
 * drops any message whose Meta timestamp is older than MAX_INBOUND_AGE_MS (30 minutes) or
 * more than MAX_CLOCK_SKEW_MS ahead, so a duplicate can start a second turn (and a second
 * billed reply) only while the webhook would still accept it. Before WO-040 the ids seen
 * were kept in memory only, so a gateway restart forgot them (WO-038 decision 8). This store
 * keeps them on disk across restarts and across processes.
 *
 * Layout: a directory DEDUPE_DIR_NAME next to the owner's credentials file, mode 700, made
 * by the gateway, holding one marker file per claimed message. A marker's name is the first
 * 128 bits of HMAC-SHA256(key, messageId) in hex, where the key is derived from the business
 * phone-number id; it holds the message's Meta timestamp (ms). Never a message id, a peer,
 * a text or a token. The key is the same in every process for the number, so overlapping or
 * restarted processes always name a message's marker alike, and there is no salt file to
 * create, lose or swap (review round 5). It is not a secret: it keeps ids off the disk; it
 * does not stop someone who already holds a message id from testing for its marker.
 *
 * One atomic step per message, with no lock. `claim(id, timestamp)` creates the message's
 * marker with O_CREAT | O_EXCL | O_NOFOLLOW (mode 600): the file system lets exactly one
 * create succeed, in any process, so two gateway processes overlapping during a restart
 * cannot both claim a message, and no claim can be lost by another writer. A create that
 * fails with EEXIST is a duplicate. A create that succeeds is the claim, made before the
 * webhook starts the turn; the timestamp write and the fsyncs after it are best effort, so a
 * claimed message is never reported unclaimed (a crash in that gap leaves an empty marker,
 * which still counts as claimed and expires by its file time). Any other create failure
 * throws, and the webhook answers 503 so Meta retries.
 *
 * Bounded. A marker is kept for DEDUPE_RETENTION_MS (24 hours) after its Meta timestamp,
 * far longer than the acceptance window (DEDUPE_WINDOW_MS, 35 minutes). Expiry is measured
 * from the clock but never from further ahead than the newest marker plus the window, so a
 * clock days fast at a restart cannot expire everything. At most `maxEntries` markers
 * (4096): when full, markers past the retention go first, then markers past the acceptance
 * window, oldest first, down to 90% of the cap; removing a marker before its 24 hours needs
 * a Meta timestamp (the newest stored one, or the claimed message's) showing it can no
 * longer be accepted, so a fast clock makes a full store refuse ("full"), never evict. While
 * our clock is shown to be behind (the newest stored Meta stamp is more than the skew
 * margin ahead of it), claims refuse ("clock-behind"), so a clock stepped back cannot let a
 * retry of an evicted message through. Claims in overlapping processes are not serialised
 * and can together pass the cap; claims then answer "full" until markers leave the window,
 * and open refuses only beyond DEDUPE_CAP_SLACK over it. The webhook claims only messages
 * from senders the channel admits, so strangers cannot fill it.
 *
 * Owner-only, like the credentials file it sits next to: the parent directory is owned by
 * this user and not group- or world-writable; the store directory and every marker are this
 * user's, without group or other bits, not symlinks, single-link regular files, with no
 * extended ACL on macOS. A store that fails a check, or holds a non-dot file it did not make,
 * is refused at open with a fixed reason and never changed: the owner looks at it and
 * removes it by hand. Dot-files (Finder's `.DS_Store`) are ignored. The directory gets mode
 * 700 whatever the umask; reads never block on a FIFO.
 *
 * The store belongs to the credentials file's directory: moving the credentials file
 * elsewhere starts an empty store, so move the store directory with it (gateway stopped).
 *
 * Node built-ins only. No network.
 */

import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { createHmac, randomBytes as cryptoRandomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  constants as fsConstants,
  fstatSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  readdirSync,
  realpathSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import path from "node:path";

import { MAX_CLOCK_SKEW_MS, MAX_INBOUND_AGE_MS } from "./cloud-api-transport.mjs";

/** The store directory's name, next to the owner's credentials file. */
export const DEDUPE_DIR_NAME = "cloud-api-dedupe.v1";
/** Markers kept at most; when full only markers past the window may go. */
export const DEDUPE_STORE_MAX_ENTRIES = 4096;
/** The acceptance window: every message the webhook could still accept (age limit plus
 *  the margin for a timestamp ahead of our clock). A marker inside it is never evicted. */
export const DEDUPE_WINDOW_MS = MAX_INBOUND_AGE_MS + MAX_CLOCK_SKEW_MS;
/** How long a marker is kept after its Meta timestamp when there is room: far past the
 *  window, so a wall-clock step cannot drop an id that could be accepted again. */
export const DEDUPE_RETENTION_MS = 86_400_000;
/** How often (at most) a claim looks through the markers to remove expired ones. */
export const DEDUPE_PRUNE_INTERVAL_MS = 60_000;
/** Markers over the cap that open still accepts: claims in overlapping processes are not
 *  serialised and each process counts only its own claims between prunes, so together they
 *  can pass the cap; claims then answer "full" until markers leave the window. */
export const DEDUPE_CAP_SLACK = DEDUPE_STORE_MAX_ENTRIES;
/** When a full store is pruned, it is brought down to this share of the cap, so a full
 *  scan runs once per hundreds of claims, not on each one. */
const LOW_WATER = 0.9;
/** The label the marker key is derived under, with the phone-number id. */
const KEY_LABEL = "idx-whatsapp-channel/cloud-api-dedupe/v1";

const KEY_RE = /^[0-9a-f]{32}$/u;
/** A plausible Meta timestamp in ms: 13 digits (2001 to 2286). */
const TS_RE = /^\d{13}$/u;
const TMP_RE = /^\.tmp\.\d+\.[0-9a-f]{12}$/u;
const LS_BIN = "/bin/ls";
const ACL_LINE_RE = /^\s*\d+: /m;

/** A refusal with a fixed reason only. */
export class DedupeStoreError extends Error {
  /** @param {string} reason */
  constructor(reason) {
    super(`idx-whatsapp-channel: dedupe store: ${reason}`);
    this.name = "DedupeStoreError";
    this.reason = reason;
  }
}

/** Whether a path carries a macOS extended ACL (see cloud-api-wiring.mjs for why). */
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

/**
 * The store directory for a credentials file: DEDUPE_DIR_NAME in the real directory that
 * holds it (the directory the credentials reader has already checked).
 * @param {string} credentialsFile an absolute path
 * @param {{ realpathSync?: (p: string) => string }} [deps]
 */
export function dedupeDirFor(credentialsFile, deps = {}) {
  if (typeof credentialsFile !== "string" || !path.isAbsolute(credentialsFile)) throw new DedupeStoreError("not-absolute");
  let dir;
  try {
    dir = (deps.realpathSync ?? realpathSync.native)(path.dirname(path.resolve(credentialsFile)));
  } catch {
    throw new DedupeStoreError("unsafe-directory");
  }
  return path.join(dir, DEDUPE_DIR_NAME);
}

/**
 * Opens (or, when it does not exist yet, creates) the store directory `dir`, an absolute
 * path whose parent is an owner-only directory, for the business number `keyId` (its
 * phone-number id), and proves it can write there. Throws DedupeStoreError with a fixed
 * reason: "not-absolute", "no-user-id", "no-key", "unsafe-directory", "symlink",
 * "not-directory", "wrong-owner", "permissions-too-open", "permissions-too-closed",
 * "acl-present", "acl-unknown", "unexpected-file", "hard-linked", "not-regular-file",
 * "unreadable", "too-many-entries", "unwritable".
 *
 * Returns a frozen `{ claim(messageId, timestamp), has(messageId), size() }`:
 *   - `claim` returns true when this call claimed the id (its marker now exists), false
 *     when it was claimed before, by this process or any other; it throws "full",
 *     "clock-behind", "unsafe-marker" or "write-failed", and then claims nothing;
 *   - `has` and `size` look at the directory as it is now (tests and diagnostics).
 * @param {{ dir: string, keyId: string, now?: () => number, uid?: number, maxEntries?: number,
 *   retentionMs?: number, windowMs?: number, skewMs?: number, pruneIntervalMs?: number,
 *   capSlack?: number, hasExtendedAcl?: (p: string) => boolean,
 *   randomBytes?: (n: number) => Buffer, fs?: Record<string, Function> }} opts
 */
export function openDedupeStore(opts) {
  const fs = {
    lstatSync,
    mkdirSync,
    openSync,
    fstatSync,
    readSync,
    readdirSync,
    writeSync,
    fsyncSync,
    closeSync,
    chmodSync,
    unlinkSync,
    ...(opts?.fs ?? {}),
  };
  const now = opts?.now ?? Date.now;
  const uid = opts?.uid ?? process.getuid?.();
  const maxEntries = opts?.maxEntries ?? DEDUPE_STORE_MAX_ENTRIES;
  const retentionMs = opts?.retentionMs ?? DEDUPE_RETENTION_MS;
  const windowMs = opts?.windowMs ?? DEDUPE_WINDOW_MS;
  const skewMs = opts?.skewMs ?? MAX_CLOCK_SKEW_MS;
  const pruneIntervalMs = opts?.pruneIntervalMs ?? DEDUPE_PRUNE_INTERVAL_MS;
  const capSlack = opts?.capSlack ?? DEDUPE_CAP_SLACK;
  const hasExtendedAcl = opts?.hasExtendedAcl ?? defaultHasExtendedAcl;
  const rand = opts?.randomBytes ?? cryptoRandomBytes;
  const dir = opts?.dir;
  const keyId = opts?.keyId;
  if (typeof uid !== "number") throw new DedupeStoreError("no-user-id");
  if (typeof dir !== "string" || !path.isAbsolute(dir)) throw new DedupeStoreError("not-absolute");
  if (typeof keyId !== "string" || keyId === "") throw new DedupeStoreError("no-key");
  const parent = path.dirname(dir);
  const NOFOLLOW = fsConstants.O_NOFOLLOW ?? 0;
  // Never block on a FIFO or device that took a store name: open returns, and the fstat
  // check that follows refuses it.
  const NONBLOCK = fsConstants.O_NONBLOCK ?? 0;
  const CREATE = fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL | NOFOLLOW;
  const tmpName = () => `.tmp.${process.pid}.${rand(6).toString("hex")}`;
  const key = createHmac("sha256", KEY_LABEL).update(keyId, "utf8").digest();
  /** @param {string} messageId */
  const keyOf = (messageId) => createHmac("sha256", key).update(messageId, "utf8").digest("hex").slice(0, 32);

  function aclCheck(p) {
    let acl;
    try {
      acl = hasExtendedAcl(p);
    } catch {
      throw new DedupeStoreError("acl-unknown");
    }
    if (acl !== false) throw new DedupeStoreError("acl-present");
  }
  /** @param {import("node:fs").Stats} st */
  function ownerOnlyFile(st) {
    if (st.isSymbolicLink()) throw new DedupeStoreError("symlink");
    if (!st.isFile()) throw new DedupeStoreError("not-regular-file");
    if (st.nlink !== 1) throw new DedupeStoreError("hard-linked");
    if (st.uid !== uid) throw new DedupeStoreError("wrong-owner");
    if ((st.mode & 0o077) !== 0) throw new DedupeStoreError("permissions-too-open");
  }
  /** @param {string} p */
  function lstatOr(p) {
    try {
      return fs.lstatSync(p);
    } catch {
      throw new DedupeStoreError("unreadable");
    }
  }
  /** Small owner-only file contents, read without following a link; null when missing. */
  function readSmall(p, max) {
    let fd;
    try {
      fd = fs.openSync(p, fsConstants.O_RDONLY | NOFOLLOW | NONBLOCK);
    } catch (err) {
      const code = /** @type {any} */ (err)?.code;
      if (code === "ENOENT") return null;
      if (code === "ELOOP") throw new DedupeStoreError("symlink");
      throw new DedupeStoreError("unreadable");
    }
    try {
      ownerOnlyFile(fs.fstatSync(fd));
      const buf = Buffer.alloc(max + 1);
      let n = 0;
      try {
        for (;;) {
          const got = fs.readSync(fd, buf, n, buf.length - n, null);
          if (got === 0) break;
          n += got;
          if (n > max) break;
        }
      } catch {
        throw new DedupeStoreError("unreadable");
      }
      return buf.subarray(0, Math.min(n, max + 1)).toString("utf8");
    } finally {
      try {
        fs.closeSync(fd);
      } catch {
        /* gone either way */
      }
    }
  }
  /** fsync a directory, best effort (some file systems refuse it). */
  function syncDir(p) {
    try {
      const dfd = fs.openSync(p, fsConstants.O_RDONLY);
      try {
        fs.fsyncSync(dfd);
      } finally {
        fs.closeSync(dfd);
      }
    } catch {
      /* best effort */
    }
  }

  // The parent: owned by this user, not group- or world-writable, no ACL.
  let parentStat;
  try {
    parentStat = fs.lstatSync(parent);
  } catch {
    throw new DedupeStoreError("unsafe-directory");
  }
  if (!parentStat.isDirectory() || parentStat.uid !== uid || (parentStat.mode & 0o022) !== 0) throw new DedupeStoreError("unsafe-directory");
  aclCheck(parent);

  // The store directory: made once with mode 700 whatever the umask. A directory of ours
  // with no group or other bits but without the owner's (a crash between mkdir and chmod
  // under a strict umask) gets the owner's bits; nothing else is ever widened.
  let made = false;
  try {
    fs.mkdirSync(dir, { mode: 0o700 });
    made = true;
  } catch (err) {
    if (/** @type {any} */ (err)?.code !== "EEXIST") throw new DedupeStoreError("unwritable");
  }
  let dirStat = lstatOr(dir);
  if (dirStat.isDirectory() && !dirStat.isSymbolicLink() && dirStat.uid === uid && (dirStat.mode & 0o077) === 0 && (made || (dirStat.mode & 0o700) !== 0o700)) {
    try {
      fs.chmodSync(dir, 0o700);
    } catch {
      /* the checks below decide */
    }
    dirStat = lstatOr(dir);
  }
  if (made) syncDir(parent);
  if (dirStat.isSymbolicLink()) throw new DedupeStoreError("symlink");
  if (!dirStat.isDirectory()) throw new DedupeStoreError("not-directory");
  if (dirStat.uid !== uid) throw new DedupeStoreError("wrong-owner");
  if ((dirStat.mode & 0o077) !== 0) throw new DedupeStoreError("permissions-too-open");
  if ((dirStat.mode & 0o700) !== 0o700) throw new DedupeStoreError("permissions-too-closed");
  aclCheck(dir);

  /** The marker names now in the store. `strict` (at open) refuses a name it did not make,
   *  apart from dot-files such as Finder's `.DS_Store`; while running, other names are
   *  skipped, never counted and never removed. */
  function markers(strict = false) {
    let names;
    try {
      names = fs.readdirSync(dir);
    } catch {
      throw new DedupeStoreError("unreadable");
    }
    const out = [];
    for (const n of names) {
      if (KEY_RE.test(n)) {
        out.push(n);
        continue;
      }
      if (strict && !n.startsWith(".")) throw new DedupeStoreError("unexpected-file");
    }
    return out;
  }

  /** name -> Meta timestamp (ms) for markers with a real stamp; written once, never changes. */
  const stamps = new Map();
  /** A marker's timestamp: its Meta time, or, when it is empty or not a plausible time (a
   *  crash or a full disk while stamping), the time the file was made (mtime), so it still
   *  expires; null only when it cannot be looked at (then it is never removed). */
  function stampOf(name) {
    const known = stamps.get(name);
    if (known !== undefined) return known;
    try {
      const p = path.join(dir, name);
      const s = readSmall(p, 16);
      if (s === null) return null;
      if (TS_RE.test(s)) {
        const t = Number(s);
        stamps.set(name, t);
        return t;
      }
      return Math.trunc(fs.lstatSync(p).mtimeMs);
    } catch {
      return null;
    }
  }
  const newestMeta = () => {
    let m = -Infinity;
    for (const t of stamps.values()) if (t > m) m = t;
    return m;
  };
  let lastPrune = -Infinity;
  /** Markers counted at the last prune plus this process's claims since. */
  let count = 0;
  /**
   * Removes markers past the retention; while still at or over `limit`, markers past the
   * window, oldest first, down to `target`. The retention cut-off is measured from the clock
   * but never from further ahead than the newest marker plus the window. Removing a marker
   * before its retention needs evidence of the real time our own clock cannot supply: the
   * newest Meta stamp, or `incoming` (the Meta stamp of the message being claimed); the
   * real time is at least that minus the skew margin, so a marker older than it minus the
   * whole window can no longer be accepted (review round 4). Returns how many remain.
   */
  function prune(limit = Infinity, target = limit, incoming = undefined) {
    const names = markers();
    const stamped = names.map((n) => [n, stampOf(n)]).filter(([, t]) => t !== null);
    const newest = stamped.reduce((m, [, t]) => Math.max(m, /** @type {number} */ (t)), -Infinity);
    const ref = Number.isFinite(newest) ? Math.min(now(), newest + windowMs) : now();
    const evidence = Math.max(newestMeta(), Number.isSafeInteger(incoming) ? /** @type {number} */ (incoming) : -Infinity);
    const evictBefore = Number.isFinite(evidence) ? Math.min(now(), evidence) - windowMs : -Infinity;
    let remaining = names.length;
    const drop = (n) => {
      try {
        fs.unlinkSync(path.join(dir, n));
        stamps.delete(n);
        remaining -= 1;
      } catch {
        /* another process removed it */
      }
    };
    for (const [n, t] of stamped) if (/** @type {number} */ (t) < ref - retentionMs) drop(n);
    if (remaining >= limit) {
      const old = stamped
        .filter(([, t]) => /** @type {number} */ (t) >= ref - retentionMs && /** @type {number} */ (t) < evictBefore)
        .sort((x, y) => /** @type {number} */ (x[1]) - /** @type {number} */ (y[1]));
      for (const [n] of old) {
        if (remaining < target) break;
        drop(n);
      }
    }
    lastPrune = now();
    count = remaining;
    return remaining;
  }

  // Open: check every file there, remove this store's own stale temporary files, prove a
  // write works, prune, and only then hold the count against the cap.
  const existing = markers(true);
  for (const n of existing) ownerOnlyFile(lstatOr(path.join(dir, n)));
  for (const n of fs.readdirSync(dir)) {
    if (!TMP_RE.test(n)) continue;
    try {
      const st = fs.lstatSync(path.join(dir, n));
      if (st.isFile() && !st.isSymbolicLink() && st.uid === uid && Date.now() - st.mtimeMs > 60_000) fs.unlinkSync(path.join(dir, n));
    } catch {
      /* gone, or not ours to remove */
    }
  }
  const probe = path.join(dir, tmpName());
  try {
    fs.closeSync(fs.openSync(probe, CREATE, 0o600));
    fs.unlinkSync(probe);
  } catch {
    throw new DedupeStoreError("unwritable");
  }
  // Over the cap after pruning: claims answer "full" until markers leave the window, so open
  // refuses only far above any overshoot overlapping processes can reach.
  if (prune(maxEntries, Math.floor(maxEntries * LOW_WATER)) > maxEntries + capSlack) throw new DedupeStoreError("too-many-entries");

  return Object.freeze({
    /** @param {string} messageId @param {number} timestamp Meta's time for the message (ms) */
    claim(messageId, timestamp) {
      const marker = path.join(dir, keyOf(messageId));
      // Already claimed, here or by another process.
      let st = null;
      try {
        st = fs.lstatSync(marker);
      } catch (err) {
        if (/** @type {any} */ (err)?.code !== "ENOENT") throw new DedupeStoreError("write-failed");
      }
      if (st !== null) {
        if (st.isSymbolicLink() || !st.isFile() || st.uid !== uid) throw new DedupeStoreError("unsafe-marker");
        return false;
      }
      if (now() - lastPrune >= pruneIntervalMs) prune();
      // Our clock shown to be behind: a marker evicted earlier could be accepted again.
      if (newestMeta() > now() + skewMs) throw new DedupeStoreError("clock-behind");
      if (count >= maxEntries && prune(maxEntries, Math.floor(maxEntries * LOW_WATER), Math.trunc(Number(timestamp))) >= maxEntries) throw new DedupeStoreError("full");
      let fd;
      try {
        fd = fs.openSync(marker, CREATE, 0o600);
      } catch (err) {
        if (/** @type {any} */ (err)?.code === "EEXIST") return false;
        throw new DedupeStoreError("write-failed");
      }
      // Claimed. What follows makes it durable and stamped; none of it can undo the claim.
      count += 1;
      const t = Math.max(0, Math.trunc(Number(timestamp) || 0));
      try {
        const body = Buffer.from(String(t), "utf8");
        let off = 0;
        while (off < body.length) off += fs.writeSync(fd, body, off, body.length - off);
        fs.fsyncSync(fd);
        if (TS_RE.test(String(t))) stamps.set(path.basename(marker), t);
      } catch {
        /* an empty marker still counts as claimed; it expires by its file time */
      } finally {
        try {
          fs.closeSync(fd);
        } catch {
          /* gone */
        }
      }
      syncDir(dir);
      return true;
    },
    /** @param {string} messageId */
    has(messageId) {
      try {
        fs.lstatSync(path.join(dir, keyOf(messageId)));
        return true;
      } catch {
        return false;
      }
    },
    size() {
      return markers().length;
    },
  });
}
