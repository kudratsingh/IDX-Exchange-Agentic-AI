"""docs/DEMO_RUNBOOK.md shows the commands the code and install.sh give, byte for byte.

Pins the tool server's mint line to `consent.mint_command`, every command
`scripts/install.sh` prints as manual follow-up, and the preflight line.
"""

from __future__ import annotations

import re
from pathlib import Path

from idx_agent.safety import consent

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "DEMO_RUNBOOK.md"
INSTALL = ROOT / "scripts" / "install.sh"
PREFLIGHT_LINE = "python scripts/demo_preflight.py --minutes 60"


def printed_follow_up_commands() -> list[str]:
    """The `openclaw ...` and `scripts/...` commands install.sh prints, comments cut."""
    text = INSTALL.read_text("utf-8")
    heredoc = re.search(r"cat <<'EOF'\n(.*?)\nEOF\n", text, re.S)
    assert heredoc is not None, "install.sh no longer prints its follow-up heredoc"
    lines = heredoc.group(1).splitlines()
    lines += re.findall(r'^\s*echo "(.*)"\s*$', text, re.M)
    commands: list[str] = []
    for line in lines:
        command = line.split("#", 1)[0].strip()
        # A line with a shell expansion is a status line (the version banner).
        if command.startswith(("openclaw ", "scripts/")) and "$" not in command:
            commands.append(command)
    return commands


def test_the_runbook_shows_the_server_mint_line() -> None:
    line = consent.mint_command(consent.SERVER_ARGV, 5, 60)
    assert line == (
        '! scripts/guards/consent.sh paid 60 --command "python -m '
        'idx_agent.mcp_server.server" --max-calls 5'
    )
    assert line in RUNBOOK.read_text("utf-8")


def test_the_parse_finds_the_install_follow_up() -> None:
    commands = printed_follow_up_commands()
    for expected in (
        "openclaw mcp doctor idx --probe",
        "openclaw skills list",
        "openclaw gateway restart",
        "scripts/jaeger-local.sh",
    ):
        assert expected in commands
    assert len(commands) >= 10


def test_every_printed_follow_up_command_is_in_the_runbook() -> None:
    runbook = RUNBOOK.read_text("utf-8")
    missing = [c for c in printed_follow_up_commands() if c not in runbook]
    assert missing == []


def test_the_runbook_shows_the_preflight_line() -> None:
    runbook = RUNBOOK.read_text("utf-8")
    assert PREFLIGHT_LINE in runbook
    assert f"{PREFLIGHT_LINE} --openclaw" in runbook
