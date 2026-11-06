"""Shared test vectors for card delivery: Python and the gateway twin read one file.

Synthetic cards only (format_search_reply over invented listings). Rewrite the file
after a deliberate change with:
    PYTHONPATH=src:. python tests/card_delivery_vectors.py --write
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from idx_agent.channels import card_delivery as cd
from idx_agent.channels import card_store as cs
from idx_agent.channels.format import format_search_reply
from idx_agent.domain.models import Listing

PATH = Path(__file__).resolve().parent / "fixtures" / "card_delivery_vectors.json"
AS_OF = date(2026, 9, 18)
NOW_MS = 1_793_000_000_000
CREATED_MS = NOW_MS - 10_000
TTL_MS = 300_000
SESSION_KEY_A = "agent:idx:whatsapp:direct:synthetic-peer-alpha"
SESSION_KEY_B = "agent:idx:whatsapp:direct:synthetic-peer-bravo"
SESSION_A = cd.session_digest(SESSION_KEY_A)
SESSION_B = cd.session_digest(SESSION_KEY_B)
RUN = "run-current-turn"
EARLIER_RUN = "run-earlier-turn"
# Card 2's living area and card 3's year built: the two P1-4 defects change these.
CARD2_SQFT, CHANGED_SQFT = "1,860 sqft", "1,240 sqft"
CARD3_YEAR, CARD2_YEAR = "built 2001", "built 1990"


def _listing(n: int, price: int, beds: int, baths: int, sqft: int, year: int):
    return Listing(
        listing_key=9190000 + n,
        listing_id=f"FIXTURE-{9190000 + n}",
        address=f"{n} Synthetic Example Lane",
        city="Pasadena",
        postal_code="91101",
        list_price=price,
        bedrooms=beds,
        bathrooms=baths,
        living_area=sqft,
        property_subtype="Single Family Residence",
        year_built=year,
        days_on_market=n * 7,
        photo_count=n + 3,
    )


def three_card_message() -> str:
    listings = [
        _listing(1, 3_180_000, 4, 4, 3412, 1985),
        _listing(2, 1_495_000, 3, 2, 1860, 1990),
        _listing(3, 2_250_000, 4, 3, 2240, 2001),
    ]
    return format_search_reply(listings, AS_OF, "Filters: city Pasadena, with pool")


def two_card_message() -> str:
    listings = [
        _listing(4, 1_120_000, 2, 2, 1310, 1978),
        _listing(5, 1_675_000, 3, 3, 2015, 2012),
    ]
    return format_search_reply(listings, AS_OF, "Filters: city Pasadena")


def _ref(name: str) -> str:
    return cd.letters(hashlib.sha256(name.encode()).digest()[: cd.REF_BYTES])


def _record(name: str, message: str, trace: str, **over: Any) -> dict[str, Any]:
    record = {
        "v": 1,
        "ref": _ref(name),
        "call": over.pop("call", f"call-{name}"),
        "trace_id": trace,
        "session": over.pop("session", SESSION_A),
        "run": over.pop("run", RUN),
        "channel": "wa",
        "message": message,
        "message_sha256": cd.message_digest(message),
        "created_ms": CREATED_MS,
        "expires_ms": CREATED_MS + TTL_MS,
    }
    record.update(over)
    return record


def _token(record: dict[str, Any], *, ref: str | None = None, tag: str | None = None):
    parsed = cd.parse_record(record)
    assert parsed is not None, record
    return cd.TOKEN_HEAD + (ref or parsed.ref) + "." + (tag or parsed.tag) + "]]"


def _tag(record: dict[str, Any]) -> str:
    parsed = cd.parse_record(record)
    assert parsed is not None, record
    return parsed.tag


def _swap_letter(text: str, index: int) -> str:
    letter = text[index]
    other = cd.ALPHABET[(cd.ALPHABET.index(letter) + 1) % len(cd.ALPHABET)]
    return text[:index] + other + text[index + 1 :]


def build() -> dict[str, Any]:
    """Every vector: records by name, then cases that name the records they hold."""
    three, two = three_card_message(), two_card_message()
    assert CARD2_SQFT in three and CARD3_YEAR in three and CARD2_YEAR in three
    records = {
        "s1": _record("s1", three, "trace-alpha"),
        "s2": _record("s2", two, "trace-bravo"),
        "s3": _record("s3", three, "trace-charlie"),
        "tampered": {
            **_record("tampered", three, "trace-delta"),
            "message": three.replace(CARD2_SQFT, CHANGED_SQFT),
        },
        "earlier": _record("earlier", three, "trace-echo", run=EARLIER_RUN),
        "expired": {
            **_record("expired", three, "trace-foxtrot"),
            "expires_ms": NOW_MS - 1,
        },
        "other_session": _record(
            "other_session", three, "trace-golf", session=SESSION_B
        ),
        "other_channel": _record("other_channel", three, "trace-hotel", channel="tg"),
        "extra_field": {**_record("extra_field", three, "trace-india"), "x": "y"},
        # Written as 1.0 and 1793000000000.0: JSON.parse reads them as integers, so the
        # Python reader must too (review of #176; the writer never spells them so).
        "float_numbers": {
            **_record("float_numbers", two, "trace-juliet"),
            "v": 1.0,
            "created_ms": float(CREATED_MS),
            "expires_ms": float(CREATED_MS + TTL_MS),
        },
    }
    t = {name: _token(rec) for name, rec in records.items() if name != "extra_field"}
    extra_ref = records["extra_field"]["ref"]
    t["extra_field"] = cd.TOKEN_HEAD + extra_ref + "." + "b" * cd.TAG_LETTERS + "]]"
    call = {name: rec["call"] for name, rec in records.items()}
    ctx = {"channel": "whatsapp", "session": SESSION_A, "run": RUN, "now_ms": NOW_MS}

    def case(name, text, held, bound, expect, why="", **context):
        action, reason = expect
        result = {"action": action, "reason": reason}
        result["text"] = {
            "withhold": cd.CARD_NOT_DELIVERED_LINE,
            "drop": None,
            "pass": text,
        }.get(action)
        if action == "substitute":
            result["text"] = "\n\n".join(records[r]["message"] for r in held)
        return {
            "name": name,
            "why": why,
            "text": text,
            "records": held,
            "context": {**ctx, "bound_calls": bound, "run_state": "open"} | context,
            "expect": result,
        }

    s1, s2, s3 = t["s1"], t["s2"], t["s3"]
    cases = [
        # --- happy path: the stored cards, byte for byte, in token order ---
        case("one_token", s1, ["s1"], [call["s1"]], ("substitute", "delivered")),
        case(
            "two_tokens",
            s1 + "\n\n" + s2,
            ["s1", "s2"],
            [call["s1"], call["s2"]],
            ("substitute", "delivered"),
        ),
        case(
            "three_tokens",
            s1 + "\n" + s2 + "\n" + s3,
            ["s1", "s2", "s3"],
            [call["s1"], call["s2"], call["s3"]],
            ("substitute", "delivered"),
        ),
        case(
            "blank_around_tokens",
            " \n" + s1 + "\t\r\n",
            ["s1"],
            [call["s1"]],
            ("substitute", "delivered"),
        ),
        case(
            "integral_float_numbers_read_as_integers",
            t["float_numbers"],
            ["float_numbers"],
            [call["float_numbers"]],
            ("substitute", "delivered"),
            "a record whose v and times are written 1.0-style: both readers accept it",
        ),
        case(
            "no_card_plain_reply",
            "Which city should I search?",
            [],
            [],
            ("pass", "no_tokens"),
        ),
        case(
            "no_card_digits_strict_off",
            "A three-bedroom search in 91101 works too.",
            [],
            [],
            ("pass", "no_tokens"),
            "limitation: an invented figure in a reply with no card is not blocked",
        ),
        case(
            "no_card_digits_strict_on",
            "A three-bedroom search in 91101 works too.",
            [],
            [],
            ("withhold", "strict_digits"),
            strict=True,
            card_in_session=True,
        ),
        case(
            "not_whatsapp_never_substitutes",
            s1,
            ["s1"],
            [call["s1"]],
            ("pass", "not_whatsapp"),
            channel="webchat",
        ),
        # --- P1-4 defect 1: card 2's living area changed ---
        case(
            "sqft_changed_free_text",
            three.replace(CARD2_SQFT, CHANGED_SQFT),
            [],
            [call["s1"]],
            ("withhold", "unreferenced"),
            "the model retyped the card and changed card 2's living area",
        ),
        case(
            "sqft_changed_after_token",
            s1 + "\n\nCard 2 has " + CHANGED_SQFT + ".",
            ["s1"],
            [call["s1"]],
            ("withhold", "text_outside_tokens"),
        ),
        case(
            "sqft_changed_in_store",
            t["tampered"],
            ["tampered"],
            [call["tampered"]],
            ("withhold", "digest_mismatch"),
            "the stored text was changed after its digest was taken",
        ),
        # --- P1-4 defect 2: card 3's year built copied from card 2 ---
        case(
            "year_copied_free_text",
            three.replace(CARD3_YEAR, CARD2_YEAR),
            [],
            [call["s1"]],
            ("withhold", "unreferenced"),
        ),
        case(
            "year_copied_after_token",
            s1 + "\n\nThe third home was " + CARD2_YEAR + ".",
            ["s1"],
            [call["s1"]],
            ("withhold", "text_outside_tokens"),
        ),
        # --- missing, stale and cross-session results ---
        case("missing_result", s1, [], [call["s1"]], ("withhold", "unknown_ref")),
        case(
            "stale_other_run",
            t["earlier"],
            ["earlier"],
            [],
            ("withhold", "wrong_run"),
            "a token from an earlier turn ('show those again')",
        ),
        case(
            "stale_other_run_in_card_run",
            t["earlier"],
            ["earlier", "s1"],
            [call["s1"]],
            ("withhold", "wrong_run"),
        ),
        case(
            "stale_expired",
            t["expired"],
            ["expired"],
            [call["expired"]],
            ("withhold", "expired"),
        ),
        case(
            "cross_session",
            t["other_session"],
            ["other_session"],
            [call["other_session"]],
            ("withhold", "wrong_session"),
            "a valid record and tag for session B, delivered in session A",
        ),
        case(
            "record_channel_not_wa",
            t["other_channel"],
            ["other_channel"],
            [call["other_channel"]],
            ("withhold", "wrong_channel"),
        ),
        case(
            "record_with_extra_field_is_missing",
            t["extra_field"],
            ["extra_field"],
            [call["extra_field"]],
            ("withhold", "unknown_ref"),
        ),
        # --- forged tokens ---
        case(
            "forged_ref_letter",
            _token(records["s1"], ref=_swap_letter(records["s1"]["ref"], 0)),
            ["s1"],
            [call["s1"]],
            ("withhold", "unknown_ref"),
        ),
        case(
            "forged_tag_letter",
            _token(records["s1"], tag=_swap_letter(_tag(records["s1"]), 3)),
            ["s1"],
            [call["s1"]],
            ("withhold", "tag_mismatch"),
        ),
        case(
            "forged_made_up",
            cd.TOKEN_HEAD + "b" * cd.REF_LETTERS + "." + "c" * cd.TAG_LETTERS + "]]",
            ["s1"],
            [call["s1"]],
            ("withhold", "unknown_ref"),
        ),
        # --- text around tokens ---
        case(
            "digits_outside_tokens",
            "Here you go 2\n\n" + s1,
            ["s1"],
            [call["s1"]],
            ("withhold", "text_outside_tokens"),
        ),
        case(
            "words_outside_tokens",
            "Here you go:\n\n" + s1,
            ["s1"],
            [call["s1"]],
            ("withhold", "text_outside_tokens"),
        ),
        case(
            "duplicate_token",
            s1 + "\n\n" + s1,
            ["s1"],
            [call["s1"]],
            ("withhold", "duplicate"),
        ),
        case(
            "partial_token_in_block",
            s1[:-12],
            ["s1"],
            [call["s1"]],
            ("withhold", "partial_token"),
        ),
        case(
            "malformed_token",
            cd.TOKEN_HEAD + "not-a-reference]]",
            ["s1"],
            [call["s1"]],
            ("withhold", "malformed_token"),
        ),
        # --- coverage of the run's bound card calls (the plugin's ledger) ---
        case(
            "issued_card_left_unreferenced",
            s1,
            ["s1", "s2"],
            [call["s1"], call["s2"]],
            ("withhold", "unreferenced"),
        ),
        case(
            "token_for_unbound_call",
            s1,
            ["s1"],
            [call["s2"]],
            ("withhold", "unbound"),
        ),
        case(
            "switch_off_with_plugin_on",
            three,
            [],
            [call["s1"]],
            ("withhold", "unreferenced"),
            "the server ignored the binding and sent the full card; the model's copy "
            "is withheld even when every figure is right",
        ),
        case(
            "split_across_payloads",
            s1,
            ["s1", "s2"],
            [call["s1"], call["s2"]],
            ("withhold", "unreferenced"),
            "one payload must carry all of a run's cards",
        ),
        case(
            "token_repeated_in_later_payload",
            s1,
            ["s1"],
            [call["s1"]],
            ("drop", "already_released"),
            run_state="released",
        ),
        case(
            "commentary_after_release",
            "Anything else?",
            [],
            [call["s1"]],
            ("drop", "after_release"),
            run_state="released",
        ),
        case(
            "after_a_failure",
            s1,
            ["s1"],
            [call["s1"]],
            ("drop", "run_failed"),
            run_state="failed",
        ),
        case("no_run_id_with_token", s1, ["s1"], [], ("withhold", "no_run_id"), run=""),
        case("no_run_id_plain", "Hello again.", [], [], ("pass", "no_tokens"), run=""),
    ]
    tags = [
        {
            "name": name,
            "record": records[name],
            "expect": {
                "tag": _tag(records[name]),
                "token": t[name],
                "file_name": cd.file_name(records[name]["ref"]),
            },
        }
        for name in ("s1", "s2")
    ]
    return {
        "version": 1,
        "note": "Synthetic cards only. Generated by tests/card_delivery_vectors.py.",
        "constants": {
            "alphabet": cd.ALPHABET,
            "token_head": cd.TOKEN_HEAD,
            "token_tail": cd.TOKEN_TAIL,
            "card_not_delivered_line": cd.CARD_NOT_DELIVERED_LINE,
            "channel_refusal": cd.CHANNEL_REFUSAL,
            "default_card_dir": cs.DEFAULT_DIR,
        },
        "sessions": [
            {"session_key": key, "digest": cd.session_digest(key)}
            for key in (SESSION_KEY_A, SESSION_KEY_B)
        ],
        "tags": tags,
        "records": records,
        "cases": cases,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        PATH.write_text(render(), encoding="utf-8")
    else:
        sys.stdout.write(render())
