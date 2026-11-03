# Chart delivery to WhatsApp (WO-030 proposal and contract)

Status: built and tested offline behind `IDX_CHART_DELIVERY` (off). **Actual WhatsApp
delivery is UNVERIFIED** until the operator acceptance check in section 7 passes on the
owner's phone. Until then the requirement "charts are delivered to users" is not met;
the text-only answer (WO-027) stays and remains complete on its own.

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
| E13 | Each session gets its own MCP runtime (servers keyed by session id); this design does not rely on it. | `dist/agent-bundle-mcp-manager-api-DswOxDdW.mjs:387-391`; `dist/agents/agent-bundle-mcp-runtime.js:99-140` |
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
   `MEDIA:/absolute/path/chart-<token>.png`, and `data.chart.delivery` says
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

### How each constraint is met

| Constraint | Mechanism |
|---|---|
| No broad messaging | No new tool, no `message` tool, no policy change. A MEDIA line can only attach media to the reply OpenClaw is already sending to the requesting chat (E8, E9). |
| No arbitrary file access | The server writes only into one directory whose last part must be `idx-charts`; the path is absolute, without `..`, whitespace or quotes; the directory must sit in an existing parent (the workspace is never created), must be a real directory owned by this user (a symlink is refused), and is set to mode 700; files are created with `O_EXCL|O_NOFOLLOW`, mode 600. OpenClaw's own read policy is unchanged (the model could already name workspace files; nothing new becomes readable). |
| No public URL | Local path only; OpenClaw copies the bytes into its own store before sending (E6). |
| Session/recipient isolation | The line is returned only in the tool result of the request that drew the chart; reply routing sends it only to that request's chat (E8, E9). Another session cannot learn a 128-bit name: there is no listing tool (`group:runtime` and `write` are denied), the directory is mode 700, and only the owner's number may message the agent. Tests check that two concurrent sessions never see each other's line. |
| PNG validation | `png_size` from WO-017: PNG signature, CRC on every chunk, only IHDR/pHYs/IDAT/IEND, 8-bit RGBA, no interlace, IDAT inflates (bounded) to exactly the expected scanlines; width 200-2000 and height 150-1500, below WhatsApp's 2048 px side. |
| Bounded size | 512 KiB (the renderer cap); a caller may lower it, never raise it. WhatsApp's cap is 50 MB. |
| Retention | Only our names (`chart-<32 hex>.png`, `.chart-<32 hex>.tmp`), only regular files, never symlinks or subdirectories, never anything else in the directory. Removed after 300 s, beyond the newest 20, at server start, and before every write; `python -m idx_agent.analysis.delivery prune [--all]` for the operator. |
| Delivery failures | Server side (bad directory, missing workspace, invalid PNG, write error): the caption becomes "Chart: could not be prepared for this chat this time; the figures above are the whole result.", `data.chart.delivery` is `{"status": "failed", "reason": <code>}`, and one `chart_delivery` log line records the code (never the path). OpenClaw side: a missing or refused file adds `⚠️ chart-....png: <reason>` to the reply (E6); a WhatsApp send failure sends `⚠️ Media failed.` with the caption (E9). The figures and caveats are in the text either way. |
| At most once | One new file and one line per request; a token is never reused (`O_EXCL`, and a taken name is refused). Within a reply OpenClaw sends a source once (E6). After 120 s a newer chart from the same process removes this process's older ones, and every file is gone after 300 s, so a line repeated later yields a "file not found" note, not a second image. The skill forbids repeating the line. Residual: a model that repeats the line in a later reply within that window would resend the same chart to the same chat (never to another chat). |
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
- **Path in text.** The absolute path (it contains the macOS user name) is visible to
  the model and, if the model mis-formats the line, to the owner's own chat.
- **Retention window.** Files live up to 300 s, longer if no request or restart follows;
  the prune command removes them.

## 6. Contract (repository side)

- Settings (pool allowlist, `.env.example`): `IDX_CHART_DELIVERY` (on only when exactly
  `1`, and only with `IDX_ANALYSIS_TOOL=1`), `IDX_CHART_DIR` (optional).
- Module `idx_agent.analysis.delivery`: `enabled`, `chart_dir`, `ChartStore`
  (`write`, `prune`), `deliver`, `content_blocks`, `store_for`, `main` (prune command),
  constants `TTL_SECONDS=300`, `SUPERSEDE_GRACE_SECONDS=120`, `MAX_FILES=20`,
  `MAX_BYTES=512 KiB`, `CHART_NOT_DELIVERED_LINE`.
- `bounded_analysis` with delivery on returns one text block; `data.chart` gains
  `delivery` and has `image_attached: false`. Off, the result is WO-027's byte for byte.
- Server instructions, tool descriptions and skill descriptions are unchanged (routing
  pins unchanged). The `bounded-analysis` skill body gains the MEDIA-line rule.
- `scripts/install.sh` reports the state; it renders and merges nothing for charts.

## 7. Operator activation and acceptance (not executed)

Phase 2 is activated and accepted **after** Phase 1 (WO-027) has been installed and
accepted, as its own step, so a failure is attributable to chart delivery alone.
Each step needs the owner's go; the live chat turn is a paid model call and needs its
own `paid` grant.

Activation:

```sh
# 1. In the repo checkout on the main branch after this PR merges, in .env:
#      IDX_CHART_DELIVERY=1      (IDX_ANALYSIS_TOOL=1 and IDX_ANALYSIS_IMAGE already set)
scripts/install.sh
#    expect: "Chart delivery is on (IDX_CHART_DELIVERY=1): charts are written to
#             /Users/<you>/.openclaw/workspace-idx/idx-charts"
#    expect: openclaw.json unchanged compared with the Phase 1 install (no new keys)
openclaw gateway restart
```

Smallest live check (one WhatsApp turn from the owner's number):

1. Send: "Chart price against size in Pasadena."
2. Expect within about a minute: one WhatsApp image (the scatter chart) whose caption,
   or the text right after it, has the verified figures, the line "Chart: ... follows
   as an image in this chat. If no image appears in this chat, the figures above are
   the whole result." and the caveats. No line starting `MEDIA:` is visible.
3. Expect no `⚠️` line. On the Mac: `ls -l ~/.openclaw/workspace-idx/idx-charts` shows
   one `chart-<32 hex>.png`, mode `-rw-------`, and is empty again after five minutes and
   one more request (or after the prune command).
4. Send: "Send that chart again." Expect no second image of the same file (a new
   analysis may draw a new chart; the old line must not be repeated).

Pass: step 2 shows the image and steps 3-4 hold. Record the result (date, OpenClaw
version, pass/fail) in WO-030's Status. Fail modes and what they mean:

| Seen | Meaning |
|---|---|
| A visible `MEDIA:/...` line, no image | The model formatted the line; text is whole. Delivery path not proven. |
| `⚠️ chart-....png: File not found` | The file was pruned or written elsewhere; check `IDX_CHART_DIR`. |
| `⚠️ chart-....png: Rejected...` or `Delivery failed` | OpenClaw refused the path; check the workspace setting and that `read` is still allowed. |
| `⚠️ Media failed.` | WhatsApp refused the send; text was delivered. |
| "Chart: could not be prepared for this chat" | Server-side failure; the `chart_delivery` log line has the reason code. |

Rollback:

```sh
# remove IDX_CHART_DELIVERY from .env (or set it empty), then
scripts/install.sh
openclaw gateway restart
.venv/bin/python -m idx_agent.analysis.delivery prune --all
#    expect: "removed N chart file(s)"; bounded_analysis is back to WO-027's text reply
```
