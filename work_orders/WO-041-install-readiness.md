# WO-041 — Install readiness for the owner-only Cloud API smoke test (runbook gate G4)

**Driver:** agent (startup assertions, tests, harness, host trace, docs); owner (review and
merge of this PR, and separately every live step of runbook section 7)
**Depends on:** WO-037 (owned channel, real-host harness), WO-038 (Cloud API transport),
WO-039 (Cloud API wiring), WO-040 (persistent dedupe, #187 merged as 7a1fe36)
**Autonomy level this moves toward:** L1: it makes the install PR of the runbook (gate G4)
true. It installs, enables and sends nothing.

## Objective
Close the code and documentation gaps a readiness review of
`docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md` found on main, so that the only things standing
between main and the owner-only WhatsApp Cloud API smoke test are owner approvals and
owner-run live steps.

## In scope
1. Startup assertions (runbook C4), as refusals at `register`, in the existing self-check
   refusal style, each only where the pinned OpenClaw 2026.9.5 plugin API really exposes the
   data (traced read-only in the installed host's `dist/`, cited by file:line and the first
   12 hex characters of the file's sha256):
   - `session.dmScope` is not `per-channel-peer` (and no WhatsApp route binding overrides it);
   - a `CARD_TOOL_HOST_NAMES` entry that `isCardTool` rejects or maps to the wrong base;
   - another plugin claims channel `whatsapp` (runbook C8).
   Where the API does not expose the data, the gap is documented and the manual runbook
   check stays.
2. A fail-before/pass-after unit test for each new refusal, and a harness check where it fits.
3. The stock `@openclaw/whatsapp` plugin present (runbook 3.1, C8): find out, from what is on
   disk outside `~/.openclaw`, whether the harness can run with it installed; if it can, a
   harness mode proving the explicit `plugins.allow` form keeps it out while ours loads and
   delivers, and a trace of channel auto-enable with it present. No network download.
4. Runbook 3.6 (queue mode): an offline trace of `messages.queue.byChannel.whatsapp` and the
   default, written into the runbook with citations, with both options for the owner.
5. Runbook 7.3: the owner's tunnel choice (below) and an owner-run setup block for the named
   tunnel (login, create, route dns, offline checks, run), each command cited to the
   cloudflared 2026.10.7 source or Cloudflare docs and marked TO-CONFIRM on the owner's build;
   the owner-supplied offline-check evidence of 2026-11-10, formats only.
5b. Outage and restore review (coordinator, 2026-11-10): exact R4/R4b/R5b commands with the
   `dmPolicy` guard, the verify order (`gateway status --require-rpc` before a probe), the
   section 2 write-down, stock linked/connected checks and the conditional relink, the
   cloudflared stop, an optional merged rollback (TO-CONFIRM), the no-download condition,
   the macOS respawn window rule, R3's interactive uninstall, the backlog restore order,
   pre-window read-only checks, the `<BOT_NUMBER>` rule, the 7.4 App Mode check and the 7.5
   session-continuity note.
6. Stale docs: runbook gate rows G2-G4, "What is installable today", C3, C5, C10, 3.1, 3.7,
   3b, the section 2 and section 4 key loops, R4/R5, the section 7 preconditions,
   `SMOKE_START`, 7.6 step 6; `docs/STATUS.md`, `docs/ACCEPTANCE_MATRIX.md`, the extension
   README; one append-only `docs/EVIDENCE_LOG.md` entry.

## Out of scope
Installing, enabling or configuring anything on the live gateway; running `openclaw` against
it; reading `~/.openclaw` or `.env`; any credential, number, tunnel, Meta subscription or
send; any paid call. Recording owner decisions other than those given in writing, quoted as
given (listed below); no approval or waiver beyond them. The
brokerage (Q2), MLS/IDX (Q4) and hosted-model (Q6) questions stay pending. No new dependency
or service. No change to `scripts/gates`, `scripts/guards`, `.claude/settings.json`, CI or
`.gitignore`.

## Owner decisions recorded here (written, 2026-11-10 and 2026-11-11; scoped decisions, not waivers)
1. Tunnel: "Tunnel choice: Cloudflare named tunnel." Runbook 7.3 uses a locally managed
   named Cloudflare Tunnel; Tailscale Funnel stays documented as the alternative.
2. G4: "Wait for the install-readiness PR to resolve G4, stock plugin exclusion and queue
   handling." No G4 waiver: this PR has to close G4 (runbook section 1).
3. Stock plugin: "Keep the stock plugin installed while the harness checks whether the
   allowlist excludes it." The harness then found that the allow list alone does NOT exclude
   it (C8). Runbook 3.1 option (b), the allow list plus `openclaw plugins disable whatsapp`,
   was then the agent's PROPOSED route, harness-proven; option (a), the uninstall, the
   alternative. The owner chose (b) on 2026-11-11 (decision 5).
4. Queue: "Leave queue settings alone pending the trace and keep dashboard traffic out of
   the WhatsApp session during the smoke test." Runbook 3.6 makes no config write; 7.5 says
   to send nothing into the WhatsApp session from any other source during the smoke.
5. 2026-11-11, quoted verbatim: "For the owner-only smoke test, use stock exclusion route (b): keep stock installed, disable it explicitly, and apply the allowlist. Use queue option 1 with no dashboard sends into the WhatsApp session. Keep the no-reboot, no-logout rule and skip gateway stop --disable."
   Runbook 3.1 option (b) is the chosen route for the owner-only smoke test, and (a) stays
   the documented alternative. Runbook 3.6 option 1 is chosen: no queue config write, and
   nothing is sent from the dashboard into the WhatsApp session. The no-reboot, no-logout
   window rule stays, and `gateway stop --disable` is skipped.
No other approval or waiver is recorded. G1, the section 7 live approval, Q2, Q4 and Q6 stay
pending, and so do the other WO-038 owner items.

## Acceptance criteria
- Each assertion the API supports refuses registration (`refusing to register: <reason>`)
  with a unit test that fails on main and passes here; each one it cannot support is named as
  a gap with its citation, and the manual runbook check is kept.
- `README.md` and `constants.mjs` claim only assertions that exist.
- Harness A1 at the final head, every mode passing:
  `genuine-only not-allowlisted default steer followup collect interrupt-roles payloads
  cloud-api cloud-api-rollback cloud-api-restart` plus any new mode.
- The runbook's owner-check blocks are byte-identical (`tests/test_runbook_owner_checks.py`
  and harness check O still pass); the DRAFT/PAUSED header stays.
- pytest (`MYSQL_HOST=`), ruff check, ruff format --check and `node --test` pass; CI green.
- Nothing live is done.

## Stop conditions
Any need for a network download, a real number or id, a credential or a paid call; a host
behaviour that differs from what the harness assumes; a change that would relax a safety
invariant.

## Status
2026-11-10, implemented offline on branch `wo-041-install-readiness` (from main 7a1fe36). PR
open for owner review; not merged. Nothing was installed, enabled or configured on the live
gateway. `openclaw` ran only inside the sandboxed harness and its temporary state. Nothing
was read under `~/.openclaw` or any `.env`. No credential, no paid call, no send; synthetic
data with 555 numbers only.

C4, startup assertions (`self-check.mjs`, refusals at `register`):
- `dm-scope-not-per-channel-peer`: the root `session.dmScope` must be exactly
  `per-channel-peer`, and no WhatsApp route binding may override it
  (`dist/resolve-route-C3fi9e8K.mjs:302,331,392` [218c186c0a82];
  `dist/bindings-CI-O7TMQ.mjs:2-19` [8db80c9c9fec]). `api.config` is the whole root config,
  after auto-enable (`dist/loader-runtime-load-CdQ5OcQq.mjs:1208-1213` [91180d699f64];
  `dist/server-plugin-bootstrap-DsdH1fKq.mjs:24-47` [f1c13ecd94cf]).
- `card-tool-host-names-invalid`: each `CARD_TOOL_HOST_NAMES` pin must be the literal
  `idx__<tool>`, within 64 characters, accepted by `isCardTool` and mapped to its own base.
  The `api` has no tool list at register (`dist/setup-registry-C0Jco-hC.mjs:373-396`
  [7146e121eb5a]), so the pins are checked statically, and harness check T checks them
  against the names the host really presents (every mode).
- Not implemented, documented as a gap: "no other plugin claims channel `whatsapp`". The API
  exposes no plugin or channel-owner list at register, and `registerChannel` returns nothing
  on a conflict, which the host only logs (`dist/loader-runtime-load-CdQ5OcQq.mjs:2938-2995`).
  The manual runbook check stays (3.1, 3.7).
- Tests: HW-10 and HW-11 (`entry.test.mjs`), HC-18 (T) and HC-19 (Z) (`host-harness/checks.test.mjs`).
  Fail before, pass after: a probe of the two refusals, run against a copy of main
  7a1fe36, failed 5 of 6 (the five refusals; the good config registers) and passes 6 of 6
  here. Every test config now sets `session.dmScope`.

C8 and 3.1, the stock plugin present. The stock `@openclaw/whatsapp` 2026.9.5 package was not
in the openclaw npm install (no `dist/extensions/whatsapp`, nothing under
`node_modules/@openclaw` but `ai`, `fs-safe`, `fs-safe-darwin-arm64` and `proxyline`). Its
tarball was on disk in the local npm cache (22,377,771 bytes, sha512 equal to the registry
integrity), so nothing was downloaded. A managed archive install of it runs `npm install`,
which failed offline in the sandbox (`ENOTCACHED`), so the harness link-installs the extracted
copy, which ships its dependencies. New mode `stock-present`, check Z:
- the install added `whatsapp` to `plugins.allow` and set `plugins.entries.whatsapp.enabled:
  true`;
- phase 1, with the allow list set back without `whatsapp` and the entry left enabled: the
  host logged "auto-enabled plugins for this runtime without writing config: - whatsapp plugin
  config present, added to plugin allowlist." Both registers of ours saw `whatsapp` in the
  effective allow list and refused `stock-whatsapp-not-denied`, and the stock plugin loaded;
- after `openclaw plugins disable whatsapp`, phase 2: both registers saw neither, ours
  registered and its channel started, the stock plugin was never loaded, no ownership
  conflict was logged, and the genuine card was delivered (A, I, T).
Trace: `dist/plugin-auto-enable.materialize-IpOcPSgc.mjs:161-176,197-235,283-303,316-382`
[22f0fa98fbdd]; `dist/config-normalization-shared-Btqp-2KT.mjs:38-118` [e9ea9129fdff].

3.6, queue. Traced offline: the mode is the turn's inline mode, then the session's `/queue`,
then `messages.queue.byChannel.<Provider>`, then `messages.queue.mode`, then `steer`
(`dist/settings-GfUY60zL.mjs:443-457` [f4e0965d3d1c]). `byChannel` keys on the message's
`Provider` (`dist/get-reply-DN4OcavF.mjs:3398-3406` [ddacdea4bc3e]), and the dashboard's is
`webchat` (`dist/operator-role-policy-CQ0LLlEF.mjs:67-73` [ad2d89613e59]). So
`byChannel.whatsapp` would change nothing for this channel. Both options are in the runbook;
none is chosen.

Owner-supplied tunnel evidence (2026-11-10, formats only, offline, not an approval):
`cloudflared` 2026.10.7 installed by Homebrew on the gateway host. The 7.3 offline checks were
run against a placeholder config: `ingress validate` OK, exit 0; the webhook URL `Matched
rule #0` (0-based on this build); all eight negative variants `Matched rule #1` /
`http_status:404`; the two encoded variants and the query variant `Matched rule #0`. The
checks against the real config are pending, after the tunnel is created under the section 7
approval.

Verification, run before the commit: pytest (`MYSQL_HOST=`) 5478 passed, 131 skipped;
`ruff check` clean; `ruff format --check` 482 files formatted; `node --test` 319/319; the
runbook's owner-check blocks are byte-identical to main's. Gates run per file on every
changed path: forbidden_paths, pii_scan and confidential_text each ok.

Harness A1 (OpenClaw 2026.9.5, sandboxed; the tree of this PR's commit, apart from this
Status section and the EVIDENCE_LOG entry), `run.mjs genuine-only not-allowlisted default
steer followup collect interrupt-roles payloads cloud-api cloud-api-rollback
cloud-api-restart stock-present`, exit 0, every mode PASS:
- `genuine-only`: A, I 2/2, T;
- `not-allowlisted`: A, D, I, T;
- `default`, `steer`, `followup`, `collect`: L, A, B (`hook-refused`), C, I, T each;
- `interrupt-roles`: L, A, B (`host-rejected`), C, I, T;
- `payloads`: A, P (55 released exactly, 3 withheld as expected), I 118/118, T (all four
  card tools admitted);
- `cloud-api`: S, W, G, U, N, R, X, A, I 6/6, T, K, O;
- `cloud-api-rollback`: H, F, V, A, I, T, K, O;
- `cloud-api-restart`: E, A, I, T, K;
- `stock-present`: Z, A, I, T.
No dashboard model request carried the reply instruction, in any mode.

Owner decisions (above) are recorded as given. Still open for the owner: G1, the section 7
written approval, Q2/Q4/Q6 and the other WO-038 items, the 3.6 option, every TO-CONFIRM on
the owner's build, and merging this PR (G4).

2026-11-10, review fixes, new commits on 1e6b1cb (no amend, no force push). An adversarial
review of #190 (coordinator) confirmed the items below, and each was checked against the
pinned host before it was fixed. Two critic items were verified here first; both were real.
- Correction: the earlier text of this order, the runbook and the EVIDENCE_LOG entry
  recorded 3.1 option (b) as the owner's chosen route. It is not. The owner wrote only the
  sentence quoted in decision 3, and the harness then disproved its premise. (b) is the
  agent's PROPOSED route, harness-proven and awaiting the owner's written decision; (a)
  stays the alternative. The out-of-scope line now matches the four quoted decisions.
- R3 `plugins uninstall idx-whatsapp-channel` deletes the whole `channels.whatsapp` block,
  because the uninstall removes the config of every channel the manifest declares
  (`dist/uninstall-config-CBhuoZUg.mjs:99-105` [46b48ecb370b]). R5b now restores the whole
  recorded block in one `--expect-current-absent` write, with the dmPolicy guard. 3.1 (a)
  says the stock uninstall does the same.
- R6: with the gateway stopped, `plugins enable whatsapp` is refused "blocked by
  allowlist" when the allow list is set without `whatsapp`
  (`dist/management-mutations-DfooQCya.mjs:170,201` [df08dd50fd50];
  `dist/enable--azUUNOl.mjs:90` [eff28c91a912]). R6 now has two forms:
  - the recorded list names `whatsapp` (or is unset): `plugins enable whatsapp`;
  - the recorded list omits it: `config set plugins.entries.whatsapp.enabled true
    --strict-json --expect-current-json false`.
  Either form is followed by a read-back. Section 2 now records whether the list names
  `whatsapp`, and the exact stock entry.
- 3.1 (b) is now in the harness's order: `plugins disable whatsapp`, then the list read
  back (the disable rewrites it in normalized form,
  `dist/config-normalization-shared-Btqp-2KT.mjs:163-166`), then the conditional write
  expecting that read-back. A recovery note covers a refused write.
- Auto-enable log. Critic item, real: the host logs a header line and then untimed
  `- <change>` lines (`dist/server-startup-config-DPBDTuFJ.mjs:104`). This was seen in the
  pinned host's `openclaw logs --plain` output. The 3.7 check is now an owner-check block
  (`auto-enable`), run verbatim by the harness and in `tests/test_runbook_owner_checks.py`.
- Restart recovery. Critic item, real: `docs/gateway/restart-recovery.md:25-26` says
  accepted Control UI inputs are re-admitted on reconnect and interrupted turns are
  resumed. A new window rule says: close dashboard tabs before every stop, and watch the
  log after every start.
- 3.6: the busy gate sees only this channel's own turns, but the host decides queueing per
  session (`get-reply:3480-3502`). A WhatsApp message into a live dashboard run on that
  session is steered, or queued when the tool authority differs (`agent-runner:8004-8008`).
  The 7.5 rule protects the smoke test in both directions.
- 7.3: the owner must authorize the zone that holds `<PUBLIC_HOST>`, because `route dns`
  writes into the cert's zone (cloudflared `origin_cert.go` L23, `credentials.go` L51-55,
  `cfapi/hostname.go` L178-180; TO-CONFIRM). The printed CNAME name must equal
  `<PUBLIC_HOST>`, and 7.6 deletes the record by that printed name.
