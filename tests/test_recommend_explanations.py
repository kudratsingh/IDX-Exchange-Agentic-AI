"""Shared-feature explanations on `recommend` (WO-024): off by default, never reorder.

Reuses the WO-011 harness (hashing index, faked fetch and comps) with a real effective
store of invented statuses. Feature weights stay zero: order, scores, candidates and
price checks must be identical with explanations on and off."""

import json
import sqlite3

import pytest
from tests.test_mcp_recommend import (  # noqa: F401 - shared fixtures
    ASOF,
    SUBJECT,
    _recommend,
    fake_db,
    served,
)

from idx_agent.channels.format import (
    SHARED_NOTE,
    SHARED_PREFIX,
    format_recommendations,
)
from idx_agent.db import listings as db_listings
from idx_agent.domain.models import SharedFeatures
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


@pytest.mark.parametrize("value", ["0", "true", " 1x", "", " 1 ", "1\n", "01"])
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


def test_condominium_is_never_offered_as_a_shared_trait():
    """Owner decision 2026-11-03: subtype is already a hard filter, so a shared
    condominium status would only repeat the card."""
    assert "condominium" not in mcp.EXPLANATION_FACETS
    assert mcp.EXPLANATION_FACETS == (
        mcp.ELIGIBLE_FACETS - fa.AREA_FACETS - {"condominium"}
    )


def test_a_shared_condominium_status_gives_no_explanation_entry(
    store, monkeypatch, tmp_path
):
    statuses = {
        SUBJECT: {"condominium": "present", "solar": "present"},
        # Shares solar and condominium: only solar is explained.
        9870002: {"condominium": "present", "solar": "present"},
        # Shares only condominium: no entry at all.
        9870004: {"condominium": "present"},
    }
    off = _recommend(listing_key=SUBJECT)
    store["path"] = write(tmp_path / "condo.sqlite3", statuses)
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    assert result.data.shared_features.features == {9870002: ["solar"]}
    assert "condominium" not in result.message
    assert ranking(result) == ranking(off)


# --- Review additions: constraints, payload, rollback, formatting, log ---


def test_candidate_constraints_reach_the_sql_recheck_unchanged(
    store,
    monkeypatch,
    fake_db,  # noqa: F811
):
    """The same filters (city, subtype, price band) and keys reach the SQL re-check,
    and explaining adds no listing fetch of its own."""
    _recommend(listing_key=SUBJECT)
    fetch_off = list(fake_db["fetch"])
    fake_db["fetch"].clear()
    on(monkeypatch)
    assert _recommend(listing_key=SUBJECT).data.shared_features is not None
    assert fake_db["fetch"] == fetch_off
    ranked = [f for f, _ in fetch_off[1:]]
    assert ranked and all(f.city == "Pasadena" for f in ranked)
    assert all(f.min_price == 750_000 and f.max_price == 1_250_000 for f in ranked)


def test_never_extracted_and_unqualified_candidates_show_nothing(store, monkeypatch):
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    keys = [r.listing.listing_key for r in result.data.recommendations]
    assert {9870003, 9870008, 9870009} <= set(keys)  # area only, no present, never
    for key in (9870003, 9870008, 9870009):
        assert key not in result.data.shared_features.features
    cards = result.message.split("\n\n")
    for card in cards:
        if any(f"{k % 1000} Invented Way" in card for k in (9870003, 9870008, 9870009)):
            assert SHARED_PREFIX not in card


def test_a_never_extracted_subject_explains_nothing(store, monkeypatch, tmp_path):
    rest = {k: v for k, v in STATUSES.items() if k != SUBJECT}
    store["path"] = write(tmp_path / "nosubject.sqlite3", rest)
    on(monkeypatch)
    assert _recommend(listing_key=SUBJECT).data.shared_features is None


def test_a_store_with_repeated_rows_shows_nothing(store, monkeypatch):
    """A repeated (listing, facet) row could double or pick a status arbitrarily; the
    shared validation refuses such a store, so nothing is shown and order stands."""
    off = _recommend(listing_key=SUBJECT)
    db = sqlite3.connect(store["path"])
    db.executescript(
        "CREATE TABLE loose (listing_key TEXT NOT NULL, facet TEXT NOT NULL,"
        " status TEXT NOT NULL);"
        "INSERT INTO loose SELECT * FROM facets; DROP TABLE facets;"
        "ALTER TABLE loose RENAME TO facets;"
        f"INSERT INTO facets VALUES ('{SUBJECT}', 'solar', 'present');"
    )
    db.commit()
    db.close()
    fa.reset_for_tests()
    on(monkeypatch)
    result = _recommend(listing_key=SUBJECT)
    assert result.data.shared_features is None and result.message == off.message
    assert ranking(result) == ranking(off)


