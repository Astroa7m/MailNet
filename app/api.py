import asyncio
import base64
import datetime
import os
import re
import sys
import time
import uuid
from pathlib import Path

from typing import Optional
from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from copilotkit import LangGraphAGUIAgent
import redis.asyncio as redis
import uvicorn
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette_session import SessionMiddleware, BackendType

from bson import ObjectId
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.mongodb import MongoDBSaver
from common import encrypt_payload, decrypt_payload, refresh_microsoft_token_if_needed, refresh_google_token_if_needed, \
    build_agent, fetch_mcp_tools, get_or_create_user, db, mongo_client, content_to_text
from provider_meta import list_chat_models, validate_key, ProviderError
from logging_config import get_logger

log = get_logger("api")

load_dotenv()

# Patch a truncation bug in ag_ui_langgraph's streaming (it drops all but the
# first text part of list-shaped content, which cut off Gemini's thinking
# replies mid-sentence). See app/agui_patch.py.
from agui_patch import apply as _apply_agui_patch
_apply_agui_patch()

# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# starlette_session returns None for missing sessions instead of {}; normalise it here
@app.middleware("http")
async def ensure_session(request: Request, call_next):
    if request.scope.get("session") is None:
        request.scope["session"] = {}
    return await call_next(request)
limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("REDIS_URL"))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
async def _prewarm():
    """Pre-warm the shared mem0 instance and the LangGraph checkpointer at startup
    so the first user request doesn't pay their lazy-init costs."""
    async def _warm():
        try:
            from app.memory_store import _get_memory
            await asyncio.to_thread(_get_memory)
            log.info("semantic memory pre-warmed")
        except Exception as e:
            log.warning("memory pre-warm skipped: %r", e)
        try:
            from common import _checkpointer
            # A no-op list call forces the checkpointer to open its collection
            # and set up any TTL indexes before the first real request.
            await asyncio.to_thread(list, _checkpointer.list(config={"configurable": {"thread_id": "__prewarm__"}}))
            log.info("checkpointer pre-warmed")
        except Exception as e:
            log.warning("checkpointer pre-warm skipped: %r", e)
    asyncio.create_task(_warm())
is_not_using_copilot_kit = os.getenv("UI_PROVIDER", "custom") == "chainlit"
CHAINLIT_URL = os.getenv("CHAINLIT_URL")
JWT_SECRET = os.getenv("JWT_SECRET")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


class ChainlitAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/chat/login"):
            return await call_next(request)

        # check if user is authenticated
        user = request.session.get("user")
        if not user:
            # Not authenticated - redirect to login
            log.debug("no user in session, redirecting to login")
            return RedirectResponse(url="/", status_code=303)

        # Refresh Microsoft token if needed, right here before chainlit sees it
        encrypted_azure = request.session.get("azure_token")
        if encrypted_azure:
            try:
                azure_token = decrypt_payload(encrypted_azure)
                fresh_token = await refresh_microsoft_token_if_needed(azure_token)
                if fresh_token != azure_token:
                    log.debug("microsoft token refreshed (middleware)")
                    request.session["azure_token"] = encrypt_payload(fresh_token)
            except Exception as e:
                log.warning("microsoft token refresh failed (middleware): %r", e)

        encrypted_google = request.session.get("google_token")
        if encrypted_google:
            try:
                google_token = decrypt_payload(encrypted_google)
                if not google_token:
                    raise ValueError("google_token decrypted to None")
                fresh_google = await refresh_google_token_if_needed(google_token)
                if fresh_google != google_token:
                    log.debug("google token refreshed (middleware)")
                    request.session["google_token"] = encrypt_payload(fresh_google)
            except Exception as e:
                log.warning("google token refresh failed (middleware): %r", e)

        # user is authenticated then continue
        response = await call_next(request)
        return response


redis_client = redis.from_url(
    os.getenv("REDIS_URL"),
    encoding="utf-8",
    decode_responses=False,
)

if is_not_using_copilot_kit:
    app.add_middleware(ChainlitAuthMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET"),
    https_only=os.getenv("ENVIRONMENT") == "production",
    cookie_name="session",
    backend_type=BackendType.aioRedis,
    backend_client=redis_client,
    same_site="lax",
    max_age=86400  # 1 day
)

# for HTML template serving
templates = Jinja2Templates(directory="templates")

oauth = OAuth()

oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    authorize_params={
        "access_type": "offline",
        "prompt": "consent",
    },
    client_kwargs={
        "scope": " ".join([
            "openid",
            "email",
            "profile",
            "https://mail.google.com/",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.modify",
        ]),
        # OIDC metadata + token requests: authlib's default httpx timeout is
        # 5s, which intermittently 500s logins on slow/jittery networks.
        "timeout": 20,
    },
)

oauth.register(
    name="microsoft",
    client_id=os.getenv("AZURE_APPLICATION_CLIENT_ID"),
    client_secret=os.getenv("AZURE_SECRET_VALUE"),
    server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    client_kwargs={
        "scope": " ".join([
            "openid",
            "email",
            "profile",
            "offline_access",  # microsoft's equivalent of access_type=offline
            "https://graph.microsoft.com/Mail.ReadWrite",
            "https://graph.microsoft.com/Mail.Send",
            "https://graph.microsoft.com/MailboxSettings.ReadWrite",
            "https://graph.microsoft.com/User.Read",
        ]),
        # Same 5s-default-timeout fix as the google client above.
        "timeout": 20,
    }
)

# swtiching uis
UI_PROVIDER = os.getenv("UI_PROVIDER", "custom")

# --- /agent rate limiting -----------------------------------------------
# Two Redis-backed tiers keyed on the user id (never the IP):
#   burst: AGENT_BURST_PER_MIN requests/min for everyone, protects the server;
#   daily: AGENT_DAILY_SHARED requests/day, but only for users running on the
#          shared developer keys. Users who added their own chat key pay their
#          own provider bill, so the daily cap does not apply to them.
# Redis failures fail open: a broken limiter must never take the product down.