- Other corrections: the fast-rollback text and an abort criterion (the allow list does not
  keep stock out); README queue text (traced); constants.mjs credits check T, not A; the
  harness README.
- Harness, the stock modes:
  - New mode `stock-present-allowlisted` (the recorded allow list names `whatsapp`) next to
    `stock-present` (it does not).
  - Each mode builds the owner's pre-install snapshot, then runs phase 1 (allow list alone:
    refused, stock loaded, owner check flagged) and 3.1 (b) in the runbook's order.
  - Phase 2: ours alone, owner check `auto-enable: clean`.
  - Phase 3: the section 4 rollback in its real order (R3, R4, R5b, R6, read-backs,
    validate) and a fresh gateway.
  - Check Z covers all phases (HC-19); `tests/test_runbook_owner_checks.py` gains two tests
    for the auto-enable block.

Verification of the fixes: pytest (`MYSQL_HOST=`) 5486 passed, 131 skipped; ruff clean;
`node --test` 319/319; owner-check blocks `smoke-log` and `rollback` byte-identical to main
(the new `auto-enable` block is added).

Harness A2, an earlier run, before the 9abb35f commit: it ran on that commit's tree minus
this Status text and the EVIDENCE_LOG entry. Command: `run.mjs genuine-only
not-allowlisted default steer followup collect interrupt-roles payloads cloud-api
cloud-api-rollback cloud-api-restart stock-present stock-present-allowlisted`. Exit 1:
- every mode PASS except `steer`, which failed at startup: the channel did not start within
  60 s. The gateway log shows 24 s between "starting..." and "starting HTTP server...". An
  `uptime` taken minutes later showed load averages of 9 to 13 from other work on the
  machine. The mode made no model request and no check ran on evidence. A rerun of `steer`
  alone passed L, A, B (`hook-refused`), C, I and T.
