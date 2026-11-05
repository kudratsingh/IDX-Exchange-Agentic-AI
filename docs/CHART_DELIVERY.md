# Chart delivery to WhatsApp (WO-030 design, contract and trial)

Status: built and tested offline behind `IDX_CHART_DELIVERY` (off). **Actual WhatsApp
delivery is UNVERIFIED** until the one-shot live trial in section 7 passes on the
owner's phone and is recorded. Until then the requirement "charts are delivered to
users" is not met; the text-only answer (WO-027) stays and remains complete on its own.
The trial rolls back at once when it completes or fails, without waiting for anyone's
reply (owner requirement, 2026-11-04); delivery is enabled again only by a later,
separate owner approval of the recorded result. That rollback is armed before
activation and fires by itself (section 7, step 0a, `scripts/chart_trial_armed.sh`);
the trial stays **paused** until that is merged and its offline demonstration passed.

Owner decisions, 2026-11-03 (round three):

- **D5, approved:** this chart path for **one** separately authorized live WhatsApp
  trial (section 7). The trial needs its own `paid` grant and its own activation
  approval; neither is given by D5. The trial ends with an immediate rollback, pass or
  fail (owner, 2026-11-04: "The procedure must roll back immediately after completion
  or failure, without waiting for my reply."). Keeping delivery enabled needs the
  owner's later approval of the recorded result, as a separate step (section 7, step
  9). WhatsApp delivery stays UNVERIFIED until that trial passes.
- **D6, approved:** the launchd prune job (section 5b) is part of Phase 2 chart
  activation. The owner installs it as an operator step; nothing in the repository
  installs it. The file stays `config/chart-prune.launchd.plist.proposal`: a template
  with a `__REPO__` placeholder, not a loadable plist, and the suffix keeps it from
  being mistaken for one.
