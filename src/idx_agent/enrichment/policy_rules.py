"""Deterministic triage of stored facet labels against the approved review policy.

Outcomes: support, omit, retemporal, or read when a rule cannot settle the label.
An omission means insufficient evidence, never a finding that a feature is absent.
"""

# Blind calibration showed that absence rules built on one keyword misfire on typos
# and abbreviations, and that negation and most possibility rules were unreliable.
# Those cases are deliberately routed to individual reading here.

import re
from typing import NamedTuple

# Bump whenever a rule's behaviour changes; dispositions record the version they used.
POLICY_RULES_VERSION = "2026-11-01.4"

POLICY_FACETS = (
    "hardwood",
    "solar",
    "adu",
    "patio",
    "mountain_view",
    "water_view",
    "open_plan",
    "bonus_room",
    "walk_in_closet",
    "pool",
    "community_pool",
    "gated_community",
    "clubhouse",
    "fitness_center",
)

HEDGE_BEFORE = re.compile(
    r"\b(?:no|not|without|never|could|would|might|may|can|potential\w*|possib\w*|"
    r"optional|option\s+(?:of|to|for)|imagine|envision|room\s+for|space\s+for|"
    r"plenty\s+of\s+room|ample\s+room|bring\s+your|build\w*|add(?:ing)?\s+(?:a|an|your)|"
    r"future|plans?\s+(?:for|to)|planned|proposed|lacks?|except|formerly|previously|"
    r"once|used\s+to|removed|opportunity|convert\w*)\b[^.!?;]{0,30}$",
    re.I,
)
HEDGE_AFTER = re.compile(
    r"^[^.!?;]{0,22}\b(?:potential|possib\w*|optional|ready|pre-?wired|sized|"
    r"conversion|could|would|might|may\s+be|subject\s+to|buyer\s+to|permits?|"
    r"plans|opportunity|removed|not\s+included)\b",
    re.I,
)
COMMUNAL = re.compile(
    r"\b(?:communit\w+|communal|shared|hoa|association|complex|resort|amenit\w+|"
    r"clubhouse|club|residents?|building|neighbou?rhood|nearby|near|park|rooftop|"
    r"roof deck|common|tenants?|55\+)\b",
    re.I,
)
LOOKALIKE = re.compile(
    r"\b(?:laminate|vinyl|lvp|lvt|luxury vinyl|faux|look|looking|style|tile|"
    r"porcelain|like|imitation|carpet\w*)\b",
    re.I,
)
POSSIBILITY = re.compile(
    r"\b(?:potential\w*|possib\w*|could|might|may|can|room\s+for|space\s+for|"
    r"plenty\s+of\s+room|ample\s+room|opportunit\w+|imagine|envision|bring\s+your|"
    r"buyer\s+to\s+verify|buyers?\s+to|subject\s+to|ideal\s+for|perfect\s+for|"
    r"future|convert\w*|conversion|add(?:ing)?\s+(?:a|an|your)|build(?:ing)?\s+(?:a|an|your)|"
    r"create\s+(?:a|an|your)|inquire|option\w*)\b",
    re.I,
)
PROPOSAL = re.compile(
    r"\b(?:plans?\s+(?:for|to|are|have|in\s+place)|approved|permitted\s+plans|"
    r"ready[\s-]+to[\s-]+issue|rti|proposed|in\s+progress|under\s+construction|"
    r"being\s+built|architectural\s+plans|permits?\s+(?:in|issued|approved))\b",
    re.I,
)


class Triage(NamedTuple):
    outcome: str
    rule: str
    quote: str | None


def _read(name):
    return Triage("read", f"{name}.review", None)


def _near(text, match, width=45):
    return text[max(0, match.start() - width) : match.end() + width]


def _affirmed_current(facet):
    return facet.get("polarity") == "affirmed" and facet.get("temporality") == "current"


def _hedged(text, match):
    return bool(
        HEDGE_BEFORE.search(text[max(0, match.start() - 45) : match.start()])
        or HEDGE_AFTER.search(text[match.end() : match.end() + 40])
    )


def _clean(pattern, text, guards=(), width=45):
    """Return the first unhedged match whose neighbourhood is free of guards."""
    for match in pattern.finditer(text):
        if _hedged(text, match):
            continue
        window = _near(text, match, width)
        if not any(guard.search(window) for guard in guards):
            return match
    return None


