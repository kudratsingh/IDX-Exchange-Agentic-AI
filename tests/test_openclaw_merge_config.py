"""install.sh merges our JSON5 fragment over the wizard's config, losing neither."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "openclaw_merge_config.py"
TEMPLATE = ROOT / "config" / "openclaw.idx.json5"


def load():
    spec = importlib.util.spec_from_file_location("merge", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_template_parses_as_json5():
    merge = load()
    data = merge.load_json5(TEMPLATE)
    assert data["agents"]["entries"]["idx"]["tools"]["allow"] == ["idx__*", "read"]
    assert "group:runtime" in data["agents"]["entries"]["idx"]["tools"]["deny"]
    assert data["tools"]["toolSearch"] is False
    assert data["session"]["dmScope"] == "per-channel-peer"
    assert data["channels"]["whatsapp"]["dmPolicy"] == "allowlist"
    assert data["mcp"]["servers"]["idx"]["args"] == [
        "-m",
        "idx_agent.mcp_server.server",
    ]


def test_merge_keeps_wizard_keys_and_lets_our_lists_win(tmp_path):
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
