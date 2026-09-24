# WO-006 — Multi-turn memory

**Driver:** agent builds; human runs the spike's live messages and the WhatsApp test and records them.
**Depends on:** WO-004 (search tool, skill, formatter), WO-005 (eval runner; its PR merged first)
**Estimated effort:** 4-5 hours (the spike is time-boxed to 1 hour of that)

## Objective
After a search, a second WhatsApp message such as "only condos", "under $1.2M", or "show me more" refines
that search for the same sender: code merges the change into the last accepted filters, validates the
result, and runs it. A different sender never sees another sender's filters, results, or page. "Start
over" clears the sender's state. Every card shows the photo count; the formatter already prints it, so
this WO turns it into an acceptance check, not new work.

## Why
Week 4 asks for refinement across turns, and it is the first feature where state outlives a single
message. If the merge lives in the model, "under $1.2M" can silently drop the city; if the store is keyed
loosely, one sender's search can surface in another's chat.

## Inputs
ADR-0003 question 5 (sender identity, `dmScope: per-channel-peer`, OpenClaw owns the transcript, our code
owns policy state, OpenClaw memory does not enforce policy, flush and dreaming off); ADR-0004 (the model
fills the schema, code validates); `docs/CONTRACTS.md` (`UserSession`, `SavedSearch` deferred,
`search_listings` outcomes); `docs/EVALUATION.md` (multi-turn memory category, case format, check types);
`docs/DECISIONS.md` (saved searches pending for Week 4); `src/idx_agent/domain/models.py`
(`UserSession`, `PropertySearchFilters.from_input`, `Listing.photo_count`); `src/idx_agent/memory/`
(empty package); `skills/property-search/SKILL.md`; WO-004 Status (the sender-id item moved here; the
second-phone tests deferred).

## In scope
- **Early-start spike (first task, before any build code; 1 hour; result recorded in Status).** Question:
  how does the sender id reach a tool argument in an OpenClaw WhatsApp DM? Check, in order: (a) whether
  the runtime passes any sender or session identity to an MCP call on its own (request metadata, an
  environment value, the session key); (b) whether the sender appears in the model's turn context so
  the skill can tell the model to copy it into a `sender_id` argument; (c) what happens when the model
  leaves it out (the tool must stay safe and stateless). Also note whether the MCP server process lives
  across turns (count `server_start` lines over a few messages), since an in-process store depends on it.
  Read the local OpenClaw doc digests first; the live messages are sent by the human from the owner
  number, and each is a paid model turn, so a `paid` token covers that run.
  **Decision rule.** (a) holds: use the runtime value; the model never supplies identity. Only (b) holds
  and the model passed the right value on 10 of 10 turns: accept the model-passed id for search state
  only (never for anything that grants an action). Neither holds, or (b) is below 10 of 10: fall back.
  Carry-forward then comes from the OpenClaw transcript (the model passes the last `applied_filters` it
  was shown as `previous_filters`, and code still merges and validates), and our store waits for an
  identity route; nothing that carries policy moves into OpenClaw. The chosen branch goes into a short
  ADR-0005 that closes the ADR-0003 open item.
- `src/idx_agent/memory/merge.py`: `merge_filters(previous, update, mode, clear=())`, deterministic, with
  modes `update`, `replace`, `reset`, validated through `PropertySearchFilters.from_input`.
- `src/idx_agent/memory/identity.py`: `sender_key(raw)`: a keyed hash (HMAC-SHA256) of the normalized
  sender id; the raw value never leaves this function.
- `src/idx_agent/memory/store.py`: an in-process, per-sender `SessionStore` of `UserSession` records with a
  TTL and an entry cap. No file, no database, no persistence across restarts (`DECISIONS.md` gates
  persistent memory on a measured need).
- `search_listings` gains optional `sender_id`, `mode` (`replace` default, `update`, `more`, `reset`), and
  `clear` (filter names to unset) arguments, plus `previous_filters` only if the spike lands on the
  fallback. The result's `applied_filters` is the merged, validated object, and the reply's filters line
  shows it, so the user sees what carried over.
