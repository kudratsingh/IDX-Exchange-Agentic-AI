# WO-039 — Cloud API wiring, offline

**Driver:** agent (wiring, tests, harness, docs); owner (approval of this PR, every live
step, credentials, the tunnel, the Meta console, the smoke test)
**Depends on:** WO-038 (Cloud API transport and wiring pieces, #184 merged as 0a06324);
WO-037 (owned channel); ADR-0016; ADR-0017 (proposed)
**Autonomy level this moves toward:** L1: the assistant's replies can reach the owner's own
number over the official channel once the owner turns it on; nothing reaches a buyer.

Owner instruction, verbatim: "#184 is merged as 0a06324. Open the offline wiring PR against
main. Keep Cloud API off by default and use synthetic credentials and fake Graph API
responses to verify startup, signed webhook delivery, exact replies, and shutdown. Bring
back green CI and the owner-run smoke and rollback steps. Live setup requires separate
approval, and persistent dedupe is required before buyer rollout."

## Objective
Wire the WO-038 Cloud API transport and loopback webhook listener into the plugin entry,
OFF by default, and prove startup, signed delivery, exact replies and shutdown offline and
on the pinned host with synthetic credentials and a fake Graph API, so the owner's live
setup needs only owner-held values, a tunnel and the Meta console.

## Why
WO-038 left the transport staged; the owner chose the credentials file and the separate
loopback listener. The install needs one tested switch that is off unless the owner
turns it on, and that fails closed on every refusal.

## In scope
1. `index.mjs`: the plugin's own config schema (`PLUGIN_CONFIG_SCHEMA`, equal to the
   manifest `configSchema`), `readCloudApiBlock`, `processCloudApi` (one Cloud API
   transport and one listener per process behind a frozen process-wide key, like
   `processIngress`), `hostSafeLogger`, and `createPluginEntry({ transport?, cardResolver?,
   cloudApiDeps? })`. The default export injects nothing.
