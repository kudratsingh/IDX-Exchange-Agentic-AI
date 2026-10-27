"""Small offline rule experiment for invented examples; not a production extractor."""

from __future__ import annotations

import re

from idx_agent.domain.enrichment import (
    FacetRef,
    SyntheticAnnotationCase,
    SyntheticFacetEvidence,
)

# A few exact whole-input statements carry nonpositive or temporal labels. Other
# explicit positive claims use narrow patterns; unfamiliar uncertainty, negation,
# time or instruction cues trigger abstention. This is not a language safety guard.
_EXACT_NEGATED = re.compile(
    r"\s*there\s+is\s+(?P<quote>no\s+(?P<feature>pool|garage|patio))\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
_EXACT_PLANNED = re.compile(
    r"\s*a\s+(?P<quote>future\s+(?P<feature>pool|garage|patio)\s+is\s+planned)\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
_EXACT_HISTORICAL = re.compile(
    r"\s*a\s+(?P<quote>(?P<feature>pool|garage|patio)\s+stood\s+here\s+years\s+ago)\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
_EXACT_SOLAR = re.compile(
    r"\s*(?P<quote>possible\s+solar\s+panels)\s+are\s+mentioned\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
_EXACT_KITCHEN = re.compile(
    r"\s*the\s+(?P<quote>kitchen\s+might\s+be\s+updated)\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
_EXACT_REMOVED_POOL = re.compile(
    r"\s*a\s+(?P<past>former\s+pool\s+was\s+removed)\s*;\s*"
    r"(?P<now>no\s+pool\s+remains)\s*(?:[.!]\s*)?",
    re.IGNORECASE,
)
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


def _exact_nonpositive(
    case: SyntheticAnnotationCase,
) -> tuple[SyntheticFacetEvidence, ...]:
    """Recognize only a few fully bounded synthetic nonpositive/time statements."""
    for pattern, polarity, temporality in (
        (_EXACT_NEGATED, "negated", "current"),
        (_EXACT_PLANNED, "affirmed", "planned"),
        (_EXACT_HISTORICAL, "affirmed", "historical"),
    ):
        match = pattern.fullmatch(case.text)
        if match:
            return (
                SyntheticFacetEvidence(
                    facet=FacetRef(
                        group="exterior_lot", value=match.group("feature").lower()
                    ),
                    start=match.start("quote"),
                    end=match.end("quote"),
                    quote=match.group("quote"),
                    polarity=polarity,
                    temporality=temporality,
                ),
            )
    for pattern, value in (
        (_EXACT_SOLAR, "solar"),
        (_EXACT_KITCHEN, "updated_kitchen"),
    ):
        match = pattern.fullmatch(case.text)
        if match:
            return (
                SyntheticFacetEvidence(
                    facet=FacetRef(group="interior_systems", value=value),
                    start=match.start("quote"),
                    end=match.end("quote"),
                    quote=match.group("quote"),
                    polarity="uncertain",
                    temporality="unspecified",
                ),
            )
    match = _EXACT_REMOVED_POOL.fullmatch(case.text)
    if match:
        return tuple(
            SyntheticFacetEvidence(
                facet=FacetRef(group="exterior_lot", value="pool"),
                start=match.start(name),
                end=match.end(name),
                quote=match.group(name),
                polarity=polarity,
                temporality=temporality,
            )
            for name, polarity, temporality in (
                ("past", "affirmed", "historical"),
                ("now", "negated", "current"),
            )
        )
    return ()


def extract_synthetic(case: SyntheticAnnotationCase) -> SyntheticAnnotationCase:
    """Produce a few explicit candidate mentions from an invented input case.

    Operates only on the original string so offsets stay valid. It ignores any
    supplied reference annotations, does not log the text, and does not access a
    database, index, network, session, or provider. The synthetic marker is
    self-declared; this prototype must not be used on real remarks.
    """
    exact = _exact_nonpositive(case)
    if exact:
        return SyntheticAnnotationCase(
            id=case.id,
            split=case.split,
            source=case.source,
            text=case.text,
            annotations=exact,
        )
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
