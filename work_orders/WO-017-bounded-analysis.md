# WO-017 — Bounded database analysis

Authorized 2026-10-25: finish the existing handoff work and begin the capability
roadmap, starting with database analysis. One implementation assignment is active.
WO-015's protected hook fix remains a separately granted closeout task.

## Goal and phases

Allow a question outside the fixed market metrics to run a bounded analysis over
code-selected sales and eventually return a chart. Models supply Python, never SQL,
column lists, database credentials, executable paths or container flags.

Phase A (active): implement and test the numeric sample boundary; write the sandbox
design and roadmap. No new dependency, process execution, tool registration, runtime
installation or paid call. This phase is useful preparation, not a live capability.
Phase B requires the human's container-infrastructure decision before implementation.
It adds the isolated executor, bounded output protocol, deterministic chart rendering,
fixture integration and hostile-code tests. Phase C registers the tool only after
those isolation tests pass and the chart transport has been verified. Live model
acceptance needs its own paid grant. Do not mark the whole WO done after Phase A.

## Owns (Phase A)

- src/idx_agent/domain/analysis.py and tests/test_analysis_sample.py
- this work order; docs/ANALYSIS_DESIGN.md and docs/CAPABILITY_ROADMAP.md
- docs/CONTRACTS.md boundary section; roadmap block in docs/TIMELINE.md;
  assignment pointers in docs/STATUS.md and CLAUDE.md
- an append-only evidence entry

Do not touch guards, guard tests, CI, runtime/provider configuration, private data,
email approval, scheduling or dependencies. No new service is adopted by this phase.

## Boundary contract

At most 50 already-fetched SoldComp records may enter the adapter. Refuse an over-cap
batch, duplicate keys, mismatched place/type, dates outside the requested window,
future dates relative to either snapshot, invalid close/list prices and reverse
window provenance. Use the existing single-family default. The worker gets numeric
fields only: close/list/original-list prices, usable area and stored DOM. It receives
no keys, addresses, coordinates, remarks, contacts or DB access. Nulls remain null;
area under the existing floor is unavailable. Sample provenance includes the exact
place, subtype, window, as-of dates and an explicit bounded-sample caveat. Never claim
this is a representative sample or all sales in an area.

Original versus final list price is a snapshot difference. It cannot establish the
number/timing of price reductions or a causal effect on selling time. Do not describe
an analysis as a complete city-level market statistic or an appraisal.

## Acceptance

Run focused sample-boundary tests, the existing market/domain tests, lint/format,
and all repository content hooks; open a PR and wait for green CI. Preserve historical
acceptance separately. No real rows or model-generated output in fixtures.

## Status

Phase A merged in PR #85 as 1eb84d8. Its final PR CI run 40222297444 passed 2,995
offline tests (60 skipped), 59 fixture integration tests (one skipped), and 155
model-free eval cases. The user's later combined roadmap puts WO-018 enrichment
before the remaining sandbox work. No executor is installed; container adoption
and later phases are still pending. The local/pre-integration record follows.

2026-10-25: Phase A implemented locally; PR/CI acceptance pending. Container-infrastructure decision requested; no
sandbox is installed or exposed. Existing closeout still requires a human gates
grant, provider selection, paid acceptance, operator email and final demo evidence.

Local validation: 157 focused analysis/market tests passed in 0.58 s and 373 shared
domain tests passed in 0.87 s. Ruff lint passed after formatting. The first test
invocation named a nonexistent test_models.py, ran no tests and was corrected to
test_domain_models.py. No database, execution engine or provider was invoked.

All commit/content hooks passed on the scoped files before PR creation.
