"""WO-026 omission-risk pilot: frozen stratified sample, review records and aggregates.

Pure functions over caller-supplied rows; no database, provider or file access. An
omission is a listing whose remark affirms a current feature while the effective store
has no `present` status for it. Pilot rates are not dataset-wide accuracy estimates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from idx_agent.enrichment.effective import ELIGIBLE_FACETS, FACET_STATUSES

PILOT_ID = "omission-pilot-v1"
SEED = "wo026-omission-20261102"
METHOD = "per-stratum sha256(seed|facet|stratum|key) rank, smallest first"
GUIDE_VERSION = "ENRICHMENT_ANNOTATION v1 + ENRICHMENT_REVIEW_POLICY v4"
# Audited only in the 471 diagnostic cases (WO-018 closeout); larger strata.
LIMITED_FACETS = frozenset(
    {
        "condominium",
        "garage",
        "near_grocery_mentioned",
        "near_transit_mentioned",
        "single_level",
        "stainless_appliances",
    }
)
STRATA = ("labeled_non_present", "cue", "no_cue")
# Existing non-present labels on the other 14 facets were read by the policy audit.
LIMITED_ALLOCATION = {"labeled_non_present": 2, "cue": 7, "no_cue": 3}
OTHER_ALLOCATION = {"labeled_non_present": 0, "cue": 3, "no_cue": 2}
DECISIONS = ("omitted_present", "correctly_absent", "non_present_mention", "unclear")
REVIEW_TYPES = ("model", "human")
HUMAN_REVIEW = ("pending", "confirmed", "overridden")
STATUS_CHECK = ("not_applicable", "correct", "wrong", "unclear")
_NON_PRESENT = frozenset(FACET_STATUSES) - {"present"}

# Crude, public lexical cues used only to split strata; a cue is not a label.
_WOODS = "oak|walnut|maple|hickory|cherry|mahogany|teak|acacia|pecan|birch|ipe"
_GROCERS = (
    "grocer|supermarket|trader joe|whole foods|ralphs|vons|safeway|albertsons|"
    "sprouts|stater bros|costco|aldi|food 4 less|smart (?:&|and) final|h ?mart|"
    "99 ranch|gelson|bristol farms|pavilions|save mart|raley|winco|food ?max"
)
_WATER = "ocean|water|bay|lake|river|harbor|sea|marina|coast(?:al|line)?|pacific|beach"
CUES: Mapping[str, re.Pattern[str]] = {
    facet: re.compile(pattern, re.IGNORECASE)
    for facet, pattern in {
        "adu": r"\badu\b|accessory dwelling|granny|in-?law"
        r"|guest (?:house|unit|quarters)|casita|second unit|\bjadu\b",
        "bonus_room": r"bonus|\bflex\b|\bloft\b|game room|media room",
        "clubhouse": r"club ?house|club ?room|community (?:room|center)"
        r"|rec(?:reation)? (?:room|center)",
        "community_pool": r"\bpools?\b",
        "condominium": r"\bcondo(?:minium)?s?\b",
        "fitness_center": r"fitness|\bgym\b|exercise room|work ?out",
        "garage": r"garage|\b\d[\s-]*car\b",
        "gated_community": r"\bgated?\b|guard",
        "hardwood": rf"hard ?wood|wood (?:floor|flooring)|\b(?:{_WOODS})\b",
        "mountain_view": r"mountain|\bmtn\b|(?:hill|canyon|valley|peak)s?\W+view",
        "near_grocery_mentioned": rf"\b(?:{_GROCERS})",
        "near_transit_mentioned": r"transit|\bmetro(?:link)?\b|\bbus(?:es)?\b"
        r"|\btrains?\b|\brail(?:way|road)?\b|light[\s-]rail|\bbart\b|caltrain"
        r"|trolley|subway|amtrak|commuter",
        "open_plan": r"open[\s-]*(?:floor[\s-]*plan|concept|layout|plan)|great room"
        r"|flows? (?:into|to)|open (?:kitchen|living)",
        "patio": r"patio",
        "pool": r"\bpools?\b",
        "single_level": r"\b(?:single|one|1)[\s-]*(?:level|story|storey|floor)\b"
        r"|no (?:interior )?(?:stairs|steps)",
        "solar": r"solar|photovoltaic|\bpv\b",
        "stainless_appliances": r"stainless|\bs/?s\b",
        "walk_in_closet": r"walk[\s-]*in(?:s|\s+(?:closet|wardrobe))?\b|\bwic\b",
        "water_view": rf"(?:{_WATER})\W+(?:\w+\W+){{0,3}}views?"
        rf"|views?\W+(?:\w+\W+){{0,4}}(?:{_WATER})",
    }.items()
}


def allocation(facet: str) -> dict[str, int]:
    """Target items per stratum for one facet (larger for the six limited facets)."""
    if facet not in ELIGIBLE_FACETS:
        raise ValueError("unknown facet")
    return dict(LIMITED_ALLOCATION if facet in LIMITED_FACETS else OTHER_ALLOCATION)


def stratum_of(facet: str, status: str | None, remark: str) -> str | None:
    """The stratum for one listing and facet; None when the status is present."""
    if status == "present":
        return None
    if status is not None:
        if status not in _NON_PRESENT:
            raise ValueError("unknown status")
        return "labeled_non_present"
    return "cue" if CUES[facet].search(remark) else "no_cue"


def cue_spans(facet: str, remark: str) -> list[list[int]]:
    """Half-open offsets of cue matches, for a private review packet only."""
    return [[m.start(), m.end()] for m in CUES[facet].finditer(remark)]


def build_population(
    rows: Iterable[tuple[str, str, Mapping[str, str]]], excluded: Iterable[str]
) -> dict[tuple[str, str], list[str]]:
    """Group non-present (listing, facet) pairs by (facet, stratum), keys sorted.

    Rows are (listing_key, remark, {facet: status}); excluded keys never enter.
    """
    skip = {str(key) for key in excluded}
    groups: dict[tuple[str, str], list[str]] = {
        (f, s): [] for f in sorted(ELIGIBLE_FACETS) for s in STRATA
    }
    seen: set[str] = set()
    for key, remark, statuses in rows:
        key = str(key)
        if key in seen:
            raise ValueError("duplicate listing key")
        seen.add(key)
        if key in skip:
            continue
        for facet in ELIGIBLE_FACETS:
            stratum = stratum_of(facet, statuses.get(facet), remark)
            if stratum is not None:
                groups[(facet, stratum)].append(key)
    return {group: sorted(keys) for group, keys in groups.items()}


def _rank(seed: str, facet: str, stratum: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|{facet}|{stratum}|{key}".encode()).hexdigest()


def draw_sample(
    population: Mapping[tuple[str, str], Sequence[str]], seed: str = SEED
) -> list[dict]:
    """Take each stratum's allocation by seeded hash rank; a short stratum gives all.

    Items are ordered by facet, stratum and rank and get opaque sequential ids.
    """
    items = []
    for facet, stratum in sorted(population):
        want = allocation(facet)[stratum]
        keys = sorted(
            population[(facet, stratum)],
            key=lambda k: (_rank(seed, facet, stratum, k), k),
        )
        for key in keys[:want]:
            items.append({"facet": facet, "stratum": stratum, "listing_key": key})
    for number, item in enumerate(items, 1):
        item["item_id"] = f"op1-{number:03d}"
    return items


def population_counts(population: Mapping[tuple[str, str], Sequence[str]]) -> dict:
    """{facet: {stratum: count}} for weighting; counts only, no keys."""
    counts: dict[str, dict[str, int]] = {}
    for (facet, stratum), keys in sorted(population.items()):
        counts.setdefault(facet, {})[stratum] = len(keys)
    return counts


def canonical_jsonl(records: Iterable[Mapping]) -> str:
    """One compact, key-sorted JSON object per line."""
    return "".join(
        json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for r in records
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def validate_judgments(
    judgments: Sequence[Mapping], sample: Sequence[Mapping], review_type: str
) -> list[dict]:
    """Check review records against the frozen sample; return them in sample order.

    Every judgment must name a sampled item once, with its facet and stratum, a known
    decision, reviewer provenance and a status check. Model records stay pending.
    """
    if review_type not in REVIEW_TYPES:
        raise ValueError("unknown review type")
    by_id = {item["item_id"]: item for item in sample}
    out: dict[str, dict] = {}
    for record in judgments:
        item = by_id.get(record.get("item_id"))
        if item is None:
            raise ValueError("judgment for an item outside the sample")
        if record["item_id"] in out:
            raise ValueError("duplicate judgment")
        if (record.get("facet"), record.get("stratum")) != (
            item["facet"],
            item["stratum"],
        ):
            raise ValueError("judgment facet or stratum differs from the sample")
        if record.get("decision") not in DECISIONS:
            raise ValueError("unknown decision")
        if record.get("review_type") != review_type:
            raise ValueError("review type differs from the declared one")
        reviewer = record.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("reviewer is required")
        if review_type == "model" and not reviewer.startswith("model:"):
            raise ValueError("a model review must name a model reviewer")
        if review_type == "human" and reviewer.startswith("model:"):
            raise ValueError("a human review cannot name a model reviewer")
        if record.get("guide_version") != GUIDE_VERSION:
            raise ValueError("guide version differs from the pilot's")
        datetime.fromisoformat(str(record.get("reviewed_at")))
        human = record.get("human_review")
        if human not in HUMAN_REVIEW or (review_type == "model" and human != "pending"):
            raise ValueError("model reviews must leave human_review pending")
        check = record.get("existing_status_check")
        applies = item["stratum"] == "labeled_non_present"
        if check not in STATUS_CHECK or (check == "not_applicable") == applies:
            raise ValueError("status check must be given exactly for labeled items")
        out[record["item_id"]] = dict(record)
    return [out[i["item_id"]] for i in sample if i["item_id"] in out]


def merge_reviews(model: Sequence[Mapping], human: Sequence[Mapping] = ()) -> dict:
    """{item_id: judgment}, a human judgment replacing the model's for that item."""
    merged = {r["item_id"]: dict(r) for r in model}
    merged.update({r["item_id"]: dict(r) for r in human})
    return merged


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion; None when n is zero."""
    if n == 0:
        return None
    p = successes / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denominator = 1 + z * z / n
    return (
        max(0.0, (centre - spread) / denominator),
        min(1.0, (centre + spread) / denominator),
    )


def _cell(decisions: Counter, population: int | None = None) -> dict:
    n = sum(decisions.values())
    omitted = decisions["omitted_present"]
    cell = {"n": n, **{d: decisions[d] for d in DECISIONS}}
    cell["omission_rate"] = omitted / n if n else None
    interval = wilson(omitted, n)
    cell["wilson95"] = list(interval) if interval else None
    if population is not None:
        cell["population"] = population
    return cell


def aggregate(
    sample: Sequence[Mapping], reviews: Mapping[str, Mapping], counts: Mapping
) -> dict:
    """Counts, rates and Wilson intervals by facet, stratum and facet group.

    A facet's weighted rate weights each sampled stratum's rate by its population; an
    unsampled stratum is reported as uncovered, never imputed. No keys are returned.
    """
    cells: dict[tuple[str, str], Counter] = {}
    checks: Counter = Counter()
    reviewed_by: Counter = Counter()
    for item in sample:
        review = reviews.get(item["item_id"])
        if review is None:
            continue
        cells.setdefault((item["facet"], item["stratum"]), Counter())[
            review["decision"]
        ] += 1
        reviewed_by[review["review_type"]] += 1
        if item["stratum"] == "labeled_non_present":
            checks[review["existing_status_check"]] += 1
    facets = {}
    for facet in sorted({i["facet"] for i in sample}):
        strata = {}
        weighted, covered, uncovered = 0.0, 0, 0
        for stratum in STRATA:
            pop = counts[facet][stratum]
            decisions = cells.get((facet, stratum), Counter())
            strata[stratum] = _cell(decisions, pop)
            rate = strata[stratum]["omission_rate"]
            if rate is None:
                uncovered += pop
            else:
                weighted += rate * pop
                covered += pop
        facets[facet] = {
            "group": "limited" if facet in LIMITED_FACETS else "audited",
            "strata": strata,
            "weighted_rate_covered": weighted / covered if covered else None,
            "estimated_omissions_covered": round(weighted),
            "covered_population": covered,
            "uncovered_population": uncovered,
        }
    groups = {}
    for group in ("limited", "audited"):
        for stratum in STRATA:
            total = Counter()
            for (facet, s), decisions in cells.items():
                in_group = (facet in LIMITED_FACETS) == (group == "limited")
                if s == stratum and in_group:
                    total.update(decisions)
            groups[f"{group}/{stratum}"] = _cell(total)
    overall = Counter()
    for decisions in cells.values():
        overall.update(decisions)
    return {
        "pilot_id": PILOT_ID,
        "items": len(sample),
        "reviewed": sum(reviewed_by.values()),
        "reviewed_by": dict(reviewed_by),
        "overall": _cell(overall),
        "groups": groups,
        "facets": facets,
        "existing_status_checks": dict(checks),
    }
