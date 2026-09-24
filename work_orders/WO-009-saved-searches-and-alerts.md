# WO-009 — Saved searches and alerts

**Driver:** agent builds; the human approves every send through the Week 11 gate and runs the manual test.
**Depends on:** the Week 11 email approval-gate work order (`draft_email`, `send_email`, the stored
`PendingAction` records and their state machine; number not yet assigned), merged first; WO-006 (`sender_key`,
the hashed-key pattern, ADR-0005); WO-004 (search SQL builder, card formatter); WO-005 (eval runner, fixture in CI).
The early-start spike below may run before the gate exists; no build commit lands until it has merged.
**Estimated effort:** 5-6 hours (the spike is time-boxed to 1 hour of that)

## Objective
A sender can say "save this search and alert me", give an email address once, and later receive an alert
email listing the new active listings that match the saved filters. Code, not the model, decides what is new
and writes each alert as a stored `PendingAction` draft; nothing goes out until the human approves that exact
draft through the Week 11 gate. The sender can list their saved searches, delete one after a confirmation
turn, and say "forget me" to erase every saved search and the stored address. Nothing else.

## Why
The human decided yes on 2026-09-24 (`docs/DECISIONS.md`, Pending table): the goal is the most capable
assistant, with cost absorbed and safety carried by gates. It is the first feature that stores personal data
past a session, runs without a user message, and sends to an address, so each of those needs a control that
lives in tested code, not in the model's judgment.

## Inputs
`docs/DECISIONS.md` (the saved-search row; the extension gate "Persistent memory ... a measured requirement";
Email as a state machine keyed by a stored draft id; Time windows); `docs/CONTRACTS.md` (`SavedSearch`
deferred, `PendingAction`, `UserSession`, `AgentResult`, the `draft_email` and `send_email` rows, the rule that
`send_email` refuses anything that is not a stored, approved `PendingAction`); `docs/adrs/0005-sender-identity.md`
(the model passes the sender id; it keys search state only); `docs/SAFETY_INVARIANTS.md` (the email row, the
SELECT-only reader, 50-row cap, agent contact fields, no session state in the repo); `docs/AGENT_RULES.md`
(consent for deletions and paid runs; the agent never installs or runs anything unattended that spends);
`docs/ARCHITECTURE.md` (sections 1, 2, 5, 6); `docs/EVALUATION.md` (case format, sender-label rule, `turns`);
`docs/TIMELINE.md` (Week 11); `work_orders/WO-006-multi-turn-memory.md` (identity, store pattern, Status);
`src/idx_agent/domain/models.py` (`UserSession`, `SearchResult`, `PropertySearchFilters.from_input`);
`src/idx_agent/domain/results.py` (`PendingAction`); `src/idx_agent/memory/{identity,store}.py`;
`src/idx_agent/db/{listings,asof,pool}.py`; `src/idx_agent/channels/format.py`; `config/openclaw.idx.json5`;
`docs/data/schema_notes.md` (active-table date columns); the Week 11 gate WO once it exists.

## Sequencing and identity
- **After the gate.** Alerts leave only through the Week 11 gate. Until `draft_email`, `send_email`, and the
  `PendingAction` store exist and are merged, only the spike and ADR-0007 may be done.
- **Identity rule.** ADR-0005 stands: the sender id is model-passed, and it keys search state only. This WO
  does not let that id authorize anything. The address is bound to a sender like this: the sender types it in
  their own chat; code validates it and stores it under the hashed sender key only; an alert is drafted only
  to the address stored under the key that saved the search; and every send needs the human's approval of the
  exact draft (recipient included). The authorization for a send is the human's approval, never the id. The
  worst case of a wrong id (a model slip, or text pretending to be another sender) is a stored search under
  the wrong key and, later, a draft the human sees and rejects; no mail leaves on the id alone. ADR-0007
  records this rule and ADR-0005 gains a one-line pointer to it. If the human wants a runtime-bound identity
  before any address is stored, that is a stop condition (OpenClaw offers none today, per ADR-0005).