- `stock-present`: Z with every phase passing (setup, phase 1, 3.1 (b), phase 2, rollback,
  phase 3), plus A, I and T.
  - Rollback steps: R3 disable 0, R3 uninstall 0, R4 0, R5b 0, R6 entry write 0, validate 0.
  - `channels.whatsapp` was deleted by R3 and is equal to the snapshot afterwards; dmPolicy
    read back `"allowlist"`; the allow list is equal to the snapshot; the entry read back
    true.
  - `plugins enable whatsapp` was refused "blocked by allowlist" (exit 1, entry left false).
  - Phase 3: the stock plugin loaded, ours did not, and ours had no register.
- `stock-present-allowlisted`: the same, with R6 `plugins enable whatsapp` exit 0.
- the other modes as in A1: `payloads` P 55 released and 3 withheld, I 118/118; every
  dashboard request had no instruction.
Still open for the owner, in addition: confirm 3.1 option (b), including `plugins disable
whatsapp`, or choose (a).

Harness A3, at exactly 9abb35f with a clean tree (OpenClaw 2026.9.5, sandboxed), the same
13 modes, exit 0, every mode PASS:
- `genuine-only`: A, I 2/2, T;
- `not-allowlisted`: A, D, I, T;
- `default`, `steer`, `followup`, `collect`: L, A, B (`hook-refused`), C, I, T each;
- `interrupt-roles`: L, A, B (`host-rejected`), C, I, T;
- `payloads`: A, P (55 released, 3 withheld), I 118/118, T;
- `cloud-api`: S, W, G, U, N, R, X, A, I 6/6, T, K, O;
- `cloud-api-rollback`: H, F, V, A, I 4/4, T, K, O;
- `cloud-api-restart`: E, A, I 4/4, T, K;
- `stock-present`: Z (every phase; R6 by entry write after `plugins enable` was refused
  "blocked by allowlist"), A, I, T;
