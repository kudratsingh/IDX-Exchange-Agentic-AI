# IDX-Exchange-Agentic-AI

Capstone for the IDX Exchange Agentic AI internship (Fall 2026): a multi-agent
real-estate assistant over MLS listing and sold-transaction data, reached through
WhatsApp, with email drafting behind a human approval gate. Runtime: OpenClaw.
Tools: Python.

**Status:** The requested implementation is merged into main and installed locally:
eight skills and eleven tools across the reader and saved-search servers. Automated
checks and runtime probes pass. Anthropic setup, fresh live acceptance, real email
verification and the final recording remain pending. See [current readiness](docs/STATUS.md).

> **Before you commit anything, read `RULES.md`.** Three rules, each enforced by a
> pre-commit hook and again by CI: no data, no text from the handbook or the supplied
> PDFs, no secrets or people. Commits are blocked until the gates are installed.

## Implemented capabilities
- Search active listings from plain-language requests, with follow-up refinement.
- Answer market questions from closed transactions (median price, days on market,
  sale-to-list ratio, trend), by property subtype.
- Find similar homes semantically and check their prices against comparable sales.
- Answer real-estate and schema questions from indexed reference documents.
- Persist saved filters and queue new-listing alert drafts when the snapshot advances.
- Calculate means, monthly price-per-sqft changes and current inventory comparisons.
- Draft photo/comp property summaries, recommendation digests and market reports for
  the owner; delivery requires explicit
  approval of the stored preview through a separate operator command.

## Demo and email workflow

Use [the capstone guide](docs/CAPSTONE.md) for the five-minute presentation sequence,
[the full runbook](docs/DEMO_RUNBOOK.md) for the regression walkthrough, and
[the email guide](docs/EMAIL.md) for draft inspection, approval, local delivery and
weekly reports. [Provider handoff](docs/PROVIDER_HANDOFF.md) distinguishes the planned
Anthropic chat switch from the existing embedding provider. Architecture and field
usage are documented in [ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[schema_notes.md](docs/data/schema_notes.md).

Example UI flow:

```text
Find 3-bedroom homes in Pasadena under $1.5M and how is the market there?
only condos
email me these listings
```

The final reply is a pending preview. `send it` in chat cannot approve or deliver it.
The operator reviews it with `python scripts/approve.py show <draft-id>`, approves its
displayed digest in a terminal, then uses `python scripts/send_approved.py <draft-id>
--transport sink` for local verification. Nothing leaves the machine through the sink.
Saved-search alerts, photo/comp email summaries and expanded market analytics are
merged into main and installed locally, with live acceptance pending. See the
[additional-capability handoff](docs/ADDITIONAL_CAPABILITIES.md) and
[saved-search runbook](docs/ALERTS.md), which includes optional cron and LaunchAgent
examples. No schedule is installed by the application.

## Layout
```
CLAUDE.md            working rules for coding agents
AGENTS.md            coding-agent entry point
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
`~/.openclaw/`, and configures the `idx` reader and `idx_alerts` writer servers.
It loads the skill sources in place. Then check the install by hand:
```
openclaw config validate
openclaw mcp doctor idx --probe        # seven tools, including draft_email; no send/approval tool
openclaw mcp doctor idx_alerts --probe # save, list, confirmed delete, forget
openclaw skills list                  # eight ready skills, including email and saved-searches
```
Link WhatsApp and start the gateway (first time only for the login):
```
openclaw channels login --channel whatsapp
openclaw gateway restart
openclaw logs --follow
```

### The WhatsApp test
To run the full 25-message regression conversation with its preflight,
paid token, recording, and error checks, follow `docs/DEMO_RUNBOOK.md`. The steps below
test one role at a time.

Start a demo block with a fresh session: send `/new` from the allowlisted number first.
OpenClaw replays the whole transcript on every model call, and the gateway's chat model
(historically `gpt-5.6-terra`, `docs/DECISIONS.md`) garbled long replies once a day's transcript rode
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

The next capability phases are saved in [the combined roadmap](docs/CAPABILITY_ROADMAP.md),
with [a complete proposal crosswalk](docs/ROADMAP_CROSSWALK.md). The first enrichment
library is preparation only; [WO-018](work_orders/WO-018-remarks-enrichment.md) records
its scope and the labeling/integration still required before new filters are available.
