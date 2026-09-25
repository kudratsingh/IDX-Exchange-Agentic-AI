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
    # Narrowed after the first live session: lookups and no-model subcommands.
    "command -v openclaw || echo missing",
    "which openclaw",
    "openclaw mcp doctor idx --probe",
    "openclaw config validate",
    "openclaw skills list --agent idx",
    "openclaw channels status",
    "openclaw gateway restart",
    "openclaw sessions tail --session-key agent:idx:whatsapp:direct:x",
    "openclaw agents list --bindings",
    "openclaw pairing list whatsapp",
    "python3 -c \"import subprocess; subprocess.run(['pytest', '-q'])\"",
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

    ct.grant("paid", minutes=5, command="rm -rf data/", max_calls=1)
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


# ----- paid tokens v2: one token, one command line, one run (ADR-0002 amendment) -----
ROUTING = (
    "python -m evals.run --suite local --allow-paid --category routing "
    "--no-temperature --reasoning-effort none"
)
ROUTING_ARGV = ROUTING.split()
SERVER = "python -m idx_agent.mcp_server.server"


def mint(command=ROUTING, max_calls=40, minutes=15, now=None):
    return ct.grant("paid", minutes, now=now, command=command, max_calls=max_calls)


def old_reader_expiry(path):
    """How a pre-v2 checkout read any token: line 1 as the float expiry."""
    try:
        return float(path.read_text().strip().splitlines()[0])
    except (OSError, IndexError, ValueError):
        return None


def test_paid_token_format_v2(isolated_consent):
    exp = mint(now=1000.0)
    lines = (isolated_consent / "paid").read_text().splitlines()
    assert lines == [
        "paid-token-v2",
        f"expiry={exp:.0f}",
        f"command={ROUTING}",
        "max_calls=40",
        "granted=1000",
    ]
    assert ct.expiry("paid") == exp == 1000.0 + 15 * 60
    assert ct.is_valid("paid", now=1000.0 + 60), "is_valid stays for status output"
    ct.grant("delete", minutes=5, now=1000.0)
    ct.grant("gates", minutes=5, now=1000.0)
    assert (isolated_consent / "delete").read_text() == "1300\n"
    assert (isolated_consent / "gates").read_text() == "1300\n"


def test_an_old_reader_sees_no_paid_token(isolated_consent):
    mint()
    assert ct.is_valid("paid")
    assert old_reader_expiry(isolated_consent / "paid") is None
    # And the reverse: an old one-line paid token has no expiry for the v2 reader.
    (isolated_consent / "paid").write_text(f"{time.time() + 600:.0f}\n")
    assert ct.expiry("paid") is None and not ct.is_valid("paid")


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"max_calls": 5},
        {"command": ROUTING},
        {"command": "   ", "max_calls": 5},
        {"command": ROUTING, "max_calls": 0},
        {"command": ROUTING, "max_calls": -3},
        {"command": ROUTING, "max_calls": True},
        {"command": ROUTING, "max_calls": "5"},
    ],
)
def test_paid_grant_needs_a_command_and_a_ceiling(kwargs, isolated_consent):
    with pytest.raises(ValueError):
        ct.grant("paid", 15, **kwargs)
    assert not (isolated_consent / "paid").exists()


def test_delete_and_gates_take_no_paid_fields():
    with pytest.raises(ValueError):
        ct.grant("delete", 5, command="rm -rf data")
    with pytest.raises(ValueError):
        ct.grant("gates", 5, max_calls=3)


MATCHES = [
    (ROUTING, ROUTING_ARGV, True),
    (ROUTING, ["/usr/bin/python3", *ROUTING_ARGV[1:]], True),
    (ROUTING, ["/repo/.venv/bin/python", *ROUTING_ARGV[1:]], True),
    (ROUTING, ["python3.11", *ROUTING_ARGV[1:]], True),
    (
        ROUTING,
        ["PYTHONPATH=src", "MYSQL_HOST=127.0.0.1", "python3", *ROUTING_ARGV[1:]],
        True,
    ),
    (ROUTING, ["env", "PYTHONPATH=src", *ROUTING_ARGV], True),
    (ROUTING, [" python ", "-m  evals.run", *ROUTING_ARGV[3:]], True),
    (
        "  python3   -m evals.run\t--suite local ",
        "python -m evals.run --suite local",
        True,
    ),
    (SERVER, ["/x/.venv/bin/python3", "-m", "idx_agent.mcp_server.server"], True),
    (ROUTING, [*ROUTING_ARGV, "--limit", "5"], False),
    (ROUTING, ROUTING_ARGV[:-1], False),
    (ROUTING, [*ROUTING_ARGV[:3], *ROUTING_ARGV[5:], *ROUTING_ARGV[3:5]], False),
    (ROUTING, ["python", "-c", ROUTING], False),
    (ROUTING, ["python", "evals/run.py", *ROUTING_ARGV[3:]], False),
    (ROUTING, ["/abs/evals/run.py", *ROUTING_ARGV[3:]], False),
    (ROUTING, ["pythonista", *ROUTING_ARGV[1:]], False),
    (ROUTING, ["python2", *ROUTING_ARGV[1:]], False),
    (SERVER, ROUTING_ARGV, False),
    ("", [], False),
    ("", ["python"], False),
]


