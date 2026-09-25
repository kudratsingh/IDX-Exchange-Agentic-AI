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
Set `IDX_SENDER_KEY` to a random hex secret (`python -c "import secrets; print(secrets.token_hex(32))"`); without it, follow-ups such as "only condos" do not remember the last search.

`scripts/install.sh` checks OpenClaw and Node, renders `config/openclaw.idx.json5` into
`~/.openclaw/`, and registers the `idx` MCP server. Then check the install by hand:
```
openclaw config validate
openclaw mcp doctor idx --probe     # the server answers and lists its tools, including search_listings, get_market_stats, find_similar_listings, recommend, and rag_answer
openclaw skills list                # includes health, property-search, market-stats, similar-listings, recommend, and docs-qa
```
Link WhatsApp and start the gateway (first time only for the login):
```
openclaw channels login --channel whatsapp
openclaw gateway restart
openclaw logs --follow
```

### The WhatsApp test
Start a demo block with a fresh session: send `/new` from the allowlisted number first.
OpenClaw replays the whole transcript on every model call, and the gateway's chat model
(`gpt-5.6-terra`, `docs/DECISIONS.md`) garbled long replies once a day's transcript rode
along. Then send:

> Find 3-bedroom homes in Pasadena under $1.5M

Expected: up to five listing cards (address or city and ZIP, price, beds and baths,
square feet, days on market with the data's as-of date, photo count) and no agent names,
emails, or phones. Then ask "what did you search for?": the reply shows the accepted
filters (city Pasadena, at least 3 bedrooms, at most 1,500,000). A city the data does not
know gets a follow-up question instead of a guess.

Market figures: send "how is the market in Pasadena" for one card from closed sales (sample count, median price, median days on market, sale-to-list, a monthly trend, and the sold as-of date).

Similar homes: send "a quiet mid-century home with a big yard near good schools" for the five active listings whose descriptions come closest, each card under its rank line. It needs the remarks index built under `data/` (`python -m idx_agent.semantic.build_index --allow-paid`, a human `paid` token minted for that exact command, and `OPENAI_API_KEY` in the environment or `.env`) and `IDX_SEMANTIC_INDEX_DIR` in `.env` pointing at it (WO-010, ADR-0007). Each such message is one paid embedding call, so the tool server needs `OPENAI_API_KEY` (the environment, else the repo's `.env`, the way it finds the database password) and a `paid` token for its own command, or it answers with a provider error. For a WhatsApp test the human mints one token for the server with a ceiling of paid calls, `! scripts/guards/consent.sh paid 30 --command "python -m idx_agent.mcp_server.server" --max-calls 10`: only a process started as exactly that command (as OpenClaw starts it) can spend it, the server's first embedding call spends it, every later call counts against the ceiling, and once the ceiling is reached, the window closes, or a provider call fails, the tool answers with a provider error until the human mints a new token (one token, one run; the server picks up a new one without a restart). Without an index the tool says it is not set up yet.

Homes like one you have seen: after a search, send "show me homes like the second one" for up to five active listings in the same city and type, listed within 25% of its price, each with a price check against comparable closed sales in its ZIP, or its city when the ZIP has too few ("Listed 4% above the median price per square foot of 12 comparable sales in ZIP 91101 over the last six months. The middle half of those sales ran from $602 to $700 per square foot."); "is this priced right?" returns that check alone. It reuses the remarks index and embeds nothing, so the tool adds no embedding call (WO-011).

Terms and columns: send "what does DOM mean?" for a short answer written only from the reference documents, ending with a Sources line that names each document and field or section. It needs the document index built under `data/`, in this order: `python scripts/market_summaries.py` (database only, no paid call; saves the market summaries under `data/knowledge/summaries/`), then `python -m idx_agent.rag.build --allow-paid --calibrate` under a human `paid` token minted for that exact command, with `OPENAI_API_KEY` in the environment or `.env` (the build refuses with the mint line when there is none; a missing summaries folder is skipped with a warning); then `IDX_RAG_INDEX_DIR` in `.env` pointing at the new folder (WO-012, ADR-0009). A question the documents do not cover gets "That is not in the reference documents I have." The not-found floors come from the index; `IDX_RAG_FLOOR_BM25` and `IDX_RAG_FLOOR_COSINE` in `.env` replace them without a rebuild (the tool reloads the index when a floor setting changes).

To follow one message from WhatsApp down to the SQL stages in a local trace viewer, see `docs/TRACING.md` (optional; off unless `IDX_OTLP_ENDPOINT` is set).

The parser eval cases in `evals/cases/property_search.yaml` need a model, so they run
only with a human `paid` consent token minted for that one run's exact command line
(the plan prints the mint line; `evals/README.md`).

## Rules of this repo
- Public. Code and docs only. No MLS data, dumps, embeddings, logs, or secrets, ever.
- Safety invariants: `docs/SAFETY_INVARIANTS.md`. They are not suggestions.
- Measured results live in `docs/EVIDENCE_LOG.md` (from WO-005 on).
