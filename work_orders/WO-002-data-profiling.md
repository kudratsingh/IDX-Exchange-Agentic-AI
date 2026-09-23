# WO-002 — MLS data profiling

**Driver:** human runs everything against the local database; the agent writes the profiling script and the
migration script. No agents, no skills, no model calls.
**Depends on:** WO-000 (the database import is a local, manual step; see "Local setup")
**Estimated effort:** 2-3 hours

## Objective
Know the data before writing a query against it: a schema notes draft, the column allowlist and deny-list,
valid-value sets, both as-of dates, exclusion rules, and a migration for date columns and indexes.

## Why
The handbook documents about 45 of 130+ columns, stores dates as text, stores counts as doubles, and has two
status columns. Every later component depends on knowing which values are real.

## Local setup (human, not committed)
Create database `idx_exchange`; check the first lines of both dump files for a schema name before importing;
import both tables; create a SELECT-only user `idx_reader`; put its credentials in `.env`. Dumps stay in `data/`.

## Inputs
`docs/ARCHITECTURE.md` section 3; `docs/SAFETY_INVARIANTS.md` deny-list candidates; `docs/CONTRACTS.md` (Listing, SoldComp).

## In scope
`scripts/profile_data.py` (read-only, parameterized, aggregates only) that writes `docs/data/schema_notes.md` and prints a summary. It reports, for both tables:
1. Row counts.
2. Every column: name, type, null and empty rate. Flag by name pattern: deny-list candidates (`AccessCode`, `LockBox*`, `PrivateRemarks`, `PrivateOfficeRemarks`, `ShowingInstructions`, `Owner*`, `Occupant*`) and agent contact fields (`*Agent*Email`, `*Agent*Phone`, `*Agent*Name`, `LA1_*`).
3. Dates: min and max of `CloseDate`, `PurchaseContractDate`, `ListingContractDate` (both tables), `ModificationTimestamp`; share of values that are not clean `YYYY-MM-DD`. Derive the two as-of dates.
4. Status: distributions of `L_Status` and `StandardStatus`, and a cross-tab of the two.
5. Distinct values and counts for `L_Class`, `L_Type_`, `PropertyType`, `PropertySubType`, and each True/False/empty flag.
6. City spellings: distinct `L_City` and `City` values, with casing variants grouped.
7. Days on market: on a sample, `DaysOnMarket` versus `PurchaseContractDate - ListingContractDate`.
8. Duplicates: repeated `ListingKey`; repeated address plus close date in california_sold.
9. Outliers: percentiles of `ClosePrice`, `LivingArea`, lot size; proposed floors.
10. Unit and frequency columns if present: `AssociationFeeFrequency`, `LivingAreaUnits`, `LotSizeUnits`.
11. Display flags if present: `InternetEntireListingDisplayYN`, `InternetAddressDisplayYN`.
12. `L_Photos`: share parseable as a JSON array; null or zero coordinates.
13. Existing indexes on both tables.

Then, from the results:
- `src/idx_agent/safety/columns.py`: `ALLOWLIST` per table (only columns the contracts need) and `DENYLIST` (confirmed present sensitive columns), plus `AGENT_CONTACT` (present, allowed in the data layer, never returned).
- `src/idx_agent/domain/valid_values.py`: cities (normalized), subtypes, status values, flag encodings.
- `scripts/migrations/001_dates_and_indexes.sql`: real DATE columns for the text dates (generated columns or populated columns), indexes on `City`, `PostalCode`, `PropertySubType`, and the close-date column. Applied locally by the human; never in CI.
- `docs/data/schema_notes.md`: the canonical map (RESO name | rets_property | california_sold | note), the findings above, the decision on which status column defines "active", the exclusion rules, both as-of dates, the deny-list.

## Out of scope
Any query used by the product, any agent, embeddings, the synthetic fixture (WO-005).

## Files expected to change
`scripts/profile_data.py`, `scripts/migrations/001_dates_and_indexes.sql`, `src/idx_agent/safety/columns.py`,
`src/idx_agent/domain/valid_values.py`, `docs/data/schema_notes.md`, `docs/DECISIONS.md` (status column, exclusions).

## Interfaces and contracts
`columns.py` must expose `ALLOWLIST: dict[str, frozenset[str]]`, `DENYLIST: frozenset[str]`, `AGENT_CONTACT: frozenset[str]`.

