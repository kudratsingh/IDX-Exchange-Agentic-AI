"""The versioned v5 store migration (WO-035): v4 unchanged, v5 = v4 + ruling 8.

A synthetic world: an invented results source, invented frozen artifacts and invented
policy files in a temporary checkout. The source check and the trusted digest are the
production functions, given the synthetic world's own expected values.
"""

import functools
import hashlib
import itertools
import json
import sqlite3
import stat
from pathlib import Path

import pytest
from scripts import build_enrichment_effective_store as builder
from scripts.propose_enrichment_v5_manifest import propose
from tests.synthetic_store import trust_source, trust_synthetic

from idx_agent.enrichment import store_v5
from idx_agent.enrichment.effective_store import (
    FacetStore,
    StoreUnavailable,
    open_store,
)
from idx_agent.enrichment.policy_audit import candidates
from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION
from idx_agent.enrichment.source_check import results_digest, verify_source

WATERMARK = "2026-09-18 06:58:44"
DATA = Path("data/enrichment")


def lab(group, value, polarity="affirmed", temporality="current"):
    return dict(group=group, value=value, polarity=polarity, temporality=temporality)


SOLAR = lab("interior_systems", "solar")
SOLAR_PLANNED = lab("interior_systems", "solar", temporality="planned")
GARAGE = lab("exterior_lot", "garage")
GARAGE_UNSURE = lab("exterior_lot", "garage", "uncertain")
CONDO_UNSURE = lab("property_type", "condominium", "uncertain")
LEVEL_UNSURE = lab("interior_layout", "single_level", "uncertain")
# Row 1 is a diagnostic case; row 2 is in the dataset inventory (solar) and its v4
# correction makes solar planned; rows 3-5 are outside both packets. Ruling 8 removes
# the uncertain garage on rows 2 and 3 and keeps the uncertain condominium on row 4.
REMARKS = {
    1: ("901", "Invented remark one with owned solar.", [SOLAR], 1),
    2: ("902", "Invented remark two with owned solar.", [SOLAR, GARAGE_UNSURE], 0),
    3: ("903", "Invented remark three about parking.", [GARAGE_UNSURE], 0),
    4: ("904", "Invented remark four about the unit.", [CONDO_UNSURE], 0),
    5: ("905", "Invented remark five with a garage.", [GARAGE, LEVEL_UNSURE], 0),
}
# What the v4 and v5 builds must hold.
V4_ROWS = {
    "901": {"solar": "present"},
    "902": {"solar": "planned", "garage": "uncertain"},
    "903": {"garage": "uncertain"},
    "904": {"condominium": "uncertain"},
    "905": {"garage": "present", "single_level": "uncertain"},
}
V5_ROWS = dict(V4_ROWS, **{"902": {"solar": "planned"}, "903": {}})
# The v4 store's semantic fingerprint (meta, listings and facets), taken from the
# builder before WO-035 on this same world; the v4 build must keep producing it.
V4_FINGERPRINT = "1aee85745164744d706f4a4d39f306c445b3be7b5e925ca489adbd027830ca2a"


def _jsonl(path, records):
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))


