# WO-000 — Repository bootstrap

**Driver:** agent (human reviews before WO-001 starts)
**Depends on:** nothing
**Estimated effort:** 1 hour

## Objective
A safe, empty-but-runnable public repository: nothing to leak, tooling in place, CI green.

## Why
The repo is public and its history is permanent. Everything that keeps data and secrets out
must exist before the first line of application code.

## Inputs
`CLAUDE.md`, `RULES.md`, `README.md`, `.gitignore`, `.env.example`, `docs/`, `work_orders/`, the gates in
`scripts/gates/`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `tests/test_gates.py` (all already present).

## In scope
- **Human step first:** put the three documents at the paths in `scripts/gates/sources.txt`, run
  `pip install pre-commit pypdf && pre-commit install && python scripts/gates/build_fingerprints.py`, commit
  `scripts/gates/fingerprints.txt`. No commit passes until this is done.
- Verify `.gitignore` matches `docs/SAFETY_INVARIANTS.md` (data, context, coordination, env, logs, dumps, auth).
- Run `pre-commit autoupdate` so the pinned hook versions are current; run `pre-commit run --all-files`.
- `pyproject.toml`: package `idx_agent` with src layout, Python >= 3.11, `[project.optional-dependencies].dev`
  = pytest, ruff, pre-commit, pypdf; ruff config; pytest config with the `db` marker.
- `src/idx_agent/__init__.py` with `__version__`; empty subpackages `domain/ db/ safety/ mcp_server/ parser/ memory/ channels/ observability/`.
- `tests/test_smoke.py`: imports the package and asserts the version.
- `tests/conftest.py`: skips `@pytest.mark.db` tests when `MYSQL_HOST` is unset.
- `evals/README.md` describing the case format (from `docs/EVALUATION.md`) and an empty `evals/cases/`.
- `scripts/README.md` naming the scripts to come (`install.sh`, `profile_data.py`, `migrations/`).
- Prove each gate blocks, on a throwaway branch: a fake `sk-` key, a `.csv`, a ten-word sentence copied from the
  handbook, an email address. Describe the four failures in Status, then delete the branch.
- `Makefile` or `justfile` with `install`, `lint`, `test`, `evals` targets.
- `docs/EVIDENCE_LOG.md` with the column headers only.

## Out of scope
Any application code, database code, OpenClaw code, skills, or changes to the docs' content.

