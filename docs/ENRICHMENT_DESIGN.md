# Remarks enrichment: first boundary

WO-018 Phase A is a library foundation, not a new chat tool. No active search,
index, hard filter, model prompt or listing card imports it. Normalized remarks
remain untrusted data, including any instruction-like content in the source.

## Vocabulary

`enrichment/vocabulary.py` publishes `remarks-facets-v1`, an immutable map of eight
groups to immutable candidate identifiers: property type, architectural style,
rooms/layout, interior/systems, exterior/lot, shared amenities, location/views and
condition/sale mentions. `domain/enrichment.py` validates group/value pairs and
refuses unknown pairs, extra fields or a `verified` assertion. A vocabulary
reference is not a supported fact. No protected-class, contact, office or owner
identity category is present. Proximity mentions do not prove measured distance.

A later evidence schema must bind every candidate to a source version and span,
with explicit affirmation/negation/uncertainty/planned/historical status. It must
not create a positive filter from a denied, speculative or missing statement.
Current structured fields remain authoritative for current hard filters. Remarks
versus column discrepancies require review; neither value is silently overwritten.

## Normalization

`normalize_remarks()` returns typed `NormalizedRemarks` with the resulting text,
`remarks-normalizer-v1` and ordered identifiers of rules that changed text. It
expands slash-form A/C and W/D; the BR/BA label and numeric BR/BA suffixes; SS in
an appliances phrase; the LVP token; and HWD followed by floor/floors/flooring.
Ambiguous bare AC, SS and HWD are left alone. It does not infer home features,
remove negation, convert units, change numbers or rewrite unknown terms.

Inputs must be text and at most 16,000 characters; NUL is refused. The output is
capped at 128,000 characters. No truncation, filesystem/network/provider operation,
contact-redaction claim or source logging is part of this function. Empty text
is valid. Repeated normalization keeps the same text. Returned objects are frozen;
the rule list is metadata, not a confidence score or a source-evidence span.

## Compatibility and later acceptance

No runtime is wired in this phase. Before a real ingestion or index change, label
and hold out an approved sample, evaluate errors by facet/entity/polarity, and
settle offset semantics. Expansion changes character positions: normalized offsets
cannot be presented as original-source spans. Preserve the original under the
approved private data policy; do not put examples or extracted rows in GitHub.

Version the normalizer and query/document index together; changing query text alone
would make an old embedding pipeline inconsistent. A rebuild needs a command-bound
budget and a separate destination so earlier artifacts survive. Existing retrieval
and hard filters must pass regressions before accepted enrichment is integrated.
No dataset-wide accuracy, relevance improvement or public release is claimed by
passing the invented examples in Phase A.