- `stock-present-allowlisted`: Z (every phase; R6 `plugins enable whatsapp` exit 0), A, I, T.
CI at 9abb35f (push and pull_request): commit gates pass, lint and tests pass; pytest 5536
passed, 74 skipped. Local before the commit: 5486 passed, 131 skipped; node 319/319.

2026-11-10, second review round (re-review of 9abb35f, coordinator; every item confirmed
against the pinned host and fixed in one new commit):
- 3.7 START_CHECK: a stamp taken after `gateway start` hid the stock header and printed a
  false `auto-enable: clean`. The stamp is now in the 3.7 block, before the start (`;
  sleep 1`), and the owner check fails closed: it prints `not checked` unless a `gateway
  starting...` line is stamped at or after START_CHECK. New pytest case.
- gateway.auth is redacted in the snapshot: `config get` writes `__OPENCLAW_REDACTED__`
  for token and password, which only the gateway's RPC write path restores
  (`dist/redact-snapshot-BOWMnozc.mjs:86-91` [f1477491f2d6]). R4b now restores only the
  sub-keys 3.6b changed, one by one, never gateway.auth as a whole and never a secret. A
  `grep -l __OPENCLAW_REDACTED__` line marks files that must not be fed to `config set`.
- Authored versus runtime view: `config get` prints the defaulted runtime view
  (`dist/config-cli-C89Y1yYt.mjs:94-96` [5cba26048ad9]). New owner-check block
  `authored-snapshot` reads `channels.whatsapp` from the config file with python3 and no
  `openclaw` call, into `$SNAP/channels.whatsapp.authored.json`. It refuses JSON5, a missing
  block and `$include` (pytest cases). R5b and the verify use it. The harness runs the same
  block, with an authored block that has no `groupPolicy` or `mediaMaxMb` and has an account
  with a `~` authDir. On the pinned host `config get` showed a different view, with
  defaults added.
