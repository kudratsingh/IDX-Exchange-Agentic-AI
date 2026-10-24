# ADR-0008: Local saved searches and draft-only alerts

2026-10-24. The human asked to build all remaining handbook capabilities offline.

Use stdlib SQLite in ignored `data/state/alerts.sqlite`, with WAL, a busy timeout,
private permissions and explicit transactions. A separate MCP process owns this
writer; the MLS reader retains SELECT-only credentials. A local spike on SQLite
3.53.4 verified that a second process reads committed state during a writer's
transaction. No database service or dependency is added.

An aggregate reader check found all 55,212 rows in the active-listings table have ListingContractDate;
none is after the active snapshot, 2026-09-18. New means a matching listing whose
contract date is after the saved check date and no later than the new snapshot.
Modification-only changes do not qualify. Each query returns at most 50 rows.
Already alerted keys are excluded; refreshes generate one idempotent draft per
search and snapshot. The job never imports a delivery transport.

WO-015's newer owner-only recipient decision supersedes the early WO-009 proposal
to collect addresses in chat. Saved searches store the owner label, never another
address; code resolves the configured recipient when drafting. Sender hashes pick
records and confer no delivery authority. Blank sender uses the existing local
dashboard bucket. Five searches per bucket and 200 overall are enforced in SQLite.
Searches lapse after 180 days. Deletes and forget require a single-use, ten-minute
confirmation bound to bucket, operation and target. Outstanding alert drafts are
expired before their search records are removed.

The email journal and SQLite cannot share a transaction. The job holds the SQLite
write lock while creating an idempotent draft and recording it. If interrupted,
retry returns that same draft. Forget expires by the saved-search idempotency
prefix, including drafts created before an interrupted SQLite commit.

This implementation is based on PR #81's approval gate. It must not be installed or
merged ahead of that dependency. Live routing, the scheduler and delivery remain
operator steps after the credential change.
