# IDX Exchange — Agentic Real Estate Assistant

A real-estate assistant over MLS listings and closed transactions, reached through WhatsApp. It searches homes, explains the market, finds comparable properties, answers reference questions and prepares email drafts. OpenClaw handles the conversation; typed Python tools handle database access, calculations and side effects.

Built as the IDX Exchange Agentic AI internship capstone, Fall 2026.

## What it does

- **Property search and follow-ups:** translate a request into validated filters, then refine the same search in conversation.
- **Market analytics:** median prices, days on market, sale-to-list ratios, inventory and monthly trends, tied to the dataset's as-of dates.
- **Semantic matching and comparable sales:** match listing descriptions and explain price-per-square-foot comparisons against closed transactions.
- **Grounded reference answers:** retrieve from indexed real-estate and schema documents, with sources and an explicit not-found response.
- **Saved searches:** persist filters and prepare new-listing alert drafts when the data snapshot advances.
- **Email preparation:** property summaries, recommendation digests and market reports, with approval bound to the stored preview.

```text
Find 3-bedroom homes in Pasadena under $1.5M
only condos
email me these listings
```

The last request creates a pending draft. A chat reply such as `send it` cannot approve or deliver it. The operator reviews the stored content and approves its digest through a separate command; no approval or send tool is exposed to the model.

## Current state

The core assistant is merged and has a recorded local installation. Operator email approval, delivery and inbox receipt have been verified. Fresh end-to-end acceptance is still open: the browser rehearsal exposed factual-relay and draft-state errors, and passing direct model checks do not establish correct WhatsApp behavior.

Newer capabilities are at different stages:

| Capability | Public implementation state | Runtime evidence |
|---|---|---|
| Core search, analytics, recommendations, reference answers, email drafts and saved searches | Merged; installation recorded | Partial live evidence; fresh acceptance remains open |
| Remark-feature search, card badges and shared-feature explanation lines | Merged; opt-in configuration required | No serving-host activation or live acceptance recorded |
| Bounded analysis and chart generation | Worker and opt-in tool merged | Worker activation and end-to-end chart delivery remain open |
| Expanded measurement tooling | Merged | Not a completed model-quality campaign |
| Feature reranking, saved feature searches and deal-signal alerts | Not released as live capabilities | No claim |

The [readiness checkpoint](docs/STATUS.md), [acceptance matrix](docs/ACCEPTANCE_MATRIX.md) and [evidence log](docs/EVIDENCE_LOG.md) distinguish merged, installed, enabled and live-verified work. The public repository contains code and documentation only: MLS rows, supplied reference documents, indexes, credentials and recordings are excluded.

## Architecture

```text
Allowlisted WhatsApp user
    → OpenClaw agent + skills
    → typed MCP tools
        → SELECT-only MySQL queries / deterministic analytics
        → semantic and document indexes
        → saved-search store / pending email drafts
    → operator review and approval → separate delivery command
```

Database queries use named, allowlisted columns and parameters. Contact fields are excluded from replies. Market windows use the data snapshot dates rather than today's date. Retrieved text is treated as input data, not instructions. See [architecture](docs/ARCHITECTURE.md) and [safety invariants](docs/SAFETY_INVARIANTS.md).

## Local development

Python **3.11+**. Offline unit tests use synthetic fixtures; database integration needs an authorized MySQL instance. A working assistant additionally needs the private MLS tables, OpenClaw, an allowlisted WhatsApp account, provider configuration and separately built indexes.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python -m evals.run --suite ci
```

Without MySQL, database-dependent CI evaluation cases are skipped. A complete database-backed run requires the documented fixture setup; strict CI mode refuses missing database access.

For a full installation, follow [the setup sequence](work_orders/WO-004-property-search-vertical-slice.md) and [runtime runbook](docs/DEMO_RUNBOOK.md). Copy `.env.example` locally and supply the documented owner, database and sender-key settings. `scripts/install.sh` changes the local OpenClaw configuration; it is not needed for the offline checks above. Index builds and live model runs require the documented per-run consent.

## Explore the project

| Area | Entry point |
|---|---|
| Python tools, domain types and data access | [src/idx_agent](src/idx_agent/) |
| OpenClaw skills | [skills](skills/) |
| Evaluation cases and runner | [evals](evals/), [evaluation guide](docs/EVALUATION.md) |
| Email and saved-search operations | [Email guide](docs/EMAIL.md), [alerts](docs/ALERTS.md) |
| Presentation and walkthrough | [Capstone guide](docs/CAPSTONE.md), [demo runbook](docs/DEMO_RUNBOOK.md) |
| Planned capabilities | [Roadmap](docs/CAPABILITY_ROADMAP.md), [acceptance matrix](docs/ACCEPTANCE_MATRIX.md) |

Before contributing, read [RULES.md](RULES.md) and install the required commit gates. No MLS data, confidential source text, contact details or secrets belong in a commit.
