"""Build private policy-audit dispositions from per-label review outcomes.

Each in-scope label records how it was decided; corrections become remove/add
changes. Stored results are never mutated, and unresolved rows apply nothing.
"""

import re
from typing import NamedTuple

from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION

MENTIONS = {
    "hardwood": r"hard[\s-]?wood|solid[\s-]+\w+|\bwood\b|\boak\b|\bfloor\w*",
    "solar": r"solar",
    "adu": r"\badus?\b|\bjadu\b|accessory dwelling|casita|guest|in-?law|cottage",
    "patio": r"patio|balcon\w+|terrace|courtyard|outdoor",
    "mountain_view": r"mountain\w*|\bviews?\b|vistas?|hill\w*",
    "water_view": r"\bviews?\b|vistas?|waterfront|ocean|\blake\b|\bwater\b",
    "open_plan": r"\bopen\w*|flow\w*|bright|airy",
    "bonus_room": r"bonus|loft|game\s*room|media\s*room|flex\w*",
    "walk_in_closet": r"walk[\s-]*in|closet\w*",
    "pool": r"\bpools?\b|spool|\bspa\b",
    "community_pool": r"\bpools?\b|spool|\bspa\b",
    "gated_community": r"\bgate\w*|guard\w*|secur\w+",
    "clubhouse": r"club\w*",
    "fitness_center": r"fitness|gym|exercise|workout",
    "garage": r"garage|carport|parking",
    "stainless_appliances": r"stainless|appliance\w*",
    "condominium": r"condo\w*|townho\w+",
    "single_level": r"single[\s-]+(?:story|level)|one[\s-]+story|\blevel\b",
    "near_transit_mentioned": r"transit|metro|station|\bbus\b|train|freeway",
    "near_grocery_mentioned": r"grocer\w*|supermarket|market|shopping",
}

POLICY_VERSION = "v3"
CODE_TARGETS = {
    "S": ("uncertain", "unspecified"),
    "H": ("uncertain", "planned"),
    "P": ("affirmed", "planned"),
    "C": ("affirmed", "current"),
    "N": ("negated", "current"),
}


class LabelOutcome(NamedTuple):
    """One decision for one stored label; `target` is (polarity, temporality)."""

    label: dict
    action: str  # keep | remove | retag | unresolved
    method: str  # rule | read | prior_read
    rule: str | None
    reason: str
    target: tuple[str, str] | None = None
    evidence: str | None = None


def evidence_for(remark, value):
    """Return an exact source excerpt; a removal cites what the remark does say."""
    pattern = MENTIONS.get(value)
    match = re.search(pattern, remark, re.I) if pattern else None
    if match is None:
        return remark[:40]
    return remark[max(0, match.start() - 25) : match.end() + 25]


def read_outcome(label, code, note=""):
    """Translate one reader's decision code into a label outcome."""
    if code == "K":
        return LabelOutcome(label, "keep", "read", None, "Read and supported.")
    if code == "O":
        reason = "Read: evidence is insufficient under the approved policy."
        return LabelOutcome(label, "remove", "read", None, reason)
    if code == "U":
        reason = f"Unresolved after reading: {note or 'no note'}"
        return LabelOutcome(label, "unresolved", "read", None, reason)
    if code in CODE_TARGETS:
        target = CODE_TARGETS[code]
        if target == (label["polarity"], label["temporality"]):
            return LabelOutcome(label, "keep", "read", None, "Read and supported.")
        reason = "Read: polarity or temporality corrected under the approved policy."
        return LabelOutcome(label, "retag", "read", None, reason, target)
    raise ValueError(f"invalid decision code: {code}")


def rule_outcome(label, triaged):
    """Translate a deterministic triage result into a label outcome."""
    if triaged.outcome == "support":
        reason = f"Rule {triaged.rule}: evidence supports the label."
        return LabelOutcome(
            label, "keep", "rule", triaged.rule, reason, None, triaged.quote
        )
    if triaged.outcome == "omit":
        reason = f"Rule {triaged.rule}: required evidence is absent."
        return LabelOutcome(label, "remove", "rule", triaged.rule, reason)
    if triaged.outcome == "retemporal":
        reason = f"Rule {triaged.rule}: possibility without stated intent."
        return LabelOutcome(
            label, "retag", "rule", triaged.rule, reason, ("uncertain", "unspecified")
        )
    raise ValueError(f"rule did not decide this label: {triaged.rule}")


