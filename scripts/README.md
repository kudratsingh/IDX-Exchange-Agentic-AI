# scripts

Helper scripts that sit next to the package but are not part of it.

## Here now
- `gates/`: the commit gates run by pre-commit and CI (forbidden paths, confidential
  text, contact details, protected deletions). See `RULES.md`. Never edit a gate to get
  a commit through.
- `guards/`: the Claude Code hook (`guard.py`) that blocks destructive commands, paid
  model runs, and edits to the enforcement unless a human consent token exists, and
  `consent.sh`, which only the human runs. See `docs/AGENT_RULES.md` and ADR-0002.
- `install.sh` (v0, WO-001): checks openclaw and node, renders `config/openclaw.idx.json5`
  with absolute paths and the owner's number from `.env` into `~/.openclaw/`, installs it
  when no config exists or deep-merges it into the existing config (backup kept), and
  registers the `idx` MCP server. Skills load in place from `skills/` through
  `skills.load.extraDirs`; nothing is linked or copied.
  With `IDX_OTLP_ENDPOINT` set in `.env` (WO-007) it also renders and merges
  `config/openclaw.otel.json5`, OpenClaw's tracing keys; unset, nothing about tracing.
- `openclaw_merge_config.py`: the deep merge used by `install.sh`. Reads one or more JSON5
  fragments, merges them over the wizard's JSON (our lists replace theirs), writes a backup.
- `jaeger-local.sh` (WO-007): runs the local Jaeger binary (gitignored, never downloaded by
  the script) with `config/jaeger-local.yaml`, loopback only. See `docs/TRACING.md`.

## Coming later
- `profile_data.py` (WO-002): profiles the two MLS tables and writes schema notes;
  it prints aggregates only and never writes rows into the repo.
- `migrations/`: numbered `.sql` files for indexes and derived columns. Besides
  `tests/fixtures/`, this is the only place a `.sql` file may be tracked.
