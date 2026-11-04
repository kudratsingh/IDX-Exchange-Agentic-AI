"""Review policy v5 for the effective store: ruling 8 and v5 provenance (WO-035).

A v5 store is the v4 effective labels with ruling 8's correction overlay on top, pinned
by a separate v5 manifest; the v4 manifest is never changed. Reads no listing text.
"""

# v5 extends v4 (`docs/ENRICHMENT_REVIEW_POLICY_V5.md`). The v4 effective labels are the
# results plus the diagnostic or dataset overlay. Ruling 8's overlay may only remove
# `uncertain` labels on the six limited facets; anything else is refused. The v5
# manifest pins every input, the v4 manifest included, and a v5 store records both.

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from idx_agent.enrichment.effective import facet_status, facet_statuses

POLICY_VERSION = "v5"
BASE_POLICY_VERSION = "v4"
MANIFEST_FORMAT = "effective-store-v5-manifest/1"
BUILT_FROM_FORMAT = "effective-store-built-from-v5/1"
CLEANUP_RULING = 8
# What a v5 store states about its labels, verbatim (owner decisions, 2026-11-03 and
# 2026-11-04): v5 applies only ruling 8's overlay; rulings 1-7 and 9-15 are policy
# text, not applied to the stored labels (any re-read is a separate owner decision). A
# v5 store's meta must carry exactly this as `policy_scope`; a v4 store carries no
# `policy_scope`.
POLICY_SCOPE = (
    "policy v5; rulings applied: 8 overlay only; "
    "rulings 1-7 and 9-15 not applied to stored labels"
)
# Ruling 8 covers only the six limited facets, never audited outside the 471 cases.
CLEANUP_FACETS = frozenset(
    {
        "condominium",
        "garage",
        "near_grocery_mentioned",
        "near_transit_mentioned",
        "single_level",
        "stainless_appliances",
    }
)
# What the v4 freeze manifest pins, by name (see the effective-store builder).
V4_ARTIFACT_NAMES = frozenset(
    {
        "packet",
        "overlay",
        "policy",
        "dataset_packet",
        "dataset_overlay",
        "dataset_scope",
        "dataset_rules",
    }
)
# What v5 adds: the v4 manifest itself, the v5 policy, and ruling 8's overlay and its
# manifest. A v5 manifest pins exactly the union.
V5_ONLY_ARTIFACT_NAMES = frozenset(
    {"v4_manifest", "policy_v5", "cleanup_overlay", "cleanup_manifest"}
)
V5_ARTIFACT_NAMES = V4_ARTIFACT_NAMES | V5_ONLY_ARTIFACT_NAMES
_MANIFEST_KEYS = frozenset(
    {
        "format",
        "policy_version",
        "base_policy_version",
        "rules_version",
        "results_digest",
        "source_rows",
        "source_watermark",
        "artifacts",
    }
)
_BUILT_FROM_KEYS = frozenset({"format", "manifests", "v5_manifest"})
_LABEL_FIELDS = frozenset({"group", "value", "polarity", "temporality"})
_CLEANUP_STATUSES = ("corrected", "accepted_unchanged")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_bytes(manifest: Mapping[str, Any]) -> bytes:
    """The one byte form of a v5 manifest, so a store's copy can be re-hashed."""
    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()


def _is_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _is_basename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and Path(value).name == value
        and "\\" not in value
    )


def _check_manifest_shape(manifest: Any) -> None:
    """Raise ValueError unless `manifest` has the v5 manifest's exact shape."""
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ValueError("v5 manifest has the wrong fields")
    if manifest["format"] != MANIFEST_FORMAT:
        raise ValueError("v5 manifest has an unknown format")
    if (
        manifest["policy_version"] != POLICY_VERSION
        or manifest["base_policy_version"] != BASE_POLICY_VERSION
    ):
        raise ValueError("v5 manifest names the wrong policy versions")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != V5_ARTIFACT_NAMES:
        raise ValueError("v5 manifest names different artifacts")
    if not all(_is_hex(value) for value in artifacts.values()):
        raise ValueError("v5 manifest holds a malformed hash")
    rows = manifest["source_rows"]
    if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
        raise ValueError("v5 manifest holds a malformed source count")
    if not _is_hex(manifest["results_digest"]) or not all(
        isinstance(manifest[k], str) for k in ("rules_version", "source_watermark")
    ):
        raise ValueError("v5 manifest holds malformed provenance")


