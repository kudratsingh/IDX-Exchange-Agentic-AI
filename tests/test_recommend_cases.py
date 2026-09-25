"""Checks for evals/cases/recommendations.yaml (WO-011): no model, db, or provider.

Each `price_check_exact` literal is recomputed by comps.reference_price_check on the
generator's sold rows, each `ranked_keys` one by the hashing index of its active rows
(requirement 12); ci cases then use the runner and real tool body, only SQL replaced.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from evals import run as runner

from idx_agent.db import asof as db_asof
from idx_agent.db import comps as db_comps
from idx_agent.db import listings as db_listings
from idx_agent.db import pool as db_pool
from idx_agent.db.listings import SearchOutcome
from idx_agent.domain import comps
from idx_agent.domain.asof import AsOfDates
from idx_agent.domain.fieldmap import to_listing
from idx_agent.domain.market import PRICE_FLOOR
from idx_agent.domain.models import (
    Clarification,
    CompEvidence,
    PropertySearchFilters,
    RecommendRequest,
)
from idx_agent.safety.columns import AGENT_CONTACT

pytest.importorskip("numpy")

from idx_agent.semantic.index import load_index, rank  # noqa: E402
from idx_agent.semantic.neighbors import rank_neighbors  # noqa: E402
from idx_agent.semantic.query import MAX_RANKED_KEYS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = ROOT / "evals" / "cases" / "recommendations.yaml"
CATEGORY = "recommendations"
TOOL = "recommend"
# The words WO-010's cases rank on; the WO-011 remarks avoid every one of them.
WO010_WORDS = (
    "mid-century", "condo", "views", "gym", "yard", "schools", "fixer", "cottage",
    "cafes", "canyon", "rooftop", "garden", "pool", "entertaining", "cul-de-sac",
    "walnut", "quiet", "bright", "modern", "cozy", "sunny", "patio",
)  # fmt: skip
BATH_AND_COUNTY = ("LM_Dec_3", "BathroomsTotalInteger", "CountyOrParish")


def _module(name: str, path: Path) -> ModuleType:
    """Import a file under tests/ by path (the folder is no package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _module("make_synthetic", ROOT / "tests" / "fixtures" / "make_synthetic.py")
FIXTURE = _module("semantic_fixture", ROOT / "tests" / "semantic_fixture.py")
ACTIVE = GEN.active_rows()
BY_KEY = {int(r["L_ListingID"]): r for r in ACTIVE}
AS_OF = AsOfDates(sold=GEN.SOLD_ASOF, active=GEN.ACTIVE_ASOF.date())
WINDOW = comps.comps_window(AS_OF)


def _sold_rows() -> list[dict[str, Any]]:
    """Every sold row the generator writes, in file order (active rows draw first)."""
    make = GEN.Maker()
    GEN.active_groups(make)
    return [row for _, rows in GEN.sold_groups(make) for row in rows]


SOLD = _sold_rows()


def _load() -> tuple[list[runner.Case], list[runner.LoadError]]:
    """Load only recommendations.yaml, through the runner's own loader."""
    cases, errors = runner.load_cases(CASES_FILE.parent)
    mine = [c for c in cases if c.source == CASES_FILE.name]
    return mine, [e for e in errors if e.source == CASES_FILE.name]


CASES, LOAD_ERRORS = _load()
CI = [c for c in CASES if c.suite == "ci"]
LOCAL = [c for c in CASES if c.suite == "local"]
PRICE = [c for c in CI if c.check == "price_check_exact"]
RANKED = [c for c in CI if c.check == "ranked_keys"]
CLARIFY = [c for c in CI if c.check == "clarification"]
BY_ID = {c.id: c for c in CASES}


# --- the Python reference ------------------------------------------------------------


def _close(row: dict[str, Any]) -> date | None:
    """The close date as the generated close_date_d column reads it (None if bad)."""
    value = row["CloseDate"]
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def comp_sales(subject: comps.CompSubject, level: str) -> list[tuple[float, float]]:
    """(close price, area) of the comps at one level: WO-008's exclusions, then the
    subtype and both bands (in the WHERE, so before the duplicate collapse), then one
    sale per ListingKey (latest close, higher close price, higher list price)."""
    kept: dict[Any, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    keyless = []
    for row in SOLD:
        close = _close(row)
        if level == "city":
            in_place = row["City"] == subject.city
        else:
            in_place = str(row["PostalCode"] or "").startswith(subject.postal_code)
        if not in_place or row["PropertySubType"] != subject.subtype or close is None:
            continue
        if not WINDOW.start <= close <= WINDOW.end or close > AS_OF.active:
            continue
        if row["PurchaseContractDate"] and close < row["PurchaseContractDate"]:
            continue
        if min(row["ClosePrice"], row["ListPrice"]) < PRICE_FLOOR:
            continue
        if not comps.in_bands(subject, row["LivingArea"], row["BedroomsTotal"]):
            continue
        if row["ListingKey"] is None:
            keyless.append(row)
            continue
        order = (close, row["ClosePrice"], row["ListPrice"])
        if row["ListingKey"] not in kept or order > kept[row["ListingKey"]][0]:
            kept[row["ListingKey"]] = (order, row)
    rows = [row for _, row in kept.values()] + keyless
    return [(row["ClosePrice"], row["LivingArea"]) for row in rows]


def subject_of(key: int) -> comps.CompSubject:
    """The comps subject of a fixture listing, as the tool builds it."""
    subject = comps.subject_from_listing(to_listing(BY_KEY[key]))
    assert isinstance(subject, comps.CompSubject), key
    return subject


def reference_evidence(key: int) -> CompEvidence:
    """The listing's price check by the reference: ZIP comps, city comps if short."""
    subject = subject_of(key)
    return comps.reference_price_check(
        comp_sales(subject, "postal_code"), subject, comp_sales(subject, "city")
    )


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The CI fixture index, loaded as the tool loads it."""
    path = FIXTURE.build_fixture_index(tmp_path_factory.mktemp("index"))
    return load_index(path, FIXTURE.TEST_MODEL, FIXTURE.FIXTURE_DIMS)


def reference_keys(index: Any, key: int, k: int) -> list[int]:
    """The top k neighbours: the subject's stored vector ranked by WO-010's `rank`
    under the same city, subtype, and price band, the subject removed. Every fixture
    row is active, so SQL drops none."""
    row = BY_KEY[key]
    low, high = comps.price_band(row["L_SystemPrice"])
    filters = PropertySearchFilters(
        city=row["L_City"],
        property_subtype=row["L_Type_"],
        min_price=low,
        max_price=high,
    )
    vector = index.vectors[list(index.keys).index(key)]
    ranked = rank(index, vector, filters, MAX_RANKED_KEYS + 1)
    return [k_ for k_, _ in ranked if k_ != key][:k]


def _request(case: runner.Case) -> RecommendRequest:
    request = RecommendRequest.from_input(case.input_filters or {})
    assert isinstance(request, RecommendRequest), case.id
    return request


def _plain(value: Any) -> Any:
    return runner._plain(value)


# --- the case file ---------------------------------------------------------------


def test_file_loads_with_no_errors() -> None:
    assert LOAD_ERRORS == []
    assert all(c.id.startswith("recommendations-") for c in CASES)
    assert {c.category for c in CASES} == {CATEGORY}
    assert {c.tool for c in CASES} == {TOOL}
    # About 14 ci cases and the WO's 5 phrasing cases, each with the user's words.
    assert len(CI) >= 14 and len(PRICE) >= 6 and len(RANKED) >= 2
    assert len(LOCAL) == 5
    assert all(c.input and c.check == "filters_subset" for c in LOCAL)


def test_fixture_bound_cases_are_marked_fixture_only() -> None:
    """Every case that reaches the tool names fixture keys; validation cases and the
    phrasing cases hold anywhere."""
    fixture = {c.id for c in CASES if c.database == "fixture"}
    assert fixture == {c.id for c in CI if c.check != "clarification"}
    assert all(c.database == "any" for c in CLARIFY + LOCAL)


def test_the_generator_holds_the_recommend_rows() -> None:
    group = [r for r in ACTIVE if 9130001 <= int(r["L_ListingID"]) <= 9139999]
    assert [int(r["L_ListingID"]) for r in group] == [k for k, *_ in GEN.RECOMMEND]
    assert {r["L_City"] for r in group} == {"Monrovia", "Duarte"}
    assert all(int(r["L_DisplayId"]) == int(r["L_ListingID"]) + 400_000 for r in group)
    # Older than the as-of row, so neither as-of date moves; appended last.
    assert all(r["ModificationTimestamp"] < GEN.ACTIVE_ASOF for r in group)
    assert ACTIVE[-len(group) :] == group and len(ACTIVE) == 88
    bradbury = [r for r in SOLD if r["City"] == "Bradbury"]
    assert SOLD[-len(bradbury) :] == bradbury and len(bradbury) == 4
    assert max(c for r in SOLD if (c := _close(r)) and c <= AS_OF.active) == AS_OF.sold


def test_the_remarks_avoid_the_semantic_case_words() -> None:
    for key, *_, remarks in GEN.RECOMMEND:
        found = [w for w in WO010_WORDS if w in remarks.lower()]
        assert found == [], key


@pytest.mark.parametrize("case", PRICE, ids=lambda c: c.id)
def test_price_check_literals_match_the_reference(
    case: runner.Case, fixture_index: Any
) -> None:
    """Requirement 12: each hand-computed field equals the Python reference, for the
    subject and, in rank order, for every recommended listing."""
    request = _request(case)
    key = int(request.listing_key or 0)
    derived = reference_evidence(key).model_dump(mode="json")
    for field, expected in case.expect["subject"].items():
        assert _plain(expected) == derived[field], f"{case.id}: subject {field}"
    if "ranks" in case.expect:
        keys = reference_keys(fixture_index, key, request.k)
        assert len(keys) == len(case.expect["ranks"]), case.id
        for rank_no, fields in case.expect["ranks"].items():
            got = reference_evidence(keys[rank_no - 1]).model_dump(mode="json")
            for field, expected in fields.items():
                assert _plain(expected) == got[field], f"{case.id}: {rank_no} {field}"


@pytest.mark.parametrize("case", RANKED, ids=lambda c: c.id)
def test_ranked_keys_literals_match_the_ranking(
    case: runner.Case, fixture_index: Any
) -> None:
    request = _request(case)
    key = int(request.listing_key or 0)
    assert reference_keys(fixture_index, key, request.k) == case.expect["keys"]
    # WO-011's own neighbour ranking agrees with the reference built on `rank`.
    row = BY_KEY[key]
    low, high = comps.price_band(row["L_SystemPrice"])
    ranked = rank_neighbors(
        fixture_index, key, row["L_City"], row["L_Type_"], low, high, MAX_RANKED_KEYS
    )
    assert [k for k, _ in ranked][: request.k] == case.expect["keys"]


def test_the_ranked_candidates_obey_the_hard_filters() -> None:
    """Same city and subtype, inside the price band, never the subject; the single-
    family row inside the condo's price band is not the condo's candidate."""
    for case in RANKED:
        subject = BY_KEY[int(case.input_filters["listing_key"])]
        low, high = comps.price_band(subject["L_SystemPrice"])
        for key in case.expect["keys"]:
            row = BY_KEY[key]
            assert row is not subject and row["L_City"] == subject["L_City"]
            assert row["L_Type_"] == subject["L_Type_"]
            assert low <= row["L_SystemPrice"] <= high
    condo_low, condo_high = comps.price_band(BY_KEY[9130004]["L_SystemPrice"])
    single = BY_KEY[9130006]
    assert condo_low <= single["L_SystemPrice"] <= condo_high
    assert single["L_Type_"] == "SingleFamilyResidence"
    assert 9130006 not in BY_ID["recommendations-ci-006"].expect["keys"]
    # 9130005 sits exactly on the first subject's upper price edge and is kept.
    assert comps.price_band(1_020_000) == (765_000, 1_275_000)
    assert BY_KEY[9130005]["L_SystemPrice"] == 1_275_000


def test_the_band_edges_the_cases_rely_on() -> None:
    """A sale at exactly 0.8 or 1.2 times the subject's area is a comp."""
    edge = subject_of(9130002)
    assert comps.area_band(edge.living_area)[0] == 1580
    assert (915_000, 1580.0) in comp_sales(edge, "city")
    upper = subject_of(9130007)
    assert comps.area_band(upper.living_area)[1] == 1260
    assert (689_000, 1260.0) in comp_sales(upper, "city")
    # The no-subtype sale is inside the condo's bands but never counted.
    condo = subject_of(9130004)
    unknown = [r for r in SOLD if r["City"] == "Monrovia" and not r["PropertySubType"]]
    assert len(unknown) == 1
    assert comps.in_bands(condo, unknown[0]["LivingArea"], unknown[0]["BedroomsTotal"])
    assert len(comp_sales(condo, "city")) == 6


def test_the_zip_comes_first_and_the_city_only_when_it_is_short() -> None:
    """Duarte 9130008 reaches 5 at its ZIP (3 Duarte + 2 Bradbury sales), so no
    widening; 9130009 has 1 at the ZIP and 0 in the city; Monrovia's ZIP holds only
    Monrovia sales, so its ZIP and city counts agree."""
    duarte = subject_of(9130008)
    assert len(comp_sales(duarte, "postal_code")) == 5
    assert len(comp_sales(duarte, "city")) == 3
    assert reference_evidence(9130008).level == "postal_code"
    short = subject_of(9130009)
    counts = (len(comp_sales(short, "postal_code")), len(comp_sales(short, "city")))
    assert counts == (1, 0)
    assert (reference_evidence(9130009).level, reference_evidence(9130009).count) == (
        "city",
        0,
    )
    for key in (9130001, 9130002, 9130003, 9130004, 9130005, 9130007):
        subject = subject_of(key)
        zip_sales = sorted(comp_sales(subject, "postal_code"))
        assert zip_sales == sorted(comp_sales(subject, "city")), key


def _blocks() -> list[dict[str, Any]]:
    """Every expected check with a sentence, in the subject and in each rank."""
    found = []
    for case in PRICE:
        blocks = [case.expect["subject"], *case.expect.get("ranks", {}).values()]
        found += [b for b in blocks if "sentence" in b]
    return found


def _sentences() -> list[str]:
    """Every sentence the case file expects, main and range, in every block."""
    main = [b["sentence"] for b in _blocks()]
    return main + [b["range_sentence"] for b in _blocks() if b.get("range_sentence")]


def _place_names(block: dict[str, Any]) -> set[str]:
    """The block's area and its widened-from ZIP, both as the sentence writes them."""
    return {name for name in (block.get("area"), block.get("widened_from")) if name}


def test_every_expected_sentence_has_a_fixed_shape_and_no_forbidden_word() -> None:
    sentences = _sentences()
    shapes = {comps.sentence_shape(s) for s in sentences}
    assert None not in shapes
    # The fixture exercises above, below, and at the ZIP level, the middle-half
    # range, and not enough; every sufficient check here stops at its ZIP, so the
    # widened city shape is covered by tests/test_comps_math.py only.
    assert {"at", "postal_code", "range", "not_enough"} <= shapes
    for block in _blocks():
        exempt = _place_names(block)
        assert not comps.contains_forbidden(block["sentence"], exempt=exempt)
        if block.get("sufficient") is True:
            assert comps.sentence_shape(block["range_sentence"]) == "range"
    for sentence in sentences:
        if comps.sentence_shape(sentence) == "not_enough":
            assert not re.search(r"\d", sentence)


def test_the_card_pattern_rejects_every_forbidden_word() -> None:
    pattern = BY_ID["recommendations-ci-020"].expect["pattern"]
    card = (
        "Similar to 1 Placeholder Drive:\nPrice check: Listed 4% above the median "
        "price per square foot of 5 comparable sales in ZIP 91016 over the last six "
        "months. The middle half of those sales ran from $575 to $587 per square "
        "foot.\n\nSimilar 1 of 3\nPrice check: Listed 5% below x\n\nSimilar 3 of 3"
        "\nPrice check: Not enough comparable sales to check the price."
    )
    assert re.search(pattern, card)
    for word in comps.FORBIDDEN_WORDS:
        assert not re.search(pattern, f"{card} It {word.upper()} here."), word


def test_no_comps_statement_names_a_bathroom_county_or_agent_column() -> None:
    """Every statement the fixture subjects make, at both levels."""
    for key, *_ in GEN.RECOMMEND:
        for level in comps.LEVELS:
            sql, params = db_comps.build_comps_sql(
                subject_of(key), level, WINDOW, AS_OF
            )
            text = sql + " " + " ".join(map(str, params))
            assert not [c for c in (*BATH_AND_COUNTY, *AGENT_CONTACT) if c in text]


def test_the_absence_case_names_the_remarks_and_columns() -> None:
    fields = BY_ID["recommendations-ci-019"].expect["fields"]
    assert set(BATH_AND_COUNTY) <= set(fields)
    assert {f for f in fields if f in AGENT_CONTACT}
    remarks = " ".join(r for *_, r in GEN.RECOMMEND).lower()
    assert sum(f in remarks for f in fields) >= 4
    twin = BY_ID["recommendations-ci-001"]
    assert twin.input_filters == BY_ID["recommendations-ci-019"].input_filters
    assert len(twin.expect["ranks"]) == 3


@pytest.mark.parametrize("case", CLARIFY, ids=lambda c: c.id)
def test_clarification_cases_through_from_input(case: runner.Case) -> None:
    got = RecommendRequest.from_input(case.input_filters or {})
    want = case.expect["clarification"]
    assert isinstance(got, Clarification), case.id
    assert (got.field, got.reason) == (want["field"], want["reason"])


@pytest.mark.parametrize("case", LOCAL, ids=lambda c: c.id)
def test_phrasing_expectations_are_valid_requests(case: runner.Case) -> None:
    got = RecommendRequest.from_input(case.expect["filters"])
    assert isinstance(got, RecommendRequest), case.id
    dumped = got.model_dump(exclude_defaults=True)
    assert dumped == case.expect["filters"]


def test_the_file_quotes_only_invented_keys() -> None:
    text = CASES_FILE.read_text(encoding="utf-8")
    keys = {int(k) for k in re.findall(r"\b9\d{6}\b", text)}
    assert keys and all(runner.INVENTED_KEY.match(str(k)) for k in keys)
    assert all(k in BY_KEY or k == 9139999 or 9310001 <= k <= 9310099 for k in keys)
    assert 9139999 not in BY_KEY
    assert yaml.safe_load(text)


# --- the ci cases through the runner and the real tool body ----------------------


def _passes(row: dict[str, Any], filters: PropertySearchFilters) -> bool:
    """The candidate filters as the SQL applies them (every fixture row is active)."""
    checks = (
        filters.city is None or row["L_City"] == filters.city,
        filters.property_subtype is None or row["L_Type_"] == filters.property_subtype,
        filters.min_price is None or row["L_SystemPrice"] >= filters.min_price,
        filters.max_price is None or row["L_SystemPrice"] <= filters.max_price,
    )
    return all(checks)


def fake_candidates(
    filters: PropertySearchFilters, keys: list[int], conn: Any
) -> SearchOutcome:
    """fetch_candidates over the generator's rows, in reverse key order so the tool
    must keep rank order itself."""
    assert 1 <= len(keys) <= 50
    rows = [BY_KEY[k] for k in keys if k in BY_KEY and _passes(BY_KEY[k], filters)]
    listings = [to_listing(r) for r in rows]
    return SearchOutcome(sorted(listings, key=lambda x: -x.listing_key))


def _order_statistics(
    sales: list[tuple[float, float]],
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """The one or two middle price-per-sqft values and the middle half's two ends
    (0-based k and n - k - 1 with k = n // 4), as the SQL returns them."""
    values = sorted(comps._exact(p) / comps._exact(a) for p, a in sales if a >= 200)
    n = len(values)
    if n == 0:
        return (), ()
    k = n // 4
    return tuple(values[(n - 1) // 2 : n // 2 + 1]), (values[k], values[n - k - 1])


def fake_fetch_comps(
    subject: comps.CompSubject, window: Any, as_of: AsOfDates, conn: Any
) -> comps.CompsAggregate:
    """fetch_comps computed in Python: the ZIP, then the city when the ZIP is short."""
    assert as_of == AS_OF and window == WINDOW
    zip_name = f"ZIP {subject.postal_code}"
    for level in ("postal_code", "city"):
        sales = [s for s in comp_sales(subject, level) if s[1] >= 200]
        widened = zip_name if level == "city" else None
        area = subject.city if level == "city" else zip_name
        middles, ends = _order_statistics(sales)
        aggregate = comps.CompsAggregate(
            level, area, len(sales), middles, widened, ends
        )
        if not comps.needs_widening(aggregate.count):
            break
    return aggregate


def test_ci_cases_pass_through_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the SQL is replaced: validation, the fixture index the runner builds, the
    neighbour ranking, the math, the sentences, the card, and the checks are real."""
    monkeypatch.setattr(db_pool, "database_configured", lambda: True)
    monkeypatch.setattr(db_pool, "connect", lambda *a, **k: object())
    monkeypatch.setattr(db_asof, "get_asof_dates", lambda conn: AS_OF)
    monkeypatch.setattr(db_listings, "fetch_candidates", fake_candidates)
    monkeypatch.setattr(db_comps, "fetch_comps", fake_fetch_comps)
    for name in runner.SEMANTIC_ENV:
        monkeypatch.delenv(name, raising=False)
    ctx = runner.RunContext(require_database=True)
    try:
        records = [runner.run_case(case, ctx) for case in CI]
    finally:
        ctx.close()
    failed = {r["id"]: r["detail"] for r in records if r["result"] != runner.PASS}
    assert failed == {}
    assert all(name not in runner.os.environ for name in runner.SEMANTIC_ENV)
    details = " ".join(r["detail"] for r in records)
    assert not re.search(r"9\d{6}", details)