- **D7, approved:** #148 merges before #155. #155 then switches
  `tests/test_phase_integration_charts.py` to its synthetic-store helper. The Phase 1
  probe (#147) must show `bounded_analysis` absent, `IDX_ANALYSIS_TOOL` off and
  `IDX_CHART_DELIVERY` off.

## 1. The requirement

The owner decided that charts must actually reach the user in the chat. A text-only
fallback stays, but it does not complete the requirement. Constraints for any path:

- no broad messaging permission: the agent must not gain a way to message any recipient
  other than the chat it is answering;
- no arbitrary file access: only charts the server generated, from one dedicated
  directory;
- no public chart URLs;
- the model answers from the verified figures already in text; it never needs to see
  the chart.

## 2. What OpenClaw 2026.9.5 does today (evidence)

Read only, from the installed package (`~/.npm-global/lib/node_modules/openclaw`,
`package.json` version 2026.9.5) and the installed WhatsApp plugin
(`~/.openclaw/npm/projects/openclaw-whatsapp-*/node_modules/@openclaw/whatsapp`, version
2026.9.5). Nothing was run, sent or changed. `dist/` file names carry build hashes; line
numbers are for this build. The live config was read for key names and tool-policy
values only (no secrets, credentials, sessions, logs or media).

| # | Finding | Where |
|---|---|---|
| E1 | An MCP `image` content block becomes an image block for the **model**; `resource` and `resource_link` blocks become text. | `dist/mcp-content-Dj8o6nFL.mjs:61-105` (`mcpContentBlockToAgentContent`) |
| E2 | An MCP tool result is tagged `details: {mcpServer, mcpTool}`; only `structuredContent` is copied into `details`. Nothing from the MCP result can set `details.media` or `details.path`. | `dist/agent-bundle-mcp-materialize-Bf4ktXvL.mjs:322-326`; `dist/mcp-content-Dj8o6nFL.mjs:118-130` |
| E3 | Tool-result media reaches the reply only via `details.media`, or an image block plus `details.path`; a result tagged `mcpServer`/`mcpTool` is "external", and for external results every local path is dropped: only `http(s)` URLs survive. | `dist/embedded-agent-messaging-extraction-B4_H2Tnw.mjs:109-138` (`isExternalToolResult`, `filterToolResultMediaUrls`), `:207-227` (`extractToolResultMediaArtifact`); called at `dist/builtin-openclaw-C7-lQJ2Z.mjs:2950-2966` |
| E4 | OpenClaw's own docs: tool-result images are private to the agent and are not attached to channel replies automatically. | `docs/tools/browser/configuration.md:158-160` |
| E5 | Outbound local-media roots for an agent are OpenClaw's temp dir, `<state>/media`, the delivery-queue media dir, `<state>/canvas`, and the agent's own workspace; with `tools.fs.workspaceOnly: true` they are never widened to a file's parent directory. | `dist/local-roots-hDHLnjuV.mjs:28-41, 91-105, 123-141` |
| E6 | Media in a reply is normalized per reply: a local path is read under the agent's outbound media access and **copied into OpenClaw's outbound media store**; identical sources in one reply are sent once; a source that fails is dropped and a line `⚠️ <file name>: <reason>` is appended to the reply text. | `dist/reply-media-paths.runtime-Df9MwgEF.mjs:115-133, 146-212, 213-262`; `dist/reply-payload-DXOJ3g20.mjs:27-41` |
| E7 | That media access is allowed only when the `read` tool is allowed for the sender; then the roots are E5 plus the workspace. | `dist/read-capability-B5hXVZWk.mjs:17-42, 84-123` |
| E8 | A standalone `MEDIA:<path>` line in the agent's **final reply** is parsed into reply media (not inside code fences, not inside Markdown, not inline). The normalizer is created per dispatch with that turn's session key, agent id, workspace and requester. | `dist/parse-output-DGOcuzU4.mjs:173-231`; `dist/payloads-B5TkO01B.mjs:369-383`; `dist/dispatch-from-config-CTQQ29Us.mjs:2946-2969`; `docs/reference/rich-output-protocol.md:22, 36-60` |
| E9 | WhatsApp sends reply media to the **inbound conversation's transport** with the first text chunk as caption; on a media failure it sends the caption plus `⚠️ Media failed.` (or `⚠️ Media unavailable.` for a later item). Size cap `channels.whatsapp.mediaMaxMb`, default 50; images are re-encoded to fit. | plugin `dist/.setup/monitor-BblvzLpX.mjs:2865-2928, 3351, 3372-3377`; `docs/channels/whatsapp.md:425-443` |
| E10 | The loader reads a local file only inside the given roots (`path-not-allowed` otherwise), sniffs the MIME type, and applies the byte cap and image limits. | `dist/web-media-DQ8C-3GL.mjs:575-698` |
| E11 | With block streaming on, streamed text is not parsed for `MEDIA:`; block streaming defaults to off. | `docs/concepts/streaming.md:55, 98-107` |
| E12 | The `message` tool can send to other conversations unless `tools.message.crossContext` blocks it, and even then the cross-context guard covers mutations, not every channel action. Its media argument can name any file the agent can read. | `docs/gateway/security/tool-permissions.md:33-56`; `docs/start/openclaw.md:203-220` |
| E13 | Each session gets its own MCP runtime (servers keyed by session id), so each chat session has its own `idx` server process, and **all of them share the one chart directory**. Retention is therefore written so that no process removes what another session may still need (section 3); the supersede ledger is also keyed by MCP session, so the design holds even if one process served several sessions. | `dist/agent-bundle-mcp-manager-api-DswOxDdW.mjs:387-391`; `dist/agents/agent-bundle-mcp-runtime.js:99-140` |
| E15 | A **workspace-relative** local MEDIA path is valid: the parser accepts a relative path containing `/` without `..` or a leading `~`; the reply normalizer resolves it against the run's agent workspace through `resolveWorkspaceRelativeMedia`, the same function an absolute path inside the workspace goes through, then the same `persistLocalReplyMedia` read check. The workspace is the agent's configured `workspace` with `~` expanded. OpenClaw's docs list workspace-relative and `~/` paths as valid local attachments under the same read policy. Applies when the agent is not sandboxed (E16); a `~/` path was not traced to the loader's expansion, so it is not used. | `dist/parse-output-DGOcuzU4.mjs:29-41, 70-79`; `dist/reply-media-paths.runtime-Df9MwgEF.mjs:126-145, 168, 190-199`; `dist/agent-runner.runtime-DRp6jmuv.mjs:3268-3272, 8188-8192`; `dist/agent-scope-config-D2MQzbc-.mjs:368-371`; `docs/reference/rich-output-protocol.md:21` |
| E16 | Sandboxing defaults to off (`mode: "off"`) unless configured for the agent or in defaults; `config/openclaw.idx.json5` configures none. With a sandbox, relative media would resolve inside the sandbox root instead. | `dist/config-Bo2B3kKQ.mjs:138-152`; `dist/runtime-status-CKWyBZaV.mjs:20-24`; `dist/context-D_TiLPsh.mjs:642-650` |
| E17 | A session's MCP runtime (our server process) lives for the session: idle eviction is opt-in (`mcp.sessionIdleTtlMs`, default 0 = session lifetime), so the process normally outlives each reply and is disposed on session retirement or gateway shutdown. | `dist/agent-bundle-mcp-runtime-shared-BFBNCZj0.mjs:4-8`; `dist/agent-bundle-mcp-manager-api-DswOxDdW.mjs:516-536, 980-992, 1023-1025` |
| E18 | Disposing a stdio MCP server: close stdin, wait 2 s, SIGTERM, wait 2 s, SIGKILL; if the graceful close has not settled in 5 s the transport is force-closed with SIGKILL. | `dist/owned-stdio-DMuoFNgp.mjs:37-58` (`closeOwnedStdioProcess`); `dist/mcp-client-lifecycle-BRs8iV6t.mjs:369-404, 470-505` (`disposeMcpClient`, `forceClose`); `dist/agents/agent-bundle-mcp-runtime.js:21` (5 s) |
| E19 | The server is spawned as an owned process tree: OpenClaw tracks its process group and a lineage pipe and treats cleanup as complete only when the group is gone, so a helper process left behind would be killed with the group or hold up cleanup. | `dist/child-hDIQtCC4.mjs:398, 573-580, 627-660, 988-1000` |
| E20 | No turn length bound to rely on: the default agent timeout is 172800 s (48 h) unless `agents.defaults.timeoutSeconds` is set (it is not, E14). | `dist/timeout-Bjg7ga80.mjs:8-14` |
| E14 | Live config (key names and policy values only): `agents.entries.idx.tools.allow = ["idx__*", "idx_alerts__*", "read"]` (no `message`), `tools.fs.workspaceOnly = true`, `tools.message.crossContext` both `false`, no streaming or sandbox keys set (defaults: off). Same as `config/openclaw.idx.json5`. | `~/.openclaw/openclaw.json` (structure only) |

**Re-verification of WO-027's finding.** Confirmed, with one correction of detail: the
image block from `bounded_analysis` reaches the model only (E1, E4), and the MCP tool
result cannot attach a local file to the reply at all (E2, E3); the only way a tool
result could add media is a public `https` URL, which is ruled out. The `idx` agent has
no `message` tool (E14).

## 3. The chosen path: a server-written file named by the reply's MEDIA line

When `IDX_CHART_DELIVERY=1` (and `IDX_ANALYSIS_TOOL=1`):

1. `bounded_analysis` runs exactly as in WO-027: at most 50 sales, numeric fields only,
   figures verified on the host, the PNG drawn by the pinned worker and checked.
2. The server checks the PNG again and writes it once to
   `IDX_CHART_DIR/chart-<32 hex>.png` (default `~/.openclaw/workspace-idx/idx-charts`,
   inside the `idx` agent workspace, which is an outbound media root, E5). The name is
   128 random bits (`secrets.token_hex(16)`).
3. The tool result carries **no image block**. Its message ends with one line,
   `MEDIA:idx-charts/chart-<token>.png` in the default directory (workspace-relative,
   E15, so no user name is in it) or `MEDIA:/absolute/path/chart-<token>.png` for a
   custom `IDX_CHART_DIR`, and `data.chart.delivery` says
   `{"status": "ready", "media_line": ..., "expires_in_s": 300}`. The caption reads
   "..., follows as an image in this chat. If no image appears in this chat, the figures
   above are the whole result."
4. The skill tells the model to keep that line, unformatted, as the last line of its
   reply, in that reply only. OpenClaw parses it (E8), copies the file into its media
   store under the agent's existing `read` permission (E6, E7) and WhatsApp sends it with
   the reply to the chat the request came from (E9).

No OpenClaw config or tool-policy change is needed: `read` is already allowed, the
workspace is already a media root, and `workspaceOnly` stays `true`. Hence there is no
`config/openclaw.charts.json5`; `scripts/install.sh` only reports the switch state.

### One switch rule for install.sh and the server

`IDX_CHART_DELIVERY` and `IDX_CHART_DIR` live in `.env` only, under WO-027's rule
(`analysis.tool.switch_state`; the shared tests `switch_contradicted` and
`value_differs` are reused by `analysis.delivery.chart_state`):

| Process environment vs `.env` | install.sh | Server |
|---|---|---|
| Agree (key absent from the environment, or equal under the "exactly `1`" test) | reports `.env`'s state | follows `.env` |
| `IDX_CHART_DELIVERY` contradicts `.env` (one side exactly `1`, the other not; checked even while the analysis tool is off) | prints the problem line, exits 1 before writing anything | chart delivery off (WO-027's result), problem in `health` message and warnings and in the `server_start` log line (`chart_delivery_problem`) |
| Delivery on in `.env`, analysis tool on, `IDX_CHART_DIR` in the environment differs from `.env` (spaces ignored; absent from `.env` counts as empty) | as above | as above |
| Delivery on in `.env`, analysis tool off | "has no effect" note | off (inert) |

The server decides once at start (`configure_chart_delivery` in `main()`, after
`register_analysis_tool` and before `_prune_charts_at_start` and `log_start`), not per
call. The prune command uses the directory `.env` names and refuses when the
environment names another. `tests/test_chart_switch_agreement.py` pins every
combination through install.sh (temp HOME and state dir) and the runtime.

### How each constraint is met

| Constraint | Mechanism |
|---|---|
| No broad messaging | No new tool, no `message` tool, no policy change. A MEDIA line can only attach media to the reply OpenClaw is already sending to the requesting chat (E8, E9). |
| No arbitrary file access | The server writes only into one directory whose last part must be `idx-charts`; the path is absolute, without `..`, whitespace or quotes; the directory must sit in an existing parent (the workspace is never created), must be a real directory owned by this user (a symlink is refused), and is set to mode 700; files are created with `O_EXCL|O_NOFOLLOW`, mode 600. The one other file is the admission lock `.idx-charts.lock` (section 5, "Cap across processes"): opened with `O_NOFOLLOW`, refused unless a regular file owned by this user, mode 600, never written to (it stays empty), never named in a MEDIA line. OpenClaw's own read policy is unchanged (the model could already name workspace files; nothing new becomes readable). |
| No public URL | Local path only; OpenClaw copies the bytes into its own store before sending (E6). |
| Session/recipient isolation | The line is returned only in the tool result of the request that drew the chart; reply routing sends it only to that request's chat (E8, E9). Another session cannot learn a 128-bit name: there is no listing tool (`group:runtime` and `write` are denied), the directory is mode 700, and only the owner's number may message the agent. One session's chart never removes another session's chart or write in progress (see Retention). Tests check that two concurrent sessions never see each other's line, including a forced interleaving of their worker runs. |
| PNG validation | `png_size` from WO-017: PNG signature, CRC on every chunk, only IHDR/pHYs/IDAT/IEND, 8-bit RGBA, no interlace, IDAT inflates (bounded) to exactly the expected scanlines; width 200-2000 and height 150-1500, below WhatsApp's 2048 px side. |
| Bounded size | 512 KiB (the renderer cap); a caller may lower it, never raise it. WhatsApp's cap is 50 MB. |
| Retention | Only our names (`chart-<32 hex>.png`, `.chart-<32 hex>.tmp`), only regular files, never symlinks or subdirectories, never anything else in the directory. **Expiry** (section 5a): while the server process lives, a daemon thread removes each chart this process wrote at its deadline, 300 s after writing, with no further request; a clean exit (stdin closed, SIGTERM, SIGINT) removes this process's charts at once; after a SIGKILL, the next sweep removes them. Sweeps, at server start, before every write and at each of this process's deadlines, remove any of our charts older than 300 s (a crashed process's); beyond 20 charts the oldest are removed, but **never one younger than 120 s** (its reply may still be pending in another session; a directory of 20 young charts refuses the new one with reason `dir_full` instead). The 20-chart cap holds **across all server processes**, not just within one: each write's sweep, count, write and rename run under one exclusive `flock` on `.idx-charts.lock` shared by every session's process, waited for at most 2 s (`LOCK_WAIT_SECONDS`; then the chart is refused with `dir_busy`, the figures stay). Retention never removes the lock file (its name matches neither pattern, so `prune --all` keeps it too); a temp file only once 60 s old (younger is another process's write in progress). Names are matched whole (a name with a trailing newline is not ours). Sweeps by several processes at once are safe: an entry another process removed after this one listed it is skipped, one this process cannot stat is never removed, and a directory that cannot be listed fails the chart (`dir_unavailable`) or, at server start, logs one `chart_prune` failure line and the server starts anyway. `python -m idx_agent.analysis.delivery prune [--all]` for the operator (`--all` removes every file of ours, by design). |
| Delivery failures | Server side (bad directory, missing workspace, invalid PNG, write error, `dir_full`, `dir_unavailable`, `dir_busy` (another session held the admission lock past 2 s), `lock_unsafe` (the lock file is a symlink, a directory or another user's), `lock_unavailable`; every file-system error while writing or sweeping becomes one of these codes, never a failed tool call): the caption becomes "Chart: could not be prepared for this chat this time; the figures above are the whole result.", `data.chart.delivery` is `{"status": "failed", "reason": <code>}`, and one `chart_delivery` log line records the code (never the path). OpenClaw side: a missing or refused file adds `⚠️ chart-....png: <reason>` to the reply (E6); a WhatsApp send failure sends `⚠️ Media failed.` with the caption (E9). The figures and caveats are in the text either way. |
| At most once | One new file and one line per request; a token is never reused (`O_EXCL`, and a taken name is refused). Within a reply OpenClaw sends a source once (E6). After 120 s a newer chart from the same session removes that session's older ones (never another session's), and while the server lives the file is removed at 300 s (section 5a), so a line repeated later yields a "file not found" note, not a second image. The skill forbids repeating the line. Residual: a model that repeats the line in a later reply within that window would resend the same chart to the same chat (never to another chat); after a SIGKILL the window lasts until the next sweep (section 5a). |
| No chart vision | With delivery on the model gets no image at all; it relays the verified figures in `message`. |

Kept from WO-027: the 50-row boundary, the bounded-sample caveat in every result, no
host-execution fallback, the text-only reply when delivery is off.

## 4. Alternatives rejected

| Option | Why not |
|---|---|
| Keep the MCP image block and hope OpenClaw relays it | It does not (E1-E4). |
| MCP `resource` / `resource_link` block, or `structuredContent` with a media field | Projected to text or kept in `details.structuredContent`; never reply media (E1-E3). |
| Public or tunnelled `https` URL in the tool result | The only tool-result media OpenClaw accepts from MCP (E3), but it publishes chart images (built from sold-listing data) at a URL anyone with the link can fetch, and adds a hosting service. Ruled out by the constraints. |
| Allow the `message` tool for `idx` | Adds a general send tool: other targets unless cross-context guards hold, other actions outside those guards, and attachment of any file the agent can read (E12). Too broad. |
| A custom OpenClaw plugin tool registered as trusted local media | Plugin code inside the gateway and a `trustedLocalMediaToolNames` grant: a new runtime component and a wider trust grant. Out of scope; reconsider only if the MEDIA line proves unreliable. |
| `tools.fs.workspaceOnly: false` and a chart dir outside the workspace | Widens what every local media send may read to any host file the agent can read. |
| Charts in `~/.openclaw/media` | That is OpenClaw's managed store; writing into it couples us to its layout. |

## 5. Risks and limits

- **Model compliance.** The chart arrives only if the model keeps the line as a
  standalone, unformatted line. A wrapped line stays text (E8); the user then sees a
  path in place of an image, and the text answer is still whole. This is what the
  acceptance check measures.
- **Legacy syntax.** OpenClaw calls final-reply `MEDIA:` lines legacy but supported
  (`docs/reference/rich-output-protocol.md:26-38`). A future upgrade could drop them; the
  check must be repeated after an OpenClaw upgrade.
- **Preconditions.** Block streaming off for WhatsApp (E11), the `idx` agent not
  sandboxed, `read` allowed, the workspace at `~/.openclaw/workspace-idx` (or
  `IDX_CHART_DIR` pointed at `<that workspace>/idx-charts`). All hold in the current
  config (E14).
- **Path in text.** Reduced: in the default directory the line is workspace-relative
  (`MEDIA:idx-charts/chart-<hex>.png`, E15), so a mis-formatted line shows no user name.
  With a custom `IDX_CHART_DIR` the absolute path (with the user name) is still what the
  model sees and, if it mis-formats the line, what the owner's own chat shows. The
  relative form depends on the `idx` agent staying unsandboxed (E16) and on its
  workspace staying `~/.openclaw/workspace-idx` (a test pins the config value).
- **Re-send window.** 300 s while the server lives (section 5a): a model that repeats
  the line in a later reply within that window resends the same chart to the same chat.
  OpenClaw copies the file into its own media store when it sends the reply (E6), so
  the file is needed only between the tool result and that reply; but nothing bounds a
  turn's length (default agent timeout 48 h, E20; local models can be slow), so the
  window is not shortened: a shorter one could expire a chart before its own reply is
  sent. A one-shot read marker is not possible: OpenClaw's read leaves no signal we can
  observe (no hook; access times are not a reliable record). The skill forbids
  repeating the line; the session's next chart retires it after 120 s.
- **Concurrent sweeps.** Every session's server process sweeps the one directory. Before
  review round 2 an entry removed by another process between listing and `lstat`
  raised `FileNotFoundError` out of the sweep: the tool call failed with no figures,
  and at start the process ended. Reproduced with two real OS processes pruning one
  directory (40 of 40 runs raised with 20 expired charts); after the fix 0 of 40.
  Residual: if a stat fails for another reason the entry is neither removed nor
  counted toward the 20-file cap, so the cap can be exceeded by such files until a
  later sweep can stat them.
- **Cap across processes.** Review follow-up on #148: admission (count, then write)
  was serialized only by a thread lock inside one process, so concurrent sessions'
  processes could all pass the count and exceed the cap. Reproduced with 8 real OS
  processes, cap 3, a 0.2 s write between count and rename: 8 charts written (5 of 5
  runs, `AssertionError: 8 charts written, cap 3`). Now admission takes an exclusive
  `fcntl.flock` on `.idx-charts.lock` in the directory: exactly 3 written, the other
  5 refused with `dir_full`, none waiting past the bound
  (`test_concurrent_processes_never_exceed_the_cap_and_none_hangs`). The kernel
  releases the lock when its holder exits, however it exits (SIGKILL included), so a
  dead writer never blocks the others; a live one holding it past 2 s costs the next
  writer its chart (`dir_busy`), never the tool call or the figures. What the lock
  does not cover: charts a sweep cannot stat (previous bullet) and files not written
  by this code. The lock is advisory and local: it assumes the directory is on a
  local file system (the default, inside `~/.openclaw`).
- **Retention window.** Section 5a states exactly what is guaranteed and what is
  not. A burst of more than 20 charts within 120 s across sessions makes the next
  chart fail visibly (`dir_full`) rather than remove a chart whose reply may be
  pending.

## 5a. Expiry: what is guaranteed, and what is not

Review round 3 found that cleanup ran only at server start, before another write, or
through the prune command: during inactivity a chart stayed readable past the claimed
300 s, so a later reply repeating the MEDIA line could resend it. Opportunistic sweeps
are **not** an expiry guarantee, and this document no longer presents them as one.

| Situation | What happens | Proven by |
|---|---|---|
| Server alive, no further request, restart or prune | The store's daemon thread (`idx-chart-expiry`, started by the first chart) removes each chart this process wrote at its deadline (written + 300 s). Its waits are at most `EXPIRY_CHECK_SECONDS` (15 s) and deadlines are wall-clock, so after the Mac wakes from sleep (the monotonic wait clock stops during sleep; nothing can read the file while asleep) a due chart goes within 15 s. At each deadline it also sweeps other expired charts of ours (a crashed process's). | `test_a_chart_is_removed_at_its_deadline_with_no_further_request` (injected clock), `test_the_deadline_check_waits_at_most_the_check_interval`, `test_the_expiry_thread_removes_a_chart_at_its_deadline` (real thread), `test_over_mcp_an_idle_chart_is_gone_at_its_deadline` (the review's reproduction over MCP) |
| Clean end: stdin closed (OpenClaw's first step, E18) | The server returns from `server.run` and exits 0; the `atexit` hook removes every chart this process wrote, at once (its session is over). Measured on the Mac: 0.14-0.15 s from stdin close to exit, inside OpenClaw's 2 s grace. | `test_how_the_process_ends_decides_what_happens_to_its_charts[stdin_closed]`, `test_the_real_server_with_delivery_on_ends_cleanly[stdin_closed]` |
| SIGTERM (OpenClaw's second step) or SIGINT | The handler removes this process's charts, then the process ends as SIGTERM would (status -15); SIGINT runs the `atexit` hook. | `...[sigterm]`, `...[sigint]`, `test_the_real_server_with_delivery_on_ends_cleanly[sigterm]` |
| SIGKILL (OpenClaw's last step, or the 5 s force close, E18; or a crash or power loss) | Nothing in the process runs. Its charts stay readable until the first of: any `idx` server start (any session) once they are older than 300 s; any chart write by a live server; any live server's own chart deadline; the operator's prune; or, once the owner installs it (D6, Phase 2 step 2), the launchd job (5b), which bounds it at 360 s while the Mac is awake. **Residual without the job: unbounded if no server starts or writes again and nobody prunes** (for example, the gateway stopped). | `test_how_the_process_ends_decides_what_happens_to_its_charts[sigkill]` (file left), `test_after_a_kill_the_next_start_sweep_removes_the_expired_chart` |
| Delivery off | Nothing is armed: no thread, no handler, no exit hook, main's tool list and instructions. | `tests/test_phase_integration_charts.py::test_default_off_start_arms_no_handler_and_no_thread`, `test_default_off_surfaces_match_main` |

A chart caught mid-write by a signal (renamed but not yet recorded) is not in the
process's ledger, so it too waits for the next sweep, like a SIGKILLed one.

Trade-off of the clean-exit removal: a reply OpenClaw dispatches after our process has
already exited loses the image (OpenClaw appends `⚠️ chart-....png: ...`; the text is
whole). The process normally outlives each reply (E17), so this happens only when a
session is retired or the gateway stops while a reply is in flight.

Rejected: a detached helper process per chart that sleeps until the deadline. It would
outlive SIGKILL only by escaping the process group OpenClaw owns and tracks (E19), which
either gets it killed with the group or holds up OpenClaw's cleanup; that is a change of
process policy, not ours to make.

## 5b. Strict expiry independent of our process (D6 approved; installed by the owner)

A strict bound that holds after SIGKILL needs something outside the `idx` server. The
owner approved (D6, 2026-11-03) a launchd user agent that runs the existing operator
command every 60 s, as part of Phase 2 chart activation (section 7, step 2). The
template is `config/chart-prune.launchd.plist.proposal`; nothing in the repository
installs, copies or loads it (a test pins that). The owner installs it.

- What it runs: `<repo>/.venv/bin/python -m idx_agent.analysis.delivery prune`, from the
  repo directory (so `.env` names the directory), with no environment of its own (so it
  cannot contradict `.env`), never `--all`. Output to `/dev/null`; its result shows in
  `launchctl print` as the last exit code (0: pruned, or no directory yet; 1: the
  directory is misnamed or unlistable, nothing pruned).
- What it can delete: only names `chart-<32 hex>.png` older than 300 s and
  `.chart-<32 hex>.tmp` older than 60 s, regular files only, never a symlink or a
  subdirectory, in the one `idx-charts` directory `.env` names; beyond 20 charts, the
  oldest past the 120 s grace. A directory `.env` does not name, or an environment that
  names another, prunes nothing.
- Bound it gives: a chart is gone at most 360 s after it was written while the Mac is
  awake, whatever happened to the server; launchd skips intervals missed during sleep
  (`man launchd.plist`, StartInterval), so after a wake the next run is within 60 s.

Install (owner, operator step; not run here). Run in a shell whose working directory is
the main checkout, on `main`, with section 7 step 1 done:

```sh
REPO="$(git rev-parse --show-toplevel)"
LABEL=local.idx-exchange.chart-prune
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
test "$(git -C "$REPO" branch --show-current)" = main && test -x "$REPO/.venv/bin/python"
#   expect: exit status 0 (else stop: wrong checkout or no venv)
(cd "$REPO" && .venv/bin/python -m idx_agent.analysis.delivery prune)
#   expect: "removed N chart file(s)" (N may be 0); "nothing pruned" means stop and fix .env
test ! -e "$PLIST"
#   expect: exit status 0 (else it is already installed: verify or uninstall first)
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO__|$REPO|g" "$REPO/config/chart-prune.launchd.plist.proposal" > "$PLIST"
chmod 644 "$PLIST"
plutil -lint "$PLIST"
#   expect: "<PLIST>: OK" (a repo path with "|" or "&" fails here; stop)
grep -c __REPO__ "$PLIST"
#   expect: 0
launchctl bootstrap "gui/$(id -u)" "$PLIST"
#   expect: no output, exit status 0
```

Verify (wait 5 s after the bootstrap; RunAtLoad starts one run at once):

```sh
launchctl print "gui/$(id -u)/local.idx-exchange.chart-prune" \
  | grep -E 'path =|run interval|runs =|last exit code'
#   expect: "path = /Users/<you>/Library/LaunchAgents/local.idx-exchange.chart-prune.plist"
#   expect: "run interval = 60 seconds"
#   expect: "runs = 1" or more, rising by one a minute while awake
#   expect: "last exit code = 0"
```

`last exit code = (never exited)` right after the bootstrap is not a failure: launchd
prints it until the first run has ended, and that run (Python start plus one directory
listing) normally ends within a few seconds. Wait 5 s and run the verify again. If it
still says `(never exited)`, or `runs = 0`, 65 s after the bootstrap (one 60 s interval
plus that margin), the job is not running: treat it as a failed step 2 of section 7,
which ends the trial (`aborted`) with the rollback. `last exit code = 1` means its
`prune` refused (the directory `.env` names is misnamed or unlistable): the same.

Uninstall (also part 5 of the trial's rollback, section 7, step 6). Each part is guarded, so a
job that was never installed, or only half installed, is reported as such and is not an
error:

```sh
SERVICE="gui/$(id -u)/local.idx-exchange.chart-prune"
PLIST="$HOME/Library/LaunchAgents/local.idx-exchange.chart-prune.plist"
if launchctl print "$SERVICE" >/dev/null 2>&1; then
  launchctl bootout "$SERVICE" && echo "booted out"
else
  echo "not loaded"
fi
#   expect: "booted out" (installed) or "not loaded" (never installed)
if [ -e "$PLIST" ]; then rm "$PLIST" && echo "plist removed"; else echo "no plist"; fi
#   expect: "plist removed" (installed) or "no plist" (never installed)
#   "not loaded" and "no plist" together: the job was not installed; nothing to undo
launchctl print "$SERVICE"
#   expect: "Could not find service" and a non-zero exit status (in every case)
```

Without the job installed the guarantee is the one in section 5a: expiry at the deadline
while the server lives, removal at a clean exit, and the next sweep after a SIGKILL.

## 6. Contract (repository side)

- Settings (pool allowlist, `.env.example`): `IDX_CHART_DELIVERY` (on only when exactly
  `1`, and only with `IDX_ANALYSIS_TOOL=1`), `IDX_CHART_DIR` (optional).
- Module `idx_agent.analysis.delivery`: `enabled`, `chart_dir`, `chart_state`
  (`ChartState(on, directory, problem)`), `configured_dir`, `ChartStore`
  (`write(png, owner)`, under the cross-process admission lock; `prune`, which raises
  `OSError` only for an unlistable directory and takes no lock (it only removes);
  `lock_wait`, `expire_in_background`, `expire_due`, `next_check`, `pending`, `stop`,
  `close`), `arm_exit_cleanup(store)`, `owner_for(session)`, `media_reference`, `deliver`,
  `content_blocks`, `store_for(directory)`, `main` (prune command), constants
  `TTL_SECONDS=300`, `SUPERSEDE_GRACE_SECONDS=120`, `STALE_TEMP_SECONDS=60`,
  `EXPIRY_CHECK_SECONDS=15`, `LOCK_NAME=".idx-charts.lock"`, `LOCK_WAIT_SECONDS=2.0`,
  `MAX_FILES=20`, `MAX_BYTES=512 KiB`, `WORKSPACE`, `CHART_NOT_DELIVERED_LINE`, problem
  lines `DELIVERY_FILE_ONLY`, `DELIVERY_ENV_ONLY`, `DIR_DIFFERS`.
- Module `idx_agent.analysis.tool` (WO-027) gains `switch_contradicted`,
  `value_differs` and `KEEP_IN_DOTENV`; `switch_state` is main's (#156): an
  `IDX_ANALYSIS_IMAGE` conflict is off with `IMAGE_DIFFERS`, so charts are off too
  (`ChartState(False)`), and the one problem line is the analysis one: chart delivery
  adds none of its own, as for a contradicted analysis switch
  (`test_an_image_conflict_keeps_charts_off_with_no_chart_line`,
  `test_health_and_start_log_report_an_image_conflict_once`).
- Server: `configure_chart_delivery()` (start, after `register_analysis_tool`),
  `_prune_charts_at_start()` (never raises; False and a `chart_prune` line when the
  directory cannot be listed), `_arm_chart_expiry()` (after the start sweep; with
  delivery on, the exit hook and SIGTERM handler; off, nothing),
  `chart_delivery_problem()`; `health` lists every start-time problem as a warning and
  appends them to its message; `server_start` carries `chart_delivery_problem` only when
  there is one.
- `bounded_analysis` with delivery on returns one text block; `data.chart` gains
  `delivery` and has `image_attached: false`. Off, the result is WO-027's byte for byte.
- Server instructions, tool descriptions and skill descriptions are unchanged (routing
  pins unchanged). The `bounded-analysis` skill body gains the MEDIA-line rule.
- `scripts/install.sh` reports the state; it renders and merges nothing for charts, and
  refuses (exit 1, nothing written) when the environment contradicts `.env`.

## 7. The one-shot live trial: arm, enable, one turn, automatic rollback (not executed)

**Paused.** The trial does not start until the armed rollback below (WO-030 follow-up,
`scripts/chart_trial_armed.sh`, with the signed trial signal, the tombstone and the
fail-safe) is merged, its offline demonstration has passed
(`tests/test_chart_trial_armed.py`, see "Offline evidence" after step 7), and the owner
has lifted the pause. No paid turn is run and nothing is activated before then.
Pretyping `scripts/chart_trial_rollback.sh` in a terminal is not an automatic rollback
and is not the procedure.

Phase 2 is tried **after** Phase 1 (WO-027) has been installed and accepted, as its own
step, so a failure is attributable to chart delivery alone. D5 (2026-11-03) approves
this path for **one** live WhatsApp trial; the trial needs its own `paid` grant (the
trial turn is a paid model call) and the owner's activation approval. Nothing here has
been run.

Owner requirement (2026-11-04): "The procedure must roll back immediately after
completion or failure, without waiting for my reply. Record the rollback and verify
analysis/chart delivery are off. Keeping delivery enabled requires my later approval."
So the trial is one sequence with no pause for review:

**enable (1-3) -> one trial turn (4) -> record the observed result (5) -> roll back (6)
-> verify off (7) -> write the record (8).**

Owner, 2026-11-04 (verbatim): "For chart rollback, use the agent-operated path with a
valid delete grant issued before the trial. Existing delete grants are time-bound, not
command-bound; describe them accurately." and "Pretyping a terminal command does not
provide automatic rollback. Arm cleanup and a timeout before activation, and demonstrate
that cleanup runs without waiting for my reply. Keep the chart trial paused until that
works." So steps 6-7 are **armed before step 1** (step 0a): a watchdog started by the
agent runs them by itself, and nothing in steps 4-7 waits for anyone's reply:

**arm (0a) -> enable (1-3) -> `activated` -> one trial turn (4), `sent` -> the watchdog
rolls back (6) and verifies off (7) -> record (5, 8).**

Owner, 2026-11-04 (verbatim): "For the watchdog, demonstrate that the reply signal comes
from the actual authorized trial—not a simulated or manually supplied acknowledgement.
Also test that late activation cannot re-enable anything after timeout-triggered
rollback. Keep all paid turns and chart activation paused." So a `pass` comes **only**
from the chart_delivery line the tool server signs with this trial's key (below); no
operator word, no hand-written line and no line from another trial can produce one; and
after any rollback the trial is closed by a tombstone and a re-enable is rolled back
again.

- The rollback starts as soon as the trial turn has **completed** (the server's signed
  chart_delivery line, plus a settle so the reply is sent first) or **failed**: no
  signed line within 2 minutes of `sent` (the operator marks the send, step 4), the
  hard timeout (10 minutes after `activated`), `done fail`, or any of steps 1-3 failed
  (`abort`). The operator does not wait for the owner's reply, review or approval, and
  a pass does not keep delivery on.
- The rollback turns **both** switches off: `IDX_CHART_DELIVERY` and
  `IDX_ANALYSIS_TOOL`, so the gateway is back to the 7-tool, 8-skill state of the Phase
  1 off probe (#147, C3a).
- Keeping delivery enabled is **not part of the trial**: it is step 9, a later and
  separate owner decision on the recorded result.

### Step 0. Before anything

The owner has recorded the trial's activation approval and its `paid` grant, Phase 1 is
accepted, and nothing exports `IDX_ANALYSIS_TOOL`, `IDX_ANALYSIS_IMAGE`,
`IDX_CHART_DELIVERY` or `IDX_CHART_DIR` in the shell or the gateway's environment
(they live in `.env` only). Work in the main checkout on `main` after this PR merges.
The owner has issued the delete grant below, and the trial is no longer paused (the
armed-rollback PR is merged and its offline demonstration passed).
Note the start time (UTC) and `openclaw --version`.

### The delete grant (owner, before step 0a)

The rollback deletes (chart files, the launchd plist) and rewrites `.env`, so the agent
runs it only under a `delete` grant. A delete grant is **time-bound, not
command-bound**: `! scripts/guards/consent.sh delete <minutes>` writes one expiry
(at most 240 minutes ahead) to the main checkout's `.local/consent/delete`, and until
then it covers **every** agent deletion, not only the rollback. It names no command and
is not spent by use; it ends at its expiry or at `! scripts/guards/consent.sh revoke
delete`. (Only a `paid` grant is command-bound: one exact command line, one run, a
call ceiling.) The owner issues it **before** step 0a, long enough for the whole armed
window: activation limit + trial timeout + rollback limit (600 s) + 60 s. With the
defaults (600 s + 600 s) that is 31 minutes; `arm` refuses a shorter or missing grant,
reads it without the `IDX_CONSENT_DIR`/project-dir overrides (as the commit gate does)
and prints its expiry. The watchdog keeps blocking a re-enable after the rollback
until that same expiry (below), so a longer grant (60 minutes) gives a longer
post-rollback watch; the grant still covers every agent deletion for that whole time.
Revoking it mid-trial does not stop the armed rollback (turning things off is the
point); the record shows the grant's state when the rollback ran.

```sh
! scripts/guards/consent.sh delete 60     # owner, in the Claude Code prompt; 60 >= 31
```

### Step 0a. Arm the rollback (agent, before step 1)

```sh
mkdir -m 700 <record dir>        # or an existing 700 directory, e.g. the install backups
scripts/chart_trial_armed.sh arm --record-dir <record dir> --log <IDX_LOG_FILE path>
#   expect: "ARMED: <record dir>/chart-trial-<UTC>-<pid>" (the run directory), the
#           watchdog pid, "trial id <32 hex>; its key stays in <run>/trial.key (mode
#           600), never printed", "delete grant: valid until <UTC> ... time-bound, it
#           covers every agent delete until then", the activation deadline, the timeout,
#           the reply wait, the post-rollback watch and "deadline check (agent): by
#           <UTC> run ... status <run>"
#   anything else ("REFUSED: ... Nothing was armed; do not activate."): stop; no step
#   1-3 is run
```

`arm` refuses (exit 1, nothing started, nothing changed) unless
`scripts/chart_trial_rollback.sh` exists, the record directory exists, is owned by the
user and is mode 700, the `--log` file (if given) exists, the bounds hold (activation
limit and timeout 1-1800 s, settle 0-300 s, reply wait 1-600 s, `--watch-after`
0-14400 s) and the delete grant above is valid long enough. Without `--log` (no
`IDX_LOG_FILE` in `.env`, `docs/TRACING.md`) no signed line can be seen and the trial
can only fail; give `--log`. Then it creates the trial: a random 128-bit **trial id**
and a random 256-bit **key**, written once to `<run>/trial.key` (mode 600, inside the
700 run directory; the key is never printed, logged or put in the record), and starts
the watchdog in **its own session** (a new session and process group, as `setsid`
makes; Python standard library, no new dependency, no launchd job): it survives the
agent's shell exiting or being killed, and a gateway restart (it is not the gateway's
child). It holds a lock in the record directory, so one trial is armed at a time
(including its post-rollback watch), writes its pid and the arm time to the run
directory, and waits for the first of:

| Event | Rollback | When |
|---|---|---|
| `scripts/chart_trial_armed.sh abort <run>` (a step 1-3 failed) | `aborted` | within 1 s |
| no `activated` by the activation limit (default 600 s after arming) | `aborted` | at the limit |
| a chart_delivery line in the `--log` file **signed for this trial** (below) | `pass` (status `ready`) or `fail` (`failed`) | settle (default 120 s) later, so the reply and its image are sent first |
| `scripts/chart_trial_armed.sh done <run> fail` (the trial visibly failed) | `fail` | within 1 s |
| no signed line within the reply wait (default 120 s) of `sent` | `fail` | at `sent` + 120 s |
| none of these by the trial timeout (default 600 s after `activated`) | `fail` | at the timeout, a hard bound (it also cuts a settle short) |
| SIGTERM to the watchdog | `aborted` | at once |
| any unexpected exception in the watchdog (fail-safe) | `aborted` | at once; the record names the exception class |
| a `<run>/fired` or `<run>/tombstone` the watchdog did not write (tampering) | `aborted` | within 1 s; the rollback runs anyway |

There is **no manual pass**: `done <run> pass` is refused (exit 2, nothing signalled),
and a `done` file holding anything but `fail` is ignored and recorded as rejected.

**The signed trial signal.** How the server learns the trial: step 1 is
`scripts/chart_trial_armed.sh enable <run>`, which edits `.env` in place to
`IDX_CHART_DELIVERY=1` and `IDX_CHART_TRIAL_FILE=<run>/trial.key` (the path only; the
key stays in the run directory). The tool server reads `IDX_CHART_TRIAL_FILE` from
`.env` (never from the process environment), at start, through the chart-delivery
configuration (`server.configure_chart_delivery`, `delivery.trial_signer`), and **only
when chart delivery is on**; it accepts only an absolute path to a regular file (no
symlink) of this user, mode 600 or tighter, holding a 32-hex id and a 64-hex key. Then
each chart_delivery log line it writes (when `bounded_analysis` delivers a chart, or
fails to) carries `trial_id`, `trial_t` (unix ms) and `trial_mac`, an HMAC-SHA256 with
the key over the trial id, the trace id, the status and `trial_t`. Its `server_start`
line names the trial id (`chart_trial`), never the key; an unusable file gives
`chart_trial_problem` there instead and unsigned lines. The watchdog reads only the
lines appended to the `--log` file after `activated` (following a rename rotation; also
when a gateway log escapes the JSON once) and accepts a line **only** when each of those
fields and `status`/`trace_id` appear exactly once, the status is `ready` or `failed`,
the trial id is this trial's, the HMAC verifies (constant-time compare), and `trial_t`
is after `activated`, by the timeout and not more than 2 s ahead of the watchdog's
clock. Any other chart_delivery line (appended by hand, replayed from an earlier trial,
wrong trial id, bad or missing HMAC, outside the window) is ignored and recorded as
rejected (`<run>/rejected.jsonl`: time and reason only; the first ten also in the
record). Nothing from a line is printed but the trace id of the accepted one. So if no
signed line arrives, the outcome is `fail` (or `aborted`), never `pass`. What this
proves and what it does not: the line came from a process that could read the trial's
600 file, that is, this user's tool server started on this `.env` during this trial. It
does **not** tie the line to the trial turn or to a sender: the MAC covers the trial id,
trace id, status and time and nothing else, and `bounded_analysis` receives no sender or
session value it could add (the agent fills every argument, so one would prove nothing
either). Any tool server started on this `.env` during the window signs its line the
same way: a second owner session (each chat session has its own server, E13), a server
started by hand, or an MCP call the agent makes itself, which is exactly what the
offline test (a) does. Such a line is accepted and the rollback runs `pass`. So the
watchdog's `pass` word means "a tool server on this `.env` signed a chart_delivery line
in the window", not "the trial passed" (its record says so); it does not prove the image
reached the phone either. The trial's result is the step 5 observation (the result in
step 8 is pass only when the image arrived on the phone in reply to the trial message,
whatever word the rollback ran with), and while armed the agent must make no
`bounded_analysis` call or start any tool server of its own (a rule, not something the
watchdog can check). Anyone who can read the run directory as this user could also sign
a line. The protection is against a line the server did not produce for this trial (a
manual or copied acknowledgement), not against this user's own account or processes.

The rollback runs **exactly once**: the watchdog decides one event per poll and claims
the run with an exclusive create of `<run>/fired`, together with `<run>/tombstone`,
under the run's state lock, before it starts `scripts/chart_trial_rollback.sh <word>`; a
second watchdog cannot take the record-directory lock, and one started after the claim
exits without running anything (it checks for the claim again once it holds the lock).
Only the watchdog writes `fired` and `tombstone`, so one that appears while it is still
watching, or is already there when it claims, was written by something else: it is
recorded as tampering ("claim pre-existed (tampered)") and never suppresses the
rollback. The watchdog rolls back `aborted` at once, writes the tombstone if missing and
writes the record. The output goes to `<run>/rollback.log`, the record to
`<run>/record.txt` (step 6). The watchdog inherits the arming shell's permissions: arm
from a shell that may run the rollback itself (unsandboxed, as for step 6 by hand).

**After the rollback: no re-activation.** The tombstone is permanent (never removed).
`enable`, `activated` and `sent` take the same state lock and refuse while it exists
("NOT ARMED: the rollback has already fired (...; tombstone). This trial cannot be
activated again; nothing was changed."), so an activation step either lands before the
claim (and the rollback undoes it) or is refused; a new trial needs a new `arm` and a
new authorization. Because a hand edit or a manual `install.sh` bypasses the helper,
the watchdog also keeps watching after the rollback, until the delete grant's expiry
(or `--watch-after` seconds, whichever is first): if any `IDX_ANALYSIS_TOOL` or
`IDX_CHART_DELIVERY` line in `.env` is not `0`/empty, or install.sh's analysis fragment
(`openclaw.analysis.json5`) is back in the OpenClaw state directory, it runs the
rollback again with the same result word (output in `<run>/rollback-2.log`, ...) and
adds "re-enable blocked <UTC>: <what>; rollback <word> run again" to the record. After
three reruns it stops and the record says to roll back by hand. SIGTERM ends this watch
(recorded); while it runs, `status` says "post-rollback watch running" and a new trial
cannot be armed in the same record directory.

**Not covered by the watchdog: SIGKILL, logout and reboot.** SIGKILL cannot be
handled, and logging out or rebooting the Mac ends the watchdog (its own session does
not survive the user's login session or a restart; it is not a launchd job). Then no
rollback runs and no record is written, and nothing in the watchdog notices. Those
cases are covered by two things outside it: **the agent's deadline check**, `scripts/
chart_trial_armed.sh status <run>` at the trial's latest end (activation + timeout +
the 600 s rollback limit, printed by `arm`) and whenever the agent resumes: it prints
the record (exit 1) after a rollback, or "NOT RUNNING and no record ... Run
scripts/chart_trial_rollback.sh aborted now" (exit 3), and then the agent runs the
rollback by hand at once; and **the owner's by-hand rollback**,
`scripts/chart_trial_rollback.sh aborted` (or the step 6 commands by hand), if the
agent's session is gone too. After a reboot the switches are still on in `.env`, so the
gateway would serve analysis and charts again until that rollback runs.

### Steps 1-3. Enable

Before each step, `scripts/chart_trial_armed.sh status <run>` must exit 0 ("armed"):
if it does not, the rollback has fired; stop and run `scripts/chart_trial_rollback.sh
aborted` again, which undoes any step run after it. If any step fails, run
`scripts/chart_trial_armed.sh abort <run>` (rollback `aborted` within a second). After
step 3 has met every expectation:

```sh
scripts/chart_trial_armed.sh activated <run>
#   expect: "ACTIVATED <UTC>: the watchdog's trial timeout has started"
#   "NOT ARMED: ...": stop, run scripts/chart_trial_rollback.sh aborted now
#   "NOT ENABLED: ...": step 1 was not done with `enable`; abort
```

```sh
# 1. The .env edit, through the helper (IDX_ANALYSIS_TOOL=1 and IDX_ANALYSIS_IMAGE
#    are already set by Phase 1; it refuses, changing nothing, if IDX_ANALYSIS_TOOL is
#    not 1):
scripts/chart_trial_armed.sh enable <run>
#    expect: "ENABLED: .env IDX_CHART_DELIVERY=1, IDX_CHART_TRIAL_FILE=<run>/trial.key"
scripts/install.sh
#    expect: "Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to
#             /Users/<you>/.openclaw/workspace-idx/idx-charts"
#    expect: openclaw.json unchanged compared with the Phase 1 install (no new keys)
# 2. Install the launchd prune job (D6): the install and verify commands of section 5b,
#    including its "(never exited)" re-check.
# 3. Restart the gateway:
openclaw gateway restart
openclaw mcp doctor idx --probe   # expect: 8 tools, including idx__bounded_analysis
openclaw skills list              # expect: 9, including bounded-analysis
grep -c '"chart_trial": "<trial id>"' <IDX_LOG_FILE path>   # expect: 1 or more
#    (the probe's server_start names this trial; "chart_trial_problem" instead: abort)
```

If any expectation in steps 1-3 is not met, stop enabling: the trial result is
`aborted`; signal `abort` (above), and the watchdog runs step 6 at once.

### Step 4. The one trial turn

From the owner's number, send `/new`, then one message: "Chart price against size in
Pasadena." Right after sending, the operator marks it:

```sh
scripts/chart_trial_armed.sh sent <run>
#   expect: "SENT <UTC>: no signed chart_delivery line by <UTC + 2 min> ->
#            rollback fail"
```

That starts the 2-minute no-reply countdown: if the server has not logged a signed
chart_delivery line by then (for example the model answered without calling the tool,
or nothing came back), the watchdog rolls back `fail`. The watchdog does not wait for
any reply or for anyone: it fires on the signed line (+ settle), `done fail`, the
countdown or the hard timeout (which counts from `activated` and holds even if `sent`
is never given). Send nothing else; in particular no "send that chart again" (a second
paid turn). Expiry and the no-resend rule are pinned offline (section 5a), and step 6
removes the chart at once.

### Step 5. Record the observed result (a scratch note; under a minute)

Write down, before doing anything else: the send time and the reply time (UTC); whether
one WhatsApp image (the scatter chart) arrived; whether the caption or the text after
it has the verified figures, the line "Chart: ... follows as an image in this chat. If
no image appears in this chat, the figures above are the whole result." and the
caveats; whether any line starting `MEDIA:` is visible; any `⚠️` line, verbatim; and
the output of:

```sh
ls -l ~/.openclaw/workspace-idx/idx-charts
#   expect: one chart-<32 hex>.png, mode -rw-------
```

**Pass** when one image arrived with that caption line, no `MEDIA:` line and no `⚠️`
line were visible, and `ls` showed the one chart with mode `-rw-------`. Anything else
is **fail**; a step 1-3 failure is **aborted**. The table below says what each failure
means; whatever it shows, go on to step 6 at once.

| Seen | Meaning |
|---|---|
| A visible `MEDIA:idx-charts/...` line, no image | The model formatted the line; text is whole. Delivery path not proven. |
| `⚠️ chart-....png: File not found` | The file was pruned or written elsewhere; check `IDX_CHART_DIR`. |
| `⚠️ chart-....png: Rejected...` or `Delivery failed` | OpenClaw refused the path; check the workspace setting and that `read` is still allowed. |
| `⚠️ Media failed.` | WhatsApp refused the send; text was delivered. |
| "Chart: could not be prepared for this chat" | Server-side failure; the `chart_delivery` log line has the reason code. |
| A text-only reply with WO-027's caption and no image, and `health` says "Chart delivery is misconfigured" | The gateway's environment contradicts `.env` on `IDX_CHART_DELIVERY` or `IDX_CHART_DIR`. |
| No analysis at all, and `health` says "Bounded analysis is misconfigured: IDX_ANALYSIS_IMAGE ..." (no chart line) | The gateway's `IDX_ANALYSIS_IMAGE` differs from `.env`: the tool is not registered (#156), so charts are off with it. |
| The reply says "attached" or "sent" but no image arrived | Wording defect. |
| No reply within 2 minutes of `sent` | Fail (the watchdog's countdown); the cause is investigated after the rollback, from the logs. |

The fixes these rows point to are made after the rollback, never during the trial;
trying again is a new trial and needs a new authorization.

The `ls -l` above is done while the watchdog settles (it prunes the chart in step 6).
The owner's observations of the phone (image, caption, warning lines) may arrive after
the rollback; they go into the step 8 record and never delay the rollback.

### Step 6. Roll back, now (the watchdog does it)

The armed watchdog runs, by itself and once:

```sh
scripts/chart_trial_rollback.sh pass      # or fail, aborted: the watchdog's result word
```

and writes `<run>/record.txt`: the run, the arm time and watchdog pid, the delete grant
(at arm and when the rollback ran), the activation and the signal or timeout, the
result word with its reason, fired and finished times and the exit status, then the
rollback's own output, which ends with the record block below.
`scripts/chart_trial_armed.sh status <run>` prints it once written. The operator runs the rollback by hand
only when the wrapper says `NOT ARMED`, or to repeat an incomplete one.

It runs these, in order, each one even when an earlier one failed, and reports each
(the manual equivalent, if the script cannot run, is the same commands by hand):

1. `.env`: every `IDX_ANALYSIS_TOOL=` and `IDX_CHART_DELIVERY=` line (an `export`
   line too) is **edited in place** to `=0`. Appending a line does not work: the first
   line for a key wins (`dotenv_values`). Other lines and the file mode are kept. By
   hand: change those lines in an editor, then
   `grep -nE '^[[:space:]]*(export[[:space:]]+)?IDX_(ANALYSIS_TOOL|CHART_DELIVERY)[[:space:]]*=' .env`
   must show only lines ending in `=0`.
2. `scripts/install.sh` (expect: exit 0, no "Bounded analysis is on" and no "Chart
   delivery is on" line; it removes `~/.openclaw/openclaw.analysis.json5`).
3. `openclaw gateway restart`.
4. `.venv/bin/python -m idx_agent.analysis.delivery prune --all` (expect: "removed N
   chart file(s)"; only our chart and temp names; the lock file stays).
5. The launchd prune job, guarded (the section 5b uninstall): `launchctl bootout` only
   if `launchctl print` finds the job, `rm` of the plist only if it exists. Neither
   present is reported as "not installed", not as an error (for example when step 2
   never ran).

### Step 7. Verify that analysis and chart delivery are off

The script then checks, and prints, each of these; by hand they are:

```sh
.venv/bin/python -c "from idx_agent.analysis import delivery; \
from idx_agent.db.pool import dotenv_values as v; d = v(); \
print(d.get('IDX_ANALYSIS_TOOL') == '1', d.get(delivery.SWITCH) == '1')"
#   -> False False            (IDX_ANALYSIS_TOOL and IDX_CHART_DELIVERY off in .env)
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
s.configure_chart_delivery(), s.analysis_switch_problem(), s.chart_delivery_problem()); \
h = s.health_result(); print(h.warnings, 'analysis' in h.message.lower(), \
'chart' in h.message.lower())"
#   -> False False False None None   (bounded_analysis absent; chart_state off)
#   -> [] False False                (health: no analysis or chart line)
openclaw mcp doctor idx --probe | grep -c bounded_analysis   # -> 0 (7 tools)
openclaw skills list | grep -c bounded-analysis              # -> 0 (8 skills)
ls ~/.openclaw/openclaw.analysis.json5                       # -> No such file or directory
launchctl print "gui/$(id -u)/local.idx-exchange.chart-prune"
#   -> "Could not find service ..." and a non-zero exit status
ls ~/.openclaw/workspace-idx/idx-charts                      # -> nothing listed
```

The script ends with its record block. A complete rollback looks like this (the job
was installed; for a job never installed the launchd line reads `not installed`):

```text
chart trial rollback record (WO-030, D5)
  trial result: pass
  rollback started: <UTC>  finished: <UTC>
  step .env: IDX_ANALYSIS_TOOL 1 line(s) set to 0, IDX_CHART_DELIVERY 1 line(s) set to 0
  step install.sh: ok
  step gateway restart: ok
  step prune --all: removed 1 chart file(s)
  step launchd prune job: booted out, plist removed
  verify .env: IDX_ANALYSIS_TOOL off, IDX_CHART_DELIVERY off
  verify server: bounded_analysis absent (not listed), chart_state off, problems None / None
  verify health: 0 warning(s), no analysis/chart line
  verify chart files: 0
  verify mcp doctor: bounded_analysis listed 0 time(s)
  verify skills: bounded-analysis listed 0 time(s)
  verify analysis fragment: absent
  verify launchctl: Could not find service
ROLLBACK DONE: analysis off, chart delivery off
```

Exit status 0 only with `ROLLBACK DONE`. Otherwise the last line is `ROLLBACK
INCOMPLETE: <the failed steps and checks>` and the exit status is 1: fix what it names
(for example an exported switch, which makes `install.sh` refuse) and run the script
again with the same result word. It is safe to repeat: a rerun edits the same lines to
the same value, prunes nothing more and reports the job as not installed. Do not turn
anything back on to get past a failure.

Offline evidence (`tests/test_chart_trial_rollback.py`, 7 test functions, 9 collected
cases): the script, copied
into a throwaway repository with a temp `HOME` and state directory and stub
`openclaw`, `node` and `launchctl` that answer from the files the steps change, prints
exactly the block above (installed and never-installed job), edits every switch line in
place (an `export` line and a repeated key included) and keeps the file mode, keeps
going after a failed gateway restart and reports `ROLLBACK INCOMPLETE: gateway
restart`, does not report off while a shell still exports `IDX_ANALYSIS_TOOL=1`,
changes nothing for a bad argument, and never bootstraps or loads anything.

Offline evidence for the armed flow (`tests/test_chart_trial_armed.py`, 28 test
functions, 53 collected cases: 24 single, plus 2 hand-written-claim cases, 7 refusal
cases, 13 signal-judging cases and 7 unusable-trial-file cases), in the same kind of
throwaway repository plus a delete grant in that repository's own consent directory, a
700 record directory, a plain-JSON `openclaw.json` (as on the Mac) and the server log
the watchdog tails; no process is given any input, nothing is paid for, sent or
activated. (a) Arm, `enable`, `activated`, then one **real** `bounded_analysis` call
over an in-process MCP session (the tool server started on the `.env` that `enable`
wrote, `IDX_LOG_FILE` the watched log, the fake docker worker drawing the scatter chart
of the invented sample): the server's own code writes the signed chart_delivery line,
the watchdog verifies it and rolls back `pass` one settle later by itself, naming the
call's trace id; the key appears in no log, output, record or result. (b) Lines in the
right format appended by hand after activation (unsigned; this trial's id with a made-up
HMAC; signed with another key): all three rejected and recorded, the run ends at the
timeout, `fail`. (c) Trial 1 passes on its server line; trial 2 is armed in the same
record directory and that exact line, and the same line relabelled with trial 2's id,
are appended: rejected ("another trial's id", "HMAC does not verify"), `fail`. (d) `done
pass` is refused (exit 2) and a hand-written `done` file saying `pass` is rejected:
`fail` at the timeout; `done fail` rolls back `fail` at once. (e) After the timeout
rollback has claimed the run, `enable`, `activated` and `sent` are refused (tombstone),
during and after the rollback; a re-enable forced by editing `.env` is rolled back again
by the post-rollback watch ("re-enable blocked", a second restart), and SIGTERM ends
that watch; `enable` retried in a tight loop across the activation-limit rollback: every
attempt that began after the claim is refused, and `.env` ends off with one rollback.
(f) A corrupt `activated` file makes the watchdog raise TypeError: the fail-safe rolls
back `aborted` and records the class; a `fired` or `tombstone` file written by hand
after `enable` rolls back `aborted` at once (not suppressed), with the tombstone and the
record. (g) A signed line, `done fail`, `abort` and the timeout land together and a
second watchdog is started during and after: one rollback, one restart. Also: `sent`
plus no signed line for the reply wait -> `fail` before the timeout; no signal -> `fail`
at the timeout; `abort` -> `aborted`; never `activated` -> `aborted` at the limit and
late steps refused; the arming shell's process group killed -> the watchdog still fires;
SIGTERM -> `aborted`; SIGKILL -> no rollback, and `status` says "NOT RUNNING and no
record" (exit 3) with the by-hand rollback; `activated` needs `enable`, and `enable`
needs Phase 1; the seven arm refusals; the judging rules case by case (escaped once,
other trial, other key, edited status or trace id, before `activated`, after the window,
ahead of the clock, repeated fields, other events); the watchdog and the server sign the
same bytes; the server reads the trial file only with chart delivery on, refuses a
relative, missing, symlinked, group-readable, malformed or wrong-id file or a directory,
and its start line names the trial id, never the key. Fail-before: on `c5ace93`
(archive, this test file copied in) 42 of the 51 fail and the 9 unchanged ones pass (the
7 refusals, `activated` without a watchdog, the grant arithmetic); with only the new
server code on `c5ace93`, 32 fail (every watchdog behaviour); with only the new
watchdog, 27 fail (every case that needs the server's signature). All 51 passed on
`0c80870`; there, the 2 hand-written-claim cases fail (a hand-written `fired` let the
watchdog exit with no rollback and no record; a hand-written tombstone was ignored until
the activation limit), and so do (a) (its record did not yet say what a signed `pass`
does not prove) and (c) (its rejection reason, reworded from "replayed or other sender"
to "replayed or another run"); the other 49 pass. All 53 pass here.

### Step 8. Write the record

After `ROLLBACK DONE` (or, if it stays incomplete, with what is still on), append one
entry to `docs/EVIDENCE_LOG.md` (append-only) and one dated entry to WO-030's Status,
aggregates only (no phone number, no chat text beyond the fixed request):

```text
- <date>, WO-030: one-shot live WhatsApp chart trial (D5). Activation approval and paid
  grant: <where they are recorded>. OpenClaw <version>.
  Trial: started <UTC>; trial turn sent <UTC>; reply <UTC or "none within 2 min">.
  Result (step 5, not the rollback's word): <pass | fail | aborted at step N>.
  Image: <yes/no>. Caption line: <yes/no>.
  MEDIA line visible: <yes/no>. Warning line: <verbatim or none>.
  ls: <one chart-<hex>.png, -rw------- | other, as seen>.
  Rollback: run at once, without waiting for review; started <UTC>, finished <UTC>;
  <the script's record block, verbatim, or the manual step results>.
  State now: analysis off, chart delivery off. Keeping delivery enabled was not
  decided by the trial; it needs the owner's approval of this entry.
```

WhatsApp delivery is verified only by a recorded pass; a fail or an aborted trial
leaves it UNVERIFIED and the requirement not met, even though the text was whole.

### Step 9 (separate, not part of the trial). Keeping delivery enabled

Only after the owner has read the step 8 record of a **pass** and approved, in writing,
keeping chart delivery enabled, the operator repeats steps 1-3 (with `IDX_ANALYSIS_TOOL`
edited back to `=1` first) as a new activation and records it. No approval, or no reply,
means delivery stays off; a fail or an aborted trial cannot be approved into "on", only
into a new authorized trial.

Residue after the rollback: no config keys beyond the `.env` line
`IDX_CHART_TRIAL_FILE=<run>/trial.key`, which is inert while `IDX_CHART_DELIVERY` is 0
(the server reads it only with delivery on; the next trial's `enable` replaces it);
the run directory with its tombstone and the trial file (mode 600; the key signs nothing
once that trial's watchdog has ended); the `idx-charts` directory with only the empty
lock file `.idx-charts.lock` (`ls` lists nothing; `ls -A` lists that one file).
Removing the directory or the line is optional and the owner's decision.
