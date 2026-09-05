"""Semantic memory layer backed by mem0 + MongoDB Atlas Vector Search.

Facts about each user (preferences, recurring contacts, habits) are extracted by
an LLM, embedded into vectors, and stored in Mongo. The agent reaches this
through the `recall`/`remember` tools wired up in common.build_agent.

Memory is free for every user and runs on the app's shared NVIDIA key ONLY
(extraction and embeddings both); it never spends the Groq or Gemini keys, and
when NVIDIA is unavailable it degrades to off for that operation instead of
falling back to another provider. Free-tier saves are capped per day; bringing
your own smart-features key (NVIDIA, Google, or OpenAI) lifts the cap.

Every embedder is pinned to 2048 dims (nemotron-3-embed-1b's native size) so
the single Atlas vector index stays valid across providers. Ollama Cloud was
dropped as an embeddings provider here: nomic-embed-text is fixed at 768 dims
and cannot join the shared index.

Memory instances are built lazily and cached per provider+key, so a missing or
broken key degrades the feature instead of crashing the whole agent.
"""
import os
import hashlib

from dotenv import load_dotenv

from app.llm_errors import classify_provider_error
from app.logging_config import get_logger

log = get_logger("memory")

load_dotenv()

# Embedder output dimensions, kept in sync with the Atlas vector index. All
# providers are normalized to this so memories share one collection/index.
# 2048 is nemotron-3-embed-1b's native (and only) size; Gemini reaches it via
# output_dimensionality and OpenAI via text-embedding-3-large's dimensions
# param. Changing the embed model means dropping and recreating the index.
EMBEDDING_DIMS = 2048

# NVIDIA NIM speaks the OpenAI wire format, so the shared build drives it
# through mem0's openai provider with a custom base URL. nemotron-3-embed-1b is
# the only hosted embedding model that works through the plain OpenAI shape
# (the QA embedders demand an input_type param mem0 cannot send). The
# extraction model must accept response_format=json_object, which mem0's add()
# step always sends; the first pick (openai/gpt-oss-120b) reached end of life
# on 2026-09-03, which silently broke every shared save, so both names are
# env-overridable now: the next retirement is a restart, not a rebuild.
# Changing the EMBED model still means dropping and recreating the index,
# because vectors from two models cannot share one.
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MEM_EXTRACT_MODEL = os.getenv("MEM_EXTRACT_MODEL", "nvidia/nemotron-3-super-120b-a12b")
MEM_EMBED_MODEL = os.getenv("MEM_EMBED_MODEL", "nvidia/nemotron-3-embed-1b")

# Free-tier cap on memory SAVES per user per day (extraction is the expensive
# call). Recall is uncapped. BYOK and admin are exempt.
MEMORY_SAVES_PER_DAY = int(os.getenv("MEMORY_SAVES_PER_DAY", "20"))

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
    # Without a user key everything resolves to the same shared NVIDIA build,
    # so collapse all no-key configs to one cache entry. This keeps the agent
    # and the /memories endpoints sharing a single warm mem0 instance instead
    # of each paying the ~25s init cost separately.
    if not api_key:
        return "shared"
    raw = f"{provider}::{api_key}".encode()
    return hashlib.sha256(raw).hexdigest()


