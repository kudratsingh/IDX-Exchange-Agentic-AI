# Email drafts and market reports

Run commands from the repository root with `.venv` active. Configure your owner
recipient locally in `.env`, following `.env.example`. Never paste real addresses,
credentials, previews, journals or exported messages into GitHub.

## Preview through chat

After a listing search, ask `email me these listings`. After recommendations or
semantic results, the model must use those displayed listing keys rather than an
older search. A market example is `email me the condo market in Glendale`.
For reference notes, ask `email me what DOM means`; only project-authored passages
can be included. These preview operations do not call a model or embedding provider
below the tool boundary. The surrounding gateway chat still uses its chat provider.

The preview includes a draft ID, expiry and digest prefix. It says nothing was sent.
`send it`, `approve the draft` and recipient changes are declined in chat.

## Inspect, approve, deliver

The following commands are human-operated. Replace the placeholders with the actual
draft ID and its displayed 12-character digest; never approve a draft you have not read.

```bash
python scripts/approve.py list
python scripts/approve.py show draft-<id>
python scripts/approve.py approve draft-<id> --digest <12-hex-digest>
python scripts/send_approved.py draft-<id> --transport sink
```

The sink stores `data/email/outbox/draft-<id>.eml`; it sends no external mail.
Trying to send the same draft twice is refused. Rejection is available through
`python scripts/approve.py reject draft-<id>`. A draft expires in 24 hours; an
approval expires in 30 minutes. After an interrupted send, create a new draft only
after the operator determines whether the earlier delivery reached its recipient.

For eventual Gmail delivery, set `EMAIL_USER`, `EMAIL_PASSWORD` (an app password),
and `EMAIL_FROM` locally. The recipient stays the configured `owner`. Mint consent
for that one actual draft and then run the exact command:

```bash
scripts/guards/consent.sh paid 30 --command "python scripts/send_approved.py draft-<id> --transport smtp" --max-calls 1
python scripts/send_approved.py draft-<id> --transport smtp
```

This is a future operator step, not part of the offline checks. SMTP uses Gmail SSL
on port 465, with no automatic retries. It is not reachable from MCP.

## Weekly market report

```bash
python scripts/weekly_report.py --print
python scripts/weekly_report.py
python scripts/weekly_report.py --draft --to owner
```

The first command prints without writing a report; the second creates a private
snapshot report under `data/reports/weekly/` and refuses an existing filename. The
third stores a pending draft, never sends, and returns the same draft for unchanged
content and dates. These commands need the SELECT-only database, not an API key.
The default cities are Pasadena, Glendale and Duarte, each at six, three and one
month. A shorter window below five sales is omitted. Duarte's one-month sample has
six sales: price/ratio are reported, while DOM and price per sqft remain unavailable
below their ten-usable-sales threshold. All windows count back from the sold
snapshot and do not change until the dataset is refreshed.

## Offline verification

```bash
python -m pytest -q tests/test_approval.py tests/test_email_bodies.py tests/test_mcp_draft_email.py tests/test_approve_cli.py tests/test_send_approved.py tests/test_weekly_report.py tests/test_email_evals.py
```

Those tests use invented data and temporary private ledgers. They exercise expiry,
tampering, replay, concurrent claims, recipient isolation, local delivery and the
regression scenarios without provider credentials or a real database.