HARDWOOD_WORD = re.compile(
    r"hard[\s-]?woods?|solid[\s-]+(?:[\w-]+[\s-]+){0,2}wood|\bh/?w\b|\bhdwd\b|hardwd|harwood",
    re.I,
)
HARDWOOD_FLOOR = re.compile(
    r"(?:hard[\s-]?woods?)[\s-]+(?:[\w-]+[\s-]+){0,2}floor\w*|"
    r"floor\w*\s+(?:[\w-]+\s+){0,3}hard[\s-]?wood",
    re.I,
)
# The owner-approved list of qualifying species. Bamboo, softwoods, cork and
# unspecified parquet do not qualify. "ash" and "ipe" are matched as whole words.
SPECIES = (
    r"(?:oak|walnut|maple|hickory|cherry|mahogany|teak|acacia|pecan|ash|birch|ipe|"
    r"tigerwood)"
)
SPECIES_WORD = re.compile(rf"\b{SPECIES}\b", re.I)
SPECIES_FLOOR = re.compile(
    rf"\b{SPECIES}[\s-]+(?:(?:wood|hardwood|plank|wide-plank|parquet|herringbone|"
    r"chevron)[\s-]+){0,2}floor\w*|"
    rf"\b{SPECIES}[\s-]+parquet\b|\bfloor\w*\s+of\s+(?:[\w-]+\s+){{0,2}}{SPECIES}\b",
    re.I,
)
SPECIES_LOOKALIKE = re.compile(
    r"\b(?:laminate|vinyl|lvp|lvt|faux|imitation|look|looking|style|tile|porcelain|"
    r"engineered|finish|print)\b|wood-look",
    re.I,
)
SOLID_FLOOR = re.compile(
    r"solid[\s-]+(?:[\w-]+[\s-]+){0,2}wood[\s-]+(?:[\w-]+[\s-]+)?floor\w*", re.I
)


EXCLUDED_WOOD = re.compile(r"\b(?:bamboo|pine|fir|cedar|cork)\b", re.I)
NOT_A_FLOOR = re.compile(
    r"floorplans?\b|cabinet\w*|trim\b|doors?\b|ceiling\w*|beams?\b", re.I
)


def _floor_match(pattern, text, guards, width):
    for match in pattern.finditer(text):
        if _hedged(text, match) or NOT_A_FLOOR.search(match.group(0)):
            continue
        if re.match(r"[\s-]*plans?\b", text[match.end() : match.end() + 8], re.I):
            continue
        if not any(guard.search(_near(text, match, width)) for guard in guards):
            return match
    return None


def _hardwood(text, facet):
    if not HARDWOOD_WORD.search(text) and not SPECIES_WORD.search(text):
        return Triage("omit", "hardwood.no_qualifying_wording", None)
    if not _affirmed_current(facet):
        return _read("hardwood")
    guards = (LOOKALIKE, EXCLUDED_WOOD)
    match = _floor_match(HARDWOOD_FLOOR, text, guards, 18) or _floor_match(
        SOLID_FLOOR, text, guards, 18
    )
    if match:
        return Triage("support", "hardwood.explicit_floor", match.group(0))
    match = None
    if not HARDWOOD_FLOOR.search(text):
        match = _floor_match(
            SPECIES_FLOOR, text, (SPECIES_LOOKALIKE, EXCLUDED_WOOD), 30
        )
    if match:
        return Triage("support", "hardwood.species_floor", match.group(0))
    return _read("hardwood")


SOLAR_WORD = re.compile(r"solar", re.I)
SOLAR_NON_ELECTRIC = re.compile(
    r"solar[\s-]*(?:(?:pool|water|spa)[\s-]+)?(?:heat\w*|cover\b|blanket|curtain)|"
    r"(?:pool|spa)[\s-]+(?:\w+[\s-]+)?solar|solar[\s-]+(?:pool|spa)|"
    r"solar[\s-]+(?:tubes?|tunnels?|lights?|lighting|attic|fans?|shades?|screens?|"
    r"gate|windows?|well|pump)|solatube",
    re.I,
)
SOLAR_POWER = re.compile(
    r"(?:(?:owned|paid[\s-]*(?:off|for)?|leased|fully[\s-]+paid|purchased|included|"
    r"\d+(?:\.\d+)?[\s-]*kw)[\s-]+(?:[\w-]+[\s-]+){0,2}solar\b)|"
    r"solar[\s-]+(?:\w+[\s-]+){0,2}(?:panels?|system|power\w*|electric\w*|energy|"
    r"pv\b|array|photovoltaic|lease)|photovoltaic",
    re.I,
)


