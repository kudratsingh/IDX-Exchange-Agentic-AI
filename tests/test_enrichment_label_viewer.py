"""Run the local labeling viewer smoke test on invented data."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_viewer_synthetic_smoke():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the synthetic viewer smoke test")
    script = Path(__file__).resolve().parents[1] / "tools/enrichment/test_viewer.cjs"
    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, check=True
    )
    assert "viewer smoke test passed" in result.stdout
