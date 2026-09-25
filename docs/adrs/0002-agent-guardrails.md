# ADR-0002: Agent guardrails with human consent tokens

**Status:** accepted
**Date:** 2026-09-23
**Work order:** none (repo chore before WO-001), requested by the human

## Context
The coding agent runs with broad shell access and, since WO-000, may merge its own PRs on
green CI. The human's earlier agent project (incident-commander) recorded what that
freedom costs when nothing mechanical stands behind a rule: an offline re-run that
overwrote a paid live run's records, a budget enforced against an estimate that was 2.4x
under the real bill, a `git stash` that ate a parallel agent's work. The human asked for
rules and gates so the agent can never delete experimental, evaluation, application,
debugging, database, or agent data, and never executes a paid API run, without explicit
consent, and asked that none of it slow down ordinary merges.

## Decision
Three layers, each with a test that proves it blocks. The first two are tripwires
that catch the common spellings of an accident; the real boundaries are the branch
ruleset on `main` (no direct or force pushes, PR with both checks required), provider
API keys kept out of the agent's environment, and human review of each PR.
1. A Claude Code PreToolUse hook (`scripts/guards/guard.py`, wired in the tracked
   `.claude/settings.json` for Bash, Write, Edit, NotebookEdit) classifies each tool call
   as `delete`, `paid`, `gates`, or never-allowed, and exits 2 unless a matching human
   consent token exists. It fails closed.
2. A fourth commit gate (`scripts/gates/protected_deletions.py`) blocks any staged
   deletion of a tracked file without a `delete` token, and in CI blocks PR deletions
   without the `deletion-approved` label. Renames and `.gitkeep` pass.
3. Consent tokens: files in the gitignored `.local/consent/` created only by the human
   with `scripts/guards/consent.sh <kind> [minutes]` (typed with a leading `!` in the
   prompt, or in another terminal). A token is a time window (15 minutes by default,
   240 at most), not a per-command grant, because one deletion is two commands (`git rm`
   then `git commit`). Every grant, use, block, and refusal is appended to an audit log.
   The agent's Bash tool is refused when it tries to run the script or touch the
   directory, and the transcript would show the attempt. An independent review found
   several ways to phrase around the classifier; each is now a regression test, and the
   docs say plainly that it is a tripwire.

`docs/AGENT_RULES.md` states the rules in words; `.local/` (gitignored) holds the
agent-local lessons digest and the consent state. Rejected: consent through a session
environment variable (proof of the human's hand, but per session and needing a restart);
rules without enforcement (zero friction, zero protection); a per-command one-shot token
(broken by the two-command deletion flow); storing agent notes in `context/` (that
folder is the human's).

## Consequences
Ordinary commits, PRs, and merges are unchanged: gate 4 is a sub-second `git diff` that
only speaks when a deletion is staged, and the hook adds milliseconds per tool call. A
deletion, a paid run, or an edit to the enforcement now costs the human one short
command, and leaves a log line. The agent cannot self-approve: no token unlocks creating
a token, skipping the hooks, or adding the CI label in the spellings it knows. Editing the
gates, guards, hooks, CI, or `.gitignore` needs a `gates` token, which is deliberate
friction. Hooks defined in
project settings only load when the session starts (or after `/hooks`), so the commit
gate, the ruleset, and CI are the layers that hold in a session that predates the
settings file. The `deletion-approved` label can be added by anyone holding the repo
token, so it is a speed bump; the human's PR review is the check.
Code-level guards for paid calls (a consent check before the first model call, and an
eval runner that refuses the `local` suite without a flag) are owed by WO-004 and WO-005.

## What would reverse this
A month of audit-log lines showing the human granting `delete` or `gates` several times
a day for routine work, which would mean the classifier is too broad and the patterns
should be narrowed. Or Claude Code shipping a native per-action approval that carries
the human's identity, which would replace the token file.

## Amendment 2026-09-25: a paid token covers one run of one command

**What changed.** `delete` and `gates` tokens stay time windows. A `paid` token is now
bound to one exact command line and a ceiling on provider calls; the hook admits that
command once, and the run spends the token the moment it starts:
- Token file format v2: the first line is the literal `paid-token-v2`, then `key=value`
  lines (`expiry`, `command`, `max_calls`, `granted`; once admitted, `admitted` and
  `run_id`; once spent, `consumed` and `pid`). A checkout from before this amendment
  reads line 1 as its expiry, fails, and sees no paid token at all, so an old guard can
  never treat a v2 token as a plain window; and a one-line token never unlocks a paid
  path here. The human mints it with `consent.sh paid [minutes] --command "<argv words>"
  --max-calls <N>`, which takes the same lock as admission and consumption.
- `scripts/guards/consent_token.py` holds the only implementation: `command_matches`
  (basename of the first word, any python spelling as `python`, leading `env` and
  `NAME=value` words dropped, then exact word-for-word equality), `admit_paid` (the
  hook's once-only admission, under a lock), `consume_paid` (checks and rewrites the
  token atomically under the same lock, keeping the admitted `run_id`; a second call is
  refused as `consumed`), and `paid_token_status`.
- The hook admits a paid finding only when the token names the argv of the command that
  carried it and is unexpired, not yet admitted, and unspent; the same command a second
  time is refused as `admitted`. Heredocs, substitutions, inline code, nested shells,
  `PATH`/`PYTHON*`/`LD_*`/`DYLD_*` env words, inline API keys, and `.env` sourcing carry
  no argv and are never unlocked; nor is writing a provider SDK import or paid host into
  a file outside the known paid modules and `tests/`. The block message prints the mint
  command for the refused argv.
- In the code, every paid path calls one check (`start_paid_run()` in
  `src/idx_agent/safety/consent.py`, which loads the guard's reader by path, so no rule
  is mirrored) and counts each provider request against the ceiling before sending it.
  A refusal, a request-shape change, or a driver error ends the run and spends the
  token; nothing retries or adapts.

**Why.** Under a single paid window, five routing runs went to the provider one after
another, continuing after a stop condition had been hit. The window measured time, not
intent: it approved "paid calls for a while" when the human meant "this run". Binding
the token to the command line, admitting it once, and spending it at start makes each paid run a separate, visible human decision, and the
call ceiling bounds what one decision can cost.

**Consequences.** Every paid run costs the human one mint command, including a repeat
of the same command; the block message and the eval runner's notice print it ready to
copy, so the friction is one paste. A run that stops early still spends its token, and
the minutes bound the run as well as its start. Known limit: a command with no
code-level check (a raw `curl` to a provider, the `openai` CLI, `openclaw`) is admitted
once by the hook and cannot be admitted again, but the hook cannot count its calls, so
the ceiling means nothing for it; our own paid paths count every request. The long-
lived tool server spends one token, minted for its own command line, on its first
provider call and stops calling once the ceiling is reached. The earlier rejection of a
per-command one-shot token still holds for `delete`, where one deletion is two commands.
