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
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
NVIDIA_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

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


# Curated shortlist surfaced above the full list in the model dropdown, most
# recommendable first. NVIDIA hosts ~70 chat models and most are specialists
# (code, medical, translation, safety, OCR) that cannot drive a mail agent, so
# a flat alphabetical list buries the handful worth picking.
#
# Speed tags are measured, not guessed: the median MailNet task in the eval
# suite (tests/evals, run 20260905-120805, 12 scenarios each). Buckets are fast
# (under 15s), medium (15 to 30s), slow (over 30s). Membership is earned in the
# same run: of 13 NVIDIA models probed, the rest either could not return a tool
# call, timed out past 75 seconds, or answered "Not found for account" despite
# being listed, so they stay out of the shortlist but remain in the full list.
#
# Entries are filtered against the live /v1/models response before reaching the
# UI, so a retired model drops off on its own, which matters because NVIDIA
# retires hosted models on a few days' notice (six went "[410] Gone" during
# this project, including a previous default).
NVIDIA_POPULAR = (
    ("nvidia/nemotron-3-super-120b-a12b", "fast",
     "Default. Best scores in our evals, and the quickest."),
    ("nvidia/nemotron-3.5-lightning-30b-a3b", "medium",
     "Scores like the default, a few seconds behind it."),
    ("openai/gpt-oss-20b", "medium",
     "Fine for everyday asks, weaker on multi-step ones."),
    ("nvidia/nemotron-3-ultra-550b-a55b", "slow",
     "The largest model here, and the most rate-limited."),
)

_POPULAR = {"nvidia": NVIDIA_POPULAR}


def annotate_chat_models(provider: str, models: list) -> tuple:
    """Return (ordered_models, meta) for a provider's model list.

    Curated models keep their table order and come first; everything else
    follows in the provider's own order. meta maps model id to
    {"tag", "note", "popular"} and is empty for providers without a table,
    which leaves their dropdown exactly as it was.
    """
    table = _POPULAR.get(provider)
    if not table:
        return models, {}
    available = set(models)
    picked = [row for row in table if row[0] in available]
    meta = {mid: {"tag": tag, "note": note, "popular": True} for mid, tag, note in picked}
    rest = [m for m in models if m not in meta]
    return [row[0] for row in picked] + rest, meta


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
    """Live NVIDIA hosted chat models, same policy as every other provider.

    An earlier version filtered to the langchain package's static
    supports_tools catalog, but that catalog proved stale within months
    (it listed already-retired models and missed new ones), which shrank the
    dropdown to a handful of names while NVIDIA hosts dozens. Now the live
    /v1/models list is used with the shared chat-model blocklist, exactly
    like Groq and Ollama Cloud; the existing UI hint already tells users to
    pick a tool-capable model."""
    return [m for m in _bearer_models(NVIDIA_MODELS_URL, api_key) if _is_chat_model(m)]


def retired_nvidia_models(api_key: str, wanted: list) -> list:
    """Return the names in wanted that NVIDIA's live catalog no longer serves.

    A retirement fails quietly in production: chat walks the failover chain and
    memory just stops saving, so the app looks healthy while NVIDIA is doing
    nothing. Called once at startup to turn that into a log line that names the
    dead model. Raises ProviderError if the catalog itself cannot be read,
    which the caller treats as "unknown", never as "retired".
    """
    live = set(_bearer_models(NVIDIA_MODELS_URL, api_key))
    return [m for m in wanted if m not in live]


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
    """Make a tiny real embedding call for the smart-features key.

    Models and dims mirror app.memory_store exactly: every provider must be
    able to write into the shared 2048-dim index. Ollama was removed here for
    that reason (nomic-embed-text is fixed at 768 dims)."""
    if provider == "google":
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        client.models.embed_content(
            model="gemini-embedding-001",
            contents="ping",
            config=types.EmbedContentConfig(output_dimensionality=2048),
        )
        return
    if provider == "openai":
        r = requests.post(
            OPENAI_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "text-embedding-3-large", "input": "ping", "dimensions": 2048},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            raise ProviderError(_reason_from_status(r.status_code), f"{r.status_code}: {r.text[:200]}")
        return
    if provider == "nvidia":
        r = requests.post(
            NVIDIA_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "nvidia/nemotron-3-embed-1b", "input": "ping", "dimensions": 2048},
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
