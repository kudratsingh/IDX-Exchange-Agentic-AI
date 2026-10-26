# Complete the semantic relevance review

## Current checkpoint: supplied labels scored

The operator supplied the marked archive after the behavior baseline's ten recall
skips. Validation found 100 valid labels across all ten sheets, with candidate
membership and every non-label field unchanged. Original unmarked files were
archived and hash-verified; source archive and notes remain private. The scoring
command created data/semantic/judging/judgments.json without any provider request.

| Measure on saved judged rankings | Result | Scope |
|---|---|---|
| Mean recall@5 | 81.25% | Eight queries with relevant candidates |
| Mean precision@5 | 64% | All ten queries, including two intentionally empty ones |
| Mean precision@5 excluding empty queries | 80% | Eight queries with relevant candidates |
| Zero-hit queries | 2 | Both intentionally empty queries |

Recall uses hits / min(5, relevant candidates in the judged top-ten pool), not
recall over all listings. Empty-query recall is undefined and excluded from its
mean. These are measurements of the saved rankings. They do not demonstrate live
abstention or establish a quality threshold. The next step is a separate grant
for ten embedding requests to check the current service against these labels.
No new sheet generation or repeated parsing tests are needed for that check.

## Mark or revise sheets for a future review

From the main checkout, open the private local folder:

```bash
open data/semantic/judging
```

Open each CSV locally and edit only its `relevant` column: `y` for a result you
consider relevant to that sheet's query, `n` otherwise. Use the displayed fields
and remarks as evidence; the assistant does not supply these judgments. Keep the
filenames, identifiers, columns and CSV format. The sheets and labels stay under
ignored `data/`; they are not public artifacts. The file's query is listed below.

| File | Query | Hard filter |
|---|---|---|
| semantic-local-001.csv | a quiet mid-century home with a big yard near good schools | none |
| semantic-local-002.csv | bright modern condo with city views and a gym in the building | none |
| semantic-local-003.csv | charming craftsman with mountain views and a wide front porch | Pasadena |
| semantic-local-004.csv | a fixer-upper with character on a large lot | up to $900,000 |
| semantic-local-005.csv | single-story home with a pool, good for entertaining | at least 3 beds |
| semantic-local-006.csv | cozy cottage close to shops and cafes | none |
| semantic-local-007.csv | quiet street, big yard, updated kitchen | Long Beach |
| semantic-local-008.csv | light-filled townhouse with a private patio and an attached two-car garage | up to $1,200,000 |
| semantic-local-009.csv | a lighthouse keeper's cottage on a rocky island reached only by ferry | none |
| semantic-local-010.csv | a medieval stone castle with a moat, a drawbridge, and a dungeon | none |

## Score, then check the current ranking

For a future review, after all 100 cells are marked, tell the assistant **marked**. It can run this
model-free command; you can also run it yourself:

```bash
.venv/bin/python scripts/semantic_spike.py --score
```

The command prints numbers only and creates the private judgments file if it is
absent. A blank cell leaves its query unscored. An existing judgments file is
preserved; report that message rather than replacing it. No recall or precision
value is claimed while the queries remain unscored.

Once all ten queries have judgments, the assistant will validate the numbers-only
output and prepare a separate grant for just those ten recall cases. Their ceiling
is ten embedding requests and zero chat requests. The passed parsing and memory
cases do not need to be repeated. The current ranking check fails if a returned
home was not on the judged sheet; changed candidates require fresh human labels,
not an altered expected result.

Recall and precision describe these judged candidates. They do not establish
market calculations, final-answer relay, email approval or WhatsApp behavior.
Those remaining checks are in BASELINE_ACCEPTANCE.md and DEMO_RUNBOOK.md.
