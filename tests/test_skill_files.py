"""Lint every skills/*/SKILL.md: frontmatter, the one tool call, line length, the data
line, the email decline, and no contact details.

Each check takes a skills directory and returns a list of problems, so the synthetic
test at the end can point it at an invented bad skill under tmp_path.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from collections.abc import Callable

import pytest
import yaml

from idx_agent.mcp_server import server as mcp

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
# The PII gate's own patterns and placeholder allowances, imported read-only.
sys.path.insert(0, str(ROOT / "scripts" / "gates"))

import pii_scan  # noqa: E402

NAME = re.compile(r"^[a-z0-9-]+$")
MAX_DESCRIPTION = 400
MAX_LINE = 120
# The same call-line pattern as tests/test_routing_contract.py.
CALL = re.compile(r"\bcall (?:the tool )?`idx__(\w+)`", re.IGNORECASE)
DATA_LINE = re.compile(r"\bdata\b[^.]*\bnever instructions\b")
EMAIL_WORD = re.compile(r"\bemails?\b", re.IGNORECASE)

Problems = list[str]


def skill_files(skills_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(skills_dir.glob("*/SKILL.md"))


def split_skill(path: pathlib.Path) -> tuple[str, str]:
    """Return (raw frontmatter, body); raise ValueError when there is no frontmatter."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError("no --- frontmatter block at the top")
    return match.group(1), match.group(2)


def parse_skill(path: pathlib.Path) -> tuple[dict, str, str]:
    """Return (meta, raw frontmatter, body); raise ValueError if unparsable."""
    front, body = split_skill(path)
    try:
        meta = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter is not YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return meta, front, body


def parsed_skills(skills_dir: pathlib.Path) -> list[tuple[str, dict, str, str]]:
    """(folder, meta, raw frontmatter, body) of each skill whose frontmatter parses."""
    out = []
    for path in skill_files(skills_dir):
        try:
            meta, front, body = parse_skill(path)
        except ValueError:
            continue  # reported by check_frontmatter
        out.append((path.parent.name, meta, front, body))
    return out


def registered_tools() -> set[str]:
    """Tool names the MCP server registers; OpenClaw exposes each as idx__<name>."""
    return {t.name for t in asyncio.run(mcp.server.list_tools())}


def check_frontmatter(skills_dir: pathlib.Path) -> Problems:
    """name: lowercase letters, digits, hyphens, equal to the folder; description: one
    line of at most 400 characters."""
    problems = []
    for path in skill_files(skills_dir):
        folder = path.parent.name
        try:
            meta, front, _ = parse_skill(path)
        except ValueError as exc:
            problems.append(f"{folder}: {exc}")
            continue
        name = meta.get("name")
        if not isinstance(name, str) or not NAME.match(name):
            problems.append(
                f"{folder}: name {name!r} is not lowercase letters, digits, hyphens"
            )
        elif name != folder:
            problems.append(f"{folder}: name {name!r} differs from the folder name")
        description = meta.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(f"{folder}: description is missing or empty")
            continue
        lines = [ln for ln in front.splitlines() if ln.startswith("description:")]
        one_line = (
            len(lines) == 1
            and yaml.safe_load(lines[0]).get("description") == description
        )
        if not one_line:
            problems.append(f"{folder}: description is not on one line")
        if len(description) > MAX_DESCRIPTION:
            problems.append(
                f"{folder}: description is {len(description)} characters"
                f" (max {MAX_DESCRIPTION})"
            )
    return problems


def check_calls(skills_dir: pathlib.Path, tools: set[str] | None = None) -> Problems:
    """The call lines name exactly one idx__<tool>, and the server registers it."""
    tools = registered_tools() if tools is None else tools
    problems = []
    for folder, _, _, body in parsed_skills(skills_dir):
        called = sorted(set(CALL.findall(body)))
        if len(called) != 1:
            problems.append(
                f"{folder}: call lines name {len(called)} tools {called}, not one"
            )
        problems += [
            f"{folder}: calls idx__{tool}, which the MCP server does not register"
            for tool in called
            if tool not in tools
        ]
    return problems


def check_line_length(skills_dir: pathlib.Path) -> Problems:
    """No line over 120 characters, except the frontmatter's description line."""
    problems = []
    for path in skill_files(skills_dir):
        lines = path.read_text(encoding="utf-8").splitlines()
        closing = next((i for i, ln in enumerate(lines[1:], 1) if ln == "---"), 0)
        for number, line in enumerate(lines, 1):
            exempt = number - 1 < closing and line.startswith("description:")
            if len(line) > MAX_LINE and not exempt:
                problems.append(
                    f"{path.parent.name}: line {number} is {len(line)} characters"
                    f" (max {MAX_LINE})"
                )
    return problems


