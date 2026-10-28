# Analysis worker image (WO-017, ADR-0013)

The container that runs model-written analysis code over a bounded numeric sample,
and later renders trusted chart data. The tool server starts it through
`src/idx_agent/analysis/executor.py` with a fixed set of docker flags; nothing in a
user turn can change the image, the flags or the script it runs.

## What is in the image

- `python:3.11-slim`, pinned by digest in the `FROM` line.
- matplotlib 3.11.2 and its dependencies, installed from `requirements.txt` with
  `--require-hashes --no-deps --only-binary=:all:` (hashes for amd64 and arm64).
- `/opt/worker/bootstrap.py`, the fixed analysis entry script (root-owned,
  read-only to the worker user). Step 5 adds `render.py` next to it.
- A prebuilt matplotlib font list in `/opt/mpl-cache`, copied into the tmpfs at run
  time (`MPLCONFIGDIR=/tmp/matplotlib`) so importing matplotlib takes about half a
  second instead of rebuilding the list on every run.
- User `65534:65534`, working directory `/tmp`, no `ENTRYPOINT` or `CMD`: the
  executor names the script on every run.

## Build and pin (operator, once per machine)

```sh
docker build --tag idx-analysis-worker:local docker/analysis-worker
docker image inspect --format '{{.Id}}' idx-analysis-worker:local
```

Set the printed `sha256:...` ID as `IDX_ANALYSIS_IMAGE` in the tool server's
environment. A tag is refused; only an image ID or a `name@sha256:` digest is
accepted. Each machine builds its own image, so the ID differs between machines;
rebuild and re-pin after any change in this directory.

If the build machine sits behind a TLS-inspecting proxy, pass its CA bundle as the
optional build secret `pip_cert`; it is used for the install step only and is not
stored in the image:

```sh
docker build --secret id=pip_cert,src=/path/to/ca-bundle.crt \
  --tag idx-analysis-worker:local docker/analysis-worker
```

## What never happens at run time

The executor runs with `--pull never` and never builds. If the client, the daemon or
the pinned image is missing, a run reports `unavailable`; there is no fallback that
runs code on the host.

## Tests

```sh
IDX_ANALYSIS_IMAGE=$(docker image inspect --format '{{.Id}}' idx-analysis-worker:local) \
  IDX_REQUIRE_CONTAINER=1 MYSQL_HOST= pytest -q -m container
```

`tests/test_analysis_isolation.py` runs hostile code against the real engine.
Without `IDX_ANALYSIS_IMAGE` those tests skip; with `IDX_REQUIRE_CONTAINER=1` (as in
CI) a missing image fails them instead.