def test_shared_features_are_listed_once_each(store, monkeypatch):
    on(monkeypatch)
    shared = _recommend(listing_key=SUBJECT).data.shared_features
    for features in shared.features.values():
        assert len(features) == len(set(features)) and features == sorted(features)


def test_payload_shape_off_and_on(store, monkeypatch):
    monkeypatch.delenv(mcp.EXPLANATIONS_SETTING, raising=False)
    off = mcp.recommend(listing_key=SUBJECT)
    assert "shared_features" not in off["data"]
    on(monkeypatch)
    payload = mcp.recommend(listing_key=SUBJECT)
    shared = json.loads(json.dumps(payload))["data"]["shared_features"]
    assert set(shared) == {"features", "snapshot_watermark", "limitation"}
    assert shared["snapshot_watermark"] == WATERMARK
    assert shared["limitation"] == fa.LIMITATION
    assert {str(k): v for k, v in shared["features"].items()} == {
        "9870002": ["pool", "solar"],
        "9870004": ["hardwood"],
    }
    # Everything else in the payload is exactly the payload with explanations off.
    rest = {k: v for k, v in payload["data"].items() if k != "shared_features"}
    assert rest == off["data"]


def test_rollback_unsetting_the_switch_is_byte_identical_to_off(store, monkeypatch):
    monkeypatch.delenv(mcp.EXPLANATIONS_SETTING, raising=False)
    off = mcp.recommend(listing_key=SUBJECT)
    on(monkeypatch)
    assert "shared_features" in mcp.recommend(listing_key=SUBJECT)["data"]
    monkeypatch.delenv(mcp.EXPLANATIONS_SETTING)
    back = mcp.recommend(listing_key=SUBJECT)

    def untraced(value):
        """The envelope without its per-call trace id (the only thing that varies)."""
        if isinstance(value, dict):
            return {k: untraced(v) for k, v in value.items() if k != "trace_id"}
        if isinstance(value, list):
            return [untraced(v) for v in value]
        return value

    dumped = [json.dumps(untraced(x), sort_keys=True, default=str) for x in (off, back)]
    assert dumped[0].encode() == dumped[1].encode()
    log: dict = {}
    mcp.recommend_result({"listing_key": SUBJECT}, log_fields=log)
    assert not any(k.startswith("shared_") for k in log)


def test_formatting_without_an_explained_card_adds_nothing(store, monkeypatch):
    """A SharedFeatures naming no shown card adds no line and no note."""
    result = _recommend(listing_key=SUBJECT).data
    plain = format_recommendations(result, ASOF)
    stray = SharedFeatures(
        features={1: ["pool"]}, snapshot_watermark=WATERMARK, limitation=fa.LIMITATION
    )
    for shared in (stray, SharedFeatures(**dict(stray.model_dump(), features={}))):
        message = format_recommendations(
            result.model_copy(update={"shared_features": shared}), ASOF
        )
        assert message == plain
        assert SHARED_PREFIX not in message and fa.LIMITATION not in message


def test_the_log_line_counts_and_never_names_a_listing(store, monkeypatch, capsys):
    store["changed"] = {"9870002"}
    on(monkeypatch)
    capsys.readouterr()
    log: dict = {}
    result = mcp.recommend_result({"listing_key": SUBJECT}, log_fields=log)
    assert result.data.shared_features.features == {9870004: ["hardwood"]}
    assert log["shared_features"] == 1 and log["shared_left_out"] == 1
    text = json.dumps(log, default=str)
    assert "9870002" not in text and "9870004" not in text
    assert "hardwood" not in text


def test_an_unusable_store_logs_only_its_reason(store, monkeypatch):
    store["fresh"] = (1000, 101)
    fa.reset_for_tests()
    on(monkeypatch)
    log: dict = {}
    mcp.recommend_result({"listing_key": SUBJECT}, log_fields=log)
    assert log["shared_features"] == "stale" and "shared_left_out" not in log


def test_badges_switch_never_turns_explanations_on(store, monkeypatch):
    """IDX_FEATURE_BADGES (search cards) is independent of IDX_FEATURE_EXPLANATIONS."""
    off = _recommend(listing_key=SUBJECT)
    monkeypatch.delenv(mcp.EXPLANATIONS_SETTING, raising=False)
    monkeypatch.setenv(mcp.BADGES_SETTING, "1")
    result = _recommend(listing_key=SUBJECT)
    assert result.data.shared_features is None and result.message == off.message
