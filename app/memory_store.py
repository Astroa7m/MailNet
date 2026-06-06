"""Semantic memory layer backed by mem0 + MongoDB Atlas Vector Search.

Facts about each user (preferences, recurring contacts, habits) are extracted by
an LLM, embedded with Gemini, and stored as vectors in Mongo. The agent reaches
this through the `recall`/`remember` tools wired up in common.build_agent.

The Memory instance is created lazily so a missing GEMINI_API_KEY degrades the
feature instead of crashing the whole agent at import time.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# Gemini embedder dimensions, keeping this in sync with the Atlas vector index.
EMBEDDING_DIMS = 768

_memory = None
_init_failed = False


def _build_config() -> dict:
    return {
        "vector_store": {
            "provider": "mongodb",
            "config": {
                "db_name": "MailNet",
                "collection_name": "memories",
                "mongo_uri": os.getenv("MONGO_DB_URL"),
                "embedding_model_dims": EMBEDDING_DIMS,
            },
        },
        "llm": {
            # Gemini for fact extraction, which avoids the Groq free-tier 8k TPM limit
            # that mem0's extraction prompt blows past, and reuses GOOGLE_API_KEY.
            "provider": "gemini",
            "config": {
                "model": "gemini-2.0-flash-001",
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "gemini",
            "config": {
                "model": "models/gemini-embedding-001",
                "embedding_dims": EMBEDDING_DIMS,
            },
        },
        "custom_instructions": """
        Extract durable facts about the user that help personalize future emails:
        tone and writing-style preferences, recurring contacts and how they like
        to address them, scheduling habits, organizations they belong to, and any
        explicit do/don't instructions.
        Exclude one-off task details, greetings, and transient conversation.
        """,
    }


def _get_memory():
    """Lazily build the mem0 Memory singleton. Returns None if unavailable."""
    global _memory, _init_failed
    if _memory is not None:
        return _memory
    if _init_failed:
        print("[MEMORY] previous init failed; memory stays disabled this run")
        return None
    if not os.getenv("GOOGLE_API_KEY"):
        print("[MEMORY] GOOGLE_API_KEY not set; semantic memory disabled")
        _init_failed = True
        return None
    if not os.getenv("MONGO_DB_URL"):
        print("[MEMORY] MONGO_DB_URL not set; semantic memory disabled")
        _init_failed = True
        return None
    try:
        print("[MEMORY] initializing mem0 (gemini embedder + mongo vector store)…")
        from mem0 import Memory
        _memory = Memory.from_config(_build_config())
        print("[MEMORY] mem0 initialized successfully")
        return _memory
    except Exception as e:
        import traceback
        print(f"[MEMORY] init failed, semantic memory disabled: {e!r}")
        traceback.print_exc()
        _init_failed = True
        return None


def remember(user_id: str, text: str) -> str:
    """Store a durable fact about the user. Returns a human-readable status."""
    mem = _get_memory()
    if mem is None:
        return "Memory is not configured, nothing was saved."
    try:
        result = mem.add(text, user_id=user_id)
        print(f"[MEMORY] remember(user={user_id}) -> {result}")
        return "Saved to memory."
    except Exception as e:
        import traceback
        print(f"[MEMORY] remember failed: {e!r}")
        traceback.print_exc()
        return "Could not save to memory right now."


def recall(user_id: str, query: str, limit: int = 5) -> str:
    """Search the user's memories. Returns a newline-joined list or an empty note."""
    mem = _get_memory()
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
