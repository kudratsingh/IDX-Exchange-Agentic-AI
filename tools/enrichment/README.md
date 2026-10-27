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
