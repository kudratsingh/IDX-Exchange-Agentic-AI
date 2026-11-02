# ADR-0014: A private effective-facet store for remark-feature search

**Status:** accepted 2026-11-02 by the human, who authorized WO-021 integration development
and offline testing. Production deployment needs separate approval.
**Date:** 2026-11-02
**Work order:** WO-021

## Context
WO-018 extracted remark facets for 54,888 active listings and corrected them with two frozen
review overlays (the 471-case diagnostic overlay and the dataset policy audit). Search runs
on the MySQL listings table, with a SELECT-only user and 50-row results. The facets live in
a private SQLite file under `data/enrichment/`. Applying overlays at query time would reread
two large private JSONL files on every call. Writing facets into MySQL would need write
access, which the reader must never have.

## Decision
An offline script, `scripts/build_enrichment_effective_store.py`, refuses to run unless all
seven frozen audit artifacts match the freeze manifest and the results table is exactly what
the audit certified: every row, remark hash and provenance, the 471 diagnostic and 46,420
policy-audit rows, the frozen scope's counts, the extraction's verified source watermark,
which the freshness test depends on, and a frozen canonical digest of all 54,888 result
records (sequence, listing key, source-text hash, facets, diagnostic count, usage and
extractor), so rows outside both audit packets are covered too (`enrichment.source_check`).
The digest is an approved constant in code; a build never computes its own expected value. It applies each listing's overlay to
the original results and writes one private SQLite file. The file holds per-listing facet
statuses (`present`, `stated_absent`, `contradictory`, `planned`, `uncertain`, `historical`;
a missing facet is not stored and stays unknown), the set of covered listings, and metadata:
schema version, source watermark, policy and rules versions, and the manifest it was built
from, including how many results it validated; a store covering a different number of
listings does not open. It holds no remark text. The file is written atomically with owner-only permissions.

The tool server reads the path from the new `IDX_ENRICHMENT_STORE` setting and opens the
file read-only on a feature search only. A store that is missing, unreadable, from another
schema, incomplete or malformed is unavailable, and the feature search fails closed. The
store's listing keys for the requested features are bound into the existing allowlisted,
parameterized listing query, which also excludes any listing ID with a row modified after
the watermark. A listing changed after the snapshot, including through an older row of the
same ID, is therefore never matched on features that may be out of date.
If more than 10% of active listings changed since the snapshot, the whole store counts as
stale.

## Consequences
- No new dependency or service. SQLite is in the standard library and already holds the
  extraction results. The reader stays SELECT-only.
- A rebuild is required whenever the overlays, rules, policy or source change; the builder
  re-verifies the freeze each time.
- Feature filters inherit the audit's documented limits: an estimated ~1,600 uncorrected
  rule-kept errors and ~600 read errors, no search for features the extractor missed, and
  six facets audited only in the diagnostic cases. Every feature result shows a limitation
  line, and a missing feature is unknown, not absent.
- The largest key set today is about 25,000 bound values. The query layer caps a scope at
  40,000 keys; a larger scope is refused as `unavailable`, never run without the scope.
- Saved-search alerts do not apply remark features. `save_search` refuses them rather than
  saving a broader search, and the alert query refuses a saved search that holds them.
