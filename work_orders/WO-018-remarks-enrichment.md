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

Paused by the user on 2026-10-25 until WO-019 accepts the base assistant on the new
provider. Merged foundation code remains unused by live behavior. Do not start the
remaining capability phases while baseline acceptance is open.

2026-10-25: Phase A implemented on its isolated branch after WO-015 closeout
merged. Boundary models live in domain/ to follow the existing repository convention.
The first 30 foundation/length tests passed (0.57 s); a wider run covering the new
boundary and existing index/query/RAG behavior passed 186 tests (1.37 s). Ruff
passed after formatting. CI/integration is still required before this phase lands.
No real remarks, provider, SQL query or embedding job was used; no runtime is wired.
The overall WO remains open through labeling, extraction, integration and acceptance.
Next: an approved annotation specification and dev/test sample, then extraction.
No accuracy or new user-facing filter is claimed from this preparation alone.
