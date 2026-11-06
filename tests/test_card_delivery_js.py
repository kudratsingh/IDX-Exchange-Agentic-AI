"""Run the gateway twin's offline tests (extensions/idx-card-delivery) with Node.

Plain ESM with JSDoc types, so Node 18 or later runs it without a compiler (CI's
runner Node included); skipped only when no such Node is on the PATH.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "extensions" / "idx-card-delivery" / "delivery.test.mjs"


def test_card_delivery_gateway_twin_offline():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
    if not match or int(match[1]) < 18:
        pytest.skip(f"Node 18+ is required for node:test (found {version})")
    result = subprocess.run(
        [node, "--test", str(TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"(?m)^ℹ fail 0$|^# fail 0$", result.stdout), result.stdout
