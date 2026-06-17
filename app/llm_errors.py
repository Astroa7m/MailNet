"""Provider-agnostic classification of LLM/embedding errors.

Standalone so both the chat path (common.py) and the memory path
(memory_store.py) can share it without a circular import. The goal is to turn
any provider's exception (Groq, Google/Gemini, OpenAI, Anthropic, Ollama) into
one of two user-actionable categories, then build a friendly message that
points the user to Settings to add their own key.
"""
from typing import Optional

# Substrings that show up in quota / rate-limit errors across providers.
_QUOTA_HINTS = (
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "quota",
    "insufficient_quota",
    "too many requests",
)

# Substrings that show up when a key is missing, wrong, or not permitted.
_AUTH_HINTS = (
    "invalid api key",
    "api key not valid",
    "incorrect api key",
    "invalid_api_key",
    "permission_denied",
    "permissiondenied",
    "unauthenticated",
    "unauthorized",
    "no auth credentials",
)


def classify_provider_error(exc: Exception) -> Optional[str]:
    """Return "quota", "auth", or None for any provider exception.

    Checks an HTTP-style status code first (groq/openai/anthropic expose
    .status_code; google exposes .code), then falls back to matching the
    message text so we still catch providers that do not set a code.
    """
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    msg = str(exc).lower()

    if code == 429 or "429" in msg or any(h in msg for h in _QUOTA_HINTS):
        return "quota"
    if code in (401, 403) or any(h in msg for h in _AUTH_HINTS):
        return "auth"
    return None


def quota_message(using_shared: bool) -> str:
    """Message shown when a provider reports a rate/quota limit."""
    if using_shared:
        return (
            "I've hit the usage limit on the app's shared AI key for now. "
            "To keep going without waiting, add your own free API key in "
            "Settings → AI Models. It only takes a minute."
        )
    return (
        "Your API key has hit its rate limit. Please wait a moment and try "
        "again, or switch to a different provider in Settings → AI Models."
    )


def auth_message() -> str:
    """Message shown when a provider rejects the API key."""
    return (
        "Your API key was rejected. Please double-check it in "
        "Settings → AI Models, or remove it to fall back to the app's "
        "shared key."
    )


def generic_message() -> str:
    """Fallback for errors we could not classify."""
    return (
        "I ran into a problem reaching the AI model. Please try again in a "
        "moment. If it keeps happening, check your key in Settings → AI Models."
    )
