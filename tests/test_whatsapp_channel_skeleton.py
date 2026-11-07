"""Run the offline WhatsApp channel skeleton's Node tests, and check its manifest."""

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
]


def test_manifest_shape():
    """Python-only: the manifest claims the channel without reusing the stock id."""
    manifest = json.loads((EXT / "openclaw.plugin.json").read_text())
    assert manifest["id"] != "whatsapp"
    assert manifest["id"] == "idx-whatsapp-channel"
    assert manifest["channels"] == ["whatsapp"]
    assert manifest["channelConfigs"]["whatsapp"]["preferOver"] == ["whatsapp"]
    assert isinstance(manifest["configSchema"], dict)
    assert isinstance(manifest["channelConfigs"]["whatsapp"]["schema"], dict)
    assert not (EXT / "package.json").exists()
    for test_file in NODE_TESTS:
        assert test_file.exists()


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
