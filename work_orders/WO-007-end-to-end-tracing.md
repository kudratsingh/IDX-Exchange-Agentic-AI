# WO-007 — End-to-end tracing

**Driver:** agent builds; human runs the one WhatsApp turn (and any `openclaw` command) and records it.
**Depends on:** WO-004 (search tool, log line), WO-005 (CI), WO-006 (merged in PR #21: mode, key prefix,
meta keys in the log line; ADR-0005)
**Estimated effort:** 3-4 hours (the spike is time-boxed to 45 minutes of that)

## Objective
One WhatsApp request is visible as one trace in a local viewer: OpenClaw's turn spans (inbound message,
model run, the `idx__search_listings` tool call) and our tool's stage spans (validate, merge, query,
count, format) on one timeline, with every attribute on our side passed through the redaction rules and
an allowlist. When the collector is down nothing on our side is lost: every log line our server writes
also lands in a gitignored, rotating local file.

## Why
Today the two halves cannot be joined: OpenClaw passes no id into an MCP call (ADR-0005, WO-006 spike:
`meta_keys: []` on every call), and our server's stderr, where the `tool_call` line goes, is dropped by
the gateway log, so a slow or wrong reply cannot be traced from message to SQL. The human asked for
end-to-end tracing on 2026-09-24, after being told it needs a local collector, OpenClaw exporting to it
over OTLP, and our server emitting its own spans with a shared id that OpenClaw does not pass today.

## Inputs
- `src/idx_agent/observability/logging.py`: `redact()`, `log_event()` (one redacted JSON line to
  stderr), `new_trace_id()` (16 hex), `Timer`.
- `src/idx_agent/mcp_server/server.py`: `_guarded()` writes one `tool_call` line per call with the trace
  id, tool, ok, ms, error category, `meta_keys`/`meta_shape`, and the body's fields (mode, `key_prefix`,
  validated `filters`, rows, `total_matches`, `skipped`, `clarification`/`field`, `cleared`,
  `last_page`, `count_error`, `error_type`); `search_result()` / `_search_body()` hold the stages;
  `health_result()`.
- `src/idx_agent/db/pool.py`: the `.env` fallback is an explicit name allowlist, because the server
  OpenClaw starts has no shell environment (WO-006 deviation).
- `config/openclaw.idx.json5`, `scripts/install.sh`, `scripts/openclaw_merge_config.py`,
  `tests/test_openclaw_merge_config.py`.
- ADR-0005 and the WO-006 Status "Spike result": no runtime identity on stdio; the MCP process lives
  across turns; stderr was only visible by copying it to a scratch file.
- Local OpenClaw doc digest, gateway partition (read 2026-09-23): `diagnostics.otel.*` is off by
  default, has a `logsExporter` setting (`"stdout"` documented; the OTLP form is to be confirmed), and
  `captureContent` is off by default; the audit ledger records `tool.action.started` / `finished` with
  tool name, session key, run id, and status; OpenClaw's own file logs are JSON lines under
  `/tmp/openclaw/`, pruned after 24 hours; unknown config keys stop the gateway from starting. The
  `/gateway/opentelemetry/*` pages were not digested, so the exact span names and attributes are unknown.
- `docs/DECISIONS.md` (a new dependency or infrastructure needs a note in the WO and an ADR),
  `docs/SAFETY_INVARIANTS.md`, `docs/AGENT_RULES.md` section 1 (logs are protected from deletion).

