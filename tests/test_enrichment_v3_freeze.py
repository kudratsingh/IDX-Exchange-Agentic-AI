"""WO-034 Phase A: recompute the frozen v3 contract hashes from the design doc.

Run directly to print the hashes:
    PYTHONPATH=src:. .venv/bin/python tests/test_enrichment_v3_freeze.py
Reads four tracked docs (contract, freeze, v5 policy, WO-034); no data/, no provider.
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


RULING_8_FACETS = {
    "property_type.condominium",
    "exterior_lot.garage",
    "location_views.near_grocery_mentioned",
    "location_views.near_transit_mentioned",
    "rooms_layout.single_level",
    "interior_systems.stainless_appliances",
}


def _facet_names(text: str) -> set[str]:
    item = json.loads(block(_doc(), "schema"))["input_schema"]["properties"]
    names = item["decisions"]["items"]["properties"]["facet"]["enum"]
    return {name for name in names if name in text}


def doubt_rule_facets(prompt: str) -> set[str]:
    """Facets named by the POLARITY line that requires doubt wording in the span."""
    polarity = prompt.split("POLARITY\n", 1)[1].split("\n\nTIME\n", 1)[0]
    rule = "needs that doubt wording"
    lines = [line for line in polarity.split("\n") if rule in line]
    if len(lines) != 1:
        raise ValueError("expected one doubt-wording rule")
    return _facet_names(lines[0].split(". The one exception", 1)[0])


def test_doubt_wording_rule_is_scoped_to_the_six_ruling_8_facets():
    prompt = block(_doc(), "prompt")
    assert doubt_rule_facets(prompt) == RULING_8_FACETS
    general = prompt.split("- uncertain: ", 1)[1].split("\n", 1)[0]
    assert "record no uncertain decision" not in general


def test_stainless_kitchen_is_the_named_exception_on_both_lines():
    prompt = block(_doc(), "prompt")
    polarity = prompt.split("POLARITY\n", 1)[1].split("\n\nTIME\n", 1)[0]
    assert "The one exception is in the stainless_appliances guide line" in polarity
    guide = prompt.split("FACET GUIDE\n", 1)[1].split("\n")
    name = "interior_systems.stainless_appliances:"
    line = next(x for x in guide if x.startswith(name))
    assert "one exception to the doubt-wording rule" in line
    assert "stainless appliances in general" in line


RULINGS_9_TO_15 = {
    "location_views.near_grocery_mentioned": (
        "a market counts only when the remark says it sells food or groceries",
        "a bare market or a market hall does not",
        "uncertainty about what a market sells is no reason for an uncertain decision",
        "The word groceries counts when the remark places grocery shopping near",
        "food inside the home and grocery delivery do not",
    ),
    "location_views.near_transit_mentioned": ("a scheduled public ferry",),
    "exterior_lot.garage": ("inside a shared garage counts as a garage",),
    "rooms_layout.single_level": (
        "is single level even when an entry stair leads up to it",
    ),
    "interior_systems.stainless_appliances": (
        "a stainless insert built into an outdoor barbecue",
    ),
    "rooms_layout.bonus_room": (
        "A utility room counts only when the remark presents it as existing, usable",
        "could be converted is uncertain",
    ),
}


def test_guide_carries_v5_rulings_9_to_15_on_their_facets():
    guide = block(_doc(), "prompt").split("FACET GUIDE\n", 1)[1].split("\n")
    lines = {x.split(": ", 1)[0]: x for x in guide if ": " in x}
    for facet, phrases in RULINGS_9_TO_15.items():
        for phrase in phrases:
            assert phrase in lines[facet], (facet, phrase)
            others = [name for name, line in lines.items() if phrase in line]
            assert others == [facet], (facet, phrase)


VERSION_1_PROMPT = "2e5ad2d199ea563377f821d5b0564a43996d63d99d02613e35fae5d714b14ad7"
VERSION_2_PROMPT = "c0dd6c744fb76ddb22d298bf795c98cb8a646ea6aefd15a8e572ef7686653cf0"
VERSION_3_PROMPT = "da0c34a1dce2d745f175b5d40c7476fb7c473ca08dcfed84fd0693f94f2dd1e4"
VERSION_1_SCHEMA = "91bbeb567206700222ff2d5d88e1fd3fc719b6728e800b3598f293b6f01bcb67"
VERSION_1_REQUEST = "c8e5ef0c0759c9b606e795a99e99dfb3d5508dc2159596fca8a751f2b92dfb11"


def test_freeze_version_4_keeps_versions_1_to_3_and_no_paid_call():
    frozen = _freeze()
    assert frozen["version"] == 4 and frozen["frozen_on"] == "2026-11-04"
    assert frozen["reason"] == "ruling 9 named grocery chains (owner-authorized)"
    assert frozen["paid_calls_before_freeze"] == 0
    first, second, third = frozen["previous"]
    assert [first["version"], second["version"], third["version"]] == [1, 2, 3]
    assert first["prompt_sha256"] == VERSION_1_PROMPT
    assert second["prompt_sha256"] == VERSION_2_PROMPT
    assert third["prompt_sha256"] == VERSION_3_PROMPT
    assert third["frozen_on"] == "2026-11-04" and third["reason"] == "rulings 9-15"
    prompts = [x["prompt_sha256"] for x in (first, second, third, frozen)]
    assert len(set(prompts)) == 4
    assert frozen["schema_sha256"] == VERSION_1_SCHEMA
    assert frozen["request_sha256"] == VERSION_1_REQUEST
    for earlier in (first, second, third):
        assert earlier["paid_calls_before_freeze"] == 0
        for key in ("schema_sha256", "request_sha256"):
            assert earlier[key] == frozen[key]


MERGED_POLICY_V5 = "229fdd74eb280827a2cf799897c229c33330a97d4cd31c84122d2eb0dbf0e7f8"


def test_latest_freeze_version_pins_the_policy_file_as_merged():
    frozen = _freeze()
    latest = max([frozen, *frozen["previous"]], key=lambda entry: entry["version"])
    assert latest is frozen and latest["version"] == 4
    policy = latest["policy"]
    assert policy["file"] == "docs/ENRICHMENT_REVIEW_POLICY_V5.md"
    actual = hashlib.sha256((ROOT / policy["file"]).read_bytes()).hexdigest()
    assert policy["sha256"] == actual
    # The policy file as merged by #162 (ruling 9 named grocery chains).
    assert actual == MERGED_POLICY_V5


HELDOUT_EXCLUSIONS = (
    "data/enrichment/v3-heldout-exclusions-v1.json",
    "2e60fd85f264415fc39627f8b85e3b4e16aacacc865b092f4fc749fe47e8a8a0",
)


def _section(text: str, heading: str) -> str:
    return text.split(heading + "\n", 1)[1].split("\n### ", 1)[0]


def test_final_freeze_seals_the_heldout_exclusion_and_primary_population():
    # Owner decision 1 (2026-11-04): one exposed held-out case is excluded from the
    # primary score; the file and the procedure are sealed before Phase D.
    text = _doc()
    seals = _section(text, "### What the final freeze seals (decision 3)")
    rows = [
        line for line in seals.split("\n") if line.startswith("| Held-out exclusion")
    ]
    assert len(rows) == 1
    path, digest = HELDOUT_EXCLUSIONS
    assert f"`{path}`" in rows[0] and f"`{digest}`" in rows[0]
    assert "`primary_n` 149" in rows[0] and "`diagnostic_n` 150" in rows[0]
    metric = " ".join(
        _section(text, "### The metric and the pass rule (decision 4)").split()
    )
    assert "150 per configuration" in metric
    assert "**primary score**" in metric and "**149** cases" in metric
    assert "**full-150 score**" in metric and "**diagnostic** only" in metric
    assert "**Pass** (on the primary score, 149 cases)" in metric
    work_order = (ROOT / "work_orders" / "WO-034-extraction-v3.md").read_text("utf-8")
    assert f"`{digest}`" in work_order


def test_grocery_line_counts_named_chains_and_scopes_the_market_rules():
    guide = block(_doc(), "prompt").split("FACET GUIDE\n", 1)[1].split("\n")
    name = "location_views.near_grocery_mentioned:"
    line = next(x for x in guide if x.startswith(name))
    named_chain = (
        "A named grocery chain counts whatever words its name contains, "
        'including "Market" and "Farmers Market".'
    )
    assert named_chain in line
    chain, scoped = (
        line.index("A named grocery chain"),
        line.index("The market rules apply only to an unnamed or unknown place: "),
    )
    assert chain < scoped < line.index("a farmers market does not count")
    assert scoped < line.index("a market counts only when")
    assert "named or not" not in line
    assert line.count("farmers market") == 1


VERSION_3_GROCERY_LINE = (
    "location_views.near_grocery_mentioned: the remark explicitly places a grocery "
    "store, supermarket, named grocer or warehouse club near the home. Generic "
    "shopping or retail is not enough, and neither is a farmers market. A market, "
    "named or not, counts only when the remark says it sells food or groceries; a "
    "bare market or a market hall does not, and uncertainty about what a market "
    "sells is no reason for an uncertain decision. The word groceries counts when "
    "the remark places grocery shopping near the home; food inside the home and "
    "grocery delivery do not."
)


def test_version_4_changes_only_the_grocery_line_of_version_3():
    prompt = block(_doc(), "prompt")
    name = "location_views.near_grocery_mentioned:"
    lines = prompt.split("\n")
    changed = [i for i, line in enumerate(lines) if line.startswith(name)]
    assert len(changed) == 1
    lines[changed[0]] = VERSION_3_GROCERY_LINE
    restored = "\n".join(lines).encode("utf-8")
    assert hashlib.sha256(restored).hexdigest() == VERSION_3_PROMPT


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
