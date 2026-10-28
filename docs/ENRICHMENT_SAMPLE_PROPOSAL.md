# Remarks annotation: approved private labeling plan

The owner approved a sample of 250 remarks: 100 development and 150 held-out
test cases, selected with a fixed seed and stratified by property subtype. Group
versions of the same listing in one split and record allocation, seed and source
snapshot in the private manifest. Never silently relax the 250 total or the
100/150 split; report insufficient eligible groups instead. A sampling method
uses the existing embedding reader in pages of at most 50. The owner identified
`rets_property.L_Remarks` as the source on the same basis as the embedding build
and directed a private 250-record sample only. No general data export is implied.

Real remarks, identifiers, manifests and human labels stay under the local
`data/enrichment/` directory. Only aggregate scores and counts may leave that
directory. The owner labels the cases in a local-only page that reads and writes
private files, with no server or model. The JSONL viewer, private split manifest and sampler are in draft review. The owner controls access to the machine and files; a browser file
picker does not itself enforce that a selected file is inside the directory.
No real sample has been selected and no private labels have been written.

2026-10-27: the owner approved Claude Code (Opus) drafting suggested labels from
the 250 remarks, which sends that remark text to Anthropic for this purpose only.
Drafts are kept in a private file apart from the labels file; the owner reviews
every case before it counts as a label. The extractor under evaluation uses a
different Claude model (Sonnet). This approval does not cover extraction runs.

Before paid extraction, resolve the private-data boundary: sending remarks to an
external model provider would move text outside `data/enrichment/`, while the
approved workflow permits only aggregate scores and counts to leave it. A local
model would keep the data on the machine but still needs a separate exact-command
token under the requested procedure. Run the chosen prototype on the 100 labeled
development remarks and report tokens per remark and per-facet precision and recall. Freeze the extraction and scoring rules before the held-out
test. Feeding search requires at least 85% F1 on structured facets on the 150
test remarks; define the aggregation and handling of unsupported facets before
that test. The sample is not automatically representative of all MLS remarks.
Keep source text and labels out of logs, public artifacts and model reports.

The approved redaction reuses the embedding preparation function. It masks links
and certain email, phone and secret patterns; it is not a guarantee that every
person name, contact detail or sensitive statement is removed. Review is local,
and the redacted remarks and identifiers remain private. Its whitespace
normalization means annotation offsets refer to the redacted sample, not the
original database text.
