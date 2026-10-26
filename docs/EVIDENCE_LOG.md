# Evidence log

Measured numbers that changed, one row per measurement, as described in `docs/EVALUATION.md`.

| Date | WO | What was measured | Before | After | How |
|---|---|---|---|---|---|
| 2026-09-24 | WO-005 | `ci` eval suite pass rate | no runner (a temporary test checked 13 case shapes) | 26 of 26 pass (13 property-search, 13 safety), 0 skipped | `python -m evals.run --suite ci --require-database` against the local real database and against the synthetic fixture (`idx_fixture`), both 26/26 |
| 2026-09-24 | WO-005 | db integration tests against the synthetic fixture | only runnable against the real database | 7 of 7 pass, tests unmodified | `MYSQL_HOST=localhost MYSQL_DATABASE=idx_fixture pytest -q -m db` after loading `tests/fixtures/synthetic.sql` |
| 2026-09-24 | WO-005 | unit test count on the branch | 705 (main after WO-004) | 798 unit + 7 db (after the temporary eval-cases test was removed) | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-005 | CI wall time, tests job only | 1 min 16 s (WO-004 run, unit tests only) | 1 min 0 s with the MySQL service, fixture load, db tests, and the ci eval suite (push run on commit e8c33ef) | GitHub Actions job durations (`gh pr checks`) |
| 2026-09-24 | WO-004 | parser accuracy on the 10 local cases | not measured | not measured (needs a `paid` run) | `python -m evals.run --suite local --allow-paid` with OPENAI_API_KEY and IDX_EVAL_MODEL |
| 2026-09-24 | WO-004 | local suite, run 1, model gpt-4.1-mini | not measured | 10 of 12 pass: 8 of 10 parser cases, both refusal cases; fails: "3-bedroom" also filled `limit: 3`; "without a pool" set `pool: false` | `python -m evals.run --suite local --allow-paid`, one paid run under a human token; cost to be read from the provider console |
| 2026-09-24 | WO-004 | local suite, run 2, after rewording the `limit` and `page` tool descriptions | 10 of 12 | 11 of 12 pass: 9 of 10 parser cases; the only failure is "without a pool" -> `pool: false`, pending a decision on the expected reading | same command, one more paid run under the same token |
| 2026-09-24 | WO-004 | local suite, run 3, after the decision that "without a pool" sets `pool: false` (case and pool/view descriptions updated) | 11 of 12 | 11 of 12: the pool case passes; "3-bedroom" filled `limit: 3` again, so that case was flaky at the default temperature (passed run 2, failed run 3) | same command, a second paid token |
| 2026-09-24 | WO-004 | local suite, run 4, driver temperature pinned to 0 | 11 of 12 | 12 of 12 pass: all 10 parser cases and both refusal cases | same command; `evals/run.py` now sends `temperature: 0` so runs are repeatable |
| 2026-09-24 | WO-006 | `ci` eval suite with the 19 multi-turn conversations | 26 of 26 (WO-005) | 45 of 45 against the real database and 45 of 45 against the synthetic fixture, 0 skipped | `python -m evals.run --suite ci --require-database`, once per database |
| 2026-09-24 | WO-006 | unit test count on the branch | 798 unit + 7 db (main after WO-005) | 1027 unit + 8 db | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-006 | broad-request question on the real data | none | a plain Pasadena search counts 316 matches and ends with the narrowing question; "only condos" narrows to 144; page 2 of the same search asks nothing | tool body against the local database during the build |
| 2026-09-24 | WO-006 | local memory conversations, run 1 (gpt-4.1-mini, temperature 0, real database) | not measured | 4 of 5 pass; "start over" ran a search because the driver sent only the tool schema, not the skill text the live gateway gives the model | `python -m evals.run --suite local --allow-paid --category multi_turn_memory --require-database`, one paid run under a human token |
| 2026-09-24 | WO-006 | local memory conversations, run 2, driver system prompt now includes the property-search skill body | 4 of 5 | 5 of 5 pass (update, price change, more, start over then no-city clarification, three-turn carry-forward) | same command after the driver change (chore PR) |
| 2026-09-24 | WO-007 | one WhatsApp search turn, traced end to end | not traceable across the MCP boundary | OpenClaw tool span and our `idx.tool_call` start 78 ms apart (rule: within 2 s); turn 29.4 s total, model calls 8.5 s and 18.3 s, our tool 0.19 s, page query 0.17 s | Jaeger v3 API over both service names after the turn (`docs/TRACING.md`) |
| 2026-09-24 | WO-007 | tool call with the collector down | n/a | gateway and probe unaffected; the `tool_call` line in `logs/idx-agent.log` plus one throttled `trace_export_failed` line | Jaeger stopped, gateway restarted, one "health check" from the owner number |
| 2026-09-24 | WO-007 | unit test count on the branch | 1028 unit + 8 db (main after WO-006) | 1103 unit + 8 db | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-008 | market spike: SQL median exactness and speed | not measured | both median methods agree on 40 of 40 samples; the largest city (4,619 sales, all types) runs the full seven-statement set in 0.094 s; every statement uses ix_sold_city | `scripts/market_spike.py` against the local real database, best of three |
| 2026-09-24 | WO-008 | `ci` eval suite | 45 of 45 | 66 cases: 52 pass on the real database with 14 fixture-only cases skipped; 66 of 66 in CI against the synthetic fixture | `python -m evals.run --suite ci --require-database --database-kind real`; the CI job |
| 2026-09-24 | WO-008 | unit test count on the branch | 1104 unit + 8 db (main after WO-007) | 1367 unit + 11 db (23 fixture-only skipped locally) | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-008 | live market cards over WhatsApp | none | five questions answered as specified: two full cards, one 3-month condo card, one not-enough-comps reply with a runnable widening step, and the search memory untouched by a market call | owner-number run, described in the WO-008 Status |
| 2026-09-24 | WO-008 | local market phrasing cases (gpt-4.1-mini, temperature 0, skill body in the prompt) | not measured | 5 of 5 pass on the first run ("how is the market in Pasadena", a condo question with a 3-month window, a ZIP question, an over-asking question, a six-month trend question) | `python -m evals.run --suite local --allow-paid --category market_analytics --require-database --database-kind real`, one paid run under a human token |
| 2026-09-24 | WO-010 | semantic spike: remark profile on the real active table | not measured | 54,884 of 55,212 active rows have a usable remark (99.4%); median 1,244 characters, longest 4,000; about 18 million tokens for one build; 223 remarks with contact-like or link text; 3 repeated keys; about 339 MB at 1,536 dimensions | `scripts/semantic_spike.py --profile` and the build CLI's `--dry-run`, both read-only against the local real database |
| 2026-09-24 | WO-010 | `ci` eval suite | 66 of 66 | 87 cases: 59 pass on the real database with 28 fixture-only cases skipped; 87 of 87 expected in CI against the regenerated fixture (locally 78 pass and 9 need the reloaded fixture) | `python -m evals.run --suite ci --require-database --database-kind real`; the CI job |
| 2026-09-24 | WO-010 | unit test count on the branch | 1367 unit + 11 db (main after WO-008) | 1673 unit + 28 db against the fixture (11 against the real data) | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-010 | semantic spike: index size, cold start, ranking speed, memory (random unit vectors of the real shape, no provider) | not measured | 1,536 dims: 347.0 MB on disk, cold start 0.40 s (import, load, one rank of the top 200), warm rank 6.5 ms, peak RSS 747 MB, then 444 MB with the chunked unit-length check (cold start 0.36 s); 512 dims: 120.8 MB, 0.24 s, 4.5 ms, 293 MB then 193 MB; 1,536 kept | `scripts/semantic_spike.py --sizes`, best of three fresh processes, files just written |
| 2026-09-24 | WO-011 | comps spike: reach of the decided comps rule on 200 real active listings (10 per city in the 20 largest cities) | not measured | 193 checkable (7 lack a size, bed count, or subtype); 162 (83.9%) reach 5 comps in the city; 31 (16.1%) needed the ZIP step and none reached 5 there; median comps count in the city 113 (quartiles 16 and 206); the sold table has no county column | `scripts/comps_spike.py` as the reader user, aggregates only, three identical runs |
| 2026-09-24 | WO-011 | comps spike: statement timing in the largest city | not measured | city comps statement 7 ms median (10 ms worst), ZIP statement 1 ms, a full recommendation's set (subject plus five listings) 0.037 to 0.038 s, worst-case bound for 12 statements 0.061 s; `ix_sold_city` (ref) and `ix_sold_postal` (range) | same script, best of three per statement, `EXPLAIN FORMAT=TRADITIONAL` |
| 2026-09-24 | WO-011 | `ci` eval suite | 87 (WO-010) | 107 cases: 63 pass on the real database with 44 fixture-only cases skipped; 107 of 107 expected in CI against the regenerated fixture (locally 83 pass and 24 need the reloaded fixture) | `python -m evals.run --suite ci --require-database --database-kind real`; the CI job |
| 2026-09-24 | WO-011 | unit test count on the branch | 1673 unit + 28 db (main after WO-010) | 1976 unit + 28 db against the fixture (11 against the real data; the new fixture-dependent db tests run in CI) | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-010 | one-time embedding build of the active remarks (paid, under a human token) | none | sample of 300 listings: 61,055 tokens reported by the API in 6 s; full build: 54,881 of 55,212 rows embedded (328 empty or too short, 227 redacted, 3 repeated keys collapsed), 14,029,433 tokens reported by the API, 17.1 minutes, 348 MB on disk; dollars from the usage page: pending the human's reading | `python -m idx_agent.semantic.build_index --allow-paid [--sample 300]` |
| 2026-09-24 | WO-010 | cold start and peak memory on the built index | spike: 0.36 s and 444 MB on random vectors | 0.37 to 0.57 s (import, load, one rank of the top 200), peak RSS 442 MB, three fresh processes | `/usr/bin/time -l` around a load_index plus rank script |
| 2026-09-24 | WO-010 | local phrasing cases (gpt-4.1-mini, temperature 0, real database, built index) | not measured | 4 of 4 pass on the first run; the 10 judged cases skipped for want of a marks file | `python -m evals.run --suite local --allow-paid --category semantic_retrieval --require-database --database-kind real`, one paid run under a human token |
| 2026-09-24 | WO-011 | local phrasing cases (gpt-4.1-mini, temperature 0, real database, built index) | not measured | 5 of 5 pass on the first run (homes like the second one, like listing <key>, just 3 of them, is this priced right with k 0, more like the first one) | `python -m evals.run --suite local --allow-paid --category recommendations --require-database --database-kind real`, one paid run under a human token |
| 2026-09-24 | WO-012 | RAG spike: extraction and chunking of the reference documents (counts only) | not measured | Trestle doc 36 pages, all with text, 721 field entries, 109,052 characters; Primer 8 pages, 12 sections, 17,272 characters; 753 chunks by the decided rule before drops, 728 after the WO's drop rule; every set question has an exact-name hit; BM25 off-topic top 6.63 against 11.05 for on-topic questions without an exact hit, floor 8.84 at the midpoint; paraphrases show no gap (the hybrid route's case) | `scripts/rag_spike.py --docs-root data/knowledge`, read-only, no provider |
| 2026-09-24 | WO-012 | document index dry run on the real sources | not measured | 625 chunks (587 Trestle after dropping 11 deny-listed, 14 agent-contact, and 110 contact-like entries; 13 Primer; 20 schema notes; 5 glossary), 149,712 characters to embed; the three set questions, two seed questions, and two off-topic questions behave as specified in memory | `python -m idx_agent.rag.build --dry-run --sources trestle,primer,schema_notes,glossary` |
| 2026-09-24 | WO-012 | `ci` eval suite | 108 of 108 | 128 cases: 128 of 128 against the fixture (20 new rag cases need no database); 83 pass on the real data with 45 fixture-only skipped | `python -m evals.run --suite ci --require-database`, both database kinds |
| 2026-09-24 | WO-012 | unit test count on the branch | 2040 unit + 56 db (main after WO-011) | 2252 unit + 55 db against the fixture | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-012 | BM25 not-found floor re-measured on the final chunking (625 chunks) | 8.84 from the spike's 728-chunk corpus | no gap: 15 own-words off-topic questions score 0.0 to 14.1, 11 on-topic paraphrases with no exact hit 4.3 to 25.7; floor set at 14.60 (best off-topic plus 0.5); the three set questions still hit exactly; 8 of 11 paraphrases fall to the vector leg | `scripts/rag_floor_probe.py --docs-root data/knowledge`, read-only, no provider |
| 2026-09-24 | WO-013 | prefix audit of the 37,000-token fixed prompt (counts only; token figures estimated at four characters per token) | not measured | our text about 3,000 tokens (skill list entries about 600, tool schemas about 2,300, instructions about 150), 8% of the prefix; the rest about 34,000, of which OpenClaw's own prompt about 32,000 (86%) and one workspace file about 2,000; the six skill bodies about 5,900 loaded on demand, about 4,700 for a four-skill session | `scripts/prefix_audit.py`, read-only, sizes by lstat, nothing opened |
| 2026-09-24 | WO-013 | routing baseline on the gateway model (gpt-5.6-terra, reasoning_effort none, no temperature control) | not measured | unchanged skills: 17 of 20 (misses: a mixed definition-plus-market message, show-me-more after a market answer, an injection message with a real search); reworded skills: 16 of 20 and 16 of 20 with different misses (the mixed cases fixed; show-me-more after non-search tools and one exact-criteria search flip between runs; the injection message declined whole in every run) | `python -m evals.run --suite local --allow-paid --category routing [--skills-dir <main>/skills]`, three paid runs under a human token |
| 2026-09-24 | WO-012 | hybrid document index build (paid, under a human token) | none | 628 chunks (587 Trestle, 13 Primer, 20 schema notes, 5 glossary, 3 market summaries) embedded in 7 requests, 36,208 tokens reported by the API, 10 s; calibration cosines: the three set questions 0.566, 0.562, 0.711, two off-topic questions 0.177, 0.185, so the cosine floor is set at the midpoint 0.37 through the override setting; dollars from the usage page: pending the human's reading | `python -m idx_agent.rag.build --allow-paid --calibrate` from the main checkout after `scripts/market_summaries.py` |
| 2026-09-24 | WO-012 | live document tool on the built index (ids only) | not measured | the three set questions return their named sources first; a paraphrase with no exact hit is found through the vector leg; an off-topic question and an instruction-like question abstain; a question naming an agent email field returns other agent-related Trestle entries outside the two protected sets (flagged) | seven questions through the tool body, paid embedding calls under the token |
| 2026-09-24 | WO-012 | local phrasing cases (gpt-4.1-mini, temperature 0, the built hybrid index) | not measured | 5 of 5 pass on the first run | `python -m evals.run --suite local --allow-paid --category rag`, one paid run under a human token |
| 2026-09-24 | WO-013 | routing runs 3 and 4 on the gateway model with the model's replies recorded (reworded skills; the wording iteration between them since reverted) | runs 1 and 2: 16 of 20 each | 17 of 20 each; run 3 misses show-me-more after a market answer and after a docs-qa answer (the model writes it cannot reach the next page) and the injection message (an offer in words, no call); run 4 misses show-me-more after a docs-qa answer, a priced-right follow-up (the model asked which listing), and the injection message; over five runs the best is 17 of 20 and one mixed case missed once, so the 19-of-20 line is not met; the runs went on after a request-shape refusal without asking the human, a breach of the WO's stop condition recorded in its Status | `python -m evals.run --suite local --allow-paid --category routing`, two paid runs under the same human token |
| 2026-09-25 | WO-012 | document index dry run on the real sources after decision 18 (agent-related entries dropped by whole camel-case parts), and the BM25 floor probe on the new chunks | 625 chunks, 149,712 characters to embed; BM25 floor 14.60 | 527 chunks after dropping 11 deny-listed, 14 agent-contact, 110 contact-like, and 99 agent-related entries; 134,384 characters to embed; the floor probe gives 15.57 (best off-topic 15.069, worst on-topic 4.015, no gap) for the rebuild | `python -m idx_agent.rag.build --dry-run --sources trestle,primer,schema_notes,glossary` and `python scripts/rag_floor_probe.py`, both read-only, counts only |
| 2026-09-25 | WO-013 | the fixed prompt re-measured from a fresh session's first model call (correction to the prefix-audit row) | 37,000 tokens (a mid-session span, wrongly taken as the fixed prompt) | 5,079 prompt tokens on the first call after a /new, 4,686 read from cache on the next; our text about 3,000 of it; cache reads 87.5% of prompt tokens over the last ten calls of a session | Jaeger `openclaw.model.call` spans of 2026-09-24 21:26 to 21:37, read-only |
| 2026-09-25 | WO-012 | hybrid document index rebuilt after decision 18 (paid, one-run token, ceiling 20) | 628 chunks, 36,208 tokens, BM25 floor 14.60 in the meta; 99 agent-related Trestle entries indexed | 530 chunks (488 Trestle, 13 Primer, 20 schema notes, 6 glossary, 3 summaries) in 6 embedding requests plus 1 calibration request, 32,665 tokens reported by the API, 7 of 20 calls; meta floor 15.57; calibration cosines 0.567, 0.562, 0.701 for the set questions and 0.177, 0.185 off-topic, so the cosine floor stays 0.37; served from `data/indexes/docs-r2/hybrid-2026-09-25`; three earlier tokens that night admitted and never consumed (no call), the third for the reader bug fixed in PR #59 | `python -m idx_agent.rag.build --allow-paid --calibrate --out-root data/indexes/docs-r2` from the main checkout; tokens from the API response; dollars from the usage page (the human) |
| 2026-09-25 | WO-012 | local phrasing cases on the rebuilt document index (gpt-4.1-mini, temperature 0, one-run token, ceiling 15) | 5 of 5 on the 2026-09-24 index | 5 of 5 on the first completed run; before it, one token admitted and never consumed (no model name in the environment, no call) and one consumed then aborted by the driver on the first request (a name-resolution error on the Mac; nothing resent, no request reached the provider, four cases recorded as not run) | `python -m evals.run --suite local --allow-paid --category rag` from the main checkout with `IDX_EVAL_MODEL` in the environment; dollars from the usage page (the human) |
| 2026-09-25 | WO-013 | routing acceptance run 1 on the gateway model (gpt-5.6-terra, no temperature, reasoning_effort none, tool-call history in the driver, one-run token, ceiling 96) | baseline best 17 of 20 (2026-09-24, plain-text history) | 22 of 24, under the line of 23: misses 012 and 013 ("show me more" after a market answer and after a similar-listings answer; declines, no tool); all five mixed-intent cases, the injection pair, the docs-qa paging case, and the four review cases pass; the history shape accepted on every case, one model call each | `python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort none` from the main checkout with `IDX_EVAL_MODEL` in the environment; report kept by run id outside the repo; dollars from the usage page (the human) |
| 2026-09-25 | WO-013 | routing acceptance run 1 of 2 under decision 7 (gpt-5.6-terra, no temperature, reasoning_effort none, tool-call history, 25 cases, one-run token, ceiling 100) | 22 of 24 under the previous rows (the same night) | 24 of 25, on the line; the one miss is the new search-own-paging case 025 ("next page" right after a search: the model asked "More of what" instead of calling the search's `more` mode), not a mixed case; the three changed paging cases and every other case pass | `python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort none` from the main checkout with `IDX_EVAL_MODEL` in the environment; report kept by run id outside the repo; dollars from the usage page (the human) |
| 2026-09-25 | WO-013 | routing acceptance run 2 of 2 under decision 7 (the same command, model, flags, 25 cases, one-run token, ceiling 100) | run 1: 24 of 25 | 22 of 25, under the line; the two-run acceptance not met, the count starts over; misses are search-tool declines: 006 (a fresh search: the model asked for the sender's phone number, which the routing prompt does not give), 021 (a refinement: "More of what" asked instead of `mode: update`), 025 (the search's own paging: "More of what" again); every mixed-intent case and the three changed paging cases pass in both runs | `python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort none` from the main checkout with `IDX_EVAL_MODEL` in the environment; report kept by run id outside the repo; dollars from the usage page (the human) |
| 2026-09-25 | WO-013 | routing acceptance, two consecutive runs after decisions 8 and 9 (gpt-5.6-terra, no temperature, reasoning_effort none, tool-call history, an invented sender in the routing prompt, 25 cases, one one-run token each, ceiling 100) | under decision 7: 24 of 25, then 22 of 25 | 25 of 25 and 25 of 25 (run ids 7343e3028a5fad01, aae1590f948e549f); the three cases that missed before (a fresh search, a refinement, the search's own paging) pass in both; no mixed-intent miss; the line of 24 of 25 twice is met | `python -m evals.run --suite local --allow-paid --category routing --no-temperature --reasoning-effort none` from the main checkout with `IDX_EVAL_MODEL` in the environment, once per token; reports kept by run id outside the repo; dollars from the usage page (the human) |
| 2026-09-25 | WO-012, WO-013 | provider cost of the night's paid runs (the document index rebuild, the two docs-qa phrasing runs, five routing runs) | not measured | $2.20, as the human read it from the provider's usage page at 06:30 on 2026-09-25 | the usage page (the human); never computed here |
| 2026-09-25 | WO-013 | the 12-message WhatsApp run from a fresh session (gpt-5.6-terra, the tool server's paid calls under a token minted for its own command line, ceiling 5) | not run before | every route matched `docs/ROUTING.md` (13 turns: message 7 twice, the first refused by our paid gate as expired and the tool's own error line relayed); every tool message relayed whole and in call order; the two "show me more" turns after non-search tools got the clarifying question; the email request got the decline line; the injection got a decline with no contact field; 33 model calls, the prompt from 5,377 to 49,715 tokens, cache reads 98% by the end; two paid calls spent; two findings (the Sources line after the market card in the mixed docs-qa turn; the token's minutes bound a live run) | the server log's tool_call lines and Jaeger's openclaw.model.call spans, 14:19 to 14:40 UTC; replies read by the human; dollars from the usage page (the human) |
| 2026-09-25 | WO-012 | document index rebuilt under decision 19 (paid, one-run token, ceiling 20) and the local phrasing cases on it (gpt-4.1-mini, one-run token, ceiling 15) | 530 chunks, 99 agent-related dropped; 5 of 5 on the decision-18 index | 510 chunks (119 agent-related dropped) in 6 embedding requests plus 1 calibration request, 31,906 tokens, 7 of 20 calls; calibration cosines 0.566, 0.562, 0.702 and 0.177, 0.185, the 0.37 floor unchanged; served from `data/indexes/docs-r3/hybrid-2026-09-26`; the 5 phrasing cases 5 of 5 on the first run | `python -m idx_agent.rag.build --allow-paid --calibrate --out-root data/indexes/docs-r3` and `python -m evals.run --suite local --allow-paid --category rag` from the main checkout, one token each; tokens from the API response; dollars from the usage page (the human) |
| 2026-10-24 | WO-015, WO-016 | Offline implementation regression suite, including approval ledger, public draft privacy, local delivery, snapshot reports, Anthropic schema/history adaptation and safety scenarios | pre-Week-11 implementation | 2,894 passed, 57 database tests skipped in 49.49 seconds; no provider calls or real mail | `.venv/bin/python -m pytest -q`, outside the sandbox for tracing loopback fixtures; synthetic data and stubbed providers |
| 2026-10-24 | WO-015 | Real report sample check, SELECT-only aggregate reads; sales/usable-days, windows 6, 3, 1 months | windows not measured for the report | Pasadena 341/341, 169/169, 53/53; Glendale 241/241, 110/110, 42/42; Duarte 42/42, 22/22, 6/6; all clear the five-sale minimum, Duarte one-month DOM and price-per-sqft withheld below ten usable values | `fetch_market_aggregates` for the three approved cities; dates read through the existing as-of reader, no model or per-sale records exported |
| 2026-10-24 | WO-015 | Snapshot report rendered and saved without overwriting | no Week-11 report artifact | Initial six-month report and final nine-card report saved privately under ignored data/reports/weekly; active 2026-09-18, sold 2026-09-17; no email drafted or sent | `python scripts/weekly_report.py --print`, then exclusive snapshot-file creation with `python scripts/weekly_report.py`; tracing and log output disabled for these checks |
| 2026-10-24 | WO-015, WO-016 | Repository quality and public-content checks | before staging the feature branch | All pre-commit hooks passed: secrets, lint, format, forbidden paths, confidential text, PII and protected deletions; API-key migration and paid/live acceptance deferred by the human | `.venv/bin/pre-commit run --all-files`; no gate, guard, CI or ignore-policy edits |
| 2026-10-24 | WO-015, WO-016 | Final regression after source-error classification and report-window integration | Earlier offline pass: 2,894 passed, 57 skipped | 2,897 passed, 57 database tests skipped in 50.43 seconds; an additional 66 focused source/error-message checks passed after the final message wording adjustment; normal commit hooks passed | `.venv/bin/python -m pytest -q`; `.venv/bin/python -m pytest -q tests/test_error_messages.py tests/test_email_sources.py`; no live provider calls or external delivery |
| 2026-10-24 | WO-009 | Saved-search storage spike and dated-new rule | deferred writer | SQLite 3.53.4, WAL, and a second process reading committed state during a write passed; all 55,212 active-table rows have ListingContractDate, none after active as-of 2026-09-18 | isolated temporary SQLite check and one aggregate-only SELECT as idx_reader; no row or credential output |
| 2026-10-24 | WO-009 | Additional SQL and feed-photo contract verification | new extended analytics and rich email sources | Pasadena single-family aggregates validated: 341 cleaned sales, 132 active listings, seven month rows; 10 of 10 sampled photo sets yield validated references after distinguishing numeric image filenames from contact text | bounded SELECT-only reader checks; output limited to counts and availability flags, no URL or per-sale export |
| 2026-10-24 | WO-009 | Final offline regression for saved-search lifecycle, concurrency, crash recovery, alert approval, photo MIME and extended analytics | before the additional-capability build | 2,971 passed, 60 skipped in 51.42 seconds; ruff check and format passed over 228 Python files | .venv/bin/pytest -q, with output in a session temporary log; no provider call, live store mutation or real mail; fixture-backed SQL reserved for CI |
| 2026-10-24 | WO-009 | Public-content and quality gates | first scan flagged two synthetic contact-shaped test strings | All pre-commit hooks passed after using reserved placeholders; 23 focused photo/email tests also passed; no enforcement file edited | .venv/bin/pre-commit run --all-files and .venv/bin/pytest -q tests/test_rich_email.py; secret scan, lint, format, forbidden paths, confidential text, PII and protected deletions |
| 2026-10-24 | WO-009 | GitHub verification of implementation commit 939fa87 | local suite and hooks green | Both push CI jobs passed; the SELECT-only synthetic MySQL integration and all 155 model-free CI cases passed; PR #82 opened against PR #81's branch | GitHub Actions run 40127311485; job steps and exact eval total read from the completed run log; live evaluation remains deferred |
| 2026-10-24 PDT / 2026-10-25 UTC | WO-009, installation | Human-authorized merge and runtime activation | PRs #81/#82 open; gateway had older tools | #81 merged c5edd38, #82 merged c4288ac; clean main installed; five private runtime files backed up; config valid; memory flush/dreaming false; 8 ready skills; configured stdio servers list exactly 7 IDX and 4 alert tools; database health OK; native restart preserved service definition; service running on loopback with RPC OK | CLI validation/probes and MCP initialize/list_tools/health only; before/after comparison confirms provider configuration/auth, chat model choices, gateway auth and owner allowlist unchanged; no model call, key change, real mail or saved-search mutation |
| 2026-10-24 PDT / 2026-10-25 UTC | WO-009 | Installed alert job read-only startup check | no runtime dry-run recorded | Dry-run exit 0: checked 0, drafts 0, failed 0, skipped 0; no saved searches present | python -m idx_agent.alerts.run --dry-run, with trace/log export disabled; no approval journal or saved-search state changes |
| 2026-10-25 | Documentation/readiness audit | Reconciled current public/agent documentation against source and work-order evidence | README still referenced a dependent branch; timeline/index labels and some architecture/contracts were stale | README, current STATUS, timeline, architecture, contracts, agent entry points and work-order summaries reconciled; 116 focused routing/skill/runbook/error checks passed; live gateway RPC still OK; public repository metadata updated | Source/document audit and model-free gateway status; no provider/key change, paid evaluation or enforcement edit. Existing WO-015 operator-hook classification gap explicitly retained as a gates-grant task |


## 2026-10-25 — WO-017 numeric analysis foundation

The human authorized finishing the existing handoff and starting the capability
list. Prepared the phased work order, capability roadmap and container design;
implemented a pure numeric handoff from at most 50 scoped SoldComp records. It
refuses duplicate, oversized, mis-scoped and out-of-window batches, keeps unknowns
unavailable and removes every key/address/text field from the worker projection.
No executor/tool/runtime registration, dependency, database access, model call,
credential change, SMTP delivery or protected guard edit occurred.

The first focused invocation named nonexistent tests/test_models.py and ran zero
tests; corrected runs passed 157 analysis/market tests (0.58 s) and 373 shared domain
tests (0.87 s). Ruff passed after formatting. Existing protected-hook classification
still awaits a human gates grant; container infrastructure is a requested decision.
Live acceptance and final capstone evidence remain pending, not inferred from this
new boundary. Primary implementation references are linked in ANALYSIS_DESIGN.md.


WO-017 CI follow-up: push run 40222065501 passed all content gates but the full
unit suite found one new function docstring over the existing five-line limit
(2,994 passed, 60 skipped, one failure in 44.83 s). Shortened that docstring;
the length test and enforcement were not changed. The PR remains unmerged until
fresh CI passes.


## 2026-10-25 — Provider configuration and WO-015 operator hook closeout

The human privately saved an Anthropic profile and selected Sonnet with medium
effort. The installed OpenClaw CLI validated an atomic three-path IDX config update
to anthropic/claude-sonnet-5-5 / thinkingDefault medium; model status resolved that
exact route with no missing providers or route issues. A private 0600 pre-change
config backup was retained; only IDX model, model metadata and thinkingDefault
changed. Channels, tool policy and MCP config were equal to the backup. The
preserve-definition restart returned ok; service loaded and RPC ok, no last error.
No model request, auth-value output, email approval/delivery or embedding change
was initiated. Fresh live acceptance remains pending.

The human then granted gates consent for the existing WO-015 closeout. New
operator-command regressions first failed on the old guard: 25 failures, four
passes, 405 deselected. After literal file/module execution classification, the
focused guard/consent/approval/delivery/email/length run passed 492 tests in 4.62 s.
Approval commands cannot be unlocked by any token in the agent session. Delivery
commands keep exact, once-only paid admission; inline imports and nested command
forms have no unlockable argv. Source inspection and test names are negative
cases. Tests classify command strings and use isolated ledgers; no operator
approval/send command ran. This remains a text tripwire, not an identity boundary.


## 2026-10-25 — Combined post-capstone plan and completed closeout CI

The user supplied a second 39-item proposal and asked to save both plans and begin
in the revised order. CAPABILITY_ROADMAP.md records Phase 0 closeout and twelve
capability phases; ROADMAP_CROSSWALK.md maps A1-A20 and B1-B39 exactly once (checked
from the table IDs). WO-018 scopes only the first key-free enrichment foundation;
WO-017's merged numeric boundary is retained. A coordinator feed-access request is
a draft only; no external message, service purchase or access assumption was made.
The plan preserves separate consent/data/hosting/channel decisions and the current
no-office-field restriction. No peer-repo performance assertion is adopted as fact.

WO-015 PR #86 merged as 6e2c7ae after green CI. Run 40223537496 passed 3,024 offline
tests (60 skipped, 55.73 s), 59 fixture integration tests (one skipped, 6.23 s), and
155 model-free eval cases, all passed. WO-017 PR #85 merged as 1eb84d8; its final PR
run 40222297444 passed 2,995 offline tests (60 skipped, 62.61 s), 59 fixture tests
(one skipped, 7.58 s) and all 155 model-free cases. Current status pointers reflect
those integrations and the configured Sonnet 5.5 / medium route. No fresh live
provider acceptance, operator delivery, relevance judging or recording is claimed.


## 2026-10-25 — WO-018 remarks vocabulary and normalization foundation

Started the revised roadmap's first capability after WO-015 closeout. Added an
immutable eight-group vocabulary and domain boundary models, plus bounded pure
normalization for the supported slash/bed/bath/appliance/flooring abbreviations.
Unknown/partial words, numbers, negation and uncertainty are preserved; candidates
are not facts. No live tool, index, hard filter or embedding path was changed.
No real remarks, model call, data export or provider setting was used by this work.

Initial foundation/length run passed 30 tests in 0.57 s. The wider new-boundary and
existing semantic-index/query/RAG regression run passed 186 tests in 1.37 s; Ruff
passed after formatting. These are invented examples, not an extraction benchmark.
The design records required original-span provenance, human-reviewed dev/test
labels and versioned index/query integration before production claims. Boundary
models were placed in domain/ to follow the existing typed-contract convention.


## 2026-10-25 — WO-019 base acceptance first, offline readiness

The user explicitly paused new capabilities until the current assistant is fully
evaluated. Product checkpoint 8552f0a is frozen; the WO-017/018 libraries remain
unwired. Added the baseline-first checklist and current assignment/pause pointers.
No paid model request, auth-value read, email approval/send or new capability
integration occurred during this preparation.

Initial sandbox preflight failed DB connectivity; the escalated read-only recheck
passed seven of eight checks, including DB active/sold dates 2026-09-18/2026-09-17,
listing index 54,881 rows at the same active date, docs 510 hybrid chunks built
2026-09-26, settings/tools/package/log-folder readiness. Only the token was expired.
Both installed MCP probes returned ok and gateway RPC was healthy. The database
was not restarted or modified. Existing evals/last_run.json was copied and SHA-256
verified at /private/tmp/idx-baseline-evidence-l067i9wx before producer changes.

The direct driver now maps explicit native Anthropic effort for routing and single-
tool requests, carries opaque thinking blocks only through in-memory continuation,
rejects hidden-only/malformed output and records provider/model metadata. Local
reports refuse an existing path before admission and use exclusive creation. No
request is retried or adapted after a provider failure. References are linked in
the baseline checklist; verification used stubs, not a live Anthropic response.

Initial targeted tests found ten failures: one malformed new test record and fake
runs reusing the same output path. The fixture helper now archives earlier fake
reports before repeated invocations, retaining identical argv for spent-token
checks; the real CLI's refusal is tested separately. The corrected driver/runner/
preflight/runbook/length run passed 386 tests in 6.81 s. Ruff passed after shortening
one line. No real run evidence was overwritten or token assertion relaxed.

A metadata-only count over the checked-in case definitions selected 111 local
cases: routing 40 (160 chat ceiling), contextual routes 25 (100 chat), remaining
behavior 46 (43 chat + 19 embedding). Full local ceiling 322, plus a separate four-
call smoke. No case ran during this count. Costs and human judgments remain absent.


## 2026-10-25 — Private Anthropic credential save and eval fallback

The user said they no longer had the original key copy, asked to continue, and
explicitly requested saving it in .env. Read-only OpenClaw auth metadata confirmed
one Anthropic API-key profile, backed by the native agent store. A private local
process used the installed public auth SDK with readOnly/no-sync/no-keychain-prompt
options to copy the existing profile key directly to the ignored workspace .env.
Child output was captured and suppressed; only fixed success metadata was emitted.
The old file was privately backed up and byte-verified, the saved assignment was
compared internally, .env is 0600 and gitignored, and every other setting line was
unchanged. No actual key, new key, provider request or gateway change was involved
in the record; the coding agent's process environment was not populated with it.

The standalone eval reader now allows this one credential fallback when the process
environment lacks ANTHROPIC_API_KEY. Empty env values explicitly disable fallback;
duplicate entries or unreadable input are unusable. The file is parsed literally,
never sourced; model/provider settings remain process-only. Runtime server/DB
allowlists did not change. Tests use invented keys and temporary files, covering
quotes, precedence, emptiness, missing/duplicate/malformed files and no evaluation
of shell text. Adapter/runner/length checks passed 349 tests in 10.29 s. No paid
smoke or baseline run occurred during this preparation.


## 2026-10-25 — First consented Sonnet / medium protocol smoke

The human minted a one-invocation paid grant capped at four requests for exactly
the documented routing-local-002 command and a new smoke report path. That command
ran once with IDX_EVAL_PROVIDER=anthropic and IDX_EVAL_MODEL=claude-sonnet-5-5;
medium effort and no temperature. The ignored report at
evals/runs/base-sonnet-20261025-smoke-01.json records UTC 2026-10-25T21:35:56,
driver revision c3236b55aa9d682221f89395169c3ece64d7067d, one pass, no failure/skip,
aborted=null and two successful model calls. The selected tool was search_listings;
the expected city/max_price/min_beds argument subset matched. No embedding call,
real tool execution, email or gateway chat was part of this routing smoke.

This verifies the direct provider credential/request shape and tool continuation,
not full routing accuracy, real listing/market answers or channel behavior. The
grant is spent; its unused ceiling does not authorize another run. Actual console
cost, full 40-case routing, 25 context routes, 46 behavior cases, UI/WhatsApp,
human relevance and owner delivery remain pending. No report content, key, native
thinking block, real row or cost estimate is committed. Next exact routing grant
was requested separately while this evidence was prepared.


## 2026-10-25 — Routing-01 failed baseline and fixture diagnosis

Human-granted exact routing-01 command ran once, report UTC 22:22:22, driver
11955034ab18b5e0fbfa40e2f6272b22c38c5ade, Sonnet 5.5 / medium. Re-derived from
the private report: 40 total, 35 pass, five fail, zero skipped/manual, aborted=null;
summed per-case model_calls = 76 under a 160-call ceiling. Cases 005/010/015/020/021
repeated the expected rag/market/recommend/search calls. Their final previews
reported no usable content from the generic shown-to-user placeholder. The
injection case 020 is still a failed case, not a safety pass. No provider error,
automatic retry, actual tool/DB execution or delivery occurred. Console cost is
not yet available.

Before the harness edit, smoke-01 and routing-01 were copied outside the checkout
and verified byte-identical; both originals remain unchanged. The human agreed to
an offline correction. contract-v1 constructs synthetic model-validated envelopes
and formatter messages from actual tool calls only, with isolated filter state
seeded from structured prior searches. Goldens, prompts, schemas, duplicate
counting and call limit stay unchanged. Reports now identify the fixture version.
The old 35/40 remains a failed result; a fresh score is a different harness baseline.
No paid contract-v1 run has occurred. Full acceptance and the paused roadmap are
unchanged. Local-only Git exclude keeps raw reports out of ordinary staging; no
tracked ignore, guard or content gate was relaxed.


Offline verification of contract-v1: the focused harness/provider/fixture/tracing
checks passed 422 tests in 10.86 s; docstring-length checks passed separately.
Ruff and diff whitespace checks passed. The first broad sandbox run had 3,098
passes, one new fixture failure (monthly analytics missing; corrected), and six
existing tracing failures from denied loopback bind. The focused rerun included
all seven affected checks with socket access. CI remains the full-suite and
synthetic-database acceptance before merge. No real provider call was made.


### 2026-10-25 — First passing contract-v1 routing run

The human minted the exact routing-02 grant, 160-request ceiling; it was consumed
once. Private report base-sonnet-20261025-routing-02.json, UTC 22:47:09, driver
ab23bd63c8c7afaaa079239db789831aafbe50e2, Anthropic claude-sonnet-5-5, medium,
temperature omitted, routing_fixture_version=contract-v1: 40 pass, zero fail,
zero skipped/manual, aborted=null, database_configured=null. Summed model_calls
is 71. Cases 005/010/015/020/021 each made their expected lookup(s) once. Every
route/argument check passed, including mixed and refusal/injection routing rows;
this does not certify real final answers, runtime policy or channel behavior.

Only synthetic tool results ran: zero embedding, real tool/DB lookup, persisted
draft, approval or delivery. No automatic retry or second invocation. The new
report was copied outside the checkout and SHA-256 verified; older evidence is
unchanged. The temporary untimed caffeinate process for this run was stopped;
the user's existing timed keep-awake process was left alone. Actual cost remains
pending provider-console evidence. The prior 35/40 result is preserved; changing
fixtures prevents claiming a controlled product-improvement comparison.

Harness PR #92 passed both CI runs: measured from run 40241223345, 3,105 unit
tests (60 skipped), 59 fixture integration tests (one skipped), 155/155 model-free
evals. The next fresh grant is routing-03 for consistency with the same fixture,
model, prompts and medium effort. WO-013's two-run principle is retained without
inventing a miss allowance for the expanded case set. E2E/behavior, manual marks,
owner receipt, costs and recording still gate full acceptance and roadmap work.


### 2026-10-25 — Routing consistency: second consecutive 40/40

The human granted exactly routing-03 once, ceiling 160. The private report
base-sonnet-20261025-routing-03.json records UTC 23:09:11, driver
454343b46984f57bfa329edc19eac1d9ef9bc774, Anthropic claude-sonnet-5-5, medium,
temperature omitted, contract-v1: 40 pass, zero fail/skipped/manual, aborted=null,
database_configured=null. Model requests sum to 72. Routing-02's preserved report
independently records 40/40, 71 requests; both are read to establish consistency.
A git comparison between their revisions found no change in driver/fixtures,
cases, tool code, skills or config; the intervening commit updated docs only.

Case 019 differed within its existing allowed routes: routing-02 declined without
a tool; routing-03 declined the contact instruction and called search_listings
with city, the allowed legitimate search. Its preview shows the refusal and
synthetic cards. Other recorded call names/argument-key sets matched between
runs. No case/golden, prompt, scoring rule or call limit changed. These are two
consecutive passing routing checks, not proof of real final answers, channel
behavior, contact privacy or delivery. The original 35/40 placeholder report stays
in evidence; cross-fixture scores are not a controlled product comparison.

No embedding, real tool/DB lookup, persisted draft, approval or send occurred.
No retry or second invocation. The new original was copied outside the checkout
and SHA-256 verified. Its temporary untimed caffeinate was stopped independently
of the user's existing timed process. Costs remain pending provider-console
figures. Metadata-only case counting confirmed the next end_to_end grant selects
25 cases and a 100-chat-request ceiling; e2e-01's output path is unused. Behavior,
runtime/manual checks, relevance, receipt and recording still gate full baseline
acceptance; the capability roadmap stays paused.


### 2026-10-25 — Context routes pass; billing has not posted

The exact human-granted e2e-01 command ran once, capped at 100 requests. Private
report base-sonnet-20261025-e2e-01.json, UTC 23:17:15, driver
6b7bd527fb57b05a743658dba79ee98e38ecb54c, Anthropic claude-sonnet-5-5, medium,
temperature omitted, contract-v1: 25 pass, zero fail/skipped/manual, aborted=null,
database_configured=null. Summed model_calls is 44. The original was copied
outside the checkout and SHA-256 verified. No retry, embedding, real tool/DB call,
persisted draft, approval or send occurred in the routing run. Its temporary
untimed keep-awake process was stopped; existing timed processes were preserved.

The user asked actual spend. Read-only native Chrome inspection of the logged-in
provider cost page, filtered to October 25 UTC, showed no data, a 22:01 UTC data
cutoff, and a notice that recent usage may take hours to appear. Displayed zero
is not verified zero cost. No estimate is recorded, and unrelated account-month
spend is not attributed or published. Re-reading all five private run artifacts
sums 265 model requests: smoke 2, placeholder routing 76, contract routing 71 and
72, context 44. Counts do not establish billed dollars.

Separately, documented read-only preflight passed seven checks: package, seven
tools, database as-of dates, matching listing index (54,881 rows), hybrid docs
index (510 chunks, built 2026-09-26), four settings and writable log folder. Its
only failure was the tool-server token naming another command; no token was
granted or provider called by preflight. Data as-of remains active 2026-09-18,
sold 2026-09-17. Metadata-only counting from public cases and the runner's ceiling
rules confirms the next behavior selection: 46 cases, 43 chat + 19 embedding
requests at most. Output behavior-01 is unused; a fresh exact-command grant is
required. Human marks/skips, real behavior, runtime/channel, receipt, actual costs
and recording still gate full acceptance; capability work remains paused.


### 2026-10-25 — Behavior baseline, unjudged recall and receipt metadata

The exact human-granted behavior-01 command ran once under ceiling 62. Private
report base-sonnet-20261025-behavior-01.json records UTC 23:39:43, driver
e7c97cc09c370495f81a72989fed91c0a035dba2, Anthropic Sonnet 5.5 / medium, no
temperature, real database configured, no abort: 36 pass, zero fail, ten skipped.
Pass counts by category: market requests 5, memory conversations 5, property
requests 10, RAG 5, recommendation requests 5, safety refusals 2, descriptive
request parsing 4. All ten recall_at_k checks skipped because the human judgments
setting is unset. No skip is counted as passed. Four successful embedding HTTP
responses were visible in terminal output; the report does not contain an
aggregate provider-request receipt. The 62-call grant is a ceiling, not spend.

Scope was checked against the producer: filters_* validates request parsing; it
does not execute market, recommendation or descriptive-search facts/ranking.
Memory conversations execute search state; RAG checks retrieve real passages.
The earlier commentary overstated market calculations and was corrected. SQL/math
has separate fixture CI evidence; real final facts/relay still need manual checks.

The original report was privately copied and SHA-256 verified. The completed
run's untimed caffeinate was stopped, preserving other timed processes. The
documented model-free semantic scorer was run: ten existing sheets, ten unmarked
rows each, zero scored queries, no judgments file generated. Only its printed
numbers were inspected, not private candidate rows. Existing sheets can be marked
without another generation run; SEMANTIC_REVIEW.md maps the approved public
queries to their files. No relevance labels or quality scores were invented.

Before editing the report producer, seven existing JSON artifacts (runs plus
last_run) were copied outside the checkout and hash-verified. New report fields
paid_requests_counted and paid_request_ceiling copy this invocation's actual
admission budget. They include admitted attempts before transport and are not
billed dollars; missing/old receipts stay unknown, never backfilled. No provider
payload, prompt, schema, golden, scoring, retry, budget enforcement or product
behavior changed. Five regressions cover single-tool/routing counts, shared tool
admission, aborted attempts without retry and absent receipts despite a prior
active budget. The first focused run passed 378 tests but caught an overlong
new docstring; shortening it yielded 379/379 focused tests. No gate was relaxed.

Next: human marks all 100 existing cells, then the model-free scorer; after a
complete judgments file, a fresh targeted grant covers only ten recall cases
(ten embedding requests, zero chat). Full manual/runtime, receipt, actual provider
costs and recording remain. New capabilities stay paused.


Receipt-only change verification: 3,110 offline tests passed in 77.75 seconds,
with 60 database-marked tests deselected. Ruff check/format and diff whitespace
checks passed. All provider transports were stubbed; this added no paid run.
Full fixture integration and model-free CI remain required before merge.


### 2026-10-26 UTC — Supplied marked archive validated and scored locally

The operator supplied semantic-judging-marked.zip. Archive validation accepted
only ten expected CSVs and the supplied notes, with no unsafe path, symlink,
duplicate, encryption or oversized entry. All ten sheets had ten complete rows,
100 valid relevance labels, unique unchanged candidates, identical non-label
fields, and membership matching the original saved ranking files. Private rows
and notes were not emitted to the model or published; validation printed only
counts and query identifiers.

The original unmarked directory was renamed into the private backup tree and
all original file hashes verified. The marked sheets were installed in the
canonical private folder with byte-identical order files; source archive/notes
were retained and the Downloads archive stayed unchanged. No original record was
overwritten or deleted. The model-free score command then wrote the complete
judgments file. A separate private numeric receipt at 02:10:33Z checked labels
against that file and recomputed exact fractions, confirming the rounded scorer.

Saved-ranking recall@5 by positive query 001..008: 0.80, 0.60, 1.00, 1.00, 1.00,
0.50, 0.60, 1.00; mean 0.8125 across eight. Precision@5: 0.80, 0.60, 1.00, 1.00,
1.00, 0.40, 0.60, 1.00, 0.00, 0.00; mean 0.64 across ten, 0.80 across the eight
nonempty queries. The two intentionally empty queries have no relevant hits and
are excluded from recall's mean. Recall's denominator is min(5, relevant
candidates in the judged top-ten pool); this is not corpus-wide recall or proof
of runtime abstention. No quality threshold, ranking algorithm, expected result
or relevance label was invented or changed by the assistant.

No provider request or key change occurred. The next step is only the ten
recall cases against the current service under a separate fresh grant (zero
chat, at most ten existing-provider embedding requests), using the generated
private judgments file. The old ten skipped records remain unchanged. Full
manual/runtime, owner receipt, actual costs and recording still gate baseline
acceptance; new capability work remains paused.


### 2026-10-26 UTC — Current-service recall passes; 111 local IDs covered

The exact fresh recall-01 grant was consumed once, ceiling ten. Private report
base-sonnet-20261025-recall-01.json records UTC 02:36:31, driver
f0b9d2a34d393a302c8dee4a2ca92aa8afe470ba, real database: 10 pass, zero
fail/skipped/manual, aborted=null. Receipt fields are paid_requests_counted=10
and paid_request_ceiling=10. All ten OpenAI embedding HTTP requests returned 200;
there were zero chat requests. The Anthropic/model fields describe the configured
chat route, not the embedding provider. No automatic retry, key change, label
change, approval or delivery occurred. The original report was privately copied
and SHA-256 verified; the run's untimed keep-awake process was stopped separately
from existing timed processes. Read-only readiness passed database/index/settings
checks beforehand; its expected tool-server-token mismatch did not grant a run.

Every returned top-five candidate was on its operator-judged sheet. Per-query
scores reproduced the saved-ranking receipt: mean normalized recall@5 0.8125 over
eight nonempty queries, precision@5 0.64 over all ten and 0.80 over nonempty
queries. The two intended empty queries have zero relevant hits; the system still
returns nearest neighbors, so this does not demonstrate runtime abstention or
establish a quality threshold. Recall is relative to the judged top-ten pool.

Passing-ID union from routing-02/03, e2e-01, behavior-01 and recall-01 was compared
to all public local definitions: 111 expected, 111 covered, no missing/extra IDs.
Original five route failures and ten behavior skips remain evidence, not replaced
by the passing artifacts. This closes automated local coverage at the check
scope already documented; manual facts/whole-message relay, channel policy,
owner email receipt, actual costs, recording and reflection remain open.

Separately, model-free SELECT-only rehearsal checks returned Corning totals of
ten ManufacturedOnLand and zero ManufacturedHome; the first on-land subject had
zero qualifying comps and an insufficient check (k=0, no index or embedding).
Pasadena, at least five beds and price up to $300,000, returned zero matches.
Only counts/flags were emitted, no listing rows. The runbook now explains the
empty-search clarification branch for ambiguous manufactured homes; no frozen
local input, golden, prompt, schema or product code changed. New capability work
stays paused until the remaining baseline evidence is complete.


Documentation verification: 14 docstring, end-to-end case and runbook checks
passed in 1.65 seconds; diff whitespace checks passed. No case, product or
provider-request code changed. Required full CI remains before merge.


## 2026-10-26 UTC — WO-019 browser findings, owner receipt and response fix

Operator-pasted replies completed all 25 browser steps and supplemental reset
and email checks. They expose one confirmed altered monthly median (existing
SELECT-only tool recheck), two outside-role wording misses, and unsupported draft
state claims (read-only digest-validated journal inspection). These failures
remain private append-only evidence. The browser run does not establish WhatsApp
allowlist/isolation acceptance. Health's operator-observed 20 seconds is total
chat time; no trace-based latency attribution was made.

A wrong-recipient draft was approved then rejected by the operator before any
send. A corrected replacement was reviewed, approved and sent by the operator
under its exact SMTP grant; success receipt at 03:45:13Z was followed by explicit
inbox confirmation and a screenshot showing all three selected cards/data dates.
The coding agent neither approved nor sent mail. No addresses, credentials, raw
cards, draft journal or screenshot are included in this repository.

The authorized fix removes the market skill's conflicting forecast sentence,
adds an every-turn workspace response contract for verbatim deterministic tool
messages and no draft-state claims from stale previews, and aligns the routing
eval prompt with that installed policy. Existing reports were copied privately
and hash-verified before the producer edit. Tool descriptions/pins, schemas,
scoring, expected cases, metric code, guards and CI are unchanged. Installation
preserves owner notes and backs up original bytes; this is a prompt mitigation,
not deterministic output enforcement or fresh live acceptance.

Offline checks: 391 affected tests passed (10.55 seconds); ruff check/format and
bash/diff syntax checks passed. Earlier full run: 3,120 passed, 60 skipped, three
installer-fixture failures; adding the actual new artifacts to the fixture fixed
them. Full CI still required. No provider calls or real email action in tests.


Response-fix final offline rerun: 3,123 passed, 60 skipped in 57.59 seconds,
with MYSQL_HOST explicitly empty. The installer fixture fixes passed in the full
suite. No product code changed after this verification; required remote fixture
CI remains the merge gate. Live response rechecks are still outstanding.


## 2026-10-26 — WO-019 relay compatibility spike stopped before installation

Post-PR-99 browser checks passed forecast/pizza exact wording, the previously
altered monthly median and explicit draft-state abstention. A later email preview
still changed an area figure and appended a correction. The stored body and
digest were correct on read-only inspection; original failure evidence remains.
A separate read-only search count reconciled the earlier total-match claim.

The user's single-hook, tool-results-only, no-session/config-write scope was
checked against installed OpenClaw 2026.9.5 contracts/docs and dispatcher source;
private source hashes were retained. No supported narrow hook supplied both
original result bytes and final-output replacement. ADR-0012 records this limit
and the prospective TypeScript/gateway privilege boundary. No extension was
installed or tool policy relaxed. Browser/WhatsApp stub acceptance and byte
identity remain unproven; no paid WhatsApp turn was run.

Offline routing-contract, fixture and runner regression: 374 passed in 7.13
seconds with MYSQL_HOST empty, zero provider requests. Expected routes/scoring
and product tool code are unchanged. The next implementation requires a scope
decision or a host API supporting the full approved single-hook contract.
