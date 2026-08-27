import datetime
import json
import os
import sys
import time
from pathlib import Path
from string import Template
from typing import Optional, Literal
from zoneinfo import ZoneInfo

from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from bson import ObjectId
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call, wrap_model_call
from langchain_core.messages import ToolMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, Field
from langgraph.types import interrupt
from langgraph.errors import GraphInterrupt

from app.extra_tools import schedule_send_email, schedule_recurring_email
from app.memory_store import remember as memory_remember, forget as memory_forget
from app.llm_errors import classify_provider_error, quota_message, auth_message, generic_message
from app.logging_config import get_logger
from app.dynamic_tools import build_dynamic_toolset, DynamicToolState, coerce_tool

log = get_logger("agent")

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

mongo_client = MongoClient(os.getenv("MONGO_DB_URL"))
db = mongo_client["MailNet"]

# The checkpointer is built lazily: MongoDBSaver's constructor creates indexes,
# which opens a real connection, and doing that at import time meant the module
# could not even be imported (tests, tooling, a container starting before
# Atlas is reachable) without a live database.
_checkpointer_inst = None


def _get_checkpointer():
    global _checkpointer_inst
    if _checkpointer_inst is None:
        _checkpointer_inst = MongoDBSaver(mongo_client, db_name="MailNet")
    return _checkpointer_inst


def __getattr__(name):
    # PEP 562: keeps `from common import _checkpointer` working lazily for the
    # existing call sites in api.py without connecting at import.
    if name == "_checkpointer":
        return _get_checkpointer()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

DEFAULT_PREFERENCES = {
    "language": "en",
    "tone": "formal",
    "writing_style": "clear_and_concise",
    "sender_name": "",
    "organization_name": "",
    "include_signature": True,
    "signature": "Best regards,\n{{sender_name}}",
    "preferred_greeting": "Dear {{recipient_name}},",
    "auto_adjust_tone": True,
    "include_thread_context": True,
    "character_limit": 1000,
    "default_provider": "google",
    "auto_approve_tools": [],
}

# Chat providers the user can pick in Settings → AI Models. Default model per
# provider is used when the user does not supply a model override.
DEFAULT_CHAT_MODELS = {
    "nvidia": "openai/gpt-oss-120b",
    "groq": "openai/gpt-oss-120b",
    "google_genai": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "ollama_cloud": "gpt-oss:120b",
}

# Providers for which the app ships a shared developer key, so a user can pick
# them without pasting their own key. Maps provider -> env var holding the key.
# NVIDIA powers the default chat when its key is set, with Groq and Google as
# the failover hops behind it.
# Upper bound for user-writable preference text that is echoed into the prompt.
_PREF_TEXT_MAX = 400

SHARED_CHAT_KEYS = {
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}

# Failover order for the app's shared keys. The first provider whose key is
# present becomes the default primary; the rest are failover hops, walked in
# order by the model-error middleware. Operators can reorder or drop providers
# per deploy without a rebuild, e.g. SHARED_CHAT_CHAIN=groq,google_genai takes
# NVIDIA out of rotation. Unknown names and providers with no key set are
# skipped, so simply not setting NVIDIA_API_KEY reproduces the pre-NVIDIA
# behavior (Groq primary, Gemini failover) exactly.
_DEFAULT_SHARED_CHAIN = "nvidia,groq,google_genai"


def _shared_chain() -> list:
    """Providers from SHARED_CHAT_CHAIN that have a shared key set, in order."""
    raw = os.getenv("SHARED_CHAT_CHAIN", _DEFAULT_SHARED_CHAIN)
    return [
        p.strip() for p in raw.split(",")
        if p.strip() in SHARED_CHAT_KEYS and os.getenv(SHARED_CHAT_KEYS[p.strip()])
    ]


def _build_shared_llm(provider: str):
    """A chat model backed by one of the app's shared keys, tuned to fail fast.

    Groq keeps max_retries=0 so a rate-limited shared key fails in about a
    second and the failover chain advances, instead of the SDK silently
    retrying for ~11s (which made every message feel slow when the shared key
    was throttled). ChatNVIDIA has no retry logic at all, so it already fails
    fast; its free tier can 429 unpredictably (undocumented per-model daily
    caps), which is exactly why it sits in front of a failover chain. Gemini
    reuses the generic builder, identical to the old failover path."""
    key = os.getenv(SHARED_CHAT_KEYS[provider])
    if provider == "groq":
        return ChatGroq(api_key=key, model=DEFAULT_CHAT_MODELS["groq"], streaming=True, max_retries=0)
    return _build_llm(provider, key, DEFAULT_CHAT_MODELS[provider])


def _build_llm(provider: str, api_key: str, model: Optional[str] = None):
    """Construct a chat model for any supported provider from a user's key.

    Ollama Cloud is reached through its OpenAI-compatible endpoint, so it reuses
    ChatOpenAI with a custom base_url rather than a separate dependency.
    """
    model = model or DEFAULT_CHAT_MODELS.get(provider)
    if provider == "groq":
        return ChatGroq(api_key=api_key, model=model, streaming=True)
    if provider == "google_genai":
        # thinking_budget=-1 (adaptive) is only valid on thinking-capable Gemini
        # models (2.5+ and 3.x). Older families (1.5, 2.0) reject thinkingConfig
        # with a 400, so only pass it when the model supports it; otherwise the
        # provider's default applies and the model stays usable.
        m = (model or "").lower()
        kwargs = {}
        if not any(v in m for v in ("gemini-1.0", "gemini-1.5", "gemini-2.0")):
            kwargs["thinking_budget"] = -1
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, streaming=True, **kwargs)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key, streaming=True)
    if provider == "anthropic":
        return ChatAnthropic(model=model, api_key=api_key, streaming=True)
    if provider == "ollama_cloud":
        return ChatOpenAI(model=model, api_key=api_key, base_url="https://ollama.com/v1", streaming=True)
    if provider == "nvidia":
        # OpenAI-compatible hosted NIM. No streaming= kwarg (ChatNVIDIA has no
        # such field; extra kwargs are silently ignored, and token streaming
        # still works because BaseChatModel auto-upgrades to _astream when a
        # streaming callback is attached, which the agent event stream always
        # does). No max_retries= either: ChatNVIDIA has no retry logic at all,
        # so it already fails fast for the failover chain. max_tokens=4096
        # overrides the package default of 1024, which truncates long email
        # drafts and can cut tool-call JSON mid-argument.
        return ChatNVIDIA(api_key=api_key, model=model, max_tokens=4096)
    raise ValueError(f"Unknown chat provider: {provider}")


