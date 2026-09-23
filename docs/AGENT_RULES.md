# Rules for the coding agent

How the agent that builds this repo (and every subagent it spawns) must behave. These
rules are about the agent's own conduct; `SAFETY_INVARIANTS.md` is about the product.
Each rule names how it is enforced. A rule with no enforcement is a belief, and the
lessons this file is built on (see the last section) are mostly about beliefs that failed.

## 1. Never delete or discard without human consent
Protected: every tracked file; everything under `data/`, `context/`, `coordination/`;
evaluation material (`evals/cases/`, `evals/runs/`, `evals/reports/`, `experiments/`,
`docs/EVIDENCE_LOG.md`); run artifacts, logs, and session stores; the database and its
tables; the agent's own memory and settings under any `.claude/` directory.

Covered actions: `rm` outside scratch space and rebuildable caches, `git clean`,
`git reset --hard`, `git checkout`/`git restore` of paths, `git stash`, force pushes,
`git branch -D`, forced worktree removal, `git rm`, history rewriting, `find -delete`,
`xargs rm`, `mv` of data or evidence, `shred`, `truncate`, `docker ... down -v` and
volume removal, `DROP`/`TRUNCATE`/`DELETE FROM`/`ALTER ... DROP`, truncating an
evidence file with `>`, and overwriting an existing evidence or data file with the
Write tool.

Allowed without consent: deleting inside the session scratch directory or `/tmp`;
removing `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `*.egg-info`, `build/`,
`dist/`; `git branch -d` and `git push --delete` of a merged branch; renames;
`.gitkeep` files; appending (`>>`) to the evidence log.

Enforced by: `scripts/guards/guard.py` (Claude Code PreToolUse hook on Bash, Write,
Edit, NotebookEdit) with a `delete` consent token; `scripts/gates/protected_deletions.py`
(gate 4) at commit with the same token, and in CI on pull requests with the
`deletion-approved` label that only a human applies. Proven by `tests/test_guards.py`
and `tests/test_protected_deletions.py`.

## 2. Never spend money without human consent for that run
Covered: any command that reaches a paid model or API host, imports or instantiates a
model SDK, passes or exports an `*_API_KEY`, runs the `local` eval suite, runs
`pytest -m live|paid`, runs an `openclaw` subcommand that could start the agent, or a
`make` target named live or paid. Consent is per window (default 15 minutes), granted
for a run the human has seen the exact command for.

Standing rules from the lessons: a paid run executes the documented command exactly,
never an equivalent; if the documented command does not fit, that is a finding to
bring to the human before spending. Costs are recorded from the provider's console,
never from an estimate. Long paid runs go in the background under an untimed
`caffeinate -dims`. The run is traced before its output is parsed, so a billed call
that fails to parse still leaves a record.

Enforced by: the same hook with a `paid` consent token. Code-level guards arrive with
the code that makes calls: the eval runner (WO-005) refuses the `local` suite without
an explicit flag, and any module that calls a model checks a consent function in
`src/idx_agent/safety/` before the first call. Proven by `tests/test_guards.py`.

## 3. Never touch the enforcement without human consent
Covered: `scripts/gates/`, `scripts/guards/`, `.claude/settings.json` and
`.claude/settings.local.json` (any location), `.github/workflows/`,
`.pre-commit-config.yaml`, `.gitignore`. Editing any of them needs a `gates` consent
token, and the PR must say what changed and why.

Never, with no token that unlocks it: creating or editing a consent token, running
`scripts/guards/consent.sh`, `git commit --no-verify` or `-n`, `SKIP=` around a commit,
`pre-commit uninstall`, moving `core.hooksPath`, adding the `deletion-approved` label.

Enforced by: the hook (`gates` token, and a refuse list), the `permissions.deny` list in
`.claude/settings.json`, and gate 4 in CI. Proven by `tests/test_guards.py`.

## 4. Git discipline
- One branch per work order (`wo-NNN-<short-name>`), or `chore-<name>` for repo work,
  in a worktree at `../worktrees/<branch>`. Never commit on `main`.
- `git add <explicit paths>`, never `git add -A` or `git add .` from the main checkout.
- No `git stash` (it is shared across worktrees and eats other agents' work). To prove a
  test fails at HEAD, save a patch file, `git apply -R` it, run the test, re-apply.
- PR into `main`; merge only on green CI; then remove the worktree and delete the branch.
- At most two or three concurrent agents when `main` requires up-to-date checks; split
  work so agents touch different files.

## 5. Verification discipline
- A control is verified where it is used, not where it was configured. A "read-only"
  step proves it cannot write; a "no-cost" step proves nothing was billed.
- A guard is not trusted until it has been shown to fail on a case where it should fail.
  Every gate in this repo has such a test; WO-000 proved each one on a throwaway branch.
- Fixtures that stand in for an external shape (an API response, a table) come from the
  contract or a captured real response, never from what the code under test expects.
- When an existing artifact gains a new use (it starts being counted, enforced on, graded
  from, or cited), read its producer first: can it drop, truncate, or overwrite records?
- Before changing anything that writes run artifacts, copy the irreplaceable ones outside
  the working tree and confirm the copy exists.

## 6. Evidence discipline
- `docs/EVIDENCE_LOG.md`, eval outputs, and run records are append-only. A re-run adds a
  record with its own identity; it never replaces one.
- Every number in a claim says how it was measured. Numbers are re-derived from the
  artifact, never quoted from an earlier summary.
- A generated label or judge score is an input to triage, not a verdict; read the
  underlying record before acting on it, and never relax a check to make a red go green.
- Unrecoverable losses are recorded as permanent, with what was lost.

## 7. Working with the human
- Ask before major decisions: a new gate, hook, workflow step, consent mechanism,
  directory convention, dependency, or external service. Batch the questions.
- Stop conditions in `CLAUDE.md` and the active work order are hard stops.
- Exactly one work order is active; its Status section is edited only in its own file.
- The independent review pass before a PR is a standing practice.

## Consent: how the human grants it
```
! scripts/guards/consent.sh delete          # 15-minute window for deletions
! scripts/guards/consent.sh paid 30         # 30-minute window for a paid run
! scripts/guards/consent.sh gates           # edit gates, guards, hooks, CI, .gitignore
! scripts/guards/consent.sh revoke paid     # end a window early
! scripts/guards/consent.sh status
```
Typed in the Claude Code prompt with the leading `!` (which runs it as the human), or in
another terminal. Tokens live in `.local/consent/` (gitignored) and every grant, use,
block, and refusal is appended to `.local/consent/audit.log`. In CI the equivalent of a
`delete` token is the `deletion-approved` label on the PR.

If the hook is not active in a session (settings changed after start), the human opens
`/hooks` once or restarts Claude Code. The commit gate and CI hold either way.

## Where these rules come from
Most are distilled from the findings of the incident-commander project (an earlier agent
by the same author): a read-only stage that wrote, a budget enforced against an estimate,
a fix whose verification erased the evidence, a guard whose tests encoded its own
assumption, a `git stash` that ate a parallel agent's work, and a `git add -A` that
swept 342 files into a six-line PR. The agent-local digest lives in
`.local/lessons/incident-commander.md` (gitignored) and the decision record is
`docs/adrs/0002-agent-guardrails.md`.
