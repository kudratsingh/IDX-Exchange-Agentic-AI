# WO-018 extraction scoring contract v1

Frozen before real-data scoring. The only gold is the owner-reviewed
`data/enrichment/labels.json`; the Claude-generated draft is never a gold source.
The owner reviewed all 250 cases. The draft model (Opus) and proposed extractor
(Sonnet) are from the same model family; shared errors may inflate apparent
agreement. Report this limitation alongside results.

## Scope and match

The 100 dev cases support iteration. The 150 test cases are held out until the
extractor, prompt, schema and scoring implementation are frozen. Run the test
once after that freeze; do not tune or rerun against it. Each case must have a
gold label record and prediction record, including explicit empty lists.

Structured annotations comprise all allowed `remarks-facets-v1` group/value
pairs and the four numeric fields: bedrooms, bathrooms, living area in square
feet and asking price in dollars. Exclude any annotation outside that vocabulary;
invalid schema, mismatched datasets, missing cases, duplicate annotations or
invalid source offsets fail the run rather than being silently dropped.

A correct categorical prediction matches in the same case on group, value,
polarity, temporality, and exact zero-based half-open Unicode source span. A
correct numeric prediction matches field, numeric value and exact source span.
Quotes must equal the redacted source substring. A one-to-one exact match is a
true positive; all other valid predictions are false positives and all unmatched
gold annotations are false negatives. No relaxed-span matching or semantic
normalization is used for the gate. Thus correct facts with differently chosen
spans count as errors; report this limitation.

## Metrics and gate

For each field and each allowed facet value, report gold support, prediction
count, matches, precision, recall and F1. Also report categorical metrics by
polarity, including negated and uncertain; the same exact matching applies. Report
counts for all unsupported classes. Precision is undefined when predictions are
zero; recall is undefined when gold support is zero; F1 is undefined when both
are zero. Never replace undefined with 0 or 1.

The primary **structured micro F1** pools true positives, false positives and
false negatives over all eight categorical groups and all four numeric fields,
across all cases. Unsupported classes with false positives still contribute to
micro false positives. F1 is `2 TP / (2 TP + FP + FN)`, undefined with zero
denominator. As diagnostics, report numeric and categorical micro F1 separately,
and macro F1 over individual facet values and numeric fields with positive gold
support; exclude unsupported classes from macro and state the included class count.
The macro is not the release gate.

Search integration requires structured micro F1 **at least 0.85 on all 150 held-out
cases** after the single frozen test run. An undefined result, incomplete data,
invalid predictions or a failed run cannot pass the gate. This is a gate for
proceeding to integration review, not proof of safety or uniform quality across
rare facets. Report per-class and polarity limitations regardless of the result.

Token usage is actual provider-reported input and output tokens, summed across
completed requests and divided by 100 for the complete dev run; missing usage or
incomplete runs are reported as unavailable, not estimated. Cost is taken only
from the provider console. Only aggregate counts, metrics and token totals may
leave the private directory. No remark, key, annotation quote or prediction is
logged, committed, put in a PR or included in chat.

The dev report includes up to ten facet or numeric-field buckets with the most
unmatched spans, ordered by false-positive plus false-negative counts (ties by
bucket name). It reports the bucket and those counts only, never individual case
identifiers, quotes or remark text. Completed-run usage includes requests made.

Recovery after the first dev attempt: the extractor requests a strict
schema-constrained client-tool input, and computes source offsets locally from
one unambiguous exact quote, falling back to whitespace-normalized matching.
An unfound or ambiguous quote, malformed annotation, or missing tool call is a
miss with a sanitized field/rule diagnostic; processing continues. The original
frozen scoring still compares exact source spans. Invalid-response bytes are
kept only in owner-only `data/enrichment/debug/`; diagnostics never include text
or listing keys. A provider/auth failure or inability to persist private results
stops the run. Sonnet 5.5 uses automatic tool selection: strict mode constrains
the tool input when called but does not guarantee a call.
The system prompt instructs the model to call the extraction tool exactly once,
and run results report the number of responses with no extraction tool call.

## Owner-approved gate amendment: polarity-aware overlap and exact values

Frozen before any held-out scoring: categorical annotations are grouped per
case, facet and polarity. A categorical group is found if any prediction of the
same case, facet and polarity overlaps any gold span by at least one character.
Temporality is ignored. Multiple mentions of the same case/facet/polarity count
once. An unmatched group contributes a false positive, false negative, or both.
Affirmed, negated and uncertain remain distinct; uncertain stays in the gate.

Numeric annotations are grouped by case, field and distinct value. A prediction
matches only the identical gold value in that case and field, regardless of span.
A wrong additional value is a false positive; duplicate identical values count once. The structured micro F1 pools those categorical and numeric case-level
counts; the release threshold is 85% on all 150 held-out cases after one frozen
test run. Exact-span and polarity metrics remain separate diagnostics.
This owner-approved amendment supersedes earlier conflicting gate language in
this document. No held-out data was used to select or tune it.