## In scope
- **Early-start spike (first task, before any build code; 1 hour; no paid call; result in Status and
  ADR-0007).** Two questions, answered with local checks only.
  (1) *Where the records live.* Candidates: (a) a SQLite file through the standard library, under the
  gitignored `data/` folder (for example `data/state/alerts.sqlite`, covered by `/data/` and `*.sqlite`);
  (b) tables in MySQL in a schema of their own, written by a separate writer user that has no grant on the
  MLS tables, with the reader untouched; (c) a JSON file. Check for (a): the local `sqlite3` version, WAL mode,
  and that one process writing while another reads succeeds under a busy timeout. For (b): what the human
  would have to create (a schema, a user, grants), which is infrastructure. (c) is rejected unless (a) and (b)
  both fail, since two processes write the records and a JSON file has no atomic update.
  **Decision rule.** Prefer (a): no new dependency, no new service, no credential on the database server, and
  CI can use a temp file. Choose (b) only if (a) fails its check, and only after the human creates the user
  and schema. The human's yes is the measured requirement that the "persistent memory" gate in
  `DECISIONS.md` asks for, for this store only; session memory stays in process.
  (2) *What counts as new.* The data has fixed as-of dates and is refreshed by hand, so "new" is defined
  against the active as-of date (`MAX(ModificationTimestamp)`), never against today. Candidates: (A) listing
  date: a match whose listing date (an allowlisted active-table column named in `schema_notes.md`) is after
  the search's `checked_as_of`, fetched with `LIMIT` at most 50 plus one `COUNT`; (B) key set: the match keys
  now minus the keys stored at the last check, which needs every match key and so fits the 50-row cap only
  for searches with 50 or fewer matches; (C) modification time: rejected, since it also catches price and
  status edits (price-drop alerts are out of scope). Measure as the reader, aggregates only, no rows printed:
  the share of active rows with that date present, and how many dates fall after the active as-of date.
  **Decision rule.** (A) if the date is present on at least 99% of active rows and none is after the as-of
  date; otherwise (B), and `save_search` refuses a search with more than 50 matches with the existing
  narrowing question. Either way, keys already alerted for that search are never alerted again.
  The spike's scripts live in the session scratch directory; its numbers go in Status and
  `docs/EVIDENCE_LOG.md`.
- `SavedSearch` and `AlertRecipient` finalized in `src/idx_agent/domain/models.py` and `docs/CONTRACTS.md`
  (fields in Interfaces). The address moves from `SavedSearch` to one `AlertRecipient` per sender, so it is
  given once and erased once; this departs from the deferred sketch and is flagged for review.
- `src/idx_agent/alerts/store.py`: a persistent `AlertStore` over the chosen backend: recipients, saved
  searches, confirmation codes, and an alert log keyed by (saved search id, active as-of date). It has its own
  writer configuration (`IDX_ALERTS_DB_PATH` for SQLite, or `IDX_ALERTS_MYSQL_*` for MySQL), separate from the
  reader's `MYSQL_*`. The search tools never import it.
- `src/idx_agent/alerts/server.py`: a second stdio MCP server, `idx_alerts`, that holds the writer
  configuration and serves only the saved-search tools: `save_search`, `list_saved_searches`,
  `delete_saved_search`, `forget_me`. The existing `idx` server keeps only the reader. Registered in
  `config/openclaw.idx.json5` and `scripts/install.sh`; the tool allow list gains `idx_alerts__*` and
  nothing else. Because the session store lives in the `idx` process, "save this search" means the model
  passes the `applied_filters` it was last shown as flat arguments, and code validates them again
  (ADR-0004 pattern); the reply's filters line shows what was saved.
- `src/idx_agent/alerts/newsince.py` (pure, no database): the chosen rule as a function of the current match
  keys or dates, `checked_as_of`, and the alerted keys.
