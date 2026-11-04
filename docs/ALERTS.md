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

Dry-run takes every decision the normal job takes and reports the same `checked`,
`skipped`, `failed`, `deferred`, `unavailable` and `unavailable_reasons` counts and the
same exit code, so a store behind the active data (`snapshot_behind`, exit 5), a
deferral, or the alerted-key cap (exit 4) shows up there first. It is strictly
read-only: it never opens the approval journal, creates no draft and no alert-log row,
moves no checked date, and reads the alert store only through a read-only SQLite
connection (`drafts` stays 0 and `pending` empty). SQLite may leave its empty `-wal`
and `-shm` side files beside the store after a read; the store file itself is unchanged.
The next normal run can still differ through a step the dry-run does not take (a
journal failure while drafting) or a concurrent job or removal in between.
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
have completed; 5 nothing failed, but one or more saved feature searches were
unavailable (below). `--dry-run` returns the code the normal job would return for the
same state (never one for a draft or journal step it does not take). The job prints
counts and draft IDs, never addresses or source rows.

## Saved feature searches (WO-025, off by default)

A saved search may carry the listing `features` of a feature search (the same names,
at most five) when `IDX_FEATURE_SAVED_SEARCHES=1` is set in `.env` and the
`IDX_ENRICHMENT_STORE` used by feature search is usable. With the switch off, a save
with features is refused exactly as before. With it on, the save checks the features
once; if the store is unconfigured, missing, stale, too broad or failing, the save is
refused with a question and nothing is stored. A search is never saved without its
features unless the user asks again without them. Saving the same feature search
twice (page and page size do not count) answers with the existing saved search while it
is active. If that search has lapsed (180 days), the save renews it in place instead and
says so ("Search N had lapsed, so I renewed it: ..."): another 180 days from now, alerts
only for listings first listed after the save's horizon, and the listings it already
alerted are never alerted again. A lapsed search is never reported as already saved.
Another sender's equal search, active or lapsed, never matches. To change a saved
search, save the changed one and remove the old one with confirmation.

The job matches a feature only where the shared feature access (WO-023) says it is
present and the listing has not changed since the enrichment snapshot. Unknown,
never-extracted and changed listings never match; the draft names the features, the
snapshot day, how many new listings were left out as changed, and the accuracy
limitation. A feature search is checked only up to the snapshot day, because listings
first listed after it are not in the store yet; they are checked after a rebuild.

Changed listings are deferred, not skipped. A listing first listed in the window that
matches the search's other filters, was not alerted before, and has a row changed after
the snapshot cannot be checked by that snapshot (matched there or not). The job then
moves the search's checked date only to the day before the earliest such listing,
never past it, and counts the search under `deferred` in the summary. Later runs
re-read that window; listings already alerted are excluded, so nothing is alerted
twice, and the alert log still allows one draft per search and horizon, so retries and
repeated runs reuse the same draft. After a store rebuild covers the change, the
listing is checked like any other and alerted once if it has the features. A rebuild
that leaves the horizon where an earlier draft already used it waits for the next
horizon. A listing with no recorded change time can never be checked and never holds
the date back; the hold ends when the listing leaves the active set or the search
lapses. No storage change: this uses the existing checked date.

A held date never hides a stale store. A run that has nothing left to do for a held
search (its horizon was already drafted, or nothing new matched and the date is still
held) changes nothing and says why: when the active data is past the snapshot day the
search is `unavailable` with `snapshot_behind` (exit 5, the signal to rebuild the
store), exactly as for a search that is not held; when the store is level with the
active data it is counted under `deferred`.

When the switch is off, the store is unusable, binding fails, or the snapshot ends
before the search's next window, that search is reported as `unavailable` with a fixed
reason (`not_enabled`, `not_configured`, `missing`, `stale`, `too_broad`, `closed`,
`failed`, `snapshot_behind`, or another store code). It gets no draft and no
"no new matches" outcome, and its checked date and alerted keys stay as they were, so
nothing is lost once enrichment is back. Other searches in the run continue.

Rollback: unset `IDX_FEATURE_SAVED_SEARCHES` (or the store). Saved feature searches then
list as "alerts paused: listing features are off" and stay unavailable; they are never
checked as the broader search without features. Code from before WO-025 also refuses
them (counted as failed). No storage migration exists or is needed.

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