- **Broad-request clarification (added 2026-09-24 by the human).** When a search matches more rows than
  the 50-row cap, the reply carries the first page plus one question ("a budget or a home type to narrow
  it?"). Code counts the matches with the same parameterized WHERE clause, sets `total_matches` and
  `narrowing_question` on the result, and the formatter prints the question as the last line; the skill
  relays it. The missing-location Clarification stays as it is.
- What stays in OpenClaw: the per-sender transcript (session key per peer). What is ours: the last
  accepted filters (including the page cursor), the last result keys, the step count, and `updated_at`.
  OpenClaw memory stays off as a policy store: flush and dreaming stay disabled.
- `skills/property-search/SKILL.md`: when to use each mode, how to pass the sender id (per the spike),
  that "start over" is `reset`, "show me more" is `more`, and that the sender id is never shown in a reply.
- `evals/cases/memory.yaml`: multi-turn memory conversations (see Tests).
- Saved searches: ask the human the Week 4 question in `DECISIONS.md` and record the answer there. The
  question: "Should a sender be able to save a search and get alerts when new matches appear? It needs an
  email address per sender, a stored record that outlives the session, and a scheduled job, each of which
  adds cost and privacy exposure." Unless the answer is yes, `SavedSearch` stays deferred and no class,
  table, or job is added; a yes becomes its own work order, not part of this one.

## Out of scope
Saved searches and alerts (unless the human says yes, and then in a later WO); resolving "the second one"
to a listing (keys are stored for Week 7, not used); market, semantic, recommendation, RAG, or email work;
any persistent store; enabling or relying on OpenClaw memory; a second skill; changes to the formatter
beyond what a test proves is missing; the second-phone tests.

## Files expected to change
`src/idx_agent/memory/{__init__,merge,store,identity}.py`, `src/idx_agent/mcp_server/server.py`,
`src/idx_agent/domain/models.py` (only if `UserSession` changes), `docs/CONTRACTS.md`,
`skills/property-search/SKILL.md`, `evals/cases/memory.yaml`, `evals/run.py` and `docs/EVALUATION.md`
(only if a conversation format is needed), `tests/test_memory_merge.py`, `tests/test_memory_store.py`,
`tests/test_memory_identity.py`, `tests/test_mcp_search.py`, `.env.example` (the key name, no value),
`README.md` (one line on the key), `docs/adrs/0005-sender-identity.md`, `docs/DECISIONS.md` (the saved-search
answer), `docs/EVIDENCE_LOG.md`.

## Interfaces and contracts
```python
MergeMode = Literal["update", "replace", "reset"]

def merge_filters(previous: PropertySearchFilters | None, update: Mapping[str, object],
                  mode: MergeMode, clear: Collection[str] = ()) -> PropertySearchFilters | Clarification

def sender_key(raw_sender_id: str) -> str | None        # lowercase hex; None if no key is configured

class SessionStore(Protocol):
    def get(self, key: str) -> UserSession | None        # None when absent or expired
    def put(self, session: UserSession) -> None          # stamps updated_at from the store's clock
    def reset(self, key: str) -> None

class InMemorySessionStore:                              # implements SessionStore
    def __init__(self, ttl: timedelta, max_entries: int, clock: Callable[[], datetime]) -> None
```
`search_listings(<filter fields>, sender_id=None, mode="replace", clear=None)` still returns
`AgentResult[SearchResult | Clarification]`. A `reset` with no filters is a fourth outcome (`ok=True`,
`data=None`, a short "cleared" message); it goes into the `search_listings` outcomes in `CONTRACTS.md`.
`UserSession` already has what is needed (`filters` carries the page); any field added or changed goes
into `CONTRACTS.md` and the model tests in the same commit.

## Implementation requirements
1. Merge table, all in code: `update` keeps every previous field, overwrites the fields present in the
   update, unsets the names in `clear`, and resets `page` to 1 unless the update sets it; `replace` ignores
   the previous filters; `reset` drops them and uses the update alone (empty update: nothing to search).
2. Location fields replace each other: an update that sets `city` unsets `postal_code`, and the reverse.
3. `more` is code, not the model: stored filters with `page` + 1. With no stored state it becomes the
   usual `missing_location` Clarification, never a guess.
4. `update` with no stored state behaves as `replace`, and a warning says no earlier search was found.
5. Every merged object goes through `from_input`; a conflict (for example a new max below the old min)
   comes back as a Clarification. A name in `clear` that is not a filter field is `unsupported_filter`.
6. State is written only after a search runs with `ok=True`. A Clarification or an error leaves the
   stored state as it was. Stored: the accepted filters and the listing keys of the page; never listing
   text, remarks, or anything from the user's message besides the validated filters.
7. `sender_key` normalizes the id (spaces and punctuation out, one E.164 form) and returns an HMAC-SHA256
   hex digest under a key from the environment. No key configured, or an id that does not normalize:
   the tool runs statelessly and says so in a warning; it never falls back to an unkeyed hash.
8. The store expires a session after the TTL (default 30 minutes idle, set by environment) and evicts the
   oldest entry past the cap (default 1000). TTL and eviction are tested with an injected clock.
9. The tool without `sender_id` behaves exactly as in WO-004, so every WO-004 test passes unchanged.
10. One log line per call, as in WO-004, plus the mode and the first 8 characters of the key; never the
    raw sender id, never the full key, never remarks.
11. The photo count appears on every card ("N photos" or "No photos"), checked by a test and a `ci` case.
12. Over the cap: `SearchResult.total_matches` holds the match count whenever it is known (from the page
    itself when the page is short, else from one COUNT query with the same WHERE clause and parameters as
    the search, minus LIMIT/OFFSET). When the count exceeds 50 and the result is page 1,
    `narrowing_question` holds the one question and `message` ends with it; on later pages of the same
    search, and at or under the cap, `narrowing_question` is None.

## Safety requirements
- No cross-sender leakage: one key per sender, the store looks up only by that key, and the result never
  carries another sender's filters, keys, or page. Proven by a unit test with two keys, and later by the
  deferred second-phone test.
- Hashed keys only: `UserSession.sender_id` already refuses anything that is not lowercase hex. The raw
  number is not logged, stored, returned, or echoed in an error or a Clarification.
- Retrieved text is data: nothing from a result is written to the store except listing keys; remarks
  never enter state or the payload.
- Memory never grants anything: stored state only narrows or repeats a search the sender could type
  again. It never authorizes an email, an approval, or a wider query than the validator allows; the row
  cap, allowlist, and parameterized SQL apply to every merged search as to any other.
- A model-passed sender id (spike branch b) keys search state only; any future approval keys off a
  runtime-bound identity or waits.
- OpenClaw memory stays off as a policy store; `tests/test_openclaw_merge_config.py` keeps asserting that
  flush and dreaming are disabled and the session scope is per peer.

## Tests required
Unit (CI, no model, no database): the merge table as a parametrized case list (update overwrites, update
keeps, `clear` unsets, city replaces ZIP and the reverse, page resets on a change, `more` increments,
`replace` ignores previous, `reset` drops, a merged conflict gives a Clarification, a bad `clear` name
gives `unsupported_filter`); store isolation (two keys, writes to one never visible from the other);
TTL expiry and cap eviction with an injected clock; reset; `sender_key` (stable, differs by key, never
returns or logs the input, `None` without a configured key); the tool keeps state only on a successful
search and returns the merged `applied_filters`; the log line carries no raw sender id (captured stderr).
Integration: none beyond WO-004's `db` tests, which must still pass.
Evals: `evals/cases/memory.yaml`, category `multi_turn_memory`, about 15 conversations. `ci` cases drive
the tool with `input_filters` per turn and check the result with `filters_exact` (update, replace,
carry-forward across three turns, "more", reset, two synthetic sender keys that never see each other's
state) and one `regex` case for the photo line on every card. If a turn sequence cannot be written with the
current case format, add a `turns` field and document it in `docs/EVALUATION.md` in the same commit; a new
check type is added there too. `local` cases ("only condos", "under $1.2M", "show me more", "start over"
after a Pasadena search) need a model and run once with a human `paid` token; the result goes in Status
and `docs/EVIDENCE_LOG.md`.
Manual: from the owner number, a Pasadena search, then "only condos", "under $1.2M", "show me more",
"what did you search for", "start over", and a request with no city; recorded in Status with the date and
a redacted description.
Deferred until a dedicated number exists (deferred, not failed): a second phone refines nothing it did not
search itself and never sees the owner's filters; an outside number gets no reply.

## Acceptance criteria
- The spike result and the chosen branch are in Status and ADR-0005 before any build commit.
- "Only condos", "under $1.2M", and "show me more" each refine the previous search over WhatsApp, and
  "what did you search for" shows the merged filters.
- "Start over" clears state; the next refinement with no city asks for a location instead of reusing
  the old one.
- The two-key isolation, TTL, reset, and merge-table tests pass; no raw sender id appears in any log line,
  result, or fixture.
- Every card in every reply shows the photo count.
- A broad request (more than 50 matches, for example a city with no other filter) returns the first page
  and ends with the narrowing question; a narrow one does not ask.
- All unit tests and the `ci` eval suite pass locally and in CI; WO-004's tests pass unchanged.
- The local memory cases pass in one recorded run (date and result in Status and the evidence log).
- The saved-search question was asked and the answer recorded in `DECISIONS.md`; `SavedSearch` is unchanged
  unless the answer was yes.
- The second-phone tests are marked deferred in Status; they do not block this work order.

## Verification commands
```
pytest -q tests/test_memory_merge.py tests/test_memory_store.py tests/test_memory_identity.py
pytest -q                                               # unit
MYSQL_HOST=localhost pytest -q -m db                    # integration, local only
ruff check . && ruff format --check .
python -m evals.run --suite ci --category multi_turn_memory
python -m evals.run --suite ci
# local memory cases: only with a human `paid` token for that run
# then, from the owner number, the manual flow above
```

## Deliverables
The spike result and ADR-0005; `merge_filters`, `sender_key`, and the in-process session store; the
extended `search_listings` tool and skill; about 15 memory eval conversations; the saved-search answer in
`DECISIONS.md`; one recorded WhatsApp run.

## Stop conditions
- The sender id cannot reach the tool in any documented way and the transcript fallback also fails (the
  model does not pass back `previous_filters` reliably): stop and report; do not invent an identity.
- OpenClaw's session scope behaves differently from ADR-0003 (for example one session shared across
  senders, or a new session per message).
