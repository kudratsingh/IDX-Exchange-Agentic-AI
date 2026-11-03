# WO-021: Enrichment integration

**Status: Phase 1 (search filters) merged 2026-11-02 (PR #134, `7f10734`); offline
acceptance, performance and a semantic spot check in review.** Not deployed: production
deployment and paid calls need separate approval. Deliverables 2-4 below remain drafts.

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

**Frozen results digest (owner request, 2026-11-02).** About 7,997 result records sit
outside both audit packets, so the coverage checks alone did not pin their facets or
provenance. `enrichment.source_check.results_digest` is a canonical sha256 over all 54,888
original result records: sequence, listing key, source-text hash, parsed facets in stored
order, diagnostic count, usage and extractor, one key-sorted JSON line each. The approved
value `46cd0a6be8cece97e09d3865ee87aae80c17fe2b16e4aaaa1412f87649209815` was taken from the
source the WO-018 completion gate validated (unchanged since 2026-10-29) and is a constant
in code. The builder must match it and never computes its own expected value. Tests refuse
facet, added-facet, provenance and usage edits on a row outside both packets. On a copy of
the real source, a facet edit and a provenance edit outside both packets were each refused.
The real store was rebuilt and revalidated: 54,888 listings, unchanged statuses.

## Offline acceptance (2026-11-02, after PR #134 merged as `7f10734`)

**Automated tool-path acceptance, not live acceptance.** `tests/test_feature_search_acceptance.py`
drives the real `search_listings` path: validation, session memory, a real effective store
built by `effective_rows` from invented results and both overlay kinds, the real SQL
builders executed on an SQLite stand-in for `rets_property`, paging, payload and the
rendered reply. Only the connection and the as-of dates are substituted. No model, gateway
or WhatsApp channel was exercised; that needs the human-run script in
`docs/RELEASE_WO021_SEARCH.md`.

| Row | Scenario | Expected | Observed |
| --- | --- | --- | --- |
| A1 | Each of the 20 eligible facets, alone | Only present listings match; count is the scoped count | 20/20 pass |
| A2 | Present (current, unspecified), planned, uncertain, historical, negated, contradictory, unknown, never extracted | Only the two present forms match; unknown is not stored | Pass for every facet |
| A3 | Several features; features with beds, price, city; 5 and 6 features | All features required; ordinary filters still apply; 6 asks which matter | Pass |
| A4 | Diagnostic removal, diagnostic accepted, dataset retag, dataset added label | Each changes the outcome versus a store built without overlays | Pass |
| A5 | Unconfigured, missing, junk, other schema, other source digest, no digest, incomplete, bad status | `unavailable`, no listing query runs, limitation in payload | 8/8 pass; source digest added by this change |
| A6 | Changed listing, older plus newer row, unknown change time, >10% changed, >10% unknown times | Left out and counted; stale above 10% | Pass; unknown times now count toward staleness |
| A7 | Paging with `more`, last page, no match on page 1 and page 4 | Scoped counts, pages in order, no unscoped count | Pass |
| A8 | `more` after a refusal; accepting the offer | Refused page 1 is shown again, never skipped; clear keeps the area | Pass after fix |
| A9 | Refine, empty list, replace, clear, reset | Features kept until cleared or replaced | Pass |
| A10 | `save_search` with features | Clarification; nothing saved | Pass |
| A11 | Search without features | Identical SQL and payload; store never opened; identical with or without a store | Pass |
| A12 | Reply text | Features, snapshot date, left-out count, limitation last; plain feature words | Pass |

Defects found and fixed in this pass, each with a regression test:
- **`more` after a refused page 1 skipped to page 2** once the store came back, so the user
  never saw page 1. The session now records a refused search (`last_search_refused`), and
  `more` reruns that page.
- **The store was not tied to the approved source at load time.** A store from an older
  builder (no digest) or another source opened normally. `open_store` now requires the
  `results_digest` meta value to equal the frozen constant (`source_mismatch` otherwise).
- **The 10% staleness test ignored rows with no change time,** although the per-listing
  test counts them as changed. Both now treat a missing time as changed.

**Bounded real-data checks (read-only, local listings snapshot, real store).** The same tool
path for each of the 20 facets in Los Angeles returned only listings whose stored status
is `present`, with the snapshot date and limitation in every reply. Five combinations
(Pasadena solar 14 of 316; Pasadena solar and pool with 3+ beds 3 of 178; Irvine three HOA
amenities under $2M 21 of 507; San Diego water view condominium with HOA up to $800 19 of
1,859; five features in Los Angeles 0 of 4,015) were all applied with every returned
listing present for every requested feature. Paging, refinement (160 to 98), clearing
(1,381 without features), a no-match page 2 (0), the unconfigured refusal, and an identical
plain payload with and without a store all behaved as specified. The corrections change
7,394 listing-feature matches against the uncorrected results (1,043 gained, 6,351
dropped; the most dropped are hardwood 1,488, patio 1,146, open plan 909, gated community
810 and ADU 689). The snapshot has no rows changed after the watermark or without a change
time, so freshness on real data is only exercised by the synthetic tests; 321 active
listing IDs have no extraction result and stay unknown.

**Performance (local MySQL, median of 5-7 runs).** Plans: the scoped search, count and
left-out count use the city index and an anti-join through the listing-ID index (no table
scan). The freshness count is a full scan of `rets_property` (no index covers the status
or change time; indexes are out of scope): about 120 ms. Before this change a feature
search cost 197-353 ms against 13-31 ms without features: freshness 124 ms, store
validation 15-22 ms, re-checking the bound keys for each statement about 20 ms, and the
search, count and left-out count 20-55 ms each (larger for broad scopes; garage binds
25,155 keys). Now the freshness counts are reused for 60 seconds per snapshot (the
per-listing change test still runs in every query), store validation is reused for an
identical file (inode, size, change times and SQLite's change counter; never for a file
modified in the last two seconds), and the keys are checked once per scope. An
independent review found that timestamps alone could miss an in-place edit on coarse
Linux file clocks; the change counter and recency guard close that, with a test.
Warm feature searches take 32-168 ms (Irvine three features 32, Pasadena solar 72,
Los Angeles solar 107, Los Angeles garage 160); the first feature search in a window is
about 240 ms. Searches without features are unchanged (13-32 ms). Store key lookups take
2-10 ms. The remaining cost is the full-scan freshness count once a minute and the
scoped queries on very broad features; neither needs a change for this data size.

**Semantic spot check (bounded, not a dataset-wide estimate).** 32 listings, chosen with a
fixed seed: 10 ordinary positives returned by real searches, 6 borderline present cases
(unspecified-time or policy-heavy wording), 6 hypothetical cases (3 planned, 3 uncertain),
and 10 cases where a correction changed eligibility (5 dropped, 5 gained). Each was read
against its remark. Search behaviour matched the stored status in 32/32 (21 returned, 11
not). Judgments: 13 supported, 11 correctly excluded, 7 supported but borderline (a
rhetorical "I wish I could find" listing, a duplex second unit offered as an ADU, a
subterranean parking structure as a garage, river views, flex space offered as a bonus
room, a kitchen flowing into the living area), and 1 questionable (a "new transit hub"
mentioned among redevelopment projects, which may be planned). Every applied reply kept
the snapshot date and the limitation. No systematic problem was found; listing-level
evidence stays in the gitignored `data/enrichment/wo021-spot-check-*.jsonl`.

## Increment 2: card badges (built 2026-11-02, off by default, in review)

Owner-authorized for development and offline testing only, not activation. With
`IDX_FEATURE_BADGES=1`, `search_listings` labels each result card with up to three
eligible features whose effective status is `present`, from the same validated store and
under the same rules as feature search: an unavailable or stale store gives no badges, and
a listing with any row changed after the snapshot (or with no change time) or never
extracted gets none (one bounded query checks the page's keys). Badges never change what is
matched, counted or stored, and any badge failure leaves the search as it was. Each badged
card gains one line, `From description: …`, after the pool/view line; every other card
fact, its order and the card count are unchanged, and only the search reply passes badges
(alert, email, similar-listing and recommendation cards are untouched). The reply names
the snapshot date and shows the limitation once. With the setting unset or anything other
than `1`, the store is not opened for badges and every payload and reply is byte-for-byte
as before. `tests/test_card_badges.py` covers rendering, every status for every facet, the
cap and order, changed and undated listings, stale and unusable stores, failures, refusals,
later pages, attribution and the unchanged default. A bounded read-only check on the real
store and local listings (setting on in the process environment only) badged 47-49 of 50
cards in Los Angeles, Pasadena and Irvine page 2 (124-135 badges, so the cap of three
usually applies); every badge was a `present` status, the listings were identical with
badges on and off, and the warm overhead was 2-3 ms per search.

**Decisions for the owner before activation.** The defaults below are placeholders chosen
to be neutral, not approved choices:
- the cap of three badges per card, and whether to say "+N more" when it cuts;
- the order: requested features first, then alphabetical (an alternative is a fixed
  priority list, for example ADU, solar and water view first);
- whether `near_grocery_mentioned` and `near_transit_mentioned`, which describe the area
  rather than the home, should appear as badges at all;
- the card wording `From description:` and the reply note.