- `src/idx_agent/alerts/template.py` (pure): the alert email as plain text (see requirement 12).
- `src/idx_agent/alerts/run.py`, run as `python -m idx_agent.alerts.run`: for each saved search, if the active
  as-of date has moved past its `checked_as_of`, rerun its filters through the existing search builder as the
  reader, compute the new keys, and, when there is at least one, create one `PendingAction` draft through the
  Week 11 gate's draft function (never `send_email`). Flags: `--dry-run` (counts only, writes nothing) and
  `--replay <saved search id>` (operator only; treats the first page of current matches as new for that one
  search, for the manual test; still only a draft).
- `skills/saved-searches/SKILL.md` and `"saved-searches"` in the `idx` agent's skill list (the config test
  updated): when to use each tool; pass the sender's number as `sender_id` as the search skill does; ask for
  the address only when the tool asks; never repeat an address in a reply; "stop alerts" or "forget me" is
  `forget_me`; a delete or forget always takes the confirmation turn; an alert is a draft the owner reviews,
  so never promise that an email "was sent".
- Evals `evals/cases/saved_searches.yaml`, category `saved_searches`, added to `docs/EVALUATION.md`, with the
  runner support the new tools need (see Tests).
- "Forget me": `forget_me` deletes the sender's saved searches, their `AlertRecipient`, pending confirmation
  codes, and alert-log rows, and moves any of their drafts still `pending` to `expired` through the gate, so an
  old draft cannot be approved after the sender left.
- Documentation: the cron line and a LaunchAgent example for the job, in the README; the human installs one.

## Out of scope
Sending anything except through the Week 11 gate; any scheduler beyond a cron line or a LaunchAgent the human
installs (no daemon, queue, or cloud scheduler); push or WhatsApp alerts; price-drop, status-change, or sold
alerts; alerts to anyone but the sender who saved the search; sharing a saved search; a web unsubscribe link or
any hosted endpoint; model-written alert text; changes to `search_listings` or the in-process session store;
editing `.gitignore` (the chosen path must already be ignored).

## Files expected to change
`src/idx_agent/domain/models.py`, `src/idx_agent/alerts/{__init__,store,server,newsince,template,run}.py`,
`config/openclaw.idx.json5`, `scripts/install.sh`, `skills/saved-searches/SKILL.md`,
`tests/test_openclaw_merge_config.py`, `tests/test_alerts_{models,store,newsince,template,run,server}.py`,
`tests/test_models.py` (only for the new models), `evals/cases/saved_searches.yaml`, `evals/run.py`,
`docs/EVALUATION.md`, `docs/CONTRACTS.md`, `docs/ARCHITECTURE.md` (the store, the second server, section 6),
`docs/DECISIONS.md` (the persistence row), `docs/adrs/0007-saved-search-store.md`,
`docs/adrs/0005-sender-identity.md` (one pointer line), `docs/EVIDENCE_LOG.md`, `.env.example` (names only),
`README.md`; `scripts/migrations/002_saved_searches.sql` only if MySQL is chosen; `tests/fixtures/` only if a
case needs a listing the fixture lacks.