def _build_config(provider, api_key: str) -> dict:
    """Build a mem0 config for the given smart-features provider and key.

    provider is one of: None (the shared NVIDIA build every keyless user
    gets), or BYOK "nvidia", "google", "openai". The LLM (fact extraction)
    and embedder both use the same key.
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

    if provider in (None, "nvidia"):
        key = api_key or os.getenv("NVIDIA_API_KEY")
        llm = {"provider": "openai", "config": {"model": MEM_EXTRACT_MODEL, "temperature": 0.1, "api_key": key, "openai_base_url": _NVIDIA_BASE_URL}}
        embedder = {"provider": "openai", "config": {"model": MEM_EMBED_MODEL, "embedding_dims": EMBEDDING_DIMS, "api_key": key, "openai_base_url": _NVIDIA_BASE_URL}}
    elif provider == "google":
        llm = {"provider": "gemini", "config": {"model": "gemini-2.5-flash", "temperature": 0.1, "api_key": api_key}}
        embedder = {"provider": "gemini", "config": {"model": "models/gemini-embedding-001", "embedding_dims": EMBEDDING_DIMS, "api_key": api_key}}
    elif provider == "openai":
        # text-embedding-3-large, not -small: small tops out at 1536 dims and
        # cannot join the shared 2048-dim index.
        llm = {"provider": "openai", "config": {"model": "gpt-4o-mini", "temperature": 0.1, "api_key": api_key}}
        embedder = {"provider": "openai", "config": {"model": "text-embedding-3-large", "embedding_dims": EMBEDDING_DIMS, "api_key": api_key}}
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

    # The shared default needs the owner's NVIDIA key; BYOK needs the user's.
    if provider in (None, "nvidia") and not (api_key or os.getenv("NVIDIA_API_KEY")):
        log.warning("no NVIDIA key available; semantic memory disabled")
        _failed_configs.add(key_hash)
        return None
    if provider not in (None, "nvidia") and not api_key:
        log.warning("no api key for provider %s; skipping", provider)
        _failed_configs.add(key_hash)
        return None
    if not os.getenv("MONGO_DB_URL"):
        log.warning("MONGO_DB_URL not set; semantic memory disabled")
        _failed_configs.add(key_hash)
        return None

    try:
        log.info("initializing mem0 (provider=%s)", provider or "shared-nvidia")
        from mem0 import Memory
        mem = Memory.from_config(_build_config(provider, api_key))
        # Memory.from_config can "succeed" with a broken vector store: when
        # Atlas refuses the search index (index limit, or deletion of an old
        # index still propagating), mem0's mongodb store swallows the error
        # and leaves collection=None, after which every add/search dies with
        # AttributeError. Caching that instance would poison memory until the
        # process restarts, so probe it and retry on the NEXT call instead
        # (no _failed_configs entry: the condition is usually transient).
        coll = getattr(getattr(mem, "vector_store", None), "collection", "unknown")
        if coll is None:
            log.error("mem0 vector store has no collection (Atlas index not created); will retry on next use")
            return None
        _memory_cache[key_hash] = mem
        log.info("mem0 initialized successfully")
        return mem
    except Exception as e:
        log.exception("mem0 init failed, this config disabled: %r", e)
        _failed_configs.add(key_hash)
        return None


def _failure_note(exc, action: str) -> str:
    """Turn an exception into an honest, user-facing status string."""
    kind = classify_provider_error(exc)
    if kind == "quota":
        return (f"Couldn't {action}: smart features have hit their usage limit for now. "
                "They resume automatically when the free quota resets, or add your own "
                "key in Settings → AI Models for unlimited use.")
    if kind == "auth":
        return (f"Couldn't {action}: the smart-features API key was rejected. "
                "Please check it in Settings → AI Models.")
    return f"Couldn't {action} right now."


_redis_client = None


def _memory_save_capped(user_id: str) -> bool:
    """True when the free tier's daily save cap is exhausted for this user.

    Same day-key Redis pattern as the chat limiter (SET NX EX first so the
    counter always carries a TTL, then INCR). Fails OPEN on any Redis problem,
    with tight socket timeouts so a wedged Redis costs about 2 seconds, not a
    hung user turn: the cap protects shared quota, it must never take memory
    down on its own."""
    global _redis_client
    try:
        if _redis_client is None:
            import redis
            _redis_client = redis.Redis.from_url(
                os.getenv("REDIS_URL", ""),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        import datetime
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        key = f"rl:mem:{user_id}:{day}"
        _redis_client.set(key, 0, ex=172800, nx=True)
        return int(_redis_client.incr(key)) > MEMORY_SAVES_PER_DAY
    except Exception as e:
        log.warning("memory save-cap check failed (allowing): %r", e)
        return False


def remember(user_id: str, text: str, *, provider=None, api_key=None, exempt_from_cap: bool = False) -> str:
    """Store a durable fact about the user. Returns a human-readable status.

    Saves on the shared NVIDIA build (provider is None) count against a daily
    per-user cap; BYOK and admin callers pass exempt_from_cap=True."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return "Memory is not configured, nothing was saved."
    if provider is None and not exempt_from_cap and _memory_save_capped(user_id):
        return (
            "Daily memory limit reached, so this was not saved. It resets at "
            "midnight UTC, or add your own smart-features key in Settings → "
            "AI Models for unlimited memory."
        )
    try:
        result = mem.add(text, user_id=user_id)
        log.info("remember(user=%s) -> %s", user_id, result)
        # mem0 returns an empty results list when the extraction step stored
        # nothing (no durable fact found, or the extraction LLM failed). Never
        # claim success in that case.
        events = result.get("results", []) if isinstance(result, dict) else result
        if events:
            return "Saved to memory."
        return "I didn't find a durable fact worth saving in that, so nothing was stored."
    except Exception as e:
        log.exception("remember failed: %r", e)
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
        log.exception("list failed: %r", e)
        return []


