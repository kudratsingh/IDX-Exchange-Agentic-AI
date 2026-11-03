# WO-027 — Bounded analysis, phase 2: opt-in routing, skill wiring and chart text

**Driver:** agent (owner pins the image, flips the switch, installs and runs live checks)
**Depends on:** WO-017 Phase C (PR #138: `bounded_analysis` built, off by default),
WO-013 routing contract, WO-007 install-time fragment precedent
**Estimated effort:** one PR, a small commit series

## Objective
Finish the repository side of `bounded_analysis` so that activation is the image pin, one
switch (`IDX_ANALYSIS_TOOL=1`), an install and a gateway restart: tool registration,
server instructions, the `idx` agent's skill list and the routing contract follow that one
switch, and with it unset everything the model sees is byte for byte what it is today.

## Why
WO-017 left the tool registered by a switch but unroutable: the skill was outside the
agent's list, the routing row was pending, the instructions did not name the tool, and the
reply text promised an attached chart that the WhatsApp relay may never deliver.
`docs/RELEASE_WO017_ANALYSIS.md` section 3 listed those deferred repository changes.

## Inputs
- `src/idx_agent/analysis/tool.py` (`enabled`, `executor_config`, `content_blocks`),
  `src/idx_agent/analysis/mcp_result.py`, `src/idx_agent/mcp_server/server.py`
  (`register_analysis_tool`, the `instructions` string)
- `skills/bounded-analysis/SKILL.md`, `config/openclaw.idx.json5`, `scripts/install.sh`,
  `scripts/openclaw_merge_config.py` (lists replace lists), `config/openclaw.otel.json5`
  (the WO-007 precedent: a fragment rendered and merged only when its `.env` setting is set)
- `docs/ROUTING.md`, `tests/test_routing_contract.py` (pinned hashes),
  `evals/cases/routing.yaml`, `evals/run.py`, `evals/routing_fixtures.py`
- ADR-0013, `docs/ANALYSIS_DESIGN.md`, `docs/CONTRACTS.md` WO-017 sections
- OpenClaw 2026.9.5 as installed on the owner's Mac, read only (docs and the MCP content
  projection), never run: skill gating keys and how a tool's image block is handled

## In scope
1. Server instructions computed from the same `enabled()` check as registration.
2. Skill availability gated at install time by the same check, through a second config
   fragment (the existing approved mechanism; no new OpenClaw feature).
3. The routing row moved into the contract table, marked opt-in; contract tests that hold
   the default table to the default config and the whole table to the "on" config.
4. Two `local` routing cases for the opt-in row (added, not run), the runner able to run
   them with the switch on and skip them (no paid call counted) with it off, and a
   routing-fixture reply for the tool.
5. Chart text the repository can own: a caption line with a text fallback, and an
   image-delivery failure that removes the image and says so.
6. End-to-end tests through a real in-process MCP session down to the real executor with
   the executor tests' fake docker client, plus a fixture-database case (`db`).
7. Docs: release handoff (activation, exact commands, rollback), contracts, routing,
   evaluation rule, the skill, this work order.

## Out of scope
- Running `scripts/install.sh`, any `openclaw` command, a gateway restart, or touching
  `~/.openclaw` or live config. All of those are owner steps, documented only.
- A new transport for images (writing PNGs into the agent workspace for a `MEDIA:` line,
  enabling the `message` tool, a hosted URL): each is an OpenClaw feature or a policy change
  this repo does not use today. Recorded as a decision for the owner.
- Running the `local` eval suite or any paid model call; starting Docker; `-m db` against
  any database other than the synthetic fixture.
- Gates, guards, CI, `.gitignore`, `.claude/settings.json`; `docs/STATUS.md`; WO-017's
  Status; new dependencies or services.

