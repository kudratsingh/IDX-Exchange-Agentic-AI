"""Conservative candidate discovery for the offline policy audit."""

import json
import re

WOOD = re.compile(r"\b(?:wood|oak)\b", re.I)
SOLAR_HEAT = re.compile(
    r"solar[\s-]*(?:heated|heating|heat)|(?:pool|spa)[\s-]+solar|"
    r"solar[\s-]+(?:pool|spa)[\s-]+heat",
    re.I,
)


def categories(remark, facets):
    values = {facet.get("value") for facet in facets}
    found = []
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
