"""install.sh merges our JSON5 fragment over the wizard's config, losing neither.

Tests scripts/openclaw_merge_config.py and the install render: the templates parse and
hold the safety settings, a merge keeps wizard keys while our lists replace theirs, and
the tracing fragment is rendered only when IDX_OTLP_ENDPOINT is set (WO-007).
"""

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "openclaw_merge_config.py"
TEMPLATE = ROOT / "config" / "openclaw.idx.json5"
OTEL_TEMPLATE = ROOT / "config" / "openclaw.otel.json5"
ENDPOINT = "http://127.0.0.1:4318"
# Invented owner number in the 555 range, as in the other tests.
OWNER = "+15550100100"


def load():
    """Import the merge script from its file path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("merge", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_template_parses_as_json5():
    """The shipped template parses and keeps the safety-relevant settings.

    Checks the skill list, tool allow/deny, toolSearch off, per-peer DM sessions,
    allowlisted WhatsApp DMs, the MCP server args, and memory flush and dreaming off.
    """
    merge = load()
    data = merge.load_json5(TEMPLATE)
    skills = data["agents"]["entries"]["idx"]["skills"]
    assert skills == ["health", "property-search"]
    # Every listed skill has a SKILL.md in the repo's skills/ folder.
    assert all((ROOT / "skills" / name / "SKILL.md").is_file() for name in skills)
    assert data["agents"]["entries"]["idx"]["tools"]["allow"] == ["idx__*", "read"]
    assert "group:runtime" in data["agents"]["entries"]["idx"]["tools"]["deny"]
    assert data["tools"]["toolSearch"] is False
    assert data["session"]["dmScope"] == "per-channel-peer"
    assert data["channels"]["whatsapp"]["dmPolicy"] == "allowlist"
    # Left to the live config while the bot runs on the owner's phone (ADR-0003).
    assert "selfChatMode" not in data["channels"]["whatsapp"]
    assert data["mcp"]["servers"]["idx"]["args"] == [
        "-m",
        "idx_agent.mcp_server.server",
    ]
    compaction = data["agents"]["defaults"]["compaction"]
    assert compaction["memoryFlush"]["enabled"] is False
    memory_core = data["plugins"]["entries"]["memory-core"]
    assert memory_core["config"]["dreaming"]["enabled"] is False


def test_merge_keeps_wizard_keys_and_lets_our_lists_win(tmp_path):
    """Merge a small fragment into a fake wizard config in a temp dir.

    1. Write the wizard JSON and a JSON5 fragment. 2. Run the merge. 3. Wizard-only
    keys survive, fragment lists replace wizard lists, and a backup file exists.
    """
    merge = load()
    wizard = {
        "gateway": {"auth": {"mode": "token", "token": "keep-me"}},
        "agents": {"entries": {"idx": {"name": "idx", "tools": {"allow": ["exec"]}}}},
        "tools": {"profile": "full"},
    }
    target = tmp_path / "openclaw.json"
    target.write_text(json.dumps(wizard))
    fragment = tmp_path / "idx.json5"
    fragment_text = (
        "// comment\n"
        "{ agents: { entries: { idx: { tools: { allow: ['idx__*', 'read'], },"
        " skills: ['health'], }, }, }, tools: { toolSearch: false, }, }\n"
    )
    fragment.write_text(fragment_text.replace("'", '"'))
    assert merge.main(["merge", str(fragment), str(target)]) == 0
    merged = json.loads(target.read_text())
    assert merged["gateway"]["auth"]["token"] == "keep-me"
    assert merged["agents"]["entries"]["idx"]["name"] == "idx"
    assert merged["agents"]["entries"]["idx"]["tools"]["allow"] == ["idx__*", "read"]
    assert merged["agents"]["entries"]["idx"]["skills"] == ["health"]
    assert merged["tools"] == {"profile": "full", "toolSearch": False}
    assert (tmp_path / "openclaw.json.pre-idx.bak").exists()


def test_the_main_template_carries_no_tracing_keys():
    """Tracing off renders only the main template, so it must hold none of it."""
    data = load().load_json5(TEMPLATE)
    assert "diagnostics" not in data
    assert "diagnostics-otel" not in data["plugins"]["entries"]
    assert "allow" not in data["plugins"]


def test_the_tracing_fragment_parses_and_keeps_content_out():
    """The fragment turns on traces only, content capture off, never plugins.allow.

    plugins.allow would switch off every plugin not listed, so its absence is pinned.
    """
    data = load().load_json5(OTEL_TEMPLATE)
    assert data["plugins"] == {"entries": {"diagnostics-otel": {"enabled": True}}}
    assert data["diagnostics"]["enabled"] is True
    assert data["diagnostics"]["otel"] == {
        "enabled": True,
        "endpoint": "__OTLP_ENDPOINT__",
        "protocol": "http/protobuf",
        "serviceName": "openclaw-gateway",
        "traces": True,
        "metrics": False,
        "logs": False,
        "captureContent": False,
    }
    assert set(data) == {"plugins", "diagnostics"}


def test_a_rendered_url_survives_comment_stripping(tmp_path):
    """A // inside a string is part of the value; a // after it is still a comment."""
    rendered = tmp_path / "otel.json5"
    rendered.write_text(
        OTEL_TEMPLATE.read_text().replace("__OTLP_ENDPOINT__", ENDPOINT)
    )
    assert load().load_json5(rendered)["diagnostics"]["otel"]["endpoint"] == ENDPOINT


