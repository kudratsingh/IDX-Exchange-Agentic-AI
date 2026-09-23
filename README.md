# IDX-Exchange-Agentic-AI

Capstone for the IDX Exchange Agentic AI internship (Fall 2026): a multi-agent
real-estate assistant over MLS listing and sold-transaction data, reached through
WhatsApp, with email drafting behind a human approval gate. Runtime: OpenClaw.
Tools: Python.

**Status:** Phase 0, bootstrap. Start at `docs/START_HERE.md`.

> **Before you commit anything, read `RULES.md`.** Three rules, each enforced by a
> pre-commit hook and again by CI: no data, no text from the handbook or the supplied
> PDFs, no secrets or people. Commits are blocked until the gates are installed.

## What it will do
- Search active listings from plain-language requests, with follow-up refinement.
- Answer market questions from closed transactions (median price, days on market,
  sale-to-list ratio, trend), by property subtype.
- Find similar homes semantically and check their prices against comparable sales.
- Answer real-estate and schema questions from indexed reference documents.
- Draft listing alerts and market reports that go out only after a human approves.

## Layout
```
CLAUDE.md            working rules for coding agents
docs/                START_HERE, ARCHITECTURE, CONTRACTS, SAFETY_INVARIANTS, EVALUATION, DECISIONS, adrs/
work_orders/         bounded units of work; exactly one is active
src/idx_agent/       the Python package (domain, db, safety, mcp_server, ...)
skills/              SKILL.md sources, installed into the OpenClaw workspace
scripts/             install, migrations, profiling
evals/               golden cases and the runner
tests/               pytest
```
`data/`, `context/`, `coordination/` exist locally and are gitignored.

## Install
Filled in by WO-004. Until then: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.

## Rules of this repo
- Public. Code and docs only. No MLS data, dumps, embeddings, logs, or secrets, ever.
- Safety invariants: `docs/SAFETY_INVARIANTS.md`. They are not suggestions.
- Measured results live in `docs/EVIDENCE_LOG.md` (from WO-005 on).