## Implementation requirements
1. The script connects with `idx_reader` only and refuses to run as any other user.
2. It never writes rows to disk: aggregates, counts, distinct values, and percentiles only. Distinct-value listings are capped at 200 values per column and never include free-text columns.
3. It never prints or writes agent names, emails, phones, or deny-listed column contents.
4. `schema_notes.md` is written in our words; no handbook text.
5. The migration is idempotent (safe to run twice).

## Safety requirements
SELECT-only user; no row exports; deny-listed contents never read into the notes; nothing from `data/` tracked.

## Tests required
`tests/test_columns.py`: allowlist and deny-list are disjoint; every allowlisted column exists in `schema_notes.md`; no agent contact field is in any allowlist (they live in `AGENT_CONTACT`).

## Acceptance criteria
- `docs/data/schema_notes.md` contains: row counts, both as-of dates, the status decision, the subtype list, the deny-list, the allowlist, the exclusion rules, date-format findings, duplicate findings, the index plan.
- `columns.py` and `valid_values.py` exist and their tests pass.
- The migration has been applied locally and `SELECT` on the new date columns works.
- No tracked file contains a row of real data.

## Verification commands
```
python scripts/profile_data.py --write docs/data/schema_notes.md
mysql -u <admin-user> -p idx_exchange < scripts/migrations/001_dates_and_indexes.sql   # once, as an admin; the app never uses this user
pytest tests/test_columns.py
git diff --stat   # only the files listed above
```

## Deliverables
The script, the migration, the two Python modules, the schema notes.

## Stop conditions
- A column the contracts rely on does not exist (for example `L_Keyword2`): note it and ask before mapping a substitute.
- The dump cannot be imported as documented.
- Any output would need real rows to be useful.

## Status
**Agent part drafted on 2026-09-23; blocked on the local database.** Branch `wo-002-data-profiling`.

### Done (agent, without a database)
- `scripts/profile_data.py`: read-only profiler. Refuses any user but `idx_reader`, sets the
  session read-only, quotes identifiers from information_schema, binds every value, caps
  distinct listings at 200, never lists free-text, deny-listed, or agent-contact values,
  reports every section the WO asks for (1-13), and writes `docs/data/schema_notes.md`
  with the canonical map and a Decisions block to fill by hand. A section that fails is
  recorded by error class and the rest still runs.
- `scripts/migrations/001_dates_and_indexes.sql`: idempotent (information_schema checks in
  two small procedures), generated DATE columns beside the text dates, indexes on city,
  postal code, subtype, close date, price, and listing key, for both tables. Missing
  columns are skipped with a note rather than failing.
- `src/idx_agent/safety/columns.py`: `ALLOWLIST` per table, `DENYLIST`, `AGENT_CONTACT`,
  and `check_column()`. Marked PROVISIONAL: names come from the architecture and contract
  docs and the invariant candidates; the run confirms them.
- `src/idx_agent/domain/valid_values.py`: normalization rules and empty sets to be
  filled from the run; the status decision fields are `None` until decided.
- `tests/test_columns.py`: disjointness, no agent contact in any allowlist, deny-list
  covers every invariant candidate, `check_column` behavior; the "every allowlisted column
  exists in schema_notes.md" test skips until the notes exist.
- New runtime dependency, noted as CLAUDE.md requires: `pymysql>=1.1,<3`.

### Blocked until the human's local setup
- The dump files are not on this machine yet (`data/` holds only `knowledge/`).
- MySQL is not installed. Suggested: `brew install mysql && brew services start mysql`,
  then as the admin user: create `idx_exchange`, check the first lines of both dumps for
  a schema name, import both, then
  `CREATE USER 'idx_reader'@'localhost' IDENTIFIED BY '<pw>'; GRANT SELECT ON idx_exchange.* TO 'idx_reader'@'localhost';`
  and put the credentials in `.env`.
- `.gitignore` ignores every folder named `data/`, which also hides `docs/data/`; it must
  become `/data/` (a `gates` consent token, since `.gitignore` is enforcement).

### Then, in order
1. `python scripts/profile_data.py --write docs/data/schema_notes.md` (as `idx_reader`).
2. Read the notes; fill the Decisions block; fix names in `columns.py` and fill
   `valid_values.py` from sections 4-6; move the status decision to `docs/DECISIONS.md`.
3. Apply the migration once as the admin; `SELECT close_date_d FROM california_sold LIMIT 1`.
4. `pytest tests/test_columns.py`; commit the notes (aggregates only, no rows).