AGENT_BURST_PER_MIN = int(os.getenv("AGENT_BURST_PER_MIN", "10"))
AGENT_DAILY_SHARED = int(os.getenv("AGENT_DAILY_SHARED", "15"))


async def _agent_rate_limited(user_id: str, email: Optional[str] = None) -> Optional[str]:
    """Return a user-facing message when over a limit, else None."""
    try:
        # The admin is exempt from all limits (matched on either login email
        # via the session, or the account's google_email for Microsoft logins).
        if ADMIN_EMAIL and email and email.lower() == ADMIN_EMAIL.lower():
            return None
        doc = db["users"].find_one({"_id": ObjectId(user_id)}, {"api_keys.chat.key": 1, "google_email": 1})
        if ADMIN_EMAIL and ((doc or {}).get("google_email") or "").lower() == ADMIN_EMAIL.lower():
            return None

        now = datetime.datetime.now(datetime.timezone.utc)
        minute_key = f"rl:m:{user_id}:{now.strftime('%d%H%M')}"
        n = await redis_client.incr(minute_key)
        if n == 1:
            await redis_client.expire(minute_key, 120)
        if n > AGENT_BURST_PER_MIN:
            return (
                "You're sending messages faster than I can handle. "
                "Give me a minute to catch up, then try again."
            )

        has_own_key = bool((((doc or {}).get("api_keys") or {}).get("chat") or {}).get("key"))
        if not has_own_key:
            day_key = f"rl:d:{user_id}:{now.strftime('%Y%m%d')}"
            n = await redis_client.incr(day_key)
            if n == 1:
                await redis_client.expire(day_key, 172800)
            if n > AGENT_DAILY_SHARED:
                return (
                    "You've used today's free message allowance on the shared AI keys. "
                    "It resets at midnight UTC, or add your own API key in "
                    "Settings, AI Models, to keep going without limits."
                )
    except Exception as e:
        log.warning("rate limit check failed (allowing request): %r", e)
    return None


async def _rate_limit_stream(input_data: "RunAgentInput", accept: Optional[str], text: str):
    """Stream a synthetic assistant reply so a limit reads as a polite in-chat
    message instead of a broken request."""
    from ag_ui.core import (
        RunStartedEvent, TextMessageStartEvent, TextMessageContentEvent,
        TextMessageEndEvent, RunFinishedEvent,
    )
    enc = EventEncoder(accept=accept)
    run_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    for ev in [
        RunStartedEvent(type="RUN_STARTED", run_id=run_id, thread_id=input_data.thread_id or ""),
        TextMessageStartEvent(type="TEXT_MESSAGE_START", message_id=msg_id, role="assistant"),
        TextMessageContentEvent(type="TEXT_MESSAGE_CONTENT", message_id=msg_id, delta=text),
        TextMessageEndEvent(type="TEXT_MESSAGE_END", message_id=msg_id),
        RunFinishedEvent(type="RUN_FINISHED", run_id=run_id, thread_id=input_data.thread_id or ""),
    ]:
        yield enc.encode(ev)


if is_not_using_copilot_kit:
    from chainlit.utils import mount_chainlit

    mount_chainlit(app=app, target=r"C:\Users\ahmed\PycharmProjects\MailNet\app\chatting_ui.py", path="/chat")
