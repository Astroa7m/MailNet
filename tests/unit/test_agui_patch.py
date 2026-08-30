"""The AG-UI reasoning hardening: string-shaped reasoning must not crash.

Caught live during E2E on NVIDIA primary: gpt-oss streams
additional_kwargs["reasoning"] as a plain string, the library called
.get("summary") on it, and the whole event stream died mid-run.
"""
from types import SimpleNamespace

from app.agui_patch import _make_safe_reasoning_resolver, apply


def _chunk(reasoning):
    return SimpleNamespace(additional_kwargs={"reasoning": reasoning}, content="")


def test_string_reasoning_suppressed_not_crashed():
    def original(chunk):
        return chunk.additional_kwargs["reasoning"].get("summary")  # the lib's bug

    safe = _make_safe_reasoning_resolver(original)
    assert safe(_chunk("I am thinking out loud as a string")) is None


def test_dict_reasoning_still_reaches_original():
    seen = {}

    def original(chunk):
        seen["called"] = True
        return "resolved"

    safe = _make_safe_reasoning_resolver(original)
    assert safe(_chunk({"summary": [{"text": "t"}]})) == "resolved"
    assert seen.get("called")


def test_original_exception_becomes_none():
    def original(chunk):
        raise RuntimeError("library exploded on some new provider shape")

    safe = _make_safe_reasoning_resolver(original)
    assert safe(_chunk({"weird": True})) is None


def test_apply_is_idempotent_and_marks_functions():
    import ag_ui_langgraph.utils as u
    apply()
    first = u.resolve_reasoning_content
    apply()
    # A second apply must not wrap the wrapper.
    assert u.resolve_reasoning_content is first
    assert getattr(first, "_mailnet_safe", False)