@pytest.mark.parametrize("token_command, argv, expected", MATCHES)
def test_command_matching(token_command, argv, expected):
    assert ct.command_matches(token_command, argv) is expected


def test_consume_spends_the_token_and_a_second_run_is_refused(isolated_consent):
    mint(max_calls=7)
    grant = ct.consume_paid(["/usr/bin/python3", *ROUTING_ARGV[1:]])
    assert grant.command == ROUTING and grant.max_calls == 7
    assert len(grant.run_id) == 16 and grant.expiry == ct.expiry("paid")
    text = (isolated_consent / "paid").read_text()
    assert f"run_id={grant.run_id}" in text and f"pid={os.getpid()}" in text
    assert "consumed=" in text and f"command={ROUTING}" in text

    with pytest.raises(ct.NoPaidToken) as second:
        ct.consume_paid(ROUTING_ARGV)
    assert second.value.reason == "consumed"
    assert not ct.paid_allows(ROUTING_ARGV)
    with pytest.raises(ct.NoPaidToken):
        ct.consume_paid(["python", "-m", "evals.run", "--suite", "local"])
    log = (isolated_consent / "audit.log").read_text()
    assert "consume\tpaid" in log and "block\tpaid\tconsumed" in log
    assert not list(isolated_consent.glob(".paid.*.tmp"))


def test_consume_reasons(isolated_consent):
    with pytest.raises(ct.NoPaidToken) as missing:
        ct.consume_paid(ROUTING_ARGV)
    assert missing.value.reason == "missing"

    mint()
    with pytest.raises(ct.NoPaidToken) as mismatch:
        ct.consume_paid(["python", "-m", "evals.run", "--suite", "local"])
    assert mismatch.value.reason == "command_mismatch"
    assert ct.paid_allows(ROUTING_ARGV), "a mismatch does not spend the token"

    mint(minutes=15, now=time.time() - 3600)
    with pytest.raises(ct.NoPaidToken) as expired:
        ct.consume_paid(ROUTING_ARGV)
    assert expired.value.reason == "expired"
    assert set(ct.PAID_REASONS) >= {"missing", "command_mismatch", "expired"}


def test_consume_defaults_to_the_process_command_line(monkeypatch):
    mint(command=SERVER, max_calls=3)
    monkeypatch.setattr(
        sys, "orig_argv", ["/x/.venv/bin/python", "-m", "idx_agent.mcp_server.server"]
    )
    assert ct.process_argv()[1:] == ["-m", "idx_agent.mcp_server.server"]
    assert ct.consume_paid().max_calls == 3
    with pytest.raises(ct.NoPaidToken, match="consumed"):
        ct.consume_paid()


def test_admit_once_then_a_second_admit_is_refused(isolated_consent):
    mint()
    run_id = ct.admit_paid(ROUTING_ARGV)
    text = (isolated_consent / "paid").read_text()
    assert len(run_id) == 16 and f"run_id={run_id}" in text and "admitted=" in text
    assert "consumed=" not in text
    assert ct.paid_reason(ROUTING_ARGV) == "admitted"
    assert not ct.paid_allows(ROUTING_ARGV)
    with pytest.raises(ct.NoPaidToken) as second:
        ct.admit_paid(ROUTING_ARGV)
    assert second.value.reason == "admitted"
    with pytest.raises(ct.NoPaidToken, match="command_mismatch"):
        ct.admit_paid(["python", "-m", "evals.run"])
    assert "admit\tpaid" in (isolated_consent / "audit.log").read_text()


