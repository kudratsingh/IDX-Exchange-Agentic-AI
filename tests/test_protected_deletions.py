"""Gate 4 blocks staged deletions of tracked files unless a human consented."""

import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "gates"))
sys.path.insert(0, str(ROOT / "scripts" / "guards"))

import protected_deletions as gate  # noqa: E402

GATE = ROOT / "scripts" / "gates" / "protected_deletions.py"


def test_parse_keeps_deletions_and_skips_renames_gitkeep_and_edits():
    text = (
        "D\tsrc/a.py\n"
        "R100\told.py\tnew.py\n"
        "M\tdocs/x.md\n"
        "D\tevals/cases/.gitkeep\n"
        "A\tnew.txt\n"
        "\n"
    )
    assert gate.parse_name_status(text) == ["src/a.py"]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("a\n")
    (root / "keep.txt").write_text("k\n")
    (root / "d").mkdir()
    (root / "d" / ".gitkeep").write_text("")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    return root, git


def write_token(root, minutes=5):
    consent = root / ".local" / "consent"
    consent.mkdir(parents=True, exist_ok=True)
    (consent / "delete").write_text(f"{time.time() + minutes * 60:.0f}\n")
    return consent


def run_gate(cwd, *args, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    for var in ("IDX_CONSENT_DIR", "CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
        env.pop(var, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_staged_deletion_is_blocked_then_allowed_by_a_token_in_the_repo(repo):
    root, git = repo
    git("rm", "-q", "a.txt", "d/.gitkeep")

    result = run_gate(root)
    assert result.returncode == 1
    assert "a.txt" in result.stderr and "d/.gitkeep" not in result.stderr
    assert "consent.sh delete" in result.stderr

    write_token(root)
    result = run_gate(root)
    assert result.returncode == 0
    assert "allowed by human consent" in result.stdout and "a.txt" in result.stdout
    assert "use\tdelete" in (root / ".local" / "consent" / "audit.log").read_text()


def test_environment_overrides_cannot_point_the_gate_at_a_fake_token(repo, tmp_path):
    root, git = repo
    git("rm", "-q", "a.txt")
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "delete").write_text(f"{time.time() + 300:.0f}\n")
    for var in ("IDX_CONSENT_DIR", "CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
        result = run_gate(root, env_extra={var: str(fake)})
        assert result.returncode == 1, f"{var} must be ignored by the gate"


def test_a_rename_or_a_clean_index_passes_without_consent(repo):
    root, git = repo
    assert run_gate(root).returncode == 0
    git("mv", "keep.txt", "kept.txt")
    result = run_gate(root)
    assert result.returncode == 0 and "no deletions" in result.stdout


def test_range_mode_needs_the_approved_flag(repo):
    root, git = repo
    git("rm", "-q", "a.txt")
    git("commit", "-q", "-m", "delete a")
    result = run_gate(root, "--range", "HEAD~1...HEAD")
    assert result.returncode == 1 and "deletion-approved" in result.stderr
    result = run_gate(root, "--range", "HEAD~1...HEAD", "--approved")
    assert result.returncode == 0 and "a.txt" in result.stdout
