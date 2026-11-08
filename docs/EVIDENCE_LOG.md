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
