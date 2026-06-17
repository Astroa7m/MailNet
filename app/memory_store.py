"""Semantic memory layer backed by mem0 + MongoDB Atlas Vector Search.

Facts about each user (preferences, recurring contacts, habits) are extracted by
an LLM, embedded into vectors, and stored in Mongo. The agent reaches this
through the `recall`/`remember` tools wired up in common.build_agent.

The "smart features" provider is configurable per user (Google, OpenAI, or
Ollama Cloud). When a user has not added their own key we fall back to the
owner's shared Google/Gemini key. Every embedder is normalized to 768 dims so
the single Atlas vector index stays valid across providers.

Memory instances are built lazily and cached per provider+key, so a missing or
broken key degrades the feature instead of crashing the whole agent.
"""
import os
import hashlib

from dotenv import load_dotenv

from app.llm_errors import classify_provider_error

load_dotenv()

# Embedder output dimensions, kept in sync with the Atlas vector index. All
# providers are normalized to this so memories share one collection/index.
EMBEDDING_DIMS = 768

# Ollama Cloud speaks the OpenAI wire format, so we drive it through mem0's
# openai provider with a custom base URL rather than a separate integration.
_OLLAMA_BASE_URL = "https://ollama.com/v1"

_EXTRACTION_INSTRUCTIONS = """
Extract durable facts about the user that help personalize future emails:
tone and writing-style preferences, recurring contacts and how they like
to address them, scheduling habits, organizations they belong to, and any
explicit do/don't instructions.
Exclude one-off task details, greetings, and transient conversation.
"""

# Cache of built mem0 Memory instances, keyed by a hash of (provider, api_key).
_memory_cache: dict = {}
# Config hashes whose init failed, so we stop retrying them this run.
_failed_configs: set = set()


def _cache_key(provider, api_key: str) -> str:
    # Without a user key everything resolves to the same shared Gemini build, so
    # collapse all no-key configs to one cache entry. This keeps the agent and
    # the /memories endpoints sharing a single warm mem0 instance instead of
    # each paying the ~25s init cost separately.
    if not api_key:
        return "shared"
    raw = f"{provider}::{api_key}".encode()
    return hashlib.sha256(raw).hexdigest()


def _build_config(provider, api_key: str) -> dict:
    """Build a mem0 config for the given smart-features provider and key.

    provider is one of: None/"google" (shared or BYOK Gemini), "openai",
    "ollama". The LLM (fact extraction) and embedder both use the same key.
    """
    vector_store = {
        "provider": "mongodb",
        "config": {
            "db_name": "MailNet",
            "collection_name": "memories",
            "mongo_uri": os.getenv("MONGO_DB_URL"),
            "embedding_model_dims": EMBEDDING_DIMS,
        },
    }

    if provider in (None, "google"):
        key = api_key or os.getenv("GOOGLE_API_KEY")
        llm = {"provider": "gemini", "config": {"model": "gemini-2.5-flash", "temperature": 0.1, "api_key": key}}
        embedder = {"provider": "gemini", "config": {"model": "models/gemini-embedding-001", "embedding_dims": EMBEDDING_DIMS, "api_key": key}}
    elif provider == "openai":
        llm = {"provider": "openai", "config": {"model": "gpt-4o-mini", "temperature": 0.1, "api_key": api_key}}
        embedder = {"provider": "openai", "config": {"model": "text-embedding-3-small", "embedding_dims": EMBEDDING_DIMS, "api_key": api_key}}
    elif provider == "ollama":
        llm = {"provider": "openai", "config": {"model": "gpt-oss:120b", "temperature": 0.1, "api_key": api_key, "openai_base_url": _OLLAMA_BASE_URL}}
        embedder = {"provider": "openai", "config": {"model": "nomic-embed-text", "embedding_dims": EMBEDDING_DIMS, "api_key": api_key, "openai_base_url": _OLLAMA_BASE_URL}}
    else:
        raise ValueError(f"Unknown smart-features provider: {provider}")

    return {
        "vector_store": vector_store,
        "llm": llm,
        "embedder": embedder,
        "custom_instructions": _EXTRACTION_INSTRUCTIONS,
    }


