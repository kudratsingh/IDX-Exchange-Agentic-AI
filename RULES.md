# RULES — read before every commit

Four rules. Each is enforced by a pre-commit hook and again by CI on every push; the
fourth is also enforced inside the coding agent's session by a Claude Code hook.
`--no-verify` does not help: CI runs the same gates and fails the push.

1. **No data.** Nothing from `data/`, `context/`, or `coordination/`. No dumps, CSVs, row
   exports, embeddings, indexes, logs, session or auth files, `.env`, PDFs. The only `.sql`
   files allowed are migrations (`scripts/migrations/`) and synthetic fixtures (`tests/fixtures/`).
2. **No text from the handbook, the Primer, or the Trestle metadata.** Column names are fine;
   sentences, tables, and code from those documents are not. Write it in your own words.
3. **No secrets, no people.** No API keys or passwords. No agent names, emails, or phone
   numbers anywhere: replies, fixtures, screenshots, logs, docs.
4. **No deletion, no spending, no gate edits without human consent.** The coding agent
   never deletes tracked files, data, run artifacts, or its own memory, never calls a paid
   model or API, and never edits the gates, guards, hooks, CI, or `.gitignore`, unless a
   human has granted a consent token for it. Full text: `docs/AGENT_RULES.md`.

## What runs at commit (`.pre-commit-config.yaml`)
| Gate | Catches |
|---|---|
| gitleaks, detect-private-key | keys, tokens, passwords |
| `scripts/gates/forbidden_paths.py` | rule 1, by path and extension |
| `scripts/gates/confidential_text.py` | rule 2: any 10-word window that matches the fingerprinted documents |
| `scripts/gates/pii_scan.py` | rule 3: emails and phone numbers (placeholders on example.com and 555 numbers pass) |
| `scripts/gates/protected_deletions.py` | rule 4: any staged deletion of a tracked file, unless a `delete` consent token exists (in CI: the `deletion-approved` PR label) |

Inside the coding agent's session (not at commit): `scripts/guards/guard.py`, a Claude Code
hook from `.claude/settings.json`, blocks destructive commands, paid model or API calls, and
edits to the enforcement unless a human consent token exists, and refuses `--no-verify`,
`git stash`, and any attempt to grant itself consent. It is a tripwire for accidental
spellings; the branch ruleset on `main` and human review are the boundary.
| check-added-large-files | anything over 500 KB |

CI (`.github/workflows/ci.yml`) runs the same gates on every tracked file, plus a gitleaks
scan of the whole history. GitHub push protection blocks secrets at push.

## Setup, once
```
pip install pre-commit pypdf && pre-commit install
python scripts/gates/build_fingerprints.py     # needs the three documents at the paths in scripts/gates/sources.txt
```
Then in the GitHub repo: Settings -> Code security -> Secret scanning -> enable Push protection.
Commits are blocked until `scripts/gates/fingerprints.txt` exists. That is deliberate.

## When a gate blocks you
- **forbidden path:** the file does not belong here. Move it to `data/`, `context/`, or `coordination/`.
- **confidential text:** reword the flagged window. A reviewed false positive goes in
  `scripts/gates/allowed_shingles.txt` by hash, with a comment saying why.
- **pii:** replace with a placeholder (`replace-me@example.com`, `555-010-0100`) or remove it.
- **secret:** remove it, rotate the key now, and if it was ever committed rewrite the history the same day.
- **protected deletion or guard:** if the deletion, paid run, or gate edit is intended, the human
  grants a window with `! scripts/guards/consent.sh delete|paid|gates` (or adds the
  `deletion-approved` label to the PR). Otherwise, do not do it.
- Never edit `scripts/gates/` to make a gate pass. Fix the content.