def propose_manifest(
    artifacts: Mapping[str, Path],
    *,
    rules_version: str,
    results_digest: str,
    source_rows: int,
    source_watermark: str,
) -> dict[str, Any]:
    """A v5 manifest pinning the current bytes of every named artifact.

    It only records hashes; the caller verifies the inputs first, and the owner freezes
    the result. The same inputs always give the same manifest.
    """
    if set(artifacts) != V5_ARTIFACT_NAMES:
        raise ValueError("a v5 manifest pins exactly the v5 artifacts")
    manifest = {
        "format": MANIFEST_FORMAT,
        "policy_version": POLICY_VERSION,
        "base_policy_version": BASE_POLICY_VERSION,
        "rules_version": rules_version,
        "results_digest": results_digest,
        "source_rows": source_rows,
        "source_watermark": source_watermark,
        "artifacts": {name: sha256_file(path) for name, path in artifacts.items()},
    }
    _check_manifest_shape(manifest)
    return manifest


def verify_v5_manifest(
    raw: bytes,
    artifacts: Mapping[str, Path],
    *,
    results_digest: str,
    source_rows: int | None,
    source_watermark: str,
    rules_version: str,
) -> dict[str, Any]:
    """Return the v5 manifest in `raw`, or raise ValueError if anything drifted.

    `raw` must be canonical, every artifact must match its hash, the v4 entries must
    equal the (also pinned) v4 manifest's, and the provenance must be the trusted ones.
    """
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("v5 manifest is not JSON") from None
    _check_manifest_shape(manifest)
    if canonical_bytes(manifest) != raw:
        raise ValueError("v5 manifest is not in canonical form")
    if set(artifacts) != V5_ARTIFACT_NAMES:
        raise ValueError("v5 manifest names different artifacts")
    for name, path in sorted(artifacts.items()):
        if sha256_file(path) != manifest["artifacts"][name]:
            raise ValueError(f"frozen {name} no longer matches the v5 manifest")
    v4_manifest = json.loads(Path(artifacts["v4_manifest"]).read_bytes())
    if not isinstance(v4_manifest, dict) or set(v4_manifest) != V4_ARTIFACT_NAMES:
        raise ValueError("v4 manifest names different artifacts")
    for name in V4_ARTIFACT_NAMES:
        if manifest["artifacts"][name] != v4_manifest[name]:
            raise ValueError(f"v5 manifest's {name} differs from the v4 manifest")
    if source_rows is None or manifest["source_rows"] != source_rows:
        raise ValueError("v5 manifest's source count is not the trusted count")
    if manifest["results_digest"] != results_digest:
        raise ValueError("v5 manifest's results digest is not the approved one")
    if manifest["source_watermark"] != source_watermark:
        raise ValueError("v5 manifest's source watermark is not the verified one")
    if manifest["rules_version"] != rules_version:
        raise ValueError("v5 manifest's rules version differs from the rules")
    return manifest


def _check_label(label: Any, facet: str) -> None:
    if (
        not isinstance(label, dict)
        or set(label) != _LABEL_FIELDS
        or label["value"] != facet
        or label["polarity"] != "uncertain"
    ):
        raise ValueError("ruling 8 may remove only an uncertain label of its facet")


