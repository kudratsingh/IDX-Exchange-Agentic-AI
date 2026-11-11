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
# Real tools the blocks call: wrapped so their argv is recorded too, then the real
# binary runs (resolved on this machine's PATH when the wrappers are written).
WRAPPED = ("ls", "grep", "rm", "rmdir", "mv", "mkdir", "chmod", "sleep", "cat", "date")
DONE = "__BLOCK_SURVIVED__"
# Shell errors that mean a line did not run as written. A comment-only line is a command
# named `#` in interactive zsh (`command not found: #`): harmless, and not counted.
SHELL_ERROR = re.compile(
    r"parse error|no matches found|invalid mode|bad pattern|"
    r"command not found(?!: #$)",
    re.M,
)
# What a comment-only line in a block may not hold: characters zsh -i acts on, and a
# trailing backslash, which joins the next line into the comment.
COMMENT_BAD = re.compile(r"[&;|()\[\]*?<>'\"$!`]|\\$")
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
    real = {n: shutil.which(n, path="/bin:/usr/bin") for n in WRAPPED}
    for name in (*STUBS, *WRAPPED):
        f = d / name
        # One write per call, so calls from the two ends of a pipe do not interleave.
        body = (
            "#!/bin/sh\n"
            'TAB="$(printf "\\t")"\n'
            f'rec="{name}$TAB$#"\n'
            'for a in "$@"; do\n'
            '  rec="$rec$TAB$(printf %s "$a" | /usr/bin/tr "\\n\\t" "  ")"\n'
            "done\n"
            f'printf "%s\\n" "$rec" >> "{log}"\n'
        )
        if name == "sudo":
            body += 'exec "$@"\n'
        elif name in WRAPPED:
            body += f'exec "{real[name]}" "$@"\n'
        f.write_text(body, encoding="utf8")
        f.chmod(0o755)
    return d, log


def run_block(tmp_path, shell, body):
    stubs, log = stub_dir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    snap = home / "snap"
    snap.mkdir()
    # What section 2 leaves in $SNAP for later blocks: the config path and the archive.
    (snap / "config-path.txt").write_text(f"{home}/openclaw.json\n", encoding="utf8")
    (snap / "2026-11-08T10-00-00-openclaw-backup.tar.gz").write_bytes(b"")
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
    errors = SHELL_ERROR.findall(out.stderr)
    assert not errors, f"block at line {n}: {errors}: {out.stderr[-600:]}"
    for name, argc, argv in calls:
        assert argc == len(argv)
        leaked = [a for a in argv if a.startswith("#")]
        assert not leaked, f"block at line {n}: {name} got comment words {leaked}"


def comment_start(line):
    """Index of an unquoted `#` at the start of a word, or -1 (`$#`, `"#"` are not)."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote == "'":
            quote = None if c == "'" else quote
        elif quote == '"':
            if c == "\\":
                i += 1
            elif c == '"':
                quote = None
        elif c == "\\":
            i += 1
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            return i
        i += 1
    return -1


def lint(body):
    """The problems a block's comments would cause in interactive zsh."""
    found = []
    for k, line in enumerate(body.split("\n"), 1):
        pos = comment_start(line)
        if pos < 0:
            continue
        if line[:pos].strip():
            found.append((k, "comment after a command", line))
        elif COMMENT_BAD.search(line[pos:]):
            found.append((k, "comment line with a shell character", line))
    return found


@pytest.mark.parametrize("block", BLOCKS, ids=ids())
def test_no_block_carries_a_comment_zsh_would_act_on(block):
    n, _lang, body = block
    assert not lint(body), f"block at line {n}: {lint(body)}"


def test_the_lint_flags_each_known_breakage():
    bad = [
        "openclaw config validate   # must pass first",
        'ls "$SNAP"/*.err | while read -r f; do echo "$f"; done   # read .err',
        "# must pass (first)",
        "# must pass first \\",
        "# validate & check",
        "# never feed these to `config set`",
        '# prints "allowlist"',
        "# a; b",
    ]
    for line in bad:
        assert lint(line), line
    for line in (
        'printf "%s" "$#"',
        "# plain words, a colon: and 2026.9.5",
        "echo '#x'",
    ):
        assert not lint(line), line


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
    for name in ("openclaw", "cloudflared", "python3", "curl", *WRAPPED):
        assert (stubs / name).exists()
    assert os.access(stubs / "openclaw", os.X_OK)


def test_wrapped_tools_record_and_still_run(tmp_path):
    out, calls = run_block(tmp_path, ["bash"], "mkdir -p x\nls -d x\nsleep 0")
    assert "x" in out.stdout and DONE in out.stdout
    assert [c[0] for c in calls] == ["mkdir", "ls", "sleep"]
