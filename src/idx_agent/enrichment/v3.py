"""Frozen v3 extraction contract (WO-034 Phase B), key-free: freeze verification,
the standard Messages API body, the parser, the span check, the option A subtype
mapper and the Phase D pass rule. No provider client, network or file writes; the
only reads are the two tracked contract files in `verify_contract`."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from pathlib import Path
from typing import Any

from idx_agent.enrichment.dev_extraction import _normalized
from idx_agent.enrichment.private_scoring import Counts, _key
from idx_agent.enrichment.v2 import V2_FACETS

FREEZE_FILE = "docs/ENRICHMENT_V3_FREEZE.json"
CONTRACT_DOC = "docs/ENRICHMENT_EXTRACTION_V3.md"
FREEZE_VERSION = 4
# The freeze file's own bytes and its three recorded hashes, pinned here so that a
# change to any of them refuses the run before a token is spent.
FREEZE_FILE_SHA256 = "4edd9237a08c14a6b78f3f34c6262675fb5b988014f42bff7cf6cc172bd56a89"
PROMPT_SHA256 = "c698f20cec949b8d19c6a1af7c10e7a4e11972143d1027b289131ad8e270155e"
SCHEMA_SHA256 = "91bbeb567206700222ff2d5d88e1fd3fc719b6728e800b3598f293b6f01bcb67"
REQUEST_SHA256 = "c8e5ef0c0759c9b606e795a99e99dfb3d5508dc2159596fca8a751f2b92dfb11"
TOOL_NAME = "record_facet_decisions"
QUOTE_LIMIT = 80
POLARITIES = ("affirmed", "negated", "uncertain")
TEMPORALITIES = ("current", "planned", "historical", "unspecified")
_BLOCKS = {"prompt": "text", "schema": "json", "request": "json"}

FACET_MAP: dict[str, tuple[str, str]] = {
    f"{group}.{value}": (group, value)
    for group, values in sorted(V2_FACETS.items())
    for value in sorted(values)
}
assert len(FACET_MAP) == 20
# How each scored annotation field is derived from one v3 decision.
FIELD_MAP = {
    "kind": "the constant facet",
    "group": "decision.facet before the first dot (FACET_MAP)",
    "value": "decision.facet after the first dot (FACET_MAP)",
    "polarity": "decision.polarity",
    "temporality": "decision.temporality",
    "start": "evidence_span.quote located at evidence_span.occurrence in the remark",
    "end": "start plus the located length in the remark",
    "quote": "the remark from start to end, never the model's text",
}
CONDOMINIUM = ("property_type", "condominium")
CONFLICT_FLAG = "ruling4_subtype_conflict"
# Owner decisions (a) to (c), 2026-11-04: remove contradicting claims, add nothing.
SUBTYPE_RULE = {
    "adds_annotations": False,
    "condominium_subtype": "Condominium",
    "facet": "property_type.condominium",
    "flag": CONFLICT_FLAG,
    "match": "exact string equality; every other or unseen value is not a condominium",
    "remove_when_condominium": ["negated"],
    "remove_when_not_condominium": ["affirmed", "uncertain"],
    "version": 1,
}
SUPPORT_MINIMUM = 10
F1_MINIMUM = 0.80


class ContractError(ValueError):
    """The frozen contract or one of its pins does not verify."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def block(text: str, name: str) -> str:
    """The fenced block after `<!-- v3:<name> -->`, as the freeze test reads it."""
    marker = f"<!-- v3:{name} -->"
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == marker]
    if len(starts) != 1:
        raise ContractError(f"expected one {marker} marker")
    opening = starts[0] + 1
    if opening >= len(lines) or lines[opening] != "```" + _BLOCKS[name]:
        raise ContractError(f"{marker} must be followed by a fence")
    for end in range(opening + 1, len(lines)):
        if lines[end] == "```":
            return "\n".join(lines[opening + 1 : end])
    raise ContractError(f"unclosed block after {marker}")


def contract_hashes(doc: str) -> dict[str, str]:
    return {
        "prompt_sha256": sha256(block(doc, "prompt").encode("utf-8")),
        "schema_sha256": sha256(canonical(json.loads(block(doc, "schema")))),
        "request_sha256": sha256(canonical(json.loads(block(doc, "request")))),
    }