def validate_cleanup(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    overlay_name: str,
    overlay_sha256: str,
    dataset_overlay_sha256: str,
) -> dict[int, list[Mapping[str, Any]]]:
    """Check ruling 8's overlay against its manifest; return its records by sequence.

    Each record is a v5 reading of one limited facet that was `uncertain`; a correction
    only removes that facet's uncertain labels. The manifest's counts must match.
    """
    if (
        manifest.get("policy_version") != POLICY_VERSION
        or manifest.get("ruling") != CLEANUP_RULING
        or manifest.get("overlay") != overlay_name
        or manifest.get("overlay_sha256") != overlay_sha256
    ):
        raise ValueError("ruling 8 manifest does not describe this overlay")
    base = manifest.get("base_store")
    sources = manifest.get("sources")
    if not isinstance(base, dict) or base.get("policy_version") != BASE_POLICY_VERSION:
        raise ValueError("ruling 8 overlay is not based on the v4 labels")
    if (
        not isinstance(sources, dict)
        or sources.get("dataset_overlay_sha256") != dataset_overlay_sha256
    ):
        raise ValueError("ruling 8 overlay was read against another dataset overlay")
    by_sequence: dict[int, list[Mapping[str, Any]]] = {}
    seen: set[tuple[int, str]] = set()
    counts: dict[str, Counter] = {}
    for record in records:
        sequence, facet = record.get("sequence"), record.get("facet")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError("ruling 8 record has a malformed sequence")
        if facet not in CLEANUP_FACETS:
            raise ValueError("ruling 8 record names a facet outside the six")
        if (sequence, facet) in seen:
            raise ValueError("ruling 8 overlay repeats a listing facet")
        seen.add((sequence, facet))
        if record.get("policy_version") != POLICY_VERSION:
            raise ValueError("ruling 8 record is not a v5 reading")
        if record.get("status_before") != "uncertain":
            raise ValueError("ruling 8 record does not start from uncertain")
        if record.get("listing_key") in (None, ""):
            raise ValueError("ruling 8 record has no listing key")
        status, changes = record.get("status"), record.get("changes")
        if status not in _CLEANUP_STATUSES or not isinstance(changes, list):
            raise ValueError("ruling 8 record has an unknown status")
        if status == "accepted_unchanged":
            if changes or record.get("status_after") != "uncertain":
                raise ValueError("an unchanged ruling 8 record changes something")
        else:
            if not changes or record.get("status_after") == "present":
                raise ValueError("a ruling 8 correction must remove, never add")
            for change in changes:
                if (
                    not isinstance(change, dict)
                    or change.get("operation") != "remove"
                    or change.get("corrected_annotation") is not None
                ):
                    raise ValueError("ruling 8 may only remove labels")
                _check_label(change.get("original"), facet)
        tally = counts.setdefault(facet, Counter())
        tally["read"] += 1
        tally["removed"] += len(changes) if status == "corrected" else 0
        tally["kept"] += status == "accepted_unchanged"
        by_sequence.setdefault(sequence, []).append(record)
    per_facet = manifest.get("per_facet")
    if not isinstance(per_facet, dict) or not set(per_facet) <= CLEANUP_FACETS:
        raise ValueError("ruling 8 manifest's facet counts are malformed")
    expected = {
        facet: {k: counts.get(facet, Counter())[k] for k in ("read", "removed", "kept")}
        for facet in set(per_facet) | set(counts)
    }
    totals = {
        k: sum(v[k] for v in expected.values()) for k in ("read", "removed", "kept")
    }
    if per_facet != expected or any(manifest.get(k) != v for k, v in totals.items()):
        raise ValueError("ruling 8 manifest's counts differ from its overlay")
    return by_sequence


def _status(labels: Sequence[Mapping[str, Any]], facet: str) -> str | None:
    return facet_status([x for x in labels if x["value"] == facet])


