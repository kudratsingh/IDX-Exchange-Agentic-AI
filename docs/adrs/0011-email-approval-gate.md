# ADR-0011: Owner-only previews and operator delivery

Status: implemented offline, 2026-10-24. The human decisions recorded in WO-015
on 2026-09-25 apply; live provider verification is deferred by the human.

The only model-callable email operation is `draft_email`. It receives structured
source arguments and the label `owner`, never an address, subject or body. It
re-fetches listings or market statistics, or retrieves project-authored reference
notes locally. Confidential passages and contact fields cannot enter a stored body.
The public preview omits the owner address; operator inspection shows it locally.

Draft records live under ignored `data/email/` in a locked 0600 append-only ledger.
A SHA-256 digest binds the id, recipient, source, subject, body, timestamps and
idempotency key. `approve.py` requires a terminal and the displayed digest prefix.
Approval expires after 30 minutes; drafts expire after 24 hours. A send command
reloads the record and durably claims it before opening a transport. A failed or
interrupted attempt remains locked in `sending`; there is no automatic retry.
Corrupt or torn journals fail closed and require operator attention; evidence is
never rewritten by recovery code.

`send_approved.py --transport sink` writes one private `.eml` with exclusive create.
Gmail SSL uses the standard library and the existing exact-command consent gate,
with a ceiling of one provider operation. Credentials are read only in that process.
No provider credentials are needed to verify the sink, approval logic, reports or
the new safety cases. No new dependency or service was installed.

WhatsApp approval is not adopted: no authenticated handler outside the model has
been demonstrated. The terminal path is the previously approved default. Any future
chat approval must establish runtime identity without relaxing the shell denial.

Reports use six-, three- and one-month snapshots for Pasadena, Glendale and Duarte.
The aggregate-only sample check on 2026-10-24 found at least five sales in every
window; Duarte's one-month sample has six, so DOM/price-per-sqft remain unavailable
at their ten-usable-sales threshold. Future shorter windows under five are omitted.
Reports are deterministic, never overwritten, and can
create an idempotent pending email. A scheduler is not installed.

Alternatives rejected: an MCP send tool, approval inferred from model text, recipients
typed into chat, automatic retries and outbound delivery without per-command consent.
Reverse the recipient restriction only through a separately reviewed identity design.

Deferred: live Gmail delivery, live routing evaluations, runtime skill installation,
and classifying the operator CLIs in the Claude hook. Hook changes require the
repository's explicit `gates` consent; the existing code-level delivery gate is active.