## Files expected to change
`src/idx_agent/mcp_server/server.py`, `src/idx_agent/analysis/tool.py`,
`src/idx_agent/analysis/mcp_result.py`, `src/idx_agent/channels/format.py`,
`config/openclaw.analysis.json5` (new), `scripts/install.sh`, `evals/run.py`,
`evals/routing_fixtures.py`, `evals/cases/routing.yaml`, `skills/bounded-analysis/SKILL.md`,
`tests/conftest.py`, `tests/test_analysis_integration.py` (new),
`tests/test_mcp_bounded_analysis.py`, `tests/test_analysis_service.py`,
`tests/test_routing_contract.py`, `tests/test_openclaw_merge_config.py`,
`tests/test_evals_runner.py`, `docs/ROUTING.md`, `docs/CONTRACTS.md`, `docs/EVALUATION.md`,
`docs/RELEASE_WO017_ANALYSIS.md`, this file.

## Interfaces and contracts
`docs/CONTRACTS.md`, "Opt-in wiring and chart text (WO-027)". New names:
`server.BASE_INSTRUCTIONS`, `server.ANALYSIS_INSTRUCTIONS`,
`server.reset_analysis_tool_for_tests()`, `format.format_chart_line`,
`format.CHART_IMAGE_FALLBACK`, `format.CHART_NOT_ATTACHED_LINE`,
`evals.run.OPT_IN_TOOLS`, `evals.run.analysis_switch_on()`, `evals.run.opt_in_tools()`,
`configured_skills(config, *, analysis=None)`.

## Implementation requirements
1. With `IDX_ANALYSIS_TOOL` unset (or anything but exactly `1`): the `idx` tool list, the
   installed skill list, the server instructions and the routing prompt are unchanged; the
   existing pins in `tests/test_routing_contract.py` are unchanged.
2. With it exactly `1`: the tool is registered, the instructions name it, `install.sh`
   adds the skill, the routing contract holds over all nine skills, and the "on" text has
   its own pins.
3. An unpinned image or a missing engine answers the fixed unavailable message, with no
   database read for an unpinned image and no process but the docker client ever.
4. The reply text never depends on the image reaching the user; a PNG that fails the last
   check is not attached and the text says so.
5. Switching off and reinstalling restores the default skill list without hand edits.

## Safety requirements
No relaxed invariant. The model still supplies only place arguments and Python; no SQL,
columns, paths or flags. At most 50 sales reach the worker, numeric fields only; caveats
are in every result; no host-execution fallback (asserted after every executor test);
synthetic fixture data only; no secrets read or printed (install.sh reads two settings
from `.env` through the existing allowlisted reader).

## Tests required
- Default and "on" session over `mcp.Client`: instructions, tools, skills, routing prompt.
- Install: switch off for six non-`1` values; on with and without a pinned image; on with
  no prior config; off-after-on rollback.
- Routing contract: default rows vs default config; whole table vs "on" config; skill
  checks over nine skills; "on" pins; reset restores default pins.
- Request path through the session: text-only result, chart with caption and checked PNG,
  text-only client, image-delivery failure, non-PNG render, malformed output (3 forms),
  deadline, oversized output, no engine, image missing from the engine, no pinned image,
  50-row boundary and caveats; `db`: the fixture reader through the session.
- Runner: opt-in case skipped and free while off, run while on.

## Acceptance criteria
- `ruff check .` and `ruff format --check .` pass; the offline suite passes; CI is green.
- Default pins unchanged in the diff; "on" pins added separately.
- The PR states: built and tested offline, opt-in, not installed, not live-verified.

## Verification commands
```sh
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m evals.run --suite ci
```

## Deliverables
An opt-in analysis capability whose activation is documented in
`docs/RELEASE_WO017_ANALYSIS.md` sections 1-4, with the live acceptance script in section 6.

## Stop conditions
Enabling routing would need a relaxed invariant, a new dependency, an OpenClaw feature the
repo does not already use, or a CI/gate change. Live image relay can only be proven on the
owner's phone.

## Status

2026-11-02: built and tested offline, in review. Opt-in, not installed, not live-verified.

Mechanism chosen: install-time gating with a second fragment,
`config/openclaw.analysis.json5`, merged by `scripts/install.sh` only when the tool
server's own `enabled()` check passes over `.env` (the WO-007 tracing-fragment
precedent). OpenClaw's frontmatter gating was checked and not used: the repo's skills use
only `requires.config`, and `requires.env` tests that a variable exists in the gateway's
process (which does not read our `.env`), not that it equals `1`. The instructions are
swapped by `register_analysis_tool()` from the same check (MCPServer exposes
`instructions` read-only, so the low-level server's attribute is set at start, before
any session; a test proves it reaches a real initialize result).

