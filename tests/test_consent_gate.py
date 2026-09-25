"""Tests for the one paid check in our code, safety/consent.py (paid gate v2).

One token, one run: a `paid` token names one command line and a call ceiling, is
spent when the run starts, and never covers a second invocation. Tokens are minted in
conftest's temp consent dir with the reader's own `grant`; `run_as` sets the argv."""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.paid_token import grant_paid, run_as, token_state

from idx_agent.mcp_server import server
from idx_agent.safety import consent
from idx_agent.semantic.embedder import OpenAIEmbedder, ProviderError

RUN = ["python", "-m", "evals.run", "--suite", "local", "--allow-paid"]
SERVER = " ".join(consent.SERVER_ARGV)
SPIKE = Path(__file__).resolve().parents[1] / "scripts" / "semantic_spike.py"
SPIKE_ARGV = ["python", "scripts/semantic_spike.py", "--judge-sheet"]


def start(argv: list[str] | tuple[str, ...] = tuple(RUN)) -> consent.PaidBudget:
    """Start a paid run as a process whose command line is `argv`."""
    run_as(argv)
    return consent.start_paid_run()


# --- start and spend ---


def test_start_spends_the_token_and_sets_the_budget() -> None:
    grant_paid(RUN, max_calls=3)
    assert token_state() == "valid"
    budget = start()
    assert consent.active_budget() is budget
    assert (budget.command, budget.max_calls, budget.calls_made) == (
        " ".join(RUN),
        3,
        0,
    )
    assert len(budget.run_id) >= 8 and budget.expiry > time.time()
    assert token_state() == "consumed"


def test_spend_counts_up_to_the_ceiling_then_refuses_over_budget() -> None:
    grant_paid(RUN, max_calls=3)
    budget = start()
    consent.spend_paid_call()
    consent.spend_paid_call(2)
    assert budget.calls_made == 3 and budget.remaining == 0
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "over_budget"
    assert budget.calls_made == 3 and budget.aborted == "over_budget"


def test_a_spend_that_would_pass_the_ceiling_is_refused_whole() -> None:
    grant_paid(RUN, max_calls=2)
    budget = start()
    consent.spend_paid_call()
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call(2)
    assert info.value.reason == "over_budget" and budget.calls_made == 1


def test_no_run_started_means_no_budget() -> None:
    grant_paid(RUN, max_calls=5)
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "no_budget"
    # Spending never mints or consumes: the token is still unspent.
    assert token_state() == "valid" and consent.active_budget() is None


def test_a_second_invocation_on_a_spent_token_is_refused() -> None:
    grant_paid(RUN, max_calls=10)
    start()
    # The same command again, in this process or a fresh one, finds it spent.
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.start_paid_run()
    assert info.value.reason == "consumed"
    consent.reset_for_tests()
    with pytest.raises(consent.PaidRunRefused) as info:
        start()
    assert info.value.reason == "consumed"
    with pytest.raises(consent.PaidRunRefused):
        consent.spend_paid_call()


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "evals.run", "--suite", "local"],
        [*RUN, "--category", "routing"],
        ["python", "-c", "import evals.run"],
        ["python", "-m", "idx_agent.semantic.build_index", "--allow-paid"],
    ],
)
def test_any_other_command_line_is_refused_and_leaves_the_token(argv) -> None:
    grant_paid(RUN, max_calls=10)
    with pytest.raises(consent.PaidRunRefused) as info:
        start(argv)
    assert info.value.reason == "command_mismatch"
    assert token_state() == "valid" and consent.active_budget() is None


def test_the_check_reads_the_observed_argv_never_a_callers() -> None:
    # No caller can name the command: start_paid_run takes no argument, and the
    # process's own command line (here pytest's) does not match the token.
    grant_paid(RUN, max_calls=10)
    with pytest.raises(TypeError):
        consent.start_paid_run(RUN)  # type: ignore[call-arg]
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.start_paid_run()
    assert info.value.reason == "command_mismatch" and token_state() == "valid"


def test_no_token_an_old_token_or_an_expired_one_never_starts_a_run(
    paid_consent_dir: Path,
) -> None:
    with pytest.raises(consent.PaidRunRefused) as info:
        start()
    assert info.value.reason == "missing"
    # The old one-line format: an expiry and nothing else.
    token = paid_consent_dir / "paid"
    token.write_text(f"{time.time() + 600:.0f}\n", encoding="utf-8")
    with pytest.raises(consent.PaidRunRefused) as info:
        start()
    assert info.value.reason == "malformed"
    grant_paid(RUN, max_calls=3, minutes=15, now=time.time() - 3600)
    with pytest.raises(consent.PaidRunRefused) as info:
        start()
    assert info.value.reason == "expired"


