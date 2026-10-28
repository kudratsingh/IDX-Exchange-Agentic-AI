# Database analysis: design for WO-017

Status: proposed executor, numeric boundary under implementation (2026-10-25).
2026-10-27: the executor and renderer choices are proposed in ADR-0013.
2026-10-28: ADR-0013 accepted (Docker worker; charts rendered in the worker).
This is not an available chat tool. No model code runs in the gateway process.

## What the first version can answer

An exploratory relationship in a bounded set of eligible closed sales: for example,
list-price difference versus stored DOM, or price per sqft versus DOM, for a city or
ZIP and one subtype. Show sample size, missing values, dates and sampling method.
The current snapshot has no price-change history; an original/final list difference
is not a history of cuts, and association does not establish causation. Fifty rows
cannot be presented as the whole area's market. Existing aggregate tools remain the
route for population-level market figures.

## Split the database reader from execution

The trusted reader keeps the existing SELECT-only connection, fixed allowlisted
projections, parameterized geography/date predicates and 50-row ceiling. The model
chooses a named dataset and validated filters, never columns or SQL. A numeric-only
adapter checks the scope and drops identifiers before any worker receives input.
Do not page repeatedly to reconstruct an export. Statement work/time must also be
bounded; a returned-row LIMIT alone does not bound query cost.

The proposed worker is a Linux container running a fixed image pinned by digest.
It receives only bounded JSON and model Python on stdin. No provider/email/database
credentials, inherited host environment, host directory mount, Docker socket or
network. Non-root uid, dropped capabilities, no-new-privileges, default seccomp,
read-only root filesystem, bounded noexec scratch tmpfs, CPU/memory/swap/PID limits,
a wall-clock deadline and bounded concurrent workers are mandatory. No automatic
pull/build/install on a user turn. If the engine/image/isolation is unavailable,
return unavailable; there is no local exec fallback. The daemon endpoint and all
flags are operator-owned, never model arguments.

These are proposed controls, not verified isolation. Docker has its own privileged
control plane and kernel boundary. The operator must approve this new infrastructure
before adoption; a Python AST filter or restricted builtins is not the sandbox.

## Output and lifecycle

Host code bounds stdout/stderr while reading, rejects oversized output, and removes
the named container on timeout, cancellation and disconnect. Killing a Docker client
alone is insufficient. Never persist source code, raw stderr or sample rows in logs.
Return a generic error plus trace id on failure. Reject non-finite numbers and unknown
output keys. Treat worker output as untrusted data; valid JSON does not prove correct
calculations. Recompute supported headline figures in trusted code; unsupported
computations must not be labelled verified. Bound points/groups/text and suppress
small groups before displaying aggregate output. Build chart data in trusted code
from the sample; a fixed renderer inside the worker (matplotlib, ADR-0013) draws it
to one PNG with no model code present; no arbitrary HTML, URLs, SVG or worker paths.

MCP image output and OpenClaw WhatsApp image relay need an end-to-end proof before
promising image delivery. Until then a typed result/fixture is not a WhatsApp feature.
Chart rendering and live transport are separate acceptance criteria.

## End-to-end flow as built (step 6)

Nothing below is a chat tool yet. One call reads the sold and active as-of dates,
counts the window back from the sold date and reads at most 50 cleaned sales with
the fixed reader. The model's code runs once in the pinned worker container over the
numeric rows only. Host code recomputes every figure the worker claims and keeps
its own number. If the worker asked for a chart, host code builds the chart data
from the same rows and a second, separate container run draws it with the fixed
renderer; the host checks the PNG's structure before keeping it. The result for the
model is one JSON text block (statuses, trusted values, caveats; no rows, code or
worker numbers) plus the image when it passed. A min, a max, or a mean, median or
spread over fewer than three values is withheld, since it could be one sale's value. Every failure is a status code with a
generic message. Registration and the WhatsApp image relay remain separate steps.

## Required tests before registration

- Fixed SQL projections and parameter binding; cap and query deadline; snapshot and
  cleaning consistency; fixture DB integration; no sensitive fields at the boundary.
- Network, host read/write, credential/environment and Docker-socket attempts fail.
- Infinite loops, fork/process growth, excessive allocation, scratch writes, output
  floods, malformed/hostile JSON and cancellation terminate within bounded resources.
- The container is gone after all error paths; parallel requests cannot share state;
  an absent image/engine never invokes Python on the host. Test real isolation, not
  only a mocked command-line assertion.
- Small samples, nulls, constant vectors, mixed types and outliers produce accurate
  caveats; independent trusted calculations catch fabricated headline statistics.
- Routing remains exact and no shell tool is exposed; live chat/chart acceptance is
  separately consented. Existing approval, no-contact and no-export rules still apply.

## Primary references checked 2026-10-25

[Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/)
describes read-only, network, PID and privilege flags. The
[resource controls](https://docs.docker.com/engine/containers/run/) distinguish memory
and memory-plus-swap limits. The [security overview](https://docs.docker.com/engine/security/)
explains the daemon's authority and host-mount risks. Python's
[subprocess documentation](https://docs.python.org/3/library/subprocess.html)
warns about buffered output and cleanup after a timeout. These support the design;
they do not substitute for testing the deployed worker.