def cleaned_rows(
    labelled: Iterable[tuple[int, str, list[Mapping[str, Any]]]],
    cleanup: Mapping[int, Sequence[Mapping[str, Any]]],
    removed: Counter | None = None,
) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (listing_key, statuses) after applying ruling 8 on top of the v4 labels.

    `labelled` yields (sequence, listing_key, labels) after the v4 overlays. A record's
    facet must be `uncertain` there and end in its recorded status. `removed` counts.
    """
    seen: set[int] = set()
    for sequence, key, labels in labelled:
        labels = [dict(label) for label in labels]
        for record in cleanup.get(sequence, ()):
            facet = record["facet"]
            if str(record["listing_key"]) != str(key):
                raise ValueError("ruling 8 listing key differs from the result")
            if _status(labels, facet) != record["status_before"]:
                raise ValueError("ruling 8 record's facet is not uncertain in v4")
            for change in record["changes"]:
                try:
                    labels.remove(dict(change["original"]))
                except ValueError:
                    raise ValueError(
                        "ruling 8 removes a label that is not present"
                    ) from None
                if removed is not None:
                    removed[facet] += 1
            if _status(labels, facet) != record["status_after"]:
                raise ValueError("ruling 8 record's status after differs")
        seen.add(sequence)
        yield str(key), facet_statuses(labels)
    if set(cleanup) - seen:
        raise ValueError("a ruling 8 record has no matching result")


def built_from(
    v4_manifest_name: str,
    v4_manifest_sha256: str,
    v5_manifest_name: str,
    v5_manifest: Mapping[str, Any],
) -> str:
    """A v5 store's `built_from`: both manifests, and the v5 manifest itself."""
    record = {
        "format": BUILT_FROM_FORMAT,
        "manifests": {
            "v4": {"file": v4_manifest_name, "sha256": v4_manifest_sha256},
            "v5": {
                "file": v5_manifest_name,
                "sha256": hashlib.sha256(canonical_bytes(v5_manifest)).hexdigest(),
            },
        },
        "v5_manifest": dict(v5_manifest),
    }
    check_provenance_record(record)
    return json.dumps(record, sort_keys=True)


def check_provenance_record(record: Any) -> None:
    """Raise ValueError unless a v5 `built_from` record is internally consistent."""
    if not isinstance(record, dict) or set(record) != _BUILT_FROM_KEYS:
        raise ValueError("v5 provenance has the wrong fields")
    if record["format"] != BUILT_FROM_FORMAT:
        raise ValueError("v5 provenance has an unknown format")
    manifests = record["manifests"]
    if not isinstance(manifests, dict) or set(manifests) != {"v4", "v5"}:
        raise ValueError("v5 provenance must name both manifests")
    for entry in manifests.values():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"file", "sha256"}
            or not _is_basename(entry["file"])
            or not _is_hex(entry["sha256"])
        ):
            raise ValueError("v5 provenance names a manifest badly")
    v5_manifest = record["v5_manifest"]
    _check_manifest_shape(v5_manifest)
    digest = hashlib.sha256(canonical_bytes(v5_manifest)).hexdigest()
    if digest != manifests["v5"]["sha256"]:
        raise ValueError("v5 provenance does not match its v5 manifest")
    if v5_manifest["artifacts"]["v4_manifest"] != manifests["v4"]["sha256"]:
        raise ValueError("v5 provenance's v4 manifest differs from the pinned one")


def check_store_provenance(meta: Mapping[str, str]) -> None:
    """Raise ValueError unless a store's v5 provenance holds; v4 stores pass unchanged.

    A store labelled v5 or claiming v5 provenance must be both and state `POLICY_SCOPE`;
    its v5 manifest must agree with the store's digest, count, watermark and rules.
    """
    try:
        record = json.loads(meta["built_from"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("store provenance is not JSON") from None
    claims_v5 = isinstance(record, dict) and record.get("format") == BUILT_FROM_FORMAT
    is_v5 = meta.get("policy_version") == POLICY_VERSION
    if not claims_v5 and not is_v5:
        # A v4 store states no policy scope at all.
        if "policy_scope" in meta:
            raise ValueError("only a v5 store states a policy scope")
        return
    if claims_v5 != is_v5:
        raise ValueError("store policy version and provenance disagree")
    if meta.get("policy_scope") != POLICY_SCOPE:
        raise ValueError("v5 store does not state its policy scope")
    check_provenance_record(record)
    manifest = record["v5_manifest"]
    if (
        manifest["results_digest"] != meta.get("results_digest")
        or str(manifest["source_rows"]) != meta.get("source_rows")
        or manifest["source_watermark"] != meta.get("source_watermark")
        or manifest["rules_version"] != meta.get("rules_version")
    ):
        raise ValueError("store meta differs from its v5 manifest")