SOLAR_OTHER_USE = re.compile(
    r"solar[\s-]*(?:powered|thermal)|"
    r"solar[\w\s-]{0,25}\b(?:heats?|heating|heater|gate|attic\s+fan|well\s+pump|ready|"
    r"pre-?wired|optional|can\s+be|may\s+be)\b|"
    r"\b(?:ready|ideal|pre-?wired|wired)\s+for\s+solar",
    re.I,
)


def _solar(text, facet):
    mentions = list(SOLAR_WORD.finditer(text))
    if not mentions or not _affirmed_current(facet):
        return _read("solar")
    if any(SOLAR_NON_ELECTRIC.search(_near(text, m, 22)) for m in mentions):
        return _read("solar")
    if SOLAR_OTHER_USE.search(text):
        return _read("solar")
    match = _clean(SOLAR_POWER, text)
    if match:
        return Triage("support", "solar.electric_system", match.group(0))
    match = _clean(SOLAR_WORD, text)
    if match:
        return Triage("support", "solar.home_feature", match.group(0))
    return _read("solar")


ADU_EXPLICIT = re.compile(r"\badus?\b|\bjadu\b|accessory dwelling", re.I)


ADU_NOT_EXISTING = re.compile(
    r"zon(?:ed|ing)|eligib\w*|friendly|allow\w*|approved\s+for|to\s+be\s+built|under\s+"
    r"construction|pending|denied|prohibit\w*|not\s+permitted|neighbou?r",
    re.I,
)


def _adu(text, facet):
    if _affirmed_current(facet):
        match = _clean(ADU_EXPLICIT, text)
        if (
            match
            and not POSSIBILITY.search(_near(text, match, 40))
            and not ADU_NOT_EXISTING.search(_near(text, match, 40))
        ):
            return Triage("support", "adu.explicit_existing", match.group(0))
    return _read("adu")


PATIO = re.compile(r"patio", re.I)
PATIO_NOT_SPACE = re.compile(r"patio[\s-]+(?:door|slider|home|furniture)\w*", re.I)
PATIO_COVER = re.compile(r"patio[\s-]+cover\w*", re.I)


def _patio(text, facet):
    if not PATIO.search(text):
        return Triage("omit", "patio.no_mention", None)
    spaces = [
        m for m in PATIO.finditer(text) if not PATIO_NOT_SPACE.match(text, m.start())
    ]
    if not spaces:
        return Triage("omit", "patio.door_or_product_only", None)
    if not _affirmed_current(facet):
        return _read("patio")
    for match in spaces:
        if PATIO_COVER.match(text, match.start()):
            continue
        window = _near(text, match, 40)
        private = re.search(r"\bprivate\b", window, re.I)
        if (private or not COMMUNAL.search(window)) and not _hedged(text, match):
            return Triage("support", "patio.explicit", match.group(0))
    return _read("patio")


VIEW = r"(?:views?|vistas?|overlook\w*|views?\s+of)"
MOUNTAIN = (
    r"(?:mountains?|mtns?\.?|sierras?|peaks?|san\s+gabriels?|san\s+jacinto|"
    r"san\s+bernardinos?|santa\s+\w+\s+mountains?|mt\.?\s+\w+|mount\s+\w+)"
)
WATER = (
    r"(?:ocean|sea|pacific|lake|lakes|bay|harbou?r|river|marina|water|waters|coast\w*|"
    r"catalina|channel|lagoon|pond|creek|reservoir|waterfront)"
)


def _view_near(term):
    return re.compile(
        rf"\b{term}\b[^.!?]{{0,35}}\b{VIEW}\b|\b{VIEW}\b[^.!?]{{0,45}}\b{term}\b",
        re.I,
    )


