"""WO-026 (v1) and WO-033 (v2) omission-risk pilots: samples, reviews and aggregates.

Pure functions over caller-supplied rows; no database, provider or file access. An
omission: the remark affirms a current feature, the store has no `present` status for
it. v2 splits fixed stratum totals by facet weight. Pilot rates are not dataset-wide.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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


# ---- WO-033 pilot v2: no-cue weighted allocation ---------------------------------

PILOT_V2_ID = "omission-pilot-v2"
SEED_V2 = "wo033-omission-20261103"
GUIDE_VERSION_V2 = "ENRICHMENT_ANNOTATION v1 + ENRICHMENT_REVIEW_POLICY v4 + v5"
# The four facets the owner named from v1's omission patterns. v1 also recorded single
# omissions in stainless_appliances and condominium; both already get +1 as limited
# facets, so they are not listed here.
V1_OMISSION_FACETS = frozenset(
    {"bonus_room", "clubhouse", "open_plan", "near_grocery_mentioned"}
)
# About 400 items: 60% no cue, 30% cue, 10% labeled non-present.
V2_STRATUM_TOTALS = {"labeled_non_present": 40, "cue": 120, "no_cue": 240}
# As in v1, labels on the other 14 facets were read by the policy audit.
V2_LABELED_FACETS = LIMITED_FACETS


def v2_weight(facet: str) -> int:
    """1, plus 1 for a limited facet, plus 1 for an owner-named v1 omission facet."""
    if facet not in ELIGIBLE_FACETS:
        raise ValueError("unknown facet")
    return 1 + (facet in LIMITED_FACETS) + (facet in V1_OMISSION_FACETS)


def apportion(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    """Split `total` in proportion to positive integer weights; the parts sum to it.

    Largest remainder: each facet gets the floor of its exact share, and the leftover
    items go one each to the largest remainders, ties broken by facet name.
    """
    if total < 0 or not weights or any(w <= 0 for w in weights.values()):
        raise ValueError("apportion needs a non-negative total and positive weights")
    whole = sum(weights.values())
    parts = {f: total * w // whole for f, w in weights.items()}
    order = sorted(weights, key=lambda f: (-(total * weights[f] % whole), f))
    for facet in order[: total - sum(parts.values())]:
        parts[facet] += 1
    return parts


def v2_allocation() -> dict[str, dict[str, int]]:
    """{facet: {stratum: target}} for pilot v2; sums to the stratum totals."""
    facets = sorted(ELIGIBLE_FACETS)
    eligible = {
        "labeled_non_present": sorted(V2_LABELED_FACETS),
        "cue": facets,
        "no_cue": facets,
    }
    out = {f: {s: 0 for s in STRATA} for f in facets}
    for stratum in STRATA:
        weights = {f: v2_weight(f) for f in eligible[stratum]}
        for facet, n in apportion(V2_STRATUM_TOTALS[stratum], weights).items():
            out[facet][stratum] = n
    return out


@dataclass(frozen=True)
class PilotDesign:
    """What distinguishes one pilot: directory, ids, seed, guide and allocation."""

    pilot_id: str
    work_order: str
    item_prefix: str
    seed: str
    guide_version: str
    allocation: Mapping[str, Mapping[str, int]]
    # v2 also excludes every (listing, facet) item already drawn in v1.
    excludes_v1_items: bool


DESIGNS = {
    "v1": PilotDesign(
        PILOT_ID,
        "WO-026",
        "op1",
        SEED,
        GUIDE_VERSION,
        {f: allocation(f) for f in sorted(ELIGIBLE_FACETS)},
        False,
    ),
    "v2": PilotDesign(
        PILOT_V2_ID,
        "WO-033",
        "op2",
        SEED_V2,
        GUIDE_VERSION_V2,
        v2_allocation(),
        True,
    ),
}


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
    rows: Iterable[tuple[str, str, Mapping[str, str]]],
    excluded: Iterable[str],
    excluded_items: Iterable[tuple[str, str]] = (),
) -> dict[tuple[str, str], list[str]]:
    """Group non-present (listing, facet) pairs by (facet, stratum), keys sorted.

    Rows are (listing_key, remark, {facet: status}); excluded keys never enter, and an
    excluded (listing_key, facet) item never enters for that facet.
    """
    skip = {str(key) for key in excluded}
    skip_items = {(str(key), facet) for key, facet in excluded_items}
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
            if (key, facet) in skip_items:
                continue
            stratum = stratum_of(facet, statuses.get(facet), remark)
            if stratum is not None:
                groups[(facet, stratum)].append(key)
    return {group: sorted(keys) for group, keys in groups.items()}


def _rank(seed: str, facet: str, stratum: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|{facet}|{stratum}|{key}".encode()).hexdigest()


def draw_sample(
    population: Mapping[tuple[str, str], Sequence[str]],
    seed: str = SEED,
    targets: Mapping[str, Mapping[str, int]] | None = None,
    prefix: str = "op1",
) -> list[dict]:
    """Take each stratum's target by seeded hash rank; a short stratum gives all.

    Targets default to the v1 allocation. Items are ordered by facet, stratum and rank
    and get opaque sequential ids with the given prefix.
    """
    items = []
    for facet, stratum in sorted(population):
        want = (targets[facet] if targets is not None else allocation(facet))[stratum]
        keys = sorted(
            population[(facet, stratum)],
            key=lambda k: (_rank(seed, facet, stratum, k), k),
        )
        for key in keys[:want]:
            items.append({"facet": facet, "stratum": stratum, "listing_key": key})
    for number, item in enumerate(items, 1):
        item["item_id"] = f"{prefix}-{number:03d}"
    return items


def sample_counts(sample: Sequence[Mapping]) -> dict:
    """{"by_stratum": {...}, "by_facet": {facet: {stratum: n}}}; counts only."""
    by_facet: dict[str, dict[str, int]] = {}
    for item in sample:
        cell = by_facet.setdefault(item["facet"], {s: 0 for s in STRATA})
        cell[item["stratum"]] += 1
    by_stratum = {s: sum(c[s] for c in by_facet.values()) for s in STRATA}
    return {"by_stratum": by_stratum, "by_facet": dict(sorted(by_facet.items()))}


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
    judgments: Sequence[Mapping],
    sample: Sequence[Mapping],
    review_type: str,
    guide_version: str = GUIDE_VERSION,
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
        if record.get("guide_version") != guide_version:
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


def weighted_rate(
    cells: Mapping[str, tuple[int, int]],
    populations: Mapping[str, int],
    z: float = 1.96,
) -> dict:
    """Weighted rate over facets ({f: (k, n)}, {f: N}); Wilson on Kish n_eff (WO-033).

    p_w = sum (N_f / N)(k_f / n_f); n_eff = N^2 / sum (N_f^2 / n_f), not rounded. A
    facet with n = 0 or N = 0 is left out, never imputed, and counted as uncovered.
    """
    covered = {
        f: (k, n) for f, (k, n) in cells.items() if n > 0 and populations.get(f, 0) > 0
    }
    total = sum(populations[f] for f in covered)
    uncovered = sum(populations.get(f, 0) for f in cells) - total
    n = sum(n for _, n in covered.values())
    if not total:
        return {
            "estimate": None,
            "wilson95": None,
            "n": n,
            "n_eff": None,
            "design_effect": None,
            "covered_population": 0,
            "uncovered_population": uncovered,
        }
    estimate = sum(populations[f] / total * k / m for f, (k, m) in covered.items())
    n_eff = total**2 / sum(populations[f] ** 2 / m for f, (_, m) in covered.items())
    return {
        "estimate": estimate,
        "wilson95": list(wilson(estimate * n_eff, n_eff, z)),
        "n": n,
        "n_eff": n_eff,
        "design_effect": n / n_eff,
        "covered_population": total,
        "uncovered_population": uncovered,
    }


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
    sample: Sequence[Mapping],
    reviews: Mapping[str, Mapping],
    counts: Mapping,
    pilot_id: str = PILOT_ID,
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
    # Per stratum: weighted across facets by population; the second figure is the
    # sensitivity bound that counts every unclear item as an omission.
    weighted = {}
    for stratum in STRATA:
        pops = {f: counts[f][stratum] for f in facets}
        strata_cells = {f: facets[f]["strata"][stratum] for f in facets}
        weighted[stratum] = {
            "omitted": weighted_rate(
                {f: (c["omitted_present"], c["n"]) for f, c in strata_cells.items()},
                pops,
            ),
            "unclear_as_omitted": weighted_rate(
                {
                    f: (c["omitted_present"] + c["unclear"], c["n"])
                    for f, c in strata_cells.items()
                },
                pops,
            ),
        }
    return {
        "pilot_id": pilot_id,
        "items": len(sample),
        "reviewed": sum(reviewed_by.values()),
        "reviewed_by": dict(reviewed_by),
        "overall": _cell(overall),
        "groups": groups,
        "facets": facets,
        "existing_status_checks": dict(checks),
        "weighted_by_stratum": weighted,
    }
