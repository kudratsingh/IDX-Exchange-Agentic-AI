"""The pure core of code-controlled card delivery (WO-036 prototype, ADR-0015 proposed).

Every case runs from tests/fixtures/card_delivery_vectors.json, which the gateway twin
(extensions/idx-card-delivery/verify.mjs) runs too. Synthetic cards only.
"""

from __future__ import annotations

import json
import re

import pytest
from tests import card_delivery_vectors as vectors

from idx_agent.channels import card_delivery as cd
from idx_agent.channels.relay_check import check_card_relay, number_tokens

VECTORS = json.loads(vectors.PATH.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in VECTORS["cases"]}
WITHHELD = [n for n, c in CASES.items() if c["expect"]["action"] == "withhold"]


def _records(case):
    held = {}
    for name in case["records"]:
        record = cd.parse_record(VECTORS["records"][name])
        if record is not None:
            held[record.ref] = record
    return held


def decide(case, verify=cd.verify_and_substitute):
    context = case["context"]
    return verify(
        case["text"],
        channel=context["channel"],
        session=context["session"],
        run=context["run"],
        now_ms=context["now_ms"],
        records=_records(case),
        bound_calls=context["bound_calls"],
        run_state=context["run_state"],
        strict=context.get("strict", False),
        card_in_session=context.get("card_in_session", False),
    )


def test_the_vectors_file_is_current():
    """Rewrite with `PYTHONPATH=src:. python tests/card_delivery_vectors.py --write`."""
    assert vectors.PATH.read_text(encoding="utf-8") == vectors.render()


@pytest.mark.parametrize("name", sorted(CASES))
def test_shared_vector(name):
    case = CASES[name]
    decision = decide(case)
    expect = case["expect"]
    assert (decision.action, decision.reason) == (expect["action"], expect["reason"])
    assert decision.text == expect["text"]


@pytest.mark.parametrize("name", WITHHELD)
def test_a_withheld_reply_carries_no_digit_of_any_stored_card(name):
    decision = decide(CASES[name])
    assert decision.text == cd.CARD_NOT_DELIVERED_LINE
    assert not re.search(r"[0-9]", decision.text)


def test_core_regression_changed_sqft_is_never_delivered():
    """P1-4 (2026-11-05): card 2's living area changed. The model's retyped card, the
    token plus the changed figure, and a store edited after its digest: all withheld."""
    for name, reason in [
        ("sqft_changed_free_text", "unreferenced"),
        ("sqft_changed_after_token", "text_outside_tokens"),
        ("sqft_changed_in_store", "digest_mismatch"),
    ]:
        decision = decide(CASES[name])
        assert (decision.action, decision.reason) == ("withhold", reason), name
        assert vectors.CHANGED_SQFT not in (decision.text or "")


def test_year_copied_from_another_card_is_never_delivered():
    """P1-4 (2026-11-06): card 3's year built replaced with card 2's."""
    for name in ("year_copied_free_text", "year_copied_after_token"):
        decision = decide(CASES[name])
        assert decision.action == "withhold", name
        assert vectors.CARD2_YEAR not in (decision.text or "")


@pytest.mark.parametrize("name", ["one_token", "two_tokens", "three_tokens"])
def test_delivered_cards_are_the_stored_bytes_and_pass_the_relay_check(name):
    case = CASES[name]
    decision = decide(case)
    stored = [VECTORS["records"][r]["message"] for r in case["records"]]
    assert decision.text == "\n\n".join(stored)
    for message in stored:
        assert message.encode() in decision.text.encode()
    if len(stored) == 1:
        assert check_card_relay(stored[0], decision.text).reason == "exact"


def test_the_token_shows_no_digit_and_says_what_happened():
    for vector in VECTORS["tags"]:
        record = cd.parse_record(vector["record"])
        assert record is not None
        token = cd.mint_token(record)
        assert token == vector["expect"]["token"]
        assert record.tag == vector["expect"]["tag"]
        assert cd.file_name(record.ref) == vector["expect"]["file_name"]
        assert not re.search(r"[0-9]", token)
        assert token.startswith("[[Listing details not shown. Please ask again.")
        assert list(number_tokens(token)) == []


def test_the_session_digest_matches_the_vectors():
    for item in VECTORS["sessions"]:
        assert cd.session_digest(item["session_key"]) == item["digest"]


def test_fixed_texts_have_no_digits():
    for text in (
        cd.CARD_NOT_DELIVERED_LINE,
        cd.CHANNEL_REFUSAL,
        cd.STORE_REFUSAL,
        cd.HANDLE_REFUSAL,
        cd.DELIVERY_NOTE,
        cd.TOKEN_HEAD,
    ):
        assert not re.search(r"[0-9]", text), text


def test_a_ref_is_twenty_letters_of_the_alphabet():
    ref = cd.new_ref()
    assert re.fullmatch(f"[{cd.ALPHABET}]{{20}}", ref)
    assert cd.new_ref(lambda n: bytes(range(n))) == "bbbcbdbfbgbhbjbkbmbn"


@pytest.mark.parametrize(
    ("value", "channel"),
    [
        ({"v": 1, "channel": "none"}, "none"),
        (
            {
                "v": 1,
                "channel": "wa",
                "session": "a" * 64,
                "run": "run-1",
                "call": "call_1",
            },
            "wa",
        ),
    ],
)
def test_parse_binding_accepts_exactly_two_shapes(value, channel):
    binding = cd.parse_binding(value)
    assert binding is not None and binding.channel == channel


