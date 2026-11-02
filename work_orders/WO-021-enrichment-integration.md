# WO-021: Enrichment integration

**Status: Phase 1 (search filters) authorized 2026-11-02 for development and offline
testing; in review.** Production deployment and paid calls need separate approval.
Deliverables 2-4 below remain drafts and are not built.

## Eligibility and data

Only categorical facets with held-out polarity-aware overlap F1 >= 80% **and**
at least 10 gold examples are eligible for search, cards, recommendations, or
alert triggers. The overall held-out structured F1 gate also passed. A facet's
absence is unknown, not false; only an affirmed current or unspecified-time
mention may be surfaced as a present feature. Contradictory, uncertain, planned,
or historical mentions must not be presented as current facts. Retain source
snapshot provenance and fail closed when the facet table is incomplete or stale.
Raw remarks, listing keys and per-listing predictions remain private. Do not
change the frozen extractor, prompt, schema, model or held-out scorer.

The 20 eligible facets and support/F1 are listed in WO-018's current Status and
`docs/ENRICHMENT_HELDOUT_RESULTS.md`. In particular, as-is (2), back on market
(2), and price reduction (6) do **not** meet the support threshold. Their alert
triggers stay disabled until independently approved evidence meets the rule;
never infer a transaction event just from a static remark.

## Proposed deliverables and evals

1. **Search filters.** Extend `search_listings` with an allowlisted typed facet
   filter and distinguish no match, unavailable, stale and unsupported facets.
   Evals: eligible affirmed matches, negated/uncertain/planned exclusion,
   unknown facet refusal, no-match handling, stale/missing table fail-closed,
   pagination and combined ordinary filters.
2. **Card badges.** Show eligible present facets only, with snapshot attribution
   and deterministic rendering. Evals: affirmed versus uncertain/negated/planned,
   zero badges, unqualified facets excluded, stale table, and card field relay.
3. **Recommendation features.** Add eligible features to a documented,
   deterministic ranking; preserve the price check and avoid overclaiming missing
   data. Evals: controlled ordering with equal baseline candidates, missing and
   uncertain values, unqualified facet exclusion, price-check invariance, and
   ranking regression on the existing suite.
4. **Deal-signal alerts.** Draft event comparison and deduplication for as-is,
   back on market, and price reductions, with clear source and timestamp. Keep
   all three disabled under the current support gate, and keep the existing
   approval-before-delivery rule. Evals: synthetic event transition, no-repeat,
   false/uncertain exclusion, disabled gate, stale input, approval and delivery
   controls. A static as-is mention is not itself a new event.

## Review decisions

Owner reviews feature semantics, source freshness, per-facet eligibility,
score weights, trigger thresholds and messaging before implementation. Any
future eligibility change needs new independently evaluated evidence; the
held-out set is not a tuning set. No user-visible behavior changes under this WO
until it is approved and built.

## Phase 1 scope (owner-authorized 2026-11-02)

**In scope:** deliverable 1, an allowlisted remark-feature filter on `search_listings`,
built on the original extraction results plus both validated correction overlays (the
471-case diagnostic overlay and the dataset policy audit, policy v4, rules
`2026-11-01.4`). **Out of scope:** card badges, recommendation features, deal-signal
alerts, production deployment, any paid call or re-extraction, and any change to the
frozen extractor, overlays or benchmark labels.

**Data.** `scripts/build_enrichment_effective_store.py` refuses to build unless every
frozen audit artifact matches the freeze manifest. It applies each listing's overlay and
writes a private, owner-only SQLite store (ADR-0014) holding per-listing facet statuses,
the covered listings and provenance: source watermark, policy and rules versions, and the
manifest. No remark text is stored. Built 2026-11-02: 54,888 listings; 168,333 present,
5,358 uncertain, 1,346 planned, 312 stated absent, 168 historical and 10 contradictory
facet statuses. Facets with no label are not stored and stay unknown.

