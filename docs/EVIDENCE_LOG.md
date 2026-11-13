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


## 2026-10-26 — WO-019 two-hook offline result: browser gate failed

The user authorized two narrow hooks and autonomous offline continuation. The
uninstalled TypeScript candidate's ten Node unit/stub checks passed. The Python
wrapper and existing routing-contract/fixture/runner suite passed 375 checks in
11.00 seconds, MYSQL_HOST empty. No provider calls, live channel send, model tool
or route/schema/scoring change occurred.

A host-version-pinned probe registered both hooks with the actual installed hook
runner, injected synthetic tool/model events into the real browser live-text
handler, and stubbed transport/persistence. The WhatsApp stub inserted the exact
960-sqft block. The browser emitted a 1,240-sqft rewrite with zero outgoing-hook
invocations. This counterexample is a failed browser gate even though the probe
process deliberately asserts it and exits zero. Runtime source has no session,
config, filesystem, network or shell API calls; test-only private host imports
and temporary fixture writes are not part of the extension. No manifest/activation
or policy relaxation was added. ADR-0012 records gateway privileges and the need
for a supported pre-publication seam. The paid WhatsApp preview gate is not met.

- 2026-10-26, WO-019: human cancelled the relay and prohibited installation.
  The separate staged host checkout, package copies and patch artifacts were
  removed; the IDX relay branch remains. Stock OpenClaw has no documented
  selective forced-tool control for WhatsApp MCP calls. A separate model-side
  numeric verifier and tool-first skills are under offline verification; live
  trace coverage and the tokened WhatsApp turn remain pending.

- 2026-10-26, WO-019 model-side path: 440 targeted offline tests passed. A
  synthetic MCP preview preserves its stored 960-sqft body, and the numeric
  verifier flags a 1,240-sqft rewrite without logging values. A follow-up review
  fixed a beds/square-feet label swap. The live trace cannot supply both full
  texts; no live post-check or paid WhatsApp success is inferred.

- 2026-10-26, WO-019: the human authorized the five-skill rollout, granted a fresh
  token, and supplied one WhatsApp reply after gateway restart. All five skill
  paths matched the reviewed files; configuration and IDX MCP probe passed. The
  displayed draft matched the preceding five search cards, including the fifth
  card's 960-square-foot value. No approval, email send, byte-identity proof,
  streaming proof or automatic live trace comparison is claimed.

- 2026-10-26, WO-018 Phase B: after the user directed work to move on from the
  merged WO-019 model-side change, drafted annotation rules and 26 invented
  split examples. Thirty-two focused annotation/foundation tests passed. No
  real feed, provider call, model accuracy or runtime integration is claimed.

- 2026-10-26, WO-018 Phase B: independent synthetic-example review identified
  and corrected a person/style ambiguity and a planned/current distinction.
  The expanded annotation, foundation and fixture suite passed 53 tests; no
  real-data annotation quality is inferred.

- 2026-10-27, WO-018 Phase B: bounded synthetic-case validation and exact-match
  per-facet/polarity counting passed 58 focused tests after independent review.
  The source marker is self-declared; no provenance or model accuracy is claimed.

- 2026-10-27, WO-018 Phase B: 214 synthetic annotation, index, query and
  retrieval regression tests passed with MYSQL_HOST empty. No provider or
  real-feed access was used.

- 2026-10-27, WO-018 Phase B: reviewed single-split synthetic aggregation and
  refusal of mismatched case sets; 216 annotation/index/query/retrieval tests
  passed. No model, real feed or runtime behavior was exercised.

- 2026-10-27, WO-018 Phase B: drafted the real-data pilot decisions without
  selecting, reading, exporting or labeling real remarks. Existing row caps,
  deny-lists and human approval remain in force.

- 2026-10-27, WO-018 Phase B: reviewed the synthetic-only group split planner;
  220 annotation/sampling/index/query/retrieval checks passed. The input label
  is not provenance proof and the ordering hash is not anonymization.

- 2026-10-27, WO-018: the local viewer loaded in headless Chrome and passed a
  synthetic selection/save smoke test. The private-label scorer was tested on
  invented cases with mismatches and missing/duplicate labels. No real remarks,
  provider calls or hosted service were used. Browser save-picker interaction
  and real-data workflow acceptance remain open.

- 2026-10-27, WO-018: a headless Chrome run with invented text passed selection,
  annotation, navigation and stubbed save; a synthetic desktop screenshot was
  visually reviewed. The actual save dialog and private workflow remain open.

- 2026-10-27, WO-018: the owner-authorized private remarks sample completed:
  count 250, fixed seed 20261027; development 100, held-out test 150. No listing
  keys or remark text are recorded here.

- 2026-10-27, WO-018: a separate synthetic-only rule experiment was checked on
  13 visible development examples: 5 exact matches, 5 predictions, 18 labeled
  mentions. The fixture informed the rules; this is not an independent or real-
  data benchmark. The broader offline regression passed 244 tests. No real
  remarks, provider, database query or live runtime integration was used.

- 2026-10-27, WO-018: added narrow synthetic negation, uncertainty and temporal
  templates. The visible development examples produced 12 exact matches from 12
  candidates against 18 labels; the rules were tuned on those examples. The
  expanded offline regression passed 257 tests. No independent/real-data
  accuracy, provider use or runtime integration is claimed.

- 2026-10-27, WO-018: the experimental normalization alignment helper was
  independently reviewed and tested on invented offsets, repeated expansions,
  Unicode and numeric backreferences. The broader offline suite passed 269 tests.
  Per-span scan cost remains unmeasured for bulk integration; no live index changed.

- 2026-10-27, WO-018: the synthetic extractor used reviewed offset alignment for
  an invented `W/D` claim, preserving the original span. The offline regression
  passed 273 checks; development matching remained 12 of 18 labels. No real data,
  provider or live index was used.

- 2026-10-27, WO-018: a narrow numeric candidate experiment matched the visible
  invented numeric examples it was developed against; 51 focused tests passed.
  This is neither real-data nor held-out extraction quality evidence.

- 2026-10-27, WO-017 step 1: the analysis projection reader passed 69 db tests
  (one existing real-data skip) and 155 of 155 ci evals against the regenerated
  synthetic fixture on Python 3.11 and MySQL 8.4, plus 3,264 unit tests. The
  2-second statement deadline cut a deliberately slow statement. No real data.

- 2026-10-27, WO-017 step 2: worker-output parser and trusted figure checks passed
  3,384 unit tests on Python 3.11 (62 database skips). Hand-valued statistics and
  stdlib references check every kind; fabricated, missing and wrong-sign values are
  refused. No worker, model or container was run.

- 2026-10-27, WO-017 step 3: trusted chart data (scatter, binned median with
  groups under 3 suppressed, histogram) passed 3,266 unit tests on Python 3.11
  (62 database skips) with hand-computed bins and captions. No image is rendered
  and no renderer dependency is added.

- 2026-10-27, WO-017: resumed after WO-019; ADR-0013 proposes a Docker worker
  (pinned slim Python image, no network, read-only root, dropped capabilities,
  memory/PID/CPU limits, 10 s deadline) and a matplotlib renderer. A local Docker
  engine ran one `--network none` container from the pinned image; no isolation
  claim is made until the hostile-code tests exist and pass.

- 2026-10-27, WO-017: probe of ADR-0013's proposed flags on a local Linux Docker
  29.9 engine: network, root-filesystem write and daemon socket unavailable; host
  environment absent; uid 65534; 600 MB allocation killed (137); forks stopped at 63.
  Eight hand-run snippets, not the required test suite; macOS not covered.

- 2026-10-27, WO-020: draft work order for SQL-checked measurement, a loopback-only
  local-model adapter and a latency benchmark; an independent review found seven
  harness mismatches, all corrected in the draft. No case, code or run exists yet.

- 2026-10-27, WO-018: aggregate-only structural validation of the owner-reviewed
  labels: 250 cases (100 dev, 150 test), 1,293 categorical and 378 numeric
  annotations; dataset identity and exact spans matched. No model-quality score
  was computed and no private text or keys were logged.

- 2026-10-28, WO-017 step 4: the container worker passed 29 real-engine isolation
  tests (network, read-only root and input, noexec scratch, no host environment or
  daemon socket, no capabilities, seccomp on, OOM at 600 MB, PID limit, endless
  loop, output floods, in-container deadline surviving a killed host, parallel
  isolation, missing image) on a local Linux Docker 29.9 engine with a freshly built
  image; 3,582 tests passed on Python 3.11 with containers required. Three probes
  were shown to fail with the flags removed. macOS Docker Desktop is not yet tested.

- 2026-10-27, WO-018: the first authorized dev extraction stopped after one
  request; the API reported 3,312 input and 1,309 output tokens. The old driver
  retained neither its response nor a validation diagnosis. No predictions or
  real-data score were produced; no private text or keys are recorded here.

- 2026-10-27, WO-018: offline recovery regression replayed an invented failed
  response from an owner-only debug file and verified quote alignment, sanitized
  field/rule diagnostics, and continuation. The original failed response was
  not retained, so its cause and a replay of it remain unavailable. No new
  provider request or real-data score was made.

- 2026-10-28, WO-017 step 5: the in-worker renderer drew all three chart kinds as
  960x600 PNGs in about 1.3 s per cold run, byte-identical across separate
  containers; the host PNG check refused hand-built bombs, garbage IDAT, text and
  profile chunks. 3,708 tests passed on Python 3.11 with the container suite
  required (local Linux Docker). Charts were inspected by eye; no real data used.

- 2026-10-28, WO-017 step 6: the end-to-end analysis (fixture reader, container
  worker, figure checks, trusted chart data, in-worker PNG render, MCP text plus
  image) ran against the synthetic fixture on MySQL 8.4 with a freshly built image:
  4 of 4 figures verified, 50 of 60 eligible sales disclosed, chart attached.
  3,741 unit and 70 db tests passed on Python 3.11 with containers required; 155 of
  155 ci evals passed. No tool registered; no real data, provider or channel used.

- 2026-10-27, WO-018: owner-directed dev-only categorical overlap with exact
  numeric scoring yielded hybrid micro F1 87.1% on the existing predictions;
  exact-span micro F1 remained 47.7%. No provider call or test scoring occurred.
  Results and wording-bucket counts are aggregate only.

- 2026-10-27, WO-018: the owner froze categorical case/facet/polarity overlap
  and exact numeric-value matching as the structured micro-F1 metric. Rescoring
  the existing development predictions gives 88.5% micro F1; no held-out score
  or new provider call was made. The earlier 87.1% used a different metric.

- 2026-11-02, WO-022: carried from PR #116, originally recorded 2026-10-27. The PR
  was never merged; its text is below, verbatim apart from the nesting indent. Superseded the same day by the frozen overlap metric
  (88.5% on these predictions), then dev3 (89.3%) and held-out (88.2%); see
  `docs/ENRICHMENT_CARRIED_EVIDENCE.md`.
  - 2026-10-27, WO-018: authorized dev-only extraction completed 100 requests,
    424,460 input and 43,522 output tokens, zero no-tool-call responses; 11
    diagnostics across 10 remarks. Frozen exact-span structured micro F1 on dev
    was 47.7%; the held-out test was not scored. Only aggregate evidence is
    recorded; provider-console cost remains unverified.

