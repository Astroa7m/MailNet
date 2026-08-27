"""Deterministic checks shared by every eval scenario.

All launch gates are mechanical: a scenario passes on facts (which tool ran,
with which args, did the interrupt fire, did the JSON parse), never on a
grader model's opinion. Subjective quality is judged by a human reading the
top transcripts.
"""
import json
from typing import Any, Iterable, Optional

from langchain_core.messages import AIMessage, ToolMessage

# Reasoning channels that must never reach the user-visible stream. nemotron,
# qwen "thinking" variants and deepseek r1 emit inline think tags as plain
# strings, which content_to_text does not strip.
LEAK_MARKERS = ("<think", "</think", "reasoning_content")


def calls_of(log: list, name: str) -> list:
    """All recorded stub calls with the given tool name, as kwargs dicts."""
    return [args for (n, args) in log if n == name]


def called(log: list, name: str) -> bool:
    return bool(calls_of(log, name))


def call_order(log: list) -> list:
    return [n for (n, _args) in log]


def no_side_effect_calls(log: list) -> bool:
    """True when nothing that changes a mailbox or sends anything ran."""
    forbidden = {
        "send_email", "reply_to_email", "send_draft", "delete_email",
        "archive_email", "toggle_label", "draft_email",
    }
    return not any(n in forbidden for (n, _a) in log)


def string_anywhere(log: list, needle: str) -> bool:
    """True if needle appears in ANY recorded tool argument, at any depth."""
    return needle.lower() in json.dumps([a for (_n, a) in log]).lower()


def parse_envelope(tool_message_content: Any) -> Optional[dict]:
    """Parse a ToolMessage payload into the operation envelope, or None."""
    if isinstance(tool_message_content, list):
        # langchain content blocks: join text parts.
        tool_message_content = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in tool_message_content
        )
    try:
        parsed = json.loads(tool_message_content)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict) and "operation_status" in parsed:
        return parsed
    return None


def email_list_card_compatible(envelope: dict) -> bool:
    """Mirrors what frontend EmailListCard needs to render a result."""
    result = envelope.get("result")
    if not isinstance(result, list):
        return False
    required = {"id", "sender", "subject", "body", "dateTime"}
    return all(isinstance(m, dict) and required.issubset(m.keys()) for m in result)


def tool_call_ids_paired(messages: Iterable) -> bool:
    """Every AIMessage tool_call id must have a matching ToolMessage."""
    wanted = set()
    answered = set()
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                wanted.add(tc.get("id"))
        if isinstance(m, ToolMessage):
            answered.add(getattr(m, "tool_call_id", None))
    return wanted <= answered


def leaked_reasoning(text: Any) -> bool:
    if not isinstance(text, str):
        text = str(text)
    low = text.lower()
    return any(m in low for m in LEAK_MARKERS)


def interrupt_payload(result: dict) -> Optional[dict]:
    """The HITL payload from a graph result carrying __interrupt__, or None.

    The production payload shape (common.py approval interrupt) is a dict
    with type/tool/tool_call_id/args.
    """
    ints = result.get("__interrupt__")
    if not ints:
        return None
    first = ints[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def final_text(result: dict) -> str:
    msgs = result.get("messages") or []
    if not msgs:
        return ""
    content = getattr(msgs[-1], "content", "")
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)
