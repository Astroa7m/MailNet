"""Runtime patch for a truncation bug in ag_ui_langgraph.

The library's `resolve_message_content` extracts assistant text from a streamed
chunk like this:

    content_text = next(
        (c.get("text") for c in content
         if isinstance(c, dict) and c.get("type") == "text"),
        None,
    )

When a provider streams assistant content as a LIST of parts (Google Gemini does
this once its "thinking" pass is on: visible text is split across several parts,
interleaved with thinking-signature parts), this has two failure modes:

  1. It returns only the FIRST text part and drops the rest.
  2. For a chunk whose first/only part is a signature (no type=="text"), it
     returns None. The adapter reads None as "no content" and fires the
     message-END event, cutting the live reply off mid-sentence.

That is the cut-off Gemini reply we saw ("...Microsoft you'" then nothing) even
though the fully-formed message was persisted. Providers that stream plain
strings (Groq, OpenAI) were unaffected, which is why only Gemini broke.

Fix: join ALL text parts in the chunk and ignore non-text (reasoning/signature)
parts, which the adapter already handles separately via resolve_reasoning_content.
We patch both the utils module and the agent module, because agent.py imported
the name directly into its own namespace.
"""
from typing import Any

from app.logging_config import get_logger

log = get_logger("agui")


def _resolve_message_content(content: Any):
    if not content:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                text = c.get("text")
                if text:
                    parts.append(text)
        return "".join(parts) if parts else None
    return None


def apply() -> None:
    """Patch ag_ui_langgraph's resolve_message_content in every namespace that
    holds a reference. Safe to call more than once."""
    patched = []
    try:
        import ag_ui_langgraph.utils as _utils
        _utils.resolve_message_content = _resolve_message_content
        patched.append("utils")
    except Exception as e:
        log.warning("could not patch ag_ui_langgraph.utils: %r", e)
    try:
        import ag_ui_langgraph.agent as _agent
        # agent.py did `from .utils import resolve_message_content`, so it has its
        # own binding that must be overwritten too.
        if hasattr(_agent, "resolve_message_content"):
            _agent.resolve_message_content = _resolve_message_content
            patched.append("agent")
    except Exception as e:
        log.warning("could not patch ag_ui_langgraph.agent: %r", e)
    if patched:
        log.info("patched resolve_message_content in: %s", ", ".join(patched))
