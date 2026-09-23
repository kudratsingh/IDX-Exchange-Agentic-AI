"""The Claude Code guard must block what docs/AGENT_RULES.md forbids, and nothing else.

Every command in DELETE, PAID, GATES and NEVER below was either designed in or found by
an independent review as a bypass; each is a regression case. ALLOWED holds the daily
workflow commands that must stay frictionless.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "guards"))

import consent_token as ct  # noqa: E402
import guard  # noqa: E402

GUARD = ROOT / "scripts" / "guards" / "guard.py"


@pytest.fixture(autouse=True)
def isolated_consent(tmp_path, monkeypatch):
    """Every test gets an empty consent dir and a fixed project root."""
    monkeypatch.setenv("IDX_CONSENT_DIR", str(tmp_path / "consent"))
    monkeypatch.setenv("IDX_PROJECT_ROOT", str(ROOT))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(ROOT)
    return tmp_path / "consent"


def kinds(findings):
    return sorted({f.kind for f in findings})


ALLOWED = [
    "ls -la",
    "git status && git log --oneline -3",
    "pytest -q tests/test_smoke.py",
    "pytest -k test_delete_from",
    "rm -rf /private/tmp/claude-501/session/scratchpad/venv-clean",
    "rm -rf .venv .pytest_cache src/idx_agent.egg-info",
    "rm -f src/idx_agent/__pycache__/x.pyc .coverage",
    "find . -name __pycache__ -exec rm -rf {} +",
    "find . -name '*.pyc' -delete",
    "git branch -d wo-000-repo-bootstrap",
    "git push origin --delete wo-000-repo-bootstrap",
    "git push -u origin wo-004-search",
    "git worktree add ../worktrees/wo-004-search -b wo-004-search main",
    "git worktree remove ../worktrees/wo-000-close",
    "git restore --staged tests/test_x.py",
    "git clean -n",
    "git clean -nd",
    "git stash list",
    "git checkout -b feat-x main",
    "git checkout wo-001-x --",
    "git commit -m 'feat: x' -F msg.txt",
    "git commit -m 'remove -n flag from parser'",
    "git commit -m 'docs: explain why --no-verify is banned'",
    "git commit --amend -F msg.txt",
    "git commit -q -F - <<'EOF'\nfeat: x\n\n- grep -n usage\nEOF",
    "git pull --ff-only",
    "gh pr create --base main --head x --title t --body b",
    "gh pr merge 3 --merge",
    "gh pr list --label deletion-approved",
    "gh pr view 3 --json labels",
    "python3 scripts/gates/pii_scan.py --all-tracked",
    "python3 scripts/gates/pii_scan.py --all-tracked > /tmp/out.txt",
    "cat scripts/guards/guard.py | head",
    "sed -n '1,5p' scripts/gates/forbidden_paths.py",
    "git diff scripts/gates/",
    "git add .gitignore scripts/gates/new.py",
    "grep -n 'no-verify' CLAUDE.md",
    "grep -rn 'import openai' src/",
    "cat docs/AGENT_RULES.md | grep api.openai.com",
    "grep -rn 'DELETE FROM' src/",
    "docker compose down",
    "docker compose up -d",
    "make evals",
    "make test",
    "python -m evals.run --suite ci",
    "pip install -e '.[dev]'",
    "pip install openai anthropic",
    "python3 -c \"print('drop table')\"",
    "python3 -c \"open('/tmp/x','w').write('hi')\" && cat .gitignore",
    "openclaw --version",
    "openclaw doctor",
    "openclaw gateway status",
    "caffeinate -i -d -t 14400",
    "echo 'note' >> docs/EVIDENCE_LOG.md",
    "mysql -e 'SELECT COUNT(*) FROM rets_property'",
    "ls .local/consent",
    "cat .local/consent/audit.log",
    "mkdir -p .local/lessons",
    "ruff check --fix scripts/guards/consent_token.py",
    "mv evals/cases/a.yaml evals/cases/b.yaml",
    "cd /tmp/x && python3 - <<'EOF'\nprint('hi')\nEOF",
    "~/.local/bin/uv --version",
    "ls 2>&1 | head",
]
DELETE = [
    "rm -rf data/",
    "rm notes.md",
    'rm -rf "$DIR"',
    "rm -r ./data",
    "rm -rf ./context/..",
    "rm -rf /tmp/../Users/x/data",
    "git clean -fdx",
    "git clean -fd --dry-run --no-dry-run",
    "git reset --hard HEAD~1",
    "git reset --keep HEAD~3",
    "git checkout -- .",
    "git checkout .",
    "git checkout HEAD~1 -- .",
    "git checkout HEAD~1 src/idx_agent/x.py",
    "git checkout -f",
    "git switch --discard-changes main",
    "git restore src/idx_agent/db/pool.py",
    "git restore -W src/x.py",
    "git stash",
    "git stash pop",
    "git push -f origin main",
    "git push --force-with-lease origin wo-004",
    "git push --force-with-lease=x origin wo-004",
    "git push origin +main",
    "git push origin :main",
    "git push origin --delete main",
    "git push --mirror origin",
    "git branch -D wo-004",
    "git branch -df wo-004",
    "git branch --delete --force wo-004",
    "git worktree remove --force ../worktrees/x",
    "git rm tests/test_smoke.py",
    "git rm --cached tests/test_smoke.py",
    "git -C ../x clean -fdx",
    "git reflog delete HEAD@{1}",
    "git reflog expire --expire=now --all",
    "git update-ref refs/heads/main HEAD~5",
    "git read-tree -u --reset HEAD",
    "git rebase --exec 'rm -rf data' HEAD~1",
    "git -c alias.x='!rm -rf data' x",
    "find . -name '*.log' -delete",
    "find data -type f -exec rm {} \\;",
    "ls *.pyc | xargs rm",
    "unlink docs/EVIDENCE_LOG.md",
    "trash data",
    "mv data/ /tmp/data-backup",
    "mv /tmp/empty data/dump.sql",
    "mv -t /tmp data",
    "mv ~/.claude/projects/x/memory /tmp/m",
    "rm -rf ~/.claude/projects/x/memory",
    "rsync -a --delete /tmp/empty/ data/",
    "cp /dev/null docs/EVIDENCE_LOG.md",
    "cp /tmp/x evals/cases/property_search.yaml",
    "dd if=/dev/null of=docs/EVIDENCE_LOG.md",
    "tee data/x < /dev/null",
    "sed -i '' '1,$d' docs/EVIDENCE_LOG.md",
    "perl -i -ne '' docs/EVIDENCE_LOG.md",
    "mysql idx -e 'DROP TABLE rets_property'",
    'mysql -e "delete from\\`rets_property\\`"',
    "mysql -e 'UPDATE rets_property SET ListPrice=0'",
    "mysql -e 'RENAME TABLE rets_property TO x'",
    "mycli -e 'DROP TABLE x'",
    "psql -c 'TRUNCATE california_sold'",
    "python3 -c \"cur.execute('DELETE FROM rets_property')\"",
    "python3 -c \"import shutil; shutil.rmtree('data')\"",
    "python3 -c \"import os; os.remove('docs/EVIDENCE_LOG.md')\"",
    "perl -e 'unlink \"docs/EVIDENCE_LOG.md\"'",
    'ruby -e \'require "fileutils"; FileUtils.rm_rf("data")\'',
    "node -e \"require('fs').rmSync('data',{recursive:true})\"",
    "python3 -c \"open('docs/EVIDENCE_LOG.md','w').write('')\"",
    "docker compose down -v",
    "docker-compose down -v",
    "docker volume rm idx_mysql",
    "docker exec mysql mysql -e 'DROP TABLE x'",
    ": > docs/EVIDENCE_LOG.md",
    "cat > docs/EVIDENCE_LOG.md <<'EOF'\n| a |\nEOF",
    "echo x > evals/cases/property_search.yaml",
    "echo x >| docs/EVIDENCE_LOG.md",
    "truncate -s 0 data/dump.sql",
    "shred -u data/dump.sql",
    "caffeinate -i rm -rf data/",
    "timeout -s KILL 5 rm -rf data",
    "watch -n1 rm -rf data",
    "parallel rm -rf ::: data",
    "bash -c 'rm -rf data'",
    'sh -c "rm -rf evals/cases"',
    "eval rm -rf data",
    "(rm -rf data)",
    "{ rm -rf data; }",
    "if true; then rm -rf data; fi",
    "for d in data; do rm -rf $d; done",
    "true & rm -rf data",
    "x=$(rm -rf data)",
    "echo `rm -rf data`",
    "cd ../worktrees/x && rm -rf evals/cases",
    "gh api -X DELETE repos/o/r/git/refs/heads/main",
    "gh release delete v1 --yes",
]
PAID = [
    "python -m evals.run --suite local",
    "python -m evals.run --suite=local",
    'python -m evals.run --suite "local"',
    "curl https://api.openai.com/v1/models",
    "curl -X POST https://api.anthropic.com/v1/messages",
    "python3 -c 'from openai import OpenAI; OpenAI().embeddings.create(input=[])'",
    "python3 -c 'import anthropic'",
    "python3 -c \"__import__('openai')\"",
    "python -m openai api chat.completions.create -m gpt -g user hi",
    "openai api chat.completions.create -m gpt -g user hi",
    "claude -p 'hello'",
    "OPENAI_API_KEY=sk-x python scripts/embed.py",
    "export OPENAI_API_KEY=sk-x",
    "source .env && python x.py",
    ". ./.env; python x.py",
    "openclaw run",
    "openclaw",
    "openclaw chat --to 555-010-0100",
    "openclaw gateway start",
    "npx openclaw run",
    "pnpm exec openclaw agent",
    "bunx openclaw run",
    "pytest -m live",
    "pytest -mlive",
    "make eval-live",
    "python3 - <<'EOF'\nfrom anthropic import Anthropic\nEOF",
]
GATES = [
    "sed -i 's/x/y/' scripts/gates/pii_scan.py",
    "sed -i '' 's/x/y/' scripts/gat*/pii_scan.py",
    "perl -pi -e 's/x/y/' scripts/gates/pii_scan.py",
    "cat > scripts/guards/guard.py <<'EOF'\nprint(1)\nEOF",
    "cp /tmp/settings.json .claude/settings.json",
    "echo 'data/' >> .gitignore",
    "tee .pre-commit-config.yaml < /tmp/x",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('scripts/gates/x.py').write_text('')\nEOF",
    "python3 -c \"import pathlib; pathlib.Path('.claude','settings.local.json').write_text('{}')\"",
    "touch .github/workflows/deploy.yml",
    "rm scripts/gates/forbidden_paths.py",
    "sed -i '' 's/protected-deletions/x/' tests/test_guards.py",
    "cd scripts/gates && echo x > pii_scan.py",
    "cd .claude && echo '{}' > settings.local.json",
    "echo '' > .git/hooks/pre-commit",
    "chmod -x .git/hooks/pre-commit",
    "mv .git/hooks/pre-commit /tmp/",
    "patch -p1 < /tmp/weaken.patch",
    "git mv scripts/gates/pii_scan.py scripts/gates/old.py",
]
NEVER = [
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "git commit -nm x",
    "git commit -anm x",
    "git commit -m x --no-verify",
    "git commit --no-v -m x",
    "git commit --no-veri -m x",
    "git merge --no-verify x",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git -c core.HooksPath=/dev/null commit -m x",
    "git --config-env=core.hooksPath=HP commit -m x",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
    "SKIP=protected-deletions git commit -m x",
    "SKIP=x git -C . commit -m x",
    "git config core.hookspath /tmp",
    "git config core.hooksPath /tmp/hooks",
    "gh pr edit 3 --add-label deletion-approved",
    "L=deletion-approved; gh pr edit 3 --add-label $L",
    "gh pr edit 3 --add-label deletion-appr*ved",
    "gh pr create --label deletion-approved --title t --body b",
    "gh api repos/o/r/issues/3/labels -f 'labels[]=deletion-approved'",
    "gh api repos/o/r/issues/3/labels --input /tmp/l.json",
    "gh api graphql -f query='mutation { addLabelsToLabelable(input: {}) }'",
    "gh label create deletion-approved",
    "gh repo delete --yes",
    "pre-commit uninstall",
    "touch .local/consent/delete",
    "scripts/guards/consent.sh delete",
    "bash scripts/guards/consent.sh paid 60",
    "python3 scripts/guards/consent_token.py grant delete",
    "python3 -c \"import sys; sys.path.insert(0,'scripts/guards'); import consent_token; consent_token.grant('delete')\"",
    "python3 -c \"from consent_token import grant; grant('delete')\"",
    "python3 -c \"import pathlib; pathlib.Path('.local','consent','paid').write_text('9')\"",
    "echo 99999999999 > .local/consent/paid",
    "cd .local && echo 99999999999 > consent/delete",
    "echo 9999999999 > .local/con*/paid",
    "D=.local/cons; echo 9999999999 > ${D}ent/paid",
    "ln -s .local /tmp/l",
    "echo 9999999999 > /tmp/l/consent/paid",
    "IDX_CONSENT_DIR=/tmp/f git commit -m x",
    "CLAUDE_PROJECT_DIR=/tmp/fake git commit -m x",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_ordinary_commands_pass(command):
    assert guard.classify_bash(command) == []


@pytest.mark.parametrize("command", DELETE)
def test_destructive_commands_need_delete_consent(command):
    assert "delete" in kinds(guard.classify_bash(command))


@pytest.mark.parametrize("command", PAID)
def test_paid_commands_need_paid_consent(command):
    assert "paid" in kinds(guard.classify_bash(command))


@pytest.mark.parametrize("command", GATES)
def test_editing_the_enforcement_needs_gates_consent(command):
    assert "gates" in kinds(guard.classify_bash(command))


@pytest.mark.parametrize("command", NEVER)
def test_some_commands_are_never_allowed(command):
    assert "consent" in kinds(guard.classify_bash(command))


FILE_CASES = [
    ("Write", "scripts/gates/new_gate.py", ["gates"]),
    ("Edit", "scripts/guards/guard.py", ["gates"]),
    ("Edit", "scripts/guards/consent_token.py", ["gates"]),
    ("Edit", ".claude/settings.json", ["gates"]),
    ("Write", ".claude/settings.local.json", ["gates"]),
    ("Write", "/Users/someone/.claude/settings.json", ["gates"]),
    ("Write", "~/.claude/settings.json", ["gates"]),
    ("Edit", ".github/workflows/ci.yml", ["gates"]),
    ("Edit", ".gitignore", ["gates"]),
    ("Edit", ".pre-commit-config.yaml", ["gates"]),
    ("Write", ".git/hooks/pre-commit", ["gates"]),
    ("Edit", ".git/config", ["gates"]),
    ("Edit", "tests/test_guards.py", ["gates"]),
    ("MultiEdit", "tests/test_protected_deletions.py", ["gates"]),
    ("Write", ".local/consent/delete", ["consent"]),
    ("Write", "./.local/consent/delete", ["consent"]),
    ("Write", "docs/EVIDENCE_LOG.md", ["delete"]),
    ("Edit", "docs/EVIDENCE_LOG.md", []),
    ("Write", ".local/lessons/notes.md", []),
    ("Write", "evals/cases/brand_new_case_file.yaml", []),
    ("Edit", "src/idx_agent/parser/rules.py", []),
    ("Write", "docs/ARCHITECTURE.md", []),
    ("Write", "/Users/someone/.claude/projects/x/memory/note.md", []),
    ("Write", "", []),
]


@pytest.mark.parametrize("tool, path, expected", FILE_CASES)
def test_file_tools(tool, path, expected):
    assert kinds(guard.classify_file(tool, path)) == expected


def test_file_tool_findings_do_not_depend_on_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert kinds(guard.classify_file("Write", "docs/EVIDENCE_LOG.md")) == ["delete"]
    assert kinds(guard.classify_file("Edit", "scripts/gates/x.py")) == ["gates"]


def test_tokens_are_absent_expired_forged_or_valid(isolated_consent):
    assert not ct.is_valid("delete")
    ct.grant("delete", minutes=15, now=1000.0)
    assert ct.is_valid("delete", now=1000.0 + 14 * 60)
    assert not ct.is_valid("delete", now=1000.0 + 16 * 60)
    (isolated_consent / "paid").write_text("not a number\n")
    assert not ct.is_valid("paid")
    (isolated_consent / "paid").write_text("inf\n")
    assert not ct.is_valid("paid")
    (isolated_consent / "paid").write_text(f"{time.time() + 10 * 24 * 3600:.0f}\n")
    assert not ct.is_valid("paid")
    assert ct.revoke("delete") is True
    assert ct.revoke("delete") is False
    assert not ct.is_valid("delete", now=1000.0)
    with pytest.raises(ValueError):
        ct.token_path("root")


def test_grant_clamps_minutes_and_logs_with_redaction(isolated_consent):
    ct.grant("gates", minutes=10_000, now=0.0)
    assert ct.expiry("gates") == ct.MAX_MINUTES * 60
    ct.log("block", "paid", "OPENAI_API_KEY=sk-secret python x.py\nsecond line")
    log = (isolated_consent / "audit.log").read_text()
    assert "grant\tgates" in log
    assert "sk-secret" not in log and "OPENAI_API_KEY=***" in log
    assert "second line" in log and "\nsecond" not in log


def test_decide_allows_only_with_the_matching_token():
    delete = [guard.Finding("delete", "rm of data/")]
    code, message = guard.decide(delete, "rm -rf data/")
    assert code == 2 and "consent.sh delete" in message

    ct.grant("paid", minutes=5)
    code, _ = guard.decide(delete, "rm -rf data/")
    assert code == 2, "a paid token must not unlock a delete"

    ct.grant("delete", minutes=5)
    code, message = guard.decide(delete, "rm -rf data/")
    assert code == 0 and "allowed" in message

    mixed = delete + [guard.Finding("gates", "x")]
    code, message = guard.decide(mixed, "x")
    assert code == 2 and "consent.sh gates" in message

    code, message = guard.decide([guard.Finding("consent", "x")], "touch token")
    assert code == 2 and "No consent token unlocks this" in message


def run_guard(payload, env):
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )


def test_guard_process_end_to_end(isolated_consent):
    env = {
        **os.environ,
        "IDX_CONSENT_DIR": str(isolated_consent),
        "IDX_PROJECT_ROOT": str(ROOT),
    }
    bash = {"tool_name": "Bash", "tool_input": {"command": "rm -rf data/"}}
    result = run_guard(json.dumps(bash), env)
    assert result.returncode == 2
    assert "consent.sh delete" in result.stderr

    ok = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    result = run_guard(json.dumps(ok), env)
    assert result.returncode == 0 and result.stderr == ""

    ct.grant("delete", minutes=5)
    result = run_guard(json.dumps(bash), env)
    assert result.returncode == 0
    assert "allowed by human consent" in result.stdout

    ct.grant("delete", minutes=5, now=time.time() - 3600)
    result = run_guard(json.dumps(bash), env)
    assert result.returncode == 2, "an expired token must not unlock"

    write = {"tool_name": "Write", "tool_input": {"file_path": ".local/consent/paid"}}
    assert run_guard(json.dumps(write), env).returncode == 2

    other = {"tool_name": "Read", "tool_input": {"file_path": "data/x.csv"}}
    assert run_guard(json.dumps(other), env).returncode == 0

    result = run_guard("this is not json", env)
    assert result.returncode == 2 and "failed closed" in result.stderr

    huge = {"tool_name": "Bash", "tool_input": {"command": "git commit " * 20000}}
    started = time.monotonic()
    result = run_guard(json.dumps(huge), env)
    assert result.returncode == 2 and time.monotonic() - started < 5

    log = (isolated_consent / "audit.log").read_text()
    assert "block\tdelete" in log and "use\tdelete" in log
