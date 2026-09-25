# Timeline

Twelve weekly modules that build one product. Written in our own words on 2026-09-23
(Week 0 in progress); Week 12 lands in mid-December 2026. Work orders WO-000 to WO-005
cover Weeks 0-3 plus the eval harness. Later work orders are written one week ahead.

| Week | Has to produce | Work orders | State on 2026-09-23 |
|---|---|---|---|
| 0 | Both tables loaded locally, a WhatsApp round trip, API keys working | WO-000, WO-001, WO-002 | done |
| 1 | Architecture write-up with a workflow diagram: WhatsApp -> OpenClaw skill -> our tools -> the two tables | docs PR | done (PR #11) |
| 2 | A skill that turns a free-text request into a validated filter object, proven on 10+ test queries | WO-003 (filter model), WO-004 (model fills it, code validates, evals) | done 2026-09-24 (13 ci cases pass; model-driven: 9 of 10 parser cases pass, the last one is a reading to decide) |
| 3 | A skill that runs those filters against the listings table and returns formatted property cards | WO-004, WO-005 (eval harness) | done 2026-09-24 (WhatsApp demo from the owner number recorded in the WO-004 Status) |
| 4 | Multi-turn refinement over WhatsApp with per-sender memory; cards include photo count | WO-006 | done 2026-09-24 (seven-turn WhatsApp flow recorded; saved-search decision pending) |
| 5 | Market analytics from the sold table for any California city: median price, days on market, sale-to-list ratio, a trend over the months available (about six) | WO-008 | done 2026-09-24 |
| 6 | Semantic search over listing descriptions with embeddings; top 5 similar active listings for a free-text description | WO-010 | built (PR #38); the paid index build, the judged run, and the WhatsApp test wait for the human |
| 7 | Recommendation engine: top 5 similar listings with a price check against comparable sales | WO-011 | built (PR #40); the WhatsApp test and the phrasing run wait for the human, after the WO-010 index |
| 8 | RAG assistant over the indexed reference docs; answers three set questions (what DOM means; which columns the sold table has; what the list-to-close ratio is) | WO-012 | built (PR #47); the hybrid index build, the local run, and the WhatsApp test wait |
| 9 | One entry point routing across the five agent roles, with a mixed-intent test suite | WO-013 | drafted (PR #46) |
| 10 | The whole assistant working end to end over WhatsApp | to be written | |
| 11 | Email drafting behind a human approval gate, a weekly market-report template, a passing safety test suite | to be written | |
| 12 | Capstone: public repo with clean history and README, architecture diagram, schema notes, a live WhatsApp demo plus a recorded backup, a written reflection | to be written | |

Constraints that shape the order: the dedicated WhatsApp number is deferred, so only the
owner's number is allowlisted and the second-phone tests wait; every paid call (models,
embeddings, email) needs a consent token and a note in its work order; the sold data holds
about six months, so every trend counts back from the as-of dates.
