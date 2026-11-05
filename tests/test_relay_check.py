"""The deterministic relay check and its CLI (P1-4 follow-up, 2026-11-05).

All listings are invented (format_search_reply over synthetic Listing models); the
OpenClaw transcript records are synthetic too, in the shape the gateway stores.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from idx_agent.channels.format import format_search_reply
from idx_agent.channels.relay_check import check_card_relay, number_tokens
from idx_agent.domain.models import Listing

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 18)


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "check_relay", ROOT / "scripts" / "check_relay.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


def _message() -> str:
    listings = [
        Listing(
            listing_key=9190001,
            listing_id="FIXTURE-9190001",
            address="1 Synthetic Example Lane",
            city="Pasadena",
            postal_code="91101",
            list_price=3_180_000,
            bedrooms=4,
            bathrooms=4,
            living_area=3412,
            days_on_market=20,
            photo_count=12,
        ),
        Listing(
            listing_key=9190002,
            listing_id="FIXTURE-9190002",
            address="2 Synthetic Example Lane",
            city="Pasadena",
            postal_code="91101",
            list_price=4_950_000,
            bedrooms=5,
            bathrooms=5,
            living_area=4872,
            days_on_market=1,
            photo_count=20,
        ),
    ]
    return format_search_reply(listings, AS_OF, "Filters: city Pasadena, with pool")


MESSAGE = _message()
ROUNDED = MESSAGE.replace("4,872 sqft", "5,000 sqft")


def test_the_message_itself_passes_exactly():
    result = check_card_relay(MESSAGE, MESSAGE)
    assert (result.status, result.reason, result.mismatches) == ("pass", "exact", ())


def test_line_endings_and_trailing_spaces_do_not_count():
    shown = MESSAGE.replace("\n", "  \r\n") + "\n"
    assert check_card_relay(MESSAGE, shown).reason == "exact"


def test_digit_free_prose_around_the_whole_message_passes():
    shown = "Here you go:\n\n" + MESSAGE + "\n\nWant me to widen the search?"
    assert check_card_relay(MESSAGE, shown).reason == "whole"


def test_the_p1_4_defect_class_fails_at_card_2_sqft():
    """A rounded living area, then an appended correction: still a failure."""
    shown = ROUNDED + "\n\nSorry, the second home is 4,872 sqft."
    result = check_card_relay(MESSAGE, shown)
    assert (result.status, result.reason) == ("fail", "changed")
    first = result.mismatches[0]
    assert (first.card, first.unit) == (2, "sqft")
    assert (first.expected.value, first.got.value) == (Decimal(4872), Decimal(5000))
    assert result.reply_only == (Decimal(5000),)
    summary = result.summary()
    assert summary["first_mismatch"] == {"card": 2, "unit": "sqft"}
    assert "4872" not in json.dumps(summary) and "5000" not in json.dumps(summary)


def test_a_changed_card_then_the_whole_message_restated_still_fails():
    """Layer 1 (owner, 2026-11-05): a later correction never passes the turn, even one
    that repeats the whole message unchanged after the wrong figure."""
    shown = ROUNDED + "\n\nCorrection, the right list:\n\n" + MESSAGE
    result = check_card_relay(MESSAGE, shown)
    assert (result.status, result.reason) == ("fail", "extra_numbers")
    assert result.reply_only == (Decimal(5000),)


def test_a_whole_message_with_a_number_in_the_added_text_fails():
    result = check_card_relay(MESSAGE, MESSAGE + "\n\nThe second home has 4,872 sqft.")
    assert (result.status, result.reason, result.extra_digits) == (
        "fail",
        "extra_numbers",
        4,
    )


@pytest.mark.parametrize(
    ("old", "new", "card", "unit"),
    [
        ("$3,180,000", "$3.2M", 1, "price"),
        ("4 beds", "3 beds", 1, "beds"),
        ("5 baths", "6 baths", 2, "baths"),
        ("20 photos", "21 photos", 2, "photos"),
        ("1 day on market", "2 days on market", 2, "days_on_market"),
    ],
)
def test_each_card_number_is_attributed_to_its_card_and_unit(old, new, card, unit):
    assert MESSAGE.count(old) == 1
    result = check_card_relay(MESSAGE, MESSAGE.replace(old, new))
    assert result.status == "fail"
    assert (result.mismatches[0].card, result.mismatches[0].unit) == (card, unit)


def test_reordered_cards_fail():
    head, first, second, tail = MESSAGE.split("\n\n")
    swapped = "\n\n".join([head, second, first, tail])
    assert check_card_relay(MESSAGE, swapped).status == "fail"


def test_a_dropped_card_fails():
    head, first, _second, tail = MESSAGE.split("\n\n")
    assert check_card_relay(MESSAGE, "\n\n".join([head, first, tail])).status == "fail"


@pytest.mark.parametrize(
    ("message", "reply"),
    [(None, "x"), ("x", None), ("", "x"), ("x", "  "), ("x" * 100_001, "x")],
)
def test_missing_or_oversized_input_is_unavailable_not_a_pass(message, reply):
    assert check_card_relay(message, reply).status == "unavailable"


def test_number_tokens_name_dates_and_the_summary_line():
    tokens = number_tokens(MESSAGE)
    assert tokens[0].card == 0 and tokens[0].unit == "listings"
    assert any(t.unit == "date" and t.card == 0 for t in tokens)


# --- the CLI ---


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_cli_files_pass_and_fail_with_exit_codes(tmp_path, capsys):
    message = _write(tmp_path, "m.txt", MESSAGE)
    assert cli.main(["--message", str(message), "--reply", str(message)]) == 0
    assert capsys.readouterr().out.startswith("status=pass reason=exact")
    reply = _write(tmp_path, "r.txt", ROUNDED)
    assert cli.main(["--message", str(message), "--reply", str(reply)]) == 1
    out = capsys.readouterr().out
    assert "status=fail reason=changed" in out and "first_mismatch='card 2 sqft'" in out
    # Without --values no listing number or text is printed.
    assert "4872" not in out and "5000" not in out and "Synthetic" not in out
    assert cli.main(["--message", str(message), "--reply", str(reply), "--values"]) == 1
    assert "expected=4872 reply=5000" in capsys.readouterr().out


def _structured(message: str, trace: str) -> dict:
    return {
        "ok": True,
        "data": {"listings": [{"bathrooms": 5.0}]},
        "message": message,
        "provenance": {"tool": "search_listings", "trace_id": trace},
    }


def _transcript(message: str, reply: str, trace: str = "abc123def4567890") -> str:
    sc = _structured(message, trace)
    records = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "idx__search_listings"}],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolName": "idx__search_listings",
                "content": [
                    {
                        "type": "text",
                        "text": "structuredContent:\n"
                        + json.dumps(sc, indent=2, sort_keys=True),
                    },
                    {"type": "text", "text": json.dumps(sc, indent=2)},
                ],
                "details": {"structuredContent": sc},
            },
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": reply}],
            },
        },
    ]
    return "\n".join(json.dumps(r) for r in records) + "\n"


def test_cli_reads_the_tool_message_and_reply_from_a_transcript(tmp_path, capsys):
    path = _write(tmp_path, "t.jsonl", _transcript(MESSAGE, ROUNDED))
    code = cli.main(["--transcript", str(path), "--trace-id", "abc123def4567890"])
    out = capsys.readouterr().out
    assert code == 1 and "first_mismatch='card 2 sqft'" in out
    assert "tool_blocks=2" in out
    path = _write(tmp_path, "ok.jsonl", _transcript(MESSAGE, MESSAGE))
    assert cli.main(["--transcript", str(path), "--trace-id", "abc123def4567890"]) == 0


def test_cli_transcript_problems_are_unavailable(tmp_path, capsys):
    path = _write(tmp_path, "t.jsonl", _transcript(MESSAGE, MESSAGE))
    assert cli.main(["--transcript", str(path), "--trace-id", "0000000000000000"]) == 2
    assert "0 tool results name the trace" in capsys.readouterr().out
    text = _transcript(MESSAGE, MESSAGE).replace("Showing 2", "Showing 3", 1)
    path = _write(tmp_path, "split.jsonl", text)
    assert cli.main(["--transcript", str(path), "--trace-id", "abc123def4567890"]) == 2
    assert "2 distinct messages" in capsys.readouterr().out
    lines = _transcript(MESSAGE, MESSAGE).splitlines()[:2]
    path = _write(tmp_path, "noreply.jsonl", "\n".join(lines))
    assert cli.main(["--transcript", str(path), "--trace-id", "abc123def4567890"]) == 2
    assert "no assistant reply" in capsys.readouterr().out
