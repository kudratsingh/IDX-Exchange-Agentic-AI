# scripts

Helper scripts that sit next to the package but are not part of it.

## Here now
- `gates/`: the commit gates run by pre-commit and CI (forbidden paths, confidential
  text, contact details, protected deletions). See `RULES.md`. Never edit a gate to get
  a commit through.
- `guards/`: the Claude Code hook (`guard.py`) that blocks destructive commands, paid
  model runs, and edits to the enforcement unless a human consent token exists, and
  `consent.sh`, which only the human runs. See `docs/AGENT_RULES.md` and ADR-0002.

## Coming later
- `install.sh`: links each `skills/<name>/` folder into the OpenClaw workspace.
- `profile_data.py` (WO-002): profiles the two MLS tables and writes schema notes;
  it prints aggregates only and never writes rows into the repo.
- `migrations/`: numbered `.sql` files for indexes and derived columns. Besides
  `tests/fixtures/`, this is the only place a `.sql` file may be tracked.