MOUNTAIN_VIEW = _view_near(MOUNTAIN)
WATER_VIEW = _view_near(WATER)
MOUNTAIN_TERM = re.compile(
    r"\b(?:mountains?|mountaintops?|mtns?\.?|sierras?|peaks?|ridges?|ridgeline|"
    r"mt\.?|mount|san\s+gabriels?|san\s+jacinto|santa\s+\w+s|range)\b",
    re.I,
)


VIEW_PLACE = re.compile(
    r"mountain\s+view\b(?!s)|(?:ocean|lake|bay|sea|water|river)\s*views?\s+"
    r"(?:blvd|boulevard|ave|avenue|dr|drive|st|street|rd|road|way|ln|lane|ct|court|pl|place)\b|"
    r"bay\s+windows?|water\s+heater|waterfront",
    re.I,
)


def _mountain_view(text, facet):
    if not MOUNTAIN_TERM.search(text):
        return Triage("omit", "mountain_view.no_named_feature", None)
    if _affirmed_current(facet):
        match = _clean(MOUNTAIN_VIEW, text, (COMMUNAL, VIEW_PLACE), 15)
        if match:
            return Triage("support", "mountain_view.explicit", match.group(0))
    return _read("mountain_view")


def _water_view(text, facet):
    if _affirmed_current(facet):
        match = _clean(WATER_VIEW, text, (COMMUNAL, VIEW_PLACE), 15)
        if match:
            return Triage("support", "water_view.explicit", match.group(0))
    return _read("water_view")


OPEN_PLAN = re.compile(
    r"open[\s,-]+(?:and\s+)?(?:[\w-]+[\s,]+){0,3}(?:plan|concept|layout)\b|"
    r"open[\s,-]+(?:and\s+)?(?:[\w-]+[\s,]+){0,3}floor[\s-]*plan\b",
    re.I,
)
ROOM = r"(?:(?:living|family|great|dining)\s+(?:room|area|space)s?|kitchen)"
CONNECTED_ROOMS = re.compile(
    rf"\b{ROOM}\b[^.!?]{{0,60}}\b(?:flows?|flowing|opens?|connects?|connecting|adjoins?|"
    rf"seamlessly)\b[^.!?]{{0,50}}\b{ROOM}\b",
    re.I,
)
ONE_ROOM = re.compile(
    r"\b(?:kitchen|bedroom|closet|bath\w*|shower|suite|house|to)\b", re.I
)
OUTDOOR_ROOM = re.compile(
    r"\b(?:patio|yard|backyard|deck|outdoor|garage|laundry)\b", re.I
)


def _whole_home_layout(text, match):
    tail = text[match.end() : match.end() + 25]
    return not ONE_ROOM.search(match.group(0)) and not ONE_ROOM.search(
        tail.split(",")[0]
    )


def _open_plan_match(text):
    for match in OPEN_PLAN.finditer(text):
        if not _hedged(text, match) and _whole_home_layout(text, match):
            return match
    for match in CONNECTED_ROOMS.finditer(text):
        if not _hedged(text, match) and not OUTDOOR_ROOM.search(match.group(0)):
            return match
    return None


def _open_plan(text, facet):
    if _affirmed_current(facet):
        match = _open_plan_match(text)
        if match:
            return Triage("support", "open_plan.explicit", match.group(0))
    return _read("open_plan")


BONUS_NOT_ROOM = re.compile(
    r"(?:added|extra|as\s+a|nice|huge|big|great|another|the)\s+bonus\b(?!\s+(?:room|space|"
    r"area|loft|office|den|flex|game|family|living|wing))|bonus\s*[:!,.]",
    re.I,
)
BONUS_WORD = re.compile(r"bonus", re.I)


def _bonus(text, facet):
    if _affirmed_current(facet):
        for match in BONUS_WORD.finditer(text):
            if BONUS_NOT_ROOM.search(_near(text, match, 12)) or _hedged(text, match):
                continue
            if not re.search(
                r"\badu\b|guest\s+house|casita", _near(text, match, 30), re.I
            ):
                return Triage("support", "bonus_room.explicit", match.group(0))
    return _read("bonus_room")


