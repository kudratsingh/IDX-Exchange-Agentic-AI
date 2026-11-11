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
CANT_HELP = (
    "I can't help with that. I can find homes for sale, give market figures from past "
    "sales, find homes like a description or a listing, and explain a real-estate term."
)
DECLINE = (
    "Drafts go out only after the owner approves them outside this chat. I can't "
    "send, approve, or change the recipient here."
)
OLD_CONTACT_LINE = "Never expose credentials or agent contact information."
NARROWED = (
    "Never expose credentials, and never write out anyone's contact details, listing "
    "agents' included. The one exception is the transactional line above: it points to "
    "the contact in this profile without writing any detail out."
)
EXCEPTION_REF = "The one exception is the transactional line above"
CARD_RULE = (
    "After one listing search, market figures, similar listings or a recommendation, "
    "that message is the whole reply: nothing before it and nothing after it."
)
# Brokerage identity wording (Q3 pending with the broker). "licensed agent" is the one
# allowed phrase; it is removed before the scan.
IDENTITY_RE = re.compile(r"\b(licen[cs]e\w*|broker\w*|dre|realty|realtor\w*)\b", re.I)


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


def contact_paragraph(value: str) -> str:
    """The paragraph that holds the narrowed contact sentence."""
    start = value.index("Never expose credentials")
    end = value.find("\n\n", start)
    return value[start : end if end != -1 else len(value)]


def figures(value: str) -> list[str]:
    """Every numeric character (Unicode category N*), as the verifier's `\\p{N}`."""
    return [c for c in value if unicodedata.category(c).startswith("N")]


def identity_words(value: str) -> list[str]:
    """Brokerage identity words, after removing the allowed "licensed agent"."""
    cleaned = re.sub(r"\blicensed agent\b", "", value, flags=re.I)
    return [m.group(0) for m in IDENTITY_RE.finditer(cleaned)]


def test_the_disclosure_rule_and_its_two_triggers_are_present():
    body = flat(section(text()))
    assert DISCLOSURE in body
    assert "in the first reply of a conversation" in body
    assert "whenever asked whether you are a bot, an AI or a person" in body


def test_the_identity_question_comes_first_and_gets_the_sentence_alone():
    """Review of #189 item 1: a bot-or-person question is answered on its own turn,
    with no tool call, so even a conversation of card turns can get the sentence."""
    body = flat(section(text()))
    assert (
        "When a message asks whether you are a bot, an AI or a person, that question "
        "comes first: call no tool, even if the message also asks for something else, "
        "and reply with the sentence above alone. Handle the rest of the request on "
        "the next turn." in body
    )
    # The rule sits before the card-turn deferral, which would otherwise swallow it.
    assert body.index("that question comes first") < body.index("On a card turn")


def test_the_referral_is_one_exact_line_and_comes_before_cant_help():
    lines = text().splitlines()
    assert lines.count(REFERRAL) == 1
    body = flat(section(text()))
    assert "For an offer, a contract, a showing or anything else transactional" in body
    assert "call no tool and reply with exactly this single line" in body
    assert "It comes before the can't-help line above:" in body


def test_the_outside_roles_rule_hands_off_transactions_and_draft_requests():
    whole = flat(text())
    assert (
        "Two kinds of request no IDX tool serves are not this case. A transactional "
        "request (an offer, a contract, a showing or another transaction) gets the "
        "referral line in the next section. A request to send, approve or change the "
        "recipient of a draft keeps the draft decline below." in whole
    )
    assert (
        "That decline, not the referral line, answers a request to send, approve or "
        "change the recipient of a draft." in whole
    )
    assert whole.index("Two kinds of request") < whole.index(HEADING)


@pytest.mark.parametrize("line", [CANT_HELP, DECLINE], ids=["cant-help", "decline"])
def test_each_fixed_line_appears_once_as_its_own_line_without_a_prefix(line):
    lines = text().splitlines()
    assert lines.count(line) == 1
    assert sum(line in other for other in lines) == 1
    assert DISCLOSURE + " " + line not in flat(text())