def test_two_fragments_merge_in_order_with_one_backup(tmp_path):
    """Main and tracing fragments merge in one run; plugin entries from both survive.

    The backup holds the wizard's original config, not an in-between state.
    """
    target = tmp_path / "openclaw.json"
    wizard_text = json.dumps({"plugins": {"entries": {"whatsapp": {"enabled": True}}}})
    target.write_text(wizard_text)
    otel = tmp_path / "otel.json5"
    otel.write_text(OTEL_TEMPLATE.read_text().replace("__OTLP_ENDPOINT__", ENDPOINT))
    assert load().main(["merge", str(TEMPLATE), str(otel), str(target)]) == 0
    merged = json.loads(target.read_text())
    entries = merged["plugins"]["entries"]
    assert set(entries) == {"whatsapp", "memory-core", "diagnostics-otel"}
    assert merged["diagnostics"]["otel"]["endpoint"] == ENDPOINT
    assert (tmp_path / "openclaw.json.pre-idx.bak").read_text() == wizard_text


def _fake_repo(tmp_path: pathlib.Path, env_lines: list[str]) -> pathlib.Path:
    """Copy install.sh, the merge script, and both templates into a throwaway repo.

    Also writes its .env and stub `openclaw` and `node` commands that only print.
    """
    repo = tmp_path / "repo"
    for rel in (
        "scripts/install.sh",
        "scripts/openclaw_merge_config.py",
        "config/openclaw.idx.json5",
        "config/openclaw.otel.json5",
    ):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, repo / rel)
    (repo / ".env").write_text("\n".join(env_lines) + "\n")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, text in (("openclaw", "openclaw 0.0.0-test"), ("node", "v24.16.0")):
        stub = stubs / name
        stub.write_text(f"#!/bin/sh\necho '{text}'\n")
        stub.chmod(0o755)
    return repo