def verify_contract(root: Path) -> tuple[str, dict, dict]:
    """Verify freeze version 4 and the three blocks; return prompt, schema, request.

    Any mismatch raises ContractError before a token can be spent."""
    raw = (root / FREEZE_FILE).read_bytes()
    if sha256(raw) != FREEZE_FILE_SHA256:
        raise ContractError("v3 freeze file changed")
    freeze = json.loads(raw)
    pins = {
        "prompt_sha256": PROMPT_SHA256,
        "schema_sha256": SCHEMA_SHA256,
        "request_sha256": REQUEST_SHA256,
    }
    if (
        freeze.get("version") != FREEZE_VERSION
        or freeze.get("paid_calls_before_freeze") != 0
        or freeze.get("doc") != CONTRACT_DOC
        or freeze.get("facet_count") != 20
        or {key: freeze.get(key) for key in pins} != pins
    ):
        raise ContractError("invalid v3 freeze file")
    doc = (root / CONTRACT_DOC).read_text(encoding="utf-8")
    if contract_hashes(doc) != pins:
        raise ContractError("v3 contract block changed")
    prompt = block(doc, "prompt")
    schema = json.loads(block(doc, "schema"))
    request = json.loads(block(doc, "request"))
    item = schema["input_schema"]["properties"]["decisions"]["items"]
    if schema.get("name") != TOOL_NAME or item["properties"]["facet"]["enum"] != list(
        FACET_MAP
    ):
        raise ContractError("v3 schema does not name the 20 facets")
    if "standard requests" not in request.get("api", ""):
        raise ContractError("v3 transport is not the standard Messages API")
    return prompt, schema, request


def request_body(prompt: str, schema: dict, request: dict, remark: str) -> dict:
    """The frozen standard Messages API body for one remark. Sends nothing."""
    if not prompt or not isinstance(remark, str):
        raise ValueError("invalid request")
    return {
        "model": request["model"],
        "max_tokens": request["max_tokens"],
        "thinking": request["thinking"],
        "output_config": request["output_config"],
        "tools": [schema],
        "tool_choice": request["tool_choice"],
        "system": [
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": json.dumps({"remark": remark}, ensure_ascii=False),
            }
        ],
    }


class _Miss(ValueError):
    def __init__(self, path: str, rule: str) -> None:
        super().__init__(rule)
        self.path, self.rule = path, rule


def locate_occurrence(text: str, quote: Any, occurrence: Any) -> tuple[int, int]:
    """Offsets of the `occurrence`-th appearance of `quote` (exact, else after the
    existing whitespace normalization). Overlapping appearances count."""
    if not isinstance(quote, str) or not quote.strip():
        raise _Miss("evidence_span.quote", "nonempty_quote_required")
    if len(quote) > QUOTE_LIMIT:
        raise _Miss("evidence_span.quote", "quote_exceeds_80")
    if type(occurrence) is not int:
        raise _Miss("evidence_span.occurrence", "integer_occurrence_required")
    if occurrence < 1:
        raise _Miss("evidence_span.occurrence", "occurrence_below_1")

    def positions(source: str, needle: str) -> list[int]:
        found, start = [], source.find(needle)
        while start >= 0:
            found.append(start)
            start = source.find(needle, start + 1)
        return found

    exact = positions(text, quote)
    if exact:
        if occurrence > len(exact):
            raise _Miss("evidence_span.occurrence", "occurrence_out_of_range")
        start = exact[occurrence - 1]
        return start, start + len(quote)
    source, spans = _normalized(text)
    needle, _ = _normalized(quote)
    loose = positions(source, needle)
    if not loose:
        raise _Miss("evidence_span.quote", "quote_not_found")
    if occurrence > len(loose):
        raise _Miss("evidence_span.occurrence", "occurrence_out_of_range")
    first = loose[occurrence - 1]
    return spans[first][0], spans[first + len(needle) - 1][1]


