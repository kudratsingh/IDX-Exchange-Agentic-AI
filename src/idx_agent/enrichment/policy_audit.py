"""Conservative candidate discovery for the offline policy audit."""

import json
import re

from idx_agent.enrichment.policy_rules import POLICY_FACETS

WOOD = re.compile(r"\b(?:wood|oak)\b", re.I)
SOLAR_HEAT = re.compile(
    r"solar[\s-]*(?:heated|heating|heat)|(?:pool|spa)[\s-]+solar|"
    r"solar[\s-]+(?:pool|spa)[\s-]+heat",
    re.I,
)


# Reconstructions of the owner's two earlier screens, from their descriptions. The
# owner's identifiers were not available, so a matching count does not prove these
# select the same rows. Windows are recorded because the solar one was found by
# searching for a definition that reproduced the reported count.
ENGINEERED_WOOD = re.compile(r"engineered[^.]{0,40}\b(?:wood|oak)\b", re.I)
EXPLICIT_WOOD = re.compile(r"hard[\s-]?wood|solid[\s-]*wood", re.I)
SOLAR_MENTION = re.compile(r"solar", re.I)
HEATING = re.compile(r"heat(?:ed|ing)", re.I)
BROAD_SOLAR_HEATING = re.compile(r"heat|pool|spa\b|water", re.I)


def screen_hardwood_engineered(remark, facets):
    """Hardwood label, engineered wood/oak, no explicit hardwood or solid wood."""
    return (
        any(facet.get("value") == "hardwood" for facet in facets)
        and bool(ENGINEERED_WOOD.search(remark))
        and not EXPLICIT_WOOD.search(remark)
    )


def _all_solar_near(remark, pattern, before, after):
    mentions = list(SOLAR_MENTION.finditer(remark))
    return bool(mentions) and all(
        pattern.search(
            remark[max(0, m.start() - before) : m.start()]
            + remark[m.end() : m.end() + after]
        )
        for m in mentions
    )


def screen_solar_heating_exact(remark, facets):
    """Solar label where every mention has heated/heating within a narrow window."""
    return any(facet.get("value") == "solar" for facet in facets) and _all_solar_near(
        remark, HEATING, 15, 10
    )


def screen_solar_heating_broad(remark, facets):
    """Superset screen, so reconciliation does not depend on one exact window."""
    return any(facet.get("value") == "solar" for facet in facets) and _all_solar_near(
        remark, BROAD_SOLAR_HEATING, 40, 40
    )


def categories(remark, facets):
    values = {facet.get("value") for facet in facets}
    found = []
    # Inventory every non-diagnostic row carrying any policy-affected facet. Narrow
    # signals are retained as triage hints, not treated as exhaustive discovery.
    found.extend(f"{facet}_label" for facet in POLICY_FACETS if facet in values)
    if "hardwood" in values and "engineer" in remark.lower() and WOOD.search(remark):
        found.append("engineered_wood")
    if "solar" in values and SOLAR_HEAT.search(remark):
        found.append("solar_heating")
    return found


def candidates(db):
    for seq, key, remark, encoded, origin in db.execute(
        "SELECT i.sequence,i.listing_key,i.remark,r.facets,o.extractor "
        "FROM inputs i JOIN results r USING(sequence) "
        "JOIN result_origins o USING(sequence) "
        "WHERE r.diagnostic_count=0 ORDER BY i.sequence"
    ):
        facets = json.loads(encoded)
        found = categories(remark, facets)
        if found:
            yield {
                "sequence": seq,
                "listing_key": key,
                "origin": origin,
                "remark": remark,
                "stored_facets": facets,
                "categories": found,
            }
