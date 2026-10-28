# ADR-0013: Container worker and chart renderer for bounded analysis

**Status:** accepted 2026-10-28 by the human (Docker worker, matplotlib in the worker,
CI build step); proposed 2026-10-27
**Date:** 2026-10-28
**Work order:** WO-017

## Context
WO-017 Phase B runs model-written Python over at most 50 numeric sale rows and
returns figures and a chart. That code is untrusted. ANALYSIS_DESIGN.md rules out
executing it in the gateway or tool-server process, rules out an AST filter or
restricted builtins as the boundary, and makes the container infrastructure the
human's decision. The chart renderer is also a new dependency, which needs the
human's approval (AGENT_RULES.md section 7). The roadmap's presentation note asks
for accessible, polished charts that state units, dates and uncertainty.

## Decision
**Worker image.** A small image built from `docker/analysis-worker/` in this repo:
the official `python:3.11-slim` base pinned by digest, matplotlib and its
dependencies installed from a requirements file pinned by version and hash, a fixed
non-root user, and the two fixed entry scripts below. Nothing else. The operator
builds it once and configures the tool server with the resulting image ID
(`sha256:<64 hex>`); the executor refuses any reference that is not pinned by digest
and runs with `--pull never`, so a user turn never pulls or builds. CI builds the
same Dockerfile in a step before the tests and passes the ID to them.

**Input and runs.** The worker never gets a database connection, a credential or the
host environment. Host code writes the bounded sample (the numeric rows of
`AnalysisSample.worker_rows()`, no keys or place text) and the model's code as two
files into a fresh temporary directory, mounted read-only at `/input`; that is the
only mount. Two kinds of run use the same image and flags:
1. *Analysis run*: a fixed bootstrap executes the model's code against the sample
   and prints one JSON object (the WO-017 worker output: figures and an optional
   chart request). Host code parses it strictly and recomputes every figure.
2. *Render run*: a fixed renderer, with no model code present, reads the chart data
   that host code built and validated from the same sample (`ChartData`) and prints
   one PNG. The trusted side only reads the image bytes and checks the PNG
   signature, dimensions and size; it never imports matplotlib.
So the worker renders, as the human decided, but every number in the picture comes
from trusted code, never from the model.

**Fixed flags, every run.** `--rm`, a generated `--name`, `--pull never`,
`--network none`, `--read-only`, a 16 MB `noexec,nosuid,nodev` tmpfs at `/tmp`,
`--cap-drop ALL`, `--security-opt no-new-privileges`, the default seccomp profile,
`--user 65534:65534`, `--memory 256m --memory-swap 256m`, `--pids-limit 64`,
`--cpus 1`, `--ipc none`, `--log-driver none`, no `-e`, no published port, the one
read-only `/input` mount. Limits: a 30-second wall clock per run; stdout capped at
64 KB for an analysis run and 512 KB for a render run, stderr at 8 KB, read while
the process runs and refused when exceeded. On timeout, cancellation, an output cap
or any error the host removes the named container with `docker rm -f` and deletes
the input directory. At most two runs at once. If the client, daemon or pinned image
is missing, the result is `unavailable`; there is no host-execution fallback.

**Renderer dependency.** matplotlib with the Agg backend, pinned in the worker's
requirements and recorded as the optional extra `analysis` in `pyproject.toml` (a
test keeps the two versions equal). Fixed fonts, colours and size; PNG metadata
cleared so equal input gives equal bytes.

**Rejected alternatives.** Host subprocess with resource limits: no filesystem or
network isolation. A Python AST filter or restricted builtins: not a boundary.
WebAssembly Python (Pyodide): stronger default isolation, but needs a JavaScript
runtime dependency and has no stdlib parity guarantee; worth revisiting. gVisor or
a microVM: stronger kernel boundary, but more infrastructure than one laptop and CI
need now; the main hardening step if this tool is ever exposed beyond the owner. A
hosted code-execution service: sample rows would leave the machine. Plotly or D3:
static PNG export needs a headless browser engine. Rendering on the host: puts a
large native dependency into the tool-server process. Letting the model's code
draw the chart: the picture could show numbers no check has seen.

## Consequences
The tool-server process needs access to the Docker daemon. That daemon is root-
equivalent on Linux, so this widens what a compromised tool server could do; on the
owner's macOS machine Docker Desktop runs containers inside a Linux VM, which adds a
kernel boundary but not a daemon boundary. The container shares the host or VM
kernel, so these flags are hardening, not a proof of isolation; WO-017's real
hostile-code tests are the evidence, and they run against a real engine, not a
mocked command line. The operator owns installation, the image build and the daemon
socket; none is a tool argument. The image needs wheels for both amd64 (CI) and
arm64 (Docker Desktop on Apple silicon), so the requirements carry hashes for both.
A locally built image ID differs between machines; each machine pins its own build.
The CI change is one conditional step, shown exactly in the WO-017 Status and made
only under the human's `gates` token.

## Amendment, 2026-10-28: a deadline inside the container
Review of step 4 showed the 30-second limit lived only in the host process: if the
tool server was killed mid-run, the container kept running with no bound. The
container's PID 1 is now a fixed timer from the image (coreutils `timeout`, copied
to `/opt/worker/deadline` with mode 0711) that kills the worker five seconds after
the wall clock. Model code cannot signal it away (a namespace init ignores SIGKILL
and SIGSTOP from inside) or trace it (with `--cap-drop ALL` an execute-only binary
runs non-dumpable). The host keeps a slot taken while a container it could not
remove may still run, and the executor's `sweep_leftovers` clears containers and
input directories left by a killed host. Real-engine tests cover both.

## Local probe, 2026-10-27
On a local Docker 29.9 engine (Linux, cgroup v1, default seccomp) the pinned base
image with the flags above (stdin input, before this revision) refused an outbound
connection (network unreachable) and a root-filesystem write, allowed a /tmp write,
showed only the image's own environment variables, ran as uid 65534, had no daemon
socket, was killed at a 600 MB allocation (exit 137) and stopped forking at 63
children. This is a probe of the flags, not the WO-017 test suite and not evidence
for the owner's macOS engine.

## What would reverse this
A hostile-code test that escapes or exhausts the host despite the flags; Docker
being unavailable or unacceptable on the owner's machine; the human preferring a
WebAssembly or microVM boundary; the image relay to WhatsApp proving impossible
(the renderer would then serve reports only); or the renderer failing the
accessibility or determinism checks.