def test_admit_then_consume_keeps_the_run_id(isolated_consent):
    mint(max_calls=9)
    run_id = ct.admit_paid(ROUTING_ARGV)
    grant = ct.consume_paid(["/repo/.venv/bin/python3", *ROUTING_ARGV[1:]])
    assert grant.run_id == run_id and grant.max_calls == 9
    with pytest.raises(ct.NoPaidToken, match="consumed"):
        ct.consume_paid(ROUTING_ARGV)
    with pytest.raises(ct.NoPaidToken, match="consumed"):
        ct.admit_paid(ROUTING_ARGV)


def test_consume_without_admit_works_once(isolated_consent):
    # A human running the command in their own terminal passes no hook.
    (isolated_consent).mkdir(parents=True, exist_ok=True)
    (isolated_consent / "paid").write_text(_v2(f"command={ROUTING}", "max_calls=5"))
    grant = ct.consume_paid(ROUTING_ARGV)
    assert grant.max_calls == 5 and len(grant.run_id) == 16
    with pytest.raises(ct.NoPaidToken, match="consumed"):
        ct.consume_paid(ROUTING_ARGV)


def test_grant_takes_the_paid_lock(isolated_consent):
    import fcntl
    import threading

    isolated_consent.mkdir(parents=True, exist_ok=True)
    with (isolated_consent / "paid.lock").open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        worker = threading.Thread(target=mint)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive(), "grant waits while an admit or consume holds the lock"
        assert not (isolated_consent / "paid").exists()
    worker.join(timeout=5)
    assert not worker.is_alive() and ct.paid_allows(ROUTING_ARGV)


def _future(minutes=10):
    return f"{time.time() + minutes * 60:.0f}"


def _v2(*lines, exp=None):
    expiry = _future() if exp is None else exp
    return "\n".join(["paid-token-v2", f"expiry={expiry}", *lines]) + "\n"


MALFORMED = [
    lambda: f"{_future()}\n",  # the old one-line format never unlocks paid
    lambda: f"{_future()}\ncommand={ROUTING}\nmax_calls=5\n",  # v2 fields, no magic
    lambda: f"paid-token-v1\nexpiry={_future()}\ncommand={ROUTING}\nmax_calls=5\n",
    lambda: f"paid-token-v2\ncommand={ROUTING}\nmax_calls=5\n",  # no expiry line
    lambda: _v2(f"command={ROUTING}"),
    lambda: _v2("max_calls=5"),
    lambda: _v2(f"command={ROUTING}", "max_calls=0"),
    lambda: _v2(f"command={ROUTING}", "max_calls=lots"),
    lambda: _v2("command=", "max_calls=5"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", "owner=agent"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", "command=python x.py"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", f"expiry={_future()}"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", "junk line"),
    lambda: _v2(
        f"command={ROUTING}", "max_calls=5", exp=f"{time.time() + 10 * 86400:.0f}"
    ),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", exp="inf"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", exp="nan"),
    lambda: _v2(f"command={ROUTING}", "max_calls=5", exp="soon"),
    lambda: "",
    lambda: b"\xff\xfe\x00garbage",
]


@pytest.mark.parametrize("content", MALFORMED)
def test_malformed_and_old_format_tokens_never_unlock(content, isolated_consent):
    isolated_consent.mkdir(parents=True, exist_ok=True)
    body = content()
    path = isolated_consent / "paid"
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body)
    assert not ct.paid_allows(ROUTING_ARGV)
    with pytest.raises(ct.NoPaidToken) as refused:
        ct.consume_paid(ROUTING_ARGV)
    assert refused.value.reason == "malformed"
    code, message = guard.decide(guard.classify_bash(ROUTING), ROUTING)
    assert code == 2 and "current paid token: malformed" in message
    assert ct.paid_token_status()["state"] == "malformed"


def test_a_directory_in_place_of_the_token_is_no_token(isolated_consent):
    (isolated_consent / "paid").mkdir(parents=True)
    assert not ct.paid_allows(ROUTING_ARGV)
    assert ct.paid_reason(ROUTING_ARGV) == "malformed"
    assert ct.paid_token_status()["state"] == "malformed"


def test_paid_allows_is_read_only(isolated_consent):
    mint()
    before = (isolated_consent / "paid").read_text()
    assert ct.paid_allows(ROUTING_ARGV) and ct.paid_allows(tuple(ROUTING_ARGV))
    assert (isolated_consent / "paid").read_text() == before
    assert not ct.paid_allows(["python", "-c", "import openai"])


