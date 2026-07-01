"""Central logging setup for the API.

Goals: one place to configure log level and format, concise grep-friendly lines,
and silenced third-party noise (httpx, mem0, google genai schema warnings, the
uvicorn access log) so the signal we care about (requests, the agent event
stream, tool calls, errors) is actually readable in `docker compose logs`.

Every log line for a single chat request carries a short `req=<id>` tag so you
can follow one conversation turn end to end with:  docker compose logs api | grep req=ab12
"""
import logging
import os
import sys

# Loggers that flood the console with per-call noise. Pinned to WARNING so real
# problems still surface but routine chatter does not.
_NOISY = (
    "httpx",
    "httpcore",
    "mem0",
    "mem0.vector_stores.mongodb",
    "langchain_google_genai",
    "langchain_google_genai._function_utils",
    "google_genai",
    "google.genai",
    "mcp.client.streamable_http",
    "uvicorn.access",
    "pymongo",
    "asyncio",
)

_CONFIGURED = False


def setup_logging() -> None:
    """Configure the root logger once. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-5s %(name)-9s %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger (e.g. 'agent', 'memory', 'auth')."""
    setup_logging()
    return logging.getLogger(name)
