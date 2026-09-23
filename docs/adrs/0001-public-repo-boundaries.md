# ADR-0001: Public repo boundaries

**Status:** accepted
**Date:** 2026-09-22
**Work order:** WO-000

## Context
The internship requires each intern to keep the capstone in their own public GitHub
repository, named `IDX-Exchange-Agentic-AI`, with only code and no CSV or raw-data
uploads. The handbook is marked confidential. The MLS data contains listing-agent contact
details and may contain more sensitive fields. The commit history is graded and permanent.

## Decision
Tracked: code, tests, eval cases (queries and expected values, synthetic fixtures only),
CI configuration, `.env.example`, README, docs (architecture, contracts, safety, evaluation,
decisions, ADRs, schema notes in our own words, reflection, evidence log), work orders.
Never tracked: dumps, CSVs, row exports, embeddings, RAG indexes, logs, `.env`, session
stores, WhatsApp auth, the handbook, the supplied PDFs, planning documents, meeting notes,
the hours log, coordinator correspondence. Those live in `data/`, `context/`, and
`coordination/`, all gitignored from the first commit. Secret scanning runs at commit
(gitleaks) and at push (GitHub push protection). Migrations and synthetic fixtures are
the only `.sql` files allowed.
Rejected: a private repo with a public mirror (forbidden by the rules); docs kept
outside the repo (the README is required in it, and the rule targets data).

## Consequences
Anyone can read the code and history, so the README and evidence log double as the
portfolio. Real rows can never be used as fixtures; CI runs against synthetic tables.
A secret committed once must be rotated and the history rewritten the same day.

## What would reverse this
A written instruction from the coordinator that docs must also stay out of the repo,
in which case `docs/` moves to `coordination/` except the README.