def test_paid_status_and_cli(isolated_consent, capsys):
    assert ct.paid_token_status()["state"] == "missing"
    code = ct.main(
        [
            "consent_token.py",
            "grant",
            "paid",
            "20",
            "--command",
            ROUTING,
            "--max-calls",
            "40",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert f"for `{ROUTING}`, at most 40 calls, one invocation" in out
    assert "(20 min)" in out

    status = ct.paid_token_status()
    assert status["state"] == "valid" and status["command"] == ROUTING
    assert status["max_calls"] == 40 and status["consumed"] is None
    assert 19 < status["remaining_minutes"] <= 20.01  # the expiry is stored rounded
    assert ct.main(["consent_token.py", "status"]) == 0
    out = capsys.readouterr().out
    assert "delete  none" in out and "gates   none" in out
    assert f"unspent: `{ROUTING}`, at most 40 calls" in out

    run_id = ct.admit_paid(ROUTING_ARGV)
    status = ct.paid_token_status()
    assert status["state"] == "admitted" and status["run_id"] == run_id
    assert status["admitted"] is not None and status["consumed"] is None
    ct.main(["consent_token.py", "status"])
    out = capsys.readouterr().out
    assert "admitted at" in out and run_id in out and "not yet started" in out

    grant = ct.consume_paid(ROUTING_ARGV)
    status = ct.paid_token_status()
    assert status["state"] == "consumed" and status["run_id"] == grant.run_id == run_id
    assert status["pid"] == os.getpid() and status["consumed"] is not None
    ct.main(["consent_token.py", "status"])
    out = capsys.readouterr().out
    assert (
        "spent at" in out
        and grant.run_id in out
        and "a new run needs a new token" in out
    )

    assert (
        ct.main(
            [
                "consent_token.py",
                "grant",
                "paid",
                "--command=python x.py",
                "--max-calls=2",
            ]
        )
        == 0
    )
    assert ct.paid_token_status()["state"] == "valid", (
        "re-minting replaces a spent token"
    )
    assert ct.paid_token_status()["remaining_minutes"] > 14


@pytest.mark.parametrize(
    "args",
    [
        ["grant", "paid"],
        ["grant", "paid", "15"],
        ["grant", "paid", "15", "--command", ROUTING],
        ["grant", "paid", "15", "--max-calls", "3"],
        ["grant", "paid", "15", "--command", ROUTING, "--max-calls", "lots"],
        ["grant", "paid", "15", "--command", ROUTING, "--max-calls", "0"],
        ["grant", "paid", "15", "--command"],
        ["grant", "paid", "15", "16", "--command", ROUTING, "--max-calls", "3"],
        ["grant", "delete", "15", "--command", "rm -rf data"],
        ["grant", "gates", "15", "--max-calls", "3"],
        ["grant", "delete", "soon"],
    ],
)
def test_grant_cli_usage_errors(args, isolated_consent, capsys):
    assert ct.main(["consent_token.py", *args]) == 2
    assert "usage:" in capsys.readouterr().err
    assert not (isolated_consent / "paid").exists()


def test_consent_sh_paid_flags(isolated_consent):
    script = ROOT / "scripts" / "guards" / "consent.sh"
    env = {**os.environ, "IDX_CONSENT_DIR": str(isolated_consent)}

    def run(*args):
        return subprocess.run(
            ["bash", str(script), *args], capture_output=True, text=True, env=env
        )

    bare = run("paid")
    assert bare.returncode == 2 and "--max-calls <N>" in bare.stderr
    assert run("paid", "15").returncode == 2
    ok = run("paid", "15", "--command", ROUTING, "--max-calls", "40")
    assert ok.returncode == 0, ok.stderr
    assert f"`{ROUTING}`, at most 40 calls, one invocation" in ok.stdout
    assert ct.paid_allows(ROUTING_ARGV)
    status = run("status")
    assert "unspent" in status.stdout and "at most 40 calls" in status.stdout
    assert run("delete").returncode == 0 and ct.is_valid("delete")


# ----- the hook: a paid finding needs the token for its exact argv ---------------------
def paid_argvs(command):
    return [f.argv for f in guard.classify_bash(command) if f.kind == "paid"]


@pytest.mark.parametrize(
    "command",
    [
        ROUTING,
        f"caffeinate -dims {ROUTING} > /tmp/routing.log 2>&1 &",
        f"nohup {ROUTING} >> /tmp/routing.log 2>/tmp/err.log",
        f"MYSQL_HOST=127.0.0.1 {ROUTING} | tee /tmp/routing.log",
        f'{ROUTING} > "/tmp/routing run.log" 2>&1',
        f"{ROUTING} >> '/tmp/routing run.log'",
        f"cd ../worktrees/x && {ROUTING}",
    ],
)
def test_classify_attaches_the_plain_commands_argv(command):
    argvs = paid_argvs(command)
    assert argvs and all(ct.command_matches(ROUTING, a) for a in argvs)


@pytest.mark.parametrize(
    "command",
    [
        "python -m idx_agent.semantic.build_index --allow-paid",
        "python -m idx_agent.rag.build --allow-paid --limit 10",
        "python scripts/semantic_spike.py --judge-sheet /tmp/sheet.json",
        "python scripts/semantic_spike.py --judge-sheet=/tmp/sheet.json",
    ],
)
def test_the_builders_and_the_judge_sheet_are_paid(command):
    argvs = paid_argvs(command)
    assert argvs and all(a == tuple(command.split()) for a in argvs)
    code, message = guard.decide(guard.classify_bash(command), command)
    assert code == 2 and "current paid token: missing" in message


@pytest.mark.parametrize(
    "command",
    [
        f"python3 - <<'EOF'\nimport subprocess\nsubprocess.run('{ROUTING}'.split())\nEOF",
        "python3 - <<'EOF'\nfrom anthropic import Anthropic\nEOF",
        "python3 -c 'from openai import OpenAI; OpenAI().embeddings.create(input=[])'",
        "python -uc 'import anthropic'",
        f"bash -c '{ROUTING}'",
        f"echo x | {ROUTING} < /tmp/in.txt",
        f"x=$({ROUTING})",
        f"echo $({ROUTING})",
        f"echo `{ROUTING}`",
        f"cat <({ROUTING})",
        f"echo x > >({ROUTING})",
        "diff <(python -m idx_agent.rag.build --allow-paid) /tmp/x",
        f"PYTHONPATH=src {ROUTING}",
        f"PATH=/tmp/bin:$PATH {ROUTING}",
        f"env PYTHONSTARTUP=/tmp/x.py {ROUTING}",
        f"LD_PRELOAD=/tmp/x.so {ROUTING}",
        f"DYLD_INSERT_LIBRARIES=/tmp/x.dylib {ROUTING}",
        f"OPENAI_API_KEY=sk-x {ROUTING}",
        f"source .env && {ROUTING}",
        f". ./.env; {ROUTING}",
        "export OPENAI_API_KEY=sk-x",
    ],
)
def test_some_paid_spellings_never_carry_an_argv(command):
    findings = [f for f in guard.classify_bash(command) if f.kind == "paid"]
    assert findings and any(f.argv is None for f in findings)
    mint(command=ROUTING)
    code, message = guard.decide(guard.classify_bash(command), command)
    assert code == 2 and "No paid token unlocks this spelling" in message


def test_hook_allows_the_matching_command_once(isolated_consent):
    findings = guard.classify_bash(ROUTING)
    code, message = guard.decide(findings, ROUTING)
    assert code == 2 and "current paid token: missing" in message

    mint(command=ROUTING, max_calls=40)
    for other in (
        "python -m evals.run --suite local --allow-paid --category routing",
        f"{ROUTING} --limit 5",
        "python3 -c 'import openai'",
        "curl https://api.openai.com/v1/models",
        f"source .env && {ROUTING}",
        "python3 - <<'EOF'\nfrom anthropic import Anthropic\nEOF",
    ):
        code, _ = guard.decide(guard.classify_bash(other), other)
        assert code == 2, other
    assert ct.paid_allows(ROUTING_ARGV), "blocked calls admit nothing"

    code, message = guard.decide(findings, ROUTING)
    assert code == 0 and "allowed by human consent token(s): paid" in message
    code, message = guard.decide(findings, ROUTING)
    assert code == 2 and "current paid token: admitted" in message, (
        "the same command passes the hook once"
    )

    ct.consume_paid(ROUTING_ARGV)  # the run starts and spends the token
    code, message = guard.decide(findings, ROUTING)
    assert code == 2 and "current paid token: consumed" in message
    log = (isolated_consent / "audit.log").read_text()
    assert "use\tpaid" in log and "block\tpaid" in log


def test_a_paid_token_does_not_unlock_other_kinds():
    mint(command="rm -rf data/")
    code, _ = guard.decide(guard.classify_bash("rm -rf data/"), "rm -rf data/")
    assert code == 2


def test_mixed_paid_and_delete_need_both():
    command = f"rm -rf data/ && {ROUTING}"
    mint()
    code, message = guard.decide(guard.classify_bash(command), command)
    assert (
        code == 2
        and "consent.sh delete" in message
        and "consent.sh paid" not in message
    )
    ct.grant("delete", 5)
    code, _ = guard.decide(guard.classify_bash(command), command)
    assert code == 0


def test_block_message_names_the_exact_mint_command():
    command = f"caffeinate -dims /repo/.venv/bin/python3 {' '.join(ROUTING_ARGV[1:])} &"
    code, message = guard.decide(guard.classify_bash(command), command)
    assert code == 2
    assert (
        f'  ! scripts/guards/consent.sh paid 30 --command "{ROUTING}" --max-calls <N>'
        in (message.splitlines())
    )
    assert "a second run needs a new token" in message
    assert "one exact command line" in message
    assert guard.mint_line(["python", "-c", 'print("$HOME")'], "3") == (
        "! scripts/guards/consent.sh paid 30 --command "
        "'python -c print(\"$HOME\")' --max-calls 3"
    )


def test_two_paid_commands_in_one_call_are_never_covered_by_one_token():
    command = (
        f"{ROUTING}; python -m evals.run --suite local --allow-paid --category rag"
    )
    mint()
    code, message = guard.decide(guard.classify_bash(command), command)
    assert code == 2 and message.count("consent.sh paid 30 --command") == 2
    assert "current paid token: one token covers one command" in message
    assert ct.paid_allows(ROUTING_ARGV), "nothing was admitted"


def test_content_scan_blocks_provider_calls_outside_the_paid_modules(tmp_path):
    sdk = "from openai import OpenAI\nclient = OpenAI()\n"
    host = 'URL = "https://api.anthropic.com/v1/messages"\n'
    for text in (sdk, host):
        found = guard.classify_content(str(ROOT / "src/idx_agent/tools/x.py"), text)
        assert [(f.kind, f.argv) for f in found] == [("paid", None)]
        assert guard.classify_content(str(tmp_path / "spike.py"), text)
    for allowed in (*guard.PAID_MODULES, "tests/test_semantic_embedder.py"):
        assert guard.classify_content(str(ROOT / allowed), sdk) == [], allowed
    assert guard.classify_content(str(ROOT / "src/idx_agent/x.py"), "x = 1\n") == []
    mint()
    found = guard.classify_content(str(ROOT / "scripts/probe.py"), sdk)
    code, message = guard.decide(found, "scripts/probe.py")
    assert code == 2 and "No paid token unlocks this spelling" in message


def test_guard_process_paid_end_to_end(isolated_consent):
    env = {
        **os.environ,
        "IDX_CONSENT_DIR": str(isolated_consent),
        "IDX_PROJECT_ROOT": str(ROOT),
    }
    bash = json.dumps({"tool_name": "Bash", "tool_input": {"command": ROUTING}})
    result = run_guard(bash, env)
    assert result.returncode == 2
    assert f'--command "{ROUTING}" --max-calls <N>' in result.stderr

    mint()
    result = run_guard(bash, env)
    assert result.returncode == 0 and "allowed by human consent" in result.stdout
    result = run_guard(bash, env)
    assert result.returncode == 2 and "current paid token: admitted" in result.stderr

    ct.consume_paid(ROUTING_ARGV)
    result = run_guard(bash, env)
    assert result.returncode == 2 and "current paid token: consumed" in result.stderr

    (isolated_consent / "paid").write_bytes(b"\x00\xff not a token")
    result = run_guard(bash, env)
    assert result.returncode == 2 and "failed closed" not in result.stderr

    write = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(ROOT / "scripts" / "probe.py"),
            "content": "import anthropic\n",
        },
    }
    result = run_guard(json.dumps(write), env)
    assert result.returncode == 2 and "outside the paid modules" in result.stderr
    edit = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(ROOT / "src" / "idx_agent" / "tools" / "x.py"),
            "old_string": "a",
            "new_string": "requests.post('https://api.openai.com/v1/responses')",
        },
    }
    assert run_guard(json.dumps(edit), env).returncode == 2
    edit["tool_input"]["new_string"] = "x = 1"
    assert run_guard(json.dumps(edit), env).returncode == 0
