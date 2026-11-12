# WO-043 — Window plan for the owner-only Cloud API smoke test

**Driver:** agent (runbook prose, owner-check blocks, tests); owner (review, every live step)
**Depends on:** WO-041 (#190, the install PR, stacked on its head 0acf05e); WO-042 (#189,
the disclosure and referral policy that A2 brings live)
**Autonomy level this moves toward:** L1. It plans the owner's window. It installs, enables
and sends nothing, and it records no approval.

## Objective
Turn the verified window plan into runbook text the owner can follow:
- the pre-stage phases and the outage window, with their timing;
- the separate #189 go-live (A2), with its own rollback;
- a 7.6 rollback that confirms the shutdown first and cleans up after stock is verified;
- Cloudflare changes scoped to the webhook hostname.

## Owner planning decisions, 2026-11-11 (quoted verbatim; planning decisions, NOT live approval)
"A. Accept the 3h 15m window. Start rollback when M5 passes or an abort criterion is met, and by T0 + 1h 44m at the latest. Confirm the listener stopped and stop the tunnel before restoring stock. If shutdown is unconfirmed, revoke the Meta token immediately. Finish the remaining cleanup after stock is verified.
B. Use the menu-bar reset once the installed build is confirmed to send no message.
C. Keep #189 and its matching installed policy after stock is restored and verified. If A2 fails, restore the prior checkout, policy and config together.
D. Keep A2 separate so we can verify stock before changing transports. Compare config values locally and report only changed key paths, especially for the allowlist and bindings.
E. Use the tested rollback sequence. The cleanup timing in A is the only change to that sequence.
Keep Cloudflare changes scoped to the webhook hostname and path. List any zone-wide HTTPS setting separately for review."

These shape the plan only. G1, the section 7 live approval, T0, Q2, Q4 and Q6 are not given.
No waiver is recorded.

## In scope
1. Runbook "Window plan" section:
   - pre-stage phases A-0, A-1 and A-3;
   - the named deviation (section 7 setup before section 3);
   - the window T0 to T0+3:15, the latest rollback start T0+1:44, and the checkpoints;
   - the duration table with M/D/E labels.
2. Runbook "A2: #189 go-live" section, owner-run:
   - stop, pull and install.sh with the gateway stopped;
   - a key-path-only config compare as an owner-check block, with pytest;
   - validate, start and verify, then the menu-bar reset, then a 15-minute hold;
   - an A2 rollback restoring checkout, policy and config together.
3. Runbook 7.6 per decision A:
   - fast rollback and listener confirmation, the tunnel stopped, a revoke if unconfirmed;
   - then the tested order;
   - then the cleanup after stock is verified.
4. Decision C noted in the section 4 verify and in 7.6.
5. Cloudflare scoping:
   - a hostname-scoped HTTP to HTTPS redirect rule replaces the zone-wide toggle in 7.3;
   - zone-wide settings are listed separately for owner review;
   - 7.6 removes the rule.

## Out of scope
- Any live step.
- Any change to code, the harness, `scripts/`, CI or the gates.
- Recording any approval, T0 or waiver.
- The existing owner-check blocks, which stay byte-identical.

## Acceptance criteria
- `tests/test_runbook_shell_blocks.py` passes for every bash and sh block, new ones included.
- `tests/test_runbook_owner_checks.py` covers the new compare block: it prints changed key
  paths only, flags the stock-relevant prefixes, and never prints a value.
- The full suite, `node --test` and ruff pass, and CI is green.
- Every Cloudflare dashboard step cites developers.cloudflare.com and is marked TO-CONFIRM.

## Status
2026-11-11, docs and tests only, on branch `wo-043-window-plan`, stacked on
`wo-041-install-readiness` at 0acf05e. Nothing live was run. The harness was not rerun,
because no code changed; A6 at dd848b6 covers the code.

**Runbook 1b, window plan:**
- the decisions quoted, marked planning and not approval;
- the pre-stage phases A-0, A-1 (needs the section 7 approval naming the deviation) and A-3
  at T0 - 0:30;
- the named deviation: section 7 setup before section 3;
- the window T0 to T0 + 3:15, the latest rollback start T0 + 1:44 and the rule "start
  rollback when M5 passes or an abort criterion is met";
- checkpoints at T0 + 0:40, T0 + 1:20 and T0 + 1:24;
- the Part B and Part C duration table with M/D/E labels.