def test_the_budget_ends_with_the_token_window() -> None:
    grant_paid(RUN, max_calls=5)
    budget = start()
    budget.expiry = time.time() - 1
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "expired"


def test_an_aborted_run_allows_no_further_call() -> None:
    grant_paid(RUN, max_calls=5)
    budget = start()
    consent.spend_paid_call()
    consent.abort_paid_run("http_400")
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "aborted"
    assert budget.aborted == "http_400" and budget.calls_made == 1


def test_a_failed_embedding_request_aborts_the_run() -> None:
    grant_paid(RUN, max_calls=5)
    budget = start()
    calls: list[int] = []

    def create(**kwargs):
        calls.append(1)
        raise RuntimeError("provider said no")

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    embedder = OpenAIEmbedder(client=client, environ={"OPENAI_API_KEY": "test-only"})
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert info.value.reason == "failed"
    assert budget.aborted is not None and budget.calls_made == 1
    # Nothing is resent: the next request is refused before the client is called.
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert (info.value.reason, info.value.refusal) == ("no_consent", "aborted")
    assert len(calls) == 1


# --- the command line: one normalization, the reader's ---


def test_the_argv_is_normalized_by_the_imported_reader() -> None:
    grant_paid("python -m evals.run --suite local --allow-paid", max_calls=1)
    typed = [
        "PYTHONPATH=src",
        "MYSQL_HOST=",
        "/somewhere/.venv/bin/python3.11",
        "-m",
        "evals.run",
        "--suite",
        "local",
        "--allow-paid",
    ]
    assert consent.reader().command_matches(" ".join(RUN), typed)
    assert consent.display_command(typed) == " ".join(RUN)
    assert start(typed).max_calls == 1


def test_the_mint_command_names_the_normalized_argv_and_the_ceiling() -> None:
    typed = ["/x/.venv/bin/python", "-m", "evals.run", "--suite", "local"]
    assert consent.mint_command(typed, 92) == (
        '! scripts/guards/consent.sh paid 30 --command "python -m evals.run --suite '
        'local" --max-calls 92'
    )
    odd = consent.mint_command(["python", "-m", "evals.run", "--case", 'a"b$c'], 1)
    assert '--command "python -m evals.run --case a\\"b\\$c" --max-calls 1' in odd


def test_a_reader_without_the_v2_names_refuses_every_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / "old_reader.py"
    old.write_text("def is_valid(kind, now=None):\n    return True\n", encoding="utf-8")
    monkeypatch.setattr(consent, "_reader", None)
    monkeypatch.setattr(consent, "_reader_path", lambda: old)
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.start_paid_run()
    assert info.value.reason == "reader_outdated"


# --- where the token lives ---


