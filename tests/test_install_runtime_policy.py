"""Exercise workspace policy installation without touching a real OpenClaw profile."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "idx_policy_installer", ROOT / "scripts/install_runtime_policy.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def policy(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("Copy current results exactly.\n", encoding="utf-8")
    return path


def test_install_preserves_notes_and_backups_across_policy_upgrade(tmp_path, policy):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    original = b"Owner-authored instructions stay here.\n"
    target.write_bytes(original)
    assert installer.install_policy(policy, workspace)
    first = target.read_bytes()
    assert first.startswith(original)
    backups = workspace / ".idx-policy-backups"
    assert [p.read_bytes() for p in backups.iterdir()] == [original]
    assert target.stat().st_mode & 0o777 == 0o600
    assert not installer.install_policy(policy, workspace)
    assert len(list(backups.iterdir())) == 1
    policy.write_text("Updated response contract.\n", encoding="utf-8")
    assert installer.install_policy(policy, workspace)
    assert sorted(p.read_bytes() for p in backups.iterdir()) == sorted(
        [original, first]
    )
    result = target.read_text()
    assert result.startswith(original.decode())
    assert result.count(installer.BEGIN) == 1
    assert "Updated response contract." in result
    assert "Copy current results exactly." not in result


def test_fresh_install_and_custom_suffix_survive(tmp_path, policy):
    workspace = tmp_path / "workspace"
    assert installer.install_policy(policy, workspace)
    target = workspace / "AGENTS.md"
    with target.open("a") as stream:
        stream.write("\nOwner suffix.\n")
    policy.write_text("New policy.\n")
    assert installer.install_policy(policy, workspace)
    assert target.read_text().endswith("\nOwner suffix.\n")


@pytest.mark.parametrize(
    "text", [installer.BEGIN, installer.END, installer.END + installer.BEGIN]
)
def test_malformed_markers_leave_original_untouched(tmp_path, policy, text):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    target.write_text(text)
    with pytest.raises(ValueError):
        installer.install_policy(policy, workspace)
    assert target.read_text() == text
    assert not (workspace / ".idx-policy-backups").exists()


@pytest.mark.parametrize("surface", ["workspace", "instructions", "backups"])
def test_symlinks_refused_without_modifying_destination(tmp_path, policy, surface):
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "notes.md"
    protected.write_text("Unrelated content.")
    workspace = tmp_path / "workspace"
    if surface == "workspace":
        workspace.symlink_to(outside, target_is_directory=True)
    else:
        workspace.mkdir()
        if surface == "instructions":
            (workspace / "AGENTS.md").symlink_to(protected)
        else:
            (workspace / "AGENTS.md").write_text("Local notes.")
            (workspace / ".idx-policy-backups").symlink_to(
                outside, target_is_directory=True
            )
    with pytest.raises(ValueError):
        installer.install_policy(policy, workspace)
    assert protected.read_text() == "Unrelated content."
    assert list(outside.iterdir()) == [protected]


def test_resolves_agent_override_and_default_without_changing_config(tmp_path):
    config = tmp_path / "openclaw.json"
    agent, default = tmp_path / "custom-idx", tmp_path / "default"
    data = {
        "agents": {
            "defaults": {"workspace": str(default)},
            "entries": {"idx": {"workspace": str(agent)}},
        }
    }
    config.write_text(json.dumps(data))
    original = config.read_bytes()
    assert installer.configured_workspace(config) == agent
    assert config.read_bytes() == original
    del data["agents"]["entries"]["idx"]["workspace"]
    config.write_text(json.dumps(data))
    assert installer.configured_workspace(config) == default


@pytest.mark.parametrize("value", [None, "", "relative/workspace"])
def test_missing_or_relative_workspace_refused(tmp_path, value):
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps({"agents": {"entries": {"idx": {"workspace": value}}}})
    )
    with pytest.raises(ValueError):
        installer.configured_workspace(config)


def test_eval_uses_the_same_public_policy_installed_in_workspace(tmp_path):
    from evals import run as runner

    source = ROOT / "config/IDX_RUNTIME.md"
    workspace = tmp_path / "workspace"
    installer.install_policy(source, workspace)
    policy = source.read_text().strip()
    prompt = runner.routing_prompt(runner.configured_skills())
    installed = (workspace / "AGENTS.md").read_text()
    assert prompt.count(policy) == 1
    assert installed.count(policy) == 1
