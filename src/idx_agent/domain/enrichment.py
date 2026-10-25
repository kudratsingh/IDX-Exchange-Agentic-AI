"""Typed vocabulary references and normalized untrusted text for WO-018."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from idx_agent.enrichment.vocabulary import FACETS

MAX_REMARKS_CHARS = 16_000
MAX_NORMALIZED_CHARS = 128_000
NORMALIZER_VERSION = "remarks-normalizer-v1"


class FacetGroup(StrEnum):
    PROPERTY_TYPE = "property_type"
    STYLE = "style"
    ROOMS_LAYOUT = "rooms_layout"
    INTERIOR_SYSTEMS = "interior_systems"
    EXTERIOR_LOT = "exterior_lot"
    COMMUNITY_AMENITIES = "community_amenities"
    LOCATION_VIEWS = "location_views"
    CONDITION_SALE = "condition_sale"


class FacetRef(BaseModel):
    """A valid vocabulary reference; carries no extraction or truth assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    group: FacetGroup
    value: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @model_validator(mode="after")
    def _known_pair(self):
        if self.value not in FACETS[self.group.value]:
            raise ValueError("facet is not in this group's vocabulary")
        return self


class NormalizedRemarks(BaseModel):
    """Still untrusted text; never log it or treat it as extracted fact."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    text: str = Field(max_length=MAX_NORMALIZED_CHARS)
    normalizer_version: Literal["remarks-normalizer-v1"] = NORMALIZER_VERSION
    applied_rules: tuple[
        Literal[
            "bed_bath_label",
            "bed_count",
            "bath_count",
            "air_conditioning",
            "washer_dryer",
            "stainless_appliances",
            "vinyl_plank",
            "hardwood_context",
        ],
        ...,
    ] = ()