2. `cloud-api-wiring.mjs`: `createListenerBoundTransport` (the listener's life follows the
   account's newest start) and `LISTENER_START_FAILED_MESSAGE`.
3. `cloud-api-transport.mjs`: log calls can no longer throw (`quietLog`); header comment.
4. `openclaw.plugin.json` (`configSchema`, description), `package.json` (`files` gains the
   two Cloud API modules).
5. Tests: `cloud-api-entry.test.mjs` (new, CE-1 to CE-13), CA-29, and updates to PKG-2,
   FC-single-call-site, CA-22, CW-4 and `tests/test_whatsapp_channel_skeleton.py` (the
   staged-file exceptions are gone; the runtime set equals the entry's import closure).
6. Host harness: mode `cloud-api` (`run.mjs`), the production entry with
   `cloudApiDeps.fetch` faked in `plugin/index.mjs` and the production `cloudApi` schema
   in `plugin/openclaw.plugin.json`, `POST /control/hold` in `fake-model.mjs`,
   `evaluateCloudApi` in `checks.mjs` with HC-8 to HC-12 in `checks.test.mjs`, README.
7. Docs: this work order; runbook section 7 (owner-run steps, smoke test, rollback);
   WO-038 Status cross-reference; README; ADR-0017 wiring note; harness README.

## Out of scope (each held for separate written owner approval)
- every live step: credentials, number registration, the tunnel, the Meta webhook
  subscription, any live send, the five-message smoke test;
- bounded dedupe persistence (a file write; a hard gate before any buyer is allowlisted);
- any change under `scripts/gates`, `scripts/guards`, `.claude/`, `.github/`,
  `.gitignore` or `docs/EVIDENCE_LOG.md`;
- templates, proactive sends, media, groups, read receipts, typing indicators;
- the pre-existing unguarded object log calls inside `channel.mjs` (now safe through the
  entry's logger; a channel built directly with a string-only logger would still throw on
  them).
No network was used beyond 127.0.0.1; no Graph API endpoint was called; no paid call;
synthetic 555 numbers and placeholder ids only. Credentials files exist only at test or
harness time, in a fresh temp directory outside the repo (directory 700, file 600), and are
removed after.

## Interfaces
- Plugin config (`api.pluginConfig`, strict schema): `{}` or `{ cloudApi: { enabled:
  boolean, credentialsFile?: string (absolute, 2-4096), listen?: { host: "127.0.0.1" |
  "::1", port: integer 1024-65535 } } }`. No secret in it.
- `readCloudApiBlock(pluginConfig)`: `{ state: "off" }` unless `cloudApi.enabled === true`
  (the string "true" is off); `{ state: "refused", reason: "bad-config" }` for an enabled
  block with an unknown key, a non-absolute path or a `listen` that is not exactly a
  loopback literal and an unprivileged port; else `{ state: "on", credentialsFile, host,
  port }`. Each key read once; never throws.
- `processCloudApi(block, deps, log)`: on the first call in the process reads the file
  (`deps.readCredentials`, default `readOwnerCredentialsFile`), builds the transport
  over `deps.fetch` (default the global `fetch`) and the listener, and defines
  `Symbol.for("idx-whatsapp-channel.cloud-api.v1")` on `globalThis` (frozen value
  `{ fingerprint, credentialsDigest, sendPath }`, non-writable, non-configurable,
  non-enumerable; the digest is a SHA-256 of the validated values, never a value). Later
  calls, in any module copy, return the same `sendPath` when the file, host and port match
  AND the file, read and checked again on every call, still holds the same values; the
  transport is built once. A changed file is refused `credentials-changed` (review
  finding: the host can re-register a plugin inside a running process on a hot reload,
  SIGUSR1 or `/restart`, and a rotated secret must never stay in force silently; only a
  fresh process picks up new values). The shape and fingerprint of a stored value are
  judged before the file is read. Reasons: `credentials-<reader reason>`,
  `credentials-unreadable`, `credentials-changed`, `no-fetch`, `implausible-credentials`,
  `listener-refused`, `process-state-malformed`, `config-mismatch`. A refusal stores
  nothing.
- `createPluginEntry`: an injected `transport` wins; with none, the send path comes from
  the block (`unavailableTransport` when off or refused, plus one `{ component:
  "idx-whatsapp-channel.entry", event: "cloud-api-refused", reason }` error line). A
  `transport` and `cloudApiDeps` together throw.
- `createListenerBoundTransport({ cloud, listener })`: frozen, exactly the four Transport
  members. `start` hands its options to the Cloud API transport in the same tick (the
  newest start holds the sink), then binds the listener if it is not bound; the newest
  start owns it, and when that start ends (signal abort, refusal, `stop()`) the listener is
  closed and the start settles only once the port is free. An older start ending late
  leaves it alone. A bind failure cancels that start's Cloud API run (its own abort
  controller, joined with the host's signal) and rejects with
  `LISTENER_START_FAILED_MESSAGE` only once that run has stopped and the port is free, so
  until the next start a signed POST is 503 and a send is refused with no Graph API
  request. A failed older start leaves a newer start alone: a newer start waiting on an
  older start's failed bind asks for its own (owner instruction, 2026-11-08).
  A bind that a stop or a newer start's end cancelled is not a failure: that start
  settles with its run as before. A start the Cloud API transport refuses
  (`not-configured`, `no-inbound-sink`, `unknown-account`, all before it takes the sink)
  never takes the listener, so it cannot close or strand the listener of the start that
  still holds the sink; a start that a `stop()` overtook in the same tick never binds.
- `hostSafeLogger(base)`: hands fields to the host logger as given; when the host throws on
  an object, sends the same fields as one JSON line, and JSON lines from then on; never
  throws.

## Real-host findings (OpenClaw 2026.9.5, harness mode `cloud-api`)
1. The plugin logger takes strings only: `api.logger.info({...})` threw `text.includes is
   not a function`. In the first run every webhook answer was 500 (`webhook-error`) and the
   account never became ready. Fixed by `hostSafeLogger` (CE-11, CE-12) and `quietLog` in
   the transport (CA-29).
2. On SIGTERM the harness's foreground gateway drained live work first (`draining active
   work before stop with timeout 315000ms`), so a reply held by the model at SIGTERM was
   still delivered, before the account stopped. An edit under `channels.whatsapp` was
   likewise deferred until live turns ended (`config change requires channel reload
   (whatsapp) — deferring until ... embedded run(s) complete`). The drain budget depends
   on the supervisor (OpenClaw's restart-and-supervision and restart-recovery docs): up to
   315 s in the foreground or under systemd with a long stop timeout, 75 s under
   systemd's default 90 s timeout, and 5 s under launchd on macOS. The harness measured
   the foreground case only. On the owner's macOS LaunchAgent a turn still running about
   5 s after a stop is cut off, so a late reply after the account stops CAN arise there;
   the zero-call rule for that case is proven offline only (CE-8, CL-1, CL-2). The
   harness check R accepts either correct reload outcome and names it.
3. The host accepts the `cloudApi` block under `plugins.entries.<id>.config`, validates
   it against the manifest schema, and registers the plugin from three module copies
   (one `full`, two `discovery`); one transport and one listener served all of them.

## Tests required (all offline, `node --test`)
`cloud-api-entry.test.mjs` (order matters: the process key is absent in CE-1 to CE-5 and
set by CE-6):
- CE-1 the manifest `configSchema` equals `PLUGIN_CONFIG_SCHEMA` and the entry's, the
  harness manifest's `cloudApi` block equals production's; a test-only schema check accepts
  5 good shapes and refuses 14 bad ones (extra keys, a secret, `enabled` as a string or
  missing, a relative path, `localhost`, `0.0.0.0`, ports 443, 0, 70000, "8443", 8443.5,
  a missing port).
- CE-2 off by default: 16 configs (none, `{}`, non-object blocks, `enabled` false, "true",
  1, null, absent, ...) through the default export and an injected entry: unconfigured,
  nothing read or logged, no port, no Graph call, no process key.
- CE-3 an enabled block with a bad shape (13 cases and a throwing getter): one
  `bad-config` line, file never read.
- CE-4 credentials refusals with the real reader (missing, 644, extra key, bad JSON,
  implausible id) and injected readers (a throw carrying a value, a forged reason, a
  reused secret) and a non-function fetch: unconfigured, one fixed-reason line with no
  path or value, `startAccount` rejects, no port, zero Graph calls, nothing stored.
- CE-5 child processes: a pre-seeded malformed value (6 shapes, one without a digest) is
  `process-state-malformed`, a well-formed one for another file or port is
  `config-mismatch`, with the file never read; one for the same block with another digest
  is `credentials-changed` after one read.
- CE-6 enabled: read once, key descriptor frozen (the value holds only the fingerprint,
  a 64-hex digest and the send path), nothing bound before `startAccount`,
  `listener-started`, GET verification 200 with the challenge, another path 404, a signed
  DM runs a real channel turn (card call through both hooks with the committed
  `search-features` payload) and the fake Graph API gets exactly one POST: exact URL,
  bearer, headers, `redirect: "error"`, a signal, body exactly the expected JSON with
  `text.body` equal to the server's approved reply and the renderer's; logs carry no
  peer, text, id, token, secret, path or port; the abort alone frees the port before
  `startAccount` settles.
- CE-7 a later register checks the file again and is accepted; on a running listener: unsigned, tampered, wrong-secret and zero signatures 401
  (three HMAC refusals logged), another number id and a stranger acknowledged; no turn,
  no Graph call, one `sender-not-allowed` drop.
- CE-8 a turn held across an account stop: port freed while held, late reply withheld
  `untrusted-turn`, zero Graph calls; across a reload: old reply zero calls, the listener
  binds again, the new turn exactly one.
- CE-9 two module copies (`index.mjs?copy=ce9`): one `sendPath` built once, each register
  checks the file once (a mismatched block before any read), the copy's own fetch never
  used, the second copy's start takes over without a
  second bind, the first copy's late abort leaves the port open, the newest abort frees
  it; another port is `config-mismatch`.
- CE-10 `createListenerBoundTransport` alone: sink in the same tick, ownership, no bind for
  an aborted start, the fixed bind-failure message, a refused start frees the port,
  construction refusals.
- CE-14 (bind failure, owner instruction 2026-11-08) the real transport and real listener
  on a port another socket holds: the start rejects with the fixed message, and in that
  same tick the signed handler answers 503; a send is `transport-not-running` with zero
  Graph API calls and no inbound reaches the sink; once the port is free a later start binds,
  a signed POST is 200 and one send is exactly one Graph request. Then an older start's bind
  fails while a newer start waits on it: the older start rejects, the newer one binds on
  its own and keeps the sink (signed POST 200, one send) until its own abort.
- CE-15 (bind failure edges, review 2026-11-08) with a fake run that stops 30 ms after
  its abort, the start rejects only after the run has stopped; `stop()` during the bind
  settles the start without the failure message; a newer start ending during the older
  start's bind leaves the older start running; a newer start refused `unknown-account`
  during the older start's bind leaves that bind, the listener and the older run alone;
  `stop()` in the same tick as a start means no bind at all (the real transport); a valid
  and a refused start in the same tick, two refused starts in one tick, and a refused
  start aborted at once each leave the running start's listener and run untouched.
  CE-14 and CE-15 clean up in `finally` and carry a 15 s timeout, so a regression fails
  instead of hanging.
- CE-11 `hostSafeLogger` against a string-only logger, an object logger and broken ones.
- CE-12 child process, string-only host logger (the real-host regression): GET 200, signed
  POST 200, every line a JSON string, `listener-stopped` logged before `startAccount`
  settles.
- CE-13 (after CE-6, both module copies) the credentials file rewritten with a rotated
  app secret, access token or verify token is `credentials-changed`; made 644 or not JSON
  it is refused with its own reason; one fixed line with no value, the stored transport
  unchanged; restoring the original values is accepted again.
`cloud-api.test.mjs` CA-29: a logger that throws changes no answer and no send error.
`host-harness/checks.test.mjs` HC-8 to HC-12: the passing cloud-api record (three sends:
genuine, held, next) passes S, W, G, U, N, R and X; 50 records with one piece missing or
wrong each fail their check, including a `cloud-api-refused` reason at startup or anywhere
in the run's audit log (S); G's 11 send variants fail; R names both held-turn outcomes and
fails a voided turn whose reply went out anyway; HC-12: an extra or duplicate send after
the listener restarted or after the next turn fails R (the whole Graph API log before the
stop must be the genuine, held and next sends), and an untimed send fails X.

## Acceptance
All tests above pass with the existing suite unchanged in behaviour; with no `cloudApi`
block the entry behaves exactly as before; the harness `cloud-api` mode passes twice and
`genuine-only` and `payloads` still pass; the three docs gates pass on every changed path.

## Verification commands
```
cd extensions/idx-whatsapp-channel && node --test
.venv/bin/python -m pytest -q tests/test_whatsapp_channel_skeleton.py tests/test_docstring_lengths.py tests/test_whatsapp_reply_payloads.py
ruff check tests/test_whatsapp_channel_skeleton.py && ruff format --check tests/test_whatsapp_channel_skeleton.py
IDX_HARNESS_ROOT=<scratch> node extensions/idx-whatsapp-channel/host-harness/run.mjs cloud-api cloud-api genuine-only payloads
python scripts/gates/forbidden_paths.py <paths>; python scripts/gates/pii_scan.py <paths>; python scripts/gates/confidential_text.py <paths>
```

## Stop conditions
The host refusing the `cloudApi` block or loading the plugin differently from WO-037's
facts; any need for a real credential, a real number or a network call beyond loopback;
any requirement that would relax a safety invariant.

## Status
2026-11-08, implemented offline on branch `wo-039-cloud-api-wiring` (from main 0a06324).
Nothing installed, configured or enabled outside temporary harness state; no credential,
no Graph API call, no network beyond 127.0.0.1, no paid call; the implementer made no
commit.

Node, `cd extensions/idx-whatsapp-channel && node --test`: 285/285 (`verifier.test.mjs` 37,
`channel.test.mjs` 78, `host.test.mjs` 30, `entry.test.mjs` 11, `allowlist.test.mjs` 11,
`cards.test.mjs` 18, `reply.test.mjs` 25, `host-harness/checks.test.mjs` 13,
`cloud-api.test.mjs` 29, `cloud-api-lifecycle.test.mjs` 10, `cloud-api-wiring.test.mjs` 10,
the new `cloud-api-entry.test.mjs` 13), up from 266. pytest on the three files: 126 passed.
Ruff check and format clean on the one Python file touched.

Mutations in scratch copies, each caught: the entry passing the raw host logger (CE-12);
that plus no transport log guard (CE-12 fails on GET 500; CA-29 fails on the guard alone);
any start's abort stopping the listener (CE-9, CE-10); `enabled` read as truthy (CE-2); no
fingerprint check (CE-5, CE-9); no validation of a pre-seeded value (CE-5); the listener
never bound (CE-6 to CE-10, CE-12); a refusal that throws instead of failing closed (CE-3,
CE-4, CE-5, CE-9).

Review fixes (2026-11-08), each with a regression, each mutation caught: the credentials
file re-checked on every register with a digest compare (`credentials-changed`; dropping
the compare fails CE-5 and CE-13, dropping the re-read fails CE-5, CE-7, CE-9 and CE-13);
harness R accounts for the whole Graph API log before the stop (dropping it fails HC-11
and HC-12; the reviewer's duplicate-after-restart probe on the earlier real-host data now
fails R while the unmodified data passes); harness S refuses any `cloud-api-refused`
reason from the run's audit log (dropping it fails HC-9); runbook, ADR and finding 2 now
state the supervisor-dependent drain (5 s under launchd), the effective allowlist key,
the 30-minute retry window, the fresh-process rule for credential changes, a 7.5 leak grep
built from M1 to M5 and the Cloud API identifiers, and the full removal of the secrets
directory.

Real host (OpenClaw 2026.9.5, sandboxed with `sandbox-exec`, outbound network loopback
only, synthetic credentials, fake Graph API), one command on the final code:
`run.mjs cloud-api cloud-api genuine-only payloads`, exit 0.
- `cloud-api`, run 1 and run 2, each PASS on all nine checks: S (listener-started, port
  accepting, verification GET 200 with the challenge, ready on the first signed probe, no
  `cloud-api-refused` at startup or anywhere in the run's audit log); W (signed DM 200, card call admitted, tool ran once); G (exactly 1
  Graph API request before the reload: URL, bearer, JSON, `redirect: "error"`, signal, and
  a body exactly equal to the expected JSON whose text equals the server-approved reply
  and the renderer's); U (unsigned 401, tampered 401, nothing reached the model, hook or
  tool); N (stranger 200, then 0 model requests, 0 hook calls, 0 Graph requests); R (the
  host deferred the channel restart until the held turn ended:
  `delivered-before-deferred-restart`; the listener stopped and bound again, 0 requests
  while down, the next DM exactly 1 exact request, and all 3 Graph API requests before
  SIGTERM accounted for: genuine, held, next); X (exit code 0 about 4.5 s after
  SIGTERM, `listener-stopped` logged, port released, 0 Graph requests from the SIGTERM
  on); A; I 6/6.
- `genuine-only`: PASS (A, I 2/2). `payloads`: PASS (A, P 58/58: 55 released exactly and 3
  withheld as expected; I 118/118).
The first `cloud-api` run, before `hostSafeLogger`, failed S: every webhook answer was 500
(`webhook-error`, 120 of them) because the host logger threw on object messages. The
second failed X only: the reply held at SIGTERM was delivered during the host's drain,
before the account stopped; the scenario now holds the turn across a channel reload
instead (check R) and stops a quiet gateway (check X). The third failed R only: the host
deferred the reload until the turn ended, which R now accepts and names. Every synthetic
credentials file was removed after its run (none remain under the harness root).

Docs gates from the worktree root on all 22 changed or untracked paths:
`forbidden_paths.py` ok (22 files), `pii_scan.py` ok (10 text files),
`confidential_text.py` ok (10 text files); each exit 0.

Bind failure (owner instruction, 2026-11-08). Before, a listener that failed to bind made
the start reject while its Cloud API run went on holding the sink: a signed POST was 200
and reached the channel with no listener serving. Now the start cancels its own run, waits
for it and for the port, then rejects; a failed older start leaves a newer one alone (the
regressions are CE-14 and CE-15 above). Two adversarial review rounds found five more
defects in the first two versions of this fix, each reproduced and fixed with a
regression: a bind cancelled by `stop()` or by a newer start's end reported as a failure;
and a Cloud API refusal closing or stranding another start's listener (alone, in the same
tick as a valid start, twice in a row, or aborted at once; the first was there before this
change). Mutations in scratch copies, each caught: the pre-fix wiring (CE-14, CE-15); no
wait for the run (CE-15); no own cancel (CE-14, CE-15 time out); no cancelled-bind mark
(CE-15); no early refusal check (CE-15); no stop count (CE-15); no retry for a newer start
(CE-14). Node 287/287 (`cloud-api-entry.test.mjs` 15); pytest on the two WhatsApp files
125 passed. Real host, `run.mjs cloud-api genuine-only default`, exit 0: `cloud-api`
PASS on S, W, G, U, N, R, X, A and I; `genuine-only` PASS; `default` PASS (L, A, B, C, I).

Live setup still requires separate written owner approval, and bounded dedupe persistence
is still required before any buyer is added to the allowlist.