def delete_memory(memory_id: str, *, provider=None, api_key=None, user_id: str = None) -> bool:
    """Delete a single memory by id. Returns True on success.

    When user_id is given the memory is confirmed to belong to that user first:
    ids are shared across one collection, so deleting by raw id alone would let
    a caller remove another user's memory."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return False
    try:
        if user_id is not None:
            owned = mem.get_all(filters={"user_id": user_id}, top_k=500)
            items = owned.get("results", owned) if isinstance(owned, dict) else owned
            if not any(str(it.get("id")) == str(memory_id) for it in (items or [])):
                log.warning("delete refused: memory %s not owned by %s", memory_id, user_id)
                return False
        mem.delete(memory_id=memory_id)
        return True
    except Exception as e:
        log.warning("delete failed: %r", e)
        return False


def clear_memories(user_id: str, *, provider=None, api_key=None) -> bool:
    """Delete all memories for a user. Returns True on success.

    Deliberately NOT mem.delete_all(): on mem0 2.0.4 with the mongodb vector
    store it crashes with "'tuple' object has no attribute 'id'" (delete_all
    does vector_store.list()[0] and then .id on entries the mongodb store
    returns as tuples). Listing through get_all and deleting one by one uses
    only the code paths that are known to work."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return False
    try:
        items = list_memories(user_id, provider=provider, api_key=api_key)
        for it in items:
            if it.get("id"):
                mem.delete(memory_id=it["id"])
        log.info("clear_memories(user=%s) removed %d", user_id, len(items))
        return True
    except Exception as e:
        log.warning("clear failed: %r", e)
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
        log.info("forget(user=%s, query=%r) -> removed %s", user_id, query, top.get("id"))
        return f"Removed from memory: {top.get('memory', '')}"
    except Exception as e:
        log.exception("forget failed: %r", e)
        return _failure_note(e, "remove that from memory")


def recall(user_id: str, query: str, limit: int = 5, *, provider=None, api_key=None) -> str:
    """Search the user's memories for this query. Returns a newline-joined list
    or an empty string. Queried fresh every call: a previous cache keyed only on
    user_id returned the first query's facts for every later message and could
    serve just-deleted facts, so it was removed."""
    mem = _get_memory(provider, api_key)
    if mem is None:
        return ""
    try:
        res = mem.search(query, filters={"user_id": user_id}, top_k=limit)
        items = res.get("results", res) if isinstance(res, dict) else res
        facts = [it.get("memory", "") for it in items if it.get("memory")]
        log.info("recall(user=%s, query=%r) -> %d facts", user_id, query, len(facts))
        return "\n".join(f"- {f}" for f in facts)
    except Exception as e:
        log.exception("recall failed: %r", e)
        return ""
