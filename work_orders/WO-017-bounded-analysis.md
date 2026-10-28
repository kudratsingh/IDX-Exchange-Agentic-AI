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

## Phase B and C steps (refined 2026-10-27)

One small PR each, in order; each runs against the synthetic fixture in CI only.

1. Code-owned projection: a fixed, allowlisted, parameterized SQL reader that reuses
   the WO-008 cleaning rules, returns at most 50 sales in a stated order under a
   statement deadline, and feeds `make_analysis_sample`. Fixture integration tests.
2. Worker output protocol and trusted figure checks: strict bounded parsing of the
   worker's JSON; host code recomputes every supported headline figure from the same
   rows and labels anything it cannot recompute as unverified.
3. Typed chart specification with trusted-side validation (bounded points, units,
   dates, sample-size caption). No renderer dependency yet.
4. The worker image (`docker/analysis-worker/`: base pinned by digest, hashed
   requirements), the container executor (digest-pinned image only, read-only
   `/input` sample directory, fixed flags, 30 s wall clock, output caps, removal on
   every path, no host fallback), the analysis bootstrap, and real hostile-code
   isolation and deadline tests (network, host files, environment, daemon socket,
   process growth, memory, endless loops, output floods, scratch writes, cleanup on
   every path, parallel isolation, missing image or engine).
5. The fixed in-worker renderer: a render run turns trusted `ChartData` into one
   PNG with matplotlib (Agg); the host checks only the PNG signature, dimensions
   and size. The `analysis` extra records the same matplotlib pin.
6. Service wiring: projection, analysis run, figure checks, chart data, render run,
   and an MCP text-plus-image result, tested offline. Registration (Phase C) waits
   for the human's live proof of the image relay.

Owned files for these steps: `src/idx_agent/db/analysis.py`,
`src/idx_agent/analysis/`, `docker/analysis-worker/`, the `analysis` extra in
`pyproject.toml`, matching `tests/test_*analysis*.py`, an appended fixture
group in `tests/fixtures/make_synthetic.py` and the regenerated `synthetic.sql` if the
existing rows cannot cover a case, `docs/adrs/0013-analysis-worker-container.md`,
the WO-017 sections of `docs/CONTRACTS.md` and `docs/ANALYSIS_DESIGN.md`, and
append-only notes in `docs/STATUS.md` and `docs/EVIDENCE_LOG.md`.

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

2026-10-28: steps 1-3 merged (PRs #108, #109, #110); the decision record and the CI
build step merged in PR #106. Step 4 (worker image, container executor, real
isolation tests) is in review on wo-017-executor. Review found the deadline lived
only in the host; the container's PID 1 is now an unkillable timer (ADR-0013
amendment). The image needs a TLS CA secret only on a build machine behind an
inspecting proxy; CI and the owner's Mac build without it. Human step after merge:
build the image on the Mac, set IDX_ANALYSIS_IMAGE to its sha256 ID (see
docker/analysis-worker/README.md).

2026-10-28: the human accepted ADR-0013. Docker is the worker: pinned image
digest, no network, read-only root filesystem, CPU and memory limits, a 30-second
wall clock and an output cap; the worker gets the bounded sample file only, never a
database connection. matplotlib is approved as the optional `analysis` extra and
charts render inside the worker to PNG; the trusted side reads only the image bytes
and the figure-check JSON. Steps 1-3 are in review (step 1 merged in PR #108). Steps
4-6 start once this record is on main.

The `gates` token is granted in principle and is minted by the human for this one
change to `.github/workflows/ci.yml`, applied only after the token exists. The step
is skipped while the Dockerfile is absent, so it is safe to land before step 4:

```diff
@@ -69,6 +69,12 @@
         run: |
           mysql -h 127.0.0.1 -uroot -pci-only-root idx_fixture < tests/fixtures/synthetic.sql
           mysql -h 127.0.0.1 -uroot -pci-only-root -e "CREATE USER 'idx_reader'@'%' IDENTIFIED BY 'ci-only-reader'; GRANT SELECT ON idx_fixture.* TO 'idx_reader'@'%';"
+      - name: Build the analysis worker image (WO-017, ADR-0013)
+        if: hashFiles('docker/analysis-worker/Dockerfile') != ''
+        run: |
+          docker build --tag idx-analysis-worker:ci docker/analysis-worker
+          echo "IDX_ANALYSIS_IMAGE=$(docker image inspect --format '{{.Id}}' idx-analysis-worker:ci)" >> "$GITHUB_ENV"
+          echo "IDX_REQUIRE_CONTAINER=1" >> "$GITHUB_ENV"
       - name: Unit tests (no database)
         env:
           MYSQL_HOST: ""
```

Human steps now: mint the `gates` token for exactly this diff and say so; later,
build the worker image on the owner machine and pin its ID, the live image-relay
proof, and any paid chat acceptance, each under its own grant.

2026-10-27: resumable. The pause below was conditional on WO-019 accepting the base
assistant; WO-019 merged and the user assigned Phase 2 (this WO) on 2026-10-27, with
WO-018 owned separately. Phase B steps 1-3 are key-free and container-free and start
now. Steps 4-6 wait for the human's answers on ADR-0013 (Docker worker, matplotlib
renderer, CI image-pull step). Nothing is registered or reachable from chat.

Human steps as of 2026-10-27 (superseded above): decide ADR-0013; if accepted, pull
the pinned image and grant a `gates` token for the CI step.

Earlier record, kept as written: paused by the user on 2026-10-25 until WO-019
accepts the base assistant on the new provider. Merged foundation code remains
unused by live behavior. Do not start the remaining capability phases while
baseline acceptance is open.

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
