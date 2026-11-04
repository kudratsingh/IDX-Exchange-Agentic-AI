"""Invented private files and a fake Messages API for the WO-034 Phase B tests.

Every remark, subtype, label and response here is made up. Nothing reads the real
`data/enrichment/`, a key or the network."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

DATASET = "invented-v3"
DEV, TEST = 100, 150
SUBTYPES = ("Condominium", "Townhouse", "SingleFamilyResidence", "condominium")


def case_id(index: int) -> str:
    return str(5000 + index)


def remark(index: int) -> str:
    text = f"Invented home {index}: attached garage and an open floor plan."
    if index % 3 == 0:
        text += " Easy condo living near the park."
    if index % 7 == 0:
        text += " This is not a condo."
    return text


def subtype(index: int) -> str:
    return SUBTYPES[index % len(SUBTYPES)]


def annotation(text: str, quote: str, group: str, value: str, polarity: str) -> dict:
    start = text.index(quote)
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


def claims(index: int) -> list[tuple[str, str, str, str]]:
    """(quote, group, value, polarity) a careful reader takes from the remark."""
    text = remark(index)
    found = [("attached garage", "exterior_lot", "garage", "affirmed")]
    if "condo living" in text:
        found.append(("condo living", "property_type", "condominium", "affirmed"))
    if "not a condo" in text:
        found.append(("not a condo", "property_type", "condominium", "negated"))
    return found


def gold_rows(*, revised: bool) -> list[dict]:
    """Gold for all 250 cases. The revised gold follows the subtype rule; the
    original keeps every remark claim, as before a relabel."""
    rows = []
    for index in range(DEV + TEST):
        text, condo = remark(index), subtype(index) == "Condominium"
        annotations = []
        for quote, group, value, polarity in claims(index):
            if revised and value == "condominium":
                if (polarity == "negated") == condo:
                    continue
            annotations.append(annotation(text, quote, group, value, polarity))
        rows.append({"id": case_id(index), "annotations": annotations})
    return rows


def predicted_rows(*, include_condo: bool = True) -> list[dict]:
    rows = []
    for index in range(DEV + TEST):
        text = remark(index)
        rows.append(
            {
                "id": case_id(index),
                "annotations": [
                    annotation(text, *claim)
                    for claim in claims(index)
                    if include_condo or claim[2] != "condominium"
                ],
            }
        )
    return rows


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def make_private(root: Path) -> Path:
    """Write splits.json, sample.jsonl, labels.json, a revised gold, saved v2 dev
    predictions and v1 held-out predictions; return the private directory."""
    private = root / "data" / "enrichment"
    private.mkdir(parents=True)
    private.chmod(0o700)
    splits = {case_id(i): "dev" if i < DEV else "test" for i in range(DEV + TEST)}
    _write(
        private / "splits.json", {"version": 1, "dataset_id": DATASET, "splits": splits}
    )
    lines = [
        json.dumps({"key": case_id(i), "subtype": subtype(i), "remark": remark(i)})
        for i in range(DEV + TEST)
    ]
    (private / "sample.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, revised in (("labels.json", False), ("labels-v5.json", True)):
        _write(
            private / name,
            {"version": 1, "dataset_id": DATASET, "labels": gold_rows(revised=revised)},
        )
    payload = {"version": 1, "dataset_id": DATASET, "labels": predicted_rows()}
    _write(private / "predictions-dev-v2-sonnet.json", payload)
    _write(private / "predictions-test-heldout.json", payload)
    return private


def remark_of(body: dict) -> str:
    return json.loads(body["messages"][0]["content"])["remark"]


def response_for(body: dict) -> bytes:
    """A well-formed fake tool call for either contract, from the remark alone."""
    text = remark_of(body)
    index = int(text.split()[2].rstrip(":"))
    tool = body["tools"][0]["name"]
    if tool == "record_facet_decisions":
        payload = {
            "decisions": [
                {
                    "facet": f"{group}.{value}",
                    "evidence_span": {"quote": quote, "occurrence": 1},
                    "polarity": polarity,
                    "temporality": "current",
                }
                for quote, group, value, polarity in claims(index)
            ]
        }
    else:
        payload = {
            "annotations": [
                {
                    "kind": "facet",
                    "quote": quote,
                    "group": group,
                    "facet_value": value,
                    "polarity": polarity,
                    "temporality": "current",
                }
                for quote, group, value, polarity in claims(index)
            ]
        }
    response = {
        "content": [{"type": "tool_use", "name": tool, "input": payload}],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 100,
        },
    }
    return json.dumps(response).encode("utf-8")


def block_network(monkeypatch) -> None:
    """Any real request fails the test."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
