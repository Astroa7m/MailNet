"""Settings must not demand a key for a provider MailNet already hosts.

The /provider-models endpoint once refused to touch the shared key at all, so
a free-tier user opening Settings was told to paste an API key before the app
would list models it was perfectly able to list, and to use a provider it was
already running their chat on. These pin the rule that fixed it.
"""
import sys

import pytest

sys.path.insert(0, "app")
import app.api as api


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-shared")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-shared")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-shared")


@pytest.mark.parametrize("provider,expected", [
    ("nvidia", "nvapi-shared"),
    ("groq", "gsk-shared"),
    ("google_genai", "goog-shared"),
])
def test_hosted_chat_providers_resolve_to_the_shared_key(keys, provider, expected):
    assert api._shared_key_for("chat", provider) == expected


@pytest.mark.parametrize("provider", ["openai", "anthropic", "ollama_cloud"])
def test_byok_chat_providers_have_no_shared_key(keys, provider):
    """These must keep prompting for a key: we ship none for them."""
    assert api._shared_key_for("chat", provider) is None


def test_memory_is_nvidia_only_on_the_shared_key(keys):
    """Shared memory never spends Groq or Gemini quota, so Google and OpenAI
    embeddings stay bring-your-own even though a Google chat key exists."""
    assert api._shared_key_for("embeddings", "nvidia") == "nvapi-shared"
    assert api._shared_key_for("embeddings", "google") is None
    assert api._shared_key_for("embeddings", "openai") is None


def test_no_shared_key_configured_means_no_fallback(monkeypatch):
    """With the env var unset the provider is byok again, which is also the
    NVIDIA rollback lever."""
    for var in ("NVIDIA_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert api._shared_key_for("chat", "nvidia") is None
    assert api._shared_key_for("embeddings", "nvidia") is None
