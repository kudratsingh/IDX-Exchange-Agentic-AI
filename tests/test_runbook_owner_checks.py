"""Run the owner's runbook checks (3.7, 7.5 and 7.6) verbatim against fixture logs."""

# The two shell blocks are taken from the runbook between their markers and run as
# written, with `openclaw` and `curl` replaced on PATH by fakes that print a fixture log
# (or fail) and a fixed curl result. Each case changes one thing from a passing record
# and shows the verdict the owner would see. Synthetic values only (555 numbers, made-up
# ids); no gateway, no network.

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/runbooks/WHATSAPP_CHANNEL_INSTALL.md"

START = "2026-11-08T10:00:00"
WA = "15555550101"
PNID = "1000000000555"
HOOK = "/test-seg/whatsapp"
LEAK_RE = f"{WA}|{PNID}|{HOOK}|wamid\\.|agent:|are you there|three-bedroom"
SHELLS = [s for s in ("sh", "bash", "zsh", "dash") if shutil.which(s)]
CLEAN = ["leaks: clean", "failures: clean"]
NOT_CHECKED = ["leaks: not checked", "failures: not checked"]
CONFIRMED = ["rollback confirmed: listener-stopped logged and the port is closed"]


def ev(component, **fields):
    """A plugin line's message as the host prints it: `plugins {"component":...}`."""
    body = {"component": f"idx-whatsapp-channel.{component}", **fields}
    return "plugins " + json.dumps(body, separators=(",", ":"))


INBOUND = ev("cloud-api", event="webhook-accepted", delivered=1, ignored=0)
STATUS = ev("cloud-api", event="webhook-accepted", delivered=0, ignored=1)
SENT = ev("outbound", outcome="sent", rule="card", hasRecord=True, textLength=807)
SAFE = ev("outbound", outcome="safe-text", reason="unknown-token", textLength=51)
BUSY = ev("outbound", outcome="busy", hasRecord=False, textLength=40)


def listener(event):
    return ev("cloud-api-listener", event=event)


def line(t, msg, level="info"):
    """One `openclaw logs --plain` line at local time `t` (to the second)."""
    return f"{t}.250-08:00 {level} {msg}"


def at(minute, second=0):
    return f"2026-11-08T10:{minute:02d}:{second:02d}"


EARLY = "2026-11-08T09:59:30"


def block(name):
    """The shell block between the runbook's markers for `name`."""
    text = RUNBOOK.read_text(encoding="utf8")
    begin = text.index(f"<!-- owner-check:{name}:begin -->")
    body = text[begin : text.index(f"<!-- owner-check:{name}:end -->")]
    return body[body.index("```sh\n") + len("```sh\n") : body.rindex("```")]


def smoke_log():
    """A log whose part after START is a passing five-message smoke test."""
    first_form = 'plugins {"subsystem":"plugins"} ' + listener("listener-started")[8:]
    return [
        line("2026-11-08T09:59:00", "gateway/ws hello-ok"),
        line(EARLY, first_form),
        line(EARLY, listener("listener-started")),
        line(EARLY, STATUS),
        line(at(0, 5), INBOUND),
        line(at(0, 9), SENT.replace('"card"', '"no-figures"')),
        line(at(1), INBOUND),
        line(at(1, 20), SENT),
        line(at(2), INBOUND),
        line(at(2, 30), SENT),
        line(at(3), INBOUND),
        line(at(3, 1), INBOUND),
        line(at(3, 2), BUSY),
        line(at(3, 40), SAFE),
        line(at(3, 50), STATUS),
    ]


