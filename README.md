# IDX-Exchange-Agentic-AI

Capstone for the IDX Exchange Agentic AI internship (Fall 2026): a multi-agent
real-estate assistant over MLS listing and sold-transaction data, reached through
WhatsApp, with email drafting behind a human approval gate. Runtime: OpenClaw.
Tools: Python.

**Status:** Phase 1, first slice (Weeks 2-3). Start at `docs/START_HERE.md`; the schedule is `docs/TIMELINE.md`.

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

## Install and run the property-search slice
What WO-004 delivers: a WhatsApp request such as "Find 3-bedroom homes in Pasadena
under $1.5M" returns up to five listing cards from `rets_property` through the typed
`search_listings` tool.

### Prerequisites
- Python 3.11 or newer.
- MySQL with a database `idx_exchange` holding the two tables `rets_property` and
  `california_sold`, loaded from the supplied dumps as WO-002 describes
  (`work_orders/WO-002-data-profiling.md`, "Local setup"): a SELECT-only user
  `idx_reader`, and `scripts/migrations/001_dates_and_indexes.sql` applied once by an
  admin user. The data never enters this repo.
- OpenClaw with Node 24.16+ or 26.1+, onboarded once with `openclaw onboard`. The model
  provider key goes in `~/.openclaw/.env`, not in this repo
  (`docs/adrs/0003-routing-and-tool-route.md`).
- A WhatsApp account on a phone, for the owner (allowlisted) number.

### Steps
```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then edit .env, see below
pytest -q                   # unit tests; integration tests skip without MYSQL_HOST
MYSQL_HOST=localhost pytest -q -m db     # optional: integration tests against your MySQL
./scripts/install.sh
```
In `.env`, set `IDX_OWNER_E164` to your own WhatsApp number in E.164 form (a plus sign,
country code, number), and `MYSQL_*` to the `idx_reader` credentials. `.env` is
gitignored; never commit it.

`scripts/install.sh` checks OpenClaw and Node, renders `config/openclaw.idx.json5` into
`~/.openclaw/`, and registers the `idx` MCP server. Then check the install by hand:
```
openclaw config validate
openclaw mcp doctor idx --probe     # the server answers and lists its tools, including search_listings
openclaw skills list                # includes health and property-search
```
Link WhatsApp and start the gateway (first time only for the login):
```
openclaw channels login --channel whatsapp
openclaw gateway restart
openclaw logs --follow
```

### The WhatsApp test
From the allowlisted number, send:

> Find 3-bedroom homes in Pasadena under $1.5M

Expected: up to five listing cards (address or city and ZIP, price, beds and baths,
square feet, days on market with the data's as-of date, photo count) and no agent names,
emails, or phones. Then ask "what did you search for?": the reply shows the accepted
filters (city Pasadena, at least 3 bedrooms, at most 1,500,000). A city the data does not
know gets a follow-up question instead of a guess.

The parser eval cases in `evals/cases/property_search.yaml` need a model, so they run
only with a human `paid` consent token (`evals/README.md`).

## Rules of this repo
- Public. Code and docs only. No MLS data, dumps, embeddings, logs, or secrets, ever.
- Safety invariants: `docs/SAFETY_INVARIANTS.md`. They are not suggestions.
- Measured results live in `docs/EVIDENCE_LOG.md` (from WO-005 on).
