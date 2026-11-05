"""Model-free relay check for one paid acceptance turn (P1-4 follow-up, 2026-11-05).

Give `--message`/`--reply` files, or `--transcript` with `--trace-id`. Prints counts,
card positions and units only (`--values` adds numbers). Exit 0 pass, 1 fail, 2
unavailable; `--require-exact` (procedure 1 after Layer 2) fails any non-exact pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from idx_agent.channels.relay_check import RelayCheck, check_card_relay  # noqa: E402

STRUCTURED_PREFIX = "structuredContent:\n"


class TranscriptError(ValueError):
    """The transcript does not hold one usable tool result and reply for the trace."""


def _blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    content = (record.get("message") or {}).get("content")
    return (
        [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    )


def _role(record: dict[str, Any]) -> str:
    return str((record.get("message") or {}).get("role") or "")


def _names_trace(record: dict[str, Any], trace_id: str) -> bool:
    details = (record.get("message") or {}).get("details") or {}
    provenance = ((details.get("structuredContent") or {}).get("provenance")) or {}
    if provenance.get("trace_id") == trace_id:
        return True
    return any(trace_id in str(b.get("text") or "") for b in _blocks(record))


def _block_message(text: str) -> str | None:
    body = (
        text[len(STRUCTURED_PREFIX) :] if text.startswith(STRUCTURED_PREFIX) else text
    )
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    message = parsed.get("message") if isinstance(parsed, dict) else None
    return message if isinstance(message, str) else None


def from_transcript(lines: list[str], trace_id: str) -> tuple[str, str, int]:
    """(message, reply, model-visible tool blocks) for `trace_id`."""
    records = [json.loads(line) for line in lines if line.strip()]
    hits = [
        i
        for i, r in enumerate(records)
        if _role(r) == "toolResult" and _names_trace(r, trace_id)
    ]
    if len(hits) != 1:
        raise TranscriptError(f"{len(hits)} tool results name the trace (need 1)")
    tool = records[hits[0]]
    texts = [str(b.get("text") or "") for b in _blocks(tool) if b.get("type") == "text"]
    messages = {m for m in (_block_message(t) for t in texts) if m is not None}
    if len(messages) != 1:
        raise TranscriptError(f"{len(messages)} distinct messages in the tool blocks")
    for record in records[hits[0] + 1 :]:
        if _role(record) != "assistant":
            continue
        blocks = _blocks(record)
        if any(b.get("type") == "toolCall" for b in blocks):
            continue
        text = "\n".join(
            str(b.get("text") or "") for b in blocks if b.get("type") == "text"
        )
        if text.strip():
            return messages.pop(), text, len(texts)
    raise TranscriptError("no assistant reply after the tool result")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def report(result: RelayCheck, message: str, reply: str, show_values: bool) -> str:
    s = result.summary()
    first = s["first_mismatch"]
    where = "-" if first is None else "card {card} {unit}".format(**first)
    lines = [
        f"status={s['status']} reason={s['reason']} "
        f"message_numbers={s['message_numbers']} reply_numbers={s['reply_numbers']} "
        f"mismatches={s['mismatch_count']} first_mismatch={where!r} "
        f"reply_only_values={s['reply_only_count']} extra_digits={s['extra_digits']} "
        f"message_sha256={_digest(message)} reply_sha256={_digest(reply)}"
    ]
    for m in result.mismatches:
        line = f"  card={m.card} unit={m.unit}"
        line += f" in_message={m.expected is not None} in_reply={m.got is not None}"
        if show_values:
            line += f" expected={m.expected.value if m.expected else '-'}"
            line += f" reply={m.got.value if m.got else '-'}"
        lines.append(line)
    if show_values and result.reply_only:
        lines.append("  reply_only=" + ",".join(str(v) for v in result.reply_only))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--message", type=Path)
    parser.add_argument("--reply", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--trace-id")
    parser.add_argument("--values", action="store_true")
    parser.add_argument("--require-exact", action="store_true")
    args = parser.parse_args(argv)
    blocks = None
    try:
        if args.transcript is not None:
            if args.message or args.reply or not args.trace_id:
                parser.error("--transcript needs --trace-id and no --message/--reply")
            lines = args.transcript.read_text(encoding="utf-8").splitlines()
            message, reply, blocks = from_transcript(lines, args.trace_id)
        elif args.message is not None and args.reply is not None:
            message = args.message.read_text(encoding="utf-8")
            reply = args.reply.read_text(encoding="utf-8")
        else:
            parser.error("give --message and --reply, or --transcript and --trace-id")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TranscriptError) as exc:
        print(f"status=unavailable reason={type(exc).__name__}: {exc}")
        return 2
    result = check_card_relay(message, reply)
    print(report(result, message, reply, args.values))
    if blocks is not None:
        print(f"  tool_blocks={blocks}")
    if args.require_exact and result.status == "pass" and result.reason != "exact":
        print(f"require_exact=fail reason={result.reason} (only reason=exact passes)")
        return 1
    return {"pass": 0, "fail": 1}.get(result.status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