def label_review(outcome, remark):
    label = outcome.label
    is_rule = outcome.method == "rule"
    return {
        "value": label["value"],
        "polarity": label["polarity"],
        "temporality": label["temporality"],
        "action": outcome.action,
        "method": outcome.method,
        "rule": outcome.rule,
        "rule_version": POLICY_RULES_VERSION if is_rule else None,
        "evidence": outcome.evidence or evidence_for(remark, label["value"]),
        # A rule records the text it matched. Otherwise this is an automatic locator
        # near a relevant word, not a quotation the reader cited.
        "evidence_source": "rule_match"
        if is_rule and outcome.evidence
        else "auto_locator",
        "target": list(outcome.target) if outcome.target else None,
    }


def review_mode(outcomes):
    """Distinguish rule-processed from individually reviewed records."""
    methods = {outcome.method == "rule" for outcome in outcomes}
    if methods == {True}:
        return "rule_processed"
    if methods == {False}:
        return "individually_reviewed"
    return "mixed"


def build_decision(case, outcomes, base_changes=(), base_reason=None, history=None):
    """Combine label outcomes into one disposition, preserving earlier history."""
    changes = list(base_changes)
    remaining = list(case["stored_facets"])
    additions = []
    # Remove first, then add retag targets, so the result does not depend on order.
    for number, outcome in enumerate(outcomes, 1):
        if outcome.action in ("keep", "unresolved"):
            continue
        if outcome.action not in ("remove", "retag"):
            raise ValueError(f"invalid label action: {outcome.action}")
        label = outcome.label
        quote = outcome.evidence if outcome.evidence else None
        if not quote or quote not in case["remark"]:
            quote = evidence_for(case["remark"], label["value"])
        reason = f"{outcome.reason} Omission does not assert absence. (label {number})"
        changes.append(
            {
                "operation": "remove",
                "original": label,
                "corrected_annotation": None,
                "evidence_quote": quote,
                "reason": reason,
            }
        )
        remaining.remove(label)
        if outcome.action == "retag":
            polarity, temporality = outcome.target
            annotation = dict(label, polarity=polarity, temporality=temporality)
            additions.append((annotation, quote, f"{outcome.reason} (label {number})"))
    present = remaining + [
        change["corrected_annotation"]
        for change in changes
        if change["operation"] == "add"
    ]
    for annotation, quote, reason in additions:
        if annotation in present:
            continue
        present.append(annotation)
        changes.append(
            {
                "operation": "add",
                "original": None,
                "corrected_annotation": annotation,
                "evidence_quote": quote,
                "reason": reason,
            }
        )
    if any(outcome.action == "unresolved" for outcome in outcomes):
        status = "unresolved"
        reason = "; ".join(o.reason for o in outcomes if o.action == "unresolved")
    elif changes:
        status = "corrected"
        reason = (
            base_reason
            or "; ".join(
                sorted({o.reason for o in outcomes if o.action in ("remove", "retag")})
            )
            or "Earlier additions retained after re-reading."
        )
    else:
        status = "accepted_unchanged"
        reason = (
            base_reason or "All in-scope labels supported under the approved policy."
        )
    decision = {
        "sequence": case["sequence"],
        "listing_key": case["listing_key"],
        "origin": case["origin"],
        "status": status,
        "reason": reason,
        "changes": changes,
        "label_reviews": [
            label_review(outcome, case["remark"]) for outcome in outcomes
        ],
        "policy_version": POLICY_VERSION,
        "review_mode": review_mode(outcomes),
        "semantic_reviewed": bool(outcomes)
        and all(o.method in ("read", "prior_read") for o in outcomes),
    }
    if history:
        decision["correction_history"] = [history]
    return decision
