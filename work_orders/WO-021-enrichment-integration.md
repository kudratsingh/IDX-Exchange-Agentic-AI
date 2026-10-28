# WO-021: Enrichment integration — draft for owner review

**Status: draft. Do not implement or activate until the owner reviews this work
order.** The full extraction job is separate and has not been run.

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
