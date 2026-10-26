# Additional handbook capabilities: offline handoff

The human authorized the remaining capabilities on 2026-10-24, with provider keys
and live evaluations deferred. This build adds:

| Capability | UI prompt after install | Deterministic behavior |
|---|---|---|
| Saved search | `save this search` after a listing search | Persists the displayed filters for owner-reviewed alert drafts |
| Manage alerts | `list saved searches`, `delete my saved search number 1`, `stop alerts` | Isolated bucket; removal requires a confirmation code |
| Property email | `draft a property summary with photos and comps for the first listing` | Re-fetches the subject and price check; includes up to three feed photos |
| Recommendation digest | `draft a recommendation digest with photos and comps for homes like the first listing` | Re-ranks up to five similar active homes and rechecks their comps |
| Averages and inventory | `give me average sale prices and days on market, plus active inventory versus sales, for Pasadena` | Additional aggregates over the same cleaned sale sample and subtype |
| PPSF trend and monthly changes | `show monthly price per square foot and month-over-month changes for Pasadena` | Monthly median PPSF and mean price, comparing complete months only |
| Historical comparison | `compare the condo market year over year in Pasadena` | Uses complete matching calendar months when available; otherwise explains the missing history |

Use actual displayed keys; do not invent listing identifiers. Email previews are
pending records. Approval and delivery happen only through operator commands.
Descriptions and document answers may need the existing embedding provider; the
new saved-search, analytics and email tool paths make no provider requests.

`get_market_stats(include_extended=True)` requests the extra metrics without
changing the usual median-based card. The response's `analytics` contains active
inventory and its date, sold count, mean price/DOM/PPSF and monthly rows. Means use
the same cleaning and duplicate-sale rules as the medians. Mean price requires
five sales overall and three per calendar month; DOM and PPSF metrics require ten
usable observations. Monthly price changes use mean sale price; PPSF changes use
the monthly median. Changes are computed before display rounding, to one decimal
percentage point. Partial months never supply a MoM or YoY comparison, and a gap
does not become the previous month. Current inventory is not historical inventory
or a forecast. Run `python scripts/weekly_report.py --extended --print` for an
expanded report without writing or drafting it.

The actual sold snapshot covers 2026-03-18 through 2026-09-17. Requests for a year
are truncated with the existing coverage warning; no twelve-month trend or YoY
result is fabricated. The comparison code is tested with synthetic longer history.
The established recommendation policy remains hard criteria followed by semantic
cosine ranking and a separate comp assessment; this work does not replace it with
the handbook's illustrative weighting scheme.

Photos are validated HTTPS image references from the allowlisted feed column,
never downloaded by this code. Up to three per home appear in plain text and in a
deterministic HTML alternative at delivery. HTML escapes every other line and has
no script or tracking markup. Credentials, query strings, private hosts, contact
words and malformed links are refused. Numeric image filenames are treated as
image identifiers only on validated Photo lines in the two rich draft types;
ordinary body text keeps the contact-information backstop. The exact URLs are part
of the approved body digest. The recipient's mail client may load remote images.

## Operator work after returning

PRs #81 and #82 have now been merged and installed under the human's instruction.
Config validation, both server probes, eight ready skills, model-free health and
gateway RPC checks passed. Existing provider settings and credentials were preserved.

1. Anthropic Sonnet 5.5 / medium is configured; keep the separate embedding
   dependency for semantic and hybrid document queries (PROVIDER_HANDOFF.md).
2. Gateway restart is complete; begin a fresh session for the manual rehearsal.
3. Run the UI prompts above, including the saved-search confirmation turn.
4. Run the alert job's dry-run, then a deliberate replay and terminal approval
   rehearsal if desired. Only the operator may approve or send; see ALERTS.md.
   WO-015's operator-command hook fix is merged in PR #86; approval is still
   operator-only. This rehearsal does not change enforcement.
5. Grant run-specific paid consent before live routing/e2e tests or SMTP delivery.
   Record costs from the provider console and record the final capstone backup.

Gateway installation and restart are complete. Direct routing/context checks have
passed; STATUS.md records partial behavior acceptance and the remaining human
marks, runtime/email checks and capstone steps. Scheduling is still optional and
not installed. Each remaining paid check requires its own human grant.
