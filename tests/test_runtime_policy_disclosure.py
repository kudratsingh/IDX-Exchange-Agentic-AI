"""WO-042: the AI disclosure and human referral in `config/IDX_RUNTIME.md`.

The owned WhatsApp channel withholds unsent figures (verifier R4) and prose on a card
turn (R1b), so both rules must be digit-free (no `\\p{N}`) and leave card turns alone.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import unicodedata

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "idx_policy_installer_wo042", ROOT / "scripts/install_runtime_policy.py"
)
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)
POLICY = ROOT / "config" / "IDX_RUNTIME.md"
HEADING = "## Disclosure and the licensed agent"
DISCLOSURE = "I'm an automated AI assistant, not a person."
REFERRAL = (
    "I'm an automated AI assistant and can't handle offers, contracts, showings or "
    "other transactions. Please reach the licensed agent using the contact in this "
    "profile."
)
OLD_CONTACT_LINE = "Never expose credentials or agent contact information."
NARROWED = (
    "Never expose credentials, and never write out anyone's contact details, listing "
    "agents' included. The one exception is the transactional line above: it points to "
    "the contact in this profile without writing any detail out."
)
CARD_RULE = (
    "After one listing search, market figures, similar listings or a recommendation, "
    "that message is the whole reply: nothing before it and nothing after it."
)


def text() -> str:
    return POLICY.read_text(encoding="utf-8")


def flat(value: str) -> str:
    """The text with every run of whitespace (line breaks included) as one space."""
    return " ".join(value.split())


def section(value: str) -> str:
    """The disclosure section, from its heading to the next heading."""
    start = value.index(HEADING)
    end = value.find("\n## ", start + len(HEADING))
    return value[start : end if end != -1 else len(value)]


def figures(value: str) -> list[str]:
    """Every numeric character (Unicode category N*), as the verifier's `\\p{N}`."""
    return [c for c in value if unicodedata.category(c).startswith("N")]


def test_the_disclosure_rule_and_its_two_triggers_are_present():
    body = flat(section(text()))
    assert DISCLOSURE in body
    assert "in the first reply of a conversation" in body
    assert "whenever asked whether you are a bot, an AI or a person" in body


def test_the_referral_is_one_exact_line_that_names_no_one():
    lines = text().splitlines()
    assert lines.count(REFERRAL) == 1
    body = flat(section(text()))
    assert "For an offer, a contract, a showing or anything else transactional" in body
    assert "call no tool and reply with exactly this single line" in body


def test_card_turns_stay_intact_and_the_disclosure_waits():
    whole, body = flat(text()), flat(section(text()))
    assert CARD_RULE in whole
    assert "Card turns stay as they are." in body
    assert "add nothing to it, the disclosure included" in body
    assert "give the disclosure in the next reply that is neither" in body
    assert "the card turn wins: reply with the tool's message only" in body


@pytest.mark.parametrize("part", ["section", "narrowed"])
def test_the_new_text_carries_no_figure_token_or_placeholder(part):
    value = section(text()) if part == "section" else NARROWED
    assert figures(value) == []
    for fragment in ("[[", "]]", "[card:", "agent:", "@", "<", ">", "{", "}"):
        assert fragment not in value
    assert re.search(r"\b(TODO|TBD|XXX|NAME|BROKER)\b", value) is None


def test_the_contact_sentence_is_narrowed_and_still_forbids_credentials():
    whole = flat(text())
    assert OLD_CONTACT_LINE not in whole
    assert NARROWED in whole
    assert "Never expose credentials" in whole
    assert "never write out anyone's contact details" in whole


def test_no_license_or_broker_identity_text_is_added():
    """Q3 (advertising identity) is pending with the broker (WO-042 design note 5)."""
    body = section(text()).lower()
    for word in ("license", "licence", "broker", "dre"):
        assert re.search(rf"\b{word}\b", body) is None


def test_the_installed_block_and_the_eval_prompt_carry_the_new_rules(tmp_path):
    from evals import run as runner

    workspace = tmp_path / "workspace"
    installer.install_policy(POLICY, workspace)
    installed = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    prompt = runner.routing_prompt(runner.configured_skills())
    for value in (installed, prompt):
        assert REFERRAL in value and DISCLOSURE in value
        assert NARROWED in flat(value) and OLD_CONTACT_LINE not in flat(value)
