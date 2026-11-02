# Activation handoff: bounded analysis tool (WO-017 Phase C)

The tool is built and tested offline and stays off. Registration, the skill list, the
image pin and every live check are owner steps. Nothing here has been run on the
serving host.

## 1. Build and pin the worker image (the Mac that runs the tool server)

```sh
open -a Docker          # Docker Desktop must be running; it is not today
docker build --tag idx-analysis-worker:local docker/analysis-worker
docker image inspect --format '{{.Id}}' idx-analysis-worker:local   # -> sha256:...
```

Behind a TLS-inspecting proxy, add `--secret id=pip_cert,src=/path/to/ca-bundle.crt`
(docker/analysis-worker/README.md). Rebuild and re-pin after any change to that folder.

Then prove isolation on this machine before anything is registered. These are the same
real-container tests CI runs:

```sh
IDX_ANALYSIS_IMAGE=sha256:<id> IDX_REQUIRE_CONTAINER=1 \
  .venv/bin/python -m pytest -m container -q tests/test_analysis_isolation.py \
  tests/test_analysis_render.py tests/test_analysis_executor.py
```

Every one must pass. A skip under `IDX_REQUIRE_CONTAINER=1` is a failure. Docker
Desktop on macOS has not been tested yet; if any isolation test fails, stop here.

## 2. Configure (owner, `.env` of the tool server)

```
IDX_ANALYSIS_IMAGE=sha256:<id from step 1>
IDX_ANALYSIS_TOOL=1
```

`IDX_ANALYSIS_TOOL` registers the tool at server start; without it the tool list is
unchanged. Without a pinned image, a registered tool answers "Analysis is not available
on this server right now." It never runs code on the host.

## 3. Make it routable (a reviewed repository change, then install)

1. Add `"bounded-analysis"` to the `idx` agent's `skills` list in
   `config/openclaw.idx.json5`, and the same name to `SKILLS` in
   `tests/test_openclaw_merge_config.py`.
2. Move the pending row in `docs/ROUTING.md` into the table, and add a `local` case for
   it in `evals/cases/routing.yaml`.
3. Name `bounded_analysis` in the server `instructions` and the "can't help" line, then
   update the pinned hashes in `tests/test_routing_contract.py`.
4. Run `./scripts/install.sh`, then `openclaw gateway restart`, and use a fresh session.

To turn it off again: remove `IDX_ANALYSIS_TOOL` (or set it to anything but `1`) and
restart the gateway. The skill without the tool is refused by the skill checks, so undo
step 3 in the same change.

## 4. Verify offline on the serving host

```sh
IDX_ANALYSIS_TOOL=1 .venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names())"    # True True
.venv/bin/python -m pytest -q tests/test_mcp_bounded_analysis.py \
  tests/test_analysis_service.py tests/test_skill_files.py tests/test_routing_contract.py
```

With the image pinned and the fixture database configured (as in CI), the end-to-end
cases run instead of skipping. Those are `tests/test_analysis_service_e2e.py` and the
container case in `tests/test_mcp_bounded_analysis.py`.

## 5. Human acceptance script: chart delivery (owner phone, fresh session)

Each step lists what to send and what to expect. These are model turns, so each session
needs its own `paid` grant. The first step is also the live image-relay proof that
WO-017 requires before images count as a WhatsApp feature.

1. **"In Pasadena, chart sale price against living area."**
   - A text reply starting "Bounded analysis of N sales in Pasadena, Single Family
     Residence…", with "Chart: attached." and the caveats line.
   - One PNG chart arrives in the same chat, intact (it opens and is 960×600).
   - Record whether it arrived and how long it took.
2. **"Is bigger always pricier in Glendale?"**
   - A correlation figure marked verified, or mismatched with the trusted value.
   - Caveats that say this is a bounded sample, not all sales.
   - No chart unless one was asked for.
3. **"Chart sale prices in Atlantis."** A question about the place. No analysis runs.
4. **"What will prices do next year in Pasadena?"** The one-line "I can't help with
   that…" reply. No tool call.
5. **"What's the median price in Pasadena?"** The market-stats card. This is not the
   analysis tool.
6. **Unavailable worker.**
   - Owner action: quit Docker Desktop.
   - Send step 1 again. Expected: "Analysis is not available on this server right now
     (ref …)." No image, and nothing runs on the host.
   - Restart Docker.
7. **Caveat check.** In every analysis reply, the caveats are present and unedited, no
   number appears that the reply did not mark verified or trusted, and no reply calls it
   a valuation, forecast or complete market statistic.

Record the outcomes, any image-delivery failure and the trace references in
`docs/EVIDENCE_LOG.md`.
