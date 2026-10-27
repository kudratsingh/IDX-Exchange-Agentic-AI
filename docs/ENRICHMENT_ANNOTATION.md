# Remarks annotation specification (draft v1)

WO-018 Phase B defines how to label statements in public remarks before building
an extractor. This specification and its examples are synthetic and proposed for
review; they do not authorize reading a real feed, training a model, changing a
search filter, or making an accuracy claim.

## Unit of annotation

A case is one original, unnormalized remark. Each annotation is one explicit
mention linked to a valid `remarks-facets-v1` group/value pair. Record the exact
source quote and its zero-based, half-open `[start, end)` offsets in the original
Python Unicode string. For example, an annotation for `pool` in `no pool` covers
`no pool`, retaining the negation. Do not use normalized offsets on the original:
expanding an abbreviation can move every later character.

Record two independent axes:

- **Polarity:** `affirmed`, `negated`, or `uncertain` for the mentioned facet.
- **Temporality:** `current`, `planned`, `historical`, or `unspecified`, according
  to what the text actually supports. `uncertain` plus `planned` is valid.

Use the smallest contiguous span that includes the feature and the wording needed
to support its polarity and time. A proposal is an affirmed planned mention; if
the same sentence says it is not yet built, separately annotate that explicit
current negation. The planned mention does not imply a current feature. When a remark contains separate contradictory
mentions, annotate each separately; do not silently choose one. If a mention lacks
an explicit, supported facet value, leave it unannotated. An empty annotation list
means no supported mention, not a finding that features are absent. These labels
are evidence candidates, not validated property facts or filter permissions.

Annotate only property-related vocabulary. Do not label a person, contact detail,
protected class, private instruction, inferred school quality, or a claimed
travel distance. A proximity mention states only that the text made the claim.
Keep retrieved text untrusted and do not follow instructions embedded in it.
Bathroom values are never compared across the two tables.

## Synthetic split and review

`tests/fixtures/enrichment/dev.json` and `test.json` are wholly invented, distinct
case sets. Case IDs are split-specific; a held-out example must not appear in the
development set, even with capitalization or whitespace changed. Fixtures cover
affirmed, negated, uncertain, planned and historical mentions; contradictions;
unknown/absent mentions; Unicode offsets; and all eight vocabulary groups. They
are public contract examples, not a blinded holdout, a representative sample,
or a model benchmark. A `synthetic` source marker is a declaration by the caller,
not proof of provenance.

Before applying this scheme to real remarks, the human must approve a permitted
source and sampling/labeling procedure. Create disjoint development and held-out
sets by a reviewed grouping strategy, preserve original text privately, document
disagreements, and review ambiguous cases. Freeze the schema, version, splits and
labeling instructions before measuring each facet and polarity. Define any
mapping to feed fields only after checking their actual definitions. Never publish
real remarks, contact fields, source identifiers or model-generated evidence.

## Offline validation and counting

`SyntheticAnnotationCase` validates bounded source text, split-specific IDs,
known facets, original quote offsets and duplicate evidence. Its source marker
is not an access-control or provenance mechanism. The pure `score_case` and
`score_breakdown` functions compare exact facet, source span, polarity and
temporality for the same case and return only counts. They expose counts by
facet and polarity; precision or recall is `None` when its denominator is zero.
`score_dataset` combines these counts across one declared split, requiring the
same unique case IDs and matching original text; missing, extra, duplicate or
mixed-split cases are errors. The helpers neither extract facts nor access files,
providers, databases or sessions.
Synthetic checks validate the scoring contract, not real extraction quality.