**Runbook 1c, A2, owner-run:**
- Copy the pre-A2 config, `AGENTS.md` and the checkout revision to `$SNAP_A2` first.
  `scripts/openclaw_merge_config.py` on origin/main overwrites `openclaw.json.pre-idx.bak`
  on every run (`shutil.copy2`, lines 57-58).
- Then the order: tabs closed, `gateway stop`, `git pull --ff-only`, install.sh with the
  gateway stopped. The printed follow-ups not to run are `channels login`, `gateway
  restart` / `gateway install` and the `clawhub:` install.
- New owner-check block `a2-compare`:
  - it prints changed key paths only, never a value;
  - it tags `STOCK` under `channels.`, `bindings`, `plugins.`, `gateway.` and `session.`,
    including a whole top-level key added or removed;
  - id-like key segments are redacted.
- Then validate, start, verify, the menu-bar reset (gated on its TO-CONFIRM, decision B)
  and the 15-minute hold.
- The A2 rollback restores checkout (`reset --keep`), policy and config together.
- Timing: start by T0 - 1:05, verified by T0 - 0:49, hold ends by T0 - 0:34.

**Runbook 7.6:**
- the window order (decisions A and E): fast rollback with `rollback confirmed`, the tunnel
  stopped, an immediate token revoke if the shutdown is unconfirmed;
- then full step 4, section 4 and the restore order, then the cleanup after stock is
  verified, with the dedupe store removed only after unsubscribing;
- the merged form marked not used;
- decision C in the section 4 verify and in 7.6;
- the rollback removes the redirect rule; there is no zone setting to undo.

**Runbook 7.3:**
- a host-scoped Single Redirect (wildcard `http://<PUBLIC_HOST>/*` to
  `https://<PUBLIC_HOST>/${1}`, 301, query string kept) replaces the zone-wide toggle, cited
  to developers.cloudflare.com and marked TO-CONFIRM;
- the outside check expects 301;
- a "For owner review, zone-wide settings" list, with none run by default, and the scoped
  steps named.

**Tests:**
- `tests/test_runbook_owner_checks.py` gains a2-compare cases. They cover identical files,
  a cwd-only change, every stock prefix, a redacted group key, a missing copy and JSON5, and
  prove that no value from either file is printed. The test first caught a gap: a whole
  top-level `plugins` key added was not tagged; that is fixed.
- `tests/test_runbook_shell_blocks.py` covers the new bash and sh blocks.
- Results:
  - pytest (`MYSQL_HOST=`): 5667 passed, 131 skipped.
  - `tests/test_runbook_owner_checks.py`: 65 passed.
  - `tests/test_runbook_shell_blocks.py`: 144 passed (46 blocks, each run in 2 shells and
    linted, plus 6 checks; no block skipped).
  - `node --test`: 319/319.
  - ruff: clean.

**Review fixes (2026-11-11, on ad5af1f).** An adversarial review of #191 confirmed 5 minor
findings and 2 nits. All are fixed in one commit, docs and tests only:
1. A2 runs `gateway stop && pull --ff-only && install.sh || echo 'A2: FAILED ...'`. Before
   the compare and any start, the owner checks for no `A2: FAILED`, for `IDX response
   policy installed.` (`unchanged` only if #189's policy was already installed) and that
   `rev-parse HEAD` equals `<A2_MERGE_REV>`. Any failure, and the compare's JSON5 REVIEW
   line, triggers the A2 rollback.
2. B9 expects plain HTTP 301 only, as 7.3 does.
3. The window cleanup and the 1b summary also remove `<CREDENTIALS_FILE_PATH>`,
   `<CONFIG_PATH>` and, if no longer needed, `cert.pem`.
4. 7.3 expects a full-URI wildcard match with a `wildcard_replace` target (Cloudflare's
   settings and operators pages, TO-CONFIRM) instead of `http.host eq` / `not ssl`. The
   plain-HTTP 301 outside check is the check that counts.
5. The a2-compare expected list adds `mcp.servers.idx.command`,
   `mcp.servers.idx_alerts.command` (unless `IDX_PYTHON` is set) and
   `skills.load.extraDirs` for a changed checkout path. Any other line means stop and
   decide.
6. A new fixture key `owner@example.com` proves the `@` redaction: it prints as
   `<redacted-key>` and never raw. Without the `@` branch, the a2 tests fail.
7. 7.3 quotes Cloudflare's actual sentence on proxied traffic.

The existing owner-check blocks are byte-identical; only the new a2-compare REVIEW message
changed. The harness was not rerun, because no code changed.
