# Rules for the coding agent

How the agent that builds this repo (and every subagent it spawns) must behave. These
rules are about the agent's own conduct; `SAFETY_INVARIANTS.md` is about the product.
Each rule names how it is enforced and what that enforcement can and cannot do. The
lessons this file is built on (last section) are mostly about controls that were
believed rather than verified.

## What the enforcement is, and is not
Two mechanical layers back these rules inside the agent's session and at commit time:
a Claude Code hook that classifies each shell command or file write from its text, and a
commit gate that lists staged deletions. Both are **tripwires**: they catch the common
spellings of an accidental deletion, paid call, or edit to the enforcement, and they
fail closed on errors. Neither is a security boundary. A text classifier can be phrased
around (a nested shell, an interpreter one-liner, a variable that hides a path), and
anything that runs with the agent's own credentials cannot be told apart from the human.

The real boundaries are:
- **The branch ruleset on `main`** (set by the human on GitHub): no direct pushes, no
  force pushes, no deletion of the branch, a pull request with both CI checks green
  before anything lands. This is what makes a red gate stop a merge.
- **Provider API keys stay out of the agent's environment.** They live only where the
  tool-server process reads them. An agent without a key cannot spend, whatever it types.
- **Human review of every PR**, with deletions and enforcement edits called out.
- **The audit log** in `.local/consent/audit.log`: every grant, use, block, and refusal
  is a line, so a bypass leaves a trace even when it succeeds.

## 1. Never delete or discard without human consent
Protected: every tracked file; everything under `data/`, `context/`, `coordination/`;
evaluation material (`evals/cases/`, `evals/runs/`, `evals/reports/`, `experiments/`,
`docs/EVIDENCE_LOG.md`); run artifacts, logs, and session stores; the database and its
tables; the agent's own memory and settings under any `.claude/` directory.

Covered spellings: `rm` outside scratch space and rebuildable caches, `unlink`, `trash`,
`find -delete`, `xargs rm`, `git clean`, `git reset --hard|--merge|--keep`, `git
checkout`/`restore`/`switch` that discards paths, `git stash`, force pushes and forcing
refspecs, deleting `main`, `git branch -D`, forced worktree removal, `git rm`, history
rewriting, `mv`/`cp`/`rsync`/`dd`/`tee` that overwrite or move data or evidence,
`shred`, `truncate`, in-place `sed`/`perl` on evidence, `docker ... down -v` and volume
removal, `DROP`/`TRUNCATE`/`DELETE FROM`/`UPDATE`/`RENAME`/`ALTER ... DROP`,
truncating an evidence file with `>` or `>|`, interpreter one-liners that call
`rmtree`, `os.remove`, `unlink`, `rmSync`, `rm_rf`, a subprocess, or open a protected
file for writing, and the Write tool overwriting an existing evidence or data file.
Nested `bash -c`, `eval`, subshells, `&`, `$( )`, backticks, `git rebase --exec`, and
git aliases are inspected recursively.

