# Tracing one WhatsApp message end to end

How to see a single WhatsApp request as spans in a local viewer: OpenClaw's side (message,
model calls, the tool call) next to our side (the tool call and its stages down to the SQL),
plus a log file that keeps our side's lines when the viewer is not running. Built in WO-007;
the choices behind it are in `docs/adrs/0006-local-tracing.md`. Everything here is optional:
with the variables below unset, nothing is traced and nothing extra is written.

## What you will see
Two services in one local Jaeger:

| Service | Root span | The span that matters |
|---|---|---|
| `openclaw-gateway` | `openclaw.message.processed` (one trace per WhatsApp turn) | `openclaw.tool.execution`, with `gen_ai.tool.name` = `idx__search_listings` |
| `idx-mcp` (our server) | `idx.tool_call` (one trace per tool call) | its children: `idx.search.merge`, `idx.search.validate`, `idx.search.query`, `idx.search.count`, `idx.search.format`, or `idx.health.check` |

They are two traces, not one: OpenClaw passes no id into an MCP call, so they are lined up
by tool name and start time (step 7).

## One-time setup
1. **The Jaeger binary.** Download the Jaeger v2 release archive for your machine from the
   Jaeger project's GitHub releases page, check it against the `sha256sum` file published
   beside it, and unpack it under `.local/tools/jaeger/` in the repo (gitignored), so the
   binary sits at `.local/tools/jaeger/jaeger-<version>-<platform>/jaeger`. Version 2.21.0
   is the one tested. To keep it elsewhere, set `IDX_JAEGER_BIN` to its path.
2. **The Python extra.** `pip install -e ".[dev]"` already includes it; on a runtime-only
   install, `pip install -e ".[tracing]"`.
3. **The OpenClaw plugin** (a human runs every `openclaw` command):
   `openclaw plugins install clawhub:@openclaw/diagnostics-otel`

## Each session
1. **Start the collector** in its own terminal: `scripts/jaeger-local.sh`. It checks
   `config/jaeger-local.yaml` and prints the two addresses: OTLP in on
   `http://127.0.0.1:4318`, the UI on `http://127.0.0.1:16686`. Both listen on loopback
   only. Ctrl-C stops it, and the traces it held are gone.
2. **Set three lines in `.env`** (names are in `.env.example`; never commit `.env`):
   - `IDX_OTLP_ENDPOINT=http://127.0.0.1:4318`. It must be a loopback address; our server
     refuses anything else with one warning line and runs without spans, and
     `scripts/install.sh` stops.
   - `IDX_LOG_FILE=logs/idx-agent.log`. A relative path resolves against the server's
     working directory, which is the repo root.
   - `IDX_LOG_FILE_MAX_BYTES` only if 10 MB per file is not what you want.
3. **Re-run `scripts/install.sh`.** With `IDX_OTLP_ENDPOINT` set it also renders
   `config/openclaw.otel.json5` into `~/.openclaw/openclaw.otel.json5` and merges it into
   the live config, which turns on the plugin and `diagnostics.otel` (traces only, to your
   endpoint, message content never captured). It prints the follow-up commands.
4. **Restart the gateway:** `openclaw config validate`, then `openclaw gateway restart`.
   The restart also starts a fresh MCP server process, which reads the new `.env` values.
5. **Check the exporter:** `openclaw status --all` lists `diagnostics-otel` with traces
   started. `openclaw mcp doctor idx --probe` still answers.
6. **Send one message** from the owner number, for example "Find 3-bedroom homes in
   Pasadena under $1.5M". Spans are sent in batches, so allow a few seconds.
7. **Find and line up the two sides** at `http://127.0.0.1:16686`:
   1. Service `openclaw-gateway`, operation `openclaw.message.processed`, Find Traces. Open
      the newest trace and find the `openclaw.tool.execution` span whose
      `gen_ai.tool.name` is `idx__search_listings`. Note its start time.
   2. Service `idx-mcp`, operation `idx.tool_call`, Find Traces around the same minute.
      The match is the one span with `idx.tool` = `search_listings` that starts within
      2 seconds of the time you noted.
   3. Exactly one candidate: that is your request. Its children show where the time went
      (validate, merge, query, count, format). Zero or two candidates means the rule is
      ambiguous for this run; record it rather than picking one.
   4. The span's `idx.trace_id` is the same id as the `trace_id` on our `tool_call` log
      line and the `provenance.trace_id` in the tool's result, so it leads to the log file
      and its archives: `grep <that id> logs/idx-agent*.log`.