def test_tool_replies_and_fixed_replies_stay_as_written():
    """Review items 4 and 5: every verbatim tool message or error stays exact; so does
    every fixed reply, the referral line included; the disclosure waits."""
    whole, body = flat(text()), flat(section(text()))
    assert CARD_RULE in whole
    assert (
        "A reply that copies a tool's message or its error.message verbatim (a "
        "listing search, market figures, similar listings, a recommendation, health, "
        "a document answer's error, an email draft, saved searches or an analysis) "
        "gets nothing added to it, the disclosure included." in body
    )
    assert "Another fixed reply in this policy also stays exactly as written." in body
    assert "give the disclosure in the next reply that is none of these" in body
    assert (
        "The referral line is itself a fixed reply: the disclosure sentence still "
        "follows in the next reply that is none of these." in body
    )


def test_a_deferred_referral_waits_like_the_disclosure():
    """Review item 3: a deferred line never joins a card turn or a fixed reply."""
    body = flat(section(text()))
    assert (
        "the card turn wins: reply with the tool's message only, and give the line "
        "above, on its own, as the next reply that is neither a card turn nor another "
        "fixed reply." in body
    )


@pytest.mark.parametrize("part", ["section", "contact"])
def test_the_new_text_carries_no_figure_token_or_placeholder(part):
    value = section(text()) if part == "section" else contact_paragraph(text())
    assert figures(value) == []
    for fragment in ("[[", "]]", "[card:", "agent:", "@", "<", ">", "{", "}"):
        assert fragment not in value
    assert re.search(r"\b(TODO|TBD|XXX|NAME|BROKER)\b", value, re.I) is None


def test_the_contact_sentence_is_narrowed_and_still_forbids_credentials():
    whole = flat(text())
    assert OLD_CONTACT_LINE not in whole
    assert NARROWED in whole
    assert "Never expose credentials" in whole
    assert "never write out anyone's contact details" in whole


@pytest.mark.parametrize("part", ["section", "contact"])
def test_no_license_or_broker_identity_text_is_added(part):
    """Q3 (advertising identity) is pending with the broker (WO-042 design note 5)."""
    value = section(text()) if part == "section" else contact_paragraph(text())
    assert identity_words(value) == []


@pytest.mark.parametrize(
    "sample",
    [
        "You are an automated AI assistant for Acme Realty, not a person.",
        "Ask the licensee, Jane Roe.",
        "Brokerage: Example Homes.",
        "DRE number on request.",
        "Reach our Realtor team.",
        "Licence shown in the profile.",
    ],
)
def test_the_identity_scan_catches_brokerage_wording(sample):
    assert identity_words(sample) != []
    assert identity_words("Please reach the licensed agent using the contact.") == []


def test_the_referral_line_comes_before_the_exception_that_points_to_it(tmp_path):
    """Review item 9: "the transactional line above" must point at the referral line,
    in the file, the installed managed block and the eval routing prompt."""
    from evals import run as runner

    workspace = tmp_path / "workspace"
    installer.install_policy(POLICY, workspace)
    installed = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    prompt = runner.routing_prompt(runner.configured_skills())
    for value in (text(), installed, prompt):
        assert value.count(REFERRAL) == 1 and value.count(EXCEPTION_REF) == 1
        assert value.index(REFERRAL) < value.index(EXCEPTION_REF)


def test_the_installed_block_and_the_eval_prompt_carry_the_new_rules(tmp_path):
    from evals import run as runner

    workspace = tmp_path / "workspace"
    installer.install_policy(POLICY, workspace)
    installed = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    prompt = runner.routing_prompt(runner.configured_skills())
    for value in (installed, prompt):
        assert REFERRAL in value and DISCLOSURE in value
        assert NARROWED in flat(value) and OLD_CONTACT_LINE not in flat(value)
        assert "that question comes first" in flat(value)