def parse_v3(response: Any, remark: str) -> tuple[list[dict], list[dict], list[dict]]:
    """(annotations, diagnostics, spans) for one response. Annotations have the
    scorer's shape with local offsets; diagnostics are sanitized (no model text);
    `spans` has one record per decision with a known facet and polarity (facet,
    polarity, located, start, end). An invalid decision is a miss; parsing goes on."""
    annotations: list[dict] = []
    diagnostics: list[dict] = []
    spans: list[dict] = []

    def miss(field: str, rule: str) -> None:
        diagnostics.append(
            {"error_class": "DiagnosticError", "field": field, "rule": rule}
        )

    if not isinstance(response, dict) or not isinstance(response.get("content"), list):
        miss("content", "provider_response_object_required")
        return annotations, diagnostics, spans
    calls = [
        b
        for b in response["content"]
        if isinstance(b, dict)
        and b.get("type") == "tool_use"
        and b.get("name") == TOOL_NAME
    ]
    if not calls:
        miss("content", "no_extraction_tool_call")
        return annotations, diagnostics, spans
    if len(calls) != 1 or not isinstance(calls[0].get("input"), dict):
        miss("content", "one_valid_extraction_tool_call_required")
        return annotations, diagnostics, spans
    decisions = calls[0]["input"].get("decisions")
    if not isinstance(decisions, list):
        miss("decisions", "array_required")
        return annotations, diagnostics, spans
    seen: set[tuple] = set()
    for index, decision in enumerate(decisions):
        prefix = f"decisions[{index}]"
        record: dict | None = None
        try:
            if not isinstance(decision, dict) or set(decision) != {
                "facet",
                "evidence_span",
                "polarity",
                "temporality",
            }:
                raise _Miss("", "decision_fields_required")
            facet = decision["facet"]
            if not isinstance(facet, str) or facet not in FACET_MAP:
                raise _Miss("facet", "known_facet_required")
            if decision["polarity"] not in POLARITIES:
                raise _Miss("polarity", "known_polarity_required")
            record = {
                "facet": facet,
                "polarity": decision["polarity"],
                "located": False,
                "start": None,
                "end": None,
            }
            if decision["temporality"] not in TEMPORALITIES:
                raise _Miss("temporality", "known_temporality_required")
            span = decision["evidence_span"]
            if not isinstance(span, dict) or set(span) != {"quote", "occurrence"}:
                raise _Miss("evidence_span", "span_fields_required")
            start, end = locate_occurrence(remark, span["quote"], span["occurrence"])
            record.update(located=True, start=start, end=end)
            group, value = FACET_MAP[facet]
            converted = {
                "kind": "facet",
                "group": group,
                "value": value,
                "polarity": decision["polarity"],
                "temporality": decision["temporality"],
                "start": start,
                "end": end,
                "quote": remark[start:end],
            }
            key = _key(converted, remark)
            if key in seen:
                raise _Miss("", "duplicate_annotation")
            seen.add(key)
            annotations.append(converted)
        except _Miss as exc:
            miss(f"{prefix}.{exc.path}" if exc.path else prefix, exc.rule)
        if record is not None:
            spans.append(record)
    return annotations, diagnostics, spans


def span_quality(
    spans_by_case: dict[str, list[dict]], gold: dict, case_ids: list[str]
) -> dict:
    """Reported, not gated. A decision passes when its quote was found at its
    occurrence and the span overlaps, by at least one character, a gold span of the
    same case, facet and polarity. Rates over all decisions, over decisions whose
    (case, facet, polarity) group has gold, and by facet. Aggregates only."""
    wanted = set(case_ids)
    gold_spans: dict[tuple, list[tuple[int, int]]] = {}
    for row in gold["labels"]:
        if row["id"] not in wanted:
            continue
        for item in row["annotations"]:
            name = f"{item.get('group')}.{item.get('value')}"
            if item.get("kind") == "facet" and name in FACET_MAP:
                gold_spans.setdefault((row["id"], name, item["polarity"]), []).append(
                    (item["start"], item["end"])
                )
    tallies: dict[str, list[int]] = {"all": [0, 0], "matched": [0, 0]}
    by_facet = {name: [0, 0] for name in FACET_MAP}
    for case_id in case_ids:
        for record in spans_by_case.get(case_id, []):
            spans = gold_spans.get((case_id, record["facet"], record["polarity"]))
            passed = int(
                bool(
                    record["located"]
                    and spans
                    and any(a < record["end"] and record["start"] < b for a, b in spans)
                )
            )
            for tally in [tallies["all"], by_facet[record["facet"]]] + (
                [tallies["matched"]] if spans else []
            ):
                tally[0] += 1
                tally[1] += passed

    def rate(pair: list[int]) -> dict:
        return {
            "decisions": pair[0],
            "passed": pair[1],
            "rate": pair[1] / pair[0] if pair[0] else None,
        }

    return {
        "all": rate(tallies["all"]),
        "matched": rate(tallies["matched"]),
        "by_facet": {name: rate(pair) for name, pair in by_facet.items()},
    }


def is_condominium_subtype(subtype: str) -> bool:
    """Decision (c): exactly `Condominium`; every other or unseen value is not."""
    if not isinstance(subtype, str):
        raise ValueError("subtype must be a string")
    return subtype == SUBTYPE_RULE["condominium_subtype"]


