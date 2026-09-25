# ADR-0007: Semantic search: a file index under `data/`, filters in memory, SQL has the last word

**Status:** accepted for the build (spike of 2026-09-24); the index build and the judged run are recorded in the WO-010 Status
**Date:** 2026-09-24
**Work order:** WO-010

## Context
Week 6 asks for "find me something like this" over the listing remarks: a free-text
description in, the five most similar active listings out. Remarks are the one column the
structured search cannot use, and the handbook sets the route: embed each remark once with
OpenAI's `text-embedding-3-small`, embed the query, rank by cosine. The WO-010 spike
(read-only, `scripts/semantic_spike.py`) measured the real table on 2026-09-24: 54,884 of
55,212 active rows have a usable remark (99.4%), the median is 1,244 characters and the
longest 4,000, so about 18 million tokens go to the provider once (a 4-characters-per-token
rule of thumb; the human's estimate was about 17 million tokens and about $0.35 at the
list price, to be replaced by the figure from the provider's usage page after the build);
223 remarks carry an email, a phone number, or a link; 3 listing keys repeat; a float32
index at 1,536 dimensions is about 339 MB on disk. With random unit vectors of the same
shape, a fresh process imports, loads that index, and ranks the top 200 in 0.40 s (0.24 s
at 512 dimensions), a warm ranking takes 6.5 ms, and the process peaks at 444 MB once the
unit-length check runs in chunks (747 MB before). The human's decisions of 2026-09-24 settled
the route, the filter order, the redaction, and the paid gate.

## Decision
**One embedding provider, called twice in the product's life: once per remark at build
time, once per query.** `text-embedding-3-small` at 1,536 dimensions: the decision allowed
512 if cold start exceeded 5 seconds, and the measured 0.40 s leaves 1,536. The build is a CLI (`python -m idx_agent.semantic.build_index`)
that refuses to run under CI, without `--allow-paid`, without a valid human `paid` consent
token, without a key (the environment, else the repo's `.env`, by the human's decision of
2026-09-24 so the tool server under OpenClaw finds it), or with an output outside the gitignored
`data/` folder. It reads the active table in keyset pages of 50 allowlisted columns, writes
shards, resumes after a failure, re-embeds nothing that is done, and checks the active as-of
date at the start and again before the final write. Rejected: a local embedding model
(PyTorch and a model download for a comparison nobody asked for; gated in `DECISIONS.md`),
a vector database (one process, one file set, and a matrix-vector product over 55,000 rows
is all the ranking needs), and embedding at query time on demand (every query would pay for
the rows it touches, and latency would follow the provider).

**Redaction before embedding.** Emails, phone numbers, and links in a remark become
placeholders before the text goes to the provider or into the index; the database is not
touched. The 223 affected remarks lose nothing a buyer searches for, and the provider never
sees an agent's contact details. `IDX_EMBED_REDACT` defaults to on and the build records how
many inputs changed.

**Index layout: four files, complete or absent.** `vectors.npy` (unit-length float32),
`keys.npy` (strictly ascending listing keys; a repeated key keeps the newest row),
`attrs.npz` (city, subtype, list price, bedrooms: the hard-filter fields as of the build),
and `meta.json` written last with the model, the dimensions, the active as-of date, row
counts, file hashes, the token usage the provider reported, and `complete: true`. A load
that finds anything else (a symlink, a path outside `data/`, a hash mismatch, a row that is
not unit length) reports one named cause and the tool answers "not set up" while every
other tool keeps working. The only index allowed outside `data/` is the `test:hashing`
one that CI builds from the synthetic fixture with a sha256 token-hashing embedder, so the
retrieval checks run with no provider and no key.

**Filters in memory, cosine, then SQL decides.** The hard filters (city, price, beds,
subtype) mask the index rows first, cosine ranks what is left, and the top 200 keys go to
SQL in batches of 50 with the same filters and the active-status rule. SQL's answer is the
result: a listing whose price or status changed after the build drops out; rank order is
kept. Rejected: a SQL pre-filter that returns every matching key (it breaks the 50-row cap
on the first popular city), and a FULLTEXT candidate stage before the vector pass (at this
table size one cosine pass is cheaper than the stage it would replace; it stays a gate in
`DECISIONS.md` for the day the judged queries show exact terms being missed).

**Measured, not asserted.** Twenty-one CI cases pin exact rankings over the fixture index.
Ten judged queries (mixed styles, five with a filter, two meant to match nothing) get a
human-marked sheet under `data/`, and `recall_at_k` reads the marks before any paid call
and reports numbers only.

## Consequences
- Two more packages in the `semantic` extra (`numpy>=1.26,<3`, `openai>=1.40,<3`), installed
  by `dev` so CI tests the ranking; neither is imported by the server until the first
  similar-listings call.
- The index is a snapshot. Its as-of date rides in every result and a stale index adds a
  warning; a new build is a human's paid run, not something the server does on its own.
- About 340 MB of memory in the MCP process once the index is loaded, and a cold start of
  a few seconds on the first call; nothing at all until then.
- The provider sees redacted remark text and the user's query text. Nothing else leaves the
  machine, and no remark text ever enters a result, a log line, or a span.
- The human's tasks: the paid token for the sample and full builds, the cost from the
  provider's usage page, the marks on the judged sheet.

## What would reverse this
A cold start over 5 seconds at 1,536 dimensions that 512 does not fix (then a memory-mapped
index or a small vector store). Judged recall missing exact terms that a lexical stage
would catch (the FULLTEXT gate opens). The embedding spend, read from the console, becoming
a problem (the local-model gate opens). A second table or a much larger one (shards on disk
rather than one array in memory).