def make_model_error_middleware(fallback_chain: list, using_shared: bool):
    """Middleware that turns provider failures into friendly messages, walking
    the shared failover chain first.

    Module-level (not a closure in build_agent) so tests can compose it with
    fake models and an arbitrary chain without Mongo or network. A fresh
    instance is created per build to capture that request's chain and tier.

    Semantics, pinned by tests/unit/test_failover_chain.py:
    - GraphInterrupt always re-raises (HITL approvals must not be swallowed).
    - Stale-tool errors re-raise at every level so api._safe_run can stream
      its reset message.
    - Shared tier: quota AND auth errors walk the chain in order, one try per
      hop (a misconfigured shared key must not break users while healthy
      fallbacks exist). A hop failing with any other class stops the walk:
      do not burn every provider on a request failing for a different reason.
    - BYOK tier: no walk ever. Auth shows auth_message, quota shows
      quota_message(False).
    - Terminal message classifies the LAST error seen: quota gives
      quota_message; auth on a shared key gives generic_message (auth_message
      would wrongly tell the user to check their own key when the fault is
      the deploy's key; the log line carries the truth); anything else gives
      generic_message.
    """
    @wrap_model_call
    async def handle_model_errors(request, handler):
        try:
            return await handler(request)
        except GraphInterrupt:
            raise
        except Exception as e:
            # A stale-tool error (old checkpoint history references a tool that
            # is no longer bound, more likely now that tools are loaded on
            # demand) must propagate so api._safe_run can surface its clean
            # "start a new conversation" reset stream.
            msg = str(e).lower()
            if "not in request.tools" in msg or "tool call validation" in msg:
                raise
            kind = classify_provider_error(e)
            if kind is None:
                log.exception("chat model error: %r", e)
                return AIMessage(content=generic_message())
            if kind == "auth" and not using_shared:
                log.warning("chat auth error (byok): %r", e)
                return AIMessage(content=auth_message())
            last = e
            for fb_label, fb_llm in (fallback_chain if using_shared else []):
                log.warning(
                    "shared chat model failed (%s); failing over to %s: %r",
                    classify_provider_error(last), fb_label, last,
                )
                try:
                    return await handler(request.override(model=fb_llm))
                except GraphInterrupt:
                    raise
                except Exception as e2:
                    m2 = str(e2).lower()
                    if "not in request.tools" in m2 or "tool call validation" in m2:
                        raise
                    last = e2
                    if classify_provider_error(e2) not in ("quota", "auth"):
                        log.warning("failover %s failed with a non-quota, non-auth error (%r); stopping chain", fb_label, e2)
                        break
            last_kind = classify_provider_error(last)
            if last_kind == "quota":
                log.warning("chat quota/limit error (shared=%s): %r", using_shared, last)
                return AIMessage(content=quota_message(using_shared))
            if last_kind == "auth":
                if using_shared:
                    log.warning("shared chat auth error after exhausting the chain: %r", last)
                    return AIMessage(content=generic_message())
                return AIMessage(content=auth_message())
            log.exception("chat model error: %r", last)
            return AIMessage(content=generic_message())

    return handle_model_errors


