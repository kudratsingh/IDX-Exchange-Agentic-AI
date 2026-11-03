# Enrichment refresh preflight (WO-021)

A read-only check of what a future refresh of the effective-facet store (ADR-0014) would
have to do. It compares the listings the store covers, and the store's source watermark,
with the current rows of `rets_property`. It changes nothing: no labels are extracted, no
model or API is called, the frozen extraction source and the effective store are opened
read-only or not at all, and the listings database is only read.

## Classes

Every listing ID in scope gets exactly one class. In scope means: covered by the store,
or holding at least one active (or unknown-status) row in the listings table. An inactive
ID the store never covered is outside the scope and only counted.

| Class | Meaning |
|---|---|
| `unchanged` | In the store; every row at or before the watermark; active. |
| `changed` | In the store; some row modified after the watermark. |
| `new` | Active, not in the store, with a row modified after the watermark. |
| `never_extracted` | Active, not in the store, every row at or before the watermark. |
| `no_longer_active` | In the store, with no active row now, including a key the table no longer holds (`absent_from_source`). |
| `ambiguous` | Anything the preflight cannot classify with certainty (reasons below). |

Ambiguity is checked first and wins over every other class. The reason codes, in the
order they are tested:
`key_not_digits` (the key is not an ASCII digit string), `duplicate_store_key`,
`unknown_timestamp` (a NULL or unparseable change time on any row), `after_as_of` (a row
newer than the data's own latest change time read before the scan), `unknown_status`
(a blank or NULL status), `conflicting_status` (rows of one ID disagree on whether it is
active), and `unordered_duplicate` (several rows share the ID's latest change time, so
which row is current cannot be told).

**Usable:** only `unchanged`. Those listings could keep their stored facets in a refresh
without re-extraction. `changed`, `new` and `never_extracted` would need extraction;
`no_longer_active` would leave the store; `ambiguous` needs a human look first. The
preflight fails closed: an uncertain listing is never counted as `unchanged`.

## How it reads the data

- The store is opened through `open_store` (SQLite `mode=ro`), so a missing, malformed,
  incomplete or other-schema store is refused, exactly as the search refuses it.
- The listings table is read in keyset pages of at most 50 rows:
  `L_ListingID, ModificationTimestamp, StandardStatus ... WHERE L_ListingID > %s ORDER BY
  L_ListingID LIMIT %s`. A full page holds back its last ID and the next page re-reads it
  whole, so an ID with several rows is never split across pages. An ID filling a whole
  page, or keys arriving out of order, stop the run.
- Aggregate COUNT queries run before and after the scan. The run is refused if the counts
  or the latest change time moved during the scan, or if the pages did not read every
  keyed row and every distinct ID.
- A store watermark later than the data's latest change time is refused outright.

## Running it

From the main checkout (so `.env` is found):

```
python scripts/refresh_preflight.py            # --store, --output, --overwrite optional
```

It writes the private per-listing inventory to
`data/enrichment/refresh/preflight-inventory.jsonl` (one JSON line per classified ID:
key, class, reason, row count, latest change time), with owner-only permissions in an
owner-only directory, and prints aggregate counts only. `data/` is gitignored
(`git check-ignore` confirms the path). The script refuses any output that is not a
`.jsonl` file under `data/` (symlinks are resolved first), and will not replace an
existing inventory without `--overwrite`.

## Result on the local data (2026-11-02)

Store watermark and data as-of are both `2026-09-18 06:58:44`.

| Measure | Count |
|---|---|
| Store listings | 54,888 |
| Source rows / distinct listing IDs / active IDs | 55,212 / 55,209 / 55,209 |
| Rows without a key or a change time | 0 / 0 |
| `unchanged` (usable) | 54,885 |
| `changed` | 0 |
| `new` | 0 |
| `never_extracted` | 321 |
| `no_longer_active` | 0 |
| `ambiguous` (`unordered_duplicate`) | 3 |
| Outside the scope | 0 |

The three ambiguous IDs are the store-covered IDs that hold two rows with the same
change time. The search treats them as unchanged, since no row is after the watermark;
the preflight is stricter because it cannot tell which row the extraction read. Both
stores' SHA-256 digests were identical before and after the run.

## Limitations

- The local database is a frozen snapshot, so `changed`, `new` and `no_longer_active`
  are zero here and are exercised only by the synthetic tests. Every row is `Active`.
- Change detection rests on `ModificationTimestamp` alone. An edit that does not move
  it, or that touches columns the extractor never read, is not seen either way.
- Only three columns are compared. Two rows of one ID with the same time and status are
  ambiguous even if their remarks are identical, because the remarks are not read.
- Keyset paging relies on the database's string order of `L_ListingID`. With digit keys
  this matches Python's order; odd keys under a case- or space-insensitive collation can
  stop the run through the order or count checks rather than be classified.
- The before-and-after counts detect most concurrent changes but are not a snapshot
  transaction; on a live database, rerun after a refusal.
- The inventory says what a refresh would need. It does not run, schedule or approve one.