def _get_memory(provider=None, api_key=None):
    """Return a cached mem0 Memory for this provider+key, or None if unavailable."""
    key_hash = _cache_key(provider, api_key)
    if key_hash in _memory_cache:
        return _memory_cache[key_hash]
    if key_hash in _failed_configs:
        return None

    # The shared default needs the owner's Gemini key; BYOK needs the user's.
    if provider in (None, "google") and not (api_key or os.getenv("GOOGLE_API_KEY")):
        print("[MEMORY] no Google key available; semantic memory disabled")
        _failed_configs.add(key_hash)
        return None
    if provider not in (None, "google") and not api_key:
        print(f"[MEMORY] no api key for provider {provider}; skipping")
        _failed_configs.add(key_hash)
        return None
    if not os.getenv("MONGO_DB_URL"):
        print("[MEMORY] MONGO_DB_URL not set; semantic memory disabled")
        _failed_configs.add(key_hash)
        return None

    try:
        print(f"[MEMORY] initializing mem0 (provider={provider or 'shared-gemini'})…")
        from mem0 import Memory
        mem = Memory.from_config(_build_config(provider, api_key))
        _memory_cache[key_hash] = mem
        print("[MEMORY] mem0 initialized successfully")
        return mem
    except Exception as e:
        import traceback
        print(f"[MEMORY] init failed, this config disabled: {e!r}")
        traceback.print_exc()
        _failed_configs.add(key_hash)
        return None


def _failure_note(exc, action: str) -> str:
    """Turn an exception into an honest, user-facing status string."""
    kind = classify_provider_error(exc)
    if kind == "quota":
        return (f"Couldn't {action}: the key for smart features has hit its usage limit. "
                "Add your own key in Settings → AI Models to keep using this.")
    if kind == "auth":
        return (f"Couldn't {action}: the smart-features API key was rejected. "
                "Please check it in Settings → AI Models.")
    return f"Couldn't {action} right now."


def remember(user_id: str, text: str, *, provider=None, api_key=None) -> str:
    """Store a durable fact about the user. Returns a human-readable status."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return "Memory is not configured, nothing was saved."
    try:
        result = mem.add(text, user_id=user_id)
        print(f"[MEMORY] remember(user={user_id}) -> {result}")
        # mem0 returns an empty results list when the extraction step stored
        # nothing (no durable fact found, or the extraction LLM failed). Never
        # claim success in that case.
        events = result.get("results", []) if isinstance(result, dict) else result
        if events:
            return "Saved to memory."
        return "I didn't find a durable fact worth saving in that, so nothing was stored."
    except Exception as e:
        import traceback
        print(f"[MEMORY] remember failed: {e!r}")
        traceback.print_exc()
        return _failure_note(e, "save that to memory")


def list_memories(user_id: str, *, provider=None, api_key=None) -> list:
    """Return all stored memories for a user: [{id, memory, created_at}]."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return []
    try:
        res = mem.get_all(filters={"user_id": user_id}, top_k=200)
        items = res.get("results", res) if isinstance(res, dict) else res
        out = []
        for it in items:
            if it.get("memory"):
                out.append({
                    "id": it.get("id"),
                    "memory": it.get("memory", ""),
                    "created_at": it.get("created_at"),
                })
        return out
    except Exception as e:
        import traceback
        print(f"[MEMORY] list failed: {e!r}")
        traceback.print_exc()
        return []


def delete_memory(memory_id: str, *, provider=None, api_key=None) -> bool:
    """Delete a single memory by id. Returns True on success."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return False
    try:
        mem.delete(memory_id=memory_id)
        return True
    except Exception as e:
        print(f"[MEMORY] delete failed: {e!r}")
        return False


def clear_memories(user_id: str, *, provider=None, api_key=None) -> bool:
    """Delete all memories for a user. Returns True on success."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return False
    try:
        mem.delete_all(user_id=user_id)
        return True
    except Exception as e:
        print(f"[MEMORY] clear failed: {e!r}")
        return False


def forget(user_id: str, query: str, *, provider=None, api_key=None) -> str:
    """Find the memory best matching query and delete it. Human-readable status."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return "Memory is not configured, nothing to remove."
    try:
        res = mem.search(query, filters={"user_id": user_id}, top_k=1)
        items = res.get("results", res) if isinstance(res, dict) else res
        if not items:
            return "I couldn't find a matching memory to remove."
        top = items[0]
        mem.delete(memory_id=top["id"])
        print(f"[MEMORY] forget(user={user_id}, query={query!r}) -> removed {top.get('id')}")
        return f"Removed from memory: {top.get('memory', '')}"
    except Exception as e:
        import traceback
        print(f"[MEMORY] forget failed: {e!r}")
        traceback.print_exc()
        return _failure_note(e, "remove that from memory")


def recall(user_id: str, query: str, limit: int = 5, *, provider=None, api_key=None) -> str:
    """Search the user's memories. Returns a newline-joined list or an empty note."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return ""
    try:
        res = mem.search(query, filters={"user_id": user_id}, limit=limit)
        items = res.get("results", res) if isinstance(res, dict) else res
        facts = [it.get("memory", "") for it in items if it.get("memory")]
        print(f"[MEMORY] recall(user={user_id}, query={query!r}) -> {len(facts)} facts")
        return "\n".join(f"- {f}" for f in facts)
    except Exception as e:
        import traceback
        print(f"[MEMORY] recall failed: {e!r}")
        traceback.print_exc()
        return ""