## From a script (Jaeger's v3 query API)
```
curl -s 'http://127.0.0.1:16686/api/v3/services'
curl -s 'http://127.0.0.1:16686/api/v3/traces?query.service_name=idx-mcp&query.start_time_min=2026-09-24T17:00:00Z&query.start_time_max=2026-09-24T17:05:00Z'
curl -s 'http://127.0.0.1:16686/api/v3/traces?query.service_name=openclaw-gateway&query.start_time_min=2026-09-24T17:00:00Z&query.start_time_max=2026-09-24T17:05:00Z'
```
Times are RFC 3339 in UTC. The answer is OpenTelemetry JSON; apply the same rule as step 7
(tool name, start times within 2 seconds).

## The fallback log file
With `IDX_LOG_FILE` set, every line our server writes to stderr is also appended, whole, to
that file: the same redacted JSON record, one per line, including the `tool_call` line for
every call. It does not need the collector, so it is the record to use when Jaeger was not
running. `grep '"tool_call"' logs/idx-agent.log | tail -5` shows the latest calls; to
search older lines too, include the archives: `grep -h <trace id> logs/idx-agent*.log`.
- When the file passes `IDX_LOG_FILE_MAX_BYTES` it is renamed to an archive beside it,
  `<stem>.<UTC time to the microsecond>-<pid>[-n].log` (for example
  `idx-agent.20260924T170501123456Z-4242.log`), and a new file starts. The process id keeps
  two servers rotating in the same microsecond from overwriting each other's archive.
- No code ever deletes, truncates, or prunes the file or its archives. Removing them is a
  human act under a `delete` consent token (`docs/AGENT_RULES.md`).
- `logs/` and `*.log` are gitignored; `git check-ignore -v logs/idx-agent.log` confirms it.

## What is kept out
**Our side.** A span attribute is exported only if its name is on the allowlist in
`src/idx_agent/observability/tracing.py` (the fields the log line already carries: trace
id, tool, ok, error category, mode, 8-character key prefix, validated filters, row and
match counts, clarification field, meta key names). Every value then goes through the same
`redact()` as the log line. The raw sender id, listing remarks, rows, and the unvalidated
request never reach a span; `meta_shape` stays in the log line only. Span names are fixed
strings.

**OpenClaw's side.** `captureContent` is off, so message text, replies, and tool arguments
are not exported. The spike of 2026-09-24 found no session key and no sender number in any
exported span; what is exported is the channel, the outcome, model and token usage, and the
tool's name, call id, source, and owner.

**The collector.** Loopback only, memory only, nothing forwarded anywhere. Stopping Jaeger
discards every trace.

**Eval runs.** `python -m evals.run` blanks the tracing variables unless it is given
`--allow-tracing`, so an eval run with tracing set in `.env` does not send orphan spans
(tool calls with no WhatsApp turn around them) to the collector.

## Turning it off
- Stop Jaeger with Ctrl-C. The gateway and our tools keep working; our server logs an
  export failure at most once a minute and carries on.
- Our side: clear `IDX_OTLP_ENDPOINT` (and `IDX_LOG_FILE` if you want) in `.env`, then
  `openclaw gateway restart`.
- OpenClaw's side: `scripts/install.sh` never removes keys from the live config, so run
  `openclaw config set diagnostics.otel.enabled false` and restart the gateway.

## When something is missing
- No `idx-mcp` service: the server did not see `IDX_OTLP_ENDPOINT` (the gateway was not
  restarted after editing `.env`), the endpoint is not loopback (look for the warning line
  in the log file), or the `tracing` extra is not installed in the venv.
- No `openclaw-gateway` service: the plugin is not installed, or `openclaw status --all`
  does not show traces started; re-run `scripts/install.sh` with the endpoint set.
- Nothing at all: Jaeger is not running, or something else holds port 4318 or 16686.
