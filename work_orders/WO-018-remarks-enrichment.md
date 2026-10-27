# WO-018 — Public-remarks enrichment

User direction recorded 2026-10-25: begin the combined plans in the revised order.
Remarks enrichment comes before the remaining WO-017 executor work. WO-017 Phase A
is retained. Activate this implementation only after the current WO-015 closeout
lands; it does not require waiting for human-dependent live acceptance.

## Goal

Create a versioned, inspectable property-fact enrichment path from public remarks,
so later search, cards, reports and alerts can use supported facts rather than
uncontrolled text guesses. Missing/negated/uncertain statements cannot become
positive hard constraints. This WO does not promise a fully labeled extraction
model, a production accuracy number or new search filters from a schema alone.

## Phase A: key-free foundation

Own: src/idx_agent/enrichment/__init__.py, vocabulary.py, normalize.py;
src/idx_agent/domain/enrichment.py (boundary models stay in domain per repo rules);
tests/test_enrichment_vocabulary.py and test_enrichment_normalize.py; this WO,
docs/ENRICHMENT_DESIGN.md, the enrichment section in docs/CONTRACTS.md, a README
navigation link and an append-only evidence entry. Use standard library and existing Pydantic only.
Implement eight fixed facet groups and bounded versioned normalization, with
invented adversarial examples. Do not load real remarks, infer contact facts,
re-embed, call providers, change the live index, add SQL columns, register a tool
or modify hard search filters. Normalized text is still untrusted text.

Abbreviation expansion must preserve negation, uncertainty, punctuation and numbers.
Only known unambiguous contexts expand. Record whether text changed and the
normalizer version; retain original input outside public fixtures when an approved
future ingestion job runs. Bounded input fails closed rather than silently truncates.
The normalizer is not a contact redactor or a semantic extractor.

## Later phases and dependencies

B: define annotation rules, provenance spans, polarity/status, dev/test split and
reviewed synthetic cases. Human labeling of a permissioned real sample is required
before reporting real extraction quality. Check claims against each feed's field
definitions; do not compare bathroom counts between the tables.
C: extraction, deal-signal candidates, summaries and discrepancy checks, with
per-facet/negation/uncertainty metrics and error review. Choose deterministic/model
paths from evidence; model calls require a separate command-bound budget.
D: explicit schema/SQL/index/card/report integration for accepted facets, then a
versioned rebuild with preserved previous index and live acceptance. No deployment
before query/index normalization compatibility is demonstrated.

## Acceptance for Phase A

- All eight groups and allowed values have unique identifiers; unknown facets fail.
- Pure bounded normalization is deterministic and idempotent, preserves numbers and
  negation, resists partial-word/ambiguous expansions, and carries a stable version.
- Tests cover empty/oversize/non-string input, mixed casing, punctuation and examples
  outside the intended domain. No fabricated precision/recall or live-data claim.
- Existing retrieval/query behavior is unchanged; focused tests, lint, content gates
  and CI pass. Self-review the diff and update this Status with measured evidence.

## Stop conditions

New dependency/service, a protected enforcement edit, private source access, paid
extraction/re-embedding, unresolved labels, unsupported field semantics, or a change
to the existing hard-filter contract. Record the decision needed, not a fallback
that silently weakens evidence or privacy rules.

## Status

The user paused capabilities on 2026-10-25, then directed resumption after the
WO-019 model-side change merged in PR #102. Baseline items that remain open are
not implied complete. The merged enrichment foundation remains unused at runtime.

2026-10-25: Phase A implemented on its isolated branch after WO-015 closeout
merged. Boundary models live in domain/ to follow the existing repository convention.
The first 30 foundation/length tests passed (0.57 s); a wider run covering the new
boundary and existing index/query/RAG behavior passed 186 tests (1.37 s). Ruff
passed after formatting. CI/integration is still required before this phase lands.
No real remarks, provider, SQL query or embedding job was used; no runtime is wired.
The overall WO remains open through labeling, extraction, integration and acceptance.
Next: an approved annotation specification and dev/test sample, then extraction.
No accuracy or new user-facing filter is claimed from this preparation alone.

2026-10-26: Phase B draft started with a proposed annotation specification and
26 wholly invented cases split evenly into development and holdout sets. The
examples cover all eight facet groups, independent polarity and time, original
Unicode offsets, negation, ambiguity and contradictions. Thirty-two focused tests
passed with no provider, database or real remarks. The specification and real-data
sampling procedure still require human review; no extraction accuracy is claimed.