**Semantics.** Only `present` (an affirmed current or unspecified-time mention) matches a
feature filter. Planned, uncertain, historical, stated-absent (negated) and contradictory
statuses never match, and a missing label is unknown, never false. All requested features
must be present. Searching for a feature's absence is not supported.

**Freshness and failure.** A listing changed after the store's source watermark is not
matched on features, and the reply counts those left out. If more than 10% of active
listings changed since the snapshot, the store is stale. A store that is missing, from
another schema, incomplete or malformed is unavailable. Both cases fail closed: no listing
is matched on features, the result says why, and the reply offers a search without
features. A search without features never opens the store and is unchanged.

**Accuracy limitations, kept visible.** Every feature result carries and shows a fixed
limitation line. The WO-018 audit's estimates still apply: about 1,600 uncorrected
rule-kept errors and about 600 uncorrected read errors among 125,845 audited labels, no
search for features the extractor missed, and six facets (garage, stainless appliances,
condominium, single level, near transit, near grocery) audited only in the 471 diagnostic
cases. These are review measurements, not a production accuracy claim, and production
readiness still needs end-to-end search tests.

**Status 2026-11-02.** Implemented on branch `wo-021-enrichment-search`. Tests cover
overlay application, per-status resolution (current, unspecified, planned, uncertain,
historical, negated, contradictory, missing), store validation and fail-closed cases,
bound SQL with snapshot freshness, unchanged SQL without features, the tool's applied,
unavailable and stale outcomes, follow-up merges and the reply limitation. An offline
smoke run on the real store and the local listings database matched the expected
statuses: city-only 316 listings; solar 14; solar plus walk-in closet 0; 0 listings changed
since the snapshot. No paid call was made and nothing was deployed.

An independent adversarial review before the first commit found, and this change fixes:
- A page past 1 with no feature matches reported the count without features; it now
  reports 0 and never counts without the scope.
- After an unavailable or stale refusal, the offered search ran against the previous stored
  search; the refusal now stores the requested search (amended after owner review, below).
- Saving a feature search silently dropped the features; `save_search` now refuses features
  and the alert query refuses a saved search that holds them.
- The store was not closed when the database connection failed; it now closes on every path.
- An oversized scope raised a database error; it is now refused as `unavailable`.
- The new keys appeared as nulls in searches without features; unset keys are now left out.
- The setting is documented in `.env.example`, and the property-search and saved-searches
  skills describe features, refusals and the limitation line.

Owner review of `260ec28` found three issues, fixed with regression tests:
- **A refusal dropped the features from the stored search**, so a later refinement ran
  without them although the user never accepted the broader search. The refusal now
  stores the requested search with its features; a refinement keeps them and is refused
  again, and only an explicit `clear: ["features"]` broadens it.
- **The builder could certify an incomplete source.** It now re-validates the results
  table before writing a store: every row, remark hash and provenance, diagnostic and
  policy-audit coverage, the frozen scope's counts, and an overlay row for every audited
  inventory row (`enrichment.source_check`, shared with the review validator). The store
  records the validated row count and does not open with a different number of listings.
  Dropping one result from a copy of the real source is now refused.
- **An older row of a changed listing could bypass freshness.** The search now excludes
  any listing ID with a row modified after the snapshot, and the left-out count counts IDs.
  A test runs the generated SQL on a real SQL engine with an old and a newer row for one
  ID. The local listings database has three active IDs with more than one row.

A second adversarial check of those fixes found four more issues, also fixed with tests:
an empty `features` list in an update cleared the refused features (it now means "not
given"); a refused page past 1 was stored, so "more" would skip pages once the store
returned (it is no longer stored); the builder did not pin the source watermark, so a
raised watermark would have disabled freshness (it must equal the verified extraction
watermark in both the settings and every verification row); and a row with no recorded
modification time would have counted as unchanged (it now counts as changed).