else:
    @app.post("/agent")
    async def agent_endpoint(input_data: RunAgentInput, request: Request):
        rid = uuid.uuid4().hex[:4]
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Rate check before any token refresh, DB, or LLM work happens.
        limited = await _agent_rate_limited(user["id"], user.get("email"))
        if limited:
            log.info("[req=%s] rate limited user=%s", rid, user["id"])
            accept = request.headers.get("accept")
            enc = EventEncoder(accept=accept)
            return StreamingResponse(
                _rate_limit_stream(input_data, accept, limited),
                media_type=enc.get_content_type(),
            )

        azure_token = None
        google_token = None
        # Providers whose sign-in has expired (refresh failed). The agent is told
        # so it can ask the user to reconnect instead of silently returning empty.
        disconnected = set()

        encrypted_azure = request.session.get("azure_token")
        if encrypted_azure:
            azure_token = decrypt_payload(encrypted_azure)
            try:
                fresh = await refresh_microsoft_token_if_needed(azure_token)
                if fresh != azure_token:
                    azure_token = fresh
                    request.session["azure_token"] = encrypt_payload(fresh)
            except Exception as e:
                log.warning("[req=%s] microsoft token refresh failed: %r", rid, e)
                azure_token = None
                request.session.pop("azure_token", None)
                disconnected.add("microsoft")

        encrypted_google = request.session.get("google_token")
        if encrypted_google:
            google_token = decrypt_payload(encrypted_google)
            try:
                fresh = await refresh_google_token_if_needed(google_token)
                if fresh != google_token:
                    google_token = fresh
                    request.session["google_token"] = encrypt_payload(fresh)
            except Exception as e:
                log.warning("[req=%s] google token refresh failed: %r", rid, e)
                google_token = None
                request.session.pop("google_token", None)
                disconnected.add("google")

        # restore missing tokens from MongoDB refresh tokens (e.g. second provider after re-login)
        if not encrypted_google or not encrypted_azure:
            user_doc = db["users"].find_one(
                {"_id": ObjectId(user["id"])},
                {"google_refresh_token": 1, "microsoft_refresh_token": 1}
            )
            if user_doc:
                if not encrypted_google and user_doc.get("google_refresh_token"):
                    try:
                        stored_refresh = decrypt_payload(user_doc["google_refresh_token"])["token"]
                        minimal = {
                            "token": "", "refresh_token": stored_refresh,
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                            "scopes": ["https://mail.google.com/"],
                            "expiry": "2000-01-01T00:00:00Z",
                        }
                        google_token = await refresh_google_token_if_needed(minimal)
                        request.session["google_token"] = encrypt_payload(google_token)
                    except Exception as e:
                        log.warning("[req=%s] google token restore failed: %r", rid, e)
                        disconnected.add("google")

                if not encrypted_azure and user_doc.get("microsoft_refresh_token"):
                    try:
                        stored_refresh = decrypt_payload(user_doc["microsoft_refresh_token"])["token"]
                        minimal = {"refresh_token": stored_refresh, "expires_at": 0}
                        azure_token = await refresh_microsoft_token_if_needed(minimal)
                        request.session["azure_token"] = encrypt_payload(azure_token)
                    except Exception as e:
                        log.warning("[req=%s] microsoft token restore failed: %r", rid, e)
                        disconnected.add("microsoft")

        user_tz = request.session.get("tz", "UTC")

        # lazy thread creation, only save to DB on first message
        thread_id = input_data.thread_id
        existing_thread = db["threads"].find_one({"thread_id": thread_id}) if thread_id else None
        # The LangGraph checkpointer is keyed purely on thread_id, so a thread_id
        # belonging to another user must be rejected before the graph loads its
        # conversation history. Otherwise one user could read or continue another
        # user's thread just by knowing its id.
        if existing_thread and existing_thread.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="You do not have access to this conversation")
        if thread_id and not existing_thread:
            title = "New conversation"
            user_msgs = [m for m in input_data.messages if m.role == "user"]
            if user_msgs:
                content = user_msgs[-1].content
                if isinstance(content, str):
                    title = content[:60].strip() or title
                elif isinstance(content, list):
                    for part in content:
                        if hasattr(part, "text") and part.text:
                            title = part.text[:60].strip() or title
                            break
            # The proactive "catch me up" briefing is a long fixed prompt; give it
            # a clean sidebar title instead of the raw instruction text.
            if title.startswith("Give me a quick briefing"):
                title = "Inbox briefing"
            db["threads"].insert_one({
                "thread_id": thread_id,
                "user_id": user["id"],
                "name": title,
                "created_at": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
            })

        # Extract the last user message text for proactive recall.
        last_user_text = ""
        for m in reversed(input_data.messages):
            if m.role == "user":
                c = m.content
                if isinstance(c, str):
                    last_user_text = c
                elif isinstance(c, list):
                    last_user_text = " ".join(
                        (p.get("text") if isinstance(p, dict) else getattr(p, "text", "")) or ""
                        for p in c
                        if (p.get("type") if isinstance(p, dict) else getattr(p, "type", None)) == "text"
                    )
                break

        async def _do_recall() -> str:
            if not last_user_text.strip():
                return ""
            try:
                from app.memory_store import recall as _recall
                ep_provider, ep_key = _user_embed_config(user["id"])
                return await asyncio.to_thread(
                    _recall, user["id"], last_user_text, provider=ep_provider, api_key=ep_key
                )
            except Exception as e:
                log.warning("[req=%s] proactive recall failed: %r", rid, e)
                return ""

        conn = "+".join(p for p, t in (("google", google_token), ("microsoft", azure_token)) if t) or "none"
        log.info(
            "[req=%s] message user=%s thread=%s msg=%r connected=%s tz=%s",
            rid, user["id"], (thread_id or "")[:8],
            (last_user_text or "")[:80], conn, user_tz,
        )

        # Fetch MCP tools and recall in parallel (both independent of each other).
        _t_parallel = time.time()
        # default_provider lives in the DB user doc, not the session `user` dict
        # (which only holds id/email/name/picture/provider). Reading it from the
        # session always yielded "google", so a user whose default is Outlook was
        # silently routed to Gmail. Read it from the DB so the MCP header is right.
        _pref_doc = db["users"].find_one(
            {"_id": ObjectId(user["id"])}, {"preferences.default_provider": 1}
        )
        user_default_provider = ((_pref_doc or {}).get("preferences") or {}).get("default_provider", "google")
        log.info("[req=%s] default_provider=%s", rid, user_default_provider)
        (recalled_context, mcp_tools) = await asyncio.gather(
            _do_recall(),
            fetch_mcp_tools(azure_token, google_token, user_default_provider),
        )
        log.info("[req=%s] recall+MCP ready in %.2fs", rid, time.time() - _t_parallel)

        # Build agent with pre-fetched tools and recalled context (no extra round-trips).
        graph = await build_agent(
            azure_token, google_token, user_tz, user_id=user["id"],
            disconnected=disconnected, recalled_context=recalled_context,
            prefetched_mcp_tools=mcp_tools,
        )

        agent = LangGraphAGUIAgent(name="Mailing Agent", description="Helps with everyday mailing tasks", graph=graph)

        def _flatten_content(content) -> str:
            """Flatten multimodal content list to a plain string (Groq only accepts strings)."""
            if isinstance(content, str):
                return content
            if not isinstance(content, list):
                return str(content)
            text_parts = []
            file_parts = []
            for part in content:
                t = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
                if t == "text":
                    text = part.get("text") if isinstance(part, dict) else getattr(part, "text", "")
                    text_parts.append(text or "")
                elif t in ("image", "image_url", "file", "url", "document", "audio", "video", "binary"):
                    if isinstance(part, dict):
                        source = part.get("source") or {}
                        val = (source.get("value") if isinstance(source, dict) else getattr(source, "value", "")) \
                              or (part.get("image_url") or {}).get("url") or part.get("url") or part.get("value", "")
                        fname = (part.get("metadata") or {}).get("filename", "")
                    else:
                        source = getattr(part, "source", None)
                        val = getattr(source, "value", "") if source else ""
                        fname = (getattr(part, "metadata", None) or {}).get("filename", "")
                    # Strip the attachment-raw URL prefix, keeping only the file_id UUID
                    if "/attachment-raw/" in val:
                        val = val.split("/attachment-raw/")[-1]
                    label = f" ({fname})" if fname else ""
                    file_parts.append(f"[Attached file ID: {val}{label}]")
            result = " ".join(text_parts)
            if file_parts:
                result += "\n\n" + "\n".join(file_parts)
            return result.strip()

        def _normalize_msg(m):
            if isinstance(m.content, (list, tuple)):
                return m.model_copy(update={"content": _flatten_content(m.content)})
            return m

        filtered_input = input_data.model_copy(
            update={"messages": [_normalize_msg(m) for m in input_data.messages if m.role != "reasoning"]}
        )

        async def _safe_run():
            _t_run = time.time()
            _first = True
            # Per-message text accumulation + tool tracking, so we can see exactly
            # what the agent streamed and where it stopped if output is incomplete.
            text_len: dict = {}        # message_id -> chars streamed
            tool_names: dict = {}      # tool_call_id -> name
            args_seen: set = set()     # tool_call_ids whose args deltas we logged
            n_events = 0
            try:
                async for e in agent.run(filtered_input):
                    n_events += 1
                    etype = getattr(e, "type", "")
                    if _first:
                        log.info("[req=%s] first event in %.2fs", rid, time.time() - _t_run)
                        _first = False

                    if etype == "TEXT_MESSAGE_CONTENT":
                        mid = getattr(e, "message_id", "")
                        text_len[mid] = text_len.get(mid, 0) + len(getattr(e, "delta", "") or "")
                    elif etype == "TEXT_MESSAGE_END":
                        mid = getattr(e, "message_id", "")
                        log.info("[req=%s] text message done chars=%d", rid, text_len.get(mid, 0))
                    elif etype == "TOOL_CALL_START":
                        name = getattr(e, "tool_call_name", "?")
                        tcid = getattr(e, "tool_call_id", "")
                        tool_names[tcid] = name
                        log.info("[req=%s] tool call -> %s", rid, name)
                    elif etype == "TOOL_CALL_ARGS":
                        tcid = getattr(e, "tool_call_id", "")
                        if tcid not in args_seen:
                            args_seen.add(tcid)
                            log.info("[req=%s] tool args streaming for %s (first delta: %r)", rid, tool_names.get(tcid, "?"), str(getattr(e, "delta", ""))[:80])
                    elif etype == "TOOL_CALL_RESULT":
                        tcid = getattr(e, "tool_call_id", "")
                        content = getattr(e, "content", "") or ""
                        preview = str(content).replace("\n", " ")[:120]
                        log.info("[req=%s] tool result <- %s: %s", rid, tool_names.get(tcid, "?"), preview)
                    elif etype == "RUN_ERROR":
                        log.error("[req=%s] RUN_ERROR: %s", rid, getattr(e, "message", e))
                    elif etype == "RUN_FINISHED":
                        total = sum(text_len.values())
                        log.info(
                            "[req=%s] run finished in %.2fs events=%d text_chars=%d tools=%d",
                            rid, time.time() - _t_run, n_events, total, len(tool_names),
                        )

                    yield encoder.encode(e)
            except Exception as exc:
                msg = str(exc)
                if "not in request.tools" in msg or "tool call validation" in msg.lower():
                    log.warning("[req=%s] stale-tool history, surfacing reset message: %s", rid, msg[:400])
                    # Old conversation history references a removed tool, so surface a clean error
                    from ag_ui.core import RunStartedEvent, TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent, RunFinishedEvent
                    import time as _time
                    ts = int(_time.time() * 1000)
                    run_id = str(uuid.uuid4())
                    msg_id = str(uuid.uuid4())
                    for ev in [
                        RunStartedEvent(type="RUN_STARTED", run_id=run_id, thread_id=filtered_input.thread_id or ""),
                        TextMessageStartEvent(type="TEXT_MESSAGE_START", message_id=msg_id, role="assistant"),
                        TextMessageContentEvent(type="TEXT_MESSAGE_CONTENT", message_id=msg_id, delta="This conversation contains history from an older version of the assistant that is no longer compatible. Please start a new conversation."),
                        TextMessageEndEvent(type="TEXT_MESSAGE_END", message_id=msg_id),
                        RunFinishedEvent(type="RUN_FINISHED", run_id=run_id, thread_id=filtered_input.thread_id or ""),
                    ]:
                        yield encoder.encode(ev)
                else:
                    log.exception("[req=%s] agent run crashed after %d events: %r", rid, n_events, exc)
                    raise

        encoder = EventEncoder(accept=request.headers.get("accept"))
        return StreamingResponse(
            _safe_run(),  # type: ignore
            media_type=encoder.get_content_type()
        )


    @app.get("/agent/health")
    def agent_health():
        return {"status": "ok", "agent": {"name": "Mailing Agent"}}