## In scope
- **Early-start spike (first task, before any build code; 45 minutes; result recorded in Status).**
  Questions, in order: (a) what OpenClaw's OTLP export actually emits for one tool call (span or log
  names, the ids each carries: trace id, span id, run id, session key, tool call id); (b) whether any
  exported value can be matched to our side (does `_meta` start carrying a `traceparent` or any id once
  diagnostics are on? our `meta_keys` field shows it without logging a value); (c) whether the runtime
  can be told by config to pass a trace id into an MCP call; (d) whether any exported attribute carries
  the raw sender number or message text (session key, peer id, captured content). First try the
  gateway's direct tool invocation (no model turn, no cost); if its path does not produce the same
  spans as an agent turn, one WhatsApp turn from the owner number under a human `paid` token.
  **Decision rule.** A runtime id reaches the call (b or c): our root span becomes a child of OpenClaw's
  tool span, so the request is one trace. None does: correlation by session key and a timestamp window
  (OpenClaw's tool span for `idx__search_listings` and our `idx.tool_call` span start within a stated
  window, one sender's session, one call at a time), shown side by side in the viewer and documented
  step by step in `docs/TRACING.md`. The chosen branch and the window go into ADR-0006.
- **Collector.** One free, local, loopback-only collector: a single binary or a Docker container, for
  example Jaeger all-in-one (OTLP in, trace UI) or the OpenTelemetry Collector (with a file exporter,
  and a processor that can drop or rewrite attributes before storage), or the Collector feeding Jaeger.
  No hosted service, no account, no paid tier. The choice, how it is started and stopped, and where it
  keeps data go into ADR-0006 with the rejected options.
- **ADR-0006 and the dependency note.** New dependency: `opentelemetry-sdk` and one OTLP exporter
  (`opentelemetry-exporter-otlp-proto-http` preferred over gRPC to avoid a compiled dependency), pinned
  with upper bounds like the existing ones, as an optional `tracing` extra that `dev` also pulls in so
  CI can test spans. New infrastructure: the local collector. Both are recorded here and in ADR-0006.
- **Our instrumentation.** `src/idx_agent/observability/tracing.py`: setup from the environment, a span
  helper, and the attribute allowlist. One root span per tool call (`idx.tool_call`) opened in
  `_guarded()`, and one child span per stage in `search_listings` (validate, merge, query, count,
  format) and one in `health`. Attributes come only from the fields the log line already carries,
  filtered by the allowlist, then passed through `redact()`. Never listing remarks, never the raw sender
  id, never a row, never the unvalidated input.
- **OpenClaw side.** The diagnostics keys that turn on OTLP export to the local collector, added to
  `config/openclaw.idx.json5` and rendered by `scripts/install.sh` only when `IDX_OTLP_ENDPOINT` is set
  (unset: nothing tracing-related is rendered, and the render is identical to today's). `captureContent`
  stays off. The gateway must start and serve with the collector stopped.
- **File fallback.** With `IDX_LOG_FILE` set, `log_event()` also appends every line (the same redacted
  record) to that file and rotates it by size. Default suggested path `logs/idx-agent.log` in the repo,
  which the current `.gitignore` already covers (`logs/`, `*.log`); `IDX_LOG_FILE` and the new
  variables join the `.env` fallback allowlist in `db/pool.py`.
- **`docs/TRACING.md`.** How to start the collector, send one message, find the trace, line up the two
  sides (by runtime id, or by session key and time window), read the fallback file, and what is
  redacted or dropped on each side.

## Out of scope
Hosted tracing services of any kind; metrics, dashboards, and alerting; token or cost tracking; changing
the `tool_call` log line format or its fields; tracing OpenClaw internals beyond what its own exporter
emits; patching or vendoring OpenClaw; anything paid beyond the one WhatsApp turn under a `paid` token;
spans for tools that do not exist yet (market, recommend, RAG, email); persisting traces beyond the
collector's local store.

## Files expected to change
`src/idx_agent/observability/tracing.py` (new), `src/idx_agent/observability/logging.py`,
`src/idx_agent/mcp_server/server.py`, `src/idx_agent/db/pool.py` (fallback allowlist names only),
`pyproject.toml` (the `tracing` extra), `config/openclaw.idx.json5`, `scripts/install.sh`,
`scripts/openclaw_merge_config.py` (only if the gated render needs it), `config/otel-collector.yaml`
(new, only if the chosen collector takes a config file), `tests/test_tracing.py` (new),
`tests/test_log_file.py` (new), `tests/test_mcp_search.py`, `tests/test_mcp_health.py`,
`tests/test_openclaw_merge_config.py`, `tests/test_db_pool.py`, `.env.example` (names, no values),
`README.md` (one line), `docs/TRACING.md` (new), `docs/adrs/0006-local-tracing.md` (new),
`docs/ARCHITECTURE.md` (the observability line), `docs/EVIDENCE_LOG.md` (the manual run),
`.gitignore` only if a path is not already covered (needs a human `gates` token).

## Interfaces and contracts
Span names (ours):

| Span | Where | Opened when |
|---|---|---|
| `idx.tool_call` | `_guarded()` | every call; root of our side |
| `idx.search.merge` | store read and mode resolution | every `search_listings` call past the reset shortcut |
| `idx.search.validate` | `PropertySearchFilters.from_input` | inside merge; may nest under it, no refactor to split them |
| `idx.search.query` | as-of read and the page query | only when validation passed and a database is configured |
| `idx.search.count` | the COUNT query | only when the page alone cannot tell the total |
| `idx.search.format` | `format_search_reply` | only on a result with listings or an empty page |
| `idx.health.check` | `health_result()` | every `health` call |

Attribute allowlist (anything else is dropped before export; values are primitives or lists of them):
`idx.trace_id` (the log line's trace id), `idx.tool`, `idx.ok`, `idx.error`, `idx.error_type`,
`idx.mode`, `idx.key_prefix` (8 hex characters, as in the log), `idx.filters.<field>` (one per validated
`PropertySearchFilters` field, flattened), `idx.rows`, `idx.skipped`, `idx.total_matches`,
`idx.clarification`, `idx.field`, `idx.cleared`, `idx.last_page`, `idx.count_error`, `idx.meta_keys`.
Resource: `service.name = "idx-mcp"`, `service.version`. `meta_shape` stays in the log line only.

```python
def tracing_enabled() -> bool                            # True only with a loopback endpoint and the SDK present
def span(name: str, **attrs: object) -> ContextManager   # no-op when tracing is off
def span_attributes(fields: Mapping[str, object]) -> dict[str, AttrValue]   # allowlist, flatten, redact
```

Environment variables (all optional; unset means today's behaviour):

| Variable | Meaning |
|---|---|
| `IDX_OTLP_ENDPOINT` | OTLP/HTTP endpoint of the local collector; must be a loopback host, anything else is refused with one warning |
| `IDX_LOG_FILE` | path of the fallback log file; relative paths resolve against the server's working directory |
| `IDX_LOG_FILE_MAX_BYTES` | rotation size, default 10 MB |

OpenClaw keys: the `diagnostics.otel.*` keys confirmed by the spike (enable, endpoint, protocol,
`captureContent: false`), rendered only when `IDX_OTLP_ENDPOINT` is set; the exact names are verified
against the gateway's config schema before they are committed, since an unknown key stops the gateway.

## Implementation requirements
1. No span attribute outside the allowlist; the filter runs before `redact()` and before export, and a
   test fails if a new attribute name appears without an allowlist entry.
2. `redact()` is applied to every attribute value and to every span name built from data (none should
   be; span names are fixed strings).
3. Spans are created only when `tracing_enabled()` is true; otherwise `span()` is a no-op context
   manager, the SDK is not imported, and no exporter, thread, or socket exists (zero overhead).
4. `IDX_OTLP_ENDPOINT` must resolve to a loopback address; any other host is refused, logged once, and
   the server runs without spans.
5. Export is batched and non-blocking; a collector that is down or slow never delays or fails a tool
   call, and the failure is logged at most once per interval, not per span.
6. The root span carries `idx.trace_id` equal to the log line's and the result's `provenance.trace_id`.
   When a runtime id is available (spike branch), it is used as the parent context; our own 16-hex
   trace id stays as it is.
7. Tests never need a collector or a network: they use the SDK's in-memory exporter.
8. The gateway starts, and `health` answers, with the collector stopped (checked by the human with the
   gateway status and the MCP probe; no model turn needed).
9. The install render with `IDX_OTLP_ENDPOINT` unset is byte-identical to today's; with it set, only
   the diagnostics keys are added.
10. `IDX_LOG_FILE`: every `log_event()` record is appended as one whole line (one write per line, safe
    with more than one server process on the same path); stderr output is unchanged. At the size limit
    the file is renamed to a timestamped archive beside it and a new file is started; no archive is
    ever removed by code (pruning is a human act under a `delete` token, per `AGENT_RULES.md`).
11. The log file's path and its archives must be gitignored. They are under `logs/` and match `*.log`
    today (checked with `git check-ignore -v`); if the chosen names are not covered, `.gitignore` gains
    the path, which needs a human `gates` token, and the agent stops until it is granted.
12. CI is unchanged except that the new unit tests run in the existing job; no collector in CI.

## Safety requirements
- Redaction on every attribute, the allowlist in front of it; no PII in span names or attributes: no
  phone number, email, raw sender id, full sender key, listing remarks, row, or unvalidated user text.
- OpenClaw side: `captureContent` stays off. If its exported spans carry the sender number or message
  text (session key, peer id), the collector drops or rewrites that attribute before storage (never an
  unkeyed hash of a number); if that is not possible, stop (see below).
- The collector binds to loopback only and exports to nothing outside the machine; its stored traces and
  any file exporter output live under a gitignored path.
- The fallback log file is gitignored, holds only the already-redacted lines, and falls under the
  run-artifact rule of `AGENT_RULES.md`: never deleted, truncated, or overwritten without a human
  `delete` token.
- Tracing never changes a tool's behaviour or result; a tracing failure is never an error to the user.
- Secrets stay in the environment; the endpoint is not a secret, but no auth header or token is added.

## Tests required
Unit (CI, no collector, no database, no model): the attribute allowlist (an unknown key is dropped; the
list is pinned so an addition must be deliberate); redaction applied to attribute values (an email- or
phone-shaped value in a field comes out redacted); a `sender_id` passed to the tool never appears in any
span or attribute; tracing off (no endpoint, or a non-loopback one) creates no spans and does not import
the SDK; tracing on with the in-memory exporter: one root plus the expected stage spans for a result, a
Clarification (no query span), a reset, a database error, and `health`; the root's `idx.trace_id`
matches the result; the file fallback appends whole lines, rotates at the size limit into an archive
without removing any, and survives two writers on one path; the install render with and without
`IDX_OTLP_ENDPOINT`; the new names in the `.env` fallback allowlist.
Integration: WO-004 and WO-006 `db` tests pass unchanged.
Evals: none new; the `ci` suite must still pass.
Manual (human, recorded in Status with the date and a redacted description): collector running, one
WhatsApp search from the owner number under a `paid` token, the trace found in the viewer with
OpenClaw's spans and ours lined up by the chosen rule; then the collector stopped, one `health` probe,
and the same call present in the fallback file.

## Acceptance criteria
- The spike result, the correlation branch (runtime id, or session key plus a stated time window), and
  the collector choice are in Status and ADR-0006 before any build commit.
- One WhatsApp turn shows OpenClaw's tool call and our `idx.tool_call` with its stage spans in one local
  viewer, as one trace or lined up by the documented rule without ambiguity.
- No span attribute outside the allowlist; no raw sender id, remarks, row, or contact field in any span,
  exported OpenClaw attribute that reaches storage, or log line.
- With `IDX_OTLP_ENDPOINT` unset, the server creates no spans, and the rendered OpenClaw config is
  identical to today's.
- The gateway starts and `health` answers with the collector down.
- With `IDX_LOG_FILE` set, every tool call's line is in the file; rotation keeps every archive; the
  file and archives are gitignored.
- All unit tests, `db` tests, and the `ci` eval suite pass locally and in CI; ruff is clean.
- `docs/TRACING.md` lets someone who did not build this find the trace for one message.

## Verification commands
```
pytest -q tests/test_tracing.py tests/test_log_file.py tests/test_mcp_search.py tests/test_mcp_health.py
pytest -q                                               # unit
MYSQL_HOST=localhost pytest -q -m db                    # integration, local only
ruff check . && ruff format --check .
python -m evals.run --suite ci
git check-ignore -v logs/idx-agent.log                  # and one archive name
# human: start the collector as in docs/TRACING.md, re-run scripts/install.sh with IDX_OTLP_ENDPOINT set,
#        check the gateway and the MCP probe, then the one WhatsApp turn under a `paid` token
# human: stop the collector, probe `health` again, and find its line in the fallback file
```

## Deliverables
The spike result and ADR-0006 (collector, dependency, correlation branch); `observability/tracing.py`
with the allowlist; stage spans in `search_listings` and `health`; the `IDX_LOG_FILE` fallback with
rotation; the gated OpenClaw diagnostics config; `docs/TRACING.md`; one recorded end-to-end trace.

## Stop conditions
- OpenClaw's OTLP export cannot be enabled for this agent only (it is gateway-wide; idx is the only
  agent today, so report it and let the human decide), or it carries raw sender numbers or message text
  that neither OpenClaw config nor the collector can drop before storage.
- The collector cannot run locally without an account, a hosted backend, or a paid tier.
- The runtime cannot be made to pass any correlation id, and timestamp correlation proves ambiguous
  (two candidate spans inside the window, or none).
- A diagnostics key the build needs is not in the gateway's config schema.
- Any requirement would need a `.gitignore`, CI, or guard change without a human `gates` token, or would
  delete or prune a log without a `delete` token.

## Status
In progress (2026-09-24). Spike done; build on branch `wo-007-end-to-end-tracing`.

**Spike result (2026-09-24, live; Jaeger v2.21.0 on loopback, OpenClaw 2026.9.5 with the
`diagnostics-otel` plugin).**
- (a) What OpenClaw exports: one trace per WhatsApp turn, service `openclaw-gateway`. Root
  `openclaw.message.processed` (channel, outcome), then `openclaw.run`, `openclaw.harness.run`,
  and under it `openclaw.context.assembled`, `openclaw.model.call` (token usage, provider,
  model, api), `openclaw.tool.execution` (`gen_ai.tool.name` = `idx__health`,
  `gen_ai.tool.call.id`, `openclaw.toolName`, `openclaw.tool.source` = `mcp`,
  `openclaw.tool.owner` = `bundle-mcp`, `openclaw.tool.params.kind` = `object`), a second
  model call, `openclaw.message.delivery`, and `openclaw.model.usage`. Gateway RPC spans
  (`openclaw.gateway.rpc.*`) arrive as separate one-span traces.
- (b) Nothing reaches our process: `_meta` stays empty on every call with diagnostics on; no
  `traceparent`, no run or tool call id (`meta_keys: []`, as in ADR-0005).
- (c) No config key found that makes the runtime pass a trace id into an MCP call.
- (d) With `captureContent: false`, no session key, sender number, message text, or tool
  argument appears in any exported span. The collector has nothing to drop.
- Config that worked, set by hand for the spike: `plugins.entries."diagnostics-otel".enabled:
  true` (plugin installed with `openclaw plugins install clawhub:@openclaw/diagnostics-otel`;
  `plugins.allow` left unset, since it would block every other plugin),
  `diagnostics.enabled: true`, and `diagnostics.otel` = enabled, endpoint
  `http://127.0.0.1:4318`, protocol `http/protobuf`, serviceName `openclaw-gateway`, traces on,
  metrics and logs off, `captureContent: false`. `openclaw status --all` then shows the plugin
  with traces started.
- Export is gateway-wide, not per agent (a stop-condition item): harmless while `idx` is the
  only agent; reported to the human to decide.

**Collector (decided; ADR-0006).** Jaeger v2.21.0, one binary under the gitignored
`.local/tools/jaeger/`, started by `scripts/jaeger-local.sh` with `config/jaeger-local.yaml`:
OTLP/HTTP in on 127.0.0.1:4318, UI and query API on 127.0.0.1:16686, memory storage only.
Rejected: Docker (daemon not running, one more dependency), Homebrew (no formula), hosted
services. Out of the box the binary binds its UI on all interfaces, hence the config file.
The OpenClaw keys live in a separate fragment, `config/openclaw.otel.json5`, rendered and
merged by `scripts/install.sh` only when `IDX_OTLP_ENDPOINT` is set; `config/openclaw.idx.json5`
is unchanged, so the unset render is byte-identical. `scripts/openclaw_merge_config.py` now
keeps `//` inside strings (the rendered endpoint is a URL) and merges several fragments in one
run with one backup.

**Correlation (decided; ADR-0006).** Branch: no runtime id, so correlation by tool name and
start time. OpenClaw's `openclaw.tool.execution` span with `gen_ai.tool.name` = `idx__<tool>`
and our `idx.tool_call` span with `idx.tool` = `<tool>` start within 2 seconds; one sender,
one call at a time. The session key is not exported, so it cannot be part of the rule. Both
sides sit in one Jaeger under `openclaw-gateway` and `idx-mcp`; `docs/TRACING.md` has the
steps. Zero or two candidates in the window count as ambiguous (stop condition).

**Pending (human).** Each is a human step (`openclaw` commands, a `paid` token, or both):
- Requirement 8: with Jaeger stopped, the gateway starts and `openclaw mcp doctor idx --probe`
  answers.
- Requirement 9, live: `scripts/install.sh` run with `IDX_OTLP_ENDPOINT` unset (render unchanged)
  and with it set (only the diagnostics keys added), then `openclaw config validate`.
- The one WhatsApp turn with tracing on, under a `paid` token: OpenClaw's tool span and our
  `idx.tool_call` with its stage spans lined up in Jaeger by the 2-second rule.
- With the collector down, one `health` probe, and its `tool_call` line found in the fallback file.
- The `docs/EVIDENCE_LOG.md` row for the manual run.
- OpenClaw's export is gateway-wide, not per agent: harmless while `idx` is the only agent;
  reported to the human, who decides (stop-condition item).

**Deviations (review).**
- Archive names carry the process id: `<stem>.<UTC µs>-<pid>[-n].log`. In testing, two processes
  rotating in the same microsecond overwrote each other's archive; with the pid they cannot.
- `scripts/openclaw_merge_config.py` overwrites its backup `openclaw.json.pre-idx.bak` on every
  install run, so the backup holds the config from just before the latest run, not the original.
  Pre-existing behaviour, raised with the human; outside this WO.

Drafted 2026-09-24 (docs-only PR), from the human's request that day for end-to-end tracing. Carries
the open item from ADR-0005 (no join key across the MCP boundary) and the WO-006 finding that the
gateway log drops our stderr. The OpenClaw OpenTelemetry pages were not in the local digest, so the
spike starts there. The current `.gitignore` already covers `logs/` and `*.log`, so a `gates` token is
needed only if the build picks a path outside them.
