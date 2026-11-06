"""Code-controlled card delivery, the pure core (WO-036 prototype; ADR-0015, proposed).

Code puts a stored card in a WhatsApp reply only when `verify_and_substitute` says so,
and only while the gateway's fail-open release handler runs (WO-036 "Architectural
blocker"). No I/O here; the twin is extensions/idx-card-delivery/verify.mjs."""

# What this does not guarantee: in OpenClaw 2026.9.5 the release handler sits on a
# fail-open hook, so a missing, timed-out or host-rejected handler lets the model's own
# text through unchanged. Tokens and prompt instructions reduce that risk; they cannot
# remove it. Only an owned send path can. Both twins read the same test vectors.

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# --- token format (letters only, so a token never shows a digit) ---

# Sixteen consonants: one letter per 4 bits. No vowel, so no word forms by chance.
ALPHABET = "bcdfghjkmnpqrstv"
REF_BYTES = 10  # 80 random bits, 20 letters
TAG_BYTES = 8  # the first 64 bits of the tag hash, 16 letters
REF_LETTERS = 2 * REF_BYTES
TAG_LETTERS = 2 * TAG_BYTES
# What a user sees if the token is ever sent raw (a skipped hook): words first, so a
# screen reader says what happened before the reference letters.
TOKEN_HEAD = "[[Listing details not shown. Please ask again. idx-card:"
TOKEN_TAIL = "]]"
# Any "idx-card" left after the whole tokens are removed is a partial or broken token.
MARKER = "idx-card"
_LETTERS = f"[{ALPHABET}]"
TOKEN_RE = re.compile(
    re.escape(TOKEN_HEAD)
    + f"({_LETTERS}{{{REF_LETTERS}}})\\.({_LETTERS}{{{TAG_LETTERS}}})"
    + re.escape(TOKEN_TAIL)
)
_REF = re.compile(f"{_LETTERS}{{{REF_LETTERS}}}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
# Host run ids (UUIDs), tool-call ids and trace ids: a bounded, quote-free charset.
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_CHANNEL = re.compile(r"[a-z]{1,16}")
# Only these four characters count as blank around tokens, in both languages.
_BLANK = re.compile(r"[ \t\r\n]*")
_DIGIT = re.compile(r"[0-9]")
MAX_TEXT_BYTES = 200_000
_SAFE_INT = 2**53 - 1

# The binding's issuing-channel enum: "wa" is a WhatsApp direct chat as the gateway
# hook derived it from host fields; "none" is anything else (refused by the server).
CHANNEL_WA = "wa"
CHANNEL_NONE = "none"
BINDING_ARG = "idx_delivery"
BINDING_VERSION = 1
RECORD_VERSION = 1

# --- fixed texts (no digits: they reach the user when a card cannot be delivered) ---

CARD_NOT_DELIVERED_LINE = (
    "I couldn't send those listing details safely this time. Please ask again."
)
CHANNEL_REFUSAL = "Listing cards are sent on WhatsApp only for now."
STORE_REFUSAL = (
    "I couldn't prepare those listing details safely this time. Please ask again."
)
HANDLE_REFUSAL = "I no longer have that listing at hand. Please search again."
# Told to the model inside the projected result (never shown to the user).
DELIVERY_NOTE = (
    "message is a reference that the chat replaces with the stored details. Reply "
    "with message exactly as it is and nothing else. listing_key values are "
    "references for follow-up tool calls only; never show them."
)

Action = Literal["pass", "substitute", "withhold", "drop"]
RunState = Literal["open", "released", "failed"]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def letters(data: bytes) -> str:
    """`data` in ALPHABET, two letters per byte, high half first."""
    return "".join(ALPHABET[b >> 4] + ALPHABET[b & 15] for b in data)


def new_ref(random_bytes: Callable[[int], bytes] = secrets.token_bytes) -> str:
    """A fresh 20-letter reference (80 random bits)."""
    return letters(random_bytes(REF_BYTES))


def message_digest(message: str) -> str:
    """sha256 (hex) of the card text's UTF-8 bytes."""
    return _sha256(message)


def session_digest(session_key: str) -> str:
    """sha256 (hex) of a host session key; the only form of it the server sees."""
    return _sha256("idx-card-session\0" + session_key)


def file_name(ref: str) -> str:
    """The store file for `ref`: named by a hash of the ref, never the ref itself."""
    return "card-" + _sha256("idx-card-file\0" + ref) + ".json"


def card_tag(
    ref: str, trace_id: str, session: str, run: str, call: str, message_sha256: str
) -> str:
    """The token's 16-letter check: the first 64 bits of a hash over the record."""
    parts = ("idx-card", ref, trace_id, session, run, call, message_sha256)
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).digest()
    return letters(digest[:TAG_BYTES])