@pytest.mark.parametrize(
    "value",
    [
        None,
        "wa",
        {},
        {"v": True, "channel": "none"},
        {"v": 2, "channel": "none"},
        {"v": 1, "channel": "whatsapp"},
        {"v": 1, "channel": "none", "session": "a" * 64},
        {"v": 1, "channel": "wa", "session": "A" * 64, "run": "r", "call": "c"},
        {"v": 1, "channel": "wa", "session": "a" * 64, "run": "", "call": "c"},
        {"v": 1, "channel": "wa", "session": "a" * 64, "run": "r", "call": "c d"},
        {"v": 1, "channel": "wa", "session": "a" * 64, "run": "r"},
        {"v": 1, "channel": "wa", "session": "a" * 64, "run": "r", "call": "c", "x": 1},
        {"v": 1, "channel": "webchat", "session": "a" * 64, "run": "r", "call": "c"},
    ],
)
def test_parse_binding_refuses_everything_else(value):
    assert cd.parse_binding(value) is None


def test_new_record_only_for_a_whatsapp_binding():
    with pytest.raises(ValueError):
        cd.new_record(
            "card",
            trace_id="t",
            binding=cd.DeliveryBinding(channel="none"),
            now_ms=0,
            ttl_ms=1,
        )
    binding = cd.DeliveryBinding(channel="wa", session="a" * 64, run="r", call="c")
    record = cd.new_record(
        "card", trace_id="bad id!", binding=binding, now_ms=5, ttl_ms=10
    )
    assert (record.trace_id, record.expires_ms, record.channel) == ("none", 15, "wa")
    assert record.message_sha256 == cd.message_digest("card")
    assert cd.parse_record(record.model_dump()) == record


def test_parse_record_refuses_bad_shapes():
    good = VECTORS["records"]["s1"]
    assert cd.parse_record(good) is not None
    assert cd.parse_record({**good, "v": True}) is None
    assert cd.parse_record({**good, "created_ms": "1"}) is None
    assert cd.parse_record({**good, "expires_ms": good["created_ms"]}) is None
    assert cd.parse_record({**good, "ref": good["ref"].upper()}) is None
    assert cd.parse_record({**good, "message": ""}) is None
    assert cd.parse_record({**good, "created_ms": float(good["created_ms"])})
    assert cd.parse_record([good]) is None


def _envelope(data, message="card text with 1,860 sqft and built 1990"):
    return {
        "ok": True,
        "data": data,
        "message": message,
        "warnings": ["w"],
        "provenance": {"tool": "t", "trace_id": "abc"},
        "pending_action": None,
        "error": None,
    }


def _listing(key, **figures):
    return {"listing_key": key, "list_price": 1495000, "living_area": 1860, **figures}


def test_project_for_model_keeps_no_card_value():
    handles = {9190001: 111, 9190002: 222}
    envelope = _envelope(
        {
            "listings": [_listing(9190001), _listing(9190002, year_built=1990)],
            "applied_filters": {"city": "Pasadena", "min_baths": 2},
            "total_matches": 7,
            "narrowing_question": None,
        }
    )
    out = cd.project_for_model(envelope, "TOKEN", handles.__getitem__)
    assert list(out) == list(envelope)
    assert out["message"] == "TOKEN"
    assert out["data"] == {
        "listings": [
            {"position": 1, "listing_key": 111},
            {"position": 2, "listing_key": 222},
        ],
        "applied_filters": {"city": "Pasadena", "min_baths": 2},
        "delivery_note": cd.DELIVERY_NOTE,
    }
    text = json.dumps(out)
    for figure in ("1495000", "1860", "1990", "9190001", "9190002", "1,860"):
        assert figure not in text


def test_project_for_model_other_shapes():
    handle = {1: 10, 2: 20, 3: 30}.__getitem__
    similar = cd.project_for_model(
        _envelope({"matches": [{"rank": 1, "listing": _listing(1)}], "k": 5}),
        "T",
        handle,
    )
    assert similar["data"]["matches"] == [{"position": 1, "listing_key": 10}]
    recommend = cd.project_for_model(
        _envelope(
            {
                "subject": _listing(1),
                "subject_check": {"x": 1},
                "recommendations": [{"listing": _listing(2)}, {"listing": _listing(3)}],
            }
        ),
        "T",
        handle,
    )
    assert recommend["data"]["subject"] == {"listing_key": 10}
    assert [r["listing_key"] for r in recommend["data"]["recommendations"]] == [20, 30]
    market = cd.project_for_model(
        _envelope(
            {
                "geography": {"city": "Pasadena"},
                "property_subtype": "Condominium",
                "sample_count": 12,
                "median_close_price": 900000,
            }
        ),
        "T",
        handle,
    )
    assert market["data"] == {
        "geography": {"city": "Pasadena"},
        "property_subtype": "Condominium",
        "delivery_note": cd.DELIVERY_NOTE,
    }
    clarification = cd.project_for_model(
        _envelope({"field": "city", "reason": "missing", "question": "Which city?"}),
        "T",
        handle,
    )
    assert clarification["data"] == {
        "clarification": True,
        "field": "city",
        "reason": "missing",
        "delivery_note": cd.DELIVERY_NOTE,
    }
    assert cd.project_for_model(_envelope(None), "T", handle)["data"] == {
        "delivery_note": cd.DELIVERY_NOTE
    }
