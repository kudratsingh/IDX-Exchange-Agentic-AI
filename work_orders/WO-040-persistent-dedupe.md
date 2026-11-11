# WO-040 — Persistent, bounded dedupe for Cloud API inbound

**Driver:** agent (store, wiring, tests, harness, docs); owner (approval of this PR, and
separately every live step and any buyer added to the allowlist)
**Depends on:** WO-039 (Cloud API wiring, #185 and #186 merged; main e0c2370); WO-038
(transport and webhook, decision 8); ADR-0017 (proposed)
**Autonomy level this moves toward:** L1 to L2: removes the last code precondition the
owner set for adding buyers to the allowlist. It adds no buyer and sends nothing.

Owner instruction, verbatim: "In parallel, prepare persistent dedupe for review using
synthetic message IDs. It's required before adding buyers."

## Objective
A Meta duplicate delivery (or a replayed captured request) must never start a second turn,
and so a second billed reply, even across a gateway restart, for as long as the webhook
would still accept the message. Bounded in size and time, owner-only on disk, fail closed.

## Why
The webhook drops any message whose Meta timestamp is older than 30 minutes (or more than
5 minutes ahead), and dedupes the rest by message id. Before this order the ids were kept
in memory only, so a restart inside the 30-minute window forgot them (WO-038 decision 8,
runbook 7 residual). Meta retries for up to 7 days and may deliver duplicates.

## In scope
1. `cloud-api-dedupe.mjs` (new runtime module): `openDedupeStore`, `dedupeDirFor`,
   `DedupeStoreError`, `DEDUPE_DIR_NAME`, `DEDUPE_RETENTION_MS`, `DEDUPE_WINDOW_MS`,
   `DEDUPE_STORE_MAX_ENTRIES`, `DEDUPE_PRUNE_INTERVAL_MS`.
2. `cloud-api-transport.mjs`: `createCloudApiWebhook({ dedupeStore, acceptsSender })` dedupes
   every message in memory, claims an admitted sender's message in the store before it
   dispatches, and answers 503 (`webhook-deferred`) when the store cannot claim; the
   transport passes the running start's `acceptsSender`.
3. `channel.mjs`: `startAccount` passes `acceptsSender` (its own allowlist rule) to
   `transport.start`; `transport.mjs` documents the optional field.
4. `index.mjs`: `processCloudApi` opens the store next to the credentials file before it
   builds the transport and refuses `dedupe-<reason>`; `cloudApiDeps.openDedupe` test seam.
5. `package.json` `files`, the runtime file-set pins (`host.test.mjs`,
   `tests/test_whatsapp_channel_skeleton.py`).
6. Tests: `cloud-api-dedupe.test.mjs` (new, DD-1 to DD-12), CE-16, harness mode
   `cloud-api-restart` with check E and HC-17.
7. Docs: runbook section 7 (the store, refusal reasons, 7.1, 7.5, 7.6 step 5), ADR-0017
   note, harness README.

## Out of scope (each held for separate written owner approval)
Adding any buyer to the allowlist; credentials, number registration, the tunnel, the Meta
subscription, any live send, the tunnel validation on the owner's build and the
five-message smoke test. No new dependency or service.

## Design (decisions, each with the reason)
1. **What is kept.** A directory `cloud-api-dedupe.v1/` (mode 700) holding one marker
   file per claimed message, named by the first 128 bits of HMAC-SHA256(key, message id) in
   hex, where the key is HMAC-SHA256 over the business phone-number id under a fixed label,
   and holding Meta's timestamp in ms. Never an id, a peer, a text or a token. The key is the
   same in every process for the number, so overlapping or restarted processes always name
   a marker alike; an earlier per-store salt file was dropped after review rounds 3 to 5
   kept finding races around making, losing and swapping it. The key is not a secret: it
   keeps ids off the disk, it does not stop someone already holding a message id from
   testing for its marker.
2. **One atomic claim, no lock.** `claim(id, ts)` creates the marker with
   O_CREAT | O_EXCL | O_NOFOLLOW (mode 600) BEFORE the webhook starts the turn. The file
   system grants that create to exactly one caller in any process, so an old and a new
   gateway process overlapping during a restart can never both start a turn for one message,
   and no other writer can erase a claim. EEXIST means a duplicate. Once the create succeeds
   the claim stands: the timestamp write and the fsyncs after it are best effort, and an
   empty marker (a crash in that gap) still counts, and expires by its file time. Any other create
   failure throws; the webhook logs `dedupe-store-failed` and answers 503, so Meta retries
   the whole POST; messages earlier in that POST were claimed and started, and their retry
   is ignored. (Review history: a single-file store with a lock file was replaced after two
   adversarial rounds found the lock could be broken under a live writer, could spin or
   stay stale after a crash, and blocked the event loop while waiting. Three further rounds
   on this store found twelve, six and seven narrower issues, each fixed with a regression,
   the last by dropping the salt file; see Status.)
3. **How long.** A marker is kept for 24 hours after its Meta timestamp, far past the
   35-minute acceptance window (MAX_INBOUND_AGE_MS plus MAX_CLOCK_SKEW_MS), so a wall-clock
   step forward and back cannot prune an id the webhook would accept again. Expiry is
   measured from the clock but never from further ahead than the newest marker plus the
   window, so a clock days fast at a restart expires nothing. A marker without a plausible
   13-digit stamp (a crash or a full disk while stamping) expires by its file time. Pruning
   runs at most once a minute, and when the store is full (then down to 90% of the cap, so
   a full scan runs once per hundreds of claims).
4. **How many, and from whom.** At most 4096 markers. When full, markers past the retention
   go, then markers past the acceptance window, oldest first; with none, the claim is
   refused (`full`, 503): an id still inside the window is never removed. Removing a marker
   before its 24 hours are up needs evidence of the real time that our own clock cannot
   supply: the newest Meta stamp, or the Meta stamp of the message being claimed (the real
   time is at least that minus the skew margin), so a fast clock, at open or while running,
   makes a full store refuse rather than evict (review round 4). Claims in overlapping
   processes are not serialised, so together they can pass the cap; claims then answer
   `full` until markers leave the window, and open refuses only far above the cap. Only messages from
   senders the channel admits (its allowlist, passed as `acceptsSender` through
   `transport.start`) are claimed; a stranger's message never touches the store, so
   strangers cannot fill it, and the channel still drops it. Every message, admitted or not,
   also goes through the in-memory dedupe.
5. **Where.** Inside the real directory of the owner's credentials file: already outside the
   repo and `~/.openclaw`, owned by the gateway user, not group- or world-writable and
   ACL-free (the credentials reader checks it). No new config key; the store is always on
   when the Cloud API is.
6. **Owner-only checks** on every open: the parent's owner and mode; the store directory not
   a symlink, this user's, mode without group or other bits, no ACL; every marker a
   single-link regular file of this user's without group or other bits; nothing in it but
   markers, dot-files (ignored, for Finder's `.DS_Store`) and the store's own temporary
   files (removed once a minute old); the directory made 700 whatever the umask, and a
   directory of ours with no group or other bits that lacks the owner's (a crash between
   mkdir and chmod under a strict umask) given them back, nothing else ever widened; after
   pruning, no more than twice the cap. A failure refuses the Cloud API at register
   (`dedupe-<reason>`) and changes nothing: the owner looks and removes it by hand. At
   claim, a marker that is a symlink or not a regular file is refused (`unsafe-marker`).
   Reads never block on a FIFO.
8. **A shared eviction watermark** (owner instruction, 2026-11-09: a duplicate across
   overlapping instances). Before any marker is removed inside its 24-hour retention, the
   Meta timestamp that justified it is recorded on disk: an empty file named by that time
   (13 digits) in `.evicted/` (owner-only, mode 700), made with an exclusive create, smaller
   names removed after, so the largest name is the watermark. Only then are markers
   removed; if the record cannot be made, nothing is removed and the claim answers `full`.
   Each prune records one watermark, its evidence (at least the newest real Meta stamp, and
   the claimed message's stamp when larger), before removing anything in either branch, so
   it covers every marker that prune removes: a retention-dropped marker is about a day older
   than it, an early-evicted one more than the window older. Every cut-off rests on real Meta
   stamps only: the retention reference is the newest real stamp plus the window (at most our
   clock), with no real stamp nothing is removed, and only markers with a real stamp are
   evicted early; an empty marker's file time is our clock, which may be behind Meta's, so
   it waits for its retention. `.evicted/` gets the same owner-bit repair, owner-only checks
   and ACL check as the store directory, at open and at each write; one that is a symlink,
   readable by others or carries an ACL is refused (`unsafe-watermark`, `acl-present`).
   A claim reads the watermark again right after its exclusive create: a process that
   stalled between its first read and the create, while another claimed and then evicted the
   same message, sees the watermark that eviction wrote first, and reports the message as seen
   (the new marker is kept). A failed re-read undoes the claim (only this call made the
   marker) and answers 503, so Meta's retry is claimed exactly once. Every watermark name must
   be an owner-only regular file, and a watermark more than a day ahead of the clock is
   refused (`unsafe-watermark`) rather than hiding every message.
   Every claim, in every process, treats a message whose Meta time is older than the
   watermark minus the 35-minute window as seen: real time is at least the watermark minus
   the 5-minute skew margin, so such a message is past the 30-minute age limit in real time
   and cannot be legitimately accepted, whatever that process's clock says. This replaces the
   per-process `clock-behind` check of round 5, which read only that process's own stamps,
   so an older instance never saw the evidence a newer one evicted on.
7. **Open proves a write.** Opening creates and removes one temporary file, so a store that
   cannot be written is refused at register (`dedupe-unwritable`), not on the first message.

## Tests required (offline, `node --test`; synthetic ids `wamid.TEST-...`, 555 numbers)
- DD-1 the first open makes an empty mode-700 directory; reopening changes nothing; a
  missing key is refused.
- DD-2 a claim is one marker named HMAC(number key, id)[0:128 bits] holding Meta's time;
  another number names it differently; again is false; known after a restart; no id on disk.
- DD-3 retention 24 hours; a clock step forward and back keeps the id, in one instance and
  after a restart; pruned after 24 hours.
- DD-4 full: markers past the window go first; full inside it refuses and removes nothing; a
  store over the cap is refused at open.
- DD-5 refusals: a symlinked or non-directory store, a group-readable store, a foreign file
  (also one named `salt`), a symlinked, hard-linked or group-readable marker, a writable parent,
  another user's parent, an ACL (present or unknown), a relative path, a missing parent;
  nothing changed.
- DD-6 a failed create claims nothing; a failed stamp still claims (an empty marker is never
  pruned and stays a duplicate after a restart); an unwritable new or existing store is
  refused at open.
- DD-7 two stores see each other's claims; in a forced race exactly one wins.
- DD-8 `dedupeDirFor`.
- DD-9 webhook: a duplicate after a restart starts nothing; a failing store answers 503 with
  `webhook-deferred` (never `webhook-accepted`) and nothing started at or after the failing
  message; Meta's retry starts each once; a stale message is never claimed; a stranger's
  flood claims nothing and a stranger's duplicate is dropped in memory.
- DD-10 transport: after a restart the duplicate makes zero Graph API requests.
- DD-11 a leftover temporary file is ignored; a symlink or directory marker is refused.
- DD-12 eight real processes race on one id: exactly one wins; none loses its own claim.
- DD-13 `.DS_Store` never blocks; a store removed and made again under a running process
  still names markers alike (the old process sees the new one's claim); a torn stamp is not
  read as 1970; mode 700 under umask 277, owner bits given back to a 500 store, a
  group-readable one refused; a FIFO named like a marker cannot hang a claim or a prune.
- DD-14 an empty 500 store directory is repaired; overlapping processes past the cap do not
  wedge the next open, and claims answer `full` until markers leave the window.
- DD-15 after a full-store eviction and a clock stepped back, Meta's retry of the evicted
  message is seen; a new message is still claimed.
- DD-16 (owner instruction) overlapping instances: the newer evicts a marker, the clock moves
  back 10 minutes, and Meta's signed retry through the OLDER instance's webhook starts zero
  turns; the control without the watermark starts a second turn on the older instance.
- DD-17 the watermark fails closed: when it cannot be written nothing is evicted and the claim
  answers `full`; a symlinked or group-readable `.evicted/` makes claims refuse
  (`unsafe-watermark`); it is never counted as a marker.
- DD-18 an empty marker 4 minutes behind its Meta time is not evicted early, so the retry
  through the older instance starts zero turns; a retention drop records the watermark
  first, so after a clock stepped back a day the retry through the older instance starts
  zero turns; an `.evicted/` left at mode 500 is repaired, at write and at open.
- DD-19 one prune that both drops by retention and evicts early records the larger evidence,
  so the retry of the early-evicted message through the older instance starts zero turns;
  with the newest marker empty, or every marker empty, nothing is dropped on a file time, so
  a retry after a clock stepped back a day starts zero turns; an ACL on `.evicted/` is
  refused at open and stops evictions while running.
- DD-20 an instance stalled between its watermark read and its create, while another claims
  the same message and evicts it, starts no second turn.
- DD-21 a failed re-read after the create undoes the claim, so the retry starts exactly one
  turn; a watermark far in the future, or a directory named like one, is refused.
- DD-4 also: a clock a day fast evicts nothing from a full store; a message whose Meta time
  shows the oldest marker is past the window frees room.
- CE-16 two real child processes: process 2 counts the duplicate ignored and delivers the new
  id; a stranger is handed to the channel, dropped, and never reaches the store; the store is
  a mode-700 directory with no id; a group-readable store refuses
  `dedupe-permissions-too-open` and is left as it is.
- HC-17 check E's rules, offline.

## Acceptance
All tests pass locally and in CI; the real-host mode `cloud-api-restart` passes E on the
pinned OpenClaw, and fails E against main's in-memory dedupe; `cloud-api` still passes;
the runbook describes the store, its refusals and its removal; nothing live is done.

## Stop conditions
Any need for a real id, a real number, a credential or a network call beyond loopback; a
host behaviour that differs from what the harness assumes; a requirement that would
relax a safety invariant.

## Status
2026-11-09, implemented offline on branch `wo-040-persistent-dedupe` (from main e0c2370).
Nothing installed, configured or enabled outside temporary harness state; no credential, no
real id or number, no Graph API call, no network beyond 127.0.0.1, no paid call; no buyer
added. Every message id in tests and the harness is synthetic (`wamid.TEST-...`,
`wamid.HARNESS-...`).

Review. Five adversarial rounds on the store, then three on the cross-instance fix, each
finding reproduced by a script before it was accepted, each fix given a regression and
checked by mutating it back:
- round 1 (one file with an in-memory map written whole): eight issues; strangers filling
  the store before the allowlist ran (now only admitted senders are claimed), a forward clock
  step pruning live ids (now 24-hour retention), a failure after the rename reported as a
  failure, two writers losing each other's ids;
- round 2 (that file behind a lock file): seven, all about the lock; replaced by one
  exclusive-create marker per message, with no lock;
- round 3 (marker store): twelve narrower ones (the cap check before pruning at open, the
  salt's second link, a fast clock at open, `.DS_Store`, a replaced store, per-claim cost when
  full, short and empty stamps, umask, FIFOs);
- round 4: six (a fast clock still evicting from a full store, a failed or lost salt, the
  overshoot past the cap, a crash between mkdir and chmod);
- round 5: seven, mostly around the salt; the salt file was dropped (the key is derived from
  the business phone-number id, the same in every process).
Owner review of #187 (2026-11-09): a duplicate across overlapping instances. The round-5
`clock-behind` check read only the evicting process's own stamps, so an older instance never
saw the evidence a newer one evicted on; it is replaced by the shared eviction watermark
(decision 8), with DD-16 as the owner's regression (its control without the watermark
starts a second turn on the older instance). Review rounds on the watermark found, in
turn, the issues fixed in DD-18 (empty markers evicted early on a file time, retention drops
without a watermark, `.evicted/` repair), DD-19 (one prune recording only the lower value,
file-time references, the ACL on `.evicted/`) and DD-20 (a stall between the watermark read
and the create), then DD-21 (a failed re-read losing the message, unchecked watermark names)
and the runbook's store-removal rule (24 quiet hours, correct clock). A control run of the real-host mode
against main's in-memory dedupe fails E: Meta's retry after a restart is counted delivered
and starts a second turn.

Node 315/315 (`cloud-api-dedupe.test.mjs` 21, `cloud-api-entry.test.mjs` 16,
`host-harness/checks.test.mjs` 18). Mutations, each caught: no exclusive create (DD-7), a
per-process random key (twelve DD and CE tests), retention back to 35 minutes (DD-3, DD-4,
DD-16, DD-18), no admission gate (DD-9, CE-16), no watermark check at claim (DD-15 to
DD-19), a watermark of the lower value (DD-16, DD-19), file-time references (DD-19), no
ACL check on `.evicted/` at open or at write (DD-19), early eviction of empty markers
(DD-18), no `.evicted/` repair (DD-18), no re-read after the create (DD-20), no undo on a
failed re-read, no watermark name check, no future bound (DD-21), dispatch
before the claim (ten CE and DD tests).

Real host (OpenClaw 2026.9.5, sandboxed, synthetic credentials, fake Graph API) on the
final code: `run.mjs cloud-api-restart cloud-api cloud-api-rollback genuine-only default`,
exit 0; `cloud-api-restart` PASS (E, A, I, K: after SIGTERM and a fresh process, Meta's
exact retry answered 200, was counted ignored, reached no model request and made no Graph
API request; the first DM's tool ran once; a new DM was delivered once with the exact body;
the store a mode-700 directory with one marker and no id); `cloud-api` PASS (S, W, G, U, N,
R, X, A, I, K, O); `cloud-api-rollback` PASS (H, F, V, K, O, A, I); `genuine-only` and
`default` PASS.

Adding any buyer to the allowlist still requires separate written owner approval, as do
credentials, the tunnel and its validation on the owner's build, the Meta subscription, any
live send and the five-message smoke test.