def run(tmp_path, shell, name, log_lines, env, log_exit=0, curl=("000", 7)):
    """Run block `name` with the fakes; return its stdout lines."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fixture = tmp_path / "fixture.log"
    fixture.write_text("".join(x + "\n" for x in log_lines), encoding="utf8")
    fake_oc = bin_dir / "openclaw"
    fake_oc.write_text(
        "#!/bin/sh\n"
        '[ "$1" = logs ] || exit 64\n'
        f'[ "{log_exit}" = 0 ] || {{ echo "invalid params" >&2; exit {log_exit}; }}\n'
        f'cat "{fixture}"\n',
        encoding="utf8",
    )
    fake_curl = bin_dir / "curl"
    # Acts as if a proxy were set: unless told to skip ~/.curlrc (-q, first) and
    # every proxy (--noproxy '*'), the "proxy" answers 200 for any URL.
    fake_curl.write_text(
        "#!/bin/sh\n"
        '[ "$1" = -q ] && [ "$2" = --noproxy ] && [ "$3" = "*" ]'
        " || { printf 200; exit 0; }\n"
        f"printf '{curl[0]}'\nexit {curl[1]}\n"
    )
    for f in (fake_oc, fake_curl):
        f.chmod(0o755)
    path = f"{bin_dir}:{os.environ['PATH']}"
    out = subprocess.run(
        [shell, "-c", block(name)],
        env={"PATH": path, "HOME": str(tmp_path), **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()


SMOKE_ENV = {
    "SMOKE_START": START,
    "SMOKE_LEAK_RE": LEAK_RE,
    "SMOKE_EXPECT_IN": "5",
    "SMOKE_EXPECT_REPLY": "4",
    "SMOKE_EXPECT_BUSY": "1",
}


def smoke(tmp_path, shell, log, env=None, **kw):
    env = SMOKE_ENV if env is None else env
    return run(tmp_path, shell, "smoke-log", log, env, **kw)


@pytest.mark.parametrize("shell", SHELLS)
def test_smoke_check_passes_only_a_complete_clean_test(tmp_path, shell):
    assert smoke(tmp_path, shell, smoke_log()) == CLEAN


@pytest.mark.parametrize("shell", SHELLS)
def test_smoke_check_never_prints_clean_without_a_good_read(tmp_path, shell):
    failed = smoke(tmp_path, shell, smoke_log(), log_exit=1)
    assert "REVIEW: the log read failed" in failed
    assert failed[-2:] == NOT_CHECKED
    reach = "REVIEW: the read does not reach back to SMOKE_START"
    empty = smoke(tmp_path, shell, [])
    assert reach in empty
    assert empty[-2:] == NOT_CHECKED
    cut = [x for x in smoke_log() if x[:19] >= START]
    assert smoke(tmp_path, shell, cut) == [reach, *NOT_CHECKED]
    for var in ("SMOKE_START", "SMOKE_LEAK_RE"):
        env = {k: v for k, v in SMOKE_ENV.items() if k != var}
        assert f"REVIEW: {var} is not set" in smoke(tmp_path, shell, smoke_log(), env)


@pytest.mark.parametrize("shell", SHELLS)
def test_smoke_check_requires_exactly_the_expected_events(tmp_path, shell):
    log = smoke_log()
    no_reply = [x for x in log if not x.startswith(at(3, 40))]
    assert smoke(tmp_path, shell, no_reply) == [
        "REVIEW: replies: 3, expected 4",
        *NOT_CHECKED,
    ]
    two_busy = smoke(tmp_path, shell, [*log, line(at(4), BUSY)])
    assert "REVIEW: busy replies: 2, expected 1" in two_busy
    extra_in = smoke(tmp_path, shell, [*log, line(at(4), INBOUND)])
    assert "REVIEW: inbound messages: 6, expected 5" in extra_in
    # Events before SMOKE_START do not count; the duplicate first-line form counts once.
    early = [line("2026-11-08T09:59:50", INBOUND), *log]
    assert smoke(tmp_path, shell, early) == CLEAN
    # M4 and M5 batched by Meta into one delivery still count as two inbound messages.
    two = ev("cloud-api", event="webhook-accepted", delivered=2, ignored=0)
    batched = [x for x in log if x[:19] not in (at(3), at(3, 1))]
    batched.insert(10, line(at(3), two))
    assert smoke(tmp_path, shell, batched) == CLEAN
    unset = {k: v for k, v in SMOKE_ENV.items() if k != "SMOKE_EXPECT_BUSY"}
    out = smoke(tmp_path, shell, log, unset)
    assert "REVIEW: busy replies: 1, expected ?" in out


@pytest.mark.parametrize("shell", SHELLS)
def test_smoke_check_flags_leaks_failures_and_a_broken_pattern(tmp_path, shell):
    log = smoke_log()
    leaks = (WA, PNID, HOOK, "wamid.HBgL", "agent:main:whatsapp", "Are you there?")
    for leak in (*leaks, "Three-Bedroom"):
        leaky = [*log, line(at(3, 55), ev("x", v=leak))]
        assert smoke(tmp_path, shell, leaky) == ["leaks: REVIEW: abort", CLEAN[1]], leak
    bad_events = [
        ev("cloud-api", event="send-failed", reason="api-error"),
        ev("outbound", outcome="not_sent", reason="untrusted-turn"),
        ev("ingress", event="inbound-dropped", reason="sender-not-allowed"),
        ev("cloud-api", event="webhook-rejected", reason="bad-signature"),
        ev("entry", event="cloud-api-refused", reason="bad-config"),
        ev("cloud-api", event="inbound-handler-error", reason="rejected"),
        ev("cloud-api", event="inbound-handler-error", reason="threw"),
        ev("cloud-api", event="webhook-error", reason="handler"),
        ev("entry", event="credentials-changed"),
    ]
    for bad in bad_events:
        failing = [*log, line(at(3, 55), bad, "info")]
        assert smoke(tmp_path, shell, failing) == [CLEAN[0], "failures: REVIEW: abort"]
    # Any plugin line at warn or error fails, named or not (dispatch-error is error).
    for level, bad in (
        ("error", ev("ingress", event="dispatch-error")),
        ("warn", ev("x")),
    ):
        failing = [*log, line(at(3, 55), bad, level)]
        assert smoke(tmp_path, shell, failing) == [CLEAN[0], "failures: REVIEW: abort"]
    out = smoke(tmp_path, shell, log, {**SMOKE_ENV, "SMOKE_LEAK_RE": "a("})
    assert out[0].startswith("leaks: REVIEW: the pattern did not run")


ROLLBACK_ENV = {"ROLLBACK_START": START, "OWNER_LISTEN_URL": "http://127.0.0.1:18789/"}


def rollback_log(stopped=True, restarted=False):
    log = [
        line("2026-11-08T09:59:00", "gateway/ws hello-ok"),
        line(EARLY, listener("listener-started")),
        line(at(0, 1), "Updated plugins.entries.idx-whatsapp-channel.config.cloudApi."),
    ]
    if stopped:
        log.append(line(at(0, 2), listener("listener-stopped")))
    if restarted:
        log.append(line(at(0, 20), listener("listener-started")))
    return log


def roll(tmp_path, shell, log, env=None, **kw):
    env = ROLLBACK_ENV if env is None else env
    return run(tmp_path, shell, "rollback", log, env, **kw)


@pytest.mark.parametrize("shell", SHELLS)
def test_rollback_confirmed_only_by_listener_stopped_and_a_closed_port(tmp_path, shell):
    assert roll(tmp_path, shell, rollback_log()) == CONFIRMED
    assert roll(tmp_path, shell, rollback_log(stopped=False)) == [
        "NOT CONFIRMED: no listener-stopped since ROLLBACK_START"
    ]
    assert roll(tmp_path, shell, rollback_log(restarted=True)) == [
        "NOT CONFIRMED: the listener started again after it stopped"
    ]
    # Stopped, started, stopped again: the last event decides.
    again = [
        *rollback_log(restarted=True),
        line(at(0, 30), listener("listener-stopped")),
    ]
    assert roll(tmp_path, shell, again) == CONFIRMED
    # The one-off first-line form counts as the event too.
    form = 'plugins {"subsystem":"plugins"} ' + listener("listener-stopped")[8:]
    assert (
        roll(tmp_path, shell, [*rollback_log(stopped=False), line(at(0, 2), form)])
        == CONFIRMED
    )
    port = "NOT CONFIRMED: the listener's port did not refuse"
    for curl in (("404", 0), ("000", 28)):
        out = roll(tmp_path, shell, rollback_log(), curl=curl)
        assert out == [f"{port} (curl exit {curl[1]}, HTTP code {curl[0]})"]
    failed = roll(tmp_path, shell, rollback_log(), log_exit=1)
    assert "NOT CONFIRMED: the log read failed" in failed
    assert CONFIRMED[0] not in failed
    early = [line("2026-11-08T09:59:00", "x")]
    early.append(line(EARLY, listener("listener-stopped")))
    assert roll(tmp_path, shell, early) == [
        "NOT CONFIRMED: no listener-stopped since ROLLBACK_START"
    ]
    for var in ROLLBACK_ENV:
        env = {k: v for k, v in ROLLBACK_ENV.items() if k != var}
        out = roll(tmp_path, shell, rollback_log(), env)
        assert f"NOT CONFIRMED: {var} is not set" in out


# 3.7 auto-enable check (WO-041). The host logs its in-memory auto-enable as a header
# line and one untimed "- <change>" line per change; the real 2026.9.5 output, as
# `openclaw logs --plain --local-time` printed it in the harness, is reproduced here.
AE_HEADER = (
    "gateway gateway: auto-enabled plugins for this runtime without writing config:"
)
AE_STOCK = "- whatsapp plugin config present, added to plugin allowlist."
AE_CLEAN = ["auto-enable: clean"]


def ae_log(*after):
    return [
        line("2026-11-08T09:59:00", "state-migrations Auto-migrated legacy state:"),
        "- Migrated plugins.bundledDiscovery",
        line(EARLY, AE_HEADER),
        AE_STOCK,
        line(at(0, 1), "gateway starting HTTP server..."),
        *after,
    ]


def ae(tmp_path, shell, log, env=None, **kw):
    env = {"START_CHECK": START} if env is None else env
    return run(tmp_path, shell, "auto-enable", log, env, **kw)


@pytest.mark.parametrize("shell", SHELLS)
def test_auto_enable_check_flags_a_whatsapp_change_after_the_start(tmp_path, shell):
    # A change line before START_CHECK (an earlier start) is not counted.
    assert ae(tmp_path, shell, ae_log()) == AE_CLEAN
    flagged = ae(tmp_path, shell, ae_log(line(at(0, 5), AE_HEADER), AE_STOCK))
    assert flagged == [f"auto-enable: REVIEW: {AE_STOCK}"]
    # The channel-configured form names the channel by its label.
    label = "- WhatsApp configured, enabled automatically."
    assert ae(tmp_path, shell, ae_log(line(at(0, 5), AE_HEADER), label)) == [
        f"auto-enable: REVIEW: {label}"
    ]
    # A change that names another plugin, and a "- whatsapp" line under another message.
    other = ae_log(
        line(at(0, 5), AE_HEADER),
        "- openai auth configured, enabled automatically.",
        line(at(0, 6), "plugins loaded 14 plugin(s)"),
        AE_STOCK,
    )
    assert ae(tmp_path, shell, other) == AE_CLEAN


@pytest.mark.parametrize("shell", SHELLS)
def test_auto_enable_check_never_prints_clean_without_a_good_read(tmp_path, shell):
    failed = ae(tmp_path, shell, ae_log(), log_exit=1)
    assert failed == [
        "auto-enable: REVIEW: the log read failed",
        "auto-enable: REVIEW: the read does not reach back to START_CHECK",
        "auto-enable: not checked",
    ]
    late = [line(at(0, 1), "x"), line(at(0, 5), AE_HEADER), AE_STOCK]
    assert ae(tmp_path, shell, late) == [
        "auto-enable: REVIEW: the read does not reach back to START_CHECK",
        "auto-enable: not checked",
    ]
    assert ae(tmp_path, shell, ae_log(), env={}) == [
        "auto-enable: REVIEW: START_CHECK is not set",
        "auto-enable: REVIEW: the read does not reach back to START_CHECK",
        "auto-enable: not checked",
    ]