def _source(path):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE inputs(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                            remark);
        CREATE TABLE results(sequence INTEGER PRIMARY KEY, listing_key, input_hash,
                             facets, diagnostic_count, usage);
        CREATE TABLE result_origins(sequence INTEGER PRIMARY KEY, extractor);
        CREATE TABLE settings(name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE verifications(completed INTEGER PRIMARY KEY, watermark TEXT);
        """
    )
    for seq, (key, remark, facets, diag) in REMARKS.items():
        digest = hashlib.sha256(remark.encode()).hexdigest()
        db.execute("INSERT INTO inputs VALUES (?,?,?,?)", (seq, key, digest, remark))
        db.execute(
            "INSERT INTO results VALUES (?,?,?,?,?,?)",
            (seq, key, digest, json.dumps(facets), diag, json.dumps({"output": 10})),
        )
        db.execute("INSERT INTO result_origins VALUES (?, 'v2')", (seq,))
    db.execute("INSERT INTO settings VALUES ('watermark', ?)", (WATERMARK,))
    db.execute("INSERT INTO verifications VALUES (5, ?)", (WATERMARK,))
    db.commit()
    return db


def _cleanup_record(seq, facet, removed):
    key = REMARKS[seq][0]
    changes = [
        dict(operation="remove", original=label, corrected_annotation=None, reason="x")
        for label in removed
    ]
    return dict(
        sequence=seq,
        listing_key=key,
        facet=facet,
        policy_version="v5",
        status="corrected" if removed else "accepted_unchanged",
        status_before="uncertain",
        status_after=None if removed else "uncertain",
        changes=changes,
        human_review="pending",
    )


def _cleanup_manifest(records, overlay, dataset_overlay):
    per_facet = {}
    for r in records:
        tally = per_facet.setdefault(r["facet"], {"read": 0, "removed": 0, "kept": 0})
        tally["read"] += 1
        tally["removed"] += len(r["changes"])
        tally["kept"] += not r["changes"]
    return {
        "policy_version": "v5",
        "ruling": 8,
        "overlay": overlay.name,
        "overlay_sha256": store_v5.sha256_file(overlay),
        "base_store": {"policy_version": "v4"},
        "sources": {"dataset_overlay_sha256": store_v5.sha256_file(dataset_overlay)},
        "per_facet": per_facet,
        **{
            k: sum(v[k] for v in per_facet.values())
            for k in ("read", "removed", "kept")
        },
    }


def _write_cleanup(records):
    overlay = DATA / "v5-uncertain-cleanup-overlay.jsonl"
    _jsonl(overlay, records)
    manifest = _cleanup_manifest(
        records, overlay, DATA / "policy-audit-dispositions.jsonl"
    )
    (DATA / "v5-uncertain-cleanup-manifest.json").write_text(json.dumps(manifest))


CLEANUP = [
    _cleanup_record(2, "garage", [GARAGE_UNSURE]),
    _cleanup_record(3, "garage", [GARAGE_UNSURE]),
    _cleanup_record(4, "condominium", []),
]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temporary checkout with invented frozen artifacts; returns build helpers."""
    monkeypatch.chdir(tmp_path)
    (DATA / "full").mkdir(parents=True)
    Path("docs").mkdir()
    Path("docs/ENRICHMENT_REVIEW_POLICY.md").write_text("Invented v4 policy.\n")
    Path("docs/ENRICHMENT_REVIEW_POLICY_V5.md").write_text("Invented v5 policy.\n")
    rules = Path("src/idx_agent/enrichment/policy_rules.py")
    rules.parent.mkdir(parents=True)
    rules.write_text("# Invented rules.\n")
    db = _source(DATA / "full" / "active-facets-v2.sqlite3")
    key, remark, facets, _ = REMARKS[1]
    _jsonl(
        DATA / "diagnostic-review-packet.jsonl",
        [
            dict(
                sequence=1,
                listing_key=key,
                remark=remark,
                origin="v2",
                stored_facets=facets,
            )
        ],
    )
    _jsonl(
        DATA / "diagnostic-review-dispositions.jsonl",
        [dict(sequence=1, listing_key=key, status="accepted_unchanged", changes=[])],
    )
    inventory = list(candidates(db))
    assert [c["sequence"] for c in inventory] == [2]
    _jsonl(DATA / "policy-audit-packet.jsonl", inventory)
    _jsonl(
        DATA / "policy-audit-dispositions.jsonl",
        [
            dict(
                sequence=2,
                listing_key="902",
                status="corrected",
                changes=[
                    dict(operation="remove", original=SOLAR),
                    dict(operation="add", corrected_annotation=SOLAR_PLANNED),
                ],
            )
        ],
    )
    scope = dict(
        population=4,
        inventory_rows=1,
        policy_version="v4",
        rules_version=POLICY_RULES_VERSION,
    )
    (DATA / "policy-audit-scope.json").write_text(json.dumps(scope))
    v4_manifest = {
        name: store_v5.sha256_file(path)
        for name, path in builder.paths(DATA)["artifacts"].items()
    }
    (DATA / "policy-audit-freeze-manifest.json").write_text(json.dumps(v4_manifest))
    _write_cleanup(CLEANUP)
    digest = results_digest(db)
    db.close()
    trust_source(digest, len(REMARKS))
    check = functools.partial(
        verify_source,
        expected_rows=len(REMARKS),
        expected_population=4,
        expected_watermark=WATERMARK,
        expected_digest=digest,
    )

    def build(policy, output=None, **kwargs):
        kwargs.setdefault("results_digest", digest)
        kwargs.setdefault("source_watermark", WATERMARK)
        return builder.build(policy, output, root=DATA, check=check, **kwargs)

    def propose_v5(output=None, **kwargs):
        output = output or tmp_path / "proposed.json"
        kwargs.setdefault("results_digest", digest)
        kwargs.setdefault("source_watermark", WATERMARK)
        return propose(output, DATA, **kwargs), output

    proposals = itertools.count()
    frozen = DATA / "effective-store-v5-manifest.json"

    def freeze_v5(**kwargs):
        """Propose, then copy into place the way the owner freezes it."""
        _, proposed = propose_v5(
            tmp_path / f"proposed-{next(proposals)}.json", **kwargs
        )
        frozen.write_bytes(proposed.read_bytes())
        return frozen

    def freeze_unchecked():
        """Pin the current inputs without the proposal's checks."""
        manifest = store_v5.propose_manifest(
            builder.paths(DATA)["v5_artifacts"],
            rules_version=POLICY_RULES_VERSION,
            results_digest=digest,
            source_rows=len(REMARKS),
            source_watermark=WATERMARK,
        )
        frozen.write_bytes(store_v5.canonical_bytes(manifest))
        return frozen

    return dict(
        tmp=tmp_path,
        digest=digest,
        build=build,
        propose=propose_v5,
        freeze=freeze_v5,
        freeze_unchecked=freeze_unchecked,
    )


def dump(path):
    """Everything a store holds, as sorted rows."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        meta = sorted(db.execute("SELECT name, value FROM meta"))
        listings = sorted(k for (k,) in db.execute("SELECT listing_key FROM listings"))
        facets = sorted(db.execute("SELECT listing_key, facet, status FROM facets"))
    return {"meta": meta, "listings": listings, "facets": facets}


def statuses(path):
    rows = {k: {} for k in dump(path)["listings"]}
    for key, facet, status in dump(path)["facets"]:
        rows[key][facet] = status
    return rows


def fingerprint(path):
    canonical = json.dumps(dump(path), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


V4_OUT = DATA / "full" / "effective-facets-v1.sqlite3"
V5_OUT = DATA / "full" / "effective-facets-v5.sqlite3"


# --- v4 is preserved ---


def test_the_v4_build_is_unchanged_and_reproducible(world):
    summary = world["build"]("v4")
    assert summary == {
        "listings": 5,
        "statuses": {"planned": 1, "present": 2, "uncertain": 4},
    }
    assert statuses(V4_OUT) == V4_ROWS
    meta = dict(dump(V4_OUT)["meta"])
    assert meta["policy_version"] == "v4"
    assert json.loads(meta["built_from"]) == json.loads(
        (DATA / "policy-audit-freeze-manifest.json").read_text()
    )
    assert fingerprint(V4_OUT) == V4_FINGERPRINT
    # The same inputs rebuild a byte-identical file.
    again = world["tmp"] / "again.sqlite3"
    world["build"]("v4", again)
    assert again.read_bytes() == V4_OUT.read_bytes()


def test_the_v4_build_needs_no_v5_input(world):
    for name in (
        "v5-uncertain-cleanup-overlay.jsonl",
        "v5-uncertain-cleanup-manifest.json",
    ):
        (DATA / name).unlink()
    Path("docs/ENRICHMENT_REVIEW_POLICY_V5.md").unlink()
    world["build"]("v4")
    assert statuses(V4_OUT) == V4_ROWS


def test_v5_work_never_changes_the_v4_policy_or_manifest(world):
    pinned = [
        Path("docs/ENRICHMENT_REVIEW_POLICY.md"),
        DATA / "policy-audit-freeze-manifest.json",
    ]
    before = [_sha(p) for p in pinned]
    world["build"]("v4")
    v4_store = V4_OUT.read_bytes()
    world["freeze"]()
    world["build"]("v5")
    assert [_sha(p) for p in pinned] == before
    assert V4_OUT.read_bytes() == v4_store


# --- v5 ---


def test_v5_applies_ruling_8_on_top_of_the_v4_overlays(world):
    frozen = world["freeze"]()
    summary = world["build"]("v5")
    assert summary == {
        "listings": 5,
        "statuses": {"planned": 1, "present": 2, "uncertain": 2},
        "policy_version": "v5",
        "removed_by_facet": {"garage": 2},
    }
    assert statuses(V5_OUT) == V5_ROWS
    store = open_store(V5_OUT)
    assert isinstance(store, FacetStore)
    assert store.info.policy_version == "v5"
    assert store.info.listing_count == 5
    store.close()
    assert stat.S_IMODE(V5_OUT.stat().st_mode) == 0o600
    meta = dict(dump(V5_OUT)["meta"])
    record = json.loads(meta["built_from"])
    assert record["manifests"] == {
        "v4": {
            "file": "policy-audit-freeze-manifest.json",
            "sha256": _sha(DATA / "policy-audit-freeze-manifest.json"),
        },
        "v5": {"file": frozen.name, "sha256": _sha(frozen)},
    }
    assert record["v5_manifest"] == json.loads(frozen.read_text())
    assert meta["results_digest"] == world["digest"]
    assert (meta["source_rows"], meta["listing_count"]) == ("5", "5")


def test_a_dry_run_verifies_and_counts_but_writes_nothing(world):
    world["freeze"]()
    summary = world["build"]("v5", dry_run=True)
    assert summary["written"] is False
    assert summary["removed_by_facet"] == {"garage": 2}
    assert summary["statuses"] == {"planned": 1, "present": 2, "uncertain": 2}
    assert not V5_OUT.exists() and not V4_OUT.exists()


def test_v5_never_writes_over_the_v4_store_or_uses_the_v4_manifest(world):
    world["freeze"]()
    with pytest.raises(ValueError, match="never writes over the v4 store"):
        world["build"]("v5", V4_OUT)
    with pytest.raises(ValueError, match="must not be the v4 manifest"):
        world["build"]("v5", v5_manifest=DATA / "policy-audit-freeze-manifest.json")
    assert not V4_OUT.exists()


def test_v5_refuses_without_a_frozen_v5_manifest(world):
    with pytest.raises(FileNotFoundError):
        world["build"]("v5")
    assert not V5_OUT.exists()


@pytest.mark.parametrize("name", sorted(store_v5.V5_ARTIFACT_NAMES))
def test_v5_refuses_when_any_pinned_input_drifts(world, name):
    world["freeze"]()
    path = builder.paths(DATA)["v5_artifacts"][name]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        world["build"]("v5")
    assert not V5_OUT.exists()


def test_the_v5_manifest_pins_every_required_input(world):
    _, proposed = world["propose"]()
    manifest = json.loads(proposed.read_text())
    assert set(manifest["artifacts"]) == {
        "policy",
        "policy_v5",
        "dataset_rules",
        "packet",
        "overlay",
        "dataset_packet",
        "dataset_overlay",
        "dataset_scope",
        "cleanup_overlay",
        "cleanup_manifest",
        "v4_manifest",
    }
    v4 = json.loads((DATA / "policy-audit-freeze-manifest.json").read_text())
    assert {k: manifest["artifacts"][k] for k in v4} == v4
    assert manifest["artifacts"]["v4_manifest"] == _sha(
        DATA / "policy-audit-freeze-manifest.json"
    )
    assert manifest["rules_version"] == POLICY_RULES_VERSION
    assert manifest["results_digest"] == world["digest"]
    assert manifest["source_watermark"] == WATERMARK
    assert manifest["source_rows"] == 5


def test_a_non_canonical_v5_manifest_is_refused(world):
    frozen = world["freeze"]()
    frozen.write_text(json.dumps(json.loads(frozen.read_text()), indent=4))
    with pytest.raises(ValueError, match="canonical"):
        world["build"]("v5")


@pytest.mark.parametrize(
    "override, message",
    [
        ({"source_watermark": "2026-01-01 00:00:00"}, "watermark"),
        ({"results_digest": "synthetic"}, "results digest"),
    ],
)
def test_a_v5_manifest_with_other_provenance_is_refused(world, override, message):
    if override.get("results_digest") == "synthetic":
        override = {"results_digest": trust_synthetic(len(REMARKS))}
    world["freeze"](**override)
    with pytest.raises(ValueError, match=message):
        world["build"]("v5")


def test_a_v5_manifest_whose_count_is_not_trusted_is_refused(world):
    frozen = world["freeze"]()
    manifest = json.loads(frozen.read_text())
    manifest["source_rows"] = 6
    frozen.write_bytes(store_v5.canonical_bytes(manifest))
    with pytest.raises(ValueError, match="source count"):
        world["build"]("v5")


# --- ruling 8 may only remove uncertain labels ---


def _mutated(**fields):
    record = json.loads(json.dumps(CLEANUP[0]))
    record.update(fields)
    return record


@pytest.mark.parametrize(
    "record",
    [
        _mutated(facet="solar"),
        _mutated(policy_version="v4"),
        _mutated(status_before="present"),
        _mutated(status="rejected"),
        _mutated(status_after="present"),
        _mutated(
            changes=[dict(operation="add", corrected_annotation=GARAGE, original=None)]
        ),
        _mutated(
            changes=[
                dict(operation="remove", original=GARAGE, corrected_annotation=None)
            ]
        ),
        _mutated(
            changes=[
                dict(
                    operation="remove", original=CONDO_UNSURE, corrected_annotation=None
                )
            ]
        ),
        _mutated(status="accepted_unchanged", status_after="uncertain"),
        _mutated(changes=[]),
    ],
    ids=[
        "facet-outside-the-six",
        "not-v5",
        "not-from-uncertain",
        "unknown-status",
        "ends-present",
        "adds-a-label",
        "removes-an-affirmed-label",
        "removes-another-facet",
        "unchanged-with-changes",
        "correction-without-changes",
    ],
)
def test_a_cleanup_that_does_anything_but_remove_uncertain_labels_is_refused(
    world, record
):
    _write_cleanup([record, *CLEANUP[1:]])
    with pytest.raises(ValueError):
        world["propose"]()
    # Pinned without the proposal's checks, the builder still refuses it.
    world["freeze_unchecked"]()
    with pytest.raises(ValueError):
        world["build"]("v5")
    assert not V5_OUT.exists()


@pytest.mark.parametrize(
    "records, message",
    [
        ([CLEANUP[0], CLEANUP[0]], "repeats"),
        (
            [_cleanup_record(5, "single_level", [LEVEL_UNSURE]), *CLEANUP],
            None,
        ),
    ],
    ids=["repeated", "consistent-extra"],
)
def test_cleanup_records_are_unique(world, records, message):
    _write_cleanup(records)
    if message is None:
        world["freeze"]()
        assert world["build"]("v5")["removed_by_facet"] == {
            "garage": 2,
            "single_level": 1,
        }
    else:
        with pytest.raises(ValueError, match=message):
            world["propose"]()


@pytest.mark.parametrize(
    "record, message",
    [
        (_cleanup_record(1, "garage", [GARAGE_UNSURE]), "not uncertain in v4"),
        (_cleanup_record(5, "garage", [GARAGE_UNSURE]), "not uncertain in v4"),
        (
            _cleanup_record(4, "condominium", [CONDO_UNSURE, CONDO_UNSURE]),
            "not present",
        ),
        (dict(_cleanup_record(3, "garage", [GARAGE_UNSURE]), listing_key="9"), "key"),
        (dict(_cleanup_record(3, "garage", [GARAGE_UNSURE]), sequence=99), "no match"),
    ],
    ids=["facet-absent", "facet-present", "label-absent", "other-key", "no-result"],
)
def test_a_cleanup_that_does_not_fit_the_v4_labels_is_refused(world, record, message):
    _write_cleanup([record])
    world["freeze"]()
    with pytest.raises(ValueError, match=message):
        world["build"]("v5")
    assert not V5_OUT.exists()


def test_the_cleanup_manifest_must_describe_its_overlay(world):
    manifest_path = DATA / "v5-uncertain-cleanup-manifest.json"
    good = json.loads(manifest_path.read_text())
    for number, edit in enumerate(
        (
            {"removed": 3},
            {
                "per_facet": dict(
                    good["per_facet"], garage={"read": 2, "removed": 1, "kept": 1}
                )
            },
            {"overlay_sha256": "0" * 64},
            {"sources": {"dataset_overlay_sha256": "0" * 64}},
            {"base_store": {"policy_version": "v3"}},
            {"ruling": 7},
        )
    ):
        manifest_path.write_text(json.dumps(dict(good, **edit)))
        with pytest.raises(ValueError):
            world["propose"](world["tmp"] / f"p-{number}.json")


# --- open_store checks v5 provenance ---


def _edit_meta(path, name, transform):
    with sqlite3.connect(path) as db:
        (value,) = db.execute(
            "SELECT value FROM meta WHERE name = ?", (name,)
        ).fetchone()
        db.execute("UPDATE meta SET value = ? WHERE name = ?", (transform(value), name))


def _edit_record(edit):
    def transform(value):
        record = json.loads(value)
        edit(record)
        return json.dumps(record, sort_keys=True)

    return transform


@pytest.mark.parametrize(
    "name, transform",
    [
        ("policy_version", lambda v: "v4"),
        ("rules_version", lambda v: "other"),
        ("built_from", lambda v: "{}"),
        (
            "built_from",
            _edit_record(lambda r: r["manifests"]["v5"].update(sha256="0" * 64)),
        ),
        (
            "built_from",
            _edit_record(lambda r: r["manifests"]["v4"].update(sha256="0" * 64)),
        ),
        (
            "built_from",
            _edit_record(lambda r: r["manifests"]["v4"].update(file="../m.json")),
        ),
        ("built_from", _edit_record(lambda r: r["manifests"].pop("v4"))),
        (
            "built_from",
            _edit_record(
                lambda r: r["v5_manifest"]["artifacts"].update(policy_v5="0" * 64)
            ),
        ),
        (
            "built_from",
            _edit_record(
                lambda r: r["v5_manifest"]["artifacts"].pop("cleanup_overlay")
            ),
        ),
        ("built_from", _edit_record(lambda r: r["v5_manifest"].update(source_rows=6))),
    ],
    ids=[
        "relabelled-v4",
        "other-rules",
        "no-provenance",
        "v5-hash",
        "v4-hash",
        "path-not-basename",
        "one-manifest",
        "manifest-edited",
        "artifact-missing",
        "count-edited",
    ],
)
def test_a_v5_store_with_broken_provenance_does_not_open(world, name, transform):
    world["freeze"]()
    world["build"]("v5")
    _edit_meta(V5_OUT, name, transform)
    assert open_store(V5_OUT) == StoreUnavailable("provenance_mismatch")


def test_a_v5_store_with_another_count_does_not_open(world):
    world["freeze"]()
    world["build"]("v5")
    with sqlite3.connect(V5_OUT) as db:
        db.execute("DELETE FROM facets WHERE listing_key = '905'")
        db.execute("DELETE FROM listings WHERE listing_key = '905'")
        for name in ("listing_count", "source_rows"):
            db.execute("UPDATE meta SET value = '4' WHERE name = ?", (name,))
    # The embedded v5 manifest still says five rows.
    assert open_store(V5_OUT) == StoreUnavailable("provenance_mismatch")


def test_a_v4_store_still_opens_beside_a_v5_store(world):
    world["build"]("v4")
    world["freeze"]()
    world["build"]("v5")
    for path, version in ((V4_OUT, "v4"), (V5_OUT, "v5")):
        store = open_store(path)
        assert isinstance(store, FacetStore) and store.info.policy_version == version
        store.close()


# --- the proposal command ---


def test_the_proposal_is_private_deterministic_and_never_overwrites(world):
    first, path = world["propose"](world["tmp"] / "one.json")
    second, other = world["propose"](world["tmp"] / "two.json")
    assert path.read_bytes() == other.read_bytes()
    assert first["sha256"] == second["sha256"] == _sha(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="existing or pinned"):
        world["propose"](path)
    v4 = DATA / "policy-audit-freeze-manifest.json"
    before = v4.read_bytes()
    with pytest.raises(ValueError, match="existing or pinned"):
        world["propose"](v4)
    assert v4.read_bytes() == before


def test_the_proposal_refuses_a_drifted_v4_input(world):
    policy = Path("docs/ENRICHMENT_REVIEW_POLICY.md")
    policy.write_text(policy.read_text() + "edited\n")
    with pytest.raises(ValueError, match="no longer matches the manifest"):
        world["propose"]()
    assert not (world["tmp"] / "proposed.json").exists()
