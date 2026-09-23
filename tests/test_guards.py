"""The Claude Code guard must block what docs/AGENT_RULES.md forbids, and nothing else."""

import json
import os
import pathlib
import subprocess
import sys

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
    return tmp_path / "consent"


def kinds(findings):
    return sorted({f.kind for f in findings})


ALLOWED = [
    "ls -la",
    "git status && git log --oneline -3",
    "pytest -q tests/test_smoke.py",
    "rm -rf /private/tmp/claude-501/session/scratchpad/venv-clean",
    "rm -rf .venv .pytest_cache src/idx_agent.egg-info",
    "rm -f src/idx_agent/__pycache__/x.pyc",
    "git branch -d wo-000-repo-bootstrap",
    "git push origin --delete wo-000-repo-bootstrap",
    "git worktree remove ../worktrees/wo-000-close",
    "git restore --staged tests/test_x.py",
    "git clean -n",
    "git commit -m 'feat: x' -F msg.txt",
    "git commit --amend -F msg.txt",
    "python3 scripts/gates/pii_scan.py --all-tracked",
    "cat scripts/guards/guard.py | head",
    "git diff scripts/gates/",
    "grep -n 'no-verify' CLAUDE.md",
    "docker compose down",
    "make evals",
    "python -m evals.run --suite ci",
    "pip install openai anthropic",
    "openclaw --version",
    "openclaw doctor",
    "caffeinate -i -d -t 14400",
    "echo 'note' >> docs/EVIDENCE_LOG.md",
    "mysql -e 'SELECT COUNT(*) FROM rets_property'",
    "ls .local/consent",
    "cat .local/consent/audit.log",
    "cd /tmp/x && python3 - <<'EOF'\nprint('hi')\nEOF",
]
DELETE = [
    "rm -rf data/",
    "rm notes.md",
    'rm -rf "$DIR"',
    "git clean -fdx",
    "git reset --hard HEAD~1",
    "git checkout -- .",
    "git checkout .",
    "git restore src/idx_agent/db/pool.py",
    "git stash",
    "git stash pop",
    "git push -f origin main",
    "git push --force-with-lease origin wo-004",
    "git branch -D wo-004",
    "git worktree remove --force ../worktrees/x",
    "git rm tests/test_smoke.py",
    "find . -name '*.log' -delete",
    "find data -type f -exec rm {} \\;",
    "ls *.pyc | xargs rm",
    "mv data/ /tmp/data-backup",
    "mv ~/.claude/projects/x/memory /tmp/m",
    "rm -rf ~/.claude/projects/x/memory",
    "mysql idx -e 'DROP TABLE rets_property'",
    "psql -c 'TRUNCATE california_sold'",
    "python3 -c \"cur.execute('DELETE FROM rets_property')\"",
    "docker compose down -v",
    "docker volume rm idx_mysql",
    ": > docs/EVIDENCE_LOG.md",
    "cat > docs/EVIDENCE_LOG.md <<'EOF'\n| a |\nEOF",
    "echo x > evals/cases/property_search.yaml",
    "truncate -s 0 data/dump.sql",
    "shred -u data/dump.sql",
    "caffeinate -i rm -rf data/",
    "cd ../worktrees/x && rm -rf evals/cases",
]
PAID = [
    "python -m evals.run --suite local",
    "python -m evals.run --suite=local",
    "curl https://api.openai.com/v1/models",
    "curl -X POST https://api.anthropic.com/v1/messages",
    "python3 -c 'from openai import OpenAI; OpenAI().embeddings.create(input=[])'",
    "python3 -c 'import anthropic'",
    "OPENAI_API_KEY=sk-x python scripts/embed.py",
    "export OPENAI_API_KEY=sk-x",
    "openclaw run",
    "openclaw",
    "openclaw chat --to 555-010-0100",
    "pytest -m live",
    "make eval-live",
]
GATES = [
    "sed -i 's/x/y/' scripts/gates/pii_scan.py",
    "cat > scripts/guards/guard.py <<'EOF'\nprint(1)\nEOF",
    "cp /tmp/settings.json .claude/settings.json",
    "echo 'data/' >> .gitignore",
    "tee .pre-commit-config.yaml < /tmp/x",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('scripts/gates/x.py').write_text('')\nEOF",
    "touch .github/workflows/deploy.yml",
    "rm scripts/gates/forbidden_paths.py",
]
NEVER = [
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "SKIP=protected-deletions git commit -m x",
    "gh pr edit 3 --add-label deletion-approved",
    "gh api repos/o/r/issues/3/labels -f 'labels[]=deletion-approved'",
    "pre-commit uninstall",
    "git config core.hooksPath /tmp/hooks",
    "touch .local/consent/delete",
    "scripts/guards/consent.sh delete",
    "bash scripts/guards/consent.sh paid 60",
    "python3 scripts/guards/consent_token.py grant delete",
    "echo 99999999999 > .local/consent/paid",
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
    ("Edit", ".claude/settings.json", ["gates"]),
    ("Write", ".claude/settings.local.json", ["gates"]),
    ("Write", "/Users/someone/.claude/settings.json", ["gates"]),
    ("Edit", ".github/workflows/ci.yml", ["gates"]),
    ("Edit", ".gitignore", ["gates"]),
    ("Edit", ".pre-commit-config.yaml", ["gates"]),
    ("Write", ".local/consent/delete", ["consent"]),
    ("Write", "docs/EVIDENCE_LOG.md", ["delete"]),
    ("Edit", "docs/EVIDENCE_LOG.md", []),
    ("Write", "evals/cases/brand_new_case_file.yaml", []),
    ("Edit", "src/idx_agent/parser/rules.py", []),
    ("Write", "docs/ARCHITECTURE.md", []),
    ("Write", "/Users/someone/.claude/projects/x/memory/note.md", []),
    ("Write", "", []),
]