Decisions recorded (owner answers of 2026-11-02 noted on items 1 and 2):
1. The "can't help" line is the same in both states. It is copied verbatim in
   `config/IDX_RUNTIME.md` (the every-turn policy) and the market-stats skill, which cannot
   vary with the switch without changing the default; the release handoff's step to change
   it is not done. The tool is named in the instructions' tool list instead.
   **Owner decision, 2026-11-02:** keep the line unchanged; naming `bounded_analysis` in
   the enabled instructions is acceptable while routing rules stay consistent. This
   departs from the old handoff's "make it routable" step 3, which named the tool in the
   "can't help" line as well. The departure is documented in
   `docs/RELEASE_WO017_ANALYSIS.md` section 3. Routing is pinned in both states by
   `tests/test_routing_contract.py`.
2. Image relay. OpenClaw 2026.9.5 (read, not run) projects an MCP image block into a
   tool-result image for the model; its docs say tool-result images are not attached to
   channel replies automatically, and media goes out through the `message` tool, a
   `MEDIA:` line naming a workspace file, or a public https URL. The `idx` agent allows
   none of those (MCP tools and `read` only, workspace-only files). So the chart most
   likely reaches the model, not WhatsApp. The repo now makes the text whole without it.
   Options for the owner, none implemented: keep as is (text-only on WhatsApp); stop
   sending the image block to save model input; or approve a delivery path (each changes
   tool policy or adds a file side channel and needs its own review). The live check is
   acceptance step 6.1.
   **Owner decision, 2026-11-02:** charts must actually be delivered to users. The
   text-only fallback stays but does not complete the requirement. Delivery is a separate
   work order, WO-030. WO-027 does not implement it and does not claim chart delivery.
3. The routing fixture version stays `contract-v1`: every existing tool's reply is
   unchanged; only a reply for the newly routable tool was added.

Evidence (this branch, owner's Mac, 2026-11-02): `ruff check .` and `ruff format
--check .` clean; `MYSQL_HOST= pytest -q -p no:cacheprovider` 4,301 passed, 130 skipped
(offline; the skips are the `db`, `container` and other environment-gated tests);
`python -m evals.run --suite ci` with no database: 211 cases, 84 pass, 0 fail, 127
skipped ("no database"). Docker is not running on the Mac, so the `container` tests
skipped locally; CI builds the image and runs them. No local synthetic fixture database is configured (the
local MySQL is not the fixture), so the `db` tests were not run locally; CI runs them on
the synthetic fixture. CI evidence is separate from Mac evidence.

Combined review fix (2026-11-02): install and runtime could disagree silently.
`install.sh` read the switch from `.env` only, while the tool server let its process
environment win (an empty value included). So `IDX_ANALYSIS_TOOL=1` in the gateway's
environment with `.env` unset registered the tool and named it in the instructions with
no skill installed, and `0` or empty there with `.env`=1 left the skill installed and the
tool unregistered, with nothing reported either way. Now one rule,
`analysis.tool.switch_state()`, serves install, server and eval runner: `.env` decides,
and a contradicting environment is a configuration failure. `install.sh` stops before
writing; the server registers nothing and reports the problem in its start log and in
`health`. A differing `IDX_ANALYSIS_IMAGE` is reported the same way, but the tool stays
registered. Switching off and reinstalling now also removes the stale
`openclaw.analysis.json5` render. Every combination (environment 1/0/empty/absent/other
against `.env` 1/0/absent/other) is tested against a temp HOME and state dir, as are
default-off health and start-log byte identity and on-then-off rollback
(`tests/test_analysis_switch_agreement.py`). Tests that turn the switch on now set it in
`.env` (`analysis_switch_in_dotenv`), as an operator does. Not detected: a `.env` edited
after install without running install again (the section 2 probe counts catch it).

Owner steps remaining: build and pin the image and prove isolation on the Mac (handoff
section 1); set the switch, install, restart (section 2); run the acceptance script with
its own `paid` grant (section 6). Chart delivery waits on WO-030.