## Interfaces and contracts
```python
class AlertRecipient(BaseModel):            # one per sender
    sender_id: str                          # lowercase hex, as UserSession
    email: SecretStr                        # validated (req. 1); masked in repr, str, and JSON dumps
    added_at: datetime

class SavedSearch(BaseModel):
    id: str                                 # random hex, 32 chars; never derived from the sender
    sender_id: str                          # lowercase hex
    filters: PropertySearchFilters          # validated; page forced to 1, limit at most 10
    created_at: datetime                    # audit only
    checked_as_of: date                     # active as-of date of the last check (at save: the current one)
    last_alert_at: datetime | None          # audit only
    last_alert_as_of: date | None
    alerted_keys: list[int]                 # at most 500, newest kept

class SavedSearchView(BaseModel):           # what a tool returns; no address, no sender key
    number: int                             # 1-based, per sender, in creation order
    filters: PropertySearchFilters
    checked_as_of: date
    last_alert_as_of: date | None
    recipient_hint: str                     # first character and top-level domain only

class AlertStore(Protocol):
    def get_recipient(self, key: str) -> AlertRecipient | None
    def set_recipient(self, recipient: AlertRecipient) -> None
    def add_search(self, search: SavedSearch) -> SavedSearch      # refuses past the per-sender cap
    def list_searches(self, key: str) -> list[SavedSearch]        # only that key's rows
    def all_searches(self) -> Iterator[SavedSearch]               # the job only
    def delete_search(self, key: str, search_id: str) -> bool     # key and id must both match
    def forget(self, key: str) -> ForgetReport                    # counts only
    def issue_code(self, key: str, action: str, target: str | None) -> str
    def redeem_code(self, key: str, action: str, target: str | None, code: str) -> bool
    def record_alert(self, search_id: str, as_of: date, pending_action_id: str) -> bool  # False if present
    def mark_checked(self, search_id: str, as_of: date, new_keys: Sequence[int]) -> None
```
Tools (flat optional arguments, each returning `AgentResult` and never raising across MCP):
- `save_search(sender_id, <PropertySearchFilters fields>, email=None)` ->
  `AgentResult[SavedSearchView | Clarification]`. New Clarification reasons: `missing_email` (no stored
  address and none given), `invalid_email` (the question never repeats the value), `missing_sender`,
  `too_many_saved` (cap reached), `too_broad` (rule B only: over 50 matches).
- `list_saved_searches(sender_id)` -> `AgentResult[list[SavedSearchView]]`.
- `delete_saved_search(sender_id, number, confirm_code=None)` and `forget_me(sender_id, confirm_code=None)`:
  without a code, `ok=True`, `data=None`, and `message` states what would be removed and gives a short code;
  with the right code within 10 minutes, the deletion and a count-only reply; a wrong or expired code changes
  nothing.
- Job exit codes: `0` finished (drafts made, nothing new, or no refresh since the last check); `1` unexpected
  error; `2` refused to start (store, writer config, or gate missing, or the reader config would be used to
  write); `3` database unreachable; `4` partial (at least one search failed; the others were committed).
Idempotency key for each draft: `alert:<saved search id>:<active as-of date>`, passed to the gate's draft
function. The gate WO must accept it or expose a lookup; if it offers neither, stop (see Stop conditions).

