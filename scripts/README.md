# scripts

Helper scripts that sit next to the package but are not part of it.

## Here now
- `gates/`: the commit gates run by pre-commit and CI (forbidden paths, confidential
  text, contact details). See `RULES.md`. Never edit a gate to get a commit through.

## Coming later
- `install.sh`: links each `skills/<name>/` folder into the OpenClaw workspace.
- `profile_data.py` (WO-002): profiles the two MLS tables and writes schema notes;
  it prints aggregates only and never writes rows into the repo.
- `migrations/`: numbered `.sql` files for indexes and derived columns. Besides
  `tests/fixtures/`, this is the only place a `.sql` file may be tracked.
