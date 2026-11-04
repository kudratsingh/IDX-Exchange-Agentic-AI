"""WO-034 Phase A: recompute the frozen v3 contract hashes from the design doc.

Run directly to print the hashes:
    PYTHONPATH=src:. .venv/bin/python tests/test_enrichment_v3_freeze.py
This module reads two tracked files and imports no provider client.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ENRICHMENT_EXTRACTION_V3.md"
FREEZE = ROOT / "docs" / "ENRICHMENT_V3_FREEZE.json"
BLOCKS = {"prompt": "text", "schema": "json", "request": "json"}
UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
}


def block(text: str, name: str) -> str:
    """Return the fenced block that follows `<!-- v3:<name> -->`, without fences."""
    marker = f"<!-- v3:{name} -->"
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == marker]
    if len(starts) != 1:
        raise ValueError(f"expected one {marker} marker")
    opening = starts[0] + 1
    if opening >= len(lines) or lines[opening] != "```" + BLOCKS[name]:
        raise ValueError(f"{marker} must be followed by a {BLOCKS[name]} fence")
    for end in range(opening + 1, len(lines)):
        if lines[end] == "```":
            return "\n".join(lines[opening + 1 : end])
    raise ValueError(f"unclosed block after {marker}")


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def hashes(text: str) -> dict[str, str]:
    result = {
        "prompt_sha256": hashlib.sha256(block(text, "prompt").encode("utf-8")),
        "schema_sha256": hashlib.sha256(canonical(json.loads(block(text, "schema")))),
        "request_sha256": hashlib.sha256(canonical(json.loads(block(text, "request")))),
    }
    return {key: digest.hexdigest() for key, digest in result.items()}


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _freeze() -> dict:
    return json.loads(FREEZE.read_text(encoding="utf-8"))


def _schema() -> dict:
    return json.loads(block(_doc(), "schema"))


def test_frozen_hashes_match_the_doc():
    frozen = _freeze()
    assert frozen["doc"] == "docs/ENRICHMENT_EXTRACTION_V3.md"
    assert frozen["paid_calls_before_freeze"] == 0
    assert {key: frozen[key] for key in hashes(_doc())} == hashes(_doc())


def test_an_edit_inside_a_block_is_detected_and_outside_is_not():
    text = _doc()
    frozen = hashes(text)
    prompt = block(text, "prompt")
    edited = text.replace(prompt, prompt.replace("at most 80", "at most 90", 1), 1)
    assert hashes(edited)["prompt_sha256"] != frozen["prompt_sha256"]
    schema = block(text, "schema")
    loosened = text.replace(schema, schema.replace('"uncertain"]', '"maybe"]', 1), 1)
    assert hashes(loosened)["schema_sha256"] != frozen["schema_sha256"]
    request = block(text, "request")
    other = text.replace(request, request.replace("sonnet", "haiku", 1), 1)
    assert hashes(other)["request_sha256"] != frozen["request_sha256"]
    assert hashes(text + "\nA new note outside the blocks.\n") == frozen


def test_block_rejects_a_missing_or_doubled_marker():
    text = _doc()
    for broken in (
        text.replace("<!-- v3:prompt -->", "", 1),
        text + "\n<!-- v3:prompt -->\n```text\nx\n```\n",
    ):
        try:
            block(broken, "prompt")
        except ValueError:
            continue
        raise AssertionError("marker check did not fail")


def test_facets_are_the_20_eligible_facets():
    from idx_agent.enrichment.effective import ELIGIBLE_FACETS
    from idx_agent.enrichment.v2 import V2_FACETS

    expected = sorted(f"{g}.{v}" for g, values in V2_FACETS.items() for v in values)
    item = _schema()["input_schema"]["properties"]["decisions"]["items"]
    assert item["properties"]["facet"]["enum"] == expected
    assert len(expected) == 20
    assert {name.split(".", 1)[1] for name in expected} == set(ELIGIBLE_FACETS)
    guide = block(_doc(), "prompt").split("FACET GUIDE\n", 1)[1]
    named = [line.split(":", 1)[0] for line in guide.split("\n") if ": " in line]
    assert sorted(named) == expected


def test_every_decision_carries_an_evidence_span():
    item = _schema()["input_schema"]["properties"]["decisions"]["items"]
    assert item["required"] == ["facet", "evidence_span", "polarity", "temporality"]
    span = item["properties"]["evidence_span"]
    assert span["properties"] == {
        "quote": {"type": "string"},
        "occurrence": {"type": "integer"},
    }
    assert span["required"] == ["quote", "occurrence"]


def test_schema_fits_strict_tool_use():
    schema = _schema()
    assert schema["strict"] is True and schema["name"] == "record_facet_decisions"

    def walk(node):
        if isinstance(node, dict):
            assert not UNSUPPORTED & node.keys()
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema["input_schema"])


def test_request_settings_match_the_v2_sonnet_baseline():
    from idx_agent.enrichment.v2 import message_parameters

    request = json.loads(block(_doc(), "request"))
    baseline = message_parameters("claude-sonnet-5-5", "invented", "invented")
    for key in ("model", "max_tokens", "thinking", "output_config", "tool_choice"):
        assert request[key] == baseline[key]
    assert "Batches" in request["api"] and "not" in request["api"]


def test_this_module_imports_no_provider_client():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {
        "__future__",
        "ast",
        "hashlib",
        "json",
        "pathlib",
        "sys",
        "idx_agent",
    }


if __name__ == "__main__":
    json.dump(hashes(_doc()), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
