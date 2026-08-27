"""Live provider metadata: list available chat models and validate API keys.

Used by the Settings → AI Models flow so users never have to type a model name
and never save a key that does not work. Every call hits the real provider, so
a successful response also proves the key is valid. Functions are synchronous
(requests / SDK clients); call them from async endpoints via asyncio.to_thread.
"""
import os
from typing import Optional

import requests

from app.llm_errors import classify_provider_error

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
OLLAMA_MODELS_URL = "https://ollama.com/v1/models"
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
OLLAMA_EMBED_URL = "https://ollama.com/v1/embeddings"

_TIMEOUT = 20

# Substrings that mark a model as NOT a text-chat model, so we keep provider
# dropdowns to actual chat models (Groq/Ollama lists include audio, TTS,
# moderation and embedding models we must hide).
_NON_CHAT_HINTS = (
    "whisper", "tts", "orpheus", "guard", "safeguard", "embed", "rerank",
    "moderation", "audio", "speech", "transcribe", "vision", "nomic", "bge",
    "stt", "distil-whisper", "image", "dall-e",
)


def _is_chat_model(model_id: str) -> bool:
    m = model_id.lower()
    return not any(h in m for h in _NON_CHAT_HINTS)


class ProviderError(Exception):
    """A provider call failed. reason is one of: auth, quota, error."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(message)


def _reason_from_status(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "quota"
    return "error"


def _bearer_models(url: str, api_key: str) -> list:
    """List model ids from an OpenAI-compatible /models endpoint."""
    r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise ProviderError(_reason_from_status(r.status_code), f"{r.status_code}: {r.text[:200]}")
    data = r.json().get("data", [])
    return sorted({m["id"] for m in data if m.get("id")})


def _anthropic_models(api_key: str) -> list:
    r = requests.get(
        ANTHROPIC_MODELS_URL,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout=_TIMEOUT,
    )
    if r.status_code != 200:
        raise ProviderError(_reason_from_status(r.status_code), f"{r.status_code}: {r.text[:200]}")
    data = r.json().get("data", [])
    return [m["id"] for m in data if m.get("id")]


def _gemini_models(api_key: str) -> list:
    from google import genai
    try:
        client = genai.Client(api_key=api_key)
        out = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" not in actions:
                continue
            name = m.name.replace("models/", "")
            if not name.startswith("gemini-"):
                continue
            if any(k in name for k in ("flash", "pro")) and not any(
                b in name for b in ("embedding", "tts", "image", "vision", "aqa")
            ):
                out.append(name)
        # Newest first so the dropdown leads with current models.
        return sorted(set(out), reverse=True)
    except Exception as e:
        raise ProviderError(classify_provider_error(e) or "error", str(e)[:200])


def _nvidia_models(api_key: str) -> list:
    """Tool-capable NVIDIA hosted chat models.

    NVIDIA's /v1/models endpoint does not say which models support tool
    calling, but ChatNVIDIA.get_available_models merges the live list with the
    package's static catalog, which does. MailNet is an agent, so a model
    without tool support is unusable here and is hidden from the dropdown."""
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    try:
        models = ChatNVIDIA.get_available_models(api_key=api_key)
    except Exception as e:
        raise ProviderError(classify_provider_error(e) or "error", str(e)[:200])
    return sorted({
        m.id for m in models
        if getattr(m, "model_type", None) == "chat"
        and getattr(m, "supports_tools", False)
        and _is_chat_model(m.id)
    })


def list_chat_models(provider: str, api_key: str) -> list:
    """Return chat-capable model ids for a provider. Raises ProviderError."""
    if provider == "nvidia":
        return _nvidia_models(api_key)
    if provider == "groq":
        return [m for m in _bearer_models(GROQ_MODELS_URL, api_key) if _is_chat_model(m)]
    if provider == "openai":
        models = _bearer_models(OPENAI_MODELS_URL, api_key)
        return [m for m in models if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")) and _is_chat_model(m)]
    if provider == "ollama_cloud":
        return [m for m in _bearer_models(OLLAMA_MODELS_URL, api_key) if _is_chat_model(m)]
    if provider == "anthropic":
        return _anthropic_models(api_key)
    if provider == "google_genai":
        return _gemini_models(api_key)
    raise ProviderError("error", f"Unknown chat provider: {provider}")


def _chat_ping(provider: str, api_key: str, model: Optional[str]) -> None:
    """Make a tiny real chat call. Proves the key AND the chosen model work
    (catches retired models that still appear in the list endpoint)."""
    from app.common import _build_llm
    llm = _build_llm(provider, api_key, model)
    llm.invoke("Reply with the single word OK.")


def _embed_ping(provider: str, api_key: str) -> None:
    """Make a tiny real embedding call for the smart-features key."""
    if provider == "google":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        client.models.embed_content(
            model="gemini-embedding-001",
            contents="ping",
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return
    if provider == "openai":
        r = requests.post(
            OPENAI_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "text-embedding-3-small", "input": "ping", "dimensions": 768},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            raise ProviderError(_reason_from_status(r.status_code), f"{r.status_code}: {r.text[:200]}")
        return
    if provider == "ollama":
        r = requests.post(
            OLLAMA_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "nomic-embed-text", "input": "ping"},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            raise ProviderError(_reason_from_status(r.status_code), f"{r.status_code}: {r.text[:200]}")
        return
    raise ProviderError("error", f"Unknown embeddings provider: {provider}")


def validate_key(provider: str, api_key: str, slot: str, model: Optional[str] = None):
    """Validate a key with a real provider call.

    Returns (ok: bool, reason: Optional[str], message: Optional[str]).
    reason is one of: auth, quota, error.
    """
    try:
        if slot == "chat":
            _chat_ping(provider, api_key, model)
        else:
            _embed_ping(provider, api_key)
        return True, None, None
    except ProviderError as e:
        return False, e.reason, e.message
    except Exception as e:
        return False, classify_provider_error(e) or "error", str(e)[:200]
