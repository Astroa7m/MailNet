"""Shared test setup.

The env guards here MUST run before any app.* import: app.common calls
load_dotenv() at import time, and python-dotenv does not override variables
that already exist in os.environ, so values set here win over the developer's
real .env. That keeps the offline suite deterministic (dummy keys, unreachable
Mongo) and guarantees no test can spend real provider quota by accident.
"""
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

# Unreachable Mongo with tiny timeouts: MongoClient is lazy, so imports are
# fine, and anything that does try to talk to it fails fast instead of hanging.
os.environ["MONGO_DB_URL"] = (
    "mongodb://127.0.0.1:9/?serverSelectionTimeoutMS=100&connectTimeoutMS=100"
)
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["GROQ_API_KEY"] = "gsk_test_dummy_key"
os.environ["GOOGLE_API_KEY"] = "AIza_test_dummy_key"
os.environ["REDIS_URL"] = "redis://127.0.0.1:9/0"
# Absent unless a test opts in: presence changes the shared chain and the
# memory gate, and would also let mem0's openai llm be hijacked (OPENROUTER).
os.environ.pop("NVIDIA_API_KEY", None)
os.environ.pop("SHARED_CHAT_CHAIN", None)
os.environ.pop("OPENROUTER_API_KEY", None)

# Repo root on sys.path so `from app...` and `from tests...` both resolve when
# pytest is run from anywhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
