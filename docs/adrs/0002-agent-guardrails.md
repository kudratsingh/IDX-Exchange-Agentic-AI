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
Three layers, each with a test that proves it blocks:
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
   directory, and the transcript would show the attempt.

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
a token, skipping the hooks, or adding the CI label. Editing the gates, guards, hooks, CI,
or `.gitignore` needs a `gates` token, which is deliberate friction. Hooks defined in
project settings only load when the session starts (or after `/hooks`), so the commit
gate and CI are the layers that hold in a session that predates the settings file.
Code-level guards for paid calls (a consent check before the first model call, and an
eval runner that refuses the `local` suite without a flag) are owed by WO-004 and WO-005.

## What would reverse this
A month of audit-log lines showing the human granting `delete` or `gates` several times
a day for routine work, which would mean the classifier is too broad and the patterns
should be narrowed. Or Claude Code shipping a native per-action approval that carries
the human's identity, which would replace the token file.
