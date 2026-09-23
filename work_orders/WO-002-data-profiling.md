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
**Done on 2026-09-23.** Draft in PR #5 (branch `wo-002-data-profiling`); the run and its
outcomes in the closing PR (branch `wo-002-profiling-run`).

### Local setup and the run (2026-09-23)
- MySQL 26.7 via Homebrew; database `idx_exchange`; both phpMyAdmin dumps imported (they
  name a schema only in a comment, so they load into any database). A first import of
  the sold table stopped partway; the partial table was dropped with the human's consent
  and re-imported. Counts match the dumps' INSERT statements: rets_property 55,212 rows,
  california_sold 98,552 rows. The third dump (`rets_openhouse.sql`) is out of scope.
- `idx_reader` created with a generated password stored in the gitignored `.env`;
  `SELECT` works, `INSERT` is refused (error 1142).
- `scripts/profile_data.py` ran as `idx_reader` in 49 s and wrote
  `docs/data/schema_notes.md` (aggregates only; the PII and confidential-text gates pass
  on it). Two fixes came out of the run: date columns are cast to CHAR because two of
  them are real DATE/DATETIME types, and the sold as-of date ignores rows dated after
  the active as-of date. The canonical map and the decisions are rendered by the script
  so they cannot drift from the code.
- Migration applied as the admin, then applied again: the second run skipped all 15
  steps. It needed one change: the dumps carry zero-date defaults that strict mode
  rejects on a table rebuild, so the session drops the two zero-date flags and restores
  them. Generated columns verified: `close_date_d` 2026-03-18 to 2072-06-29 with no
  nulls, `listing_contract_date_d` from 2010-10-09, `modification_d` to 2026-09-18.
- `.gitignore` anchored to `/data/` (PR #8) so `docs/data/` is tracked.

### Findings that changed assumptions
- The sold data covers 2026-03-18 to 2026-09-17, about six months, not 2021-2025.
  Four rows carry typo close years (2028-2072); five close before their contract date.
- Every active row is `Active` in both status columns; `StandardStatus` is the rule.
- Both tables use the same RESO subtype vocabulary (20 values); no mapping needed.
- No deny-list candidate column exists in either table. Agent-contact columns exist in
  both (11 and 7 names) and are listed in `columns.py`, never returned.
- The sold table has no index at all; the active table already indexes city, zip, id,
  and subtype. 34 sold listing keys repeat; 114 address-plus-close-date pairs repeat.
- Stored DaysOnMarket differs from the contract-minus-listing derivation by 8.6 days on
  average (63% within one day); the stored column is used, the derivation is not.
- Flags encode "1" for yes, empty for not marked, null for unknown; `parse_flag` follows
  that. City names have no casing or spacing variants (1,082 distinct across both tables).
- Display flags (`InternetAddressDisplayYN` and the like) do not exist; addresses are
  shown as stored. Coordinates are null or zero in about 1% of rows.

### Deliverables in the closing PR
- `docs/data/schema_notes.md` (generated), `src/idx_agent/safety/columns.py` with the
  confirmed names, `src/idx_agent/domain/valid_values.py` filled (cities from
  `cities.txt`, subtypes, active rule, flag encoding), the migration with the sql_mode
  guard and an index-by-column check, `docs/DECISIONS.md` and `docs/ARCHITECTURE.md`
  corrected, `tests/test_columns.py` extended (the notes-existence test now runs).

### Done (agent, before the database existed; PR #5)
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

### Left for later work orders
- WO-003 builds `fieldmap.py` from the canonical map in the notes.
- WO-004 decides the exact price and area floors from the percentiles in section 9 and
  records the exclusions it applies; the notes hold the numbers.
- A dedicated agent-contact scrub for logs uses the names in `columns.py` (WO-004).
