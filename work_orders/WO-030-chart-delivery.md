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
4. Operator activation, the smallest live acceptance check and rollback, written, not run.

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
`scripts/install.sh`, `tests/test_chart_delivery.py` (new), `docs/CHART_DELIVERY.md`
(new), this file.

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
   20 files, prune at start and before every write, superseded charts of this process
   after 120 s, and an operator prune command.
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
files, symlinks and subdirectories untouched); supersede after grace; result shape on
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
- Live: the acceptance check in `docs/CHART_DELIVERY.md` section 7 passes on the owner's
  phone (owner step).

## Verification commands
```sh
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_chart_delivery.py
```

## Deliverables
An off-by-default chart delivery path whose activation, live check and rollback are in
`docs/CHART_DELIVERY.md` section 7.

## Stop conditions
Delivery would need a broader tool, a public URL, wider file access or an OpenClaw
config change the owner has not approved; the live check shows OpenClaw ignoring the
MEDIA line.

## Status

2026-11-03 (review round 2): still off by default, not installed. **Actual WhatsApp
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