# --- the binding the gateway hook injects, and the stored record ---


class DeliveryBinding(BaseModel):
    """Host-derived identity of one card call; channel "none" is always refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: Literal["wa", "none"]
    session: str = ""
    run: str = ""
    call: str = ""


def parse_binding(value: Any) -> DeliveryBinding | None:
    """The binding in `value`, or None unless it is exactly one of the two shapes:
    {v, channel: "wa", session: 64 hex, run, call} or {v, channel: "none"}."""
    if not isinstance(value, dict) or value.get("v") != BINDING_VERSION:
        return None
    if type(value.get("v")) is not int:
        return None
    if value.get("channel") == CHANNEL_NONE and set(value) == {"v", "channel"}:
        return DeliveryBinding(channel=CHANNEL_NONE)
    if set(value) != {"v", "channel", "session", "run", "call"}:
        return None
    channel, session = value["channel"], value["session"]
    run, call = value["run"], value["call"]
    if channel != CHANNEL_WA or not _matches(_HEX64, session):
        return None
    if not (_matches(_SAFE_ID, run) and _matches(_SAFE_ID, call)):
        return None
    return DeliveryBinding(channel=CHANNEL_WA, session=session, run=run, call=call)


def _anchored(pattern: re.Pattern[str]) -> str:
    """A Field pattern that must match the whole value (pydantic searches)."""
    return "^" + pattern.pattern + "$"


def _matches(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


class CardRecord(BaseModel):
    """One stored card: the exact `message` a card tool rendered, bound to the host
    session digest, run and tool call that asked for it, with its expiry."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    v: Literal[1]
    ref: str = Field(pattern=_anchored(_REF))
    call: str = Field(pattern=_anchored(_SAFE_ID))
    trace_id: str = Field(pattern=_anchored(_SAFE_ID))
    session: str = Field(pattern=_anchored(_HEX64))
    run: str = Field(pattern=_anchored(_SAFE_ID))
    channel: str = Field(pattern=_anchored(_CHANNEL))
    message: str = Field(min_length=1)
    message_sha256: str = Field(pattern=_anchored(_HEX64))
    created_ms: int = Field(ge=0, le=_SAFE_INT)
    expires_ms: int = Field(ge=0, le=_SAFE_INT)

    @field_validator("v", "created_ms", "expires_ms", mode="before")
    @classmethod
    def _whole_number(cls, value: Any) -> Any:
        """An integral float is the integer: JSON.parse cannot tell 1.0 from 1, so the
        twin reads both the same way (review of #176: `v` was the one exception)."""
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @property
    def tag(self) -> str:
        parts = (self.ref, self.trace_id, self.session, self.run, self.call)
        return card_tag(*parts, self.message_sha256)

    @property
    def token(self) -> str:
        return mint_token(self)


def parse_record(value: Any) -> CardRecord | None:
    """A stored record as read (a JSON object), or None when it is not exactly one;
    the twin's parseRecord applies the same rules, so both treat it as missing. Each
    number may be written as an integral float (1.0); a boolean is never a number."""
    if not isinstance(value, dict) or type(value.get("v")) not in (int, float):
        return None
    try:
        record = CardRecord.model_validate(value)
    except ValidationError:
        return None
    if record.expires_ms <= record.created_ms:
        return None
    return record


def new_record(
    message: str,
    *,
    trace_id: str,
    binding: DeliveryBinding,
    now_ms: int,
    ttl_ms: int,
    ref: str | None = None,
) -> CardRecord:
    """The record for one card call (a "wa" binding only); ValueError otherwise."""
    if binding.channel != CHANNEL_WA:
        raise ValueError("only a WhatsApp binding issues a card")
    return CardRecord(
        v=RECORD_VERSION,
        ref=ref or new_ref(),
        call=binding.call,
        trace_id=trace_id if _matches(_SAFE_ID, trace_id) else "none",
        session=binding.session,
        run=binding.run,
        channel=CHANNEL_WA,
        message=message,
        message_sha256=message_digest(message),
        created_ms=now_ms,
        expires_ms=now_ms + ttl_ms,
    )


def mint_token(record: CardRecord) -> str:
    """The text the model relays in place of the card."""
    return TOKEN_HEAD + record.ref + "." + record.tag + TOKEN_TAIL