@app.post("/tz")
async def set_timezone(request: Request):
    data = await request.json()
    tz = data.get("tz", "UTC")
    request.session["tz"] = tz
    return {"tz": tz}


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/")
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page_direct(request: Request):
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})


# --- Gmail tester-access requests -------------------------------------------
# While the app is in Google's testing mode, Gmail sign-in only works for
# manually-added test users. Visitors ask for access via a form on the login
# page; each request is stored in Mongo (source of truth) and a best-effort
# notification email is sent to the admin using the admin's own stored Google
# refresh token. ADMIN_EMAIL must be the admin user's google_email.

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _notify_admin_tester_request(requester_email: str):
    if not ADMIN_EMAIL:
        log.warning("tester-request: ADMIN_EMAIL not set, skipping notification")
        return
    try:
        admin = db["users"].find_one({"google_email": ADMIN_EMAIL})
        if not admin or not admin.get("google_refresh_token"):
            log.warning("tester-request: no stored admin refresh token, skipping email")
            return
        refresh_token = decrypt_payload(admin["google_refresh_token"])["token"]
        token = {
            "token": "",
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "scopes": ["https://mail.google.com/"],
            # expiry in the past forces a refresh into a fresh access token
            "expiry": "2000-01-01T00:00:00Z",
        }
        token = await refresh_google_token_if_needed(token)

        from langchain_mcp_adapters.client import MultiServerMCPClient
        mcp = MultiServerMCPClient({
            "email_mcp": {
                "transport": "streamable_http",
                "url": os.getenv("MAILNET_SERVER_URL", "http://localhost:9111/mcp"),
                "headers": {
                    "redirect_uri": "http://localhost/",
                    "default_provider": "google",
                    "google_token": encrypt_payload(token),
                },
            }
        })
        tools = await mcp.get_tools()
        send_tool = next((t for t in tools if t.name == "send_email"), None)
        if not send_tool:
            raise RuntimeError("send_email tool not found on MCP server")
        await send_tool.ainvoke({
            "to": ADMIN_EMAIL,
            "subject": f"MailNet tester request: {requester_email}",
            "body": (
                f"{requester_email} asked for Gmail tester access.\n\n"
                "Add them in Google Cloud Console -> OAuth consent screen -> "
                "Test users, then let them know they're in."
            ),
        })
        log.info("tester-request: notification sent for %s", requester_email)
    except Exception as e:
        # Never fail the request over the courtesy email; Mongo has the record.
        log.warning("tester-request: notification failed for %s: %r", requester_email, e)


