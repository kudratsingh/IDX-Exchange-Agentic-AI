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
RESEND = DISCLOSURE + " Please send your other request again."
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
    "agents' included. The one exception is the referral line above: it points to "
    "the contact in this profile without writing any detail out."
)
EXCEPTION_REF = "The one exception is the referral line above"
CARD_RULE = (
    "After one listing search, market figures, similar listings or a recommendation, "
    "that message is the whole reply: nothing before it and nothing after it."
)
# Brokerage identity wording (Q3 pending with the broker). "licensed agent" is the one
# allowed phrase; it is removed before the scan.
IDENTITY_RE = re.compile(r"\b(licen[cs]\w*|broker\w*|dre|realty|realtor\w*)\b", re.I)


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


def test_the_identity_question_comes_first_and_asks_for_a_resend():
    """Review of #189 item 1, re-verification item 3: a bot-or-person question is
    answered on its own turn with no tool call; when the message asked for more, the
    reply says to send that again, since the model gets no turn of its own."""
    body = flat(section(text()))
    assert (
        "When a message asks whether you are a bot, an AI or a person, that question "
        "comes first: call no tool and reply with the sentence above alone. If the "
        "same message also asks for something else, call no tool and reply instead "
        "with exactly this single line:" in body
    )
    assert text().splitlines().count(RESEND) == 1
    assert figures(RESEND) == []
    # The rule sits before the card-turn rule, which would otherwise swallow it.
    assert body.index("that question comes first") < body.index("On a card turn")


def test_a_transactional_request_comes_first_and_gets_the_referral_alone():
    """Re-verification item 2: like the identity question, a transactional request
    is answered at once, so the referral is never deferred behind card turns."""
    lines = text().splitlines()
    assert lines.count(REFERRAL) == 1
    body = flat(section(text()))
    assert (
        "When a message includes an offer, a contract, a showing, anything else "
        "transactional, or a request to talk to or reach a person, a human or the "
        "agent, call no tool, even if the message also asks for something else, and "
        "reply with exactly this single line. It comes before the can't-help line "
        "above:" in body
    )
    assert "neither a card turn nor another fixed reply" not in body
    assert "the card turn wins" not in body
    assert body.index("anything else transactional") < body.index("On a card turn")


def test_a_request_for_a_person_or_the_agent_gets_the_referral():
    """Third review item 2: a buyer asking for a human gets the route to the licensed
    agent, in the policy and in the server instructions, never the can't-help line."""
    from idx_agent.mcp_server import server

    trigger = "a request to talk to or reach a person, a human or the agent"
    assert trigger in flat(section(text()))
    assert (
        "or a request to talk to or reach a person, a human or the agent, gets the "
        "referral line in the next section." in flat(text())
    )
    for instructions in (server.BASE_INSTRUCTIONS, server.ANALYSIS_INSTRUCTIONS):
        assert trigger in instructions
        assert "a question whether you are a bot, an AI or a person" in instructions
        assert instructions.index(trigger) < instructions.index(
            "I can't help with that"
        )


PRIORITY_RE = re.compile(
    r"When a message calls for more than one fixed line in this policy, reply with "
    r"only the line of highest priority: (?P<order>[^.]+)\."
)


def priority_order() -> list[str]:
    """The fixed lines in priority order, parsed from the policy file's own sentence
    (not from a constant in this test)."""
    found = PRIORITY_RE.findall(flat(text()))
    assert len(found) == 1, found
    names = []
    for part in found[0].split(","):
        name = re.sub(r"^(then )?the ", "", part.strip())
        names.append(re.sub(r" line( first)?$", "", name))
    return names


def winner(*triggered: str) -> str:
    order = priority_order()
    return min(triggered, key=order.index)


def test_one_message_gets_one_fixed_line_by_priority():
    """Re-verification item 4: "comes before" is priority, not order."""
    body = flat(section(text()))
    assert "One message gets at most one fixed line." in body
    assert (
        '"Comes before" in this policy means this priority, never an order in which '
        "to send two lines." in body
    )
    assert "These rules also come before the mixed-request rule above." in body
    # Count guard: a second precedence sentence anywhere in the policy would make the
    # order ambiguous, so the phrases appear only in the known places.
    whole = flat(text()).lower()
    assert whole.count("comes before") == 2  # the referral rule and the definition
    assert whole.count("priority") == 3  # highest priority, this priority, the note
    assert priority_order() == ["identity", "referral", "draft decline", "can't-help"]
    # Messages that match both the draft decline and the referral trigger: the
    # referral wins (a transaction, or a request to reach a person, final review).
    for message in (
        "send the draft and make an offer on it",
        "send it, and can I talk to a real person?",
    ):
        assert winner("draft decline", "referral") == "referral", message
    assert winner("can't-help", "referral") == "referral"
    assert winner("referral", "identity") == "identity"
    assert winner("can't-help", "draft decline") == "draft decline"
    assert (
        "A message that also includes a transactional request, or a request to talk "
        "to or reach a person, a human or the agent, gets the referral line instead, "
        "by the priority above." in flat(text())
    )


def test_a_composed_first_reply_opens_with_the_disclosure():
    """Re-verification item 5: docs-qa ends with its Sources line, unchanged."""
    body = flat(section(text()))
    assert (
        "When the disclosure is due in a reply you compose yourself, such as a "
        "successful document answer, make the disclosure sentence the first sentence "
        "of the reply. A document answer's Sources line stays last and unchanged."
        in body
    )
    skill = flat((ROOT / "skills/docs-qa/SKILL.md").read_text(encoding="utf-8"))
    assert "Sources line" in skill


def test_the_outside_roles_rule_hands_off_transactions_and_draft_requests():
    whole = flat(text())
    assert (
        "Three kinds of message no IDX tool serves are not this case. A question "
        "whether you are a bot, an AI or a person gets the identity line in the next "
        "section. A transactional request (an offer, a contract, a showing or another "
        "transaction), or a request to talk to or reach a person, a human or the "
        "agent, gets the referral line in the next section. A request to send, "
        "approve or change the recipient of a draft keeps the draft decline below, "
        "unless the same message also includes one of the requests that get the "
        "referral line." in whole
    )
    assert (
        "That decline, not the referral line, answers a request to send, approve or "
        "change the recipient of a draft." in whole
    )
    assert whole.index("Three kinds of message") < whole.index(HEADING)


@pytest.mark.parametrize(
    "line",
    [CANT_HELP, DECLINE, REFERRAL, RESEND],
    ids=["cant-help", "decline", "referral", "resend"],
)
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
    """Q3 (advertising identity) is pending with the broker (WO-042 design note 6)."""
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
        "Licensing details on request.",
        "Our licencing board.",
    ],
)
def test_the_identity_scan_catches_brokerage_wording(sample):
    assert identity_words(sample) != []
    assert identity_words("Please reach the licensed agent using the contact.") == []


def test_the_referral_line_comes_before_the_exception_that_points_to_it(tmp_path):
    """Review item 9: "the referral line above" must point at the referral line,
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
