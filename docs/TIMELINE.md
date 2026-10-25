# Timeline

Twelve weekly modules that build one product, summarized in our own words. Current
checkpoint audited 2026-10-25 against the work-order evidence and installed runtime.
The schedule is a deliverable map, not a claim that the final live demo has passed.
See STATUS.md for the remaining acceptance steps.

| Week | Has to produce | Work orders | Verified state |
|---|---|---|---|
| 0 | Both tables loaded locally, a WhatsApp round trip, API keys working | WO-000, WO-001, WO-002 | done |
| 1 | Architecture write-up with a workflow diagram: WhatsApp -> OpenClaw skill -> our tools -> the two tables | docs PR | done (PR #11) |
| 2 | A skill that turns a free-text request into a validated filter object, proven on 10+ test queries | WO-003 (filter model), WO-004 (model fills it, code validates, evals) | done 2026-09-24; final historical parser run passed all 10 parser and both refusal cases |
| 3 | A skill that runs those filters against the listings table and returns formatted property cards | WO-004, WO-005 (eval harness) | done 2026-09-24 (WhatsApp demo from the owner number recorded in the WO-004 Status) |
| 4 | Multi-turn refinement over WhatsApp with per-sender memory; cards include photo count | WO-006 | WhatsApp flow recorded; browser instruction fix applied; saved searches subsequently implemented in WO-009 |
| 5 | Market analytics from the sold table for any California city: median price, days on market, sale-to-list ratio, a trend over the months available (about six) | WO-008 | done 2026-09-24 |
| 6 | Semantic search over listing descriptions with embeddings; top 5 similar active listings for a free-text description | WO-010 | index built/served; earlier phrasing and WhatsApp checks recorded; human relevance marks/judged recall and fresh provider acceptance pending |
| 7 | Recommendation engine: top 5 similar listings with a price check against comparable sales | WO-011 | earlier phrasing and WhatsApp evidence recorded; current-version/provider rehearsal pending |
| 8 | RAG assistant over the indexed reference docs; answers three set questions (what DOM means; which columns the sold table has; what the list-to-close ratio is) | WO-012 | hybrid index rebuilt/served and historical phrasing checks passed; fresh live acceptance pending |
| 9 | One entry point routing across the five agent roles, with a mixed-intent test suite | WO-013 | done: routing acceptance met (two consecutive runs at 25 of 25 after decisions 7 to 9) and the 12-message WhatsApp run recorded, every route matched (2026-09-25) |
| 10 | The whole assistant working end to end over WhatsApp | WO-014 | built, model-free parts (the 25 cases, the runbook, the preflight, the error-message test; Part A answered, 2026-09-25); the paid dry run and the live rehearsal wait for the human |
| 11 | Email drafting behind a human approval gate, a weekly market-report template, a passing safety test suite | WO-015, WO-009 extension | merged and installed; approval/sink safety verified offline; real owner delivery and alert rehearsal pending |
| 12 | Capstone: public repo with clean history and README, architecture diagram, schema notes, a live WhatsApp demo plus a recorded backup, a written reflection | WO-016 | materials prepared; live demo, recording and final personal reflection pending |

Constraints that shape the order: the dedicated WhatsApp number is deferred, so only the
owner's number is allowlisted and the second-phone tests wait; every paid call (models,
embeddings, email) needs a consent token and a note in its work order; the sold data holds
about six months, so every trend counts back from the as-of dates.

## Post-capstone capability roadmap

Authorized to begin 2026-10-25; these additions do not replace the uncompleted
acceptance above. See [CAPABILITY_ROADMAP.md](CAPABILITY_ROADMAP.md) for all proposed
capabilities and [WO-017](../work_orders/WO-017-bounded-analysis.md) for the active
numeric foundation and sandbox design. There is no newly available analysis tool.

The intended sequence is bounded analysis → valuation/payment search → proactive
events → clarification/prefetch/verification → simulation and smaller-model routing.
Container infrastructure, new dependencies/services, paid runs and channel changes
retain their explicit decision gates. No speculative time or accuracy claim is a
commitment; each work order will state what must be demonstrated.