- The MCP server process does not live across turns, so an in-process store cannot hold state: stop; a
  persisted store needs a human decision and an ADR.
- A requirement would need OpenClaw memory, a workspace file, or the transcript to hold policy state.
- The human answers yes to saved searches: stop at the answer; it becomes its own work order.

## Status
**Done on 2026-09-24: merged in PR #21 (CI green with the fixture-backed eval job), independently
reviewed, spike recorded (ADR-0005), the Week 4 WhatsApp flow recorded below.** Two items still to
record here: the saved-search answer (asked; pending) and one paid run of the 5 local memory
conversations.

**Week 4 WhatsApp flow, 2026-09-24 (owner number, live gateway on the merged code; redacted, no rows)**
1. "Find 3-bedroom homes in Pasadena under $1.5M": five cards on page 1 in ascending price, each
   with the flag line, days on market as of 2026-09-18, and the photo count; the filters line; then
   the narrowing question, since the match count is above the cap.
2. "only condos": five condominiums, same city, price cap, and bedrooms carried over; the filters
   line now names Condominium; no narrowing question (36 matches).
3. "under $1.2M": the cap replaced, everything else carried.
4. "show me more": page 2 of the same search, prices continuing upward, "page 2" in the filters line.
5. "what did you search for?": the merged filters, including page 2 and 5 per page, plus the data
   date.
