// Offline prototype only (WO-036, ADR-0015 proposed): never installed or activated.
// Read-only adapter for the one card directory the server writes
// (src/idx_agent/channels/card_store.py). It never writes, creates, renames or
// removes a file. Any doubt (symlink, owner, mode, size, shape) reads as missing,
// and a missing record withholds the reply.
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync } from "node:fs";
import { basename, isAbsolute, join } from "node:path";
import { fileName, parseRecord } from "./verify.mjs";

export const DIR_NAME = "idx-cards";
export const MAX_RECORD_BYTES = 64 * 1024;
const REF = /^[bcdfghjkmnpqrstv]{20}$/;

/** @param {import("node:fs").Stats} info @param {number} uid */
const ownerOnly = (info, uid) => info.uid === uid && (info.mode & 0o077) === 0;

/**
 * @param {string} directory absolute path whose last part is idx-cards
 * @param {string} ref
 * @param {number} uid the gateway process's uid
 * @returns {import("./verify.mjs").CardRecord | undefined}
 */
export function readRecord(directory, ref, uid) {
  try {
    if (!isAbsolute(directory) || basename(directory) !== DIR_NAME || !REF.test(ref)) return;
    const dir = lstatSync(directory);
    if (!dir.isDirectory() || !ownerOnly(dir, uid)) return;
    const path = join(directory, fileName(ref));
    const before = lstatSync(path);
    if (!before.isFile() || before.size > MAX_RECORD_BYTES) return;
    const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const info = fstatSync(fd);
      if (!info.isFile() || info.ino !== before.ino || info.dev !== before.dev
          || !ownerOnly(info, uid) || info.size > MAX_RECORD_BYTES) return;
      const buffer = new Uint8Array(MAX_RECORD_BYTES + 1);
      let length = 0;
      for (;;) {
        const n = readSync(fd, buffer, length, buffer.length - length, null);
        if (n === 0) break;
        length += n;
        if (length > MAX_RECORD_BYTES) return;
      }
      const record = parseRecord(JSON.parse(new TextDecoder("utf-8", { fatal: true })
        .decode(buffer.subarray(0, length))));
      return record && record.ref === ref ? record : undefined;
    } finally {
      closeSync(fd);
    }
  } catch {
    return undefined;
  }
}