def parse_tokens(text: str) -> tuple[list[tuple[str, str]], str]:
    """The (ref, tag) of every whole token in order, and the text left without them."""
    found = [(m.group(1), m.group(2)) for m in TOKEN_RE.finditer(text)]
    return found, TOKEN_RE.sub("", text)


# --- what the model receives in place of the card tool's result ---


def project_for_model(
    envelope: Mapping[str, Any], token: str, handle: Callable[[int], int]
) -> dict[str, Any]:
    """The card tool's AgentResult with `message` replaced by `token` and `data`
    reduced to positions, opaque listing handles and the user's own filters."""
    return {
        "ok": envelope.get("ok") is True,
        "data": _project_data(envelope.get("data"), handle),
        "message": token,
        "warnings": list(envelope.get("warnings") or []),
        "provenance": envelope.get("provenance"),
        "pending_action": None,
        "error": envelope.get("error"),
    }


def _project_data(data: Any, handle: Callable[[int], int]) -> dict[str, Any]:
    """Keep no card value: listings become {position, listing_key: handle}."""
    if not isinstance(data, dict):
        return {"delivery_note": DELIVERY_NOTE}

    def inner(items: Any) -> list[Any]:
        rows = items if isinstance(items, list) else []
        return [r.get("listing") if isinstance(r, dict) else None for r in rows]

    def keyed(listing: Any, position: int) -> dict[str, Any]:
        key = listing.get("listing_key") if isinstance(listing, dict) else None
        if not isinstance(key, int) or isinstance(key, bool):
            return {"position": position}
        return {"position": position, "listing_key": handle(key)}

    out: dict[str, Any] = {}
    if isinstance(data.get("question"), str):  # a Clarification
        out["clarification"] = True
        for name in ("field", "reason"):
            if isinstance(data.get(name), str):
                out[name] = data[name]
    elif "listings" in data:  # SearchResult
        items = data.get("listings")
        items = items if isinstance(items, list) else []
        out["listings"] = [keyed(x, i) for i, x in enumerate(items, start=1)]
    elif "matches" in data:  # SimilarResult
        items = inner(data.get("matches"))
        out["matches"] = [keyed(x, i) for i, x in enumerate(items, start=1)]
    elif "subject" in data:  # RecommendationResult
        subject = keyed(data.get("subject"), 0)
        subject.pop("position", None)
        out["subject"] = subject
        items = inner(data.get("recommendations"))
        out["recommendations"] = [keyed(x, i) for i, x in enumerate(items, start=1)]
    elif "sample_count" in data:  # MarketStats: only the place and type asked about
        for name in ("geography", "property_subtype"):
            if name in data:
                out[name] = data[name]
    if "applied_filters" in data:
        out["applied_filters"] = data["applied_filters"]
    out["delivery_note"] = DELIVERY_NOTE
    return out


# --- the release decision (the twin: verify.mjs verifyAndSubstitute) ---


@dataclass(frozen=True)
class Decision:
    """pass: send as is. substitute: send `text` (the stored cards). withhold: send
    `text` (the fixed failure line). drop: send nothing (cancel)."""

    action: Action
    text: str | None
    reason: str
    refs: tuple[str, ...] = ()


def _withhold(reason: str) -> Decision:
    return Decision("withhold", CARD_NOT_DELIVERED_LINE, reason)


def correlation_problem(
    session: str, run: str, now_ms: int, known_runs: Sequence[Any] | None
) -> str | None:
    """Why this payload's run is not one the release side registered, or None:
    no_run_id, unknown_run, run_wrong_session or run_expired. `known_runs` are the
    runs before_tool_call registered, each {session, run, expires_ms}; None and
    non-mapping entries are skipped, as correlationProblem's `?? []` and `k?.run` do."""
    if not run:
        return "no_run_id"
    entries = known_runs or ()
    same_run = [k for k in entries if isinstance(k, Mapping) and k.get("run") == run]
    if not same_run:
        return "unknown_run"
    mine = [k for k in same_run if k.get("session") == session]
    if not mine:
        return "run_wrong_session"
    if not any(_live(k.get("expires_ms"), now_ms) for k in mine):
        return "run_expired"
    return None


def _live(expires_ms: Any, now_ms: int) -> bool:
    """now_ms is before expires_ms, a safe integer as Number.isSafeInteger reads it."""
    if isinstance(expires_ms, bool) or not isinstance(expires_ms, int | float):
        return False
    if isinstance(expires_ms, float) and not expires_ms.is_integer():
        return False
    return abs(expires_ms) <= _SAFE_INT and now_ms < expires_ms