- Section 2 loop: stdout only, a branch on the exit status, stderr into `.err`, exactly one
  of `.json` and `.unset` per key (the failure envelope moves to `.failed`).
- R3 to R4: `config get plugins.allow --json` labelled ALLOW_JSON_AFTER_R3, fed to R4, with
  the refusal and read-back note.
- Account-level allowFrom: R5b cuts the root list and each `accounts.<id>.allowFrom` to the
  owner. The restore order writes each recorded list back with its own paired
  `--expect-current-json '["<OWNER_E164>"]'` command, before one restart. Harness-run.
- Dashboard rule narrowed to the stops. After the start and the one-minute watch, one
  read-only tab may be opened for S3 and M3, and must be closed before the next stop. The
  rule ends when the smoke passes with no rollback, or when the restore is verified.
- The merged 7.6 rollback now includes the section 4 restore order before step 5 and the
  verify.
- Records: A2 relabelled as the earlier run with its steer failure, A3 added, the G2 row
  points here and to the PR for the merge head.
The harness run at this commit's own head is reported in PR #190; this Status cannot name
its own commit.

Harness A4, at exactly b1de88d with a clean tree: all 13 modes passed, exit 0 (the same
checks as A3). CI at b1de88d: pytest 5542 passed, 74 skipped. In both stock modes, R5b and
the restore order (root and `accounts.default` allowFrom) passed, and the final authored
block equals the snapshot.