def _install(
    tmp_path: pathlib.Path, env_lines: list[str]
) -> subprocess.CompletedProcess:
    """Run the copied install.sh against a temp state dir, with stubs first on PATH.

    PATH holds only the stubs and the system dirs, so no real openclaw can run.
    """
    repo = _fake_repo(tmp_path, env_lines)
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "IDX_PYTHON": sys.executable,
        "OPENCLAW_STATE_DIR": str(tmp_path / "state"),
    }
    return subprocess.run(
        ["bash", str(repo / "scripts" / "install.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_without_endpoint_renders_what_it_always_did(tmp_path):
    """Unset: the main render is the filled-in template, byte for byte.

    No tracing fragment is rendered and the installed config has no diagnostics keys.
    """
    done = _install(tmp_path, [f"IDX_OWNER_E164={OWNER}", "IDX_OTLP_ENDPOINT="])
    assert done.returncode == 0, done.stderr
    repo, state = tmp_path / "repo", tmp_path / "state"
    expected = (
        TEMPLATE.read_text()
        .replace("__REPO__", str(repo))
        .replace("__PYTHON__", sys.executable)
        .replace("__OWNER_E164__", OWNER)
    )
    assert (state / "openclaw.idx.json5").read_text() == expected
    assert not (state / "openclaw.otel.json5").exists()
    installed = load().load_json5(state / "openclaw.json")
    assert "diagnostics" not in installed
    assert "diagnostics-otel" not in done.stdout


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_with_endpoint_adds_only_the_diagnostics_keys(tmp_path):
    """Set: the merged config gains only the tracing keys over the unchanged render.

    A wizard config already exists, so both fragments go through one merge.
    """
    state = tmp_path / "state"
    state.mkdir()
    (state / "openclaw.json").write_text(json.dumps({"gateway": {"port": 1}}))
    done = _install(
        tmp_path, [f"IDX_OWNER_E164={OWNER}", f'IDX_OTLP_ENDPOINT="{ENDPOINT}/"']
    )
    assert done.returncode == 0, done.stderr
    merge = load()
    without = merge.deep_merge(
        {"gateway": {"port": 1}}, merge.load_json5(state / "openclaw.idx.json5")
    )
    merged = json.loads((state / "openclaw.json").read_text())
    assert merged["diagnostics"]["otel"]["endpoint"] == ENDPOINT
    assert merged["plugins"]["entries"]["diagnostics-otel"] == {"enabled": True}
    del merged["diagnostics"], merged["plugins"]["entries"]["diagnostics-otel"]
    assert merged == without
    assert "openclaw plugins install clawhub:@openclaw/diagnostics-otel" in done.stdout


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_with_endpoint_and_no_config_writes_valid_json(tmp_path):
    """Set, with no openclaw.json yet: the installed config is plain JSON with both.

    Both renders are merged into an empty object, so the result parses with
    json.loads and holds the idx keys and the diagnostics keys.
    """
    done = _install(
        tmp_path, [f"IDX_OWNER_E164={OWNER}", f"IDX_OTLP_ENDPOINT={ENDPOINT}"]
    )
    assert done.returncode == 0, done.stderr
    state = tmp_path / "state"
    merge = load()
    installed = json.loads((state / "openclaw.json").read_text())
    expected = merge.deep_merge(
        merge.load_json5(state / "openclaw.idx.json5"),
        merge.load_json5(state / "openclaw.otel.json5"),
    )
    assert installed == expected
    skills = installed["agents"]["entries"]["idx"]["skills"]
    assert skills == ["health", "property-search"]
    assert installed["diagnostics"]["otel"]["endpoint"] == ENDPOINT
    assert installed["plugins"]["entries"]["diagnostics-otel"] == {"enabled": True}
    assert "memory-core" in installed["plugins"]["entries"]
    assert (state / "openclaw.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="install.sh is a bash script")
def test_install_refuses_a_non_loopback_endpoint(tmp_path):
    """A collector off this machine is refused before anything is written."""
    done = _install(
        tmp_path,
        [f"IDX_OWNER_E164={OWNER}", "IDX_OTLP_ENDPOINT=http://collector.invalid:4318"],
    )
    assert done.returncode == 1
    assert "loopback" in done.stderr
    assert not (tmp_path / "state" / "openclaw.otel.json5").exists()