def verify_and_substitute(
    text: str | None,
    *,
    channel: str,
    session: str,
    run: str,
    now_ms: int,
    records: Mapping[str, CardRecord],
    bound_calls: Sequence[str],
    known_runs: Sequence[Any] | None,
    run_state: RunState = "open",
    strict: bool = False,
    card_in_session: bool = False,
) -> Decision:
    """Decide one outgoing payload. Unknown correlation withholds, whatever the text.
    Substitute only when every whole token is a valid, unexpired record of this
    session and run, the text around them is blank, and they cover exactly the run's
    bound card calls. A registered run with no card call passes unless strict."""
    body = text if isinstance(text, str) else ""
    if channel != "whatsapp":
        return Decision("pass", text, "not_whatsapp")
    unknown = correlation_problem(session, run, now_ms, known_runs)
    if unknown:
        return _withhold(unknown)
    if run_state == "failed":
        return Decision("drop", None, "run_failed")
    if len(body.encode("utf-8", "surrogatepass")) > MAX_TEXT_BYTES:
        return _withhold("too_long")
    tokens, outside = parse_tokens(body)
    if MARKER in outside:
        tail = outside[outside.index(MARKER) :]
        return _withhold("malformed_token" if TOKEN_TAIL in tail else "partial_token")
    if not tokens:
        if not bound_calls:
            return _plain(text, body, strict, card_in_session)
        if run_state == "released":
            return Decision("drop", None, "after_release")
        return _withhold("unreferenced")
    if run_state == "released":
        return Decision("drop", None, "already_released")
    refs = [ref for ref, _ in tokens]
    if len(set(refs)) != len(refs):
        return _withhold("duplicate")
    if _BLANK.fullmatch(outside) is None:
        return _withhold("text_outside_tokens")
    for ref, tag in tokens:
        problem = _record_problem(records.get(ref), ref, tag, session, run, now_ms)
        if problem is None and records[ref].call not in bound_calls:
            problem = "unbound"
        if problem:
            return _withhold(problem)
    calls = [records[ref].call for ref in refs]
    if len(set(calls)) != len(calls):
        return _withhold("duplicate")
    if set(calls) != set(bound_calls):
        return _withhold("unreferenced")
    delivered = "\n\n".join(records[ref].message for ref in refs)
    return Decision("substitute", delivered, "delivered", tuple(refs))


def _record_problem(
    record: CardRecord | None, ref: str, tag: str, session: str, run: str, now: int
) -> str | None:
    """The first reason this token's record cannot be released, or None."""
    if record is None or record.ref != ref:
        return "unknown_ref"
    if record.tag != tag:
        return "tag_mismatch"
    if message_digest(record.message) != record.message_sha256:
        return "digest_mismatch"
    if record.session != session:
        return "wrong_session"
    if record.run != run:
        return "wrong_run"
    if now >= record.expires_ms:
        return "expired"
    if record.channel != CHANNEL_WA:
        return "wrong_channel"
    return None


def _plain(
    text: str | None, body: str, strict: bool, card_in_session: bool
) -> Decision:
    """A reply in a registered run with no card call: passed, unless strict mode
    withholds digits after a card in this session (an owner decision; off by
    default). An invented figure here is not blocked: a stated limitation."""
    if strict and card_in_session and _DIGIT.search(body):
        return _withhold("strict_digits")
    return Decision("pass", text, "no_tokens")


# --- the release handler's shape (the twin: plugin.mjs replyPayloadSending) ---


def payload_text(payload: Any) -> str | None:
    """The text of a reply payload: its "text" when that is a string, else None (a
    media-only, non-object or otherwise non-text payload reads as empty)."""
    if isinstance(payload, Mapping):
        text = payload.get("text")
        return text if isinstance(text, str) else None
    return None


def release(
    payload: Any,
    *,
    verify: Callable[..., Decision] = verify_and_substitute,
    **context: Any,
) -> Decision:
    """The release handler's decision for one payload: any error cancels it, as the
    gateway handler's catch returns {cancel: true}. This holds only while a handler
    runs; a host that skips it sends the payload unchanged (WO-036 blocker)."""
    try:
        decision = verify(payload_text(payload), **context)
        if not isinstance(decision, Decision):
            return Decision("drop", None, "release_error")
        return decision
    except Exception:  # noqa: BLE001 - any failure must cancel, never pass
        return Decision("drop", None, "release_error")