def test_production_pins_the_consent_dir_to_the_readers_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Env vars and the working directory never move the dir the code reads; it is
    `<checkout owning the reader>/.local/consent`, as the commit gate resolves it.
    Paths are only computed here: nothing is read or written there."""
    for name in ("IDX_CONSENT_DIR", "CLAUDE_PROJECT_DIR", "IDX_PROJECT_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.chdir(tmp_path)
    path = consent._reader_path()
    module = consent._load_reader(path)
    owner = consent._git_root(path.parent) or path.resolve().parents[2]
    assert module.consent_dir() == owner / ".local" / "consent"
    assert module.consent_dir(ignore_env=False) == owner / ".local" / "consent"
    assert module.token_path("paid").parent == owner / ".local" / "consent"
    assert tmp_path not in module.token_path("paid").parents


def test_every_test_reads_a_temp_consent_dir(paid_consent_dir: Path) -> None:
    assert consent.reader().consent_dir() == paid_consent_dir
    grant_paid(RUN, max_calls=1)
    assert (paid_consent_dir / "paid").is_file()


# --- the tool server: the lazy run ---


def test_lazy_mode_needs_the_server_command_line() -> None:
    run_as(["python", "-c", "from idx_agent.mcp_server import server"])
    assert consent.allow_lazy_server_run() is False
    grant_paid(SERVER, max_calls=5)
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "no_budget" and token_state() == "valid"
    run_as(["/x/.venv/bin/python3", "-m", "idx_agent.mcp_server.server"])
    assert consent.allow_lazy_server_run() is True


def test_server_main_turns_on_lazy_mode_only_as_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.server, "run", lambda **kwargs: None)
    run_as(["python", "-m", "evals.run", "--suite", "local"])
    server.main()
    assert consent._lazy is False
    run_as(list(consent.SERVER_ARGV))
    server.main()
    assert consent._lazy is True


def test_the_server_spends_a_token_minted_for_its_command_lazily() -> None:
    run_as(list(consent.SERVER_ARGV))
    assert consent.allow_lazy_server_run()
    grant_paid(SERVER, max_calls=2)
    consent.spend_paid_call()
    budget = consent.active_budget()
    assert (
        budget is not None and budget.command == SERVER and token_state() == "consumed"
    )
    consent.spend_paid_call()
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "over_budget"
    # A new token for the server's command is picked up once the first is used up.
    grant_paid(SERVER, max_calls=1)
    consent.spend_paid_call()
    assert consent.active_budget() is not budget
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "over_budget"


def test_the_server_refuses_without_a_token_for_its_own_command() -> None:
    run_as(list(consent.SERVER_ARGV))
    consent.allow_lazy_server_run()
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "missing"
    grant_paid(RUN, max_calls=5)
    with pytest.raises(consent.PaidRunRefused) as info:
        consent.spend_paid_call()
    assert info.value.reason == "command_mismatch"
    assert token_state() == "valid"


def test_the_server_embedder_maps_a_refusal_to_no_consent() -> None:
    run_as(list(consent.SERVER_ARGV))
    consent.allow_lazy_server_run()
    embedder = OpenAIEmbedder(environ={"OPENAI_API_KEY": "test-only"})
    with pytest.raises(ProviderError) as info:
        embedder.embed(["a quiet home with a big yard"])
    assert (info.value.reason, info.value.refusal) == ("no_consent", "missing")
    assert embedder._client is None


def _spike(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, list[Any]]:
    """scripts/semantic_spike.py loaded by path, run as `python
    scripts/semantic_spike.py --judge-sheet` over two invented queries, a temp
    judging folder, and a fake connection (returned in the list once opened)."""
    spec = importlib.util.spec_from_file_location("spike_under_test", SPIKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    opened: list[Any] = []

    def connect() -> Any:
        opened.append(SimpleNamespace(closed=False))
        opened[-1].close = lambda: setattr(opened[-1], "closed", True)
        return opened[-1]

    queries = [{"query_id": f"q-{n}", "args": {"text": "a quiet home"}} for n in (1, 2)]
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(module, "JUDGING_DIR", tmp_path / "judging")
    monkeypatch.setattr(module, "ignored_by_git", lambda path: True)
    monkeypatch.setattr(module, "judged_queries", lambda: queries)
    monkeypatch.setattr(module, "connect", connect)
    run_as(SPIKE_ARGV)
    return module, opened


def test_the_judge_sheet_refuses_without_a_token_and_prints_the_mint_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    module, opened = _spike(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "similar_result", lambda raw: pytest.fail("a call"))
    assert module.judge_sheet_main() == 2 and opened == []
    printed = capsys.readouterr().out
    assert "(missing); one token covers one run" in printed
    command = " ".join(SPIKE_ARGV)
    assert f'consent.sh paid 30 --command "{command}" --max-calls 2' in printed


def test_the_judge_sheet_stops_on_a_failed_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    module, opened = _spike(monkeypatch, tmp_path)
    grant_paid(SPIKE_ARGV, max_calls=2)
    requests: list[Any] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        raise RuntimeError("stub provider failure")

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    embedder = OpenAIEmbedder(client=client, environ={"OPENAI_API_KEY": "test-only"})

    def similar(raw: Any) -> Any:
        # As the tool does: the provider failure becomes an error envelope.
        try:
            embedder.embed([raw["text"]])
        except ProviderError as exc:
            return server._similar_error("t", "provider", "x", repr(exc))
        raise AssertionError("the stub provider answered")

    monkeypatch.setattr(server, "similar_result", similar)
    assert module.judge_sheet_main() == 1
    assert len(requests) == 1 and opened[0].closed and token_state() == "consumed"
    printed = capsys.readouterr().out
    assert "q-1: run aborted" in printed and "q-2" not in printed
    assert not list((tmp_path / "judging").iterdir())


def test_the_tool_log_line_carries_the_run_id_under_a_paid_run(capsys) -> None:
    server._guarded("health", server.health_result)
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "run_id" not in line
    grant_paid(SERVER, max_calls=1)
    budget = start(list(consent.SERVER_ARGV))
    server._guarded("health", server.health_result)
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["run_id"] == budget.run_id
    for field in ("command", "max_calls", "expiry", "pid", "consumed"):
        assert field not in line