SYSTEM_PROMPT = Template(
    """
    You are MailNet, an AI email assistant. You help users read, compose, send, draft, reply to, search, archive, and schedule emails.

    LANGUAGE RULES: follow these strictly, no exceptions:
    1. Conversation: always reply to the user in whatever language they write to you in. Never switch conversation language based on any setting.
    2. Email content (subject, body, greeting, signature): ALWAYS write in $language, even if the user spoke to you in a different language. This rule overrides everything else when composing or replying to emails.

    Email composition preferences, apply only when writing or replying to emails:
    - Language: $language - MANDATORY for all email content, do not deviate
    - Tone: $tone
    - Writing style: $writing_style
    - Sender name: $sender_name
    - Organization: $organization_name
    - Greeting: $preferred_greeting
    - Signature: $signature (enabled: $include_signature)
    - Character limit: $character_limit characters
    - Auto-adjust tone: $auto_adjust_tone

    Rules for update_email_settings:
    - default_provider must be "google" or "microsoft" (lowercase only).
    - character_limit must be a number between 100 and 5000.
    - include_signature, auto_adjust_tone, include_thread_context must be true or false.

    ATTACHMENT RULE: If the user's message contains "[Attached file ID: <id>]", always pass that ID in attachment_ids when calling send_email, draft_email, or reply_to_email. Never omit it.

    MEMORY:
    - Anything already known about this user is provided automatically in the "WHAT YOU ALREADY KNOW ABOUT THIS USER" section below (it is recalled for you on every message). Apply it silently to personalize your work. You do not need to, and cannot, look it up yourself. Never announce that you used it.
    - When the user states a durable preference, decide WHERE it belongs:
      * If it maps to a settings field (language, tone, writing_style, sender_name, organization_name, preferred_greeting, signature, include_signature, default_provider, character_limit), call update_email_settings. Do NOT also store it as a memory.
      * Otherwise, if it is a durable free-form fact (a recurring contact and how to address them, a standing do/don't instruction, a relationship, an org-specific rule), call remember_user_fact.
    - Never save one-off task details or things mentioned only in passing.
    - When the user asks you to forget, delete, or stop remembering something about them, call forget_memory with a short description of the fact. Confirm what was removed based on the tool result.
    - Never tell the user something was remembered or saved unless the tool result confirms success. If a tool result says it was not saved, not configured, or failed, tell the user plainly that it could not be saved instead of claiming success.

    PROGRESS UPDATES: Right before you call an email or scheduling tool (reading, searching, sending, replying, drafting, deleting, scheduling), first send the user ONE short line of about 5 to 8 words saying what you are about to do, for example "Checking your inbox now.", "Drafting that reply.", or "Scheduling it for you.". Then call the tool. Use only one such line per action, keep it natural, and do not narrate background memory operations or repeat the line after the tool finishes unless you have a real result to share.

    EMAIL TRIAGE: Whenever you read or search emails (unless the user is looking for a specific email or asks a narrow question), triage the results by calling present_triage with one item per email: category "immediate" (time-sensitive, direct questions, deadlines today or tomorrow), "action" (tasks, requests, follow-ups that are not urgent), or "fyi" (newsletters, notifications, confirmations, no reply needed), each with a reason of at most 12 words. The card is shown to the user, so NEVER repeat the classification as text or markdown lists. After the card, write only one or two conversational sentences that lead with the single most urgent email (who it is from, why it matters) and offer to help with it. If nothing is urgent, say the inbox looks calm. If there is only one email, still triage it.

    TIME, SEARCH, AND SCHEDULING:
    - Tools: get_current_time (user's current local time), resolve_location (a city/country's exact IANA timezone), web_search (real-world facts like business hours), convert_time (DST-aware timezone conversion). Never guess the current time, a timezone, or a place's hours, and never do timezone math in your head, use these tools.
    - RESOLVE TIMEZONES, don't guess them. To get a place's timezone, call resolve_location with a city or country name; it returns the exact IANA timezone to feed into convert_time. Use web_search only to find FACTS like a company's headquarters city or its posted business hours, then pass the city to resolve_location.
    - SEARCH SMARTLY. Never search a raw email address: "name@gmail.com" returns nothing useful. Identify WHO or WHAT the recipient is first:
      * Personal mailbox domains (gmail.com, outlook.com, hotmail.com, yahoo.com, icloud.com, proton.me, etc.) identify an individual, not an organization, and have NO public working hours. Do NOT web_search them. Use any location you already know for this contact (from the recalled facts above) with resolve_location; otherwise ask the user for the person's city, timezone, or preferred time.
      * A company/custom domain (e.g. name@acme.com), or a named company, is an organization: web_search its headquarters city and posted business hours, then resolve_location on that city for the timezone. For a large multinational, there is no single timezone, so ask the user which office/region they mean instead of guessing.
      * Always fold in any location you already know for the recipient (recalled memory or earlier in the conversation).
    - Working-hours scheduling workflow (e.g. "send during their working hours"): (1) determine the recipient's city (known, recalled, or web_search), (2) resolve_location(city) for the IANA timezone, (3) web_search the business hours if you don't know them (default to 9am-5pm local on weekdays only if the user is fine with an assumption), (4) get_current_time for the user's now, (5) convert_time to map a moment inside those hours into the user's timezone, (6) schedule for that local time. Briefly tell the user the timezone, hours, and the local time you scheduled for.
    - If you cannot determine the recipient's city, timezone, or hours, say so plainly and ask, do not guess or search their email address.

    If information needed to complete a task is missing, ask don't guess. Keep responses concise.
    """
)


def encrypt_payload(creds: dict) -> str:
    """Encrypt credentials before sending"""
    try:
        plaintext = json.dumps(creds).encode()
        cipher = Fernet(ENCRYPTION_KEY.encode())
        encrypted = cipher.encrypt(plaintext)
        return encrypted.decode()
    except Exception as e:
        raise ValueError(f"Encryption failed: {e}")


