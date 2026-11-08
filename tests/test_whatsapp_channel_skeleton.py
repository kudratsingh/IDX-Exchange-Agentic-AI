"""Run the offline WhatsApp channel's Node tests, and check its manifest and package.

The package and the card renderer are also pinned against the Python side here: the
renderer's deny list equals `safety/columns.py`, the fields it shows exist on the
server's models, and its card tools are the server's ONE_COPY_TOOLS."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extensions/idx-whatsapp-channel"
NODE_TESTS = [
    EXT / "verifier.test.mjs",
    EXT / "channel.test.mjs",
    EXT / "host.test.mjs",
    EXT / "entry.test.mjs",
    EXT / "allowlist.test.mjs",
    EXT / "cards.test.mjs",
]
RUNTIME_FILES = sorted(
    p.name for p in EXT.glob("*.mjs") if not p.name.endswith(".test.mjs")
)
# The real-host replay harness needs the pinned OpenClaw build and macOS sandbox-exec,
# so CI only syntax-checks it; its evidence comes from a local run (see its README).
HARNESS_FILES = [
    EXT / "host-harness/run.mjs",
    EXT / "host-harness/fake-model.mjs",
    EXT / "host-harness/fake-mcp-idx.mjs",
    EXT / "host-harness/cards.mjs",
    EXT / "host-harness/plugin/index.mjs",
]


def test_manifest_shape():
    """Python-only: the manifest claims the channel without reusing the stock id."""
    manifest = json.loads((EXT / "openclaw.plugin.json").read_text())
    assert manifest["id"] != "whatsapp"
    assert manifest["id"] == "idx-whatsapp-channel"
    assert manifest["channels"] == ["whatsapp"]
    assert manifest["channelConfigs"]["whatsapp"]["preferOver"] == ["whatsapp"]
    assert isinstance(manifest["configSchema"], dict)
    schema = manifest["channelConfigs"]["whatsapp"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["enabled"] == {"type": "boolean"}
    assert schema["properties"]["dmPolicy"]["enum"] == ["allowlist"]
    for test_file in NODE_TESTS:
        assert test_file.exists()


def test_package_shape():
    """Owner item 12: a private, dependency-free ESM package that ships runtime only."""
    pkg = json.loads((EXT / "package.json").read_text())
    manifest = json.loads((EXT / "openclaw.plugin.json").read_text())
    assert pkg["name"] == manifest["id"]
    assert pkg["private"] is True
    assert pkg["type"] == "module"
    for key in ("dependencies", "devDependencies", "peerDependencies", "scripts"):
        assert key not in pkg
    assert pkg["openclaw"]["extensions"] == ["./index.mjs"]
    assert pkg["openclaw"]["compat"] == {
        "pluginApi": ">=2026.9.5",
        "minGatewayVersion": "2026.9.5",
    }
    files = pkg["files"]
    assert sorted(f for f in files if f.endswith(".mjs")) == RUNTIME_FILES
    assert "openclaw.plugin.json" in files
    for name in files:
        assert (EXT / name).is_file(), name
        assert ".test." not in name
        assert "test-support" not in name
        assert "host-harness" not in name


def _js_string_list(source: str, const: str) -> list[str]:
    """The string items of `export const <const> = Object.freeze([...])` in JS."""
    match = re.search(
        rf"export const {const} = Object\.freeze\(\[(.*?)\]\);", source, re.S
    )
    assert match, const
    return re.findall(r'"([^"]+)"', match[1])


def test_card_renderer_pinned_to_python():
    """The renderer's lists match the server: deny list, model fields, card tools."""
    from idx_agent.domain.models import Listing, MarketStats
    from idx_agent.mcp_server.server import ONE_COPY_TOOLS
    from idx_agent.safety.columns import AGENT_CONTACT, DENYLIST

    render = (EXT / "card-render.mjs").read_text()
    constants = (EXT / "constants.mjs").read_text()
    forbidden = _js_string_list(render, "FORBIDDEN_LISTING_KEYS")
    assert len(forbidden) == len(set(forbidden))
    assert set(forbidden) == DENYLIST | AGENT_CONTACT
    listing_fields = _js_string_list(render, "RENDERED_LISTING_FIELDS")
    assert set(listing_fields) <= set(Listing.model_fields)
    assert "remarks" not in listing_fields
    assert {"latitude", "longitude"}.isdisjoint(listing_fields)
    market_fields = _js_string_list(render, "RENDERED_MARKET_FIELDS")
    assert set(market_fields) <= set(MarketStats.model_fields)
    assert set(_js_string_list(constants, "CARD_TOOLS")) == set(ONE_COPY_TOOLS)


def test_node_suite():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 20+ is required for the skeleton's Node tests")
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    if not match or int(match[1]) < 20:
        pytest.skip("Node 20+ is required for the skeleton's Node tests")
    result = subprocess.run(
        [node, "--test", *map(str, NODE_TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_harness_syntax():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to syntax-check the host harness")
    for path in HARNESS_FILES:
        assert path.exists(), path
        result = subprocess.run(
            [node, "--check", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"