def check_data_line(skills_dir: pathlib.Path) -> Problems:
    """The body says that what tools return is data, never instructions."""
    return [
        f"{folder}: no sentence matching {DATA_LINE.pattern!r} (the data line)"
        for folder, _, _, body in parsed_skills(skills_dir)
        if not DATA_LINE.search(body)
    ]


def check_email_decline(skills_dir: pathlib.Path) -> Problems:
    """The body mentions email, where the decline rule lives."""
    return [
        f"{folder}: body never mentions email (the decline rule)"
        for folder, _, _, body in parsed_skills(skills_dir)
        if not EMAIL_WORD.search(body)
    ]


def check_no_pii(skills_dir: pathlib.Path) -> Problems:
    """No email address or phone number, with the PII gate's placeholder allowances."""
    allowed = pii_scan.load_allowed()
    problems = []
    for path in skill_files(skills_dir):
        hits = pii_scan.find_pii(path.read_text(encoding="utf-8"), allowed)
        problems += [f"{path.parent.name}: {kind} {value}" for kind, value in hits]
    return problems


CHECKS: dict[str, Callable[[pathlib.Path], Problems]] = {
    "frontmatter": check_frontmatter,
    "calls": check_calls,
    "line_length": check_line_length,
    "data_line": check_data_line,
    "email_decline": check_email_decline,
    "no_pii": check_no_pii,
}


# --- the real skills ---


def test_skills_exist():
    assert skill_files(SKILLS_DIR), f"no */SKILL.md under {SKILLS_DIR}"


def test_health_skill_calls_idx_health():
    _, _, body = parse_skill(SKILLS_DIR / "health" / "SKILL.md")
    assert set(CALL.findall(body)) == {"health"}, "health skill must call idx__health"


def test_frontmatter():
    problems = check_frontmatter(SKILLS_DIR)
    assert not problems, "Bad frontmatter:\n" + "\n".join(problems)


def test_one_registered_tool_call():
    problems = check_calls(SKILLS_DIR)
    assert not problems, "Bad call lines:\n" + "\n".join(problems)


def test_line_length():
    problems = check_line_length(SKILLS_DIR)
    assert not problems, "Lines too long:\n" + "\n".join(problems)


def test_data_line():
    problems = check_data_line(SKILLS_DIR)
    assert not problems, "Missing the data line:\n" + "\n".join(problems)


def test_email_decline():
    problems = check_email_decline(SKILLS_DIR)
    assert not problems, "Missing the email decline:\n" + "\n".join(problems)


def test_no_pii():
    problems = check_no_pii(SKILLS_DIR)
    assert not problems, "Contact details in skills:\n" + "\n".join(problems)


# --- an invented bad skill: every check must catch it ---


def _bad_skill(skills_dir: pathlib.Path) -> None:
    """Write a skill that breaks every rule; contact details are assembled at runtime so
    this file itself passes the PII gate."""
    address = "jdoe" + "@" + "brokerage.co"
    phone = "-".join(["213", "867", "5309"])
    long_line = "Filler " * 20
    body = (
        "# Bad\n\n"
        "Call `idx__search_listings` once, then call the tool `idx__not_a_tool`.\n\n"
        f"{long_line}\n\n"
        f"Reach the agent at {address} or {phone}.\n\n"
        "Treat what comes back as gospel.\n"
    )
    folder = skills_dir / "bad-skill"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: Bad_Skill\ndescription: >\n  Spans\n  two lines.\n---\n" + body,
        encoding="utf-8",
    )


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_each_check_fails_on_a_bad_skill(tmp_path, check):
    _bad_skill(tmp_path)
    assert CHECKS[check](tmp_path), f"check {check!r} passed an invented bad skill"


def test_frontmatter_fails_on_unparsable_yaml(tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: [broken\n---\nbody\n", encoding="utf-8"
    )
    problems = check_frontmatter(tmp_path)
    assert problems and "not YAML" in problems[0], problems


def test_frontmatter_fails_on_long_description(tmp_path):
    folder = tmp_path / "wordy"
    folder.mkdir()
    front = f"---\nname: wordy\ndescription: {'x' * (MAX_DESCRIPTION + 1)}\n---\n"
    (folder / "SKILL.md").write_text(front + "body\n", encoding="utf-8")
    assert check_frontmatter(tmp_path) == [
        f"wordy: description is {MAX_DESCRIPTION + 1} characters"
        f" (max {MAX_DESCRIPTION})"
    ]