## Implementation requirements
1. The address is validated in code: one address, at most 254 characters, a strict local-part and domain
   pattern, no display name, no comma, semicolon, space, or line break (no header injection); no new
   dependency (pydantic's email type needs one). It is stored only in `AlertRecipient` under the hashed sender
   key and is never echoed back except as `recipient_hint`.
2. A raw sender id is hashed with `memory.sender_key` at the tool boundary; no key configured or an id that
   does not normalize gives the `missing_sender` Clarification, and nothing is stored.
3. Saved filters go through `PropertySearchFilters.from_input`; page is forced to 1 and limit to at most 10.
   Caps: 5 saved searches per sender, 200 in total (proposal; the human confirms at review).
4. Alerts are drafts, never sends. The job calls the gate's draft function only; no module under `alerts/`
   imports or calls `send_email` or a mail transport, which a test proves by import inspection.
5. The job is idempotent and safe to rerun: at most one draft per saved search per active as-of date, enforced
   by the unique alert-log row and the idempotency key; a rerun after a crash never creates a second draft.
6. No new match, no draft; the search's `checked_as_of` still advances. An unchanged as-of date means no query
   for that search at all.
7. Every draft carries the saved filters in words, the active as-of date, the number of new matches, and the
   cards; the recipient is the stored address, read by code, never taken from model output.
8. The job reads the listings table through the existing builder and the SELECT-only reader, with the 50-row
   cap and the column allowlist; rule A uses `LIMIT` plus one `COUNT`, and rule B only runs on searches with
   50 or fewer matches.
9. Writer configuration is separate from the reader and never reaches the `idx` server process: the pool's
   `.env` fallback allowlist does not gain the writer names, `alerts/store.py` refuses the reader's
   credentials, and a test proves the `idx` server's environment and imports hold neither.
10. All data times count from the as-of dates. Wall-clock times are audit stamps and the confirmation-code
    expiry only; they never select rows.
11. Deletion and forget need a confirmation turn: a code bound to the sender key, the action, and the target,
    single use, expiring after 10 minutes.
12. Alert template: plain text; subject from the validated filters only (for example "3 new listings: Pasadena,
    3+ beds, under $1.5M"); body with the filters line, "as of <date>", at most 10 cards from the existing
    formatter, "and N more" when the count is higher, and a footer saying how to stop (send "stop alerts" on
    WhatsApp). No remarks, no agent or office contact fields, no links, no tracking.
13. One structured log line per tool call and per job step: tool or step, key prefix (8 characters), saved
    search id, counts, outcome, trace id. Never the address, the raw sender id, the full key, a code, or
    listing text.
14. Retention (proposal for review): a saved search lapses 180 days after creation unless saved again; the
    `AlertRecipient` is removed with the sender's last saved search. The sender is told both at save time.
15. The job's summary to stdout lists counts and pending-action ids only, and marks a sender's first alert
    ("first alert to this address") so the human looks twice before approving it.

## Safety requirements
- The approval gate is the only path to a send (`SAFETY_INVARIANTS.md`, email row). Alerts reuse
  `PendingAction`; `send_email` keeps refusing anything not stored and approved; a draft never changes
  recipient after creation.
- The model-passed sender id authorizes nothing (ADR-0005). It only picks which stored records a tool reads
  or writes, and a send still needs the human.
- No address in logs, cards, replies, eval files, fixtures, or test source: tests and evals build addresses
  at run time from labels under a reserved test domain, as the sender-label rule does for numbers.
- The store is outside the repo: a gitignored path (SQLite) or a separate MySQL schema (never a dump in the
  repo). A test asserts the configured path is ignored by git. `.gitignore` is not edited.
- The reader stays SELECT-only and has no grant on the saved-search tables (MySQL case, integration test).
- The model never sees another sender's records: every store read is filtered by the caller's key, and a
  delete needs both the key and the id to match; proven with two senders.
- Retrieved text is data: listing remarks never reach a draft, and nothing in a result can save, delete, or
  forget a search.
- Deleting a sender's data is a first-class command (`forget_me`), and it expires their pending drafts.
- Product deletions happen only through the tools, inside the running store. The agent building this never
  deletes or rewrites a live store file or table; tests use temp stores. `docs/AGENT_RULES.md` section 1
  applies to the live store as to any data.
- No paid call anywhere in the job; the only cost is a send, and each send is a human approval.

## Tests required
Unit (CI, no model, no database unless marked): the models (email validation table, `SecretStr` masking in
repr and JSON, filters forced to page 1 and limit 10, caps); store round trip on a temp backend with two
senders fully isolated (list, delete with the wrong key, forget leaves the other sender intact);
confirmation codes (wrong, reused, expired, other sender's, other target); new-since logic with fixed keys
and dates (new keys found, alerted keys never repeated, no refresh gives no work, an older as-of never
counts); the job with a fake gate and a fake reader (idempotent rerun, crash between draft and log row, one
draft per search per as-of, none without new matches, exit codes, `--dry-run` writes nothing, `--replay`
drafts only); the template (no agent contact field names, no remarks, no link, at most 10 cards, the as-of
date and filters present); the address never logged (captured stderr and stdout through every tool and the
job); `alerts/` never imports `send_email`; the writer names absent from the `idx` server's environment
fallback.
Integration (`@pytest.mark.db`): the job against the fixture database with a temp store and a fake gate; for
MySQL, the reader cannot select from or write to the saved-search tables.
Evals (`saved_searches.yaml`): `ci` cases for the save, list, delete, confirm round trip on the fixture; two
sender labels never see each other's searches; the new-since computation with fixed keys; no draft without new
matches; no send without approval (a draft in `pending` is refused by `send_email`); the address never in any
envelope. `local` phrasing cases ("save this search and email me new ones", "what searches do I have saved",
"delete my second saved search", "stop alerts") run once with a human `paid` token.
Manual: from the owner number, search, "save this search and alert me", give an address, list; the human runs
`python -m idx_agent.alerts.run --replay <id>`, approves the one draft through the gate, and confirms it
arrived; then delete with the confirmation turn and "forget me"; recorded in Status with the date, redacted.

## Acceptance criteria
- The spike result, the persistence choice, the new-since rule, and the identity rule are in Status and
  ADR-0007 before any build commit; ADR-0005 points to ADR-0007.
- A sender can save a search with an address given once, list it, delete it after a confirmation turn, and
  forget everything; each is proven by a `ci` case and the manual run.
- The job creates at most one draft per saved search per as-of date, none without new matches, and never sends;
  a rerun creates nothing new.
- The one manual alert went out only after the human approved it through the gate.
- No address, raw sender id, full key, or agent contact field appears in any log, reply, card, fixture, eval,
  or test source.
- The writer configuration never reaches the `idx` server; the reader stays SELECT-only.
- All unit tests and the `ci` eval suite pass locally and in CI; earlier tests pass unchanged.

## Verification commands
```
pytest -q tests/test_alerts_models.py tests/test_alerts_store.py tests/test_alerts_newsince.py \
  tests/test_alerts_template.py tests/test_alerts_run.py tests/test_alerts_server.py
pytest -q                                               # unit
MYSQL_HOST=localhost pytest -q -m db                    # integration, local only
ruff check . && ruff format --check .
python -m evals.run --suite ci --category saved_searches --require-database
python -m evals.run --suite ci --require-database
python -m idx_agent.alerts.run --dry-run                # counts only; writes nothing
git check-ignore -v data/state/alerts.sqlite            # the SQLite path is ignored (if chosen)
# local phrasing cases: only with a human `paid` token for that run
# then, from the owner number, the manual flow above
```

## Deliverables
The spike result and ADR-0007; `AlertRecipient` and the final `SavedSearch` in code and `CONTRACTS.md`; the
persistent `AlertStore` with its own writer configuration; the `idx_alerts` MCP server with four tools; the
new-since function, the alert template, and the `alerts.run` job; the `saved-searches` skill; the eval cases
and runner support; the cron and LaunchAgent documentation; one recorded, human-approved alert.

## Stop conditions
- The Week 11 gate is not merged, or it lacks a draft function the job can call, a way to expire a pending
  draft, or an idempotency key or lookup for drafts.
- The address cannot be bound safely under the rule above, or the human asks for a runtime-bound identity
  that OpenClaw does not provide.
- The persistence choice needs infrastructure the human has not approved (a MySQL user or schema, a new
  service, or a dependency), or the chosen path is not already gitignored.
- The writer configuration can only work inside the `idx` server process.
- Any requirement would send without the human's approval of the exact draft, send to an address not stored
  for that sender, or put model text into an alert.
- The new-since rule would need more than 50 rows in one result, or a window counted from today.

## Status
not started

Drafted 2026-09-24 (docs-only PR). Follows the human's yes on saved searches and alerts, recorded in
`docs/DECISIONS.md` on 2026-09-24. Sequenced after the Week 11 email approval-gate work order, since every alert
is a draft sent only through that gate; only the spike and ADR-0007 may start earlier. For review: the address
moving to `AlertRecipient`, the caps (5 per sender, 200 total), the 10-card limit, the 180-day retention, and a
second MCP server for the writer.
