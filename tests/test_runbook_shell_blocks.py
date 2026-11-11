"""Every bash and sh block of the WhatsApp install runbook survives bash and zsh -i."""

# macOS's default interactive zsh has INTERACTIVE_COMMENTS off, so a `# ...` after a
# command is passed to it as arguments, and a `;` inside such a comment ends the command
# (WO-041, third review: an R6 annotation ran `exit 0` and closed the terminal).
# Each block is fed, as the owner would paste it, to `zsh -f -i` and to `bash`, with
# every real command the runbook calls replaced on PATH by a stub that records its
# argument count and words. The test fails when a stub receives a word that starts with
# `#` (a comment that reached a command) or when the shell does not reach the end of
# the block. Synthetic only: a temporary HOME, no network, no real openclaw,
# cloudflared, python3 or curl.

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md"
FENCE = re.compile(r"^(\s*)```(\w*)\s*$")
# <OWNER_E164>, <id>, <RECORDED_IDS_WITHOUT_WHATSAPP...>: placeholders the owner types.
PLACEHOLDER = re.compile(r"<[A-Za-z0-9_.:/-]+(?:\.\.\.)?>")
STUBS = (
    "openclaw",
    "cloudflared",
    "python3",
    "curl",
    "launchctl",
    "crontab",
    "tailscale",
    "sudo",
    "editor",
)
DONE = "__BLOCK_SURVIVED__"
# Blocks the stubs cannot stand in for, by the first command line. None today; a block
# added here must say why.
SKIPPED: dict[str, str] = {}


def blocks():
    """(line number, language, dedented body) of every bash and sh block."""
    out, cur, start, indent, lang = [], None, 0, "", ""
    for n, line in enumerate(RUNBOOK.read_text(encoding="utf8").split("\n"), 1):
        m = FENCE.match(line)
        if m and cur is None:
            indent, lang, cur, start = m.group(1), m.group(2), [], n
        elif m and cur is not None:
            if lang in ("bash", "sh"):
                body = [x[len(indent) :] if x.startswith(indent) else x for x in cur]
                out.append((start, lang, "\n".join(body)))
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


BLOCKS = blocks()
SHELLS = [s for s in (["zsh", "-f", "-i"], ["bash"]) if shutil.which(s[0])]


def stub_dir(tmp_path):
    d = tmp_path / "stubs"
    d.mkdir()
    log = tmp_path / "argv.log"
    for name in STUBS:
        f = d / name
        body = (
            "#!/bin/sh\n"
            f'printf "%s\\t%s" "{name}" "$#" >> "{log}"\n'
            'for a in "$@"; do\n'
            f'  printf "\\t%s" "$(printf %s "$a" | tr "\\n\\t" "  ")" >> "{log}"\n'
            "done\n"
            f'printf "\\n" >> "{log}"\n'
        )
        if name == "sudo":
            body += 'exec "$@"\n'
        f.write_text(body, encoding="utf8")
        f.chmod(0o755)
    return d, log


def run_block(tmp_path, shell, body):
    stubs, log = stub_dir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    snap = home / "snap"
    snap.mkdir()
    (snap / "config-path.txt").write_text(f"{home}/openclaw.json\n", encoding="utf8")
    script = PLACEHOLDER.sub("PH", body) + f"\necho {DONE}\n"
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "HOME": str(home),
        "SNAP": str(snap),
        "EDITOR": str(stubs / "editor"),
        "START_CHECK": "2026-11-08T10:00:00",
        "SMOKE_START": "2026-11-08T10:00:00",
        "ROLLBACK_START": "2026-11-08T10:00:00",
        "TERM": "dumb",
    }
    out = subprocess.run(
        shell,
        input=script,
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
    )
    calls = []
    if log.exists():
        for line in log.read_text(encoding="utf8").splitlines():
            name, argc, *argv = line.split("\t")
            calls.append((name, int(argc), argv))
    return out, calls


def ids():
    return [f"line{n}-{lang}" for n, lang, _ in BLOCKS]


def test_every_block_is_found_and_none_is_skipped_silently():
    assert len(BLOCKS) >= 30
    firsts = {b.strip().split("\n")[0] for _, _, b in BLOCKS}
    assert set(SKIPPED) <= firsts


@pytest.mark.parametrize("shell", SHELLS, ids=lambda s: " ".join(s))
@pytest.mark.parametrize("block", BLOCKS, ids=ids())
def test_block_runs_in_bash_and_interactive_zsh(tmp_path, shell, block):
    n, _lang, body = block
    first = body.strip().split("\n")[0]
    if first in SKIPPED:
        pytest.skip(SKIPPED[first])
    out, calls = run_block(tmp_path, shell, body)
    assert DONE in out.stdout, (
        f"block at line {n} did not reach its end: {out.stderr[-600:]}"
    )
    for name, argc, argv in calls:
        assert argc == len(argv)
        leaked = [a for a in argv if a.startswith("#")]
        assert not leaked, f"block at line {n}: {name} got comment words {leaked}"


def test_a_trailing_comment_is_caught_in_interactive_zsh(tmp_path):
    # The check itself: the pre-fix R6 line hands `#` and the comment to openclaw, and
    # its `; exit 0` ends the shell before the end of the block.
    if not shutil.which("zsh"):
        pytest.skip("zsh not installed")
    bad = 'openclaw plugins enable whatsapp   # unset or contains "whatsapp"; exit 0'
    out, calls = run_block(tmp_path, ["zsh", "-f", "-i"], bad)
    assert DONE not in out.stdout
    assert any(a.startswith("#") for _, _, argv in calls for a in argv)


def test_bash_is_named_as_the_shell_at_the_top_and_in_each_section():
    text = RUNBOOK.read_text(encoding="utf8")
    assert "**Shell: run every block of this runbook in bash.**" in text
    for head in ("## 2. Backup", "## 3. Install", "## 4. Rollback", "## 7. Cloud API"):
        section = text[text.index(head) :][:600]
        assert "Run in bash" in section or "Run every block in bash" in section, head


def test_stubs_are_found_before_any_real_command(tmp_path):
    stubs, _ = stub_dir(tmp_path)
    for name in ("openclaw", "cloudflared", "python3", "curl"):
        assert (stubs / name).exists()
    assert os.access(stubs / "openclaw", os.X_OK)
