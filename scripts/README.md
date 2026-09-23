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
- `openclaw_merge_config.py`: the deep merge used by `install.sh`. Reads our JSON5
  fragment, merges it over the wizard's JSON (our lists replace theirs), writes a backup.

## Coming later
- `profile_data.py` (WO-002): profiles the two MLS tables and writes schema notes;
  it prints aggregates only and never writes rows into the repo.
- `migrations/`: numbered `.sql` files for indexes and derived columns. Besides
  `tests/fixtures/`, this is the only place a `.sql` file may be tracked.