6. "start over": "Cleared your search. What would you like to look for?"
7. "homes with a pool": "Which city or ZIP code should I search for homes with a pool?" (nothing
   carried over after the reset).
- Sender-id check: turns 2 to 6 can only behave this way if the model passed the same sender id on
  every call (update, more, reset all read or write the stored state), and turn 1 must have stored
  it; with the spike's turn that is 7 of 7 required turns. The gateway keeps no MCP stderr, so the
  key prefix itself was read only during the spike. The 10-of-10 target continues across the next
  WOs' manual flows; the transcript fallback was not needed.
- Photo count present on every card. No agent name, email, or phone; no remarks.
- Not run: the deferred second-phone tests (no dedicated number).

**Spike result (2026-09-24, three live turns from the owner number; `docs/adrs/0005-sender-identity.md`)**
- Setup: the snapshot of this branch ran as the live MCP server through a wrapper script, because
  OpenClaw ignores a `PYTHONPATH` in a server's env "for stdio startup safety" (a first attempt with
  env ran main's code; caught by the missing pid in the reply). The server's stderr was copied to a
  scratch file, since the gateway log keeps only its warnings.
- (a) Runtime identity: none. All three calls logged `meta_keys: []`; the MCP SDK on stdio exposes no
  client or session id. Nothing but tool arguments can carry a sender.
- (b) Model-passed identity: on the first search turn the model filled `sender_id` unprompted (the
  live skill had no instruction yet); the logged key prefix equals the HMAC of the owner number under
  the configured secret, checked without printing the number. The skill now instructs it. The
  10-of-10 check runs over the Week 4 manual flow after merge; one turn without a key prefix means
  the transcript fallback.
- Process lifetime: one `server_start` for the session, then three tool calls over five minutes with
  one server process alive; the in-process store holds across turns. Stop condition not hit.
- Also seen: 80 matches for the Pasadena request, so the narrowing question closed the reply; the
  flag lines ("no pool marked", "view") render; the health reply from the model omits pid and start
  time (the model summarises), which is fine, the log line carries them.
- Cleanup: the wrapper command and env override are removed from the live config after merge and
  `scripts/install.sh` re-renders the server entry from `config/openclaw.idx.json5`.

