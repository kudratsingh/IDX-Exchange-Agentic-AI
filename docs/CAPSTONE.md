# Capstone presentation and release handoff

The implemented system covers natural-language search, iterative refinement, sold
market statistics, semantic matching, comparable-sale checks, grounded reference
answers, mixed-intent routing, WhatsApp/Control UI, and approved email previews.
The interface remains one assistant; deterministic facts and approvals live in code.
Saved-search management and draft-only new-listing alerts, rich property/digest
previews and extended market metrics are also merged and installed. STATUS.md
separates that implementation checkpoint from the final live acceptance below.
The source-of-truth diagram is in `ARCHITECTURE.md`; data limitations and field
mapping are in `data/schema_notes.md`. API-key migration and live acceptance remain
operator tasks. A recording cannot be produced before a real rehearsal is run.

## Five-minute live sequence

Start with `/new` and wait for every reply. Begin only after the demo preflight
passes with fresh provider consent. The semantic step still needs a compatible
embedding provider independently of the gateway chat model.

| Time | Message/action | Evidence |
|---|---|---|
| 0:00–1:30 | `Find 3-bedroom homes in Pasadena under $1.5M and how is the market there?` | Search plus sold-market routing, dated facts |
| 1:30–2:00 | `only condos` | Prior city, bedroom minimum and budget retained |
| 2:00–3:00 | `a quiet craftsman with a big yard in Altadena`, then `homes like the first one` | Semantic retrieval and comparable-sale checks |
| 3:00–3:30 | `what does DOM mean?` | A grounded answer ending in sources |
| 3:30–5:00 | `email me the condo market in Pasadena`; operator inspects, approves and delivers | Pending preview, separate human approval, receipt |

If using the local sink, describe it as a local delivery demonstration. The planned
real owner email is a later separately authorized send; never describe the sink as
external delivery. The longer regression script is `DEMO_RUNBOOK.md`.

## Recording and backup

Record a clean rehearsal after provider migration. Capture the chat and the operator
approval in sequence; hide settings, addresses, auth state and credentials. Keep the
video locally, with a backup video prepared before the presentation. Do not record
the private journal or unrestricted logs. A failed paid run ends; preserve its
reference and start a separate authorized rehearsal.

## Release evidence still required

- A complete live rehearsal on the chosen chat model, with the actual outputs.
- Fresh paid routing and end-to-end evaluation reports, each at its own path.
- Fresh live workflow evidence on the selected provider. Fixture database integration
  already passed CI; real aggregate and installed health checks are recorded in
  WO-015, WO-009 and EVIDENCE_LOG.md.
- Real owner email, only after exact-draft approval and a one-send token.
- Prefix/peak tokens and actual usage-page cost, with provider and run dates.
- Final backup recording and personal reflection reviewed by the intern.

The project docs distinguish implemented code from these pending acceptance tasks.
The reflection draft is in `REFLECTION.md`; it is not a fabricated personal account.