- 2026-11-02, WO-022: post-merge readiness reconciliation, docs only. PRs #134-#141
  are merged (main CI green at `5432dc2`, run 41568267014); nothing new is installed,
  enabled or live-verified. A line-count check of the main checkout's `.env` found no
  enabled switch (values not read). Unique evidence from the unmerged WO-018 PRs #116,
  #126, #129 and #132 was carried verbatim, each block checked byte-for-byte against the
  PR text (`git diff` of each branch against its merge base). The full offline suite on
  the branch passed: 4,269 passed, 129 skipped
  (`MYSQL_HOST= .venv/bin/python -m pytest -q -x -p no:cacheprovider`, Python from
  the main checkout's venv); Ruff clean. No paid call, install or restart.

- 2026-11-03, chore-owner-decisions-20261103: recorded the owner decisions on
  recommendations, the WO-026 omission-pilot rulings and the stale WO-018 PRs.
  - **Recommendations (WO-024).** Five answers are recorded. `condominium` is removed
    from explanation facets: two regression tests failed on the old code and pass now.
    WO-031 (feature filter on `recommend`) is drafted and not approved to build.
  - **Review policy v5.** Eight rulings are in `docs/ENRICHMENT_REVIEW_POLICY_V5.md`, which
    extends v4. The v4 file is unchanged. The builder's `verify_manifest` passes with the
    real v4 manifest on this branch, and fails on the earlier head `e28b7cc`, which had
    edited the v4 file.
  - **Ruling 8 overlay.** It is a new private file; model review, `human_review` pending.
    Of 1,110 `uncertain` labels on the six limited facets, 690 were screened read-only.
    Adding the pilot's 11 labels gave 697 read, 545 removed and 152 kept. The store was not
    rebuilt, and the overlay changes no `present` status.
  - **v5 impact estimate.** About 5,700 cue review candidates for rulings 1 to 7 (WO-018
    Status). The ruling 4 subtype split is not available from the snapshot. No re-read was
    started.
  - **Stale PRs.** #126, #129 and #132 were closed as superseded by #143; their branches
    were kept.
  - **Verification.** `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider`:
    4,464 passed, 130 skipped. Ruff is clean. PR #147's `tests/test_phase_integration.py`,
    run unchanged from a scratch worktree of this branch, passed 15 of 15.
  - No paid call, extraction, install, restart or live check.

- 2026-11-03, wo-034-extraction-v3 (WO-034 Phase A, docs only): froze the extraction v3
  research candidate before any paid call.
  - **Contract.** `docs/ENRICHMENT_EXTRACTION_V3.md`: v4 and v5 policy written into the
    prompt, one evidence span per facet decision, the 20 eligible facets, Sonnet with the
    v2 settings. Proposed new facets are listed for owner decision, not added.
  - **Frozen SHA-256** (`docs/ENRICHMENT_V3_FREEZE.json`): prompt `2e5ad2d1…4b14ad7`,
    canonical schema `91bbeb56…6f01bcb67`, request settings `c8e5ef0c…92dfb11`.
    `tests/test_enrichment_v3_freeze.py` recomputes them from the doc.
  - **Derived baseline, no new measurement.** Pooling the published v1 held-out per-facet
    counts over the 20 facets gives 452 correct / 507 predicted / 471 gold, a 92.4% micro F1.
    It is a diagnostic beside the 88.2% gate.
  - No v3 request, paid call, extraction, store build, install or activation.

- 2026-11-03, wo-034-extraction-v3 (WO-034 Phase A, owner decisions on C, D and E): docs,
  freeze and tests only.
  - **Baseline wording.** 94.69% is labelled as the historical v2 Sonnet dev score; v2.1
    Sonnet has no dev score (the only v2.1 run was Haiku at 89.66%).
  - **Re-freeze, version 2, before any paid call** (`paid_calls_before_freeze` 0). Prompt
    `2e5ad2d1…4b14ad7` became `c0dd6c74…6653cf0`; schema and request unchanged. The
    doubt-wording rule is scoped to the six ruling-8 facets and the stainless exception is
    named. Three new freeze tests failed on the version 1 doc and pass on version 2.
  - **Dev v5 relabel screen,** model review, read only. 6 proposed changes in 6 items
    (ruling 3: 1, ruling 6: 1, ruling 7: 4; all additions), 6 borderline rows, none for
    rulings 1, 2, 5 and 8. Private list `984aa72e…ddf7dd4`, manifest `9cf864ef…74cb0a3d`;
    the gold file is unchanged.
  - **Saved v2 Sonnet dev predictions** (100 of 100 dev rows) rescored with the existing
    scorer against the current gold: 342 gold, 374 predicted, 339 correct, 94.69%. A
    reproducibility check, not a result; no provider call.
  - WO-018 Status: the ~5,700-pair v5 re-read is deferred until Phase D results.
  - No v3 request, paid call, extraction, store build, install or activation.

- 2026-11-03, wo-034-extraction-v3 (WO-034 Phase A, owner decisions round three): docs
  and one new private file pair; no code change.
  - **Ruling 4 conflicts.** The subtype column decides when a direct condo claim and the
    subtype disagree; flag `ruling4_subtype_conflict`. New private list
    `v3-dev-v5-relabel-candidates-v2.jsonl` (`0ae62271…de7ac507`) with manifest
    (`db3c8528…642bd0edb`); the first list and manifest are unchanged. Dev conflict
    count: 1 (10 dev cases with a gold condominium label, 1 disagreeing subtype; 1
    unlabeled non-condominium remark with condo wording, not a claim about the home).
  - **Saved held-out predictions check** (file presence, record counts, recorded
    settings; no held-out remark or gold read): no v2.1 or v2 held-out predictions
    exist. The only saved held-out predictions are v1's, 150 records, with recorded
    counts equal to the published 88.2% run. The rescored gate is waiting on the owner.
  - **Freeze unchanged** at version 2 (prompt `c0dd6c74…6653cf0`, schema and request as
    before); the freeze test recomputes them.
  - Doubt-wording "all 20" recorded as a v6 candidate; stainless reading owner-accepted;
    token order and the dev relabel procedure written into WO-034.
  - No paid or provider call, extraction, store build, install or activation.

- 2026-11-03, WO-032: key-free supplement dry run on the real private inputs, read-only
  (`scripts/extract_enrichment_supplement.py --dry-run --data-root <main checkout>/data/enrichment`,
  run from the WO-032 worktree with the main checkout as the working directory). Every
  precondition up to the input set passed: frozen v1 files, the pinned v2.1 freeze
  manifest, the v2 prompt and schema hashes, the Sonnet dev decision, and the results
  table as the frozen full run (54,888 rows: 324 v1, 54,564 v2; approved digest; all
  batches complete; watermark `2026-09-18 06:58:44` unchanged before and after the scan;
  original source unchanged). It refused with `no_eligible_remarks`: the 321
  never-extracted IDs are all active, none has a result row, and all 321 have a NULL
  remark, so nothing can be extracted. SHA-256 digests of the results table, the effective
  store and the preflight inventory were identical before and after. No key read, paid
  token, provider request or file write.

- 2026-11-03, WO-032: supplement dry run re-run after the review fix to the presence
  check, on the same real private inputs, read-only (same command, with
  `PYTHONPATH=<worktree>/src:<worktree>`). Same result: refused with `no_eligible_remarks`,
  12 preconditions evaluated, 11 passed. Presence now counts distinct IDs: 321 of 321
  never-extracted IDs present, 321 source rows, 0 reappeared; remark state from the row the
  reader keeps: 321 NULL, 0 blank, 0 with text; 0 eligible. Output identical to the first
  run's; SHA-256 digests of the results table, the effective store and the preflight
  inventory identical before and after. No key read, paid token, provider request or file
  write.

- 2026-11-04, wo-034-extraction-v3 (WO-034 Phase A, rulings 9 to 15 and final decisions):
  docs, one test file and one new private file pair.
  - **Rulings 9 to 15** (policy v5 at `3432736f…9a75a99`, #158) written into six v3
    facet guide lines. **Re-freeze, version 3:** prompt `c0dd6c74…6653cf0` became
    `da0c34a1…f2dd1e4`; schema and request unchanged; `paid_calls_before_freeze` 0. Two
    new freeze tests failed on version 2 and pass on version 3.
  - **Policy-only dev re-screen** (dev remarks, dev gold and the policy; no predictions
    opened; no held-out remark or gold read; model review): 1 proposed change (ruling 9,
    a removal) and 1 borderline row (ruling 12). New cumulative private list
    `v3-dev-v5-relabel-candidates-v3.jsonl` (`ac586374…fbf10de3`) and manifest
    (`a9ce10d3…2c8200c3b`); `labels.json` (`6aab5483…f250ebde7`) and earlier lists
    unchanged. Cumulative on dev: 7 proposed changes, 7 borderline rows.
  - **Final decisions 1 to 5** recorded: production v2 has no held-out score; 88.2% is
    v1's all-field result against `labels.json` (`6aab5483…f250ebde7`); one sealed Phase
    D command with a shared 600-call budget runs frozen production v2 and frozen v3,
    which replaces the saved-predictions gate; `score_v2` read for the subtype mapping:
    four scoring-contract points wait on the owner.
  - The dev relabel validation command ran on the unchanged dev gold (0 rows changed,
    342 gold groups) and on invented private files only.
  - No paid or provider call, extraction phase, store build, manifest freeze, install or
    activation.

- 2026-11-03, WO-033: model review of the frozen 400-item omission pilot v2 sample.
  Branch `wo-033-model-review` from `main` `48b74ab`, carrying `95f3d2f` (accepted 1%
  weighted no-cue threshold and Kish-n_eff Wilson method) as `5887caa`. Claude agent
  sessions read 8 shards of 50 against a private rubric. The rubric covers the guide,
  policy v4, v5 and the three approved decisions: stainless, condo ruling 4 and the
  doubt-wording scope. A second read of 71 items agreed on 66 (93.0%): 40 of 40 random
  items and 26 of 31 targeted ones. The 5 disagreements were adjudicated. Recorded
  with `record --kind model` (400 of 400, every record `human_review: pending`) and
  aggregated with `aggregate`, both with `--data-root` set to the main checkout's data.
  New private, owner-only files: `judgments.jsonl` `4d0d5653…1159`, `aggregates.json`
  `bb14a396…fcbe3`, `review/adjudication.jsonl` `e8e27e35…3894`.
  - Pooled: 21/400 omitted (5.25%, 3.5-7.9%). No cue 2/240, cue 14/120, labeled 5/40.
  - **Weighted no cue: 0.56%, 95% 0.11-2.81%, n_eff 207.0.** Inconclusive against
    the accepted 1% threshold; pooled with v1: 0.50% (0.10-2.37%), still inconclusive.
  - The condo subtype check (MySQL) is not done: 2 flagged items, neither no-cue.
  - Hashes of the v2 sample and manifest, all v1 files, the ruling 8 overlay and its
    manifest, and the source and store DBs were identical before and after.
  - `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider`: 4,659 passed,
    130 skipped. Ruff is clean.
  - No paid or provider call, extraction, MySQL access, store build, overlay or label
    change, install, activation or merge.

- 2026-11-04, WO-033: uncovered-population fix (r2), owner decisions, human packet.
  Branch `wo-033-model-review`; `origin/main` still `48b74ab`.
  - Regression tests `1ea89fb` failed before the fix `02c2e64`: a facet with population
    but no cell or no sampled item was missing from both the covered and the uncovered
    population, and items without a population were dropped from n silently. Now the
    estimate and interval are on the covered facets only. Uncovered facets are listed
    with their populations and the covered share, never imputed.
  - Re-run into a new private file, `aggregates-r2.json` `bf3f15cb…a468`. No figure
    changed. The v2 design samples all 20 facets in the no-cue and cue strata. The
    weighted no-cue rate stays **0.56%, 95% 0.11-2.81%**, n_eff 207.03, covering 100% of
    the 848,575 no-cue pairs. The labeled stratum is 26.2% covered (6 of 20 facets), and
    no weighted labeled figure is published.
  - Inconclusive under the accepted 1% rule, unchanged. Published as the v2 result with
    the full interval. Pooling with v1 is a sensitivity line only. No further sample
    before WO-034 Phase D.
  - Judgments preserved (`judgments.jsonl` `4d0d5653…1159`). They are pinned to rubric
    `a5090f62…1720` and to policy V5 rulings 1-8 at `1fe7eb3`, and predate rulings 9-15.
  - Human packet, new `human-packet` subcommand `003f290`: `human/human-packet-r1.jsonl`
    `b310b740…87ff`. It holds 31 unique union items (21 omitted, 8 unclear and 5
    adjudicated, 34 before deduplication) and 20 seeded agreed items (seed
    `wo033-human-20261104`, pool 40): 51 in all.
  - Condo subtype check: the owner-run command is recorded in WO-033 Status for after
    D1. Not run; dry-run with a stub connection only.
  - Hashes of the v2 sample and manifest, all v1 files, `judgments.jsonl`,
    `aggregates.json`, the review files, the ruling 8 overlay and its manifest, and the
    source and store DBs were identical before and after.
  - No paid or provider call, MySQL query, extraction, store build, install, activation
    or merge.
- 2026-11-05, staged install, Phase 1 preparation (WO-029, WO-035; no paid call, no
  WhatsApp message). Private logs, owner-only, in
  `~/.openclaw/idx-install-backups/20261104-preflight/`:
  `owner-freeze-build-20261105T020844Z.log` and `c3-install-20261105T020953Z.log`.
  - Before any change (agent, 2026-11-04 23:55Z-2026-11-05 00:20Z): starting revision
    `9cff4bf`, clean tree; gateway pid 1441 (started 2026-10-31); config
    `openclaw.json` `8be0f042…`; no `IDX_*` switch in `.env` or the gateway environment;
    no alerts DB. Copy-only backups verified by SHA-256 (C1 copy
    `openclaw.json.pre-wo029-202611041558` and the dated preflight set, folder 700).
  - C2, manifest freeze, v5 dry run and build (run by the owner with the prepared
    script, 2026-11-05 02:08:44Z-02:08:57Z): fast-forward `9cff4bf` to R `71fb39e`
    (main CI run 41950375863 green); `ENRICHMENT_REVIEW_POLICY_V5.md` `229fdd74…`; the
    v5 manifest proposal re-generated at R byte-identical to r4 and frozen as
    `data/enrichment/effective-store-v5-manifest.json` `822811b9…8648` (600, 1279 B);
    dry run and build: v5, 54,888 listings, 545 removals (condominium 72, garage 412,
    near_grocery_mentioned 7, near_transit_mentioned 26, stainless_appliances 28), all
    from uncertain (5,358 to 4,813); present 168,333. Store
    `data/enrichment/full/effective-facets-v5.sqlite3` `ae74f3d1…6e04d8a` (600);
    StoreInfo v5, rules `2026-11-01.4`, watermark `2026-09-18 06:58:44`, 54,888;
    policy_scope "policy v5; rulings applied: 8 overlay only; rulings 1-7 and 9-15 not
    applied to stored labels". v4 store `7d9007b3…` and v4 manifest `9b066566…`
    unchanged. Pasadena solar probe against the v5 store: applied 14.
  - Read-only verification (agent, 02:09Z): the same hashes, modes and StoreInfo;
    `PRAGMA integrity_check` ok; no WAL, SHM or temp files.
  - C3 install (agent, delegated by the owner, 02:09:53Z-02:12:31Z) at R, every switch
    off: `pip install -e ".[dev]"`; `install.sh` exit 0, and its two "did not succeed"
    notes are the script's own fallback (lines 186 and 190; confirmed harmless by the
    owner, with the probes as the check); `openclaw config validate` ok; installed
    config byte-identical (`8be0f042…`), so no key changed.
  - Gateway restart (agent, 02:10:53Z): LaunchAgent restarted, new pid 47776, RPC ok.
  - Probes (agent, 02:11Z-02:12Z): `idx` 7 tools (no `bounded_analysis`) plus 4 generic
    prompt/resource entries; `idx_alerts` 4 tools, no send tool; 8 skills ready,
    `bounded-analysis` excluded; C3a off probe `False False False None None`; no
    analysis render, no chart directory, no prune job; memory flush and dreaming false;
    `demo_preflight.py --minutes 60` 7 of 8 (only `paid_token` failed: expired, as
    expected before a grant).
  - Readiness after this entry: activation Phase 1 installed at R with every switch off;
    nothing enabled or live-verified.
- 2026-11-05, live check at R `71fb39e` (owner, WhatsApp and terminal; every feature
  switch off). Owner-minted tool-server `paid` grant at 03:41Z (60 min, at most 5 calls);
  `demo_preflight.py --minutes 60` then 8 of 8. Server log since 03:41Z (events only, no
  content): `server_start` 7 tools at 03:42:40Z, then `health` 03:42:42Z,
  `search_listings` 03:43:33Z and `draft_email` 03:45:31Z. Email: draft
  `draft-46ba806db33c` (5 Pasadena listings as of 2026-09-18, digest `35bf382aa463`)
  previewed in chat with "Nothing has been sent"; the owner approved it in the terminal
  with the digest and sent it under an exact one-send SMTP grant (`send_approved.py ...
  --transport smtp`, sent 03:50:30Z); the owner confirmed inbox receipt. Week 10's health
  and draft path and week 11's approval gate and delivery are live-verified at R. Similar
  listings, recommend, document answers and mixed messages were not exercised in this
  check.
- 2026-11-05, autonomy ladder (owner decision, PR #167, branch `chore-autonomy-ladder`):
  - The project's main goal is an autonomous buyer's agent under a licensed human. Work is
    ranked by the autonomy level it moves toward (`docs/AUTONOMY_LADDER.md`, L0-L4; L5 is
    never claimed). Current placement: L1 capabilities built, L1 acceptance pending.
  - New rule: every new work order names its level (`work_orders/TEMPLATE.md`); one that
    moves no level needs an owner note (`docs/CAPABILITY_ROADMAP.md`). Roadmap Phase 3 is
    kept (valuation beneath L3 offer drafting; payment-budget search taken forward as L2
    affordability search); Phase 4 (events) follows feed access.
  - Docs only. No journey-level measure has been taken. No gate, consent or deployment
    rule changed. Nothing merged, paid for, installed or activated.
- 2026-11-05, Phase 1 paid session, procedure 1 (remark-feature search on the v5 store;
  WO-029, WO-021), STOPPED after P1-4. Revision R `71fb39e`; `IDX_ENRICHMENT_STORE` (v5)
  the only switch; gateway pid 88228, not restarted afterwards. Channel: the OpenClaw
  dashboard (Control UI, sender bucket local-dashboard, key_prefix `09f697a3`), not
  WhatsApp. Chat model `claude-sonnet-5-5`.
  - P1-0 `/new`; P1-1 passed (trace `711f4cb14f974c85`), P1-2 passed (`113d02a1a77b4faa`),
    P1-3 passed (`f613013fea234ec2`).
  - P1-4 FAILED ("Any of those with a pool too?", 04:26:35Z, trace `8e84ac5c94834523`).
    Tool call: `search_listings` mode update, pool true, features [solar] and 3+ beds
    carried, page 1; 2 rows of 2 matches. (1) Relay defect: card 2's living area was
    shown as a value that appears nowhere in the tool result, then corrected in the same
    generation; a later correction does not pass a turn (`config/IDX_RUNTIME.md`). The
    model received the result twice (2 text blocks, 6,627 chars). Model-free check of the
    preserved records with `scripts/check_relay.py`: fail, reason changed, 16 numeric
    mismatches, first at card 2 sqft, 1 value in the reply and not in the message.
    (2) Test/skill conflict: the script expected features "pool, solar"; the skill and
    tool description send "a pool" to the structured pool filter. P1-4 is not marked
    passed, now or later.
  - Session stopped: P1-5 to P1-11 and procedures 2-4 not sent.
  - Provider console: closing reading US$0.35 month-to-date November 2026, read by the
    owner at about 2026-11-05T04:36Z. No opening reading was taken, and the figure covers
    every gateway chat-model turn this month, so this session's own cost cannot be
    separated.
  - Private evidence (owner-only, dir 700, files 600):
    `~/.openclaw/idx-install-backups/20261104-preflight/p1-4-failure/`: `README.txt`
    `d2c290a5d894…`, `p1-4-visible-reply.txt` `56b76bd20e5b…`,
    `p1-4-session-turn.jsonl` `5f6e29bc0392…`, `p1-4-tool-message-reproduced.txt`
    `6e3e2e4e969a…` and `.json` `f9e23dc14844…`, `investigation-notes.md`
    `32fea6e77f63…`, `fix-demo-relay-check-output.txt` `2a8b916eb0cd…`; full hashes in
    its `SHA256SUMS*` files. Acceptance script r3 beside it,
    `PHASE1-ACCEPTANCE-SCRIPT-r3.md` `7a3d419e7d61…` (r1 and r2 kept).
  - Follow-up (owner decision 2026-11-05; branch `chore-p1-4-relay-fix`, not merged):
    P1-4 reworded to "Only homes whose listing descriptions say they have both a pool
    and solar panels." with features [pool, solar]; the skill routes explicit
    description requests to features while "with a pool" keeps pool true; a model-free
    relay check after every card turn. Procedure 1 re-runs from P1-0 in a new session
    after that fix is merged and installed.
- 2026-11-05, P1-4 follow-up after #169 merged (branch `chore-p1-4-relay-fix`, PR #170;
  no paid call, nothing installed). Appended as a new entry; the entry above is kept
  as written.
  - Layer 1 clarification: the relay check after every card turn fails a turn in which
    a number changed, even if the reply then corrects itself.
  - Digest note (owner-accepted 2026-11-05): the default-off tool-surface digest pinned
    in `tests/test_phase_integration.py` and `tests/test_phase_integration_charts.py`
    moved, `idx_tools` `7e1e85cc…` -> `8185de44…`. The only cause is the
    `search_listings` `features` parameter description, changed to match the skill: a
    request about what listing descriptions say goes to `features`, a pool included.
    The instructions digest, the tool list and the routing pins are unchanged.
- 2026-11-05, relay fix Layer 2 (branch `chore-card-relay-layer2`, PR #172; no paid
  call, nothing installed or measured).
  - Layer 2 (owner decision 2026-11-05; branch `chore-card-relay-layer2`, stacked on
    `chore-p1-4-relay-fix`, not merged, installed or measured): the card tools send one
    copy of each result (integral numbers as integers; OpenClaw 2026.9.5's mirror rule,
    `dist/mcp-content-Dj8o6nFL.mjs:113`, re-read read-only in the installed package,
    then drops the SDK text block), and each card `message` is the whole reply. Model
    input per card result, real SDK call path, synthetic fixtures, before -> after:
    search 9,933 -> 4,970 characters, market 4,645 -> 2,326, similar 3,907 -> 1,962,
    recommend 3,499 -> 1,758 (two text blocks -> one). Relay case reply shape 4 added;
    no paid call made, no token minted; the measurement plan is in evals/README.md
    "Layer 2".
  - Owner decisions on Layer 2 (2026-11-05, after the routing-04 run at `4ec99bd`):
    Layer 2 first (#170 and Layer 2 merge, a fresh routing run, the relay measurement,
    then procedure 1 from P1-0); the measurement cap is raised to 160 chat calls with
    all four reply shapes; after Layer 2 is installed procedure 1 requires
    `reason=exact` on every card turn (`scripts/check_relay.py --require-exact`).
    Decisions only; nothing run.
  - Review follow-up on Layer 2 (2026-11-05, no paid call): a value such as 1e-6 is
    spelled `1e-6` by the SDK's pydantic_core and `0.000001` by JavaScript, so its card
    still reached the model twice. The card tools now write their SDK text block with
    `mcp_server/wire.javascript_json` (ECMA-262 number and string spelling); the
    structuredContent values are unchanged. Model-free checks: 23,017 values against
    node's `JSON.stringify(JSON.parse(w), null, 2)`, 0 mismatches; the 1e-6 and 9.9e-6
    regression cases fail without the change and pass with it.
- 2026-11-06, routing-05 and relay measurement 01 at `3001c69` (Layer 2 installed, every
  switch off; owner-minted tokens; Anthropic `claude-sonnet-5-5`, effort medium,
  temperature omitted; reports gitignored, local only).
  - Serving update to `3001c69` and off-probe clean, 2026-11-06T04:09Z: no analysis
    variables, analysis and chart delivery off, no analysis render, `idx` 7 tools and
    `idx_alerts` 4 without `bounded_analysis`, 8 skills, `check_relay.py` has
    `--require-exact`.
  - routing-05 (`evals/runs/base-sonnet-20261105-routing-05.json`, run 04:13:57Z):
    40 pass, 0 fail, 2 skipped (041 and 042, analysis off); 72 of 160 calls. Same as
    routing-04 at `4ec99bd`; case 019 took its other accepted route (no tool call).
  - Relay measurement 01 (`evals/runs/relay-measure-01.json`, sha256 `4b4a75a8…9822`,
    run 04:18:36Z, five runs, 80 of 160 calls): reply shapes 1 to 4, 0 relay errors in
    5 judged replies each (20 of 20 `exact`). Description routing raw: 5 pass, 15 fail
    (cases 002 to 004 in every run).
  - Checker defect: `evals.run._match_subset` compared the validator's sorted
    `features` tuple with the case file's list, so a correct call outside `mode:
    update` always failed. Fixed in `29888ee` (branch
    `chore-description-features-compare`). The raw report is kept unchanged.
  - Offline re-judgment (`evals/rejudge.py` at `8704231`, model-free, no paid call;
    `evals/runs/relay-measure-01-rejudge-01.json`, sha256 `12fbb69f…3c5f`): tied to the
    raw report's sha256 and the fix commit, case file the same blob as at `3001c69`.
    All 15 failures verified against their original expectations (single-step route,
    only `features` differing, expected keys sent, failure reproduced, corrected check
    passing): description routing corrected 20 of 20, raw 15 failures.
  - Provider console: opening reading US$3.75 month-to-date, read by the owner at about
    2026-11-06T04:10Z, before both runs; the closing reading is pending.
  - Provider console, closing reading: US$11.37 month-to-date, read by the owner at
    about 2026-11-06T04:42Z. Session cost from the two readings: US$7.62 for routing-05
    (72 calls) and relay measurement 01 (80 calls) together; the console does not split
    the two runs, and the figure includes any other use of the same account between
    04:10Z and 04:42Z.
- 2026-11-06, Phase 1 paid session under script r6 (WO-029 procedure 1, fresh session from
  P1-0; owner-run; stopped at P1-4). Not accepted.
  - Approval: the owner approved r6 (sha256 `10e4993c…fd41`) and its bounded session (up to
    3 hours, 24 model turns, US$10 of spending since the opening reading) at about
    2026-11-06T06:26Z. Serving update `3001c69` -> `0b0c48c` (`serving-update-0b0c48c-r2.sh`:
    every step's failure is an explicit stop and the off-probe values are asserted; 17
    offline harness scenarios passed before use): `openclaw.json` byte-identical
    (`8be0f042…`), new gateway process, off-probe as expected. Preflight (gate 6b and
    section 7, `phase1-preflight-r6.sh`): one v5 store line, the other feature switches
    absent, store `ae74f3d1…`, `--require-exact` present, C3a clean, procedure 1 offline
    set 238 passed and 0 failed, readiness usable, Pasadena solar applied 14.
  - Live turns (owner-sent, dashboard session `d9fc1ee6`), each card turn exported
    read-only from the agent database and checked with `scripts/check_relay.py
    --require-exact`:
    P1-1 `abe05b43bbcf4cf0` pass exact; P1-2 `3e44c4ce4cdc46c3` pass exact; P1-3
    `33ef79cbbadf4e4f` pass exact; P1-4 `cb8c22c393af4ca0` FAIL, reason changed, 1
    mismatch, first at card 3 (`number`). `tool_blocks=1` on all four, so Layer 2's one
    copy was in effect.
  - P1-4: routing was correct (Pasadena, at least 3 beds carried, `features: [pool, solar]`,
    no structured `pool`, feature filter applied). The reply matched the tool message
    line for line except one card line: card 3's year built was replaced by card 2's.
    A model relay defect of the P1-4 class again, caught by the check. Layer 2 reduces
    what the model reads but cannot stop it from retyping a value; WO-036 (#171, Layer 3,
    proposal) addresses that.
  - Stop: r6 rule (any relay result other than `status=pass reason=exact`). No resend,
    no further message; P1-5 to P1-11 and procedures 2 to 4 not sent. 4 of 24 model
    turns, one `/new`. Rollback of procedure 1 only on the owner's instruction (none
    given at this entry). No Phase 2 activation.
  - Provider console, both records kept as given by the owner (month-to-date basis):
    - opening record 1: US$11.37 at about 2026-11-06T06:35:21Z;
    - opening record 2: US$11.26 at 06:35:49Z, given by the owner as the corrected
      opening ("more like 11.26");
    - closing: US$11.38 at about 06:46:52Z; last turn 06:40:00Z.
  - Reported console difference: US$0.12 (closing US$11.38 minus opening record 2,
    US$11.26). It is the reported console difference, not a verified session cost.
  - Unexplained discrepancy, retained: US$11.37 (the closing reading recorded above for
    routing-05 and relay measurement 01, and opening record 1 here) and US$11.26 (opening
    record 2) differ by US$0.11 with no explanation on record. Neither reading is
    corrected here; the entry above stands as recorded.
  - Private evidence (owner-only, dir 700, files 600):
    `~/.openclaw/idx-install-backups/20261104-preflight/p1-rerun/` (13 files, hashes in its
    `SHA256SUMS`; the P1-4 values are only in its `-values-PRIVATE` file), the update and
    preflight logs beside it.
- 2026-11-06, WO-037 (`wo-036-whatsapp-channel-skeleton`, the branch name assigned by the
  workflow): offline Path A skeleton, `extensions/idx-whatsapp-channel/`, on a fake
  transport. Nothing installed, enabled, configured, linked or sent; no paid call.
  - Read-only SDK survey (OpenClaw 2026.9.5 at `~/.npm-global/lib/node_modules/openclaw`,
    stock `@openclaw/whatsapp` 2026.9.5 under `~/.openclaw/npm/projects/openclaw-whatsapp-290d7f7427`),
    file and sha256-12 of each dist file cited in the design and the critique:
    `config-normalization-shared-Btqp-2KT.mjs` e9ea9129fdff (deny before every other
    rule, :82-88; bundled-channel-configured for origin bundled only, :113-116);
    `plugin-policy-id-C9JZrwYv.mjs` de4b1b175c7a (policy id = lowercased plugin id);
    `config-state-BxYVV2MR.mjs` 9c7da903e40f (deny ids trimmed + lowercased);
    `loader-runtime-load-CdQ5OcQq.mjs` 91180d699f64 (api.config = cfg snapshot
    :1208-1213; register throw -> status error :1231-1252; registerChannel absent in
    cli-metadata :2140-2147; registerChannel requirements :2730-2746; first registrant
    wins :2955-2960); `loader-shared-BulwGaGf.mjs` 918b140f8fcd (failed plugin logged and
    skipped :146-169); `core-C4NLht8i.mjs` 27613ead41de (defineChannelPluginEntry always
    registers); `deliver-prepare-BRk062mg.mjs` 03f60ee0178f (normalizePayload called with
    `{ payload, cfg, accountId }` :573-577; handler fields :560-600);
    `deliver-BTRDSDzt.mjs` 20dfe713e587 (no_visible_payload :552-556; not_sent ->
    adapter_returned_no_send :130-134, 646-651; adapter throw :683-709);
    `delivery-queue-reconciliation-BrTkthQM.mjs` f630274472eb (normalizePayload again
    :45); `reply-dispatcher-Dt2lN800.mjs` 3786ba69e33f (result classification :107-118;
    await deliver :354; failed-deliver and onError :383-390; fallback through the same
    deliver :435-439); `channel-inbound-5tLZDTZk.mjs` 01d751292c14 (deliver wrapped by
    normalizeOutboundReplyPayload :105-132); `reply-payload-YT0WRAgp.mjs` bbac3d7a1a42
    (reply payload keys :99-123); `message-action-runner-CtRkNUaS.mjs` c9d4a67d5815
    (message-tool payload shape :342-347; actions bypass :340-420);
    `server-cron-B7KzTVIW.mjs` 82fbc81e3f96 (:326-345); `heartbeat-runner-run-BPqPC60M.mjs`
    4667a9bbcf0c (:970-985); `channel-outbound-send-TTutjIBc.mjs` aeb19641999c (:15-57);
    `registry-loader-BMKPNnWY.mjs` 428a1c180ce3 (:7-15); `server-channels-DqMot1BG.mjs`
    2eb7b2dcf788 (startAccount ctx :361-369; restart supervisor :198-205, 745-800;
    isConfigured -> skipped :603-618); `target-normalization-DOGcNvsV.mjs` 83272c1a54c2
    (:67-74); `session-key-CPlMYURm.mjs` 39bd60e3065a; `discovery-C8SwFp3U.mjs`
    2e591cbbdaf8 (manifest + index.mjs is loadable :1177-1180); `plugin-auto-enable.materialize-IpOcPSgc.mjs`
    22f0fa98fbdd; docs `plugins/manifest.md` fe0cf8bbca03, `plugins/manifest/surfaces.md`
    c0cc9e27f93e, `plugins/sdk-runtime.md` 82fafaeff5e8, `plugins/sdk-channel-outbound.md`
    d60f2781e49c, `plugins/sdk-channel-inbound.md` 3a20ca45088b,
    `plugins/sdk-entrypoints/define-channel-plugin-entry.md` 81893704c6ca,
    `plugins/manage-plugins.md` 5caa93720894; stock `openclaw.plugin.json` 1ffc4c4cadab,
    stock `monitor-BblvzLpX.mjs` 6a6ca5dcd340, stock `channel-CSclZYjU.mjs` f7f7ddf74828.
    Correction recorded: the design's "not installable without package.json" claim was
    wrong; a directory with a manifest and `index.mjs` is loadable via
    `plugins.load.paths`; the skeleton is not loaded because no config names it.
  - Tests on the branch: `node --test` on the three files, 55 pass, 0 fail (the whole
    `extensions/` directory with the WO-019 TypeScript spike: 65 pass). Full suite
    `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider`: 5335 passed, 131
    skipped, two of them the new manifest check and the Node wrapper. Ruff check and
    format clean. Gates `pii_scan`, `confidential_text`,
    `forbidden_paths` pass on the 21 new or changed paths.
  - Fail before, pass after (scratch copy, not committed): with the gate's withhold branch
    in `outbound.mjs` replaced by a raw-text fallback, `channel.test.mjs` fails 8 of 21
    (verifier-throws in both modes, deadline, malformed, the behavioural single-call-site
    table, no-record, end to end, second instance); against the shipped gate 21 of 21 pass.
- 2026-11-06, WO-037 review fixes (`wo-036-whatsapp-channel-skeleton`): ten code-review
  findings on the skeleton, dispositions in the work order's Status. Nothing installed,
  enabled, configured, linked or sent; no paid call.
  - Correction to the entry above: "5335 passed, 131 skipped, two of them the new manifest
    check and the Node wrapper" was misleading. The two new pytest tests were among the
    passed, not the skipped: `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider
    -rs tests/test_whatsapp_channel_skeleton.py` -> `2 passed`, no skip (Node v26.9.0
    present, so the wrapper ran the Node suite).
  - Runtime changes: the gate snapshots the verifier result (each field read once) before
    the well-formedness check and the seal; the verifier reads the resolver's `text` once;
    `PARTIAL_TOKEN_RE` no longer matches bare `card:` in prose; figures are `\p{N}` runs;
    turn ids are `randomUUID` (peer message id is metadata); ingress keeps four turns per
    peer and the inbound `deliver` binds to its own turn via `forTurn`. The single-call-site
    source test now requires every `transport` identifier outside four listed declaration
    sites to be an immediate `transport.<member>(` call.
  - Tests: `node --test` on the three files, 62 pass, 0 fail (55 before). Fail before, pass
    after (scratch copies, not committed): the new tests against HEAD's runtime files fail
    8 (3 in `verifier.test.mjs`: `\p{N}` figures, `card:` prose, resolver single read; 5 in
    `channel.test.mjs`: getter/Proxy verdicts, ingress `forTurn`, end to end, re-sent
    message id, in-flight reply); a copy of `outbound.mjs` with
    `const { sendText: rawSend } = transport; ... await rawSend(...)` and another with
    `transport.sendText.call(transport, ...)` each fail the source test (16 pass, 2 fail)
    where the previous test passed them. Wrapper: 2 passed. Full suite
    `MYSQL_HOST= .venv/bin/python -m pytest -q -p no:cacheprovider`: 5335 passed, 131
    skipped (464 s). Ruff check and format clean. Gates `forbidden_paths`, `pii_scan`,
    `confidential_text` pass on the 12 changed paths.
  - Not fixed: `.github/workflows/ci.yml` has no `actions/setup-node` step, so the Node
    tests run in CI only if the runner image ships Node 20+ (gates consent needed to edit
    CI; recorded as owner decision 15 and in the README).
- 2026-11-06, WO-037 turn binding revision (`wo-036-whatsapp-channel-skeleton`, PR #180):
  the owner's instruction of the same day: bind sends to their trusted originating turn;
  require verified card tokens whenever that turn called a card tool, keeping greetings
  and clarifications on ordinary turns; reject incomplete release verdicts; regressions
  for all three. Nothing installed, enabled, configured, linked or sent; no paid call.
  - Runtime changes: `ingress.record` returns a frozen turn handle mapped by identity (a
    WeakMap private to the instance) to the one entry it was minted for; `forTurn` answers
    only for that handle, key and entry; the channel keeps the handle in its `deliver`
    closure and gives `runInbound` a string turn id plus `noteToolCall`; `sendText`
    withholds `untrusted-turn` with nothing sent for an unrecognised handle or any
    `turnId` in the context, and binds callers with neither to the peer's current turn.
    Records carry a monotonic `cardToolCalled` (set by `markCardTool` or
    `markCardToolForSession`, never cleared, never inherited); verifier rule R1b withholds
    `card-turn-requires-tokens` for any non-token text on such a turn; `CARD_TOOLS`
    mirrors the server's `ONE_COPY_TOOLS`; `VERIFIER_VERSION` is "2".
    `isWellFormedVerdict(value, inputText, inbound)` accepts a release only with one of the
    three rules, `viaCard` matching the rule, no `reason`, no thenable, a valid record and
    rule-consistent text; on a card turn only rule `card`. Review fixes in the same
    revision: every `sendText` context field is read once, a non-string or empty `to` is
    `bad-destination` (nothing sent) and the transport receives the canonical peer the
    record was checked under (a getter or stateful `toString` on `to` could previously have
    the verifier check one peer and the transport deliver to another, present since
    873f58c); `@lid` is kept as its own peer namespace rather than folded onto `+<digits>`.
  - Deviation from the pinned design, recorded in the work order Status: a `deliver` that
    sent `SAFE_TEXT` reports `visibleReplySent: true` with `withheld.reason`, since a
    not-visible result would make the dispatcher send its fallback after `SAFE_TEXT`.
  - Review: four lenses (bypass, fail-closed, regression quality, docs) raised 10 findings;
    an independent refutation pass confirmed 6 (one medium: the double `to` read; five
    low) and rejected 4; all 6 fixed, dispositions in the work order Status.
  - Tests: `node --test` on the three files, 85 pass, 0 fail (62 before). Fail before, pass
    after, reproduced by the orchestrator in a scratch copy with the runtime `.mjs` files
    of 873f58c and the new tests: 27 fail, 58 pass (`verifier.test.mjs` 4, `channel.test.mjs`
    17, `host.test.mjs` 6). Pytest wrapper `tests/test_whatsapp_channel_skeleton.py`: 2
    passed (Node 26 present). The full Python suite was not rerun locally (no `.py` file
    changed); CI's result is recorded with the PR. Gates `forbidden_paths`, `pii_scan`,
    `confidential_text` pass on the 12 changed paths. No protected path touched.
- 2026-11-06, WO-037 owner decisions 16 and 17 (`wo-036-whatsapp-channel-skeleton`, PR
  #180): the owner decided that card turns are marked from the host's trusted tool-call
  event before execution (so failed card calls are covered) and that the channel-minted
  handle is required for this skeleton, with the latest-turn fallback removed. Nothing
  installed, enabled, configured, linked or sent; no paid call.
  - Runtime changes: `ingress.current` removed; `forTurn` with a trusted handle is the
    only record read. `sendText` withholds `no-turn-handle` (nothing sent in either mode)
    when the context carries no handle, even if the peer wrote seconds ago; any `turnId`
    or an unrecognised handle stays `untrusted-turn`; everything that reaches the transport
    is bound to a trusted turn. The turn-object seam is renamed `beforeToolCall`;
    `createBeforeToolCallHandler(ingress)` is the hook-shaped function the install PR
    registers with `before_tool_call` (`index.mjs` registers nothing; the real event shape
    is untraced). Review fix flagged for the owner's nod under decision 16: `isCardTool`
    accepts the host's namespaced, cased or padded spelling of a `CARD_TOOLS` name
    (`idx__search_listings`, per ADR-0003) as well as the bare name, since an exact match
    would have left every real card call unmarked; over-marking is the accepted direction.
  - Consequence recorded as new owner item 18: proactive sends (message tool, cron,
    heartbeat, CLI, alert delivery) are withheld over this channel until a handle-bearing
    path exists.
  - Review: two lenses raised 4 findings (one medium: exact tool-name matching; three
    low); all confirmed and fixed, dispositions in the work order Status.
  - Tests: `node --test` on the three files, 94 pass, 0 fail (85 before). Fail before,
    pass after, reproduced by the orchestrator with the runtime `.mjs` files of 3213f63 in
    a scratch copy and the new tests: 25 fail (all assertions, no TypeError), 69 pass
    (`verifier.test.mjs` 1, `channel.test.mjs` 19, `host.test.mjs` 5). Pytest wrapper: 2
    passed. Full Python suite in CI, recorded with the PR. Gates `forbidden_paths`,
    `pii_scan`, `confidential_text` pass on the 11 changed paths. No protected path touched.
- 2026-11-07, WO-037 blocking mark (`wo-036-whatsapp-channel-skeleton`, PR #180): the
  owner approved the bare and namespaced IDX tool names, deferred item 18 (proactive sends
  stay withheld), and required a successful trusted mark before a card tool executes,
  with execution blocked and the affected reply withheld when correlation or marking
  fails. Nothing installed, enabled, configured, linked or sent; no paid call.
  - Runtime changes: records carry a monotonic `toolCallBlocked`; verifier rule R0b
    withholds `blocked-tool-call` for everything on a tainted turn, tokens included, and no
    release is well-formed against a blocked record (`VERIFIER_VERSION` "3"). Both seams
    return decisions and never throw: `{ block: false, marked }` to allow, or
    `{ block: true, reason, tainted }` with reason `no-turn-for-session` (session-keyed
    handler, nothing marked), `mark-failed` (per-turn seam, turn evicted or expired) or
    `handler-error` (any throw or a non-string tool name). A block taints first:
    `blockOpenTurns` for the session-keyed handler (the affected turn cannot be
    identified), `blockTurn(handle)` for the per-turn seam. The ingress applies one TTL to
    every handle lookup (review fix: the per-turn seam had marked an expired turn as a
    success). The fake host skips execution on a block. Nothing is registered with the
    host; the host's block directive is untraced (install-PR item).
  - Review: two lenses raised 6 findings; 5 confirmed and fixed (one medium, the expired
    turn), 1 rejected. One confirmed finding is documented rather than closed: a session
    key naming another peer's open turn is accepted as a successful mark (host trust;
    pinned by BM-9). Orchestrator check: the host hook fires for every agent session, so a
    card tool from a session with no WhatsApp turn is blocked and taints every open
    WhatsApp turn; pinned by BM-10 and raised as owner item 19.
  - Tests: `node --test` on the three files, 109 pass, 0 fail (94 before). Fail before,
    pass after, rerun by the orchestrator with the runtime `.mjs` files of c6ecdbd: 30
    fail, 79 pass, all assertions (`verifier.test.mjs` 6, `channel.test.mjs` 23,
    `host.test.mjs` 1). Pytest wrapper: 2 passed. Gates `forbidden_paths`, `pii_scan`,
    `confidential_text` pass on the 12 changed paths. No protected path touched.
- 2026-11-07, WO-037 host trace for owner item 19 (`wo-036-whatsapp-channel-skeleton`,
  PR #180): read-only trace of OpenClaw 2026.9.5 at `~/.npm-global/lib/node_modules/openclaw`.
  - Method: host `dist/` code only, with no config, session store, credential or log read.
    Four tracers, one skeptic per tracer re-reading each citation, and a synthesis. The
    orchestrator then re-read the load-bearing lines itself. Paths below are relative to
    `dist/`, with sha256-12 in brackets.
  - Hook contract. A plugin registers with `api.on("before_tool_call", handler, opts)` and
    the handler is awaited before execution (`api-DArLOVCi.d.ts` 5623-5641, 6027-6083
    [7decea02a45e]). The runner reads `block`, `blockReason`, `params` and
    `requireApproval`; `block` is sticky and stops later handlers (`hooks-Jjh3afyP.mjs`
    972-993 [94e01df2379f]). A block becomes a veto, `blockToolCall` replaces execution,
    and the model receives the reason as a tool result without the run aborting
    (`agent-tools.before-tool-call-ya9NNSXc.mjs` 3004-3010, 3538-3548 [39e6ae403ad4]). The
    hook is fail-closed on a throw or a timeout (default 15 s)
    (`hook-runner-global-CN2-D2Rq.mjs` 88-100 [8a9a236d7874]; hooks 382-385, 622-654).
    Omitting the matcher matches every tool; a matcher that names the wrong tool skips the
    hook (hooks 29-55).
  - Context and channel metadata.
    - The context is an allowlist: `agentId`, `sessionKey`, `sessionId`, `runId`,
      `toolCallId`, `channelId` and an optional `requester` (before-tool-call 2881-2893).
      The event carries `toolName`, `params`, `runId` and `toolCallId` (before-tool-call
      2996-3003). The `turnSource*` fields are internal to approval routing.
    - `requester` is built on the agent-tools path, where `accountId` is the agent's own
      account and `senderId` is the inbound sender (`agent-tools-lIZNv5a0.mjs` 831-862
      [9e71b09811fa]). The built-in harness's bundled-MCP hook context has no `requester`
      (`builtin-openclaw-C7-lQJ2Z.mjs` 19682-19698 [97435362096a]).
    - No inbound message id reaches the hook. The run id is
      `params.opts?.runId ?? crypto.randomUUID()` (`agent-runner.runtime-DRp6jmuv.mjs`
      3243 [f3f4732fc5ee]). A queued follow-up mints a fresh one (same file 6657-6658).
    - `requester.channel` can read `whatsapp` on heartbeat, isolated cron, subagent and
      admin-origin dashboard runs, which inherit the persisted route
      (`effective-reply-route-DVxTotdi.mjs` 125-153 [0b131b2feef3];
      `chat-origin-routing-IBVBZAzW.mjs` 96-139 [79501da5f78a]).
  - Session keys.
    - The default dmScope is `main`, and every DM then shares `agent:<id>:main` with the
      dashboard Home (`session-key-CPlMYURm.mjs` 377-402 [39bd60e3065a]).
    - Under `per-channel-peer` the key is `agent:<id>:<channel>:direct:<peer>`. The
      runtime-policy resolver returns it unchanged unless the inbound context sets
      `RuntimePolicySessionKey` (`runtime-policy-session-key-7my6r2RV.mjs` 18-68
      [108dd8409a71]).
    - The repo already sets `per-channel-peer` (`config/openclaw.idx.json5`).
  - Isolation.
    - Block bookkeeping is keyed by run and tool-call id and read only by tool-end
      accounting (before-tool-call 81-119).
    - Loop-detection history is filtered by run id (`tool-loop-detection-BrL3lNT9.mjs`
      218-220 [c80849caf997]), and detection is off unless configured
      (`tool-loop-detection-config-CKIQC-fJ.mjs` 1-14 [ff0b753b3b3c]).
    - Runs on different keys use separate `session:<key>` lanes (`lanes-CVttd5qX.mjs` 2-10;
      `command-queue-BYhr_fMP.mjs` 294-306).
    - No coupling was found between one session's blocked call and another's reply
      dispatcher. This is a negative result, so it rests on the paths read.
  - Skeleton discrepancies, for the install PR:
    - The handler admits on a session key (BM-9).
    - It taints every open turn on a refusal (BM-10).
    - It returns `reason` where the host reads `blockReason`.
    - The fake host hard-codes the `per-channel-peer` key shape.
  - Untraced:
    - whether WhatsApp run ids reach gateway or Control UI clients
    - whether a steered turn keeps a plugin-supplied run id
    - whether the WhatsApp sender id is transport-authenticated
    - the effective live dmScope and queue mode (config was not read)
    - which path serves the `idx__*` card tools at runtime
    - how the main wrapper renders a hook failure
    - the other harnesses
  - Outcome: owner item 19 recorded as an installation prerequisite with two install-PR
    regressions (binding, isolation) and three open points. No runtime change, nothing
    installed, registered or configured, no paid call.
- 2026-11-07, WO-037 run binding (`wo-036-whatsapp-channel-skeleton`, PR #180, revision 6
  on top of d6daad2): offline implementation of owner decision 19 (a), (b), (c).
  - Runtime: a channel-minted run id per inbound passed as `replyOptions.runId`, confirmed
    only by `onAgentRunStart(<issued id>)` (which returns `undefined`), ended when
    `runInbound` settles; card calls admitted per run id (`ingress.admitCardCall`, the only
    marking path) and refused individually with `{ block: true, blockReason, reason }`,
    no taint; the session-keyed mark, the global taint and the per-turn seam removed;
    verifier "4" (R0b `unbound-turn`, R1 `card-without-trusted-call`); one active turn per
    peer with a fixed digit-free `BUSY_TEXT` through the single `transport.sendText(` call
    site.
  - Host facts cited from the read-only host trace of the same date (event and ctx
    shapes, `block`/`blockReason`, `replyOptions.runId ?? randomUUID()`,
    `onAgentRunStart`, per-key lanes); emulated in test-support, not exercised.
  - Review outcome: seven findings, all confirmed and fixed, none rejected.
    - The busy gate failed open on capacity eviction. It now uses an active index apart
      from the record store (RA-6).
    - `isCardTool` missed the host's `-N` collision suffix. It now strips the suffix
      (`isCardTool` table, D16 (f)), and the install PR asserts the literal host names.
    - There was no same-tick race test. RA-5 adds one.
    - RB-3's array case could not catch a missing array guard. It now carries every
      expected field.
    - RI-2 and RI-3 now run in both withhold modes.
    - A split WO sentence is repaired.
    - Item 16 is annotated as superseded by 19 (c), and the release-after-refusal
      behaviour is added to item 20.
    Each new regression fails on an assertion against a scratch mutant of its finding.
  - Counts: Node 121 pass (verifier 30, channel 66, host 25). Against d6daad2's runtime
    with the new tests: 93 of 121 do not pass (verifier 29, channel 52 incl. one 5 s
    timeout, host 12). There are no import errors: 51 fail on assertions, 41 are
    TypeErrors from test setup calling the new API, and 1 is the timeout. Pytest wrapper
    2 pass. Docs gates pass on changed files.
  - Left for the install PR: the host-level test of (a) (dashboard reuse of a live run id
    and session key refused; run-end window), the queue-mode config that keeps follow-ups
    and folding out, real-event capture, registering the handler. No install, config
    change, network or paid call; no commit by the implementer.
- 2026-11-07, WO-037 revision 7: tied card-call refusals withhold their own turn
  (`wo-036-whatsapp-channel-skeleton`, PR #181, on top of dd2aa6a). Offline implementation
  of owner decision 21. The owner approved the first five item 20 choices, kept item 16's
  protection, and asked that a refusal tied to its own WhatsApp turn withhold that turn,
  while a refusal of unknown origin refuses the call only.
  - Tie rule: a refusal is tied only when every run-binding check admission uses has
    passed: the run id, a stored and unexpired entry, a run that is confirmed and not
    ended, and the session key. Today only `requester-mismatch` is tied. Every earlier
    refusal and `handler-error` change nothing. A session key alone ties nothing.
  - Runtime:
    - records gain a monotonic `cardCallRefused`, set on that one entry by a tied refusal
    - `admitCardCall` answers `withheld: true` for a tied refusal
    - the handler's decision gains `withheld: 0 | 1`, which the host does not read
    - verifier "5" adds R0c `card-call-refused` before R1, so card tokens on the turn are
      withheld too, and `isWellFormedVerdict` accepts no release on a refused turn
    - four self-check vectors are added
    - no outbound change: `SAFE_TEXT` in safe-text mode, nothing in silent mode
  - Test support: the fake host can give one run's tool call its own requester, and can
    send a dashboard-style call with no run id.
  - Regressions:
    - RW-1, a buyer budget reused as a listing price. The RW-1b ordinary-turn release is
      pinned as a known limit. RW-1c shows an unknown-origin refusal still releases.
      RW-1d covers an admitted card call.
    - RW-2, a spelled-out listing claim. Its ordinary-turn release is pinned as a known
      limit.
    - RW-3, an unrelated WhatsApp reply that still delivers.
    - RW-4, no recall of blocks sent before the refusal.
    - RI-4, the flagged choice that the real-host replay test must settle at install.
    - unit tests for the ingress, gate, handler, self-check, verifier and source.
  - Counts: Node 141 pass (verifier 36, channel 78, host 27). Against dd2aa6a's runtime
    with the new tests and test-support, 25 of 141 fail (verifier 7, channel 17, host 1),
    all on assertions, with no TypeErrors and no timeouts. Pytest wrapper: 2 pass. Docs
    gates pass on the changed files.
  - Standing: re-request review on #181 after CI passes. #179 stays on hold and
    installation stays paused. Nothing installed or configured, no network or paid call,
    no commit by the implementer.
- 2026-11-07, WO-037 real-host replay test (`wo-037-real-host-replay`, from main 2a2164f):
  the pinned OpenClaw 2026.9.5 ran as a real gateway in an isolated harness, with no
  credentials and no paid calls. The harness used `env -i` with temporary home, state and
  config directories, and `sandbox-exec` denying `~/.openclaw` and all outbound network
  except loopback. It drove a fake WhatsApp transport, a scripted loopback model and a fake
  stdio `idx` MCP server, with synthetic data only.
  - Results, two full runs of six modes each, same outcome:
    - The genuine DM's card call (`idx__search_listings`) was admitted on the channel-issued,
      host-confirmed run id, and the peer received exactly the stored card bytes.
    - A dashboard `chat.send` replaying the live run id (as `idempotencyKey`) and session key
      never ran the tool. In the default, steer, followup and collect modes the host gave
      the replayed run a fresh id, which the hook refused `unknown-run`, and the genuine
      reply was delivered.
    - Under `queueMode: "interrupt"` the host aborted the genuine run, and no reply was
      sent. The "cannot suppress" check fails; owner decision WO-037 item 22.
  - Host facts that changed the code:
    - A path-loaded plugin is never started without a link install (`package.json`,
      `--accept-capabilities`).
    - A "whatsapp" deny blocks this plugin when the stock plugin is absent, so the
      self-check gains an allow-list form.
    - The host registers the plugin from several loaded copies and keeps every copy's
      hook. A per-copy ingress refused every genuine card call, so there is now one frozen
      ingress per process (RH-1).
  - Host wiring added in `index.mjs`; the hook is registered before the channel.
  - One focused send-boundary review: the invariant holds. Three findings fixed, two
    recorded as residuals.
  - Node 149/149 pass (`entry.test.mjs` 8 new). The pytest wrapper passes (3). Install,
    rollback and live smoke commands are drafted in
    `docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md` and have not been run.
  - Installation stays paused; #179 stays on hold.
- 2026-11-07/08, WO-037 item 22 decided; real-host harness tightened (`wo-037-real-host-replay`,
  PR #182). The owner confirmed the four routine choices. Option (a), operator trust, was not
  taken. A read-only trace showed that a `chat.send` interrupt needs only `operator.write`
  with no session-ownership check, and that by default the host gives dashboard users admin.
  The host-level control was brought back instead.
  - Harness: every check now needs its own evidence, and a timeout or missing evidence
    fails. Check B needs zero replay executions plus an explicit host rejection or a
    recorded hook refusal. New modes: `interrupt-fresh` and `interrupt-roles`.
  - Two full runs of eight modes on OpenClaw 2026.9.5, same outcome:
    - genuine-only, default, steer, followup and collect pass. B evidence is
      `hook-refused`, with 0 replay executions.
    - `interrupt`: `cancelled-by-interrupt`, 0 replay executions. B fails for lack of
      evidence, because the host aborted the replayed run along with the genuine one.
    - `interrupt-fresh`: `cancelled-by-interrupt` with no replayed id. The replay's card call
      was `hook-refused`.
    - `interrupt-roles` passes. Dashboard users authenticate by trusted-proxy identity under
      `gateway.roles` with `sessions.others: "none"`, read and write scopes, and no admin.
      Their interrupt, `chat.abort` and `sessions.abort` on the WhatsApp session were
      rejected ("Session ... was not found"). The same user chatted in its own session,
      and the card was delivered exactly.
  - Recorded as an availability risk: shared-token, password and admin holders bypass roles
    and can still cancel a live reply.
- 2026-11-08, WO-037 owned-channel install items on the real host
  (`wo-037-owned-channel-install`, stacked on #182). The production package, inbound
  allowlist and owned card resolver (independent of #179, which stays on hold) ran in the
  isolated harness on OpenClaw 2026.9.5, with only the transport fake. The harness used
  synthetic data only, no credentials and no paid calls.
  - Real-host fact: the bundled-MCP bridge hands both the model and `after_tool_call` one
    text block, labelled `structuredContent:` and followed by key-sorted JSON. The first
    run withheld the card (fail closed). The renderer now accepts exactly that label
    (CR-RH).
  - Two full runs of nine modes, same outcome:
    - The peer received exactly the rendered card bytes.
    - A sender outside `allowFrom` got no reply, no model call and no tool call.
    - The replay modes, interrupt-roles and the two unprotected interrupts gave the same
      results as on #182.
  - Node 183/183; pytest wrapper 5/5. A transport recommendation (Baileys on a dedicated
    number, with Cloud API as fallback) and the shortest live smoke test are drafted for
    owner approval.
- 2026-11-08, WO-037 replay liveness proof (`wo-037-real-host-replay`, PR #182). New check
  L: the host's terminal record of the genuine WhatsApp run brackets the replay's send time,
  the model was still holding the genuine request, and the peer had nothing yet.
  - B and C require L. B also requires the replay's own run to be reported terminal within
    the deadline, so a logged hook refusal no longer passes a replay that timed out.
  - The rules are in the pure `checks.mjs`, with 8 offline tests that CI runs.
  - Two runs of eight modes, same outcome:
    - Replays were sent 118 to 289 ms after the genuine run started.
    - Every replay mode passed L, with the replay settled and 0 executions.
    - interrupt and interrupt-fresh show the genuine run ending in error about 60 ms after
      the replay (`cancelled-by-interrupt`).
    - interrupt-roles passes.
- 2026-11-10, status reconciliation (`chore-status-20261110`). README, STATUS,
  START_HERE, CAPABILITY_ROADMAP and ACCEPTANCE_MATRIX now distinguish merged code
  through #186 (`e0c2370`) from the last recorded serving revision (`0b0c48c`) and
  failed Phase 1 acceptance (#176). The open PR list was checked on this date;
  #187 remains open, #163/#164 remain pending, and #179 stays on hold.
  - The checkpoint records the v5 store's limited policy scope, the pending live
    Cloud API setup, Phase 1 before Phase 2 acceptance, the text-only channel's
    chart-media gap, and the autonomy-ranked affordability / event prerequisites.
  - This was a documentation reconciliation against merged records and GitHub,
    not a new live probe. Dated evidence was preserved. No serving checkout,
    gateway, configuration or private store was changed; no paid call was made.
- 2026-11-10, WO-041 install readiness (`wo-041-install-readiness`, from main `7a1fe36`).
  This is the runbook's install PR (gate G4). It was prepared key-free and is not merged.
  Nothing was installed, enabled or configured on the live gateway, and nothing was sent.
  `openclaw` ran only in the sandboxed harness; no paid call was made.
  - Two new startup refusals in the plugin self-check:
    - `dm-scope-not-per-channel-peer`: `session.dmScope` is not exactly `per-channel-peer`,
      or a WhatsApp route binding overrides it.
    - `card-tool-host-names-invalid`: a pinned `idx__<tool>` name is not the literal name,
      is over the host's 64-character cap, or is rejected or mis-mapped by `isCardTool`.
  - A third assertion, "no other plugin claims channel `whatsapp`", cannot be made. The
    2026.9.5 plugin API shows `register` no other plugins. It stays a manual check, and the
    gap is documented in the runbook.
  - New harness check T, run in every mode: the host presents exactly the four pinned
    card-tool names.
  - New harness mode `stock-present` uses the stock `@openclaw/whatsapp` 2026.9.5 package.
    The tarball came from the local npm cache, not a download, and its sha512 equals the
    registry's. It was link-installed in the sandbox.
    - With the stock entry left enabled, as its install leaves it, the host's auto-enable
      puts `whatsapp` back into the effective allow list. The self-check then refuses, and
      the stock plugin loads. An allow list alone therefore does not keep an installed
      stock plugin out.
    - After `openclaw plugins disable whatsapp`, only our plugin loads and delivers. The
      stock plugin is never loaded.
  - Runbook changes:
    - 3.1: two options for the case where stock is installed. (b), allow list plus a
      disabled stock entry, is the owner's chosen route; (a), uninstall, is kept as a
      fallback only.
    - 3.6: the queue trace. `byChannel` keys on the message's provider, so the dashboard
      is `webchat`. 3.6 makes no write, by owner decision.
    - Gate rows G2 to G4 brought up to date.
    - Fixes to C3, C5, C10, 3b, 3.7, the snapshot and verify key lists, the section 4
      rollback commands with the `dmPolicy` guard, the stock restore and relink checks,
      the section 7 preconditions, the number rule, `SMOKE_START`, and 7.6 step 6.
    - 7.3: the owner's choice of a Cloudflare named tunnel, and a cited, TO-CONFIRM setup
      block for login, create, route dns and run.
  - Owner-supplied offline tunnel evidence, formats only: `cloudflared` 2026.10.7. The 7.3
    offline checks matched the runbook against a placeholder config. Checks against the
    real config remain pending.
  - Tests: pytest 5478 passed and 131 skipped; ruff clean; node 319/319. Harness run A1 on
    OpenClaw 2026.9.5: 12 modes, exit 0, every mode passed.
  - Recorded as given: four written owner decisions (tunnel, G4, stock plugin, queue).
    Nothing else is recorded as approved or waived. Q2, Q4 and Q6 remain pending.
- 2026-11-10, WO-041 review fixes (`wo-041-install-readiness`, new commits on 1e6b1cb; no
  amend). An adversarial review of #190 found the following problems. Each was checked
  against the pinned host and then fixed. Nothing was done live.
  - Correction to the entry above: option (b) of 3.1 is NOT the owner's chosen route.
    - The owner wrote only: "Keep the stock plugin installed while the harness checks
      whether the allowlist excludes it." The harness then found that the allow list alone
      does not exclude it.
    - (b), the allow list plus `plugins disable whatsapp`, is the agent's proposed route.
      It is harness-proven and awaits the owner's written decision. (a), uninstall, is the
      alternative.
  - Rollback: R3, `plugins uninstall idx-whatsapp-channel`, deletes the whole
    `channels.whatsapp` block. R5b now restores the full recorded block, with the dmPolicy
    guard.
  - Rollback: R6, `plugins enable whatsapp`, is refused "blocked by allowlist" when the
    recorded allow list omits `whatsapp`. In that case R6 now writes the entry directly.
    Section 2 records the information both forms need.
  - 3.1(b): `plugins disable whatsapp` normalizes the allow list, so the conditional write
    now expects the list as read back after the disable.
  - Auto-enable check: the host logs its auto-enable as a header line followed by untimed
    change lines, so the old one-line search could never match. 3.7 now has an owner-check
    block for it.
  - Window rule: restart recovery can re-admit dashboard input after a stop and start, so
    dashboard tabs must be closed before every stop and the log watched after every start.
  - 3.6: the busy gate sees only this channel's own turns.
  - 7.3: the login must authorize the zone that holds the host name, and the printed CNAME
    name is checked.
  - Stale record texts were corrected.
  - Harness:
    - New mode `stock-present-allowlisted`.
    - Both stock modes now also run 3.1(b) in the runbook's order.
    - The auto-enable owner check runs in phase 1 (flagged) and phase 2 (clean).
    - New phase 3 runs the section 4 rollback in its real order. Every step exited 0;
      `channels.whatsapp` and the allow list ended equal to the snapshot; the stock entry
      was enabled; the stock plugin loaded and ours did not.
- 2026-11-10, WO-041 second review round (`wo-041-install-readiness`, one new commit on
  9abb35f). A re-review of #190 confirmed nine items. Each was checked against the pinned
  host, then fixed. Nothing was done live.
  - Correction to the entry above, which records no full harness run:
    - The run before 9abb35f (A2) failed one mode. `steer` did not start its channel within
      60 s on a heavily loaded machine; it passed when rerun alone.
    - The run at exactly 9abb35f with a clean tree (A3) passed all 13 modes, exit 0.
    - CI at 9abb35f: 5536 passed, 74 skipped.
  - 3.7: the owner's auto-enable check could print `clean` after a late `START_CHECK`. The
    stamp now sits in the 3.7 block before `gateway start`, and the check fails closed
    unless a gateway start is logged after the stamp.
  - Snapshot reads `config get` cannot give safely:
    - `config get` redacts `gateway.auth` secrets, so R4b restores single sub-keys only.
    - `config get` shows a runtime view with schema defaults filled in. R5b now restores
      the authored `channels.whatsapp` block, read from the config file by a new
      owner-check block, which the harness and pytest also run.
  - Section 2: the snapshot loop now branches on exit status, so each key has exactly one
    value file.
  - Section 4:
    - R4 now expects the allow list as read back after R3.
    - Account-level allowFrom lists are cut to the owner and restored with paired commands.
    - The merged 7.6 rollback keeps the restore order.
  - Dashboard rule: it now applies to the stops. One read-only tab is allowed for S3 and
    M3.
  - Harness stock modes, rerun on this code with an authored stock block (no defaults, an
    account with a `~` authDir, two entries in each allowFrom): pass.
    - The snapshot came from the authored-snapshot block.
    - After R5b the lists were owner-only.
    - The paired restores exited 0.
    - The final authored block equals the snapshot.
    - Under the stock schema, `config get` showed `groupPolicy` and `mediaMaxMb` added and
      the `~` path expanded.
- 2026-11-10, WO-041 third review round (`wo-041-install-readiness`, one new commit on
  b1de88d). The final check of b1de88d confirmed four items. Each was checked against the
  pinned host, then fixed. Nothing was done live.
  - Final-head run at exactly b1de88d with a clean tree (A4): 13 of 13 modes passed,
    exit 0. CI at b1de88d: 5542 passed, 74 skipped.
  - Interactive zsh does not treat `#` as a comment on macOS. Trailing annotations reached
    commands as arguments, and the R6 annotation's `; exit 0` closed the terminal.
    - The runbook now requires one `bash` shell for every block.
    - No command line carries a comment; expected outputs moved to `text` blocks.
    - A new pytest feeds every bash and sh block (38) to `zsh -f -i` and `bash`, with
      stubs that record their arguments.
    - Against b1de88d, 15 blocks failed under zsh; all pass now.
  - Writing `gateway.auth.mode` deletes the other modes' credentials. 3.6b and R4b now
    say so, and say to recover the secret from the section 2 archive.
  - Restore watch: R5b now also cuts each `groupAllowFrom` to the owner and disables groups
    for the watch, with paired restores.
  - 3.2 now cuts each account's own `allowFrom` and `dmPolicy`. The harness runs those
    per-key commands, and check Z covers both changes.
- 2026-11-10, WO-041 fourth review round (`wo-041-install-readiness`, one small commit on
  88803e1). The final check of 88803e1 confirmed two minor items, now fixed. Nothing was
  done live.
  - Earlier run at exactly 88803e1 with a clean tree (A5): 13 of 13 modes passed, exit 0.
    CI: 5583 passed, 75 skipped.
  - When 3.6b changed `gateway.auth.mode`, the secret is now recovered as a single leaf
    (R4c), never by copying the restored config over the live one. A new owner-check block
    writes only `gateway.auth.token` or `.password`, from a fresh `backup restore` copy,
    through `config patch --stdin`, so the value is never printed or put in argv.
  - The harness stock modes prove this end to end:
    - A switch to `trusted-proxy` prunes the token.
    - The mode write-back and R4c restore exactly the original token.
    - R5b's owner-only cut stays intact.
    - `backup restore` accepted an `--only-config` archive on the pinned host.
  - The shell-block test was strengthened:
    - It now fails on zsh shell errors.
    - A static lint over every bash and sh block was added.
    - Common tools are argv-recording wrappers.
    - The reviewer's nine mutations are all caught (one by the lint alone).
- 2026-11-11, WO-041 owner decision recorded (`wo-041-install-readiness`, one docs commit on
  dd848b6). The owner wrote: "For the owner-only smoke test, use stock exclusion route (b):
  keep stock installed, disable it explicitly, and apply the allowlist. Use queue option 1
  with no dashboard sends into the WhatsApp session. Keep the no-reboot, no-logout rule and
  skip gateway stop --disable."
  - The runbook records:
    - 3.1 (b) as the chosen route for the owner-only smoke test, with (a) kept as the
      documented alternative.
    - 3.6 option 1: no queue config write, no dashboard sends.
    - `gateway stop --disable` as skipped by that decision.
  - Shell blocks are unchanged. G1, the section 7 approval, Q2, Q4 and Q6 stay pending. No
    waiver is recorded.
- 2026-11-11, WO-043 window plan (`wo-043-window-plan`, stacked on #190 at 0acf05e). This
  was docs and tests only, with nothing live.
  - The owner's planning decisions A to E and the Cloudflare scoping rule were recorded
    verbatim as planning decisions, not approval.
  - The runbook gains a window plan: pre-stage phases, the named deviation, a window of
    3 h 15 min, the latest rollback start at T0 + 1:44, checkpoints and durations.
  - It also gains the A2 #189 go-live as a separate short outage. This includes a key-path
    config compare that prints no value (pytest-proven) and a rollback that restores
    checkout, policy and config together.
  - 7.6 now follows the window order: confirm the shutdown, stop the tunnel, revoke on
    doubt, then the tested restore, then cleanup after stock is verified.
  - 7.3 replaces the zone-wide HTTPS toggle with a redirect rule for the webhook host
    alone, and lists zone-wide settings separately for owner review.
  - G1, the section 7 approval, T0, Q2, Q4 and Q6 stay pending, and no waiver is recorded.
- 2026-11-11, WO-043 review fixes (`wo-043-window-plan`, one docs and tests commit on
  ad5af1f). An adversarial review of #191 confirmed 5 minor findings and 2 nits; all are
  fixed. Docs and tests only, with nothing live.
  - A2 now chains stop, pull and install.sh so they stop at the first failure. It adds
    three checks before the compare and any start: no `A2: FAILED`, the policy installed
    line, and the checkout equal to the named #189 merge commit. Any failure triggers the
    A2 rollback, and so does the compare's JSON5 REVIEW line.
  - The a2-compare expected list now names every key install.sh renders the checkout path
    into. Any other line means stop and decide.
  - The B9 row expects plain HTTP 301 only, matching 7.3.
  - The window cleanup and the 1b summary remove the tunnel credentials JSON,
    `<CONFIG_PATH>` and, if no longer needed, `cert.pem`.
  - 7.3 describes the wildcard Single Redirect as a full-URI wildcard match with a
    `wildcard_replace` target (TO-CONFIRM), quotes Cloudflare's proxied-traffic sentence
    exactly, and relies on the plain-HTTP 301 outside check.
  - A test now covers the `@` redaction branch; a mutant without it is killed.
  - G1, the section 7 approval, T0, Q2, Q4 and Q6 stay pending, and no waiver is recorded.
- 2026-11-10, WO-042 disclosure and referral policy (`wo-042-disclosure-referral`, from
  main 7a1fe36). Following the owner's Q5 choice of clear disclosure, the response policy
  `config/IDX_RUNTIME.md` gains a rule to say plainly that the assistant is an automated AI
  assistant (first reply of a conversation, and whenever asked if it is a bot or a person),
  and a fixed line sending offers, contracts, showings and other transactional requests to
  the licensed agent through the contact in the channel's profile. The old blanket contact
  sentence is narrowed: credentials and everyone's contact details stay forbidden.
  - Both new texts hold no numeric character, so on the owned WhatsApp channel a
    disclosure greeting releases under the verifier's no-figures rule; card turns are left
    as they were, and the disclosure waits for the next non-card reply.
  - Checked offline against the code: verifier R1b, R2 and R4, `REPLY_INSTRUCTION`, and
    runbook 7.5 M1 (one `sent` line, `rule: "no-figures"`), which still holds.
  - Q5's legal question stays with counsel. Q1, Q3 and Q7 are folded into the brokerage
    confirmation and remain open; Q2, Q4 and Q6 remain unanswered. No waiver is recorded.
  - Nothing was installed, run live or sent; no paid or model call. The change reaches the
    gateway only through an owner-run install, applies to new sessions on every channel of
    the `idx` agent, and is restored from the installer's `.idx-policy-backups/` copy or by
    reinstalling the previous file.
- 2026-11-10, WO-042 correction after the review of #189 (same branch, new commits; the
  entry above stays as written). These points in it were incomplete or wrong:
  - The disclosure is not guaranteed. A card reply must stay exactly the tool's message,
    so a conversation made only of card turns may not show the disclosure until code
    enforces it (research option 3b). The policy now answers a direct "are you a bot?"
    question first, with the sentence alone and no tool call.
  - The referral line had no precedence over the "can't help" line, which the policy and
    the server instructions both gave for any request no tool serves. Both texts now send
    offers, contracts and showings to the referral line; the draft decline keeps send,
    approve and recipient requests. A ROUTING.md row and a local routing case (not run, it
    needs a paid token) were added.
  - Every verbatim tool message or error, and every fixed reply, stays exactly as written;
    the disclosure waits for the next reply that is none of these.
  - The install and restore steps lacked the gateway restart and a fresh session. They now
    include both; a reset path for the WhatsApp peer that sends no WhatsApp message is
    recorded as TO-CONFIRM. Reinstalling the earlier file is the preferred restore.
  - The Q1, Q3 and Q7 notes now quote the owner's instruction to fold them into the
    brokerage confirmation, whose draft is held outside the repo. They remain open.
  Nothing was installed, run live or sent; no paid or model call.
- 2026-11-10, WO-042 second correction after the re-verification of #189 at 2f887b8
  (same branch, a further commit; the two entries above stay as written).
  - Owner instructions of 2026-11-10, verbatim: "Use clear AI disclosure for Q5 and leave
    the legal question with counsel." and "Fold Q1 business ownership, Q3 identity text
    and Q7 retention into the brokerage confirmation." Q1, Q3 and Q7 remain open; Q2, Q4
    and Q6 remain unanswered; no waiver.
  - Go-live coupling: the `idx` MCP server runs from the repo checkout
    (`scripts/install.sh:184`), so the narrowed server-instructions sentence takes effect
    as soon as that checkout is pulled past #189 and the gateway restarts, even if the
    policy holding the referral line is not installed. "Merging changes nothing on the
    gateway" is true only until the checkout is pulled. Pulling main past #189 (runbook
    precondition G5 keeps that checkout on `main`) and installing the policy, then the
    restart and a fresh session, must be one owner step; a restore reverses both.
  - Digest note (owner acceptance pending; not accepted): the default-off instructions
    digest pinned in `tests/test_phase_integration.py`,
    `tests/test_phase_integration_charts.py` and `tests/test_routing_contract.py` moved,
    `46dfa9cc…` -> `594b8468…`, and the analysis variant `0bec5f33…` -> `c426fe8a…`. The
    only cause is the "can't help" sentence of the MCP server instructions, which now
    leaves out a transactional request (an offer, a contract, a showing). The line itself,
    the tool list and the tool-listing digest are unchanged. `docs/ACTIVATION_HANDOFF.md`
    now says the same where it described the `cbad756` pins.
  - Policy changes in this commit: a transactional request now comes first, like the
    identity question, and gets the referral line alone, so the referral is no longer
    deferred; the identity line asks the user to resend when the message asked for more;
    one message gets at most one fixed line, by priority (identity, referral, draft
    decline, "can't help"); a composed first reply opens with the disclosure.
  - The routing selection with the analysis switch off is now 41 cases; the new
    `routing-local-043` has never run (`docs/STATUS.md` notes this beside the earlier
    coverage record).
  Nothing was installed, run live or sent; no paid or model call.
- 2026-11-10, WO-042 third correction after the third review pass on #189 at a559aac
  (same branch, a further commit; the entries above stay as written).
  - Cause of the pin move, corrected: the first WO-042 entry above opens "Following the
    owner's Q5 choice of clear disclosure" and goes on to the referral line, and the
    routing-pin comment named the owner's Q5 instruction. Q5 covers disclosure only. The
    referral line and the server-instructions change are agent changes (the referral from
    the eligibility doc's escalation row, the server sentence from the #189 review, so the
    server instructions agree with the policy's fixed lines), not owner instructions.
  - Digest note (owner acceptance pending; not accepted), superseding the values in the
    entry above: the default-off instructions digest is now `ba79956b…` (from `46dfa9cc…`
    on main, via `594b8468…` on this branch), and the analysis variant `20b53b5b…` (from
    `0bec5f33…`, via `c426fe8a…`). The only cause is the "can't help" sentence of the MCP
    server instructions, which now also leaves out a request to talk to or reach a person,
    a human or the agent (referral line) and a question whether the assistant is a bot, an
    AI or a person (disclosure line). The line itself, `_ANALYSIS_ANCHOR`, the tool list
    and the tool-listing digest are unchanged.
  - The referral trigger now also covers a request to talk to or reach a person, a human
    or the agent. Two local routing cases were added, `routing-local-044` ("are you a
    bot?") and `routing-local-045` (a request for a real person), both route []; with
    `routing-local-043` none has ever run. The routing selection with the analysis switch
    off is now 43 cases under a 172-call paid ceiling.
  Nothing was installed, run live or sent; no paid or model call.
- 2026-11-11, WO-042 owner decision on #189 (branch `wo-042-disclosure-referral`, on
  d0c888c; the entries above stay as written). Owner's written decision, verbatim: "I
  approve #189's posted disclosure and referral wording and the stated digest changes.
  Keep the referral line as written. Run the 172-call routing eval under separate
  approval and require code-enforced disclosure before adding buyers. Neither needs to
  delay the owner-only smoke test."
  - Digest note, owner-accepted 2026-11-11: the stated digest changes are the default-off
    instructions digest `46dfa9cc…` -> `ba79956b…` and the analysis variant
    `0bec5f33…` -> `20b53b5b…`. The values are unchanged; the pin notes in
    `tests/test_routing_contract.py`, both phase-integration `MAIN_DIGESTS` notes and
    `docs/ACTIVATION_HANDOFF.md` now say owner-accepted.
  - The referral line stays exactly as written.
  - Two owner gates, recorded as requirements, not as done: the 172-call routing eval
    needs its own separate paid approval (not authorized by this decision, not run), and
    a code-enforced disclosure (research option 3b) is required before any buyer is
    added. Neither delays the owner-only smoke test.
  - Not recorded by this decision: no answer to Q2, Q4 or Q6, and no live approval (the
    install, live setup and smoke test still need their own written approval).
  Nothing was installed, run live or sent; no paid or model call.

- 2026-11-04, wo-034-v4-refreeze (WO-034, re-freeze version 4 and final owner
  decisions): docs, the freeze file and one test file. Branch from `main` `5504cd5`.
  - **Re-freeze, version 4** (owner-authorized, grocery line only): prompt
    `da0c34a1…f2dd1e4` became `c698f20c…8e270155e`; schema `91bbeb56…6f01bcb67` and
    request `c8e5ef0c…92dfb11` unchanged; versions 1 to 3 kept; reason `ruling 9 named
    grocery chains (owner-authorized)`; `paid_calls_before_freeze` 0.
  - Freeze test: 3 of 14 tests fail on the version 3 doc and freeze file, 14 of 14 pass
    on version 4; restoring the version 3 grocery line reproduces the version 3 prompt
    hash.
  - Ruling 9 dev row, policy only (one list row and one dev remark read; no predictions,
    no score, no held-out data): the proposal still holds under the clarification.
  - Final owner decisions recorded: scoring contract (a) to (d), standard Messages API
    for both configurations, the Phase D resume rule.
  - No paid or provider call, extraction, store build, private store-manifest freeze,
    install, activation or merge.

- 2026-11-04, wo-034-v4-refreeze (WO-034, owner acceptance check 1): docs only.
  - The dev relabel procedure states that the version 3 list (`ac586374…fbf10de3`, hash
    re-confirmed) is not stale after the ruling 9 clarification: the one ruling 9 row
    and its dev remark were re-read, policy only, and the removal recommendation still
    holds; editing instructions and expected validation counts unchanged (both sets
    repeated). No list written.
  - **Incidental held-out exposure:** the agent printed the first 400 characters of
    `data/enrichment/sample.jsonl` to learn its format; that first record is a held-out
    (test) remark. No held-out gold, label, prediction or score was read; nothing from it
    was recorded; it played no part in the check. Owner to decide any consequence for
    the held-out set's single use.
  - No paid or provider call, no API key read, no merge.

- 2026-11-04, wo-034-v4-refreeze (WO-034, policy pin correction after #162): `main`
  `71fb39e` merged in by merge commit; the freeze file, one test file, docs.
  - Version 4's policy pin in `docs/ENRICHMENT_V3_FREEZE.json` changed from
    `3432736f…9a75a99` to the merged `docs/ENRICHMENT_REVIEW_POLICY_V5.md`,
    `229fdd74eb280827a2cf799897c229c33330a97d4cd31c84122d2eb0dbf0e7f8`. Provenance only:
    prompt, schema and request hashes unchanged; versions 1 to 3 unchanged;
    `paid_calls_before_freeze` 0.
  - New freeze test (latest version's pin equals the file's SHA-256, and the file is the
    #162 bytes) fails on `160f5c8` and on the pre-fix merge, passes after.
  - No paid or provider call, key read, held-out read or merge.

- 2026-11-04, wo-034-v4-refreeze (WO-034, owner decisions 1 to 6 on the held-out
  exposure, resume, the 600th attempt, the early token check, the dev re-screen and
  roles): docs, one test, one new private file.
  - **Incident wording, corrected** (the owner acceptance check 1 entry above stays as
    written): the first 400 characters of one held-out remark **entered the
    tool/conversation record**, not merely "seen". Its text is not repeated. No
    evaluation ran, so it **consumes no Phase D attempt**; the case is **excluded from
    the primary score**; **no candidate change may be informed by it**.
  - Exposed case identified privately by id only (only the first line of `sample.jsonl`
    parsed, only its `key` used, nothing printed but the split and counts); confirmed a
    `test` case via `splits.json`. New private file
    `data/enrichment/v3-heldout-exclusions-v1.json`, mode 600, SHA-256
    `2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0`: 1 excluded
    case, `primary_n` 149, `diagnostic_n` 150. Split, sample and gold files unchanged.
  - Scoring procedure: 150 requests per configuration unchanged; primary score (gate
    and per-facet checks) on 149; full-150 diagnostic from the same outputs; exclusion
    file and procedure sealed in the Phase D freeze (contract doc seal table).
  - Decisions 2 to 4 recorded: interrupted-run resume under validated state with a fresh
    capped token per invocation; a failed or interrupted 600th attempt exhausts the run,
    no refund; read-only early token check via the existing consent reader approved.
  - Decision 5: one policy-only screen of all 100 dev remarks (no prediction, no
    held-out data); no recommendation changed, no addendum; version 3 list
    `ac586374…fbf10de3`, its manifest and `labels.json` byte-unchanged. Model judgments,
    `human_review: pending`; dev gold edits and human-pass judgments stay the owner's.
  - New freeze-doc test fails on `82f49f6`, passes after.
  - No paid or provider call, key read, `consent.sh`, no other held-out record, gold,
    prediction or score opened, no merge.
- 2026-11-11, WO-034 (`wo-034-v4-refreeze`, PR #163): review wording fixes, docs and one
  test docstring.
  - Dev relabel step 1 now gives the corrected count: six dev gold
    `near_grocery_mentioned` labels, the ruling 9 row (owner decides) plus five
    supported, matching the contract doc since `5320eac`.
  - Contract doc Phase D step 6 and command contract: a resume token now follows any
    resumable stop (provider or auth failure, a validated interrupted invocation, a
    `token_cap` or `token_refused` stop), and the 2026-11-05 failed-request rule is
    stated, pointing to Phase B acceptance check 5.
  - Freeze test docstring names the four tracked files it reads.
  - No frozen block, hash or assertion changed. No paid or provider call, key read,
    extraction or merge; no held-out remark, gold, prediction or score opened.
- 2026-11-04, wo-034-phase-b (WO-034 Phase B, key-free driver, parser, span check,
  subtype mapper and the Phase D command): code, synthetic tests and docs. Branch
  stacked on `wo-034-v4-refreeze` at `9245d3f`.
  - New: `src/idx_agent/enrichment/v3.py`, `scripts/enrichment_v3_io.py`,
    `scripts/extract_enrichment_v3_dev.py` (Phase C and the comparator),
    `scripts/extract_enrichment_v3_heldout.py` (the Phase D command, not run), three
    test files and a fixture module on invented files only (104 tests; 3 collection
    errors at `9245d3f`). Transport: standard Messages API over `urllib`;
    no provider SDK, no new dependency.
  - Freeze version 4 verified at run time by the freeze file's own SHA-256
    (`4edd9237…bd56a89`) and the three recomputed block hashes; mutations of the prompt,
    schema, request, freeze file, `v3.py`, the I/O module and `v2.py` stop before a
    token.
  - Mapper (option A, decisions (a) to (c)): code `14a79573…f94458e1`, rule JSON
    `008ae08f…980cda13`. Every polarity and subtype combination, v1/v2/v3 shapes, and
    `score_v2` rejecting a spanless condominium annotation are tested.
  - Phase D contract tested with a fake transport: 300 initial requests first,
    exhaustion at 600 is final, resume after auth, provider and interrupted failures
    with a token capped at the calls left, no reset, no resend of completed
    checkpoints, nothing printed but calls and cases until both configurations are
    complete, seal mutations refused before a token.
  - Not run on real files: the comparator and the Phase C dry run wait for the
    owner's revised dev gold; the Phase D command waits for the lock and final freeze.
  - No paid or provider call, key read, extraction, store build, private store-manifest
    freeze, install, activation or merge; no real private file, held-out remark, gold
    or prediction opened.

- 2026-11-04, wo-034-phase-b (WO-034 Phase B review fix, Phase D resume rule): the
  Phase D command now refuses a first token other than exactly 600 calls and resumes
  only after an auth or provider failure, under a new token capped at the calls left.
  A token cap, a token refused mid-run and an interrupted invocation leave the run
  final, every sent request counted. Synthetic tests only: 13 failed against the
  driver at `40d436f`, 42 passed after.
  - No paid or provider call, key read, extraction, store build, private store-manifest
    freeze, install, activation or merge; no real private file opened.

- 2026-11-04, wo-034-phase-b (WO-034, owner acceptance checks 3 and 4): code, synthetic
  tests and docs, after merging `origin/wo-034-v4-refreeze` at `160f5c8`.
  - Paid paths now check the token read-only (ceiling included) before the key is read
    or the token spent; Phase D checks the lock first and refuses before any private
    file is opened; a run with no calls left is `exhausted` whatever its last stop (the
    600th call failing or interrupted included); an interrupt is persisted as final; the
    verdict carries the decision (d) caveat; the mapper hash covers every mapping
    function and constant (code `a9a5fab6…dc73a41e`, constants `a0b23adc…9965b2c0b`).
  - Synthetic tests only: 32 failed against the pre-fix head `630bf0c`, all pass after.
  - Open owner question, unchanged: an interrupted invocation stays final until the
    owner decides whether it may be resumed.
  - No paid or provider call, key read, extraction, store build, private store-manifest
    freeze, install, activation or merge; no real private file opened.

- 2026-11-04, wo-034-phase-b (WO-034, owner decisions 1 to 4 in the Phase B code and the
  pending review fixes (a) to (d)): code, synthetic tests, docs, after merging
  `origin/wo-034-v4-refreeze` at `0fb0414`.
  - Freeze file pin follows the version 4 policy pin correction:
    `9a04ca3e0dcc21ef4306065da97a48a4913e3f25483675045ca1ed1af77b5391`.
  - Phase D: an interrupted invocation may resume under a fresh capped token when the
    sealed inputs re-verify and the ledger, the run evidence (per-call `attempt` lines,
    `response` hashes) and every checkpoint agree and the stop is recorded; corrupt or
    unverifiable state writes a private final marker and refuses before any key or
    token; a failed or interrupted 600th attempt exhausts the run, no refund; a missing
    gold refuses with a reason; no token content reaches any output or run file.
  - Decision 1: the final freeze seals the held-out exclusion file
    (`2e60fd85…e8a8a0`); 150 requests per configuration; the verdict on the 149 primary
    cases; the full-150 score as a diagnostic from the same outputs, released together
    after both configurations complete.
  - Synthetic tests only (invented exclusion); fail before, pass after for each change.
  - No paid or provider call, key read, `consent.sh`, merge; no real private file,
    held-out remark, gold, prediction or score opened.

- 2026-11-04, wo-034-phase-b (WO-034, review of `74fe559`): code, synthetic tests, docs.
  - Phase D: an interrupt while an invocation starts is held until its settlement and
    start lines are written, then goes through the interrupted path (resumable); the
    first ledger is created whole, so an interrupt mid-write leaves no ledger.
  - Decision 3: a run written `exhausted` or `failed` stays final whatever settling the
    request left in flight finds; an interrupt after both configurations are complete
    and saved writes the ledger `complete`.
  - Not changed: a `token_cap` or `token_refused` stop stays final (owner's recorded
    rule; open owner question 6).
  - Six new synthetic tests fail before, pass after.
  - No paid or provider call, key read, `consent.sh`, merge; no real private file,
    held-out remark, gold, prediction or score opened.

- 2026-11-05, wo-034-phase-b (WO-034, owner decisions of 2026-11-05 in the Phase B
  code): code, synthetic tests, docs, after merging `origin/wo-034-v4-refreeze` at
  `b675463`.
  - Phase D: `token_cap` and `token_refused` stops resume under decision 2's
    conditions, with a fresh command-bound token capped at the calls left; the 600-call
    ledger bounds spend, not the token. A run found complete after settling is still
    released with no new token; a stored `exhausted` or `failed` stays final.
  - A remark that fails all three attempts is a failed request: `failed` in the
    ledger, a `failed_request` evidence line, scored as an empty prediction for that
    configuration, its count released per configuration as `failed_requests`. More
    than two in either configuration end the run `failed` (`failed_requests`), final,
    nothing released.
  - Synthetic tests only: 25 failed, 137 passed against the merge `dd2bdd4`; all pass
    after.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge; no real private file, held-out remark, gold, prediction or
    score opened.

- 2026-11-10, wo-034-phase-b (WO-034, the `75b21b1` review fix and a stack update):
  code review fix already on the branch, one synthetic test, docs.
  - Review fix `75b21b1` (2026-11-05, not logged until now): the Phase D validator
    refused a failed request whose third attempt had a `response` line but no
    checkpoint, the state an interrupt between the two writes leaves behind. A resume
    that recorded that line made the next load unverifiable, and a paid invocation
    would then have marked the run final. `_check_failures` now accepts that line; a
    failed request still needs three attempts, a `failed` ledger state and no
    checkpoint. Its synthetic test reported `unverifiable` before the fix and a
    release with one failed request per configuration after. CI on `75b21b1` passed.
  - Stack update: `wo-034-v4-refreeze` took in `main` `7a1fe36` (merge `f3f1211`) and a
    work order wording fix (`d7a0de9`), and this branch merged that head. Each
    evidence log merge kept `main`'s file byte for byte with the branch entries
    after it, byte for byte; nothing was removed from either side.
  - New synthetic test, `tests/test_enrichment_v3_heldout.py`, pinning current
    behaviour through the command and the fake transport: a failed 600th call that is
    the third attempt of the last unanswered request leaves the run released with one
    failed request; the same call with another request still unanswered leaves it
    `exhausted`, not resumable. Retryable, auth and non-retryable errors each. It
    passes with no code change; the reading still awaits the owner before the lock.
  - No paid or provider call, key read, `consent.sh`, extraction, store build, install,
    activation or merge of a PR; no real private file, held-out remark, gold,
    prediction or score opened.

- 2026-11-11, wo-034-phase-b (WO-034, owner decision (b) on the 600th call): code,
  synthetic tests, docs.
  - Owner decision, verbatim: "For WO-034, choose option (b). A failed or interrupted
    600th call is exhausted and final, including when it was the last unanswered
    request. Pin that case in the test and keep paid runs paused."
  - Phase D `Run` (`scripts/extract_enrichment_v3_heldout.py`): with no call left and
    the request of the invocation's latest counted call without a response, the loop
    stops `exhausted` (`budget_exhausted`) and the interrupted path writes `exhausted`
    (error class `interrupted`), never `complete`, even when that was the third attempt
    of the last unanswered request. Before, that case completed the run and released
    it with one failed request. An answered 600th call, a failed request with calls
    left, the more-than-two failed requests rule and an interrupt after both
    configurations are complete and saved behave as before. Phase C's driver does not
    share this code.
  - Synthetic tests only: with the `d7010a2` driver the three Phase D test files give
    10 failed and 167 passed; all 177 pass after.
  - No prompt, schema or request block changed; the v3 freeze hashes are unchanged and
    no Phase D lock or seal exists yet.
  - Paid runs stay paused. No paid or provider call, key read, `consent.sh`,
    extraction, store build, install, activation or merge of a PR; no real private
    file, held-out remark, gold, prediction or score opened.

- 2026-11-11, wo-034-phase-b (WO-034, review follow-up to the 600th-call decision):
  synthetic tests and docs only; no driver code changed.
  - A command test pins the more-than-two failed requests rule ahead of exhaustion on
    the interrupted path at the 600th call: the ledger, the stop line and the dry run
    read `failed`. A precedence-inverting mutant of `Run.interrupted()` that passed
    all 177 tests before now fails 2.
  - The `Run`-level 600th-call fixture now passes the driver's own ledger check, and
    the precedence unit test keeps its attempts equal to the calls used.
  - Paid runs stay paused. No paid or provider call, key read, `consent.sh`,
    extraction or merge of a PR; no real private file, held-out remark, gold,
    prediction or score opened.
- 2026-11-11, planning docs reorganized (`chore-planning-docs`, from main `e1ec3ab`).
  Owner rule of 2026-11-11: STATUS.md holds the overall agreed plan, and every agreed
  decision or plan change is recorded there. Docs only, with nothing live.
  - STATUS.md now holds the current state at `e1ec3ab`, the agreed stages S0 to S6 and
    tracks T1 to T5, the only phase-to-stage map, a decision register, the pending owner
    inputs, the open PRs, a naming key and a doc map. CAPABILITY_ROADMAP.md holds
    capability detail per stage and the scope of roadmap Phases 0 to 12, unrenumbered.
    AUTONOMY_LADDER.md holds the per-level plan; items not in the 2026-11-05 decision (an
    L0 gate, the relay guarantee's level, the feed request's timing) are listed as
    proposals only.
  - Dated sections were moved verbatim to the new docs/STATUS_HISTORY.md, including the two
    WO-042 bullets #189 added to "Remaining acceptance". The legacy STATUS anchor
    `current-checkpoint-2026-11-10` still resolves.
  - PR states were checked with gh: #187, #189 (`e1ec3ab`), #190 and #191 merged; #163,
    #164 (stacked on #163), #179 (on hold) and #171 (superseded) open. Stale claims fixed in
    the three docs and START_HERE include the main revision, #187, #189 and WO-041 shown as
    open, the missing A2 step, the 2026-11-05 partial live check of the core path, and
    ADR-0013 shown as pending.
  - No approval, answer, waiver or T0 was recorded. A2 is not recorded as done. G1, the
    section 7 approval, T0, Q2, Q4 and Q6 stay pending. No serving checkout, gateway,
    configuration or private store was touched, and no paid call was made.
- 2026-11-11, planning docs brought to `main` `8d24fc1` (`chore-planning-docs`, PR #192).
  Main merged in after #163 (`ff12a71`) and #164 (`8d24fc1`) merged. STATUS.md and
  CAPABILITY_ROADMAP.md now show both merged; WO-034's decided items (AG-H5, AG-H6) are
  on `main`, conflict X7 is resolved, and the open-PR table lists only #179 (on hold) and
  #171 (superseded). The entry above, written before those merges, stays as written.
  STATUS_HISTORY.md keeps its verbatim history. Docs only; nothing live, no paid call.
- 2026-11-11, PR #192 review fixes (`chore-planning-docs`, on `85d00be`). Docs only.
  STATUS.md: the r6 console-reading citation now names the 2026-11-06 r6 entry; the
  owner's planning-docs rule is quoted in AG-A10; the docs reorganization the owner asked
  for is AG-A11 (agreed owner request; the move is its own later PR); AG-C24 is planning
  only; AG-C6 and AG-C8 are dated 2026-11-08; conflicts are renumbered X1 to X6 (the
  "X7" in the entry above is now X5); the naming key adds T0, A2, window decisions A to E,
  Q1 to Q7 and M1 to M5; stage names match their headings. CAPABILITY_ROADMAP.md keeps no
  state columns, "Build order" is renamed "Phase outcomes and prerequisites", S2
  acceptance names matrix rows P1-1, P1-2, P1-3 and P1-5, and each phase section links
  its STATUS placement. START_HERE §4 is now a pointer to STATUS. ACCEPTANCE_MATRIX's X-1
  row shows #163 and #164 merged. STATUS_HISTORY's moved text is unchanged; one index
  title was corrected. No approval, answer, waiver, T0 or A2 recorded; nothing live, no
  paid call.
- 2026-11-12, owner decisions on Q2 and Q4 for the owner-only test (`chore-record-q2-q4`).
  Docs only. Recorded in docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md §4 and STATUS AG-D1 to
  AG-D3, quoting the owner.
  - Q4: satisfied by the owner's confirmation that existing IDX Exchange permissions cover
    real MLS data in the private five-message test, from the dedicated business number to
    the owner's number. No MLS request is sent. Open for buyer rollout.
  - Q2: handled under the internship capstone context for the test; no brokerage
    confirmation requested; no separate brokerage requirement identified for the test.
    Recommendation (not a requirement): a neutral bot display name and profile (no
    brokerage name, no licence claim). Open for buyer rollout.
  - Q6 stays a separate, pending item. G1, the section 7 approval, T0, the dashboard
    result and A2 stay pending; nothing live, no paid call.
- 2026-11-11, stale-text follow-up to #192 (`chore-stale-text`, stacked on
  `chore-planning-docs` at `382b4b3`). Docs only; it carries out STATUS.md agent action 5.
  PR states checked with gh first: #187 (`7a1fe36`), #189 (`e1ec3ab`), #190 (`fb3293f`)
  and #191 (`2d5e8f1`) merged; #192 open.
  - Runbook §1 gate table: G4 met by the #190 merge; G1 and G5 pending (prose only, no
    shell block changed). Runbook §7: the waiver sentence now records the owner's "no
    blanket waivers" decision (2026-11-10, AG-D6, conflict X4), with a dated note that it
    replaced the earlier "may waive" wording; none is waived.
  - WO-041 Status gains one dated line: merged as `fb3293f`, superseding the open state.
    README shows #187 merged as `7a1fe36`. CLAUDE.md's active-assignment line now points to
    STATUS for the current stage and active work.
  - Dated "superseded / see STATUS" notes, with the recorded text kept: ACTIVATION_HANDOFF
    §1, a new 2026-11-11 owned send-path note in ACCEPTANCE_MATRIX, TIMELINE's post-capstone
    section, and WO-022's pointer (the ladder section is now in STATUS_HISTORY).
  - Conflict notes at each source: X1 (ACTIVATION_HANDOFF D5; needs an owner decision), X2
    (ADR-0016, WO-037), X3 (eligibility §5, the transport recommendation), X5 (WO-034
    Status), X6 (WO-038 decision 8). STATUS.md action 5 is marked done.
  - No approval, answer, waiver, T0, A2 or dashboard result recorded. G1, the section 7
    approval, T0, Q2, Q4 and Q6 stay pending. Nothing live, no paid call.
  - Review fixes, same PR: STATUS's conflict intro now names the runbook §7 replacement;
    the ACCEPTANCE_MATRIX note no longer lists #187 as new since 2026-11-10; runbook §7
    dates AG-D6 2026-11-10/11, as STATUS does (the single date in the runbook bullet above
    was too narrow). No approval, answer, waiver, T0 or A2 recorded.
- 2026-11-12, docs/ folder reorganization (AG-A11; branch `chore-docs-reorg`, stacked on
  `chore-stale-text` at `648a7c5`, PR #193). Docs, comments and messages only. The
  owner's request of 2026-11-11, quoted: "the docs folder is getting very large, it needs
  more organization now".
  - 22 docs moved by `git mv` (every line R100): 7 to `docs/releases/`, 3 to
    `docs/whatsapp/`, 12 to `docs/enrichment/`. Files read by code or tests, hash-pinned,
    frozen, sealed, guarded or named by CLAUDE.md stay at their paths; `docs/README.md`
    lists them with reasons, indexes every folder and maps each old path to its new one.
  - `scripts/docs_relink.py` (idempotent, dry run first) fixed relative links and current
    `docs/` path text. Old paths stay as written in this log, STATUS_HISTORY, work orders,
    frozen and sealed enrichment files, the moved results docs, ACCEPTANCE_MATRIX's
    original body, commit-pinned citations and the chart-prune plist proposal. Comment
    and message paths updated in `.env.example`, `install.sh`, the two chart-trial shell
    scripts, `delivery.py` and one test docstring. `tests/test_docs_links.py` checks links
    and anchors, index coverage and that no old path returns outside those records.
  - No approval, answer, waiver, T0, A2 or dashboard result recorded. Nothing live, no
    paid or model call.
  - Review fixes, same PR (2026-11-12). The old-path check now sees `./` and `../`
    forms, holds only listed records (a pinned-line list in `scripts/docs_relink.py`
    replaces the sha and PR-number heuristics; quotes and `**Update of` paragraphs count
    only in ACTIVATION_HANDOFF; an unclosed verbatim marker fails), and checks
    ACCEPTANCE_MATRIX's current sections and ENRICHMENT_DESIGN.md. The link check reads
    quoted titles, reference definitions, images and HTML hrefs. The relink no longer
    rewrites fenced text: the `ef3bb25` install.sh output and two lines describing that
    commit's file regain the old path, with a dated note. The chart-prune plist comment
    now names the new path, so the line above that lists it among old-path records no
    longer holds. Six bare doc names in current specs gained their folder. STATUS and
    the index name PR #196. No approval, answer, waiver, T0, A2 or dashboard result
    recorded; no paid or model call.
  - Correction and re-verification fixes, same PR (2026-11-12). The review-fixes bullet
    above is wrong where it says the chart-prune plist comment now names the new path:
    `72dde07` restored `config/chart-prune.launchd.plist.proposal` unedited, as it is an
    owner-approved template (D6) and the owner has not approved a change. Its comment
    still names `docs/CHART_DELIVERY.md` as a record, so the earlier bullet that lists
    the plist proposal among old-path records holds. Also fixed: the index's current
    sections are checked for old paths (only its move table is a record); links whose
    text wraps or holds brackets are checked; a pinned citation holds only itself, not
    its line; two code comments in `evals/truth/sql.py` gained the docs folder. No
    approval, answer, waiver, T0, A2 or dashboard result recorded; no paid or model
    call.
- 2026-11-12, owner policy decision on Q6 and vendor-terms check (`chore-record-q6`). Docs
  only. The owner's policy is quoted in docs/WHATSAPP_CLOUD_API_ELIGIBILITY.md §4 and STATUS
  AG-D3: authorized project data may be processed, the context may grow with features, and
  the vendor must exclude inputs and outputs from training.
  - The bot's model is Anthropic `claude-sonnet-5-5` (docs/PROVIDER_HANDOFF.md). Anthropic's
    Commercial Terms say it may not train on Customer Content (Inputs and Outputs), with
    the DPA incorporated; standard retention 30 days, flagged content up to 2 years,
    batches up to 29 days. Checked from official pages; no API call, no login.
  - OpenAI embeddings also receive query text and redacted remarks; not used for training
    unless the org opts in.
  - Q6 stays open: the owner's account-setting checks, the OpenAI scope and whether
    counsel is still required. docs/DECISIONS.md's gateway-model row gets a superseded
    note pointing to the 2026-10-25 switch.
- 2026-11-12, Q6 closed for the owner-only test; Q5 counsel withdrawn; dashboard access
  check done (`chore-record-q6`, PR #195). Docs only.
  - Q6: the owner's policy covers OpenAI too, no sharing with AI labs, no counsel. Account
    checks reported by the owner: the gateway key is a Console API key in the owner's own
    individual organization, expiring 2026-11-24; Console feedback off; Development
    Partner Program not joined; no separate agreement; OpenAI data sharing disabled. The
    owner's Ultra plan credits pay for API calls in that organization; Anthropic states
    that API use is subject to the Commercial Terms regardless of individual or company
    (support article 8987200).
  - Q5: the owner extended "no lawyers" to the 2026-11-10 decision; clear AI disclosure
    stays.
  - Dashboard access (runbook 3.6b): owner only, from the owner-run summary script and the
    agent's OS-level checks (loopback-only listener, no SSH, tunnel, proxy or Tailscale,
    one user account). The owner tightened ~/.openclaw/credentials to mode 700. The 3.6b
    roles write is skipped. Side finding: the local MySQL listens on all interfaces
    (3306, 33060); not a gateway path.
- 2026-11-12, Meta test number for the owner-only test; owner safeguard inputs recorded
  (`chore-test-number`, stacked on PR #195). Docs only: the runbook (§1b, §7, 7.1, 7.4,
  7.5, 7.6), docs/whatsapp/WHATSAPP_CLOUD_API_ELIGIBILITY.md §4 (Q4 scope note) and STATUS
  (the 'Where we are now' WhatsApp row, AG-C25, AG-C29, AG-D2, AG-D6, S1, pending inputs,
  owner actions).
  - Owner decisions, quoted: "yeah lets do meta free test num" (the bot's number for the
    test is Meta's free Cloud API test business number); "tes" to the Q4 scope question
    (read as yes: it covers sending from Meta's test number to the owner's personal
    number); "2 yes" (App Mode Development first; no M1 `delivered: 1` is an abort, then
    roll back and reschedule with Live mode, which needs the privacy URL, an app icon and
    a data-deletion URL); "opt-in recorded" (private record, date only); "1 is fine" (the
    About line); "we dont need the contact route for now" (scoped to the owner-only test,
    not a blanket waiver; required before any buyer); "ok A", then "privacy URL ready"
    (URL not recorded); "Nov 15, 12pm" (T0 planning choice, 2026-11-15 12:00 PT).
  - Meta test-number facts were checked on official Meta developer pages on 2026-11-12
    (no login, no API call). Unconfirmed items are marked TO-CONFIRM in the runbook with
    their owner checks: the recipient cap and verification, Dev-mode inbound webhooks,
    profile and About editability, and whether a two-step PIN exists.
  - No G1, section 7 approval, A2 or waiver is recorded as given; T0 is planning only. No
    phone number, URL, token or id recorded; no paid or model call.