Allowed without consent: deleting inside the session scratch directory or `/tmp`;
removing `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `*.egg-info`, `build/`,
`dist/`, `.coverage`; `git branch -d` and `git push --delete` of a feature branch;
renames, including within one evidence folder; `.gitkeep` files; appending (`>>`) to
the evidence log.

Enforced by: `scripts/guards/guard.py` (hook on Bash, Write, Edit, MultiEdit,
NotebookEdit) with a `delete` consent token; `scripts/gates/protected_deletions.py`
(gate 4) at commit with the same token, read from the checkout that owns the git common
dir and never from an environment variable; in CI on pull requests with the
`deletion-approved` label. Proven by `tests/test_guards.py` and
`tests/test_protected_deletions.py`, which hold every bypass found in review as a
regression case. Known limit: gutting a tracked file without deleting it commits as a
modification; the PR diff is the control. A label added after the last push is not
re-checked on later pushes.

## 2. Never spend money without human consent for that run
Covered spellings: a paid model or API host, importing or instantiating a model SDK,
`python -m openai|anthropic`, the `openai`, `anthropic`, and `claude` CLIs, passing or
exporting an `*_API_KEY`, sourcing a `.env`, the `local` eval suite, `--allow-paid` (the
index builders), `--judge-sheet`, `pytest -m live|paid`, an `openclaw` subcommand that
could start the agent (also via `npx`, `bunx`, `pnpm exec`), or a `make` target named
live or paid. Writing a provider SDK import or a paid host into a file outside the known
paid modules and `tests/` is blocked too. A script that hides the call some other way is
not caught by the hook; the code-level check and the missing key stop it.

**One token, one run.** A `paid` token is not a window: it names one exact command line
and a ceiling on provider calls. The hook admits that command once, and the run spends
the token the moment it starts. A second invocation, a changed flag, or a different
command needs a new token from the human, even inside the same minutes. The hook admits
a paid command only when the token names its argv exactly (the interpreter path and
leading `NAME=value` or `env` words aside) and is unexpired, not yet admitted, and
unspent. It never unlocks a heredoc, a `$(...)`, backtick or `<(...)` substitution,
`python -c` or other inline code, a nested shell, a leading `PATH=`, `PYTHON*=`,
`LD_*=` or `DYLD_*=` word, an inline `*_API_KEY=`, or sourcing a `.env`; a paid program
is run as one plain command, and our code reads its key from the environment itself. Every
paid path in the code (the eval runner's `local` suite, the index builders, the spike
script, the tool server) calls one check, `start_paid_run()` in
`src/idx_agent/safety/consent.py`, which spends the token through
`scripts/guards/consent_token.py`, and counts each provider request against the
ceiling before it is sent.

Standing rules from the lessons: a paid run executes the documented command exactly,
never an equivalent; if the documented command does not fit, that is a finding to bring
to the human before spending. Any provider refusal, request-shape change, or driver
error ends the run and spends the token; nothing adapts automatically, and the next
attempt is a new command the human mints a new token for. Costs are recorded from the
provider's console, never from an estimate. Long paid runs go in the background under
an untimed `caffeinate -dims`. The run is traced before its output is parsed, so a
billed call that fails to parse still leaves a record.

Enforced by: the hook with a `paid` token bound to the command, the one code-level check
above with its call ceiling, and keys kept out of the agent's environment. Proven by
`tests/test_guards.py` (token format, command matching, consumption, the hook) and
`tests/test_consent_gate.py` (the code-level budget).

## 3. Never touch the enforcement without human consent
Covered: `scripts/gates/`, `scripts/guards/`, `.claude/settings.json` and
`.claude/settings.local.json` (any location), `.git/hooks/`, `.git/config`,
`.github/workflows/`, `.pre-commit-config.yaml`, `.gitignore`, and the tests that pin
the gates and guards. Editing any of them, by any tool or by `cd`-ing into the folder
first, needs a `gates` token, and the PR must say what changed and why. `patch` needs
a `gates` token because its targets are unknown.

Never, with no token that unlocks it: creating or editing a consent token, running or
importing the consent scripts, setting `IDX_CONSENT_DIR`, `CLAUDE_PROJECT_DIR`, or
`IDX_PROJECT_ROOT` on a command, `git commit` with `--no-verify` in any spelling or
bundle (`-n`, `-nm`, `--no-v`), `git -c core.hooksPath`, `GIT_CONFIG_*` overrides,
`SKIP=` around a commit, `pre-commit uninstall`, labelling a pull request in any way,
deleting the repository.

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
  Every gate and guard here has such a test; WO-000 proved each gate on a throwaway
  branch, and the guard's review found and pinned its bypasses.
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
- When the hook blocks a call, report it and ask; do not look for another spelling.

## Consent: how the human grants it
```
! scripts/guards/consent.sh delete          # 15-minute window for deletions
! scripts/guards/consent.sh gates           # edit gates, guards, hooks, CI, .gitignore
! scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite local --allow-paid --category routing" --max-calls 40
                                            # one run of that command, at most 40 calls
! scripts/guards/consent.sh revoke paid     # end a window early
! scripts/guards/consent.sh status          # paid: the command, the ceiling, spent or not
```
Typed in the Claude Code prompt with the leading `!` (which runs it as the human), or in
another terminal. The minutes on a paid token bound both the wait for its run to start
and the run itself: the code ends the run when the token expires. The hook's block message and the eval runner's PAID notice print the exact
mint command for the call they refused, ready to copy with the ceiling filled in by the
human (the runner prints the ceiling its plan computed). Tokens live in `.local/consent/`
(gitignored) and hold an expiry no more than 240 minutes ahead; every grant, use,
consumption, block, and refusal is appended to
`.local/consent/audit.log` with secrets redacted. In CI the equivalent of a `delete`
token is the `deletion-approved` label on the PR, which any holder of the repo token can
add, so the human's review of the PR is what makes it meaningful.

Project hooks load when a Claude Code session starts. In a session started before the
settings file existed, the human opens `/hooks` once or restarts; the commit gate, the
ruleset, and CI hold either way.

## Where these rules come from
Most are distilled from the findings of the incident-commander project (an earlier agent
by the same author): a read-only stage that wrote, a budget enforced against an estimate,
a fix whose verification erased the evidence, a guard whose tests encoded its own
assumption, a `git stash` that ate a parallel agent's work, and a `git add -A` that
swept 342 files into a six-line PR. The agent-local digest lives in
`.local/lessons/incident-commander.md` (gitignored) and the decision record is
`docs/adrs/0002-agent-guardrails.md`.