@app.post("/tester-request")
@limiter.limit("5/hour")
async def tester_request(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Please enter a valid email address")
    existing = db["tester_requests"].find_one({"email": email})
    if existing:
        return {"ok": True, "message": "You're already on the list. Hang tight!"}
    db["tester_requests"].insert_one({
        "email": email,
        "status": "pending",
        "created_at": datetime.datetime.now(datetime.UTC),
    })
    background_tasks.add_task(_notify_admin_tester_request, email)
    return {"ok": True, "message": "Request received! You'll get an email once you're added."}


@app.get("/tester-requests")
async def list_tester_requests(request: Request):
    user = request.session.get("user")
    if not user or not ADMIN_EMAIL or user.get("email") != ADMIN_EMAIL:
        raise HTTPException(status_code=404, detail="Not found")
    rows = list(db["tester_requests"].find({}, {"_id": 0}).sort("created_at", -1))
    for r in rows:
        if isinstance(r.get("created_at"), datetime.datetime):
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M UTC")
    return {"requests": rows, "count": len(rows)}


@app.get("/me")
async def get_me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"providers": 1})
    providers = user_doc.get("providers", [user.get("provider", "google")]) if user_doc else [user.get("provider", "google")]
    return {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "picture": user.get("picture", ""),
        "providers": providers,
    }