2026-11-10, third review round (final check of b1de88d, coordinator; four items confirmed,
fixed in one new commit):
- Interactive zsh. macOS's default interactive zsh does not treat `#` as a comment, so
  pasted trailing comments reached commands as arguments, and the R6 comment's `; exit 0`
  closed the owner's terminal.
  - The runbook now says, at the top and in sections 2, 3, 4 and 7, to run every block in
    one `bash` shell kept open.
  - No command line in a bash or sh block carries a comment. 102 annotations moved to
    lines of their own, stripped of `; ' " ( ) < > $ * ! ? |` and backticks. The cloudflared
    and offline-check expected outputs moved to `text` blocks.
  - The owner-check blocks had no comments and are unchanged (`smoke-log` and `rollback`
    are byte-identical to main).
  - New `tests/test_runbook_shell_blocks.py` feeds every bash and sh block (38) to `zsh -f
    -i` and to `bash` with stub `openclaw`, `cloudflared`, `python3`, `curl`, `launchctl`,
    `crontab`, `tailscale`, `sudo` and an editor on PATH. The stubs record argc and words.
    The test asserts that no stub got a `#` word and that each shell reached the block's
    end. No block is skipped. A control case shows the pre-fix R6 line fails it.
  - Against b1de88d's runbook, 15 blocks fail under `zsh -f -i`; all pass under bash.
  - The owner-check tests now also run under `zsh -f -i`.
