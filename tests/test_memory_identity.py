"""Sender identity (WO-006 req. 7): a keyed hash of the normalized id, never the id.

All numbers use the reserved 555 prefix and the secrets are invented. The raw id
must never come back, be logged, or be hashed without a configured key.
"""

import hashlib
import hmac
import logging
import re
from pathlib import Path

import pytest

from idx_agent.domain.models import UserSession
from idx_agent.memory import SENDER_KEY_ENV, identity, key_prefix, sender_key

# Invented secrets standing in for IDX_SENDER_KEY, derived at run time (no literal).
SECRET = hashlib.sha256(b"invented test secret one").hexdigest()[:32]
OTHER_SECRET = hashlib.sha256(b"invented test secret two").hexdigest()[:32]
# One invented number written the ways a channel or a person might write it.
CANONICAL = "+15550100100"
VARIANTS = [
    CANONICAL,
    "15550100100",
    "+1 (555) 010-0100",
    "+1-555-010-0100",
    "1.555.010.0100",
    "  +1 555 010 0100  ",
]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    """Start every test without IDX_SENDER_KEY so the environment never leaks in."""
    monkeypatch.delenv(SENDER_KEY_ENV, raising=False)


def test_key_is_hmac_sha256_hex_of_the_e164_form():
    expected = hmac.new(
        SECRET.encode("utf-8"), CANONICAL.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert sender_key(CANONICAL, SECRET) == expected
    assert HEX64.match(expected)


def test_key_is_stable_across_calls():
    assert sender_key(CANONICAL, SECRET) == sender_key(CANONICAL, SECRET)


@pytest.mark.parametrize("raw", VARIANTS)
def test_normalization_variants_give_the_same_key(raw):
    assert sender_key(raw, SECRET) == sender_key(CANONICAL, SECRET)


def test_different_numbers_give_different_keys():
    assert sender_key("+15550100101", SECRET) != sender_key(CANONICAL, SECRET)


def test_key_differs_by_secret():
    assert sender_key(CANONICAL, SECRET) != sender_key(CANONICAL, OTHER_SECRET)


def test_secret_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv(SENDER_KEY_ENV, SECRET)
    assert sender_key(CANONICAL) == sender_key(CANONICAL, SECRET)


@pytest.mark.parametrize("env_value", [None, ""])
def test_none_without_a_configured_key(monkeypatch, env_value):
    if env_value is not None:
        monkeypatch.setenv(SENDER_KEY_ENV, env_value)
    else:
        # Neither the environment nor a .env file supplies the secret.
        monkeypatch.setattr(identity, "env_setting", lambda name: None)
    assert sender_key(CANONICAL) is None
    assert sender_key(CANONICAL, "") is None


@pytest.mark.parametrize(
    "bad_secret",
    [
        "0f1e2d3c4b5a6978",  # hex but only 16 characters
        "0f1e2d3c4b5a69788796a5b4c3d2e1f",  # hex, one short of 32
        "not-hex-but-long-enough-to-pass-a-length-check-alone",
        "g" * 64,  # right length, not hex
        "replace-me-with-random-hex",  # the old .env.example placeholder
        "",  # the .env.example value today: empty
        " " + "ab" * 32,  # padding is not trimmed into a valid key
    ],
)
def test_an_unusable_secret_counts_as_not_configured(monkeypatch, bad_secret):
    assert identity.secret_configured(bad_secret) is False
    assert sender_key(CANONICAL, bad_secret) is None
    monkeypatch.setenv(SENDER_KEY_ENV, bad_secret)
    assert sender_key(CANONICAL) is None


@pytest.mark.parametrize("good_secret", ["ab" * 32, "AB" * 32, "0F" * 16, SECRET])
def test_hex_of_at_least_32_characters_is_configured(monkeypatch, good_secret):
    assert identity.secret_configured(good_secret) is True
    monkeypatch.setenv(SENDER_KEY_ENV, good_secret)
    assert HEX64.match(sender_key(CANONICAL) or "")
    assert sender_key(CANONICAL) == sender_key(CANONICAL, good_secret)


def test_the_env_example_value_is_not_configured():
    """.env.example ships IDX_SENDER_KEY empty, never a usable placeholder."""
    example = Path(__file__).resolve().parents[1] / ".env.example"
    lines = example.read_text(encoding="utf-8").splitlines()
    values = [ln.partition("=")[2] for ln in lines if ln.startswith(SENDER_KEY_ENV)]
    assert values == [""]
    assert identity.secret_configured(values[0]) is False


def test_secret_falls_back_to_the_env_file(monkeypatch, tmp_path):
    """The server OpenClaw starts has no shell environment; .env supplies the secret."""
    monkeypatch.delenv(SENDER_KEY_ENV, raising=False)
    (tmp_path / ".env").write_text(f"{SENDER_KEY_ENV}={SECRET}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert sender_key(CANONICAL) == sender_key(CANONICAL, SECRET)


@pytest.mark.parametrize(
    "raw",
    [
        "sender-a",
        "",
        "   ",
        "+1234567",  # too short
        "+0 555 010 0100",  # leading zero
        "++15550100100",
        "1555+0100100",
        "+1555010010012345",  # too long
        "+1 555 010 0100 ext 7",
    ],
)
def test_none_for_an_id_that_is_not_a_number(raw):
    assert sender_key(raw, SECRET) is None


def test_none_for_a_non_string_id():
    assert sender_key(15550100100, SECRET) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", VARIANTS)
def test_input_never_appears_in_what_is_returned(raw):
    key = sender_key(raw, SECRET)
    digits = re.sub(r"\D", "", raw)
    for text in (key, str(key), repr(key), key_prefix(key)):
        assert raw.strip() not in text
        assert digits not in text
        assert "5550100" not in text


def test_nothing_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    sender_key(VARIANTS[2], SECRET)
    sender_key("sender-a", SECRET)
    sender_key(CANONICAL)
    assert caplog.records == []


def test_key_is_a_valid_session_sender_id():
    key = sender_key(CANONICAL, SECRET)
    session = UserSession.model_validate(
        {"sender_id": key, "updated_at": "2026-06-30T12:00:00Z"}
    )
    assert session.sender_id == key


def test_raw_number_is_refused_as_a_session_sender_id():
    with pytest.raises(ValueError):
        UserSession.model_validate(
            {"sender_id": CANONICAL, "updated_at": "2026-06-30T12:00:00Z"}
        )


def test_key_prefix_is_eight_characters():
    key = sender_key(CANONICAL, SECRET)
    assert key_prefix(key) == key[:8]
    assert len(key_prefix(key)) == 8
    assert key_prefix(None) == "-"