WALK_IN_CLOSET = re.compile(
    r"walk(?:ing)?[\s-]*in[\s-]+(?:[\w-]+[\s-]+){0,2}(?:closet|wardrobe)s?|"
    r"walking[\s-]+closet|\bwics?\b|closets?\b[^.!?]{0,30}\bwalk[\s-]*ins?\b",
    re.I,
)
CLOSET_WORD = re.compile(r"closet|wardrobe|\bwics?\b", re.I)
WALK_IN_NOT_CLOSET = re.compile(
    r"walk[\s-]*(?:in|through)[\s-]+(?:[\w'’-]+[\s-]+){0,2}"
    r"(?:shower|pantry|pantries|tub|bath\w*|wine|cellar|attic|storage)\w*|"
    r"(?:butler\S*)\s+walk[\s-]*in\s+pantry",
    re.I,
)


def _walk_in(text, facet):
    if not CLOSET_WORD.search(text):
        other = WALK_IN_NOT_CLOSET.sub(" ", text)
        if re.search(r"walk[\s-]*(?:in|through)|dressing\s+room|closer", other, re.I):
            return _read("walk_in_closet")
        return Triage("omit", "walk_in_closet.no_closet_evidence", None)
    if _affirmed_current(facet):
        guard = re.compile(r"\b(?:storage|pantry|adu|guest|casita)\b", re.I)
        match = _clean(WALK_IN_CLOSET, text, (guard,), 15)
        if match:
            return Triage("support", "walk_in_closet.explicit", match.group(0))
    return _read("walk_in_closet")


POOL = re.compile(r"\bpools?\b(?![\s-]+(?:table|hall|cue|room))", re.I)
NEARBY_BEFORE = re.compile(
    r"\b(?:near|nearby|close\s+to|next\s+to|adjacent|minutes?|miles?|walk(?:ing)?\s+(?:to|distance)|"
    r"steps?\s+(?:to|from))\b[^.!?;]{0,35}$",
    re.I,
)
NEARBY_AFTER = re.compile(r"^[^.!?;]{0,25}\b(?:nearby|miles?|minutes?|away)\b", re.I)
STRONG_COMMUNITY = re.compile(
    r"\b(?:communit\w+|hoa|association|amenit\w+|complex|residents|shared|common\s+areas?|"
    r"building|55\+|gated)\b",
    re.I,
)


def _nearby(text, match):
    return bool(
        NEARBY_BEFORE.search(text[max(0, match.start() - 45) : match.start()])
        or NEARBY_AFTER.search(text[match.end() : match.end() + 30])
    )


ON_PROPERTY = re.compile(
    r"\b(?:private|own|backyard|back\s+yard|yard|in-?ground|personal|your|property|"
    r"lot|outside|outdoors?|oasis|sparkling|waterfall|entertain\w*|grounds|infinity|"
    r"lawn|courtyard|pool\s+home|solar|heated|salt\w*|pebble\w*|custom|sun\s*shelf)\b",
    re.I,
)
COMMUNITY_CONTEXT = re.compile(
    r"\b(?:communit\w+|hoa|association|amenit\w+|club\s?house|complex|residents|"
    r"resort-style\s+amenities|tennis|fitness|gym|greenbelts?|common\s+areas?|shared|"
    r"55\+|sports?\s+courts?|golf|pickleball|parks?|trails?|building|condo\w*|"
    r"townho\w+|sauna|lobby|concierge)\b",
    re.I,
)
HOME_POOL_WORDS = re.compile(r"\b(?:backyard|back\s+yard|private|your\s+own)\b", re.I)


def _pool(text, facet):
    if not POOL.search(text):
        return _read("pool")
    if not _affirmed_current(facet):
        # The one possibility rule that held up in blind calibration.
        if facet.get("polarity") == "uncertain":
            windows = [_near(text, m, 70) for m in POOL.finditer(text)]
            close = [_near(text, m, 40) for m in POOL.finditer(text)]
            temporality = facet.get("temporality")
            if not any(PROPOSAL.search(w) for w in windows) and any(
                POSSIBILITY.search(w) for w in close
            ):
                if temporality == "unspecified":
                    return Triage("support", "pool.possibility_unspecified", None)
                if temporality == "planned":
                    return Triage("retemporal", "pool.possibility_is_unspecified", None)
        return _read("pool")
    for match in POOL.finditer(text):
        window = _near(text, match, 50)
        if _hedged(text, match) or COMMUNITY_CONTEXT.search(window):
            continue
        if ON_PROPERTY.search(window):
            return Triage("support", "pool.on_property", match.group(0))
    return _read("pool")


