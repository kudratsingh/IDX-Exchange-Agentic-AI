# scripts

Small project helpers kept outside the importable package. The two enforcement folders
are summarized rather than enumerated; their rules live in `RULES.md`.

| Script | Purpose | Database | Paid call | Work order |
| --- | --- | --- | --- | --- |
| `README.md` | Describes the scripts and their operational boundaries. | No | Never | WO-000 |
| `gates/` | Contains the commit and CI enforcement checks; see `RULES.md`. | No | Never | WO-000 |
| `guards/` | Contains the agent-session enforcement hook; see `RULES.md`. | No | Never | WO-000 |
| `comps_spike.py` | Measures the proposed comparable-sales rule using aggregate, read-only queries. | Yes | Never | WO-011 |
| `fixture_lint.py` | Rejects synthetic fixture SQL that could contain unsafe or non-invented content. | No | Never | WO-005 |
| `install.sh` | Renders and installs the local OpenClaw and tracing configuration. | No | Never | WO-001, WO-007 |
| `jaeger-local.sh` | Starts a locally supplied Jaeger collector and trace viewer. | No | Never | WO-007 |
| `market_spike.py` | Measures market-query samples, timings, and aggregation choices with read-only queries. | Yes | Never | WO-008 |
| `market_summaries.py` | Saves selected deterministic market cards for the document-index input. | Yes | Never | WO-012 |
| `migrations/001_dates_and_indexes.sql` | Adds derived date columns and indexes when a human administrator runs it. | Yes | Never | WO-002 |
| `openclaw_merge_config.py` | Merges rendered JSON5 fragments into an existing OpenClaw configuration with a backup. | No | Never | WO-001 |
| `prefix_audit.py` | Counts the fixed routing prompt components without reading their content for output. | No | Never | WO-013 |
| `profile_data.py` | Produces aggregate-only schema notes from the two MLS tables. | Yes | Never | WO-002 |
| `rag_floor_probe.py` | Measures lexical retrieval scores to choose a document-answer floor. | No | Never | WO-012 |
| `rag_spike.py` | Measures document extraction and chunking characteristics without creating an index. | No | Never | WO-012 |
| `semantic_spike.py` | Profiles remarks, measures index sizes, makes judging sheets, and scores their marks. | Yes (profile mode) | Yes — `--judge-sheet` only | WO-010 |
