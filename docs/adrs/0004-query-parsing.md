# ADR-0004: Query parsing is the model filling a typed schema

**Status:** accepted
**Date:** 2026-09-23
**Work order:** WO-003 (contract), WO-004 (wiring and evals)

## Context
WO-004 originally planned a deterministic rule parser (`parser/rules.py`) that turned free
text into `PropertySearchFilters`. The model already reads every message to choose a skill
and a tool, so a second parser would repeat that work with less coverage of phrasing, and
its rules would drift from the schema. What must stay deterministic is not the reading of
the text but the checking of the result: real city, real subtype, sane ranges, no guessing.

## Decision
The model is the parser: it fills the `search_listings` tool schema, which is
`PropertySearchFilters` with every field optional. Code validates strictly through
`PropertySearchFilters.from_input`, which returns either the accepted filters or a
`Clarification` (field, reason code, suggested follow-up question, small option list when
one exists). A `Clarification` runs no query; the skill asks the question. The tool returns
the accepted filter object alongside the results, so parsing is demonstrable on its own.
Rejected: a regex or rule parser (duplicates the model, misses phrasing); a second model call
dedicated to extraction (cost and latency for no gain in checking).

## Consequences
- The 10 parser test queries need a model, so they are `local` eval cases run with a human
  `paid` token; the validator's unit tests run in CI with no model.
- Parsing quality is measured by the local evals, not assumed; the results are logged in the
  WO-004 Status and the evidence log.
- Questions never echo the user's raw value; they name the field and, for small sets, the
  allowed options. The 1,082-city list is never sent back.
- `docs/DECISIONS.md` carries the row; the old extension "model-based filter extraction"
  became "deterministic pre-parser in front of the model", gated on eval evidence.

## What would reverse this
The local parsing evals showing the model misfilling fields that simple rules would get
right (for example the three known phrasing cases), or field-level precision or recall below
the target set in `docs/EVALUATION.md` after two rounds of skill-instruction changes.