@pytest.mark.parametrize("tool, path, expected", FILE_CASES)
def test_file_tools(tool, path, expected):
    assert kinds(guard.classify_file(tool, path)) == expected


def test_tokens_are_absent_expired_or_valid(isolated_consent):
    assert not ct.is_valid("delete")
    ct.grant("delete", minutes=15, now=1000.0)
    assert ct.is_valid("delete", now=1000.0 + 14 * 60)
    assert not ct.is_valid("delete", now=1000.0 + 16 * 60)
    (isolated_consent / "paid").write_text("not a number\n")
    assert not ct.is_valid("paid")
    assert ct.revoke("delete") is True
    assert ct.revoke("delete") is False
    assert not ct.is_valid("delete", now=1000.0)
    with pytest.raises(ValueError):
        ct.token_path("root")


def test_grant_clamps_minutes_and_logs(isolated_consent):
    ct.grant("gates", minutes=10_000, now=0.0)
    assert ct.expiry("gates") == ct.MAX_MINUTES * 60
    log = (isolated_consent / "audit.log").read_text()
    assert "grant\tgates" in log


def test_decide_allows_with_token_and_blocks_without():
    findings = [guard.Finding("delete", "rm of data/")]
    code, message = guard.decide(findings, "rm -rf data/")
    assert code == 2 and "consent.sh delete" in message
    ct.grant("delete", minutes=5)
    code, message = guard.decide(findings, "rm -rf data/")
    assert code == 0 and "allowed" in message
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

    write = {"tool_name": "Write", "tool_input": {"file_path": ".local/consent/paid"}}
    result = run_guard(json.dumps(write), env)
    assert result.returncode == 2

    other = {"tool_name": "Read", "tool_input": {"file_path": "data/x.csv"}}
    assert run_guard(json.dumps(other), env).returncode == 0

    result = run_guard("this is not json", env)
    assert result.returncode == 2 and "failed closed" in result.stderr

    log = (isolated_consent / "audit.log").read_text()
    assert "block\tdelete" in log and "use\tdelete" in log