def map_subtype(
    annotations: list[dict], text: str, subtype: str
) -> tuple[list[dict], dict]:
    """Option A, identical for v1, v2 and v3: (scored, side). Drops only condominium
    claims that contradict the subtype (affirmed or uncertain unless it is exactly
    `Condominium`, negated when it is); adds nothing and never modifies the input.
    `side`: the subtype, each removed claim without its quote, and the flag."""
    condo = is_condominium_subtype(subtype)
    contradicting = set(
        SUBTYPE_RULE["remove_when_condominium"]
        if condo
        else SUBTYPE_RULE["remove_when_not_condominium"]
    )
    scored, removed = [], []
    for item in annotations:
        if (
            isinstance(item, dict)
            and item.get("kind") == "facet"
            and (item.get("group"), item.get("value")) == CONDOMINIUM
        ):
            _key(item, text)
            if item.get("polarity") in contradicting:
                removed.append(
                    {
                        "facet": SUBTYPE_RULE["facet"],
                        "polarity": item["polarity"],
                        "temporality": item["temporality"],
                        "start": item["start"],
                        "end": item["end"],
                    }
                )
                continue
        scored.append(dict(item) if isinstance(item, dict) else item)
    side = {
        "subtype": subtype,
        "condominium_subtype": condo,
        "removed": removed,
        "flag": CONFLICT_FLAG if removed else None,
    }
    return scored, side


def map_payload(
    payload: dict, sample: dict, subtypes: dict[str, str], split: str
) -> tuple[dict, dict, dict]:
    """Map every row of `split`; other rows pass through. Returns (mapped payload,
    side records by case, removed claims counted by polarity)."""
    texts = {c["id"]: c["text"] for c in sample["cases"] if c["split"] == split}
    rows, sides, removed = [], {}, Counter()
    for row in payload["labels"]:
        if row.get("id") not in texts:
            rows.append(row)
            continue
        if row["id"] not in subtypes:
            raise ValueError("missing subtype")
        scored, side = map_subtype(
            row["annotations"], texts[row["id"]], subtypes[row["id"]]
        )
        rows.append({**row, "annotations": scored})
        sides[row["id"]] = side
        removed.update(item["polarity"] for item in side["removed"])
    counts = {polarity: removed.get(polarity, 0) for polarity in POLARITIES}
    return {**payload, "labels": rows}, sides, counts


def gold_consistency(gold: dict, sample: dict, subtypes: dict, split: str) -> None:
    """The revised gold must already follow the rule: the mapper removes nothing."""
    _, _, removed = map_payload(gold, sample, subtypes, split)
    if any(removed.values()):
        raise ContractError("gold has a condominium label that contradicts subtype")


def mapper_hashes() -> dict[str, str]:
    """The sealed identity of the mapping: code, rule, facet and field maps."""
    return {
        "code_sha256": sha256(
            (
                inspect.getsource(is_condominium_subtype)
                + inspect.getsource(map_subtype)
            ).encode("utf-8")
        ),
        "rule_sha256": sha256(canonical(SUBTYPE_RULE)),
        "facet_map_sha256": sha256(canonical(FACET_MAP)),
        "field_map_sha256": sha256(canonical(FIELD_MAP)),
    }


def counts_json(scores: dict[str, Counts]) -> dict[str, dict]:
    return {
        name: {
            "expected": value.expected,
            "predicted": value.predicted,
            "correct": value.correct,
            "precision": value.precision,
            "recall": value.recall,
            "f1": value.f1,
        }
        for name, value in scores.items()
    }


def phase_d_verdict(v3: dict[str, Counts], v2: dict[str, Counts]) -> dict:
    """Decision 4 with (d), unrounded: v3 overall F1 >= production v2's from the same
    run, and v3 F1 >= 0.80 on every evaluable facet. Support (`expected`) below 10 is
    `not_evaluable`: out of the per-facet check, kept in the micro. Undefined fails."""
    facets = sorted(f"facet.{name}" for name in FACET_MAP)
    if set(facets) - set(v3) or set(facets) - set(v2):
        raise ValueError("incomplete scores")
    v3_f1, v2_f1 = v3["overall"].f1, v2["overall"].f1
    micro = v3_f1 is not None and v2_f1 is not None and v3_f1 >= v2_f1
    per_facet = {}
    for name in facets:
        counts = v3[name]
        if counts.expected != v2[name].expected:
            raise ValueError("configurations scored against different gold")
        if counts.expected < SUPPORT_MINIMUM:
            status = "not_evaluable"
        elif counts.f1 is not None and counts.f1 >= F1_MINIMUM:
            status = "meets"
        else:
            status = "fails"
        per_facet[name] = {
            "support": counts.expected,
            "f1": counts.f1,
            "status": status,
        }
    return {
        "pass": micro and all(x["status"] != "fails" for x in per_facet.values()),
        "micro": {"v3_f1": v3_f1, "v2_f1": v2_f1, "v3_meets_v2": micro},
        "facets": per_facet,
        "not_evaluable": [
            k for k, x in per_facet.items() if x["status"] == "not_evaluable"
        ],
    }
