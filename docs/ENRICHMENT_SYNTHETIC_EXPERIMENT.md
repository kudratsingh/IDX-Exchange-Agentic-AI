# Synthetic remarks extraction experiment

This is a narrow, key-free experiment built on the proposed WO-018 annotation
contract. It is not registered as a tool, connected to search, or authorized for
real remarks. A `synthetic` source marker is self-declared and cannot prove input
provenance. The current public development cases are visible to the developer and
are not a blinded or representative benchmark.

## Scope

`extract_synthetic` reads only the supplied original synthetic case in memory and
returns candidate spans against that same original text. It recognizes a few
explicit present-tense property features, a narrowly worded architectural style,
shared facilities and one grocery-proximity mention. It recognizes a few fully
bounded negated, uncertain, planned and historical statements alongside current
claims. Coverage remains deliberately low; it
does not resolve those cases generally.

Outside those fully bounded templates, certain cue words, question marks and
quotation marks cause whole-input abstention, including when a later clause
qualifies an earlier claim. The cue list is finite, can miss paraphrases and can
suppress valid claims. It is not a
privacy filter, instruction-injection defense, or guarantee against false
positives. The feature match requires narrow subject and phrase boundaries.
The implementation returns at most 100 candidates, fails on excess, never logs
text, and performs no file, database, index, session, network or provider access.
Overlapping annotations and original Unicode offsets remain validated by the
synthetic contract.

## Reproduce the limited development check

From this worktree with its normal Python environment:

```bash
python scripts/eval_synthetic_enrichment.py
```

The script accepts no arguments, reads only the committed invented `dev.json`,
and prints aggregate and per-facet/polarity counts. It does not read the synthetic
test split. At this checkpoint it produced 12 exact matches from 12 emitted
candidates against 18 labeled development mentions, across 13 cases. The rules
were developed with these examples, so these counts describe development only and
are not estimates of held-out or real-world quality. A few negated and uncertain
labels are covered by fully bounded templates; many phrases remain unsupported. Zero denominators are reported as unavailable.

Before any real-data extraction, the annotation specification and permitted source
need human review, and the pilot workflow in ENRICHMENT_SAMPLE_PROPOSAL.md needs
separate approval. Production use would require a real provenance boundary,
negation/uncertainty and temporal evaluations, independent held-out labels,
error review, and a separate decision on filters and index compatibility.

## Offset alignment experiment

`normalize_with_alignment` applies the existing bounded normalizer and builds a
conservative mapping from normalized characters back to original source intervals.
Every character of an expansion maps to the complete original match; requesting
only part of an expansion fails rather than inventing a citation. Captured-number
replacements, repeated abbreviations and Unicode prefixes have synthetic tests.
The helper verifies its normalized text matches the existing normalizer and does
not change that normalizer or the live index. `original_span` currently scans the
bounded mapping for each request, so bulk performance needs measurement before
any integration. The synthetic extractor uses this helper for one explicit washer/dryer claim,
including `W/D`; its returned quote is the original source span. It does not
infer central air from a generic `A/C` mention.
