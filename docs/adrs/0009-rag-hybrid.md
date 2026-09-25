# ADR-0009: Document answers: exact names, then BM25 and embeddings fused by rank, over an index under `data/`

**Status:** accepted for the build (human decision of 2026-09-24 evening; spike of the same evening); the paid index build, the local phrasing run, and the WhatsApp test are recorded in the WO-012 Status
**Date:** 2026-09-24
**Work order:** WO-012

## Context
Week 8 asks for an assistant that answers questions about terms and the data from reference
documents: what DOM means, which columns the sold table has, what the list-to-close ratio is.
Two of the sources are confidential PDFs (the Trestle field guide and the Primer) whose text may
not enter the repo, a log, a span, a fixture, or an eval expectation. The WO-012 spike read them
with code and printed counts only: 36 and 8 pages, all with text; 753 chunks by the decided rule
before drops (722 Trestle fields and a preamble, 13 Primer parts, 18 schema-notes chunks); every
deny-listed name and 14 of the 17 agent-contact names have a field entry. Over questions with no
exact field-name hit, BM25 separates on-topic from off-topic questions (lowest on-topic top
score 11.05, highest off-topic 6.63), but three of five own-words paraphrases miss entirely, and
the DOM question ranks the field itself 260th without the alias table. The draft offered three
routes: embeddings only, BM25 only (no spend, no ADR), or both. WO-010's embedding route covers the
listing remarks only, and the hybrid gate in `DECISIONS.md` asks for evidence that vector-only
ranking misses exact terms, which this WO did not set out to collect.

## Decision
**Hybrid from the start, in a fixed order (human decision 1).** Code picks every passage: an exact
field name or an alias from our own table (`rag/aliases.py`: "DOM", "list-to-close", "sold table",
and so on) puts its chunk first, scored 1.0 (a multi-part camel-case field name in any case, a
one-word name only as written); then BM25 over the chunks (k1 1.5, b 0.75; tokens are lowercased
words plus the parts of a camel-case name, common function words dropped, no stemming) and cosine
over `text-embedding-3-small` vectors (WO-010's embedder and text rule, unchanged) are merged by
reciprocal rank fusion with k = 60 until 4 distinct chunks are in hand. A question is not found
unless it has an exact hit, a BM25 top score at the floor, or a cosine top score at its floor
(0.30 until the build's calibration numbers set it). The BM25 floor is 15.57: on the 527 chunks
left after decision 18 (2026-09-25; 14.60 on the earlier 625) the floor probe
(`scripts/rag_floor_probe.py`) found no gap between own-words off-topic questions (best 15.069,
a joke about agents) and own-words paraphrases with no exact hit (worst 4.015), so
the floor sits 0.5 above the best off-topic score and the paraphrases under it are left to the
vector leg. Both floors live in the index meta, and two settings can replace them at load without
a rebuild. The index (`chunks.jsonl`, `meta.json`, `vectors.npy`) is
written by `python -m idx_agent.rag.build` only under the gitignored `data/indexes/docs/`, never
over a finished one, and under the same `--allow-paid`, `paid`-token, and key refusals as WO-010's
build. The `rag_answer` tool loads it once per process, opens no database connection, drops as a
backstop any chunk keyed by a restricted field, trims a confidential passage to 120 words around
the question's words, and hands the model the passages in fences marked as reference data with a
code-written Sources line; the model writes the reply from them. Rejected: embeddings alone (a
question that names a field must hit that field every time, and a lexical rank is free and
deterministic); BM25 alone (the paraphrase misses above, and Week 8 is written as chunk, embed,
retrieve, answer); a vector database or a re-ranking model (625 chunks plus a few market summaries
fit in memory, and nothing yet shows the top 4 in the wrong order); score blending instead of
rank fusion (BM25 scores and cosines are on different scales and would need calibration per
index).

**Degrade, do not fail.** Each question is embedded under the same per-call `paid` check as
`find_similar_listings`. When there is no live token, no key, or the call fails, or the question
is under WO-010's 20-character floor, the tool answers from exact names and BM25 alone (in one
pass: the lexical ranks are kept, not recomputed), labels the route `bm25`, and says so in a
warning, rather than returning a provider error. CI and the eval runner use BM25 or WO-010's
hashing embedder, so no test needs a provider.

## Consequences
- The two PDFs' chunks go to the embedding provider once, at build time (about 36,000 tokens by
  the 4-characters rule; the cost is read from the provider console), and every live question
  goes with its retrieved passages to the gateway's model provider (decision 6).
- A live answer is a paid embedding call under a human `paid` token, like a similar-listings
  question; without a token the answer still comes, from words alone.
- The tool's `message` is written for the model, not relayed, unlike every other tool; the skill
  (`docs-qa`) carries the quoting rule (25 words from a source, with its label) that code cannot
  check on the reply. Its result names no table and no as-of date, an exception recorded in
  `CONTRACTS.md`.
- New code of our own (a BM25 of about 60 lines, the fusion, the chunker, the store); no new
  dependency beyond `pypdf` in a `rag` extra, since NumPy and `openai` are already the `semantic`
  extra.
- Confidential text lives in three places only: the index under `data/`, the tool result, and the
  model turn (and so OpenClaw's session store on this machine, capped at 120 words per passage).
- The market summaries are snapshots: each file carries the card's own as-of dates and a first
  line saying the day it was saved, so a document answer that cites one is dated, and a newer
  figure comes from the market tool, not from the index.
- With the BM25 floor above most paraphrases, a paraphrased question is found by its cosine score;
  when the embedding call is refused or fails, such a question gets the not-found reply rather
  than a weak passage.
- Every agent, office, showing, lockbox, or access-code Trestle entry (judged on whole camel-case
  parts; Owner and Occupant names stay as home facts) is left out of both indexes and the
  exact-name lookup (the human's decision of 2026-09-25), so a question about one gets the
  own-words "agent and office fields" glossary entry instead, and the live index matches only
  after a paid rebuild (until then the tool's backstop drops such chunks at query time).
- "Office" as a whole part would also drop a home-feature name such as a hypothetical
  `HomeOfficeYN`, if the data ever carried one.

## What would reverse this
Judged answers showing the vector leg adds nothing the alias table and BM25 do not already find
(then BM25 alone, no spend per question). The per-question embedding spend, read from the console,
becoming a problem (the local-model gate in `DECISIONS.md`). The top 4 holding the right passages in
the wrong order (the re-ranker gate). The floors failing to separate the set questions from
off-topic ones on the real index (a stop condition of WO-012).
