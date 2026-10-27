# ADR-0013: Container worker and chart renderer for bounded analysis

**Status:** proposed — awaiting the human's infrastructure and dependency decision
**Date:** 2026-10-27
**Work order:** WO-017

## Context
WO-017 Phase B runs model-written Python over at most 50 numeric sale rows and
returns figures and a chart. That code is untrusted. ANALYSIS_DESIGN.md rules out
executing it in the gateway or tool-server process, rules out an AST filter or
restricted builtins as the boundary, and makes the container infrastructure the
human's decision. The chart renderer is also a new dependency, which needs the
human's approval (AGENT_RULES.md section 7). The roadmap's presentation note asks
for accessible, polished charts that state units, dates and uncertainty.

## Decision (proposed)
**Worker.** One short-lived Docker container per analysis, started by the tool
server through the `docker` command-line client with a fixed argument list that no
model or user value can change. Image: the official `python:3.11-slim` image pinned
by digest (`sha256:ae952e0a57138a4317b9b61caaa19a8217c2f356803f8d7e63aad08769950937`,
the multi-platform index pulled 2026-10-27), standard library only, no build step.
The operator pulls it once; a user turn runs with `--pull never` and never pulls or
builds. Fixed flags: `--rm`, a generated `--name`, `--network none`, `--read-only`,
a 16 MB `noexec,nosuid,nodev` tmpfs at `/tmp`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, the default seccomp profile, `--user 65534:65534`,
`--memory 256m --memory-swap 256m`, `--pids-limit 64`, `--cpus 1`, `--ipc none`,
`--log-driver none`, no `-e`, no `-v`, no published port. A fixed trusted bootstrap
runs as `python -I -S`, reads one bounded JSON envelope (the numeric rows and the
model code) from stdin and writes one JSON object to stdout. The host reads at most
64 KB of stdout and 8 KB of stderr, enforces a 10-second wall clock, and on timeout,
cancellation or any error removes the named container with `docker rm -f`. At most
two analyses run at once. When the client, daemon or pinned image is missing, the
result is `unavailable`; there is no host-execution fallback.

**Renderer.** Charts are drawn in trusted host code from a typed numeric
specification, never by the worker. Proposed library: matplotlib with the Agg
backend, as a new optional extra `analysis` imported only when a chart is drawn,
with fixed fonts, colours and size, PNG metadata cleared so equal input gives equal
bytes, and a cap on encoded size.

**Rejected alternatives.** Host subprocess with resource limits: no filesystem or
network isolation. A Python AST filter or restricted builtins: not a boundary.
WebAssembly Python (Pyodide): stronger default isolation, but needs a JavaScript
runtime dependency and has no stdlib parity guarantee; worth revisiting. gVisor or
a microVM: stronger kernel boundary, but more infrastructure than one laptop and CI
need now; the main hardening step if this tool is ever exposed beyond the owner. A
hosted code-execution service: sample rows would leave the machine. Plotly or D3:
static PNG export needs a headless browser engine. A hand-written PNG writer: no
dependency, but cannot meet the roadmap's polish and accessibility direction.

## Consequences
The tool-server process needs access to the Docker daemon. That daemon is root-
equivalent on Linux, so this widens what a compromised tool server could do; on the
owner's macOS machine Docker Desktop runs containers inside a Linux VM, which adds a
kernel boundary but not a daemon boundary. The container shares the host or VM
kernel, so these flags are hardening, not a proof of isolation; WO-017's real
hostile-code tests are the evidence, and they run against a real engine, not a
mocked command line. The operator owns installation, the image pull, and the daemon
socket; none is a tool argument. CI needs a step that pulls the pinned image before
the isolation tests (a `gates`-token edit to the workflow); without it those tests
skip in CI and the evidence is local only. matplotlib adds compiled wheels to the
optional extra, not to the base install.

## Local probe, 2026-10-27
On a local Docker 29.9 engine (Linux, cgroup v1, default seccomp) the pinned image
with exactly the flags above refused an outbound connection (network unreachable)
and a root-filesystem write, allowed a /tmp write, showed only the image's own
environment variables, ran as uid 65534, had no daemon socket, was killed at a
600 MB allocation (exit 137) and stopped forking at 63 children. This is a probe of
the flags, not the WO-017 test suite and not evidence for the owner's macOS engine.

## What would reverse this
A hostile-code test that escapes or exhausts the host despite the flags; Docker
being unavailable or unacceptable on the owner's machine; the human preferring a
WebAssembly or microVM boundary; the image relay to WhatsApp proving impossible
(the renderer would then serve reports only); or the renderer failing the
accessibility or determinism checks.