def content_to_text(content) -> str:
    """Flatten an LLM message's `content` into clean display text, for any provider.

    Providers disagree on the shape of assistant content:
      - NVIDIA / Groq / OpenAI / Ollama: a plain string.
      - Anthropic: a list of blocks like {"type": "text", "text": ...} plus
        non-text blocks (tool_use, thinking).
      - Google Gemini with thinking on: a list whose text parts carry a thinking
        `signature` in `extras`, and where the visible answer can be split across
        several parts (e.g. "astroscoding@" + "gmail.com").

    Rendering such a list with str() leaks the Python repr (signatures and all)
    into the UI, which looks broken or truncated even though the text is whole.
    This joins only the human-readable text parts and drops reasoning/signatures,
    so every provider yields one complete string.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                itype = item.get("type")
                # Skip reasoning/thought blocks; keep only visible text.
                if itype in ("thinking", "reasoning", "thought"):
                    continue
                if "text" in item and isinstance(item["text"], str):
                    parts.append(item["text"])
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def decrypt_payload(encrypted: str) -> dict:
    """Decrypt encrypted credentials"""
    try:
        encrypted_bytes = encrypted.encode()
        cipher = Fernet(ENCRYPTION_KEY.encode())
        decrypted = cipher.decrypt(encrypted_bytes)
        return json.loads(decrypted.decode())
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


def get_or_create_user(email: str, name: str, picture: str, provider: Literal["google", "microsoft"]) -> dict:
    """
    Looks up a user by their provider email. Creates one if not found.
    Returns the user document with _id as a string.
    """
    email_field = "google_email" if provider == "google" else "outlook_email"
    user = db["users"].find_one({email_field: email})

    if user:
        db["users"].update_one(
            {"_id": user["_id"]},
            {
                "$set": {"name": name, "picture": picture},
                "$addToSet": {"providers": provider},
            }
        )
        user = db["users"].find_one({"_id": user["_id"]})
    else:
        pref = DEFAULT_PREFERENCES.copy()
        pref['sender_name'] = name

        new_user = {
            "google_email": email if provider == "google" else None,
            "outlook_email": email if provider == "microsoft" else None,
            "name": name,
            "picture": picture,
            "providers": [provider],
            "preferences": pref,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        result = db["users"].insert_one(new_user)
        user = db["users"].find_one({"_id": result.inserted_id})

    user["_id"] = str(user["_id"])
    return user


async def refresh_microsoft_token_if_needed(token: dict) -> dict:
    if not token:
        return token
    expires_at = token.get("expires_at", 0)
    if time.time() < expires_at - 300:
        return token  # still valid

    async with AsyncOAuth2Client(
            client_id=os.getenv("AZURE_APPLICATION_CLIENT_ID"),
            client_secret=os.getenv("AZURE_SECRET_VALUE"),
            token_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/token",
    ) as client:
        new_token = await client.refresh_token(
            url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            refresh_token=token["refresh_token"],
        )
        return dict(new_token)


async def refresh_google_token_if_needed(token: dict) -> dict:
    if not token:
        return token
    expiry_str = token.get("expiry", "")
    try:
        expiry = datetime.datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
    except (ValueError, TypeError):
        return token  # can't parse expiry, return as-is

    if datetime.datetime.now(datetime.timezone.utc) < expiry - datetime.timedelta(seconds=300):
        return token  # still valid

    async with AsyncOAuth2Client(
            client_id=token["client_id"],
            client_secret=token["client_secret"],
            token_endpoint=token["token_uri"],
    ) as client:
        new_token = await client.refresh_token(
            url=token["token_uri"],
            refresh_token=token["refresh_token"],
        )
        return {
            "token": new_token["access_token"],
            "refresh_token": new_token.get("refresh_token", token["refresh_token"]),
            "token_uri": token["token_uri"],
            "client_id": token["client_id"],
            "client_secret": token["client_secret"],
            "scopes": token["scopes"],
            "expiry": datetime.datetime.fromtimestamp(
                new_token["expires_at"], datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


async def fetch_mcp_tools(azure_token, google_token, default_provider="google") -> list:
    """Fetch and filter MCP tools. Call in parallel with recall to hide the round-trip latency."""
    client = MultiServerMCPClient(
        {
            "email_mcp": {
                "transport": "streamable_http",
                "url": os.getenv("MAILNET_SERVER_URL", "http://localhost:9111/mcp"),
                "headers": {
                    "azure_token": encrypt_payload(azure_token),
                    "google_token": encrypt_payload(google_token),
                    "redirect_uri": "http://localhost/",
                    "default_provider": default_provider,
                }
            }
        }
    )
    return [t for t in await client.get_tools() if t.name != "update_email_settings"]


def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return the top results as text.

    Use this to look up real-world facts you do not already know, such as a
    company's business hours, headquarters city, address, or contact details,
    before composing or scheduling an email. Pass a focused query (e.g.
    'Acme Corp London office opening hours'). Returns a short list of result
    titles, snippets, and URLs, or a note if nothing was found.

    For a place's TIME ZONE, do not rely on this, use resolve_location instead,
    which returns the exact IANA timezone for a city or country."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max(1, min(max_results, 10))):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                results.append(f"- {title}\n  {body}\n  {href}")
        if not results:
            return f"No web results found for '{query}'."
        return "\n".join(results)
    except Exception as e:
        log.warning("web_search failed: %r", e)
        return f"Web search failed: {e}. Tell the user you could not look that up right now."


class TriageItem(BaseModel):
    """One triaged email for the on-screen triage card."""
    # Plain str, not an enum: Groq validates tool calls strictly against the
    # schema, so a model emitting "Immediate" against a lowercase enum would
    # fail the whole call. We normalize instead.
    category: str = Field(description='One of: "immediate", "action", "fyi"')
    sender: str
    subject: str
    reason: str


_TRIAGE_ALIASES = {
    "immediate": "immediate", "urgent": "immediate", "critical": "immediate",
    "action": "action", "task": "action", "follow-up": "action", "followup": "action",
    "fyi": "fyi", "info": "fyi", "informational": "fyi", "newsletter": "fyi",
}


def normalize_triage_category(value: str) -> str:
    return _TRIAGE_ALIASES.get(str(value).strip().lower(), "")


def present_triage(items: list[TriageItem]) -> str:
    """Display the visual email triage card in the chat UI.

    Call this right after reading or searching emails whenever you are triaging
    or briefing (not when the user asked for one specific email). Pass one item
    per email with category "immediate" (time-sensitive, direct questions,
    deadlines today or tomorrow), "action" (tasks, requests, non-urgent
    follow-ups), or "fyi" (newsletters, notifications, confirmations, no reply
    needed). sender is the display name, subject the email subject, and reason
    a short phrase (12 words max) saying why it landed in that category. The
    card is rendered for the user automatically; do not repeat the same
    classification as text afterwards."""
    counts = {"immediate": 0, "action": 0, "fyi": 0}
    for it in items:
        raw = it.category if isinstance(it, TriageItem) else str(it.get("category", ""))
        cat = normalize_triage_category(raw)
        if cat in counts:
            counts[cat] += 1
    return (
        f"Triage card displayed ({len(items)} emails: "
        f"{counts['immediate']} immediate, {counts['action']} action, {counts['fyi']} fyi)."
    )


def resolve_location(place: str) -> str:
    """Resolve a city, town, or country to its country and IANA time zone.

    Use this whenever you need a place's timezone (for example, to schedule an
    email within a recipient's local working hours). Pass a place name, ideally
    a city (e.g. 'Redmond', 'London', 'Dubai'); if you only know the company,
    web_search its headquarters city first, then pass that here. Returns up to a
    few matches, each with its full location and exact IANA timezone (e.g.
    'America/Los_Angeles'), which you can feed straight into convert_time. Never
    guess a timezone yourself, use this."""
    import urllib.request
    import urllib.parse
    try:
        q = urllib.parse.urlencode({"name": place, "count": 5, "language": "en", "format": "json"})
        url = f"https://geocoding-api.open-meteo.com/v1/search?{q}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results") or []
        if not results:
            return f"No location found for '{place}'. Try a nearby city or the country name."
        lines = []
        for r in results[:5]:
            loc = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
            tz = r.get("timezone", "")
            lines.append(f"- {loc} -> timezone {tz}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("resolve_location failed: %r", e)
        return f"Could not resolve location '{place}' right now."


async def build_agent(azure_token, google_token, user_tz="UTC", user_id=None, disconnected=None, recalled_context="", prefetched_mcp_tools=None):
    import time as _time
    _t0 = _time.time()
    prefs = DEFAULT_PREFERENCES.copy()
    api_keys = {}
    if user_id:
        user_doc = db["users"].find_one({"_id": ObjectId(user_id)}, {"preferences": 1, "api_keys": 1, "google_email": 1})
        if user_doc:
            if "preferences" in user_doc:
                prefs = user_doc["preferences"]
            api_keys = user_doc.get("api_keys") or {}

    checkpointer = _get_checkpointer()

    # Chat model selection, in priority order:
    #   1. The user's own key for their chosen provider (true BYOK).
    #   2. A shared developer key for that provider, if we have one (NVIDIA,
    #      Groq and Google). This is what makes "switch to Gemini" work
    #      without the user pasting a key. OpenAI/Anthropic/Ollama have no
    #      shared key, so without a user key they drop to the default.
    #   3. The first provider in the shared chain (NVIDIA when configured,
    #      else Groq, matching the pre-NVIDIA default).
    # using_shared drives the wording of any limit/auth message later.
    using_shared = True
    _chain = _shared_chain()
    _default_shared = _chain[0] if _chain else "groq"
    active_shared = _default_shared
    model_label = f"{_default_shared}/{DEFAULT_CHAT_MODELS[_default_shared]} (shared)"
    chat_cfg = api_keys.get("chat") or {}
    provider = chat_cfg.get("provider")
    model = chat_cfg.get("model") or (DEFAULT_CHAT_MODELS.get(provider) if provider else None)
    user_chat_key = None
    if chat_cfg.get("key"):
        try:
            user_chat_key = decrypt_payload(chat_cfg["key"])["key"]
        except Exception as e:
            log.warning("could not decrypt chat key (%r)", e)
    shared_for_provider = SHARED_CHAT_KEYS.get(provider) if provider else None
    shared_provider_key = os.getenv(shared_for_provider) if shared_for_provider else None
    try:
        if provider and user_chat_key:
            llm = _build_llm(provider, user_chat_key, model)
            using_shared = False
            model_label = f"{provider}/{model} (byok)"
        elif provider and shared_provider_key:
            llm = _build_llm(provider, shared_provider_key, model)
            using_shared = True
            # Assigned only after the build succeeds: on a construction error
            # the except path runs the default primary instead, and
            # active_shared must name what is actually running or the failover
            # chain would retry the running provider and skip a real hop.
            active_shared = provider
            model_label = f"{provider}/{model} (shared)"
        else:
            llm = _build_shared_llm(_default_shared)
    except Exception as e:
        log.warning("could not build chat LLM (%r); falling back to shared %s", e, _default_shared)
        llm = _build_shared_llm(_default_shared)
        using_shared = True
        active_shared = _default_shared
        model_label = f"{_default_shared}/{DEFAULT_CHAT_MODELS[_default_shared]} (shared)"

    # Silent failover across the shared providers: when the active shared key
    # fails mid-request (rate limit, or a misconfigured shared key), the error
    # middleware retries the same request on the next provider in the chain,
    # in order, before asking the user for their own key. BYOK users get no
    # failover: their key, their quota, and silently switching would hide
    # that their key is limited.
    _fallback_chain = []  # ordered (label, llm) pairs the middleware walks
    if using_shared:
        for fb in _chain:
            if fb == active_shared:
                continue
            try:
                _fallback_chain.append((
                    f"{fb}/{DEFAULT_CHAT_MODELS[fb]} (shared failover)",
                    _build_shared_llm(fb),
                ))
            except Exception as e:
                log.warning("could not build failover model %s: %r", fb, e)

    # Smart features (memory): the user's own embedding key if saved, else shared Gemini.
    embed_cfg = api_keys.get("embeddings") or {}
    embed_provider = embed_cfg.get("provider")
    embed_key = None
    if embed_provider and embed_cfg.get("key"):
        try:
            embed_key = decrypt_payload(embed_cfg["key"])["key"]
        except Exception as e:
            log.warning("could not decrypt embeddings key (%r); falling back to shared", e)
            embed_provider = None

    # Memory is BYOK-only: recall runs on every message and extraction on every
    # save, which the shared keys don't cover. It needs the user's own smart
    # features key, except for the admin account (matched on google_email).
    # A memory_enabled=False preference pauses it even with a key present.
    _admin_email = os.getenv("ADMIN_EMAIL", "")
    _is_admin = bool(_admin_email) and (
        ((user_doc or {}).get("google_email") or "").lower() == _admin_email.lower()
        if user_id else False
    )
    memory_on = (bool(embed_key) or _is_admin) and prefs.get("memory_enabled") is not False
    MEMORY_OFF_NOTE = (
        "Memory is currently turned off for this account. It needs the user's own "
        "Smart Features key: tell the user they can add one in Settings, AI Models, "
        "and then enable the memory switch in Settings, Memories."
    )

    # Sensitive tools the user has chosen to auto-approve (skip the HITL prompt).
    auto_approve = set(prefs.get("auto_approve_tools") or [])

    if prefetched_mcp_tools is not None:
        mcp_tools = prefetched_mcp_tools
    else:
        # Same fetch as the /agent endpoint's parallel prewarm; reuse the helper
        # so the MCP URL, headers, and filtered-tool set live in one place.
        mcp_tools = await fetch_mcp_tools(
            azure_token, google_token, prefs.get("default_provider", "google")
        )


    # The authenticated owner, captured so a model-supplied argument can never
    # decide whose mailbox a scheduled job belongs to.
    _owner_id = user_id

    def bound_schedule_send_email(
            to: str, subject: str, body: str,
            minutes_from_now: Optional[int] = None,
            hours_from_now: Optional[int] = None,
            days_from_now: Optional[int] = None,
            day_string: Optional[str] = None,
            at_hour: Optional[int] = None,
            at_minute: Optional[int] = None,
            at_second: Optional[int] = None,
            at_year: Optional[int] = None,
            at_month: Optional[int] = None,
            at_day: Optional[int] = None,
    ):
        """Schedules a one-time email. Use EXACTLY ONE scheduling method:
        - Relative: minutes_from_now=25 means 'in 25 minutes'; hours_from_now=2 means 'in 2 hours'; days_from_now=3 means 'in 3 days'.
        - Specific time today/tomorrow: at_hour=12, at_minute=25 means 'at 12:25'. If that time already passed today it schedules tomorrow.
        - Named weekday: day_string='Monday' + optional at_hour/at_minute for the time on that day.
        - Exact date: at_year=2026, at_month=5, at_day=10 + optional at_hour/at_minute.
        Returns the confirmed scheduled datetime on success."""
        return schedule_send_email(
            to=to, subject=subject, body=body,
            minutes_from_now=minutes_from_now, hours_from_now=hours_from_now,
            days_from_now=days_from_now, day_string=day_string,
            at_year=at_year, at_month=at_month, at_day=at_day,
            at_hour=at_hour, at_minute=at_minute, at_second=at_second,
            user_id=_owner_id, timezone=user_tz,
            google_token=encrypt_payload(google_token) if google_token else None,
            azure_token=encrypt_payload(azure_token) if azure_token else None,
            default_provider=prefs.get("default_provider", "google"),
        )

    def bound_schedule_recurring_email(
            to: str, subject: str, body: str,
            hour: Optional[int] = None,
            minute: Optional[int] = None,
            second: Optional[int] = None,
            day_of_week: Optional[str] = None,
            day: Optional[int] = None,
            month: Optional[int] = None,
    ):
        """Schedules a recurring email using cron syntax. All time values are interpreted in the user's local timezone. day_of_week accepts: 'mon', 'tue', 'mon-fri', '1,3,5' (0=Monday). Returns a success or failure message."""
        return schedule_recurring_email(
            to=to, subject=subject, body=body, user_id=_owner_id,
            timezone=user_tz,
            hour=hour, minute=minute, second=second,
            day_of_week=day_of_week, day=day, month=month,
            google_token=encrypt_payload(google_token) if google_token else None,
            azure_token=encrypt_payload(azure_token) if azure_token else None,
            default_provider=prefs.get("default_provider", "google"),
        )

    def update_email_settings(
            language: Optional[str] = None,
            tone: Optional[str] = None,
            writing_style: Optional[str] = None,
            sender_name: Optional[str] = None,
            organization_name: Optional[str] = None,
            include_signature: Optional[bool] = None,
            signature: Optional[str] = None,
            preferred_greeting: Optional[str] = None,
            auto_adjust_tone: Optional[bool] = None,
            include_thread_context: Optional[bool] = None,
            character_limit: Optional[int] = None,
            default_provider: Optional[str] = None,
    ) -> str:
        """Update the user's email preferences. Only pass the fields you want to change, leave others as None.
        default_provider must be 'google' or 'microsoft'.
        character_limit must be between 100 and 5000."""
        if not user_id:
            return "Cannot update settings: no user context."
        try:
            updates = {k: v for k, v in {
                "language": language, "tone": tone, "writing_style": writing_style,
                "sender_name": sender_name, "organization_name": organization_name,
                "include_signature": include_signature, "signature": signature,
                "preferred_greeting": preferred_greeting, "auto_adjust_tone": auto_adjust_tone,
                "include_thread_context": include_thread_context, "character_limit": character_limit,
                "default_provider": default_provider,
            }.items() if v is not None}

            if not updates:
                return "No fields provided to update."

            if "default_provider" in updates:
                val = str(updates["default_provider"]).lower()
                if val not in ("google", "microsoft"):
                    return f"Invalid default_provider '{updates['default_provider']}'. Must be 'google' or 'microsoft'."
                updates["default_provider"] = val

            if "character_limit" in updates:
                try:
                    val = int(updates["character_limit"])
                    if not (100 <= val <= 5000):
                        return "Invalid character_limit. Must be between 100 and 5000."
                    updates["character_limit"] = val
                except (TypeError, ValueError):
                    return "Invalid character_limit. Must be a number between 100 and 5000."

            for bool_field in ("include_signature", "auto_adjust_tone", "include_thread_context"):
                if bool_field in updates and not isinstance(updates[bool_field], bool):
                    return f"Invalid value for '{bool_field}'. Must be true or false."

            # These values are read back into the system prompt on every future
            # request, so unbounded free text here is a way to plant standing
            # instructions. Cap length, and keep newlines out of the one-line
            # fields so a value cannot open a new directive of its own.
            if "default_provider" in updates:
                linked = updates["default_provider"]
                if (linked == "google" and not google_token) or (linked == "microsoft" and not azure_token):
                    return (
                        f"Cannot set default_provider to '{linked}': that account is not connected. "
                        "Ask the user to connect it in Settings first."
                    )

            for text_field in ("language", "tone", "writing_style", "sender_name",
                               "organization_name", "preferred_greeting", "signature"):
                if text_field not in updates:
                    continue
                val = updates[text_field]
                if not isinstance(val, str):
                    return f"Invalid value for '{text_field}'. Must be text."
                if len(val) > _PREF_TEXT_MAX:
                    return f"Invalid value for '{text_field}'. Keep it under {_PREF_TEXT_MAX} characters."
                # signature is the only field where multi-line is legitimate
                if text_field != "signature" and len(val.splitlines()) > 1:
                    return f"Invalid value for '{text_field}'. It must be a single line."
                updates[text_field] = val.strip()

            set_fields = {f"preferences.{k}": v for k, v in updates.items()}
            db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": set_fields})
            return "Settings updated successfully."
        except Exception as e:
            return f"Failed to update settings: {e}"

    def remember_user_fact(fact: str) -> str:
        """Save a durable, free-form fact about the user to long-term memory.

        Use this ONLY for facts that do NOT fit update_email_settings, for example:
        recurring contacts and how the user addresses them ('CC Sara on all client
        emails'), standing instructions ('never email legal on Fridays'),
        relationships, or organization-specific rules.
        Do NOT use this for tone/language/signature/provider style preferences;
        those go through update_email_settings instead.
        Do NOT save one-off task details. Write the fact as a short standalone
        sentence (e.g. 'The user's manager is Sara Lee (sara@acme.com).')."""
        if not user_id:
            return "Cannot save memory: no user context."
        if not memory_on:
            return MEMORY_OFF_NOTE
        return memory_remember(user_id, fact, provider=embed_provider, api_key=embed_key)

    def get_current_time() -> str:
        """Get the current date and time in the user's local timezone.

        Call this whenever you need to reason about 'now': to schedule relative
        to the current moment, to check whether a target time has already passed,
        or to convert another place's business hours into the user's local time
        before scheduling. Returns the local time, the timezone, and the UTC time."""
        try:
            tz = ZoneInfo(user_tz)
        except Exception:
            tz = datetime.timezone.utc
        now_local = datetime.datetime.now(tz)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        return (
            f"Current local time: {now_local.strftime('%A, %Y-%m-%d %H:%M:%S')} ({user_tz})\n"
            f"UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

    def convert_time(time_str: str, from_tz: str, to_tz: Optional[str] = None) -> str:
        """Convert a clock time from one timezone to another (DST-aware).

        Use this to turn another place's business hours into the user's local
        time before scheduling, or vice versa. Do NOT do timezone math yourself,
        always call this so daylight-saving is handled correctly.

        Args:
            time_str: The time to convert, as 'HH:MM' (assumes today) or
                'YYYY-MM-DD HH:MM' for a specific date.
            from_tz: IANA timezone of the input time (e.g. 'Europe/London',
                'America/New_York', 'Asia/Dubai').
            to_tz: IANA timezone to convert into. Defaults to the user's own
                timezone when omitted.

        Returns the converted local date and time, or an error note."""
        target_tz = to_tz or user_tz
        try:
            src = ZoneInfo(from_tz)
            dst = ZoneInfo(target_tz)
        except Exception as e:
            return f"Unknown timezone: {e}. Use IANA names like 'Europe/London' or 'Asia/Dubai'."
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(time_str.strip(), fmt)
                if fmt in ("%H:%M", "%H:%M:%S"):
                    today = datetime.datetime.now(src).date()
                    parsed = parsed.replace(year=today.year, month=today.month, day=today.day)
                break
            except ValueError:
                continue
        if parsed is None:
            return f"Could not parse time '{time_str}'. Use 'HH:MM' or 'YYYY-MM-DD HH:MM'."
        src_dt = parsed.replace(tzinfo=src)
        out = src_dt.astimezone(dst)
        return (
            f"{time_str} in {from_tz} = {out.strftime('%A, %Y-%m-%d %H:%M')} in {target_tz}"
        )

    def forget_memory(description: str) -> str:
        """Remove a saved long-term memory the user no longer wants kept.

        Use when the user asks you to forget, delete, or stop remembering
        something about them (e.g. 'forget that I CC Sara', 'don't remember my
        manager anymore'). Pass a short description of the fact to remove; the
        closest matching memory is deleted. Returns what was removed, or a note
        if nothing matched. To manage everything at once, the user can open the
        Memories panel in settings."""
        if not user_id:
            return "Cannot remove memory: no user context."
        if not memory_on:
            return MEMORY_OFF_NOTE
        return memory_forget(user_id, description, provider=embed_provider, api_key=embed_key)

    formatted_sys_prompt = SYSTEM_PROMPT.substitute(language=prefs['language'],
                                                    tone=prefs['tone'],
                                                    writing_style=prefs['writing_style'],
                                                    sender_name=prefs['sender_name'],
                                                    organization_name=prefs['organization_name'],
                                                    preferred_greeting=prefs['preferred_greeting'],
                                                    signature=prefs['signature'],
                                                    include_signature=prefs['include_signature'],
                                                    character_limit=prefs['character_limit'],
                                                    auto_adjust_tone=prefs['auto_adjust_tone']
                                                    )

    # Tell the agent about expired provider sign-ins so it asks the user to
    # reconnect instead of calling an email tool that silently returns nothing.
    if disconnected:
        names = {"google": "Google (Gmail)", "microsoft": "Microsoft (Outlook)"}
        for prov in disconnected:
            label = names.get(prov, prov)
            formatted_sys_prompt += (
                f"\n\n    CONNECTION STATUS: The user's {label} account sign-in has expired. "
                f"Do NOT call email tools for {label}. If the user asks to read, search, send, draft, "
                f"reply to, or schedule email on {label}, tell them plainly that their {label} account "
                f"needs reconnecting in Settings, and offer to use their other connected account if they have one."
            )

    # When BOTH accounts are connected, reads should span both. The read/search
    # tools take a provider arg, so the model fans out one call per account and
    # merges the results. With a single account this section is omitted and the
    # tools behave normally.
    if google_token and azure_token:
        formatted_sys_prompt += (
            "\n\n    EMAIL ACCOUNTS: The user has BOTH Google (Gmail) and Microsoft (Outlook) connected.\n"
            "    - If the user names or implies a single account (e.g. 'my Gmail', 'Google', 'Outlook', "
            "'my Microsoft email', 'only Gmail', 'just Outlook'), read ONLY that account: pass provider='google' "
            "for Gmail/Google, or provider='microsoft' for Outlook/Microsoft. Do NOT read the other one.\n"
            "    - ONLY when the user asks to read or search WITHOUT naming an account, call the read or search "
            "tool TWICE (provider='google' and provider='microsoft') and present the combined results together, "
            "clearly labelling which account each email came from.\n"
            "    Other actions (send, reply, draft, delete) use the user's default account unless they say otherwise."
        )

    # Inject what we recalled about the user for this turn (done server-side, no
    # tool call needed). Empty when there is nothing relevant stored.
    if recalled_context and recalled_context.strip():
        formatted_sys_prompt += (
            "\n\n    WHAT YOU ALREADY KNOW ABOUT THIS USER (apply silently, do not mention it):\n"
            + recalled_context
        )

    # Deferred tool loading: instead of sending all tool schemas every call
    # (which exhausted the shared free tier's token/minute budget), the model gets a
    # small core (search_tools / load_tools / unload_tools), the always-on inbox
    # tools, plus a catalog listing, and loads the long-tail tools on demand. The
    # ToolNode still holds every tool, so execution is unaffected; only the
    # per-call schemas shrink.
    extra_tools = [
        bound_schedule_send_email, bound_schedule_recurring_email, update_email_settings,
        remember_user_fact, forget_memory, get_current_time, convert_time, web_search,
        resolve_location, present_triage,
    ]
    # The everyday inbox actions almost every session uses. Kept always loaded so
    # common tasks (read, search, send, reply, draft) need no extra load step,
    # which also makes weaker models more reliable. Everything else is deferred.
    # present_triage is always-on because the inbox briefing must render its card
    # without a load_tools round trip.
    ALWAYS_ON = {"read_emails", "search_emails", "send_email", "reply_to_email", "draft_email", "present_triage"}
    pool = [coerce_tool(t) for t in (mcp_tools + extra_tools)]
    always_on_tools = [t for t in pool if t.name in ALWAYS_ON]
    catalog_tools = [t for t in pool if t.name not in ALWAYS_ON]
    all_tools, core_tools, bind_active_tools, catalog_listing = build_dynamic_toolset(
        catalog_tools, always_on=always_on_tools
    )

    formatted_sys_prompt += (
        "\n\n    TOOL LOADING: The everyday inbox tools (read_emails, search_emails, "
        "send_email, reply_to_email, draft_email) are always available, call them "
        "directly. The ADDITIONAL TOOLS below are NOT loaded yet: before calling any "
        "of them you MUST first load_tools([...]) with the exact names you need (you "
        "can load several at once); their full inputs become available on your next "
        "step. Use search_tools(query) if you are unsure which tool fits. Load only "
        "what the task needs and unload_tools when done. Loading is cheap and "
        "expected.\n\n    ADDITIONAL TOOLS (call load_tools before using):\n"
        + catalog_listing
    )

    log.info(
        "agent built model=%s catalog=%d recalled=%s prompt_chars=%d",
        model_label, len(catalog_tools),
        "yes" if (recalled_context and recalled_context.strip()) else "no",
        len(formatted_sys_prompt),
    )
    log.debug("system prompt:\n%s", formatted_sys_prompt)
    tools = all_tools

    # Catch provider quota/auth failures from the chat model and turn them into
    # a friendly assistant message instead of a hard error, walking the shared
    # failover chain first. The logic lives in make_model_error_middleware so
    # tests can drive it with fake models; a fresh instance per build captures
    # this request's chain and tier.
    handle_model_errors = make_model_error_middleware(_fallback_chain, using_shared)

    @wrap_tool_call
    async def handle_tool_errors(request, handler):
        tool_name = request.tool_call["name"]

        # Human-in-the-loop gate, skipped for actions the user auto-approved.
        # interrupt() runs BEFORE the try/except so a GraphInterrupt is never
        # swallowed by the error handler. On resume the tool node re-runs and
        # interrupt() returns the decision payload.
        if tool_name in SENSITIVE_TOOLS and tool_name not in auto_approve:
            decision = interrupt({
                "type": "approval",
                "tool": tool_name,
                # The frontend matched pending approvals on tool NAME alone, so a
                # replayed history card for the same tool could grow live buttons
                # bound to a different call. Correlate on the call id instead.
                "tool_call_id": request.tool_call.get("id", ""),
                "args": request.tool_call.get("args", {}),
            })
            approved = isinstance(decision, dict) and decision.get("approved")
            if not approved:
                return ToolMessage(
                    content=f"[USER DECLINED] The user reviewed and explicitly chose NOT to proceed with {tool_name}. Respond by acknowledging their decision naturally (e.g. 'Got it, I won't send it.' or 'No problem, I'll hold off.'). Do NOT say you failed, do NOT offer to retry, and do NOT suggest trying again unless the user brings it up.",
                    tool_call_id=request.tool_call["id"],
                )
            # "Always allow": remember this action so it skips approval next time.
            if decision.get("always") and user_id:
                try:
                    db["users"].update_one(
                        {"_id": ObjectId(user_id)},
                        {"$addToSet": {"preferences.auto_approve_tools": tool_name}},
                    )
                    auto_approve.add(tool_name)
                except Exception as e:
                    log.warning("could not persist always-allow for %s: %r", tool_name, e)

        try:
            return await handler(request)
        except GraphInterrupt:
            # Never convert an interrupt into an error message; let it propagate.
            raise
        except Exception as e:
            return ToolMessage(
                content=f"Tool error: Please check your input and try again. ({str(e)})",
                tool_call_id=request.tool_call["id"],
                is_error=True
            )

    return create_agent(
        llm,
        tools,
        system_prompt=formatted_sys_prompt,
        checkpointer=checkpointer,
        state_schema=DynamicToolState,
        # bind_active_tools must run first so it sets the per-call tool schemas
        # before the model errors/HITL middleware wrap the actual call.
        middleware=[bind_active_tools, handle_model_errors, handle_tool_errors],
    )


# Tools that send mail or destroy data. These pause for explicit human approval
# before running. Reads, searches, and drafts stay frictionless.
# Tools that pause for human approval. The scheduling tools belong here because
# they send REAL mail later, outside the agent graph, with no human present, so
# they were previously the one send path with no approval card at all.
# download_attachment writes a file, and update_email_settings persists text
# that is read back into every future system prompt.
# archive_email and toggle_label are deliberately NOT gated: both are reversible
# and used in bulk, so gating them would mean an approval card per message.
SENSITIVE_TOOLS = {
    "send_email",
    "reply_to_email",
    "send_draft",
    "delete_email",
    "bound_schedule_send_email",
    "bound_schedule_recurring_email",
    "download_attachment",
    "update_email_settings",
}
