"""Attachment ceiling and provider error hygiene (security review F11, F18)."""
import sys

sys.path.insert(0, "app")
import app.api as api


def _store(entries):
    # entries: list of (user_id, size)
    return {str(i): {"user_id": u, "size": s} for i, (u, s) in enumerate(entries)}


def test_attachment_per_user_cap_blocks():
    store = _store([("u1", api._MAX_USER_ATTACHMENT_BYTES - 10)])
    ok, why = api._within_attachment_limits(store, "u1", 100)
    assert not ok and why == "user_full"


def test_attachment_global_ceiling_blocks_even_a_fresh_user():
    big = api._MAX_USER_ATTACHMENT_BYTES
    n = api._MAX_TOTAL_ATTACHMENT_BYTES // big + 1
    store = _store([(f"u{i}", big) for i in range(n)])
    ok, why = api._within_attachment_limits(store, "fresh-user", 100)
    assert not ok and why == "busy"


def test_attachment_normal_upload_allowed():
    ok, why = api._within_attachment_limits({}, "u1", 1024)
    assert ok and why == ""


def test_safe_provider_message_never_echoes_raw_detail():
    assert api._safe_provider_message("auth") == "That API key was rejected by the provider."
    assert "provider" in api._safe_provider_message("quota").lower()
    # an unknown/raw reason falls back to the generic message, never echoed
    assert api._safe_provider_message("Traceback: secret at 0x7f...") == api._PROVIDER_REASON_MESSAGE["error"]
