"""Pin classify_provider_error against the exact strings real providers emit.

Every string here was observed from a real SDK or documented from its source:
ChatNVIDIA raises plain Exception("[status] title"), Groq embeds "Error code:
429", Gemini emits RESOURCE_EXHAUSTED. When a new provider error shows up in
production logs, its exact text gets a row here.
"""
import pytest

from app.llm_errors import classify_provider_error


class _WithStatusCode(Exception):
    def __init__(self, msg: str, status_code=None, code=None):
        super().__init__(msg)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


CASES = [
    # ChatNVIDIA shapes: plain Exception, no status attribute.
    (Exception("[429] Too Many Requests"), "quota"),
    (Exception("[401] Unauthorized: invalid response from UAM"), "auth"),
    (Exception("[403] Forbidden"), "auth"),
    (Exception("[404] Not Found: model x/y does not exist"), None),
    # Groq / OpenAI-style SDK errors carry status_code and rich text.
    (_WithStatusCode("Error code: 429 - rate_limit_exceeded", status_code=429), "quota"),
    (_WithStatusCode("invalid api key", status_code=401), "auth"),
    (_WithStatusCode("permission denied for model", status_code=403), "auth"),
    # Gemini exposes .code and RESOURCE_EXHAUSTED text.
    (_WithStatusCode("429 RESOURCE_EXHAUSTED: quota exceeded", code=429), "quota"),
    # Text-only fallbacks.
    (Exception("You have exceeded your rate limit, slow down"), "quota"),
    (Exception("insufficient_quota: add a payment method"), "quota"),
    (Exception("request rejected: unauthorized"), "auth"),
    (Exception("something entirely different broke"), None),
]


@pytest.mark.parametrize("exc,expected", CASES, ids=[str(c[0])[:48] for c in CASES])
def test_classification(exc, expected):
    assert classify_provider_error(exc) == expected