- `gateway.auth.mode`: any CLI write to it deletes the other modes' credentials. Mode
  `token` deletes the password, `password` deletes the token, and `trusted-proxy` deletes
  both (`dist/config-cli-runner-CBXweqWm.mjs:221-240,382` [4fb01f709751]). 3.6b and R4b say
  so. If 3.6b changed the mode, the token or password comes back from the section 2
  archive before `gateway start`, then the verify runs.
- Group access during the watch. R5b now also cuts each `groupAllowFrom` (root and every
  account) to the owner, and writes `groupPolicy: "disabled"` at the root and in each
  account that has its own (`docs/channels/whatsapp.md:290-292`: `open` bypasses the sender
  lists, and an unset `groupAllowFrom` falls back to `allowFrom`). The restore order has the
  paired `--expect-current-json` writes, plus an `unset` for a root `groupPolicy` the
  snapshot lacks. Section 2 records `groupAllowFrom` and `groups`.
- 3.2 and accounts:
  - Each recorded `accounts.<id>.allowFrom` is set to the owner, and an account's own
    `dmPolicy` to `"allowlist"`, each `--expect-current-json` the recorded value. Our
    channel reads the account list first (`allowlist.mjs`).
  - The section 2 stop rule covers every account's `dmPolicy`.
  - 3.7 reads back `accounts.default.allowFrom`.
  - The harness now runs the runbook's per-key 3.2 commands (unset the rejected keys, root
    and account writes) instead of a whole-block write. Z requires the account read-back to
    be owner-only and the result to be exactly the accepted keys. The harness authored block
    gains `groupAllowFrom` at the root and in the account, plus an account `dmPolicy` and
    `groupPolicy`.

Verification of this round:
- pytest (`MYSQL_HOST=`): 5583 passed, 131 skipped.
- `tests/test_runbook_owner_checks.py`: 45 passed, now also under `zsh -f -i`.
- `tests/test_runbook_shell_blocks.py`: 80 passed (38 blocks times 2 shells, plus 4 checks;
  no block skipped). Corrected in the fourth round: this line first said 81 and 5 checks,
  counting `test_docstring_lengths.py`, which ran in the same command.
