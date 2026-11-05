# WO-030 — Bounded analysis, phase 2: chart delivery to the chat

**Driver:** agent (owner flips the switch, installs, restarts and runs the live check)
**Depends on:** WO-027 (PR #146: opt-in `bounded_analysis`, text-whole chart caption),
WO-017 Phase C (PNG checks, worker), WO-007/WO-027 install precedent
**Estimated effort:** one PR, a small commit series

## Objective
Get a drawn chart to the user's WhatsApp chat, as the owner requires, without giving the
agent a messaging tool, arbitrary file access or a public URL, and without making the
answer depend on the image. Off by default behind `IDX_CHART_DELIVERY`.

## Why
WO-027 found that OpenClaw 2026.9.5 hands an MCP image block to the model only, so the
chart never reaches the chat; it made the text whole and left delivery as an owner
decision. The owner decided: charts must actually be delivered; the text-only fallback
stays but does not complete the requirement.

## Inputs
- The installed OpenClaw 2026.9.5 and its WhatsApp plugin, read only (never run): MCP
  content projection, tool-result media trust, reply MEDIA parsing, outbound media
  roots and read policy, WhatsApp media send and failure handling. The live config read
  for tool-policy key names and values only.
- `src/idx_agent/analysis/tool.py`, `png.py`, `mcp_result.py`,
  `src/idx_agent/mcp_server/server.py` (`bounded_analysis`), `skills/bounded-analysis/`,
  `scripts/install.sh`, `config/openclaw.idx.json5`, `docs/RELEASE_WO017_ANALYSIS.md`

## In scope
1. The proposal with evidence, threat model, chosen path and rejected alternatives:
   `docs/CHART_DELIVERY.md`.
2. Repository side of the chosen path, behind `IDX_CHART_DELIVERY` (exactly `1`, and only
   with `IDX_ANALYSIS_TOOL=1`): a chart writer into one dedicated directory, PNG and size
   checks, retention of our own files only, one file and one MEDIA line per request,
   failure text and logging, the skill rule for the MEDIA line, and a read-only state
   report in `install.sh`.
3. Offline tests with a temp directory as the sink and the WO-027 fake docker worker;
   install tests against temp HOME/state dirs.
4. Operator activation and the one-shot live trial (D5), written, not run: enable, one
   trial turn, record the observed result, roll back at once (pass or fail, without
   waiting for the owner's reply), verify analysis and chart delivery are off, write
   the record. `scripts/chart_trial_rollback.sh` runs the rollback and the
   verification and prints the record; keeping delivery enabled is a separate, later
   owner approval (docs/CHART_DELIVERY.md section 7, step 9).

## Out of scope
- Any OpenClaw config or tool-policy change, enabling the `message` tool, a public or
  tunnelled URL, an OpenClaw plugin.
- Running `install.sh` against the real home, any `openclaw` command, a gateway restart,
  sending anything, a paid model call or the `local` eval suite.
- Changing WO-027's off-path behavior, server instructions, tool or skill descriptions
  (routing pins), the 50-row boundary or caveats.
- Gates, guards, CI, `.gitignore`, `.claude/settings.json`; `docs/STATUS.md`,
  `docs/START_HERE.md`, `docs/CAPABILITY_ROADMAP.md`, `docs/EVIDENCE_LOG.md` (owned by #143).

## Files expected to change
`src/idx_agent/analysis/delivery.py` (new), `src/idx_agent/mcp_server/server.py`,
`src/idx_agent/db/pool.py` (allowlist), `.env.example`, `skills/bounded-analysis/SKILL.md`,
`scripts/install.sh`, `scripts/chart_trial_rollback.sh` (new), `scripts/README.md`,
`tests/test_chart_delivery.py` (new), `tests/test_chart_trial_rollback.py` (new),
`docs/CHART_DELIVERY.md` (new), this file.

## Interfaces and contracts
`docs/CHART_DELIVERY.md` section 6.

## Implementation requirements
1. Switch unset or anything but exactly `1`: `bounded_analysis` returns WO-027's result
   byte for byte (image block to the model, WO-027 caption), and nothing is written.
2. On: no image block; the PNG passes `png_size` (signature, CRCs, allowed chunks, RGBA,
   exact inflate, 200-2000 by 150-1500 px) and the 512 KiB cap before anything touches
   the disk; it is written once under a 128-bit random name into a directory whose last
   part is `idx-charts`, inside an existing parent, never through a symlink, mode 700,
   files mode 600, `O_EXCL|O_NOFOLLOW`.
3. The message ends with one standalone `MEDIA:<absolute path>` line; the caption says the
   chart follows in the chat and that the figures stand without it.
4. Any failure states itself in the message, in `data.chart.delivery`, and in one log
   line with a fixed reason code and no path; the figures and caveats stay.
5. Retention touches only our exact file names, only regular files: TTL 300 s, at most
   20 files across all server processes (admission under one `flock` on
   `.idx-charts.lock`, bounded wait, else `dir_busy`), prune at start and before every write, superseded charts of this process
   after 120 s, and an operator prune command. Expiry does not wait for those sweeps:
   while the server lives each chart is removed at its deadline with no further
   request; a clean exit removes the process's charts; the documents claim no more
   than is proven (docs/CHART_DELIVERY.md section 5a).
6. No OpenClaw config change; `install.sh` renders and merges nothing for charts.

## Safety requirements
No relaxed invariant. The model still supplies only place arguments and Python; it
supplies no path (the server chooses the path; the model only repeats the line). The
agent gains no tool and no permission. Only server-generated files in one directory are
ever named. Runtime retention deletes only files this feature generated; the agent
deletes no tracked file, data or artifact. No secrets read or printed.

## Tests required
Switch values; directory setting validation; writer (name, modes, no temp left,
fresh tokens, no reuse); refusals (no image, wrong magic, truncated, too wide, too tall,
too narrow, too large, lower cap); missing workspace not created; symlinked directory
refused; mode tightened; retention (TTL, max files, temp files, everything, others'
files, symlinks and subdirectories untouched); the cap across concurrent OS processes,
the bounded lock wait and the lock file's safety; supersede after grace; result shape on
success, on each failure, and untouched without a drawn chart; logging without a path;
over a real MCP session: default off identical to WO-027, on (no image, file equals the
PNG, 50 rows, caveats), one file and line per request, two concurrent sessions isolated,
invalid render writes nothing, bad directory fails visibly, no registration without the
analysis switch, instructions and tool description unchanged, rollback; skill rule;
install with delivery on (config identical, report printed), inert, bad directory, off.

## Acceptance criteria
- `ruff check .` and `ruff format --check .` pass; the offline suite passes; CI is green.
- Routing pins unchanged.
- The PR states: built and tested offline, off by default, not installed, WhatsApp
  delivery unverified.
- Live: the one-shot trial in `docs/CHART_DELIVERY.md` section 7 passes on the owner's
  phone, is rolled back at once with `ROLLBACK DONE`, and is recorded (owner step).

## Verification commands
```sh
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_chart_delivery.py
```

## Deliverables
An off-by-default chart delivery path whose activation, one-shot live trial, immediate
rollback, off verification and record are in `docs/CHART_DELIVERY.md` section 7.

## Stop conditions
Delivery would need a broader tool, a public URL, wider file access or an OpenClaw
config change the owner has not approved; the live check shows OpenClaw ignoring the
MEDIA line.

## Status

2026-11-04 (follow-up 2 on the same branch, wo-030-armed-trial-cleanup; main 71fb39e
already merged, so the merge was a no-op): still off, not installed, not activated;
**the live chart trial and every paid turn stay paused.** **Actual WhatsApp delivery:
UNVERIFIED.**

- Owner (verbatim): "For the watchdog, demonstrate that the reply signal comes from the
  actual authorized trial—not a simulated or manually supplied acknowledgement. Also
  test that late activation cannot re-enable anything after timeout-triggered
  rollback. Keep all paid turns and chart activation paused."
- Signed trial signal. `arm` creates a random trial id and a 256-bit key in
  `<run>/trial.key` (mode 600, 700 run dir; never printed). Step 1 is now
  `scripts/chart_trial_armed.sh enable <run>`: `.env` `IDX_CHART_DELIVERY=1` and
  `IDX_CHART_TRIAL_FILE=<run>/trial.key` (the path only). The server reads that setting
  from `.env` only, at start, only when chart delivery is on
  (`server.configure_chart_delivery` -> `delivery.trial_signer`: absolute, regular, no
  symlink, this user, mode 600 or tighter), and signs each chart_delivery log line with
  `trial_id`, `trial_t` (ms) and `trial_mac` = HMAC-SHA256(key, context, trial id, trace
  id, status, time); `server_start` names the trial id, never the key. The watchdog
  accepts only a line whose fields appear once, whose trial id is this trial's, whose
  HMAC verifies and whose time is after `activated`, by the timeout and at most 2 s
  ahead; every other chart_delivery line is ignored and recorded as rejected
  (`rejected.jsonl`, reasons only). `done pass` is removed (refused, exit 2); `done
  fail` and `abort` remain early-rollback triggers. No signed line: `fail`/`aborted`,
  never `pass`. New setting `IDX_CHART_TRIAL_FILE` on the pool allowlist and in
  `.env.example`.
- No re-activation. The claim writes a permanent `<run>/tombstone` under the run's state
  lock; `enable`, `activated` and `sent` take that lock and refuse while it exists.
  After the rollback the watchdog keeps watching until the delete grant's expiry (or
  `--watch-after`): a switch line in `.env` that is not 0, or install.sh's analysis
  fragment back, runs the rollback again ("re-enable blocked"; at most 3 reruns).
- Fail-safe: any unexpected exception in the watchdog rolls back `aborted` and records
  the exception class. SIGKILL, logout and reboot are not covered by the watchdog (no
  rollback, no record); section 7 now says so and names the cover: the agent's deadline
  check (`status` -> "NOT RUNNING and no record", exit 3) and the owner's by-hand
  rollback.
- "No reply within 2 minutes" is wired: `sent <run>` after the trial message starts a
  2-minute countdown (`--reply-wait`) to `fail`; the hard timeout still counts from
  `activated`. Docs and code agree (CHART_DELIVERY.md section 7, ACTIVATION_HANDOFF.md's
  superseded note, scripts/README.md).
- Tests: `tests/test_chart_trial_armed.py` now 27 test functions, 51 collected cases
  (24 single + 7 refusals + 13 signal-judging + 7 unusable trial files). (a) a real
  `bounded_analysis` call over an in-process MCP session (fake docker worker) writes
  the signed line through the server's own code and the watchdog rolls back `pass`;
  (b) hand appended lines (unsigned, made-up HMAC, other key) rejected, `fail` at the
  timeout; (c) trial 1's valid line replayed (and relabelled) in trial 2 rejected; (d)
  `done pass` refused, a hand-written pass ignored; (e) late
  `enable`/`activated`/`sent` after the timeout rollback refused, a forced `.env`
  re-enable rolled back again, and `enable` hammered across the activation-limit
  rollback never leaves anything on; (f) a corrupt `activated` file -> TypeError ->
  fail-safe `aborted`; (g) signed line, `done fail`, `abort` and timeout racing plus a
  second watchdog -> one rollback. `tests/test_db_pool.py` pins the new allowlist
  name. Fail-before: on c5ace93 (archive, new test file copied in) 42 of 51 fail, the
  9 unchanged cases pass (7 refusals, `activated` without a watchdog, the grant
  arithmetic); new server code only: 32 fail; new watchdog only: 27 fail. All 51 pass
  here.

Evidence (owner's Mac): `ruff check .` and `ruff format --check .` clean; `shellcheck`
clean on the wrapper. Full suite (`MYSQL_HOST= pytest -q`): 5,181 passed, 130 skipped;
with `IDX_ANALYSIS_IMAGE=sha256:<64 hex>`: 5,181 passed, 130 skipped. Repeats of the
armed file: before a test-only fix, 3 of 15 runs had one failed case; the one captured
was the test polling `fired` and then reading `tombstone` without the state lock (they
are written together under it); the test now waits for both; then 4 of 4 runs passed.
The harness now starts from a plain-JSON `openclaw.json` (as on the Mac): with none,
install.sh installs the JSON5 render and a second install (a second rollback) fails in
the merge with JSONDecodeError, which the recorded demo first showed; that install.sh
behaviour is pre-existing and unchanged here (owner question on the PR). A recorded
end-to-end run of scenarios (a)-(g) (7 tests, 9 rollbacks, all `ROLLBACK DONE`, no
trial key outside its trial file) is on the PR. Nothing installed, activated, restarted,
paid for or sent; no live `.env`, `~/.openclaw`, gateway or launchd change. CI evidence
for this branch is recorded on the PR.

2026-11-04 (follow-up: the armed rollback; branch wo-030-armed-trial-cleanup from main
71fb39e): still off, not installed, not activated; **the live chart trial is paused**
until this change is merged and its offline demonstration has passed. **Actual
WhatsApp delivery: UNVERIFIED.**

- Owner (verbatim): "For chart rollback, use the agent-operated path with a valid
  delete grant issued before the trial. Existing delete grants are time-bound, not
  command-bound; describe them accurately." and "Pretyping a terminal command does not
  provide automatic rollback. Arm cleanup and a timeout before activation, and
  demonstrate that cleanup runs without waiting for my reply. Keep the chart trial
  paused until that works."
- New `scripts/chart_trial_armed.sh` (logic in `scripts/chart_trial_armed.py`,
  standard library only). `arm` runs before step 1 and refuses, starting nothing,
  unless `scripts/chart_trial_rollback.sh`, a record directory of the user's own with
  mode 700, the `--log` file if given, bounded limits, and a delete grant valid for
  the whole window (activation limit + trial timeout + 600 s rollback + 60 s; 31 min
  with the defaults) are present; it prints the grant's expiry. It then starts a
  watchdog in its own session (survives the agent's shell and a gateway restart),
  which records its pid and arm time in a private run directory and runs the rollback
  exactly once, without waiting for any reply, on the first of: `abort` (`aborted`),
  no `activated` by the activation limit (`aborted`), a `chart_delivery` line in the
  server log after `activated` plus a settle so the reply is sent first (`ready` ->
  `pass`, `failed` -> `fail`), the operator's `done`, the hard trial timeout (`fail`),
  or SIGTERM (`aborted`). Exactly once: one decision per poll, an exclusive-create
  claim file and a lock per record directory. The record is `<run>/record.txt`.
- The delete grant, described accurately: `consent.sh delete <minutes>` writes one
  expiry (at most 240 minutes); it is time-bound, not command-bound, covers every
  agent deletion until it expires or is revoked, and is not spent by use. The owner
  issues it before arming. Revoking it does not cancel an armed rollback; the record
  shows the grant at arm and at rollback. docs/CHART_DELIVERY.md section 7 gains "The
  delete grant", step 0a (arm), the `status` check before each of steps 1-3,
  `activated` after step 3, `abort` on a failure, and step 6 run by the watchdog.
- `tests/test_chart_trial_armed.py`: 11 test functions, 21 collected cases (one test
  with 7 refusal cases, one with 5 parser cases, 9 single). They run the real wrapper
  and rollback in a throwaway repo (temp HOME, state, consent and record dirs; stub
  openclaw, node and launchctl) with no input to any process: signal -> rollback after
  the settle, `ROLLBACK DONE`; no signal -> at the timeout; abort and a never-confirmed
  activation -> `aborted`; the arming shell's process group killed -> the watchdog
  still fires; signal, `done` and timeout racing plus a second watchdog -> one
  rollback, one restart; each missing precondition -> refused, nothing run.
  Fail-before / pass-after: on 71fb39e (archive, test file copied in) all 21 fail
  (`FileNotFoundError`); all 21 pass here. Repeats on the Mac: 27 more runs of the
  file (10 sequential, 9 in three parallel loops, 8 beside a full-suite run); 26
  passed, and one sequential run that overlapped the start of a full-suite run had
  1 failed case, not captured. The two timing upper bounds (signal: settle + 2 s;
  timeout: + 2 s) were then widened to + 5 s; 21 of 21 passed after that.

Evidence (owner's Mac; Docker running, worker image not exported, so `container`
tests skip as before): `ruff check .` and `ruff format --check .` clean; `shellcheck`
clean on `scripts/chart_trial_armed.sh`. Full suite (`MYSQL_HOST= pytest -q`): 5,150
passed, 130 skipped. A second full run, alongside 8 runs of the armed tests, had one
failure, the `[sigint]` case of
`tests/test_chart_delivery.py::test_how_the_process_ends_decides_what_happens_to_its_charts`
(untouched code; it passed alone right after, with the 21 armed cases: 25 passed). Main CI 41950375863 on 71fb39e: success. Nothing
installed, activated, restarted, paid for or sent; no live `.env`, `~/.openclaw`,
gateway or launchd change. CI evidence for this branch is recorded on the PR.

2026-11-04 (owner requirement for the trial; main 48b74ab merged in): still off by
default, not installed, not activated. **Actual WhatsApp delivery: UNVERIFIED.**

- Main merged in by merge commit 58f7d61 (#144, #154, #145, #152, #156 on main at
  48b74ab); no conflicts.
- Owner requirement (verbatim): "The procedure must roll back immediately after
  completion or failure, without waiting for my reply. Record the rollback and verify
  analysis/chart delivery are off. Keeping delivery enabled requires my later
  approval." docs/CHART_DELIVERY.md section 7 is rewritten as one sequence: enable
  (1-3), one trial turn (4; the earlier second turn "send that chart again" and the
  five-minute expiry wait are dropped, both are pinned offline), record the observed
  result (5), roll back at once (6), verify off (7), write the record (8). Keeping
  delivery enabled is step 9, separate and not part of the trial; no reply means off.
- The rollback turns both `IDX_CHART_DELIVERY` and `IDX_ANALYSIS_TOOL` off by editing
  each line in place to `=0` (the first line for a key wins, so appending would not),
  then install.sh, gateway restart, `prune --all`, and the launchd job's bootout and
  plist removal, each only if present ("not installed" otherwise, not an error).
  Verification: both switches off in `.env`; the server rule gives `bounded_analysis`
  absent and `chart_state` off with no problem; `health` has no warning and no
  analysis or chart line; no chart files; `mcp doctor` and `skills list` do not list
  the tool or skill; no analysis fragment; `launchctl print` says "Could not find
  service". The record entry for `docs/EVIDENCE_LOG.md` and this Status is a template
  in section 7, step 8.
- New `scripts/chart_trial_rollback.sh pass|fail|aborted` runs steps 6-7 and prints the
  record (exit 0 only with `ROLLBACK DONE`); it never bootstraps or loads anything.
  `tests/test_chart_trial_rollback.py` (7 test functions, 9 collected cases) runs it in a
  throwaway repo with temp `HOME` and state dir and stub `openclaw`, `node` and
  `launchctl`, and pins the record
  line by line. Fail-before / pass-after: on 58f7d61 (archive in a scratch directory,
  test file copied in) all 9 collected cases fail (`FileNotFoundError`, no script); all 9
  pass here.
- Low notes fixed: the section 5b uninstall is guarded (bootout only if loaded, rm only
  if present); `last exit code = (never exited)` right after the bootstrap is explained
  (re-check after 5 s; still so, or `runs = 0`, at 65 s is a failed step 2); the title
  no longer says "proposal".

Evidence (owner's Mac, Docker and Ollama absent, so `container` tests skip): `ruff
check .` and `ruff format --check .` clean; `shellcheck` clean on the new script. Full
suite: 4,901 passed, 130 skipped with IDX_ANALYSIS_IMAGE unset, and the same with
`IDX_ANALYSIS_IMAGE=sha256:b...` exported (merge commit 58f7d61 alone, unset: 4,892
passed, 130 skipped). Nothing installed, activated, restarted, paid for or sent. CI
evidence is recorded separately on the PR, by run id.

2026-11-03 (owner decisions, round three; main 27c4ef1 merged in): still off by
default, not installed, not activated. **Actual WhatsApp delivery: UNVERIFIED.**

- Main merged in by merge commit 3c84575 (#156: an `IDX_ANALYSIS_IMAGE` conflict
  fails closed). The one conflict, `src/idx_agent/analysis/tool.py`, kept this
  branch's `KEEP_IN_DOTENV` and `value_differs` and main's `IMAGE_DIFFERS` text; the
  image check is now `if file_on and value_differs(IMAGE_ENV, environ, dotenv): return
  SwitchState(False, IMAGE_DIFFERS)`. `tests/test_analysis_switch_agreement.py` from
  main is unchanged and passes.
- Image conflict and charts: chart delivery is off with the tool (`ChartState(False)`,
  even with `IDX_CHART_DELIVERY=1` in `.env`), and `health` and `server_start` carry
  only `IMAGE_DIFFERS`. No separate chart problem line: the one root cause gets one
  line, and that line already says the tool is not registered, which is how a
  contradicted analysis switch is reported too. Pinned by
  `test_an_image_conflict_keeps_charts_off_with_no_chart_line` (`.env` image differs
  or absent) and `test_health_and_start_log_report_an_image_conflict_once`
  (`bounded_analysis` absent). Fail-before / pass-after: with 6a27dca's `tool.py` put
  back in the worktree, all 3 fail (`on: True != False`); they pass after the merge.
- D5 (approved): this path for **one** separately authorized live WhatsApp trial
  (docs/CHART_DELIVERY.md section 7). It still needs its own `paid` grant and activation
  approval. Keeping delivery enabled afterwards needs the owner's approval of the
  result. Delivery stays UNVERIFIED until the trial passes and is recorded here.
- D6 (approved): the launchd prune job is part of Phase 2 chart activation (section
  7, step 2), and the owner installs it as an operator step. Kept as
  `config/chart-prune.launchd.plist.proposal`: it is a template with a `__REPO__`
  placeholder, a test pins the name, and renaming a tracked file is out of scope for
  this round. Only its comment changed (approved, not installed). Section 5b now gives
  exact install, verify and uninstall commands: precondition checks, a manual prune
  first, `plutil -lint`, no leftover placeholder, `launchctl bootstrap`/`print`/`bootout`,
  each with expected output. The rollback in section 7 ends with the uninstall.
- D7 (approved): #148 merges before #155. #155 will then switch
  `tests/test_phase_integration_charts.py` to its synthetic-store helper. The Phase 1
  probe (#147) must show `bounded_analysis` absent, `IDX_ANALYSIS_TOOL` off and
  `IDX_CHART_DELIVERY` off.

Evidence (owner's Mac, Docker and Ollama absent, so `container` tests skip): `ruff
check .` and `ruff format --check .` clean. Full suite: 4,706 passed, 130 skipped with
IDX_ANALYSIS_IMAGE unset, and the same with `IDX_ANALYSIS_IMAGE=sha256:b...` exported
(merge commit 3c84575 alone: 4,703 passed, 130 skipped, both modes).
`tests/test_chart_switch_agreement.py`: 105 passed. Nothing installed, activated, paid
for or sent. CI evidence is recorded separately on the PR, by run id.

2026-11-03 (review follow-up, non-blocking): still off by default, not installed.
**Actual WhatsApp delivery: UNVERIFIED.** The round 3 expiry fix passed review and is
unchanged.

- Finding: the 20-file cap was best effort across server processes. OpenClaw runs one
  `idx` server per chat session, all sharing one `idx-charts` directory, and admission
  (sweep, count, write, rename) was serialized only by a thread lock inside one
  process. Chosen: serialize it (option a). `ChartStore.write` now holds an exclusive
  `fcntl.flock` on `.idx-charts.lock` in the directory (stdlib, macOS and Linux):
  opened `O_RDWR|O_CREAT|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, mode 600, refused unless a
  regular file owned by this user (`lock_unsafe`), never written to, never removed by
  retention or `prune --all` (its name matches neither pattern). The wait is bounded at
  `LOCK_WAIT_SECONDS` (2 s); past it the chart is refused with `dir_busy` and the
  figures stay whole. The kernel drops a dead holder's lock, so SIGKILL never blocks
  anyone. `prune` and the expiry thread only remove and take no lock.
- Fail-before / pass-after: regression committed first (0b68af9).
  `test_concurrent_processes_never_exceed_the_cap_and_none_hangs` (8 OS processes, cap
  3, 0.2 s between count and rename) fails on ad5e46c with `AssertionError: 8 charts
  written, cap 3` in 5 of 5 runs; it passes after the fix (3 written, 5 `dir_full`, no
  writer past the bound). With the final test file in a detached worktree of ad5e46c,
  12 tests fail (that one, 8 lock tests by missing API, and 3 listing tests that now
  also see the lock file) and 101 pass; all 113 pass here.
- Docs: `docs/CHART_DELIVERY.md` sections 3, 5, 6 and 7 (new reason codes, the lock
  file in `ls -la` and after rollback, "Cap across processes"). Residual kept: a chart a
  sweep cannot stat is still not counted (section 5).

Evidence (owner's Mac, Docker and Ollama absent, so `container` tests skip): `ruff
check .` and `ruff format --check .` clean. Full suite: 4,695 passed, 130 skipped with
IDX_ANALYSIS_IMAGE unset, and the same with `IDX_ANALYSIS_IMAGE=sha256:b...` exported
(ad5e46c: 4,686). Stability, 10 of 10 runs each: the expiry, concurrency, cap, lock and
default-off tests of `tests/test_chart_delivery.py` (48 tests) and
`tests/test_phase_integration_charts.py` (16 tests). CI evidence is recorded separately
on the PR, by run id.

2026-11-03 (review round 3): still off by default, not installed. **Actual WhatsApp
delivery: UNVERIFIED.** Retargeted to `main` (PR #148); main cbad756 merged in with a
merge commit (d6f631e; the settings allowlist and its test kept both sides). Round 2's
two commits (34bf3d0, c72113d) reviewed, verified and pushed as they were.

- Round 2 verification (concurrent sweeps, trailing-newline names; `fullmatch` was
  already in 34bf3d0): the 10 regressions, run on 16d3d38 in a detached worktree, all
  fail (`FileNotFoundError` from the racing scandir, `PermissionError`, `assert 2 ==
  0` for the newline names, `JSONDecodeError` where the tool call failed); all pass at
  c72113d. Command: `pytest tests/test_chart_delivery.py -k "removed_mid_sweep or
  unlistable or after_its_rename or vanishes_after or only_looks_like_ours or
  concurrent_sweep or start_up_prune"` (10 failed / 10 passed).
- Finding (expiry), fixed: cleanup ran only at start, before another write or through
  prune, so an idle chart stayed readable past 300 s. Now the server's store runs one
  daemon thread that removes each chart this process wrote at its deadline (waits
  capped at 15 s against wall-clock deadlines, for sleep and clock changes); a clean
  exit (stdin closed, SIGTERM, SIGINT) removes the process's charts; SIGKILL leaves them
  to the next sweep (start, write, deadline) or the prune command. OpenClaw's dispose
  (read only, E17-E20): stdin close, 2 s, SIGTERM, 2 s, SIGKILL; the server exits 0 in
  0.14-0.15 s after stdin close on the Mac (5 runs), so the exit hook runs in the normal
  case. docs/CHART_DELIVERY.md section 5a claims exactly that, and no more.
- Fail-before / pass-after: `test_over_mcp_an_idle_chart_is_gone_at_its_deadline`
  (the review's reproduction over MCP, ttl 0.3 s, no further call) fails on d6f631e
  with `AssertionError: the chart is still readable after its deadline` and passes
  now; with it, 15 of the 17 new tests in `tests/test_chart_delivery.py` fail on
  d6f631e (missing API, the child probe cannot arm its exit hook, the proposal file is
  absent) and pass now; the two real-server termination tests are behaviour pins that
  pass on both. Of the 16 ported integration tests, 8 fail on d6f631e (no
  `_arm_chart_expiry`, the idle chart outlives its deadline) and all pass now.
  Command: both test files copied into a detached worktree of d6f631e, `pytest
  tests/test_chart_delivery.py tests/test_phase_integration_charts.py` (23 failed, 97
  passed there; 120 passed here).
- Cross-feature acceptance tests: `tests/test_phase_integration_charts.py` ports the
  scratch branch's checks that concern charts with main's features (badges,
  explanations, analysis routing, rollback, install rollback); its three strict xfails
  are real assertions against `configure_chart_delivery()` and
  `chart_delivery_problem()`, on the server and in install.sh. Saved feature searches
  stay with #147.
- Considered and not changed: a shorter TTL (OpenClaw copies the file into its media
  store at dispatch, E6, but the default agent timeout is 48 h, E20, so no turn bound
  supports it); a one-shot read marker (no observable read); a detached helper process
  (escapes the process group OpenClaw owns, E19).

Decision for the owner (new): strict expiry independent of our process. Proposal,
NOT installed: `config/chart-prune.launchd.plist.proposal`, a launchd user agent running
`python -m idx_agent.analysis.delivery prune` (expired files only, our names, the one
directory `.env` names) every 60 s; bound 360 s while awake. Install and uninstall
commands in docs/CHART_DELIVERY.md section 5b. Until then: expiry at the deadline while
the server lives, removal at a clean exit, the next sweep after a SIGKILL.

Evidence (owner's Mac, Docker and Ollama absent, so `container` tests skip): `ruff
check .` and `ruff format --check .` clean. Full suite: 4,686 passed, 130 skipped with
IDX_ANALYSIS_IMAGE unset, and the same with `IDX_ANALYSIS_IMAGE=sha256:b...` exported
(merge commit d6f631e alone: 4,653 passed, 130 skipped). The expiry tests passed 20 of
20 repeated runs. CI evidence is recorded separately on the PR, by run id.

Earlier entry, 2026-11-03 (review round 2): still off by default, not installed. **Actual WhatsApp
delivery: UNVERIFIED.** Steps 1-4 of round 1 re-verified at 16d3d38 (rebased on
wo-027-analysis-integration eaca2d8; `main()` prunes, then `log_start`).

- Finding (medium), confirmed and fixed: concurrent sweeps by two sessions' server
  processes. An entry another process unlinked between this process's listing and its
  `lstat` raised `FileNotFoundError` out of `ChartStore._sweep`: `bounded_analysis`
  returned only `Error executing tool bounded_analysis` (figures lost) and the
  start-time prune ended the process. Reproduced over a real MCP client, on the start
  prune, with an unlistable directory, and with two real OS processes (40 of 40 runs
  raised before, 0 of 40 after). Now the sweep skips such an entry; `write()` maps any
  OSError to `dir_unavailable` or `write_failed` (the figures stay, the caption says the
  chart could not be prepared); the start prune never raises and logs one
  `chart_prune` failure line; the prune command reports an unlistable directory.
- Also fixed (found by the same probe): our names are matched whole; `$` had also
  accepted a trailing newline, so a foreign `chart-<hex>.png\n` file was pruned.
- 10 deterministic regression tests (racing scandir, removal right after rename, a
  directory vanishing after mkdir, start prune, prune command, names); all 10 fail on
  16d3d38 and pass now.

Earlier entry, 2026-11-02 (review round): rebased onto wo-027-analysis-integration at eaca2d8 (its
`switch_state` and `log_start`); `main()` now runs `register_analysis_tool`,
`configure_chart_delivery`, `_prune_charts_at_start`, then `log_start`. Still off by
default, not installed. **Actual WhatsApp delivery: UNVERIFIED.**

- Flake (`test_two_sessions_never_see_each_others_chart`, KeyError 'delivery', one
  chart `unavailable`): the test fake, not production. The shared fake worker took its
  argv and input directory from the newest entries of call lists shared by all
  threads, so a render that started after the other session's analysis directory was
  made opened the wrong directory, raised FileNotFoundError inside Popen, and the real
  executor correctly answered `unavailable`. The fake now reads the directory its own
  argv mounts. A new test forces that interleaving; it failed on the old fake every
  time and passes now. Before the fix, 6 of 40 runs of the flaky test failed on the
  Mac. After it, the whole test file passed 30 of 30 runs with only the fake fixed and
  30 of 30 on the final code (77 tests each), and the two concurrency tests passed 30 of
  30 runs with IDX_ANALYSIS_IMAGE exported.
- The same review found real cross-session effects in production, now fixed. All chat
  sessions' server processes share one directory, and three paths could remove another
  session's file: an in-progress temp file pruned at any age; the 20-file cap evicting
  a chart seconds old; supersede retiring every chart in the process, not just the
  session's own. Now: temp files only when 60 s old; the cap evicts only charts past
  the 120 s grace (else `dir_full`, stated in the reply); the ledger is keyed by MCP
  session.
- Switch agreement: IDX_CHART_DELIVERY and IDX_CHART_DIR follow WO-027's rule through
  `delivery.chart_state`, built on `analysis.tool.switch_contradicted` and
  `value_differs`, the tests `switch_state` itself now uses. install.sh refuses before
  writing anything; the server keeps delivery off and reports the problem in `health`
  and `server_start`. Pinned in `tests/test_chart_switch_agreement.py` (102 tests).
- Residual risks re-checked against the installed OpenClaw 2026.9.5 (read only,
  docs/CHART_DELIVERY.md E15-E16). The default directory now gives a workspace-relative
  `MEDIA:idx-charts/...` line, so a mis-formatted line shows no user name. The 300 s
  re-send window is kept and documented: no evidence bounds a turn's length.

Evidence (owner's Mac, Docker and Ollama absent, so `container` tests skip): `ruff
check .` and `ruff format --check .` clean. Full suite: 4,544 passed, 130 skipped with
IDX_ANALYSIS_IMAGE unset, and the same with `IDX_ANALYSIS_IMAGE=sha256:b...` exported.
`tests/test_chart_delivery.py`: 77 passed. CI evidence is recorded separately on the
PR.

Earlier entry, 2026-11-02: built and tested offline, in review. Off by default, not installed.
**Actual WhatsApp delivery: UNVERIFIED** until the operator acceptance check passes.

Finding (re-verified from the installed OpenClaw 2026.9.5, read only): an MCP tool
result cannot put a local file into the reply; an MCP image block goes to the model
only; the reply's own media (a standalone `MEDIA:` line in the final answer) is read from
the agent workspace under the existing `read` permission and sent only to the chat the
turn came from. Chosen path: the server writes the checked PNG into
`<idx workspace>/idx-charts/` and returns the MEDIA line; no OpenClaw config change.
Evidence table and threat model: `docs/CHART_DELIVERY.md` sections 2-3.

Decisions for the owner:
1. Approve the MEDIA-line path (no policy change, relies on the model keeping one line
   unformatted and on OpenClaw's legacy-but-supported final-reply `MEDIA:` parsing), or
   prefer one of the rejected options (`message` tool, plugin tool) that need a policy
   change.
2. Accept the residual duplicate window: within 300 s a model that repeats the line in
   a later reply resends the same chart to the same chat (never another chat).
3. Activation order: install and accept Phase 1 first, then flip `IDX_CHART_DELIVERY` and
   run section 7 as a separate step with its own `paid` grant.

Evidence (this branch, owner's Mac, 2026-11-02): `ruff check .` and `ruff format
--check .` clean; `MYSQL_HOST= pytest -q -p no:cacheprovider` 4,370 passed, 130 skipped
(base branch wo-027-analysis-integration: 4,301 passed, 130 skipped);
`tests/test_chart_delivery.py` 67 passed. Docker is not running on the Mac, so the
`container` tests skipped locally; CI builds the image and runs them. CI evidence is
separate from Mac evidence. Not installed, no OpenClaw command run, nothing sent.
