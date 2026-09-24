# Timeline

Twelve weekly modules that build one product. Written in our own words on 2026-09-23
(Week 0 in progress); Week 12 lands in mid-December 2026. Work orders WO-000 to WO-005
cover Weeks 0-3 plus the eval harness. Later work orders are written one week ahead.

| Week | Has to produce | Work orders | State on 2026-09-23 |
|---|---|---|---|
| 0 | Both tables loaded locally, a WhatsApp round trip, API keys working | WO-000, WO-001, WO-002 | done |
| 1 | Architecture write-up with a workflow diagram: WhatsApp -> OpenClaw skill -> our tools -> the two tables | docs PR | done (PR #11) |
| 2 | A skill that turns a free-text request into a validated filter object, proven on 10+ test queries | WO-003 (filter model), WO-004 (model fills it, code validates, evals) | done 2026-09-24 (13 ci cases pass; the 10 model-driven cases await one paid run) |
| 3 | A skill that runs those filters against the listings table and returns formatted property cards | WO-004, WO-005 (eval harness) | done 2026-09-24 (WhatsApp demo from the owner number still to record) |
| 4 | Multi-turn refinement over WhatsApp with per-sender memory; cards include photo count | WO-006 | drafted (PR #15) |
| 5 | Market analytics from the sold table for any California city: median price, days on market, sale-to-list ratio, a trend over the months available (about six) | to be written | |
| 6 | Semantic search over listing descriptions with embeddings; top 5 similar active listings for a free-text description | to be written | |
| 7 | Recommendation engine: top 5 similar listings with a price check against comparable sales | to be written | |
| 8 | RAG assistant over the indexed reference docs; answers three set questions (what DOM means; which columns the sold table has; what the list-to-close ratio is) | to be written | |
| 9 | One entry point routing across the five agent roles, with a mixed-intent test suite | to be written | |
| 10 | The whole assistant working end to end over WhatsApp | to be written | |
| 11 | Email drafting behind a human approval gate, a weekly market-report template, a passing safety test suite | to be written | |
| 12 | Capstone: public repo with clean history and README, architecture diagram, schema notes, a live WhatsApp demo plus a recorded backup, a written reflection | to be written | |

Constraints that shape the order: the dedicated WhatsApp number is deferred, so only the
owner's number is allowlisted and the second-phone tests wait; every paid call (models,
embeddings, email) needs a consent token and a note in its work order; the sold data holds
about six months, so every trend counts back from the as-of dates.
