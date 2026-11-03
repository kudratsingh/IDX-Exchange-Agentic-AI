"""Shared-feature explanations on `recommend` (WO-024): off by default, never reorder.

Reuses the WO-011 harness (hashing index, faked fetch and comps) with a real effective
store of invented statuses. Feature weights stay zero: order, scores, candidates and
price checks must be identical with explanations on and off."""

import json

import pytest
from tests.test_mcp_recommend import (  # noqa: F401 - shared fixtures
    SUBJECT,
    _recommend,
    fake_db,
    served,
)

from idx_agent.channels.format import SHARED_NOTE, SHARED_PREFIX
from idx_agent.db import listings as db_listings
from idx_agent.enrichment import access as fa
from idx_agent.enrichment import effective_store
from idx_agent.enrichment.source_check import EXPECTED_RESULTS_DIGEST
from idx_agent.mcp_server import server as mcp

WATERMARK = "2026-09-18 06:58:44"
META = {
    "source_watermark": WATERMARK,
    "policy_version": "v4",
    "rules_version": "2026-11-01.4",
    "results_digest": EXPECTED_RESULTS_DIGEST,
    "built_from": json.dumps({"overlay": "invented"}),
}
# Invented statuses. The subject has solar, pool, hardwood and near transit present,
# a planned ADU and an uncertain patio.
STATUSES = {
    SUBJECT: {
        "solar": "present",
        "pool": "present",
        "hardwood": "present",
        "near_transit_mentioned": "present",
        "adu": "planned",
        "patio": "uncertain",
    },
    # Shares solar and pool; its ADU is present but the subject's is only planned.
    9870002: {"solar": "present", "pool": "present", "adu": "present"},
    # Shares only an area facet (left out) and a hardwood stated absent.
    9870003: {"near_transit_mentioned": "present", "hardwood": "stated_absent"},
    # Shares hardwood; its pool is historical and its patio present (subject uncertain).
    9870004: {"hardwood": "present", "pool": "historical", "patio": "present"},
    # Contradictory solar and an uncertain pool: nothing shared.
    9870008: {"solar": "contradictory", "pool": "uncertain"},
    # 9870009 was never extracted: unknown everywhere.
}


def write(path, statuses=STATUSES):
    rows = [(str(k), v) for k, v in sorted(statuses.items())]
    effective_store.write_store(path, rows, dict(META, source_rows=len(rows)))
    return path


@pytest.fixture
def store(tmp_path, monkeypatch, fake_db):  # noqa: F811
    state = {"path": write(tmp_path / "effective.sqlite3"), "fresh": (1000, 0)}
    state["changed"] = set()
    monkeypatch.setattr(
        mcp.effective_store, "configured_store_path", lambda: state["path"]
    )
    monkeypatch.setattr(
        db_listings, "fetch_freshness", lambda watermark, conn: state["fresh"]
    )

    def changed(keys, watermark, conn):
        assert watermark == WATERMARK and len(keys) <= 50
        return {k for k in keys if k in state["changed"]}

    monkeypatch.setattr(db_listings, "fetch_changed_keys", changed)
    fa.reset_for_tests()
    yield state
    fa.reset_for_tests()


def on(monkeypatch):
    monkeypatch.setenv(mcp.EXPLANATIONS_SETTING, "1")


def ranking(result):
    """Everything about the recommendations except the explanation."""
    return [
        (
            r.listing.listing_key,
            r.score_total,
            r.score_components,
            r.comp_evidence.model_dump(),
            r.explanation,
        )
        for r in result.data.recommendations
    ]


def test_off_by_default_never_opens_the_store(store, monkeypatch):
    monkeypatch.delenv(mcp.EXPLANATIONS_SETTING, raising=False)

    def refuse(path):
        raise AssertionError("the store must not be opened")

    monkeypatch.setattr(mcp.effective_store, "open_store", refuse)
    result = _recommend(listing_key=SUBJECT)
    assert result.ok and result.data.shared_features is None
    assert "shared_features" not in mcp.recommend(listing_key=SUBJECT)["data"]
    assert SHARED_PREFIX not in result.message


@pytest.mark.parametrize("value", ["0", "true", " 1x", ""])
def test_anything_but_exactly_one_is_off(store, monkeypatch, value):
    monkeypatch.setenv(mcp.EXPLANATIONS_SETTING, value)
    assert _recommend(listing_key=SUBJECT).data.shared_features is None


