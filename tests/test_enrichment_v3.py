"""WO-034 Phase B: the v3 contract module, on invented remarks only."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from idx_agent.enrichment import v3
from idx_agent.enrichment.private_scoring import Counts
from idx_agent.enrichment.v2 import score_v2

ROOT = Path(__file__).resolve().parents[1]
TEXT = "Invented: a bright condo with a garage. Garage parking. condo   living."


def _tool(decisions, name=v3.TOOL_NAME):
    return {
        "content": [
            {"type": "tool_use", "name": name, "input": {"decisions": decisions}}
        ]
    }


def _decision(facet, quote, occurrence=1, polarity="affirmed", temporality="current"):
    return {
        "facet": facet,
        "evidence_span": {"quote": quote, "occurrence": occurrence},
        "polarity": polarity,
        "temporality": temporality,
    }


def _copy_contract(tmp_path: Path) -> Path:
    for name in (v3.FREEZE_FILE, v3.CONTRACT_DOC):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


# Contract verification (acceptance check 1)


def test_the_tracked_contract_verifies_as_freeze_version_4():
    prompt, schema, request = v3.verify_contract(ROOT)
    assert hashlib.sha256(prompt.encode()).hexdigest() == v3.PROMPT_SHA256
    assert schema["name"] == v3.TOOL_NAME and schema["strict"] is True
    assert request["model"] == "claude-sonnet-5-5"
    frozen = json.loads((ROOT / v3.FREEZE_FILE).read_text())
    assert frozen["version"] == 4 and frozen["paid_calls_before_freeze"] == 0
    assert hashlib.sha256((ROOT / v3.FREEZE_FILE).read_bytes()).hexdigest() == (
        v3.FREEZE_FILE_SHA256
    )


@pytest.mark.parametrize(
    "target, old, new",
    [
        (v3.CONTRACT_DOC, "at most 80 characters", "at most 90 characters"),
        (
            v3.CONTRACT_DOC,
            '"enum": ["affirmed", "negated", "uncertain"]',
            '"enum": ["affirmed"]',
        ),
        (v3.CONTRACT_DOC, '"max_tokens": 4096', '"max_tokens": 8192'),
        (v3.FREEZE_FILE, '"version": 4', '"version": 5'),
    ],
)
def test_a_mutated_prompt_schema_request_or_freeze_file_refuses(
    tmp_path, target, old, new
):
    root = _copy_contract(tmp_path)
    text = (root / target).read_text()
    assert old in text
    (root / target).write_text(text.replace(old, new, 1))
    with pytest.raises(v3.ContractError):
        v3.verify_contract(root)


def test_an_edit_outside_the_blocks_still_verifies(tmp_path):
    root = _copy_contract(tmp_path)
    doc = root / v3.CONTRACT_DOC
    doc.write_text(doc.read_text() + "\nAn invented note outside the blocks.\n")
    v3.verify_contract(root)


def test_request_body_is_the_frozen_standard_messages_request():
    prompt, schema, request = v3.verify_contract(ROOT)
    body = v3.request_body(prompt, schema, request, "Invented remark é.")
    assert set(body) == {
        "model",
        "max_tokens",
        "thinking",
        "output_config",
        "tools",
        "tool_choice",
        "system",
        "messages",
    }
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "medium"}
    assert body["tool_choice"] == {"type": "auto"} and body["tools"] == [schema]
    assert body["system"] == [
        {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"][0]["content"] == '{"remark": "Invented remark é."}'
    assert "batch" not in json.dumps(body).lower()


def test_module_imports_no_provider_client_and_opens_no_socket():
    tree = ast.parse((ROOT / "src/idx_agent/enrichment/v3.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"anthropic", "urllib", "socket", "http", "requests", "httpx"}


# Parser (acceptance check 2)


def test_parser_converts_decisions_with_local_offsets():
    response = _tool(
        [
            _decision("property_type.condominium", "condo", occurrence=2),
            _decision("exterior_lot.garage", "garage"),
            _decision("rooms_layout.open_plan", "condo living", polarity="uncertain"),
        ]
    )
    annotations, diagnostics, spans = v3.parse_v3(response, TEXT)
    assert diagnostics == []
    condo, garage, loose = annotations
    second = TEXT.index("condo", TEXT.index("condo") + 1)
    assert (condo["start"], condo["end"]) == (second, second + 5)
    assert condo["group"] == "property_type" and condo["value"] == "condominium"
    assert garage["quote"] == TEXT[garage["start"] : garage["end"]] == "garage"
    # Whitespace-normalized match; the quote is the remark's own characters.
    assert loose["quote"] == "condo   living"
    assert all(s["located"] for s in spans) and len(spans) == 3
    assert set(condo) == {
        "kind",
        "group",
        "value",
        "polarity",
        "temporality",
        "start",
        "end",
        "quote",
    }


@pytest.mark.parametrize(
    "decision, field, rule",
    [
        (
            _decision("exterior_lot.garage", "g" * 81),
            "evidence_span.quote",
            "quote_exceeds_80",
        ),
        (
            _decision("exterior_lot.garage", "garage", 0),
            "evidence_span.occurrence",
            "occurrence_below_1",
        ),
        (
            _decision("exterior_lot.garage", "garage", 2),
            "evidence_span.occurrence",
            "occurrence_out_of_range",
        ),
        (
            _decision("exterior_lot.garage", "carport"),
            "evidence_span.quote",
            "quote_not_found",
        ),
        (
            _decision("exterior_lot.garage", "garage", True),
            "evidence_span.occurrence",
            "integer_occurrence_required",
        ),
        (
            _decision("exterior_lot.garage", "  "),
            "evidence_span.quote",
            "nonempty_quote_required",
        ),
        (_decision("exterior_lot.carport", "garage"), "facet", "known_facet_required"),
        (
            _decision("exterior_lot.garage", "garage", polarity="maybe"),
            "polarity",
            "known_polarity_required",
        ),
        (
            _decision("exterior_lot.garage", "garage", temporality="soon"),
            "temporality",
            "known_temporality_required",
        ),
        ({"facet": "exterior_lot.garage"}, "", "decision_fields_required"),
        ("not an object", "", "decision_fields_required"),
    ],
)
def test_each_invalid_decision_is_a_sanitized_miss_and_processing_continues(
    decision, field, rule
):
    response = _tool([decision, _decision("property_type.condominium", "bright condo")])
    annotations, diagnostics, _ = v3.parse_v3(response, TEXT)
    expected_field = "decisions[0]" + (f".{field}" if field else "")
    assert diagnostics == [
        {"error_class": "DiagnosticError", "field": expected_field, "rule": rule}
    ]
    assert [a["value"] for a in annotations] == ["condominium"]
    assert "g" * 20 not in json.dumps(diagnostics) and "carport" not in json.dumps(
        diagnostics
    )


@pytest.mark.parametrize(
    "response, rule",
    [
        ({"content": []}, "no_extraction_tool_call"),
        (_tool([], name="record_extractions"), "no_extraction_tool_call"),
        ({"invalid_response": True}, "provider_response_object_required"),
        (
            {"content": _tool([])["content"] * 2},
            "one_valid_extraction_tool_call_required",
        ),
        (
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": v3.TOOL_NAME,
                        "input": {"decisions": 1},
                    }
                ]
            },
            "array_required",
        ),
    ],
)
def test_a_missing_or_malformed_tool_call_is_a_miss(response, rule):
    annotations, diagnostics, spans = v3.parse_v3(response, TEXT)
    assert annotations == [] and spans == [] and diagnostics[0]["rule"] == rule


def test_duplicate_decision_is_a_miss_and_an_empty_list_is_valid():
    same = _decision("exterior_lot.garage", "garage")
    annotations, diagnostics, _ = v3.parse_v3(_tool([same, same]), TEXT)
    assert len(annotations) == 1 and diagnostics[0]["rule"] == "duplicate_annotation"
    assert v3.parse_v3(_tool([]), TEXT) == ([], [], [])


# Span quality (acceptance check 3)


def _gold(*annotations):
    return {
        "version": 1,
        "dataset_id": "x",
        "labels": [{"id": "1", "annotations": list(annotations)}],
    }


def _ann(
    quote, value="garage", group="exterior_lot", polarity="affirmed", occurrence=1
):
    start = -1
    for _ in range(occurrence):
        start = TEXT.index(quote, start + 1)
    return {
        "kind": "facet",
        "group": group,
        "value": value,
        "polarity": polarity,
        "temporality": "current",
        "start": start,
        "end": start + len(quote),
        "quote": quote,
    }


def test_span_quality_inside_and_overlapping_passes():
    _, _, spans = v3.parse_v3(
        _tool([_decision("exterior_lot.garage", "a garage")]), TEXT
    )
    result = v3.span_quality({"1": spans}, _gold(_ann("garage")), ["1"])
    assert result["all"] == {"decisions": 1, "passed": 1, "rate": 1.0}
    assert result["matched"] == {"decisions": 1, "passed": 1, "rate": 1.0}
    assert result["by_facet"]["exterior_lot.garage"]["passed"] == 1


def test_span_quality_inside_but_not_overlapping_fails():
    _, _, spans = v3.parse_v3(
        _tool([_decision("exterior_lot.garage", "Garage parking")]), TEXT
    )
    result = v3.span_quality({"1": spans}, _gold(_ann("a garage")), ["1"])
    assert result["all"]["passed"] == 0 and result["matched"]["decisions"] == 1


def test_span_quality_not_found_and_wrong_occurrence_fail():
    decisions = [
        _decision("exterior_lot.garage", "carport"),
        _decision("property_type.condominium", "condo", occurrence=3),
    ]
    _, diagnostics, spans = v3.parse_v3(_tool(decisions), TEXT)
    assert [d["rule"] for d in diagnostics] == [
        "quote_not_found",
        "occurrence_out_of_range",
    ]
    gold = _gold(_ann("garage"), _ann("condo", "condominium", "property_type"))
    result = v3.span_quality({"1": spans}, gold, ["1"])
    assert result["all"] == {"decisions": 2, "passed": 0, "rate": 0.0}
    assert result["matched"]["decisions"] == 2


def test_span_quality_requires_the_same_polarity_and_reports_none_without_decisions():
    _, _, spans = v3.parse_v3(
        _tool([_decision("exterior_lot.garage", "garage", polarity="negated")]), TEXT
    )
    result = v3.span_quality({"1": spans}, _gold(_ann("garage")), ["1"])
    assert result["all"]["passed"] == 0 and result["matched"]["decisions"] == 0
    assert v3.span_quality({}, _gold(), ["1"])["all"]["rate"] is None


# Subtype mapper (acceptance check 7; contract doc tests 1 to 8)

CONDO_TEXT = "Invented: a condo with a garage; not a condo tower."


def _claim(polarity, quote="a condo"):
    start = CONDO_TEXT.index(quote)
    return {
        "kind": "facet",
        "group": "property_type",
        "value": "condominium",
        "polarity": polarity,
        "temporality": "current",
        "start": start,
        "end": start + len(quote),
        "quote": quote,
    }


GARAGE = {
    "kind": "facet",
    "group": "exterior_lot",
    "value": "garage",
    "polarity": "affirmed",
    "temporality": "current",
    "start": CONDO_TEXT.index("garage"),
    "end": CONDO_TEXT.index("garage") + 6,
    "quote": "garage",
}


@pytest.mark.parametrize(
    "polarity, subtype, removed",
    [
        ("affirmed", "Townhouse", True),
        ("uncertain", "Townhouse", True),
        ("negated", "Townhouse", False),
        ("affirmed", "Condominium", False),
        ("uncertain", "Condominium", False),
        ("negated", "Condominium", True),
        ("affirmed", "condominium", True),
        ("affirmed", "Condo", True),
        ("affirmed", " Condominium", True),
        ("affirmed", "UnseenSubtype", True),
        ("negated", "UnseenSubtype", False),
        ("uncertain", "", True),
    ],
)
def test_every_polarity_and_subtype_follows_decisions_b_and_c(
    polarity, subtype, removed
):
    raw = [_claim(polarity), GARAGE]
    before = json.dumps(raw, sort_keys=True)
    scored, side = v3.map_subtype(raw, CONDO_TEXT, subtype)
    assert json.dumps(raw, sort_keys=True) == before  # raw claims untouched
    condos = [a for a in scored if a["value"] == "condominium"]
    assert (condos == []) is removed
    assert GARAGE in scored
    assert side["subtype"] == subtype
    assert side["condominium_subtype"] is (subtype == "Condominium")
    if removed:
        assert side["flag"] == "ruling4_subtype_conflict"
        assert side["removed"] == [
            {
                "facet": "property_type.condominium",
                "polarity": polarity,
                "temporality": "current",
                "start": raw[0]["start"],
                "end": raw[0]["end"],
            }
        ]
        assert "quote" not in side["removed"][0]
    else:
        assert side == {
            "subtype": subtype,
            "condominium_subtype": subtype == "Condominium",
            "removed": [],
            "flag": None,
        }


def test_a_silent_remark_gets_no_condominium_label_and_nothing_is_made_up():
    scored, side = v3.map_subtype([GARAGE], CONDO_TEXT, "Condominium")
    assert scored == [GARAGE] and side["removed"] == []
    assert all(a["quote"] == CONDO_TEXT[a["start"] : a["end"]] for a in scored)


def test_mixed_claims_remove_only_the_contradicting_one():
    raw = [_claim("affirmed"), _claim("negated", "not a condo"), GARAGE]
    scored, side = v3.map_subtype(raw, CONDO_TEXT, "Condominium")
    assert [a["polarity"] for a in scored if a["value"] == "condominium"] == [
        "affirmed"
    ]
    assert [r["polarity"] for r in side["removed"]] == ["negated"]


def test_a_condominium_claim_with_an_invalid_span_is_refused():
    broken = dict(_claim("affirmed"), quote="invented")
    with pytest.raises(ValueError):
        v3.map_subtype([broken], CONDO_TEXT, "Townhouse")
    with pytest.raises(ValueError):
        v3.map_subtype([GARAGE], CONDO_TEXT, None)


def test_identical_mapping_for_v1_v2_and_v3_shapes():
    v3_response = _tool(
        [
            {
                "facet": "property_type.condominium",
                "evidence_span": {"quote": "a condo", "occurrence": 1},
                "polarity": "affirmed",
                "temporality": "current",
            },
            {
                "facet": "exterior_lot.garage",
                "evidence_span": {"quote": "garage", "occurrence": 1},
                "polarity": "affirmed",
                "temporality": "current",
            },
        ]
    )
    from_v3, _, _ = v3.parse_v3(v3_response, CONDO_TEXT)
    from_v2 = [_claim("affirmed"), GARAGE]
    numeric = {
        "kind": "numeric",
        "field": "bedrooms",
        "value": 2,
        "start": 0,
        "end": 8,
        "quote": CONDO_TEXT[:8],
    }
    other_facet = dict(GARAGE, group="exterior_lot", value="deck")
    from_v1 = [_claim("affirmed"), GARAGE, numeric, other_facet]
    results = [
        v3.map_subtype(x, CONDO_TEXT, "Townhouse") for x in (from_v1, from_v2, from_v3)
    ]
    condo = [[a for a in s if a.get("value") == "condominium"] for s, _ in results]
    assert condo == [[], [], []]
    assert results[0][1] == results[1][1] == results[2][1]
    assert results[0][0] == [GARAGE, numeric, other_facet]
    assert results[1][0] == results[2][0] == [GARAGE]


def _case_files(subtype="Townhouse", predicted=None):
    sample = {
        "version": 1,
        "dataset_id": "x",
        "cases": [{"id": "1", "split": "test", "text": CONDO_TEXT}],
    }
    gold = {
        "version": 1,
        "dataset_id": "x",
        "labels": [{"id": "1", "annotations": [GARAGE]}],
    }
    predictions = {
        "version": 1,
        "dataset_id": "x",
        "labels": [
            {"id": "1", "annotations": predicted or [_claim("affirmed"), GARAGE]}
        ],
    }
    return sample, gold, predictions, {"1": subtype}


def test_score_v2_runs_on_mapped_output_and_rejects_a_spanless_condominium():
    sample, gold, predictions, subtypes = _case_files()
    mapped, sides, removed = v3.map_payload(predictions, sample, subtypes, "test")
    assert removed == {"affirmed": 1, "negated": 0, "uncertain": 0}
    assert sides["1"]["flag"] == "ruling4_subtype_conflict"
    scores = score_v2(sample, gold, mapped, "test")
    assert scores["overall"].f1 == 1.0
    unmapped = score_v2(sample, gold, predictions, "test")
    assert unmapped["overall"].predicted == 2
    # Option B is excluded: a subtype-derived label has no remark span.
    spanless = {
        "kind": "facet",
        "group": "property_type",
        "value": "condominium",
        "polarity": "affirmed",
        "temporality": "unspecified",
    }
    bad = copy.deepcopy(predictions)
    bad["labels"][0]["annotations"] = [spanless]
    with pytest.raises(ValueError, match="invalid annotation span"):
        score_v2(sample, gold, bad, "test")


def test_gold_consistency_check_fails_on_a_contradicting_gold_label():
    sample, gold, _, subtypes = _case_files()
    v3.gold_consistency(gold, sample, subtypes, "test")
    gold["labels"][0]["annotations"].append(_claim("affirmed"))
    with pytest.raises(v3.ContractError):
        v3.gold_consistency(gold, sample, subtypes, "test")
    v3.gold_consistency(gold, sample, {"1": "Condominium"}, "test")


def test_map_payload_requires_a_subtype_for_every_scored_case():
    sample, _, predictions, _ = _case_files()
    with pytest.raises(ValueError, match="missing subtype"):
        v3.map_payload(predictions, sample, {}, "test")


def test_a_mutated_mapper_rule_changes_the_sealed_hash(monkeypatch):
    before = v3.mapper_hashes()
    assert set(before) == {
        "code_sha256",
        "rule_sha256",
        "facet_map_sha256",
        "field_map_sha256",
    }
    changed = dict(v3.SUBTYPE_RULE, remove_when_condominium=[])
    monkeypatch.setattr(v3, "SUBTYPE_RULE", changed)
    after = v3.mapper_hashes()
    assert after["rule_sha256"] != before["rule_sha256"]
    assert after["code_sha256"] == before["code_sha256"]


# Pass rule (decision 4 with decision (d))


def _scores(overall, facets=None, support=12):
    result = {"overall": Counts(*overall)}
    for name in v3.FACET_MAP:
        result[f"facet.{name}"] = Counts(support, support, support)
    for name, counts in (facets or {}).items():
        result[f"facet.{name}"] = Counts(*counts)
    return result


def test_pass_rule_requires_meeting_v2_and_every_evaluable_facet():
    v2 = _scores((100, 100, 90))
    assert (
        v3.phase_d_verdict(_scores((100, 100, 90)), v2)["pass"] is True
    )  # equal meets
    assert v3.phase_d_verdict(_scores((100, 100, 89)), v2)["pass"] is False
    # F1 exactly 0.80 meets; just below fails, compared unrounded.
    exact = _scores((100, 100, 95), {"exterior_lot.garage": (10, 10, 8)})
    assert exact["facet.exterior_lot.garage"].f1 == 0.8
    same_gold = _scores((100, 100, 90), {"exterior_lot.garage": (10, 0, 0)})
    assert v3.phase_d_verdict(exact, same_gold)["pass"] is True
    below = _scores((100, 100, 95), {"exterior_lot.garage": (100, 101, 80)})
    verdict = v3.phase_d_verdict(
        below, _scores((100, 100, 90), {"exterior_lot.garage": (100, 0, 0)})
    )
    assert verdict["facets"]["facet.exterior_lot.garage"]["status"] == "fails"
    assert verdict["pass"] is False


def test_support_below_10_is_not_evaluable_and_kept_in_the_micro():
    thin = {"location_views.water_view": (9, 9, 0)}
    v3_scores = _scores((100, 100, 95), thin)
    verdict = v3.phase_d_verdict(v3_scores, _scores((100, 100, 90), thin))
    assert (
        verdict["facets"]["facet.location_views.water_view"]["status"]
        == "not_evaluable"
    )
    assert verdict["not_evaluable"] == ["facet.location_views.water_view"]
    assert verdict["pass"] is True
    at_ten = {"location_views.water_view": (10, 10, 0)}
    verdict = v3.phase_d_verdict(
        _scores((100, 100, 95), at_ten), _scores((100, 100, 90), at_ten)
    )
    assert verdict["facets"]["facet.location_views.water_view"]["status"] == "fails"


def test_undefined_f1_never_passes_and_gold_must_match():
    empty = _scores((0, 0, 0))
    assert v3.phase_d_verdict(empty, _scores((10, 10, 9)))["pass"] is False
    assert v3.phase_d_verdict(_scores((10, 10, 9)), empty)["pass"] is False
    with pytest.raises(ValueError):
        v3.phase_d_verdict(_scores((1, 1, 1), support=11), _scores((1, 1, 1)))
    with pytest.raises(ValueError):
        v3.phase_d_verdict({"overall": Counts(1, 1, 1)}, _scores((1, 1, 1)))
