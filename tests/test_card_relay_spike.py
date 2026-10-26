"""Run the uninstalled TypeScript relay candidate's synthetic checks with Node."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_card_relay_offline_unit_and_stub_delivery():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 24+ is required for the optional TypeScript spike checks")
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    if not match or int(match[1]) < 24:
        pytest.skip("Node 24+ is required for native TypeScript stripping")
    result = subprocess.run(
        [node, "--test", str(ROOT / "extensions/idx-card-relay/relay.test.ts")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
