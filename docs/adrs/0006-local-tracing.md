# ADR-0006: Local tracing: Jaeger v2 on loopback, joined by tool name and start time

**Status:** accepted for the build (spike of 2026-09-24); the end-to-end run is recorded in the WO-007 Status
**Date:** 2026-09-24
**Work order:** WO-007

## Context
A slow or wrong WhatsApp reply could not be followed from the inbound message to our SQL.
Two gaps: OpenClaw passes no id into an MCP call (ADR-0005: request `_meta` is empty on
every call), and the gateway log drops our server's stderr, where the `tool_call` line
goes. The human asked for end-to-end tracing on 2026-09-24. The WO-007 spike ran Jaeger
v2.21.0 on loopback with OpenClaw 2026.9.5 and its `diagnostics-otel` plugin, and found:
- OpenClaw exports one trace per WhatsApp turn under the service `openclaw-gateway`:
  `openclaw.message.processed` at the root, then `openclaw.run`, `openclaw.harness.run`,
  context assembly, model calls, and one `openclaw.tool.execution` span per tool call,
  carrying the tool name (`gen_ai.tool.name` = `idx__health` in the spike), a tool call
  id, and the tool's source and owner (`mcp`, `bundle-mcp`).
- With content capture off, no session key, sender number, message text, or tool
  argument is exported.
- Turning diagnostics on changes nothing at the MCP boundary: `_meta` stays empty, and no
  `traceparent` or other id reaches our server. Nothing in the config asks for one.

## Decision
**Collector: Jaeger v2, one binary, loopback only, memory storage.** Jaeger v2 is built on
the OpenTelemetry Collector, so one process takes OTLP in and serves the trace UI.
`config/jaeger-local.yaml` binds the OTLP/HTTP receiver to 127.0.0.1:4318 and the UI and
query API to 127.0.0.1:16686, and keeps traces in memory only (they are gone when Jaeger
stops; nothing is written to disk). `scripts/jaeger-local.sh` starts it in the foreground.
The binary is downloaded once by a human from the project's release page, checked against
its published checksum, and unpacked under `.local/tools/jaeger/`, which is gitignored; the
script never downloads anything. Rejected:
- Docker (Jaeger all-in-one image): the Docker daemon is not running on this machine, and
  it would be one more piece of software to install and keep running for a single viewer.
- Homebrew: there is no formula for Jaeger v2.
- Hosted tracing services: out of scope for WO-007 (accounts, paid tiers, and traces
  leaving the machine).
- The OpenTelemetry Collector with a file exporter in front of Jaeger: its reason to exist
  here was to drop or rewrite sensitive OpenClaw attributes before storage, and the spike
  found none to drop. It stays the fallback if a later OpenClaw version starts exporting
  a sender or message field.

**Dependency.** `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http`, bounded
`>=1.30,<2`, as an optional `tracing` extra that `dev` also installs so CI tests the spans.
The HTTP exporter is chosen over gRPC to avoid a compiled `grpcio` dependency. Without the
extra, or without `IDX_OTLP_ENDPOINT`, the SDK is never imported.

**OpenClaw side.** The `diagnostics-otel` plugin (installed by hand from ClawHub) plus the
`diagnostics.otel` keys, traces only, `captureContent: false`, in a separate fragment,
`config/openclaw.otel.json5`. `scripts/install.sh` renders and merges it only when
`IDX_OTLP_ENDPOINT` is set in `.env`; unset, the main render is byte-identical to before.
The fragment never sets `plugins.allow`, which would switch off every unlisted plugin.

**Correlation: by tool name and start time, within 2 seconds.** No runtime id crosses the
MCP boundary, so our `idx.tool_call` root cannot be a child of OpenClaw's tool span, and
the WO's fallback key (the session key) is not exported either. The join rule: OpenClaw's
`openclaw.tool.execution` span with `gen_ai.tool.name` = `idx__<tool>` and our
`idx.tool_call` span with `idx.tool` = `<tool>` start within 2 seconds of each other. Both
sit in the same Jaeger under two services, `openclaw-gateway` and `idx-mcp`. The rule is
sound because there is one allowlisted sender and the model calls one tool at a time; the
window is wide enough for the stdio hop and process scheduling, and far shorter than the
gap between two model turns. Zero or two candidates inside the window count as ambiguous,
which is a WO-007 stop condition, not a guess.

## Consequences
- One WhatsApp turn can be followed from message to SQL stage in one local viewer, by the
  steps in `docs/TRACING.md`, without any change to OpenClaw.
- The two halves are two traces, lined up by a documented rule, not one trace. The UI does
  not draw them on one timeline; a reader matches them by name and time.
- OpenClaw's export is gateway-wide, not per agent. That is harmless while `idx` is the only
  agent; a second agent's turns would also be exported.
- Traces are lost when Jaeger stops. The `IDX_LOG_FILE` fallback keeps our side's log lines
  on disk (gitignored, rotated, never pruned by code), so nothing on our side depends on the
  collector being up. The gateway and our tools should run the same with the collector
  down; that is pending the human's check (WO-007 requirement 8, listed in its Status).
- Three more loopback ports are in use while Jaeger runs: 4318 (OTLP/HTTP in), 16686 (UI
  and query API), and 16685 (the query API's gRPC side).

## What would reverse this
OpenClaw passing a `traceparent` (or any run or tool call id) in MCP `_meta`: our root span
then becomes a child of `openclaw.tool.execution` and the request is one trace, with the
time window dropped. A second sender or concurrent tool calls making the 2-second window
ambiguous. An OpenClaw export that starts carrying a sender number or message text: an
OpenTelemetry Collector goes in front of Jaeger to drop it, or tracing is switched off. A
need to keep traces across restarts: a persistent Jaeger backend, with its own ADR.