def _community_pool(text, facet):
    if not POOL.search(text) or not _affirmed_current(facet):
        return _read("community_pool")
    for match in POOL.finditer(text):
        window = _near(text, match, 70)
        if (
            not _hedged(text, match)
            and not _nearby(text, match)
            and STRONG_COMMUNITY.search(window)
            and not HOME_POOL_WORDS.search(window)
        ):
            return Triage("support", "community_pool.community_context", match.group(0))
    return _read("community_pool")


GATED = re.compile(
    r"(?:guard\w*[\s-]*)?gated?[\s-]+(?:[\w-]+[\s-]+){0,3}"
    r"(?:communit\w+|enclave|neighbou?rhood|development|subdivision|tract|village|"
    r"resort|country\s+club|golf|townho\w+|condo\w*|hoa)|"
    r"\bguard\w*[\s-]*gated?|(?:communit\w+|neighbou?rhood|enclave)\s+(?:is\s+)?"
    r"(?:guard\w*[\s-]*)?gated|(?:behind|within|inside)\s+the\s+(?:[\w-]+\s+){0,2}gates\s+of",
    re.I,
)
GATE_SIGNAL = re.compile(r"\bgate|\bguard", re.I)
GATE_PROPERTY = re.compile(
    r"\b(?:property|lot|home|yard|pool|estate|residence|driveway|entry|parking|garage)\b",
    re.I,
)
GATE_NEGATED_BEFORE = re.compile(r"\b(?:non|un)[\s-]*$", re.I)


def _gated_match(text):
    for match in GATED.finditer(text):
        if _hedged(text, match) or _nearby(text, match):
            continue
        if GATE_PROPERTY.search(match.group(0)):
            continue
        if GATE_NEGATED_BEFORE.search(text[max(0, match.start() - 4) : match.start()]):
            continue
        if not GATE_NON_COMMUNITY.search(_near(text, match, 12)):
            return match
    return None


GATE_NON_COMMUNITY = re.compile(r"\b(?:parking|garage|building|driveway|lobby)\b", re.I)


def _gated(text, facet):
    if not GATE_SIGNAL.search(text):
        return Triage("omit", "gated_community.no_mention", None)
    if _affirmed_current(facet):
        match = _gated_match(text)
        if match:
            return Triage("support", "gated_community.explicit", match.group(0))
    return _read("gated_community")


MEMBERSHIP = re.compile(r"member\w*|country\s+club|golf\s+club", re.I)
CLUBHOUSE = re.compile(r"club\s?house", re.I)
FITNESS = re.compile(r"fitness|gym|exercise|workout|weight\s+room", re.I)
HOME_AMENITY = re.compile(
    r"\b(?:home\s+gym|your\s+own|private|in-?home|garage|primary)\b", re.I
)


def _amenity(text, facet, signal, name):
    if not _affirmed_current(facet):
        return _read(name)
    for match in signal.finditer(text):
        window = _near(text, match, 70)
        if (
            MEMBERSHIP.search(window)
            or _hedged(text, match)
            or _nearby(text, match)
            or HOME_AMENITY.search(_near(text, match, 25))
        ):
            continue
        if STRONG_COMMUNITY.search(window):
            return Triage("support", f"{name}.community_explicit", match.group(0))
    return _read(name)


def triage(text, facet):
    """Classify one stored facet label against the approved policy."""
    value = facet["value"]
    if value == "hardwood":
        return _hardwood(text, facet)
    if value == "solar":
        return _solar(text, facet)
    if value == "adu":
        return _adu(text, facet)
    if value == "patio":
        return _patio(text, facet)
    if value == "mountain_view":
        return _mountain_view(text, facet)
    if value == "water_view":
        return _water_view(text, facet)
    if value == "open_plan":
        return _open_plan(text, facet)
    if value == "bonus_room":
        return _bonus(text, facet)
    if value == "walk_in_closet":
        return _walk_in(text, facet)
    if value == "pool":
        return _pool(text, facet)
    if value == "community_pool":
        return _community_pool(text, facet)
    if value == "gated_community":
        return _gated(text, facet)
    if value == "clubhouse":
        return _amenity(text, facet, CLUBHOUSE, value)
    if value == "fitness_center":
        return _amenity(text, facet, FITNESS, value)
    raise ValueError(f"facet outside policy audit scope: {value}")
