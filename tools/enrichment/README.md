# Private labeling viewer

Open `label.html` directly from disk in a browser that supports the File System
Access API on local files. There is no server, model call, remote dependency or
storage in browser localStorage. Choose the input and output files inside
`data/enrichment/`; the browser's file picker cannot verify the absolute path.
Do not use a browser profile with extensions that can read page contents.

Input is UTF-8 JSON of the form `{"version":1,"dataset_id":"private-sample-v1","cases":[{"id":"dev-001",
"split":"dev","text":"invented example"}]}`. IDs must be unique; splits are
`dev` or `test`. Output is a separate JSON file with `version: 1` and `labels`:
the same `dataset_id`, and one `{id, annotations}` object per reviewed case. A missing ID means unreviewed;
an empty annotations array means reviewed with no explicit facts.

Select the exact text in the displayed remark and use the Add controls to build an
annotation, or edit the JSON array directly. Case edits remain in memory until
you save the file.

Each annotation has Unicode code-point `start` and exclusive `end` and an exact
`quote`. A categorical annotation also has `kind: "facet"`, `group`, `value`,
`polarity` and `temporality`. A numeric annotation has `kind: "numeric"`, `field`
(one of `bedrooms`, `bathrooms`, `living_area_sqft`, `asking_price_usd`) and a
nonnegative numeric `value`. The viewer checks the shape and exact span, but it
does not decide whether a claim is eligible under the annotation rules. It does
not validate split provenance, sample selection, feed rights or quality. Save explicitly before closing, and keep backups privately. Sample
creation, numeric schema and production scoring remain separate work.

The viewer does not submit any text to a model. When it is time to evaluate,
`idx_agent.enrichment.private_scoring.score_private_labels` compares complete
matching split labels in memory and returns aggregate counts and precision,
recall and F1 only. It uses exact original spans as well as facet/polarity/time
or numeric field/value, so alternate spans can score as errors even when the
value is right. Counts for each numeric field and categorical facet are separate;
the `structured_numeric` aggregate is not automatically the release gate until
the gate's scope and aggregation are frozen. Unsupported denominators report
`None`. The operator can run `python scripts/score_enrichment_private.py --split dev`
once the private `sample.json`, `labels.json`, and `predictions-dev.json` are
ready in `data/enrichment/`; `--split test` uses `predictions-test.json`. The
command checks the split size and completeness and prints only aggregate counts
and metrics. It does not select the sample, run extraction, measure tokens or
contact a provider. Freeze the metric before evaluating the held-out split.

A pure `stratified_plan` helper can allocate already supplied, deduplicated
listing groups by subtype with a fixed seed. It selects proportional subtype
counts using largest remainder and divides the selected groups into 100 dev and
150 test. It does not obtain candidates, read a feed, produce a sample file or
make identifiers anonymous. Real selection must still resolve source permission
and the existing query and bulk-export restrictions; do not page around limits.

For a no-data smoke test, open the included `example-sample.json`, select
`fenced yard` in the first case, enter `exterior_lot` and `fenced_yard` as the
group and value, and add it. Save an example label file in a temporary location;
these two invented cases are not the 250-case evaluation dataset.
