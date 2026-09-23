"""Gate 4 blocks staged deletions of tracked files unless a human consented."""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "gates"))
sys.path.insert(0, str(ROOT / "scripts" / "guards"))

import consent_token as ct  # noqa: E402
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


def run_gate(cwd, consent_dir, *args):
    env = {**os.environ, "IDX_CONSENT_DIR": str(consent_dir)}
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_staged_deletion_is_blocked_then_allowed_by_a_token(
    repo, tmp_path, monkeypatch
):
    root, git = repo
    consent = tmp_path / "consent"
    git("rm", "-q", "a.txt", "d/.gitkeep")

    result = run_gate(root, consent)
    assert result.returncode == 1
    assert "a.txt" in result.stderr and "d/.gitkeep" not in result.stderr
    assert "consent.sh delete" in result.stderr

    monkeypatch.setenv("IDX_CONSENT_DIR", str(consent))
    ct.grant("delete", minutes=5)
    result = run_gate(root, consent)
    assert result.returncode == 0
    assert "allowed by human consent" in result.stdout and "a.txt" in result.stdout


def test_a_rename_or_a_clean_index_passes_without_consent(repo, tmp_path):
    root, git = repo
    consent = tmp_path / "none"
    assert run_gate(root, consent).returncode == 0
    git("mv", "keep.txt", "kept.txt")
    result = run_gate(root, consent)
    assert result.returncode == 0 and "no deletions" in result.stdout


def test_range_mode_needs_the_approved_flag(repo, tmp_path):
    root, git = repo
    consent = tmp_path / "none"
    git("rm", "-q", "a.txt")
    git("commit", "-q", "-m", "delete a")
    result = run_gate(root, consent, "--range", "HEAD~1...HEAD")
    assert result.returncode == 1 and "deletion-approved" in result.stderr
    result = run_gate(root, consent, "--range", "HEAD~1...HEAD", "--approved")
    assert result.returncode == 0 and "a.txt" in result.stdout