def test_order_scores_and_price_checks_are_unchanged(store, monkeypatch, fake_db):  # noqa: F811
    off = _recommend(listing_key=SUBJECT)
    comps_off = list(fake_db["comps"])
    fake_db["comps"].clear()
    on(monkeypatch)
    with_features = _recommend(listing_key=SUBJECT)
    assert ranking(with_features) == ranking(off)
    assert fake_db["comps"] == comps_off
    assert with_features.data.subject_check == off.data.subject_check


def test_only_present_on_both_home_features_are_shown(store, monkeypatch):
    on(monkeypatch)
    shared = _recommend(listing_key=SUBJECT).data.shared_features
    assert shared is not None
    assert shared.features == {9870002: ["pool", "solar"], 9870004: ["hardwood"]}
    assert shared.snapshot_watermark == WATERMARK
    assert shared.limitation == fa.LIMITATION


def test_reply_adds_one_line_per_explained_card_and_one_note(store, monkeypatch):
    off = _recommend(listing_key=SUBJECT).message
    on(monkeypatch)
    message = _recommend(listing_key=SUBJECT).message
    assert message.count(SHARED_PREFIX) == 3  # two card lines and the note's quote
    assert f"{SHARED_PREFIX} pool, solar\nPrice check:" in message
    assert f"{SHARED_PREFIX} hardwood\nPrice check:" in message
    assert SHARED_NOTE.format(date="2026-09-18") in message
    assert message.count(fa.LIMITATION) == 1
    # Removing the added lines gives back the reply without explanations exactly.
    stripped = "\n".join(
        line for line in message.split("\n") if not line.startswith(SHARED_PREFIX)
    )
    note = f"\n\n{SHARED_NOTE.format(date='2026-09-18')} {fa.LIMITATION}"
    assert stripped.replace(note, "") == off


def test_no_shared_feature_leaves_the_reply_as_it_was(store, monkeypatch, tmp_path):
    off = _recommend(listing_key=SUBJECT)
    store["path"] = write(tmp_path / "bare.sqlite3", {SUBJECT: {"garage": "present"}})
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    assert result.data.shared_features is None and result.message == off.message


@pytest.mark.parametrize(
    "make",
    [
        lambda s, t: s.update(path=None),
        lambda s, t: s.update(path=t / "absent.sqlite3"),
        lambda s, t: s.update(fresh=(1000, 101)),
        lambda s, t: s.update(fresh=(0, 0)),
    ],
    ids=["unconfigured", "missing", "stale", "no_active"],
)
def test_unusable_or_stale_store_shows_nothing(store, monkeypatch, tmp_path, make):
    off = _recommend(listing_key=SUBJECT)
    make(store, tmp_path)
    fa.reset_for_tests()
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    assert result.ok and result.data.shared_features is None
    assert result.message == off.message
    assert ranking(result) == ranking(off)


def test_a_changed_subject_explains_nothing(store, monkeypatch):
    store["changed"] = {str(SUBJECT)}
    on(monkeypatch)
    assert _recommend(listing_key=SUBJECT).data.shared_features is None


def test_a_changed_candidate_loses_only_its_own_line(store, monkeypatch):
    store["changed"] = {"9870002"}
    on(monkeypatch)
    shared = _recommend(listing_key=SUBJECT).data.shared_features
    assert shared.features == {9870004: ["hardwood"]}


def test_a_failure_leaves_the_recommendations_as_they_were(store, monkeypatch):
    off = _recommend(listing_key=SUBJECT)

    def broken(keys, watermark, conn):
        raise OSError("down")

    monkeypatch.setattr(db_listings, "fetch_changed_keys", broken)
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    assert result.ok and result.data.shared_features is None
    assert result.message == off.message


def test_k_zero_never_opens_the_store(store, monkeypatch):
    on(monkeypatch)

    def refuse(path):
        raise AssertionError("no recommendations, no store")

    monkeypatch.setattr(mcp.effective_store, "open_store", refuse)
    result = _recommend(listing_key=SUBJECT, k=0)
    assert result.ok and result.data.shared_features is None


def test_the_store_is_closed_after_explaining(store, monkeypatch):
    closed = []
    real_open = effective_store.open_store

    def tracking(path):
        got = real_open(path)
        real_close = got.close
        got.close = lambda: closed.append(True) or real_close()
        return got

    monkeypatch.setattr(mcp.effective_store, "open_store", tracking)
    on(monkeypatch)
    assert _recommend(listing_key=SUBJECT).data.shared_features is not None
    assert closed == [True]


def test_area_facets_are_never_offered_as_a_shared_trait():
    assert mcp.EXPLANATION_FACETS.isdisjoint(fa.AREA_FACETS)
    assert "condominium" in mcp.EXPLANATION_FACETS  # owner decision pending