@app.get("/connection-status")
async def connection_status(request: Request):
    """Live health of each linked mailbox. Being in `providers` only means the
    account was linked once; the OAuth token can still be expired (invalid_grant).
    We probe by forcing a refresh with the stored refresh token, so the UI can
    show "Connected" vs "Reconnect needed" accurately instead of always-connected."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    doc = db["users"].find_one(
        {"_id": ObjectId(user["id"])},
        {"providers": 1, "google_refresh_token": 1, "microsoft_refresh_token": 1},
    )
    if not doc:
        return {}
    providers = doc.get("providers", [])
    status: dict[str, str] = {}

    if "google" in providers:
        if doc.get("google_refresh_token"):
            try:
                stored = decrypt_payload(doc["google_refresh_token"])["token"]
                minimal = {
                    "token": "", "refresh_token": stored,
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "scopes": ["https://mail.google.com/"],
                    "expiry": "2000-01-01T00:00:00Z",
                }
                await refresh_google_token_if_needed(minimal)
                status["google"] = "connected"
            except Exception as e:
                log.info("connection-status: google expired (%r)", e)
                status["google"] = "expired"
        else:
            status["google"] = "expired"

    if "microsoft" in providers:
        if doc.get("microsoft_refresh_token"):
            try:
                stored = decrypt_payload(doc["microsoft_refresh_token"])["token"]
                await refresh_microsoft_token_if_needed({"refresh_token": stored, "expires_at": 0})
                status["microsoft"] = "connected"
            except Exception as e:
                log.info("connection-status: microsoft expired (%r)", e)
                status["microsoft"] = "expired"
        else:
            status["microsoft"] = "expired"

    return status


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")
        return RedirectResponse(url=FRONT_END_URL)
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


def _oauth_redirect_uri(request: Request, name: str) -> str:
    """Build the OAuth callback URL for the given route.

    Behind a reverse proxy (e.g. on AWS) the request's scheme/host are the
    internal ones, so request.url_for() yields an http:// internal URL that
    Google/Azure reject. When PUBLIC_URL is set (the API's public origin, e.g.
    https://api.example.com) we keep the resolved path but swap in the public
    scheme + host so redirect_uri matches what's registered with the provider.
    Locally PUBLIC_URL is unset and we fall back to url_for() unchanged.
    """
    uri = str(request.url_for(name))
    public = os.getenv("PUBLIC_URL")
    if public:
        from urllib.parse import urlsplit, urlunsplit
        pub = urlsplit(public)
        parts = urlsplit(uri)
        uri = urlunsplit((pub.scheme, pub.netloc, parts.path, parts.query, parts.fragment))
    return uri


# Google
@app.get("/login/google")
@limiter.limit("20/minute")
async def login_google(request: Request):
    request.session["tz"] = request.query_params.get("tz", "UTC")
    redirect_uri = _oauth_redirect_uri(request, "auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google", name="auth_google")
@limiter.limit("20/minute")
async def auth_google(request: Request):
    token = await oauth.google.authorize_access_token(request)

    granted_scopes = set(token.get("scope", "").split())
    is_connecting = request.session.pop("connecting", False)
    if "https://mail.google.com/" not in granted_scopes:
        dest = os.getenv("FRONTEND_URL", "http://localhost:3000") if is_connecting else "/"
        return RedirectResponse(url=f"{dest}?error=missing_scopes")

    user_info = token.get("userinfo")
    email = user_info["email"]
    refresh_token = token.get("refresh_token")

    google_token_json = {
        "token": token["access_token"],
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "scopes": token["scope"].split(" "),
        "expiry": datetime.datetime.fromtimestamp(token["expires_at"], datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    if is_connecting:
        # linking flow: attach google account to existing user
        if refresh_token:
            db["users"].update_one(
                {"_id": ObjectId(request.session["user"]["id"])},
                {"$set": {"google_refresh_token": encrypt_payload({"token": refresh_token})}}
            )
        else:
            user_doc = db["users"].find_one({"_id": ObjectId(request.session["user"]["id"])})
            if user_doc and user_doc.get("google_refresh_token"):
                refresh_token = decrypt_payload(user_doc["google_refresh_token"])["token"]
                google_token_json["refresh_token"] = refresh_token

        # TODO: merge orphan document if another user already has this google_email
        db["users"].update_one(
            {"_id": ObjectId(request.session["user"]["id"])},
            {"$set": {"google_email": email}, "$addToSet": {"providers": "google"}}
        )
        request.session["google_token"] = encrypt_payload(google_token_json)
        FRONT_END_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    else:
        # normal login flow
        name = user_info.get("name", "")
        picture = user_info.get("picture", "")
        user = get_or_create_user(email, name, picture, "google")
        request.session["user"] = {
            "id": user["_id"], "email": email,
            "name": name, "picture": picture, "provider": "google",
        }
        if refresh_token:
            db["users"].update_one(
                {"google_email": email},
                {"$set": {"google_refresh_token": encrypt_payload({"token": refresh_token})}}
            )
        else:
            user_doc = db["users"].find_one({"google_email": email})
            if user_doc and user_doc.get("google_refresh_token"):
                refresh_token = decrypt_payload(user_doc["google_refresh_token"])["token"]
                google_token_json["refresh_token"] = refresh_token

        request.session["google_token"] = encrypt_payload(google_token_json)
        FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")

    return RedirectResponse(url=FRONT_END_URL)


# Microsoft
@app.get("/login/microsoft")
@limiter.limit("20/minute")
async def login_microsoft(request: Request):
    request.session["tz"] = request.query_params.get("tz", "UTC")
    redirect_uri = _oauth_redirect_uri(request, "auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@app.get("/auth/microsoft", name="auth_microsoft")
@limiter.limit("20/minute")
async def auth_microsoft(request: Request):
    try:
        token = await oauth.microsoft.authorize_access_token(
            request,
            claims_options={"iss": {"essential": False}}
        )

        granted_scopes = token.get("scope", "")
        is_connecting = request.session.pop("connecting", False)
        if "Mail.ReadWrite" not in granted_scopes and "Mail.Send" not in granted_scopes:
            dest = os.getenv("FRONTEND_URL", "http://localhost:3000") if is_connecting else "/"
            return RedirectResponse(url=f"{dest}?error=missing_scopes")

        user_info = token.get("userinfo")
        email = user_info.get("email") or user_info.get("preferred_username", "")
        refresh_token = token.get("refresh_token")

        if is_connecting:
            # linking flow: attach microsoft account to existing user
            set_fields = {"outlook_email": email}
            if refresh_token:
                set_fields["microsoft_refresh_token"] = encrypt_payload({"token": refresh_token})

            # TODO: merge orphan document if another user already has this outlook_email
            db["users"].update_one(
                {"_id": ObjectId(request.session["user"]["id"])},
                {"$set": set_fields, "$addToSet": {"providers": "microsoft"}}
            )
            request.session["azure_token"] = encrypt_payload(dict(token))
            FRONT_END_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
        else:
            # normal login flow
            name = user_info.get("name", "")
            picture = user_info.get("picture", "")
            user = get_or_create_user(email, name, picture, "microsoft")
            request.session["user"] = {
                "id": user["_id"], "email": email,
                "name": name, "picture": picture, "provider": "microsoft",
            }
            if refresh_token:
                db["users"].update_one(
                    {"outlook_email": email},
                    {"$set": {"microsoft_refresh_token": encrypt_payload({"token": refresh_token})}}
                )
            request.session["azure_token"] = encrypt_payload(dict(token))
            FRONT_END_URL = "/chat" if is_not_using_copilot_kit else os.getenv("FRONTEND_URL")

        return RedirectResponse(url=FRONT_END_URL)
    except OAuthError:
        return RedirectResponse(url="/")


@app.get("/connect/google")
async def connect_google(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.session["connecting"] = True
    redirect_uri = _oauth_redirect_uri(request, "auth_google")
    return await oauth.google.authorize_redirect(request, redirect_uri, prompt="select_account consent")


@app.get("/connect/microsoft")
async def connect_microsoft(request: Request):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.session["connecting"] = True
    redirect_uri = _oauth_redirect_uri(request, "auth_microsoft")
    return await oauth.microsoft.authorize_redirect(request, redirect_uri, prompt="select_account")


@app.get("/preferences")
async def get_preferences(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"preferences": 1})
    if not user_doc or "preferences" not in user_doc:
        from common import DEFAULT_PREFERENCES
        return DEFAULT_PREFERENCES.copy()
    return user_doc["preferences"]


@app.patch("/preferences")
async def update_preferences(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    updates = await request.json()
    set_fields = {f"preferences.{k}": v for k, v in updates.items()}
    db["users"].update_one({"_id": ObjectId(user["id"])}, {"$set": set_fields})
    return {"ok": True}


# Bring-your-own-key: which providers are valid for each slot.
CHAT_PROVIDERS = {"groq", "google_genai", "openai", "anthropic", "ollama_cloud"}
EMBED_PROVIDERS = {"google", "openai", "ollama"}

# Shared (developer) keys available per provider. Only Groq and Google are
# provided by the app; for the rest the user must bring their own key.
SHARED_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama_cloud": "OLLAMA_API_KEY",
    "google": "GOOGLE_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}


def _shared_key_for(provider: str) -> Optional[str]:
    env = SHARED_KEY_ENV.get(provider)
    return os.getenv(env) if env else None


@app.get("/api-keys")
async def get_api_keys(request: Request):
    """Return the user's saved provider/model choices, never the raw keys."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"api_keys": 1})
    api_keys = (doc or {}).get("api_keys") or {}
    chat = api_keys.get("chat") or {}
    emb = api_keys.get("embeddings") or {}
    return {
        "chat": {
            "provider": chat.get("provider"),
            "model": chat.get("model"),
            "has_key": bool(chat.get("key")),
        },
        "embeddings": {
            "provider": emb.get("provider"),
            "has_key": bool(emb.get("key")),
        },
    }


@app.put("/api-keys")
async def put_api_keys(request: Request):
    """Save chat and/or embeddings provider + key. Keys are encrypted at rest.

    If a key is omitted for a slot we keep the stored one when the provider is
    unchanged; if the provider changed without a new key we drop the stale key
    so the user is prompted to add a matching one.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    body = await request.json()

    doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"api_keys": 1})
    existing = (doc or {}).get("api_keys") or {}
    new_keys = dict(existing)

    if body.get("chat") is not None:
        c = body["chat"]
        provider = c.get("provider")
        if provider not in CHAT_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Invalid chat provider: {provider}")
        prev = existing.get("chat") or {}
        model = (c.get("model") or "").strip() or None
        raw_key = (c.get("key") or "").strip()
        # Validate the effective key+model with a real call before persisting, so
        # an invalid key or retired model never gets saved.
        kept_key = prev["key"] if prev.get("key") and prev.get("provider") == provider else None
        effective_key = raw_key or (decrypt_payload(kept_key)["key"] if kept_key else None)
        if effective_key:
            ok, reason, msg = await asyncio.to_thread(validate_key, provider, effective_key, "chat", model)
            if not ok:
                raise HTTPException(status_code=400, detail={"slot": "chat", "reason": reason, "message": msg})
        slot = {"provider": provider, "model": model}
        if raw_key:
            slot["key"] = encrypt_payload({"key": raw_key})
        elif kept_key:
            slot["key"] = kept_key
        new_keys["chat"] = slot

    if body.get("embeddings") is not None:
        e = body["embeddings"]
        provider = e.get("provider")
        if provider not in EMBED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Invalid embeddings provider: {provider}")
        prev = existing.get("embeddings") or {}
        raw_key = (e.get("key") or "").strip()
        kept_key = prev["key"] if prev.get("key") and prev.get("provider") == provider else None
        effective_key = raw_key or (decrypt_payload(kept_key)["key"] if kept_key else None)
        if effective_key:
            ok, reason, msg = await asyncio.to_thread(validate_key, provider, effective_key, "embeddings")
            if not ok:
                raise HTTPException(status_code=400, detail={"slot": "embeddings", "reason": reason, "message": msg})
        slot = {"provider": provider}
        if raw_key:
            slot["key"] = encrypt_payload({"key": raw_key})
        elif kept_key:
            slot["key"] = kept_key
        new_keys["embeddings"] = slot

    db["users"].update_one({"_id": ObjectId(user["id"])}, {"$set": {"api_keys": new_keys}})
    return {"ok": True}


@app.post("/provider-models")
async def provider_models(request: Request):
    """Validate a key and (for chat) list its available models.

    Used by Settings to populate the model dropdown and to give immediate
    feedback before the user saves. Uses the posted key if present, otherwise
    the user's saved key for that slot, otherwise the shared developer key.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    body = await request.json()
    slot = body.get("slot")
    provider = body.get("provider")
    key = (body.get("key") or "").strip() or None

    if slot not in ("chat", "embeddings"):
        raise HTTPException(status_code=400, detail="Unknown slot")
    valid_providers = CHAT_PROVIDERS if slot == "chat" else EMBED_PROVIDERS
    if provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Invalid {slot} provider: {provider}")

    if not key:
        doc = db["users"].find_one({"_id": ObjectId(user["id"])}, {"api_keys": 1})
        saved = ((doc or {}).get("api_keys") or {}).get(slot) or {}
        if saved.get("provider") == provider and saved.get("key"):
            key = decrypt_payload(saved["key"])["key"]
    if not key:
        key = _shared_key_for(provider)
    if not key:
        return {"ok": False, "reason": "error", "message": "No API key available for this provider yet. Paste your key above."}

    if slot == "chat":
        try:
            models = await asyncio.to_thread(list_chat_models, provider, key)
            return {"ok": True, "models": models}
        except ProviderError as e:
            return {"ok": False, "reason": e.reason, "message": e.message}
        except Exception as e:
            return {"ok": False, "reason": "error", "message": str(e)[:200]}
    else:
        ok, reason, msg = await asyncio.to_thread(validate_key, provider, key, "embeddings")
        return {"ok": True} if ok else {"ok": False, "reason": reason, "message": msg}


@app.delete("/api-keys/{slot}")
async def delete_api_key(slot: str, request: Request):
    """Remove a saved key slot, reverting that capability to the shared key."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if slot not in ("chat", "embeddings"):
        raise HTTPException(status_code=404, detail="Unknown key slot")
    db["users"].update_one({"_id": ObjectId(user["id"])}, {"$unset": {f"api_keys.{slot}": ""}})
    return {"ok": True}


def _user_embed_config(user_id: str):
    """Resolve a user's smart-features (embeddings) provider + decrypted key, or
    (None, None) to use the shared default. Mirrors build_agent."""
    doc = db["users"].find_one({"_id": ObjectId(user_id)}, {"api_keys": 1})
    cfg = ((doc or {}).get("api_keys") or {}).get("embeddings") or {}
    provider = cfg.get("provider")
    if provider and cfg.get("key"):
        try:
            return provider, decrypt_payload(cfg["key"])["key"]
        except Exception:
            return None, None
    return None, None


@app.get("/memories")
async def get_memories(request: Request):
    """List the signed-in user's stored long-term memories."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.memory_store import list_memories
    provider, key = _user_embed_config(user["id"])
    items = await asyncio.to_thread(list_memories, user["id"], provider=provider, api_key=key)
    return {"memories": items}


@app.delete("/memories/{memory_id}")
async def remove_memory(memory_id: str, request: Request):
    """Delete one of the user's memories by id."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.memory_store import delete_memory
    provider, key = _user_embed_config(user["id"])
    ok = await asyncio.to_thread(delete_memory, memory_id, provider=provider, api_key=key)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not delete memory")
    return {"ok": True}


@app.delete("/memories")
async def clear_all_memories(request: Request):
    """Delete all of the user's memories."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.memory_store import clear_memories
    provider, key = _user_embed_config(user["id"])
    ok = await asyncio.to_thread(clear_memories, user["id"], provider=provider, api_key=key)
    return {"ok": ok}


@app.get("/threads")
async def get_threads(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    threads = list(db["threads"].find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("created_at", -1))
    return threads


@app.post("/threads")
async def create_thread(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    thread = {
        "thread_id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": "New conversation",
        "created_at": int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    }
    db["threads"].insert_one(thread)
    thread.pop("_id", None)
    return thread


@app.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = db["threads"].delete_one({"thread_id": thread_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True}


# Tool calls that are internal mechanics, not user-facing actions, so they are
# never rendered in the chat history (mirrors HIDDEN_TOOLS in the frontend).
_HIDDEN_TOOL_NAMES = {
    "recall_user_context", "remember_user_fact",
    "search_tools", "load_tools", "unload_tools",
}


@app.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not db["threads"].find_one({"thread_id": thread_id, "user_id": user["id"]}):
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        checkpointer = MongoDBSaver(mongo_client, db_name="MailNet")
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.to_thread(checkpointer.get_tuple, config)
        if not checkpoint_tuple:
            return []

        messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])

        # Pre-index tool results by tool_call_id
        tool_results: dict[str, str] = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_results[msg.tool_call_id] = content_to_text(msg.content)[:500]

        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                result.append({"id": str(msg.id), "role": "user", "content": content_to_text(msg.content)})
            elif isinstance(msg, AIMessage) and msg.tool_calls:
                # An AIMessage can carry BOTH a text line and tool calls (the
                # PROGRESS UPDATES prompt makes the model say "Checking your inbox
                # now." then call a tool in the same message). Render that text
                # first so it survives a thread reload, then the tool-call cards.
                text = content_to_text(msg.content)
                if text.strip():
                    result.append({"id": str(msg.id), "role": "assistant", "content": text})
                else:
                    result.append({"id": str(msg.id), "role": "_suppress", "content": ""})
                # One renderable entry per tool call (id = tool_call_id, used by CopilotKit).
                # Skip the deferred-loading plumbing tools, which are internal mechanics.
                for tc in msg.tool_calls:
                    if tc["name"] in _HIDDEN_TOOL_NAMES:
                        continue
                    result.append({
                        "id": tc["id"],
                        "role": "tool_call",
                        "content": tc["name"],
                        "args": tc.get("args", {}),
                        "result": tool_results.get(tc["id"], ""),
                    })
            elif isinstance(msg, AIMessage) and msg.content:
                text = content_to_text(msg.content)
                if text.strip():
                    result.append({"id": str(msg.id), "role": "assistant", "content": text})
                else:
                    result.append({"id": str(msg.id), "role": "_suppress", "content": ""})
            elif isinstance(msg, ToolMessage):
                # Suppress ToolMessage since the result is already embedded in the tool_call entry
                result.append({"id": str(msg.id), "role": "_suppress", "content": ""})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load messages: {str(e)}")


# ── Attachment temp store ─────────────────────────────────────────────────────
_attachment_store: dict[str, dict] = {}
_ATTACHMENT_TTL = 3600  # 1 hour


def _purge_old_attachments():
    cutoff = time.time() - _ATTACHMENT_TTL
    stale = [k for k, v in _attachment_store.items() if v["uploaded_at"] < cutoff]
    for k in stale:
        del _attachment_store[k]


@app.post("/upload-attachment")
async def upload_attachment(request: Request, file: Optional[UploadFile] = File(None)):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if file is None:
        raise HTTPException(status_code=422, detail="No file provided")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit")

    _purge_old_attachments()
    file_id = str(uuid.uuid4())
    _attachment_store[file_id] = {
        "filename": file.filename or "attachment",
        "mimeType": file.content_type or "application/octet-stream",
        "data": base64.b64encode(content).decode(),
        "size": len(content),
        "uploaded_at": time.time(),
        "user_id": user["id"],
    }
    return {
        "file_id": file_id,
        "filename": file.filename,
        "mimeType": file.content_type,
        "size": len(content),
    }


@app.get("/attachment/{file_id}")
async def get_attachment(file_id: str):
    att = _attachment_store.get(file_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found or expired")
    return {"filename": att["filename"], "mimeType": att["mimeType"], "data": att["data"]}


@app.get("/attachment-raw/{file_id}")
async def get_attachment_raw(file_id: str):
    """Returns the raw file bytes, used by CopilotKit for image previews."""
    att = _attachment_store.get(file_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found or expired")
    raw = base64.b64decode(att["data"])
    return Response(content=raw, media_type=att["mimeType"])


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8002)
