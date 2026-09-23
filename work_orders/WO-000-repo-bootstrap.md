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
not started