## Files expected to change
`pyproject.toml`, `src/idx_agent/**/__init__.py`, `tests/*`, `evals/README.md`, `scripts/README.md`,
`.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `Makefile`, `docs/EVIDENCE_LOG.md`.

## Interfaces and contracts
None yet.

## Implementation requirements
1. `pip install -e ".[dev]"` succeeds on a clean virtualenv.
2. `ruff check .` and `pytest` pass locally.
3. CI runs the same commands plus the secret scan and the forbidden-files check.
4. Each of the three gates and gitleaks blocks its test case (see In scope).
5. No file under `data/`, `context/`, or `coordination/` is tracked, even if the folders exist locally.

## Safety requirements
Secrets only in environment; nothing from data, context, or coordination tracked; forbidden-files check in CI.

## Tests required
`tests/test_smoke.py` (import, version); `tests/test_gates.py` passes; the four throwaway-branch failures described in Status.

## Acceptance criteria
- CI is green on `main`.
- `git ls-files` contains no data, secret, or context material.
- All four gate checks block their test case; `scripts/gates/fingerprints.txt` is committed and non-empty.
- `pytest -m db` reports skipped, not failed, without a database.

## Verification commands
```
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
ruff check . && pytest
pre-commit run --all-files
git ls-files | grep -E '\.(csv|sql)$|^\.env$|^(data|context|coordination)/' ; echo "expect only migrations/fixtures"
```

## Deliverables
The tooling above, committed as one or two commits, CI green.

## Stop conditions
- A tool listed here is unavailable and the substitute would change the workflow.
- Anything would require a credential or data file to be committed.

## Status
**Done. Merged into `main` in PR #1 on 2026-09-23 with CI green.** Branch `wo-000-repo-bootstrap`
and its worktree were removed after the merge.

### Done
- Human step: the three source documents were fingerprinted and `scripts/gates/fingerprints.txt`
  (21,395 hashes) was committed in `ba49c30`. `main` was pushed to GitHub; push protection is on.
- `pyproject.toml`: `idx_agent` in src layout, Python >= 3.11, no runtime dependencies, dev extra
  (pytest, ruff pinned to the pre-commit rev, pre-commit, pypdf), version read from
  `idx_agent.__version__`, ruff config, pytest config with the `db` marker and `pythonpath = ["src"]`
  so tests run from the shared `.venv` in any worktree without an editable install.
- `src/idx_agent/__init__.py` (`__version__ = "0.0.1"`) and the eight empty subpackages.
- `tests/conftest.py` skips tests carrying the `db` marker when `MYSQL_HOST` is unset.
  `tests/test_smoke.py` checks the import and version and carries one `db`-marked placeholder so
  `pytest -m db` reports a skip instead of "no tests ran".
- `evals/README.md` and `evals/cases/` (kept with `.gitkeep`), `scripts/README.md`, `Makefile`
  (`install`, `lint`, `test`, `evals`; every tool runs as `$(PYTHON) -m`, default `python3`),
  `docs/EVIDENCE_LOG.md` (header row only).
- `.gitignore` audited against `SAFETY_INVARIANTS.md` and `forbidden_paths.py`: added office
  documents and PDFs, archives, sqlite/db files, jsonl, pickle, index/bin, `/embeddings/`,
  `/indexes/`, `*.session`. Existing negations for migrations, fixtures and `.env.example` still work.
- `pre-commit autoupdate`: pre-commit-hooks v5.0.0 -> v6.0.0, gitleaks v8.21.2 -> v8.30.0,
  ruff-pre-commit v0.8.4 -> v0.16.8. Hook id `ruff` renamed to `ruff-check` (the old id is a legacy alias).
- CI: `ruff format --check .` added to the tests job. Gate steps untouched.
- `CLAUDE.md`: branch, worktree, PR and Status conventions added under Conventions (human request).

### Verification (local, shared `.venv`, no editable install, after the review fixes)
- `pytest`: 7 passed, 1 skipped. `pytest -m db`: 1 skipped, 7 deselected, exit 0.
- `ruff check .` clean. `ruff format --check .` clean (39 files).
- `pre-commit run --all-files`: all 11 hooks passed, including from a shell with no `python` on PATH.
- `make test PYTHON=.venv/bin/python`: 7 passed, 1 skipped.
- A clean python3.13 virtualenv installed `pip install -e ".[dev]"` before the review fixes; the PR's
  CI repeats the install and the same commands on Python 3.11 with the final files.
- Gates on all tracked files: forbidden_paths ok (50 files); confidential_text ok (47 text files);
  pii_scan ok (47 text files). `git ls-files` shows no csv, sql, pdf, `.env`, or private folders.
- Baseline before this WO: the CI run on `main` passed the gates job and failed only
  `pip install -e` because `pyproject.toml` did not exist yet.

### Gate proofs (throwaway branch `wo-000-gate-proofs`, deleted afterwards)
Each attempt staged one offending file with `git add -f` and ran `git commit`. Every attempt exited 1,
created no commit, and left HEAD at `ba49c30`.
1. **Secret.** `notes/config.py` assigning a fake OpenAI-style key to `OPENAI_API_KEY`. Blocked by
   gitleaks, rule `openai-api-key`, with the value redacted in the output. Every other hook passed.
2. **Forbidden path.** `exports/listings.csv` with a made-up header and one row. Blocked by gate 1
   (`forbidden-paths`) on its extension rule. `.gitignore` also refuses the file without `-f`; the
   gate is the second layer.
3. **Confidential text.** `notes/draft.md` holding one ten-word window from the handbook, taken with the
   gate's own extraction and shingling functions. Blocked by gate 2 (`confidential-text`), which named
   the file and word offset. The window is deliberately not reproduced here.
4. **PII.** `notes/contacts.md` with one fictional email on a non-placeholder domain. Blocked by gate 3
   (`pii-scan`), which named the file and the address.

Positive path: a one-sentence markdown file committed on the throwaway branch with every hook
passing. The branch and its worktree were removed; `main` and the feature branch were untouched.

### Review
An independent review of the diff found no blockers. Applied from it: the `db` skip now matches the
marker rather than a keyword (a keyword match would have silently skipped every unmarked test under a
future `tests/db/`); an environment-dependent installed-metadata test was dropped; ruff is pinned to the
pre-commit rev so CI's format check and the hook cannot drift; `/embeddings/` and `/indexes/` are
anchored so they cannot hide a future source package; the Makefile no longer depends on bare `pip`,
`pytest` or `python`; `-q` left pytest's addopts so CI logs keep the pass/skip counts; the evals README
wording was aligned with `docs/EVALUATION.md`.

### Deviations and decisions
- The three local hook entries call `python3` instead of `python`. On macOS `python` does not exist
  outside an activated venv, so all three gates errored with "Executable `python` not found" and
  blocked every commit, harmless ones included. `python3` resolves on macOS, inside a venv, and on the
  CI runner. The gate scripts are unchanged; `.pre-commit-config.yaml` is in this WO's file list.
- Ruff's line-length rule (E501) is ignored for `scripts/gates/*.py` only. Their long message strings
  would otherwise fail lint, and the gates must never be edited to satisfy a check.
- The Node 20 deprecation notices from `actions/checkout@v4` and `actions/setup-python@v5` are
  warnings only; bumping them is left for a later WO.

### Follow-ups
- WO-001 is now the active work order (`docs/START_HERE.md`).
- Optional: branch protection on `main` requiring the `ci` checks before merge.
