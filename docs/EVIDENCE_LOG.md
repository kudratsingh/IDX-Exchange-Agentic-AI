# Evidence log

Measured numbers that changed, one row per measurement, as described in `docs/EVALUATION.md`.

| Date | WO | What was measured | Before | After | How |
|---|---|---|---|---|---|
| 2026-09-24 | WO-005 | `ci` eval suite pass rate | no runner (a temporary test checked 13 case shapes) | 26 of 26 pass (13 property-search, 13 safety), 0 skipped | `python -m evals.run --suite ci --require-database` against the local real database and against the synthetic fixture (`idx_fixture`), both 26/26 |
| 2026-09-24 | WO-005 | db integration tests against the synthetic fixture | only runnable against the real database | 7 of 7 pass, tests unmodified | `MYSQL_HOST=localhost MYSQL_DATABASE=idx_fixture pytest -q -m db` after loading `tests/fixtures/synthetic.sql` |
| 2026-09-24 | WO-005 | unit test count on the branch | 705 (main after WO-004) | 798 unit + 7 db (after the temporary eval-cases test was removed) | `pytest -q` with and without `MYSQL_HOST` |
| 2026-09-24 | WO-005 | CI wall time, tests job only | 1 min 16 s (WO-004 run, unit tests only) | 1 min 0 s with the MySQL service, fixture load, db tests, and the ci eval suite (push run on commit e8c33ef) | GitHub Actions job durations (`gh pr checks`) |
| 2026-09-24 | WO-004 | parser accuracy on the 10 local cases | not measured | not measured (needs a `paid` run) | `python -m evals.run --suite local --allow-paid` with OPENAI_API_KEY and IDX_EVAL_MODEL |