**Saved searches (Week 4 decision)**: asked on 2026-09-24; answer pending. `SavedSearch` unchanged.

**Built (2026-09-24; committed only after the spike result and ADR-0005 below)**
- `memory/identity.py`: `sender_key` (HMAC-SHA256 over the one E.164 form under
  `IDX_SENDER_KEY`; a secret counts only as hex of at least 32 characters; None otherwise, no
  unkeyed fallback), `key_prefix` for logs. `memory/merge.py`: `merge_filters` (modes update,
  replace, reset; `clear`; city and ZIP replace each other; page resets on a change; every
  result through `from_input`), `next_page`. `memory/store.py`: `InMemorySessionStore` (TTL on
  read, oldest-first eviction, injected clock, copies in and out, a lock) and `store_from_env`.
- `search_listings` gains `sender_id`, `mode` (replace, update, more, reset), `clear`; four
  outcomes (results, Clarification, error, and `data=None` for a reset with no filters or
  "more" past the last page); state written only after an ok search, under a per-sender lock;
  the store is built on first use; one log line per call with mode and the key prefix, never
  the raw id. Over-cap rule: `total_matches` from a shared, parameterized COUNT; the narrowing
  question on page 1 only.
- `db/pool.py`: the `.env` fallback supplies MYSQL_* plus exactly `IDX_SENDER_KEY`,
  `IDX_SESSION_TTL_MINUTES`, `IDX_SESSION_MAX_ENTRIES`; the owner number and provider keys are
  never read into the process.
- Formatter: the question as the last section. Skill: modes, the null-data outcomes, the
  narrowing question, the sender rule (filled from the spike). CONTRACTS.md, EVALUATION.md,
  the evals README, `.env.example`, README updated.
- Evals: `evals/cases/memory.yaml`, 19 `ci` conversations (`turns` format in the runner: one
  synthetic sender label per conversation, a fictional-range id derived at run time and never
  written anywhere, the store reset around each case, `sender_id` refused inside any case's
  filters) plus 5 `local` conversations; a `regex` case proves the photo line on every card.
- Tests: `tests/test_memory_{identity,merge,store,cases}.py`, `tests/conftest.py` (every test
  runs with the `.env` fallback pointed at an empty directory unless marked `db` or
  `real_env`), additions to the search, health, format, runner, pool, and db tests.
- Measured on 2026-09-24: unit suite 1027 passed, 8 skipped; `pytest -m db` 8 passed;
  `python -m evals.run --suite ci --require-database` 45 of 45 against the real database and
  45 of 45 against the synthetic fixture (`idx_fixture`).

**Review outcome (no blocker left; all should-fix items applied)**
- Request-metadata key names are logged only when they are plain identifiers with no digit
  run; anything else is logged as a placeholder with its length and phone-like flag.
- A placeholder or short secret never keys anything: `.env.example` ships the key empty.
- The `.env` fallback is an explicit name allowlist, not a prefix.
- The at-or-under-cap boundary is tested with a full page and a count of 50.
- The real HMAC is exercised through the MCP entry point with a run-time-built fictional
  number; the digits never reach stderr or the envelope.
- "More" past the last page answers "last page" and leaves the state unchanged; a reset with
  filters keeps the old state until the new search succeeds.
- The store is lazy, so a bad `IDX_SESSION_*` value cannot break `health`; a per-sender lock
  makes get, search, and put atomic per sender.
- The runner fails a conversation loudly when the store reset helper is missing, refuses a
  `sender_id` in any case's filters, and derives synthetic ids from the fictional range.

**Deviations recorded while building**
- Requirement 9 ("every WO-004 test passes unchanged"): one test had to change, the one asserting the
  tool's flat argument set, because `sender_id`, `mode`, and `clear` now exist. Every other WO-004 test
  is unchanged.
- `src/idx_agent/db/pool.py` changed although it is not in the files list: the `.env` fallback now also
  supplies exactly `IDX_SENDER_KEY`, `IDX_SESSION_TTL_MINUTES`, and `IDX_SESSION_MAX_ENTRIES` (explicit
  names, nothing else), because the server OpenClaw starts has no shell environment and would otherwise
  run stateless.
- Requirement 12 was reworded on 2026-09-24: `total_matches` is set whenever it is known; the question
  appears on page 1 only.
- `more` past the last page returns a short "last page" answer and leaves the state unchanged (not in the
  draft; found in review).

Drafted 2026-09-23 (docs-only PR). Carries two items forward from WO-004: how the sender id reaches a tool
argument (the spike), and the deferred second-phone tests. Assumes WO-005's runner is merged before the
build starts.
