"""The owner-only card store and the handle map (WO-036 prototype). tmp_path only."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

import pytest

from idx_agent.channels import card_delivery as cd
from idx_agent.channels import card_store as cs

ROOT = Path(__file__).resolve().parents[1]
BINDING = cd.DeliveryBinding(channel="wa", session="a" * 64, run="run-x", call="c-1")


def _record(message="card text", now_ms=1_000_000, ref=None):
    return cd.new_record(
        message,
        trace_id="trace-a",
        binding=BINDING,
        now_ms=now_ms,
        ttl_ms=300_000,
        ref=ref,
    )


@pytest.fixture
def store(tmp_path):
    return cs.CardStore(tmp_path / "idx-cards")


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_write_then_read_round_trips_with_owner_only_modes(store):
    record = _record("line one\nline two · ünïcode")
    path = store.write(record)
    assert path.name == cd.file_name(record.ref)
    assert record.ref not in path.name
    assert _mode(store.directory) == 0o700
    assert _mode(path) == 0o600
    assert store.read(record.ref) == record
    assert json.loads(path.read_bytes())["message"] == record.message


def test_unknown_ref_is_none(store):
    store.write(_record())
    assert store.read(cd.new_ref()) is None


def test_a_looser_directory_mode_is_repaired_on_write_and_refused_on_read(store):
    store.write(_record())
    os.chmod(store.directory, 0o755)
    record = _record("second")
    assert store.read(record.ref) is None
    store.write(record)
    assert _mode(store.directory) == 0o700
    assert store.read(record.ref) == record


def test_a_symlinked_directory_is_refused(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir(mode=0o700)
    (tmp_path / "idx-cards").symlink_to(real)
    store = cs.CardStore(tmp_path / "idx-cards")
    with pytest.raises(cs.CardStoreError, match="dir_unsafe"):
        store.write(_record())
    assert store.read(cd.new_ref()) is None


def test_a_symlinked_record_is_refused(store, tmp_path):
    record = _record()
    store.write(_record("other"))
    target = tmp_path / "planted.json"
    target.write_text(json.dumps(record.model_dump()))
    os.chmod(target, 0o600)
    (store.directory / cd.file_name(record.ref)).symlink_to(target)
    assert store.read(record.ref) is None


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_a_group_or_world_readable_record_is_refused(store, mode):
    record = _record()
    path = store.write(record)
    os.chmod(path, mode)
    assert store.read(record.ref) is None


def test_an_oversized_or_malformed_record_is_refused(store):
    record = _record()
    path = store.write(record)
    path.write_bytes(b"{" + b" " * cs.MAX_RECORD_BYTES + b"}")
    assert store.read(record.ref) is None
    path.write_text("not json")
    assert store.read(record.ref) is None
    path.write_text(json.dumps({**record.model_dump(), "extra": 1}))
    assert store.read(record.ref) is None
    other = _record("other")
    path.write_text(json.dumps(other.model_dump()))  # a record under the wrong name
    assert store.read(record.ref) is None


def test_a_record_over_the_size_cap_is_not_written(store):
    with pytest.raises(cs.CardStoreError, match="too_large"):
        store.write(_record("x" * cs.MAX_RECORD_BYTES))
    assert not store.directory.exists()


def test_a_full_store_refuses_instead_of_evicting(tmp_path):
    store = cs.CardStore(tmp_path / "idx-cards", max_files=2)
    first, second = _record("a"), _record("b")
    store.write(first)
    store.write(second)
    with pytest.raises(cs.CardStoreError, match="full"):
        store.write(_record("c"))
    assert store.read(first.ref) == first and store.read(second.ref) == second


def test_prune_removes_only_expired_own_files(tmp_path):
    now = [10_000.0]
    store = cs.CardStore(tmp_path / "idx-cards", clock=lambda: now[0])
    old = store.write(_record("old"))
    fresh = store.write(_record("fresh"))
    os.utime(old, (now[0] - 400, now[0] - 400))
    os.utime(fresh, (now[0] - 10, now[0] - 10))
    stale_temp = store.directory / f".card-{'0' * 64}.{'1' * 16}.tmp"
    stale_temp.write_text("x")
    os.utime(stale_temp, (now[0] - 120, now[0] - 120))
    foreign = store.directory / "notes.json"
    foreign.write_text("{}")
    os.utime(foreign, (now[0] - 9999, now[0] - 9999))
    assert store.prune() == 2
    assert not old.exists() and not stale_temp.exists()
    assert fresh.exists() and foreign.exists()


def test_the_store_needs_its_fixed_name():
    with pytest.raises(ValueError):
        cs.CardStore(Path("/tmp/cards"))


def test_card_dir_rules(tmp_path):
    def setting(value):
        return lambda name: value if name == cs.DIR_SETTING else None

    assert cs.card_dir(setting(None)) == Path(cs.DEFAULT_DIR).expanduser()
    assert cs.card_dir(setting(str(tmp_path / "idx-cards"))) == tmp_path / "idx-cards"
    assert cs.card_dir(setting("relative/idx-cards")) is None
    assert cs.card_dir(setting(str(tmp_path / "cards"))) is None
    assert cs.card_dir(setting(str(tmp_path / "a b" / "idx-cards"))) is None
    assert cs.card_dir(setting(str(tmp_path / ".." / "idx-cards"))) is None
    inside = Path(cs.WORKSPACE).expanduser() / "idx-cards"
    assert cs.card_dir(setting(str(inside))) is None
    assert cs.card_dir(setting(cs.WORKSPACE + "/sub/idx-cards")) is None


def test_card_dir_inside_the_workspace_through_a_symlink_is_refused(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace-idx"
    workspace.mkdir()
    (tmp_path / "link").symlink_to(workspace)
    monkeypatch.setattr(cs, "WORKSPACE", str(workspace))
    value = str(tmp_path / "link" / "idx-cards")
    assert cs.card_dir(lambda name: value) is None


def _config_workspace() -> tuple[str, str]:
    text = (ROOT / "config" / "openclaw.idx.json5").read_text()
    workspaces = set(re.findall(r'workspace:\s*"([^"]+)"', text))
    assert len(workspaces) == 1, workspaces
    only = re.search(r"fs:\s*\{\s*workspaceOnly:\s*(\w+)", text)
    assert only is not None
    return workspaces.pop(), only.group(1)


def test_the_default_store_is_outside_the_agent_workspace():
    """Critique fix: the model's `read` tool is limited to the workspace; the store
    must stay outside it, and the workspace limit must stay on."""
    workspace, workspace_only = _config_workspace()
    assert workspace == cs.WORKSPACE
    assert workspace_only == "true"
    default = Path(cs.DEFAULT_DIR).expanduser()
    assert not cs._inside(default, Path(workspace).expanduser())
    assert default.parent == Path(cs.STATE_DIR).expanduser()


def test_the_chart_store_workspace_constant_agrees():
    from idx_agent.analysis import delivery

    assert delivery.WORKSPACE == cs.WORKSPACE


def test_handles_round_trip_and_expire():
    now = [0.0]
    handles = cs.HandleMap(ttl=10, max_entries=3, clock=lambda: now[0])
    a = handles.issue(9190001)
    assert handles.issue(9190001) == a
    assert handles.resolve(a) == 9190001
    assert handles.resolve(5) is None
    assert handles.resolve(True) is None and handles.resolve("x") is None
    assert 10**8 <= a < 10**9
    now[0] = 11
    assert handles.resolve(a) is None


def test_handles_are_capped_oldest_first():
    handles = cs.HandleMap(max_entries=2)
    first = handles.issue(1)
    second = handles.issue(2)
    third = handles.issue(3)
    assert handles.resolve(first) is None
    assert handles.resolve(second) == 2 and handles.resolve(third) == 3
