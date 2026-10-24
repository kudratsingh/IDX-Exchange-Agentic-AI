# Saved searches and new-listing alert drafts

This is an owner-only feature, using the same recipient configuration and approval
journal as [email drafts](EMAIL.md). It never collects an address in chat. The
`idx_alerts` process has four tools and its own private SQLite writer; the `idx`
process continues to read MLS data with the SELECT-only account.

After installing the code and restarting the gateway, send these one at a time:

```text
Find 3-bedroom condos in Pasadena under $1.5M
save this search
list saved searches
delete my saved search number 1
```

The last reply supplies a confirmation code. Reply with that code only if you want
the removal. `stop alerts` requests removal of all this sender's saved searches,
also with a confirmation turn. Outstanding pending or approved alert drafts are
expired before records are removed. A delivery already claimed by the operator
cannot be recalled. The append-only email audit journal is retained.

The default path is `data/state/alerts.sqlite`, already ignored by Git. Optional
`IDX_ALERTS_DB_PATH` must resolve inside ignored `data/`; it is read only by the
alerts process and job. No new dependency, service, or database grant is needed.
SQLite uses WAL, a busy timeout and transactions; the file is private (0600).
Searches retain validated filters, a hashed bucket key and snapshot dates, never
the raw sender or recipient address. The local browser uses the existing dashboard
bucket. Model-passed identity selects records, and grants no delivery authority.
Confirmation codes are bound to bucket, operation and search, expire in ten
minutes and work once. The skill requires a later human turn; the runtime does
not supply authenticated human-turn metadata to the server.

There are five searches per bucket and 200 overall. Searches lapse after 180 days;
list and explicitly remove a lapsed search before replacing it. A search retains
up to 500 alerted keys. At that limit the job refuses further additions until the
operator replaces the search, preserving the no-repeat rule instead of discarding
old keys. No background job deletes a saved search.

## Refresh and review

The reader's current active snapshot is compared with each search's last checked
date. Only matching homes with ListingContractDate after that date and no later
than the new snapshot qualify. Price or status edits alone do not qualify. An
unchanged snapshot produces no query for that search. Historical windows never
use today's date.

```bash
python -m idx_agent.alerts.run --dry-run
python -m idx_agent.alerts.run
python scripts/approve.py list
```

Dry-run reads and reports counts without changing saved-search or approval state.
The normal job creates at most one draft per search and active snapshot, with up
to ten cards and a count of additional matches. The summary includes pending IDs
and marks a first alert. No SMTP or model call occurs. Review, approve and deliver
each draft through the commands in EMAIL.md. Failed sends are never retried.

For a future manual rehearsal, obtain the private saved-search ID with
`python -m idx_agent.alerts.run --list` (no MLS query) and run
`python -m idx_agent.alerts.run --replay <search-id>`. Replay treats
the current matches as new but still creates only a draft, and still cannot create
another draft for the same search/snapshot. No replay was run against live state
during this build.

The journal and SQLite cannot commit atomically together. The job serializes with
removals while writing an idempotent draft and its alert-log row. If interrupted
between those writes, the next run receives the same draft ID. Removal expires by
saved-search prefix, including such an unlogged draft. A journal failure leaves
the saved search and its confirmation intact for operator inspection.

Exit codes: 0 complete; 1 unexpected failure; 2 settings or private-store refusal;
3 database unavailable at startup; 4 one or more searches failed while others may
have completed. The job prints counts and draft IDs, never addresses or source rows.

## Optional schedule, installed by the operator

Nothing installs a schedule automatically. Choose one of these after live
acceptance. This daily refresh spends nothing and creates drafts only when the
dataset snapshot advances. Keep output in ignored local data.

```cron
0 8 * * * cd /absolute/project && /absolute/project/.venv/bin/python -m idx_agent.alerts.run >> /absolute/project/data/alerts-job.log 2>&1
```

A macOS LaunchAgent alternative (replace every absolute path, create the ignored
log folder first, save locally in Library/LaunchAgents, and load it yourself):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.idx.alert-drafts</string>
  <key>ProgramArguments</key><array>
    <string>/absolute/project/.venv/bin/python</string>
    <string>-m</string><string>idx_agent.alerts.run</string>
  </array>
  <key>WorkingDirectory</key><string>/absolute/project</string>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/absolute/project/data/alerts-job.log</string>
  <key>StandardErrorPath</key><string>/absolute/project/data/alerts-job-errors.log</string>
</dict></plist>
```
