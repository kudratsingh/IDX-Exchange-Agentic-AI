"""Small offline rule experiment for invented examples; not a production extractor."""

from __future__ import annotations

import re

from idx_agent.domain.enrichment import (
    FacetRef,
    SyntheticAnnotationCase,
    SyntheticFacetEvidence,
)

# Only explicit owner-subject claims are candidates. This intentionally has low
# coverage. A fixed set of uncertainty, negation, time and instruction cues
# triggers whole-input abstention. This is not a complete language safety guard.
_CLAUSE = re.compile(r"[^.!?;\n]+")
_UNSAFE = re.compile(
    r"\b(?:no|not|never|neither|without|except|unless|if|or|either|maybe|may|might|could|"
    r"would|will|possible|possibly|potential|proposed|planned|plans|future|former|"
    r"previously|prior|ago|sold|closed|historical|was|were|removed|demolished|"
    r"converted|conversion|renderings?|"
    r"photos?|photographs?|images?|pictures?|"
    r"concept|virtual|sketch(?:es)?|illustrations?|looking|prefer|wants?|seeks?|"
    r"desired|wish|hope|ignore|"
    r"instructions?|assistant|prompt|system)\b",
    re.IGNORECASE,
)
_CLAIM = re.compile(
    r"\b(?:(?:the|this)\s+)?(?:home|house|property)\s+(?:has|features|includes|with)\s+"
    r"(?:an?\s+)?(?P<feature>fenced\s+yard|private\s+pool|central\s+air|"
    r"bonus\s+room|garage|patio)\b(?=\s*$)",
    re.IGNORECASE,
)
_STYLE = re.compile(
    r"^\s*(?:a|the)\s+(?P<feature>craftsman[-\s]+style)\s+(?:home|house)"
    r"(?:\s+with\s+(?:a\s+)?fenced\s+yard)?\s*$",
    re.IGNORECASE,
)
_SHARED = re.compile(
    r"^\s*(?:the\s+)?(?P<pool>community\s+pool)\s+and\s+"
    r"(?P<clubhouse>clubhouse)\s+are\s+shared\s*$",
    re.IGNORECASE,
)
_GROCERY = re.compile(
    r"^\s*(?P<feature>close\s+to\s+(?:a\s+)?grocery\s+store)\s*$",
    re.IGNORECASE,
)
_RULES = {
    "fenced yard": ("exterior_lot", "fenced_yard"),
    "private pool": ("exterior_lot", "pool"),
    "garage": ("exterior_lot", "garage"),
    "patio": ("exterior_lot", "patio"),
    "central air": ("interior_systems", "central_air"),
    "bonus room": ("rooms_layout", "bonus_room"),
}


def extract_synthetic(case: SyntheticAnnotationCase) -> SyntheticAnnotationCase:
    """Produce a few explicit positive candidates from an invented input case.

    Operates only on the original string so offsets stay valid. It ignores any
    supplied reference annotations, does not log the text, and does not access a
    database, index, network, session, or provider. The synthetic marker is
    self-declared; this prototype must not be used on real remarks.
    """
    candidates = []
    if _UNSAFE.search(case.text) or "?" in case.text or '"' in case.text:
        return SyntheticAnnotationCase(
            id=case.id,
            split=case.split,
            source=case.source,
            text=case.text,
            annotations=(),
        )
    for clause in _CLAUSE.finditer(case.text):
        for match in _CLAIM.finditer(clause.group()):
            quote = match.group("feature")
            group, value = _RULES[" ".join(quote.lower().split())]
            start = clause.start() + match.start("feature")
            candidates.append(
                SyntheticFacetEvidence(
                    facet=FacetRef(group=group, value=value),
                    start=start,
                    end=start + len(quote),
                    quote=quote,
                    polarity="affirmed",
                    temporality="current",
                )
            )
        shared = _SHARED.fullmatch(clause.group())
        if shared:
            for name, value in (("pool", "community_pool"), ("clubhouse", "clubhouse")):
                start = clause.start() + shared.start(name)
                quote = shared.group(name)
                candidates.append(
                    SyntheticFacetEvidence(
                        facet=FacetRef(group="community_amenities", value=value),
                        start=start,
                        end=start + len(quote),
                        quote=quote,
                        polarity="affirmed",
                        temporality="current",
                    )
                )
        grocery = _GROCERY.fullmatch(clause.group())
        if grocery:
            start = clause.start() + grocery.start("feature")
            quote = grocery.group("feature")
            candidates.append(
                SyntheticFacetEvidence(
                    facet=FacetRef(
                        group="location_views", value="near_grocery_mentioned"
                    ),
                    start=start,
                    end=start + len(quote),
                    quote=quote,
                    polarity="affirmed",
                    temporality="current",
                )
            )
        style = _STYLE.fullmatch(clause.group())
        if style:
            quote = style.group("feature")
            start = clause.start() + style.start("feature")
            candidates.append(
                SyntheticFacetEvidence(
                    facet=FacetRef(group="style", value="craftsman"),
                    start=start,
                    end=start + len(quote),
                    quote=quote,
                    polarity="affirmed",
                    temporality="current",
                )
            )
    if len(candidates) > 100:
        raise ValueError("too many synthetic candidates")
    return SyntheticAnnotationCase(
        id=case.id,
        split=case.split,
        source=case.source,
        text=case.text,
        annotations=tuple(sorted(candidates, key=lambda item: item.start)),
    )