- ruff: clean.
- `node --test`: 319/319.
- Harness stock modes on this code: Z with the per-key 3.2 and the group cut and restore.
2026-11-10, fourth review round (final check of 88803e1, coordinator; two minor items
confirmed, fixed in one small commit). Harness A5 at exactly 88803e1 with a clean tree had
passed 13 of 13 modes, exit 0, and CI at 88803e1 passed 5583 with 75 skipped.
- R4b secret recovery used the whole-file restore, which would undo R5b's owner-only cut and
  skip the watch. Now:
  - R4c restores one leaf only, after every R4b line, since a later mode write would prune it
    again. `backup restore` goes into a fresh `$SNAP/restored`, never copied over the live
    config.
  - A new owner-check block, `auth-secret`, writes only `gateway.auth.token` or `.password`
    from the restored copy, through `openclaw config patch --stdin`
    (`dist/config-cli-C89Y1yYt.mjs:256`; `config set` takes values in argv only), so the value
    never appears in a command line, the process list or the terminal. `config patch` has no
    expectation flags, so the block writes only when the leaf is unset now, and it prints a
    REVIEW line otherwise.
  - On the pinned host `backup restore` accepted an `--only-config` archive. The
    TO-CONFIRM stays for the owner's build: if it refuses there, the owner sets a new token.
  - The section 4 last-resort paragraph now says to write R5b's cut again after any
    whole-file copy.
  - Harness, both stock modes:
    - a 3.6b switch to `trusted-proxy` pruned the token (the host logged the removal);
    - R4b wrote the mode back and unset `trustedProxy`;
    - R4c restored the archive and the block printed `secret: restored gateway.auth.token`;
    - the file's token equals the original, the value appears in no output, and
      `channels.whatsapp` was still absent before R5b, so R5b's cut stayed intact (no
      whole-file copy).
  - pytest covers the block in four shells and `zsh -f -i`: only the leaf is patched, never
    printed, and nothing is written when the leaf is set, the copy is missing, the leaf is
    absent, or `AUTH_SECRET` is wrong.
- Shell-block test strength:
  - The dynamic test now fails on stderr matching `parse error`, `no matches found`,
    `invalid mode`, `bad pattern` or `command not found`, except `command not found: #`,
    which is a comment-only line in zsh -i and harmless.
  - A static lint over every bash and sh block fails on an unquoted ` #` after a command,
    and on a comment-only line holding `& ; | ( ) [ ] * ? < > ' " $ !`, a backtick or a
    trailing backslash.
  - `ls`, `grep`, `rm`, `rmdir`, `mv`, `mkdir`, `chmod`, `sleep`, `cat` and `date` are now
    argv-recording wrappers that exec the real binary; each call is one write, so pipe ends
    do not interleave.
  - The reviewer's mutations M1 to M9, each applied alone to the runbook, are all caught. M7
    (a comment line ending in a backslash) is caught by the lint only, since zsh silently
    joins the lines. Each of the other eight is caught by the lint and by the `zsh -f -i`
    run.
  - The runbook's top note now names `tests/test_runbook_shell_blocks.py` for the per-block
    guarantee.
  - The round-3 count is corrected above: 80, not 81.

Verification of this round:
- pytest (`MYSQL_HOST=`): 5642 passed, 131 skipped.
  - The first full run had one failure, `test_chart_delivery.py::...[sigint]`, a file this
    work order does not touch. It then passed 3 times alone, and a second full run passed.
- `tests/test_runbook_owner_checks.py`: 55 passed.
- `tests/test_runbook_shell_blocks.py`: 129 passed. That is 41 blocks, each run in 2 shells
  and linted (123 tests), plus 6 checks; no block skipped.
- ruff: clean.
- `node --test`: 319/319.
- Harness stock-present on this code: Z with the R4b and R4c secret leaf restore.
The harness run at this commit's own head is reported in PR #190.

2026-11-11, owner decision 5 recorded (docs only, one commit on dd848b6). The decision, quoted
in the owner decisions above, chooses runbook 3.1 option (b) for the owner-only smoke test and
3.6 option 1 (no config write; no dashboard sends into the WhatsApp session). It keeps the
no-reboot, no-logout rule and skips `gateway stop --disable`; the runbook marks these as owner
decisions of that date. Shell blocks and owner-check blocks are unchanged. Still open for the
owner: G1, the section 7 written approval, Q2, Q4 and Q6 and the other WO-038 items, every
TO-CONFIRM on the owner's build, and merging this PR (G4).

2026-11-11, merged: #190 merged into `main` as `fb3293f` on green CI, which supersedes the open, not-merged state recorded above; runbook G4 is met, and G1, the section 7 approval, T0, Q2, Q4 and Q6 stay pending ([STATUS](../docs/STATUS.md#where-we-are-now)).