Independent review of the synthetic examples found one person-versus-style
ambiguity and one proposal/current-negation ambiguity. The style example now names
a home, and the proposed ADU has separate planned affirmation and current
negation with explicit guidance. The expanded annotation/foundation/fixture
suite passed 53 tests; this validates the fixtures, not an extractor.

2026-10-27: the draft now includes a bounded synthetic annotation model and
pure exact-match counts, with per-facet and polarity breakdowns. A source marker
is self-declared and is not provenance enforcement. The helpers do not extract
facts or access a database, provider, session or runtime index. Independent
review found no concrete defects; 58 focused tests passed. Real-data labels,
reviewed sampling, and extraction-quality evidence remain open.

The expanded annotation, index, query and retrieval regression passed 214 tests
with MYSQL_HOST empty. These are synthetic/model-free checks; no live data, feed
sampling, model call or runtime integration was involved.

Synthetic scoring now also aggregates one split across complete matching case
sets, preserving per-facet and polarity counts. It rejects missing, extra,
duplicate and cross-split cases. Independent review found no concrete defect;
the expanded synthetic/index/query/retrieval suite passed 216 tests. This does
not authorize or measure real-data extraction.

A reviewable pilot proposal now lists the source, access, in-place review,
splitting, labeling and low-sample decisions needed before real remarks can be
used. It performs no sampling and grants no access or export authority.

A synthetic-only split planner demonstrates a 50-input-row cap, grouping before
splitting, reproducible seed ordering, and a maximum of 30 invented groups.
Independent review found no concrete defect; the expanded regression passed 220
tests. It cannot select real listings or certify source provenance.

2026-10-27: The human approved the annotation specification with numeric-total
rules and eight-group examples. The private labeling plan is 250 seeded,
subtype-stratified remarks (100 dev, 150 test), owner-labeled locally. Only
aggregate scores and counts leave data/enrichment/. Search integration requires
at least 85% F1 on structured facets on the held-out test set. Paid extraction
requires a separate token; no real-data scoring has occurred.

A local-only labeling viewer prototype is under development. It reads an owner-
selected sample JSON and writes a separately selected labels JSON, with no server,
model or network connection. It validates original Unicode code-point spans and
basic facet/numeric fields. The browser cannot prove the chosen file paths are in
`data/enrichment/`; the owner must choose the private directory. Synthetic tests
are not a real-data sample or evidence of labeling quality.

The viewer draft now has local styling and retains selected source spans while
fields are filled; changes require an explicit file save. A local headless Chrome
load and synthetic interaction smoke test passed. A pure aggregate scorer accepts
the viewer's annotation shape, rejects mismatched/incomplete datasets and returns
per-facet and numeric counts without source text. It has not been run on real
remarks. Exact span matching is a strict metric, and the meaning and aggregation
of the 85% structured-facet gate remain to be frozen before the held-out test.

The draft aggregate-only runner reads fixed private filenames and verifies 100
dev or 150 test cases and complete labels; tests use invented temporary data.
It produces no prediction file, sends nothing to a model and does not choose the
held-out gate. The viewer and runner still need interactive acceptance.

A pure, seeded subtype allocation helper now demonstrates the requested 100/150
split on invented group identifiers, with group deduplication and deterministic
largest-remainder allocation. It performs no database or file access. Access to
an eligible candidate population and compliant creation of the local 250-remark
sample remain unresolved under the existing query and bulk-export invariants.

A headless Chrome synthetic interaction exercised selecting Unicode text, adding
an annotation, navigating and saving via a stubbed picker. The synthetic desktop
layout was visually inspected. A real operating-system save dialog and private
sample have not been exercised. Scoring now includes unsupported allowed facets
with undefined precision/recall/F1 instead of silently omitting them.

The owner specified `rets_property.L_Remarks`, the existing SELECT-only embedding
reader in pages of at most 50, a 200-character minimum, and a private 250-row
JSONL containing only key, subtype and redacted remark. A separate private split
manifest supports the approved 100/150 labeling split. The JSONL viewer and
aggregate scorer passed invented-data checks; the live sample is not asserted
complete until the reader reports its count and fixed seed.

2026-10-27: the owner-authorized local database sample completed with 250 remarks,
fixed seed 20261027 and a 100/150 split. The redacted JSONL and split manifest
are private and owner-readable only. Structural checks passed; keys and remarks
were not logged. Human labeling and model evaluation have not yet occurred.
