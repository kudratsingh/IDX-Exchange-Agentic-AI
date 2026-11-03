# Activation handoff: bounded analysis tool (WO-017 Phase C, WO-027)

The tool is built and tested offline and stays off. Since WO-027 the repository side is
finished: activation is the image pin, one switch, and an install plus restart. The pin,
the switch and every live check are owner steps. Nothing here has been run on the
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

## 2. Turn it on: one switch, then install and restart (owner)

Add to the repository's `.env` (the file the tool server and `install.sh` both read):

```
IDX_ANALYSIS_IMAGE=sha256:<id from step 1>
IDX_ANALYSIS_TOOL=1
```

Then:

```sh
./scripts/install.sh            # prints "Bounded analysis is on (IDX_ANALYSIS_TOOL=1)"
openclaw config validate
openclaw gateway restart
openclaw mcp doctor idx --probe # expects 8 tools, including idx__bounded_analysis
openclaw skills list            # expects 9, including bounded-analysis
```

Send `/new` from the phone before the first test, so the session sees the new skill list
and instructions. If `install.sh` says the image is "unset or not pinned by digest", fix
the pin first: with the switch on and no pinned image the tool answers "Analysis is not
available on this server right now." and never runs code on the host.

## 3. What the one switch does

`IDX_ANALYSIS_TOOL` counts as on only when it is exactly `1`; `0`, `true`, ` 1` or
anything else is off. One rule, `analysis.tool.switch_state()` over `.env` and the
process environment, decides all three effects, so they cannot disagree after an install
and restart:

| Effect | Where | Off (default) | On |
|---|---|---|---|
| Tool registration | the `idx` server at start (`register_analysis_tool`) | 7 tools, unchanged | adds `bounded_analysis` |
| Instructions | the same call swaps the server's `instructions` | `BASE_INSTRUCTIONS`, byte for byte as before | `ANALYSIS_INSTRUCTIONS`: one clause naming the tool; the "can't help" line is unchanged |
| Skill list | `scripts/install.sh` merges `config/openclaw.analysis.json5` | the 8 skills, unchanged | adds `bounded-analysis` |

The worker side follows `IDX_ANALYSIS_IMAGE` (pinned image ID or digest; unset or a tag
is `unavailable`). The default pins in `tests/test_routing_contract.py` are unchanged; the
"on" variant has its own pins there.

The switch lives in `.env` only. The process environment may repeat it, but when it
contradicts `.env` (on in one, off or empty in the other) it is a configuration failure,
never a silent difference:
- `install.sh` stops before writing anything: "install.sh: Bounded analysis is
  misconfigured: …", naming which side is on. The same happens when
  `IDX_ANALYSIS_IMAGE` in the environment differs from `.env`.
- The tool server, whose environment is the gateway's and may differ from the shell
  that ran `install.sh`, registers nothing and keeps the base instructions. It writes
  the problem into its `server_start` log line (`analysis_switch_problem`), and every
  `health` reply appends it, for example "… the bounded-analysis skill is installed and
  the tool is not registered." An image that differs from `.env` is reported the same
  way, but the tool stays registered.

Changing `.env` without running `install.sh` again is not detected by the server; the
probe counts in section 2 (8 tools and 9 skills, or 7 and 8) are the check.

## 4. Turn it off (rollback)

```sh
# remove the IDX_ANALYSIS_TOOL line from .env (or set it to anything but 1)
./scripts/install.sh            # the main render's skill list replaces the merged one
openclaw gateway restart
```

Then `/new` on the phone. No hand edit of the live config is needed: the merge replaces
lists, so the 8-skill list comes back, and `install.sh` removes the rendered
`~/.openclaw/openclaw.analysis.json5` ("removed …"), so nothing analysis-related is
left in the state folder. After the restart, `openclaw mcp doctor idx --probe` expects 7
tools and `openclaw skills list` 8. The worker image can stay pinned; with the switch
off nothing reads it. To back out the code, revert the WO-027 commits; nothing else in
the repository depends on them.

## 5. Verify offline on the serving host

```sh
.venv/bin/python -c "from idx_agent.mcp_server import server as s; \
print(s.register_analysis_tool(), 'bounded_analysis' in s.tool_names(), \
'bounded_analysis' in s.server.instructions, s.analysis_switch_problem())"   # True True True None
.venv/bin/python -m pytest -q tests/test_analysis_integration.py \
  tests/test_analysis_switch_agreement.py tests/test_mcp_bounded_analysis.py tests/test_analysis_service.py \
  tests/test_skill_files.py tests/test_routing_contract.py \
  tests/test_openclaw_merge_config.py
```

With the image pinned and the fixture database configured (as in CI), the end-to-end
cases run instead of skipping. Those are `tests/test_analysis_service_e2e.py`, the
container case in `tests/test_mcp_bounded_analysis.py` and the `db` case in
`tests/test_analysis_integration.py`.

## 6. Human acceptance script: chart delivery (owner phone, fresh session)

Each step lists what to send and what to expect. These are model turns, so each session
needs its own `paid` grant. The first step is also the live image-relay proof that
WO-017 requires before images count as a WhatsApp feature.

1. **"In Pasadena, chart sale price against living area."**
   - A text reply starting "Bounded analysis of N sales in Pasadena, Single Family
     Residence…", with the chart line "Chart: <title> (N of M sales), returned as an
     image with this result. If no image appears in this chat, the figures above are
     the whole result." and the caveats line.
   - Record whether a PNG arrives in the same chat, intact (it opens and is 960×600),
     and how long it took. Expect that it may not: OpenClaw 2026.9.5's own docs (read,
     not run, on 2026-11-02) say tool-result images go to the model and are not attached
     to channel replies automatically, and the `idx` agent has no tool that sends media.
     If none arrives, the text above is the whole answer and the image relay is a
     decision for the owner (WO-027 Status lists the options); nothing else changes.
   - The reply never says the chart was sent or attached.
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
