import datetime
import json
import os
import sys
import time
from pathlib import Path
from string import Template
from typing import Optional, Literal

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
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import interrupt
from langgraph.errors import GraphInterrupt

from app.extra_tools import schedule_send_email, schedule_recurring_email
from app.memory_store import remember as memory_remember, recall as memory_recall, forget as memory_forget
from app.llm_errors import classify_provider_error, quota_message, auth_message, generic_message

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

mongo_client = MongoClient(os.getenv("MONGO_DB_URL"))
db = mongo_client["MailNet"]

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
    "groq": "openai/gpt-oss-120b",
    "google_genai": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "ollama_cloud": "gpt-oss:120b",
}


def _build_shared_llm():
    """The app's default chat model, backed by the owner's shared Groq key."""
    return ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b", streaming=True)


def _build_llm(provider: str, api_key: str, model: Optional[str] = None):
    """Construct a chat model for any supported provider from a user's key.

    Ollama Cloud is reached through its OpenAI-compatible endpoint, so it reuses
    ChatOpenAI with a custom base_url rather than a separate dependency.
    """
    model = model or DEFAULT_CHAT_MODELS.get(provider)
    if provider == "groq":
        return ChatGroq(api_key=api_key, model=model, streaming=True)
    if provider == "google_genai":
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, streaming=True)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=api_key, streaming=True)
    if provider == "anthropic":
        return ChatAnthropic(model=model, api_key=api_key, streaming=True)
    if provider == "ollama_cloud":
        return ChatOpenAI(model=model, api_key=api_key, base_url="https://ollama.com/v1", streaming=True)
    raise ValueError(f"Unknown chat provider: {provider}")


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
    - ALWAYS call recall_user_context FIRST, before doing any email task (reading, searching, composing, replying, sending, drafting, scheduling) and at the start of a new conversation. Pass a short query describing the task, then apply anything relevant silently. Do this every time, even if the user did not mention a preference and even if you think you already know. Never announce that you looked it up.
    - When the user states a durable preference, decide WHERE it belongs:
      * If it maps to a settings field (language, tone, writing_style, sender_name, organization_name, preferred_greeting, signature, include_signature, default_provider, character_limit), call update_email_settings. Do NOT also store it as a memory.
      * Otherwise, if it is a durable free-form fact (a recurring contact and how to address them, a standing do/don't instruction, a relationship, an org-specific rule), call remember_user_fact.
    - Never save one-off task details or things mentioned only in passing.
    - When the user asks you to forget, delete, or stop remembering something about them, call forget_memory with a short description of the fact. Confirm what was removed based on the tool result.
    - Never tell the user something was remembered or saved unless the tool result confirms success. If a tool result says it was not saved, not configured, or failed, tell the user plainly that it could not be saved instead of claiming success.

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


async def build_agent(azure_token, google_token, user_tz="UTC", user_id=None, disconnected=None):
    prefs = DEFAULT_PREFERENCES.copy()
    api_keys = {}
    if user_id:
        user_doc = db["users"].find_one({"_id": ObjectId(user_id)}, {"preferences": 1, "api_keys": 1})
        if user_doc:
            if "preferences" in user_doc:
                prefs = user_doc["preferences"]
            api_keys = user_doc.get("api_keys") or {}

    checkpointer = MongoDBSaver(mongo_client, db_name="MailNet")
    # checkpointer = InMemorySaver()

    # Chat model: the user's own key if they saved one, otherwise the shared key.
    # using_shared drives the wording of any limit/auth message later.
    using_shared = True
    chat_cfg = api_keys.get("chat") or {}
    if chat_cfg.get("provider") and chat_cfg.get("key"):
        try:
            chat_key = decrypt_payload(chat_cfg["key"])["key"]
            llm = _build_llm(chat_cfg["provider"], chat_key, chat_cfg.get("model"))
            using_shared = False
        except Exception as e:
            print(f"[CHAT] could not build user LLM ({e!r}); falling back to shared key")
            llm = _build_shared_llm()
    else:
        llm = _build_shared_llm()

    # Smart features (memory): the user's own embedding key if saved, else shared Gemini.
    embed_cfg = api_keys.get("embeddings") or {}
    embed_provider = embed_cfg.get("provider")
    embed_key = None
    if embed_provider and embed_cfg.get("key"):
        try:
            embed_key = decrypt_payload(embed_cfg["key"])["key"]
        except Exception as e:
            print(f"[MEMORY] could not decrypt embeddings key ({e!r}); falling back to shared")
            embed_provider = None

    # Sensitive tools the user has chosen to auto-approve (skip the HITL prompt).
    auto_approve = set(prefs.get("auto_approve_tools") or [])

    mcp_client = MultiServerMCPClient(
        {
            "email_mcp": {
                "transport": "streamable_http",
                "url": os.getenv("MAILNET_SERVER_URL", "http://localhost:9111/mcp"),
                "headers": {
                    "azure_token": encrypt_payload(azure_token),
                    "google_token": encrypt_payload(google_token),
                    "redirect_uri": "http://localhost/",
                    "default_provider": prefs.get("default_provider", "google"),
                }
            }
        }
    )

    mcp_tools = [
        t for t in await mcp_client.get_tools()
        if t.name != "update_email_settings"
    ]


    def bound_schedule_send_email(
            to: str, subject: str, body: str,
            user_id: str = "tester-user-001",
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
            user_id=user_id, timezone=user_tz,
            google_token=encrypt_payload(google_token) if google_token else None,
            azure_token=encrypt_payload(azure_token) if azure_token else None,
            default_provider=prefs.get("default_provider", "google"),
        )

    def bound_schedule_recurring_email(
            to: str, subject: str, body: str,
            user_id: str = "tester-user-001",
            hour: Optional[int] = None,
            minute: Optional[int] = None,
            second: Optional[int] = None,
            day_of_week: Optional[str] = None,
            day: Optional[int] = None,
            month: Optional[int] = None,
    ):
        """Schedules a recurring email using cron syntax. All time values are interpreted in the user's local timezone. day_of_week accepts: 'mon', 'tue', 'mon-fri', '1,3,5' (0=Monday). Returns a success or failure message."""
        return schedule_recurring_email(
            to=to, subject=subject, body=body, user_id=user_id,
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
        return memory_remember(user_id, fact, provider=embed_provider, api_key=embed_key)

    def recall_user_context(query: str) -> str:
        """Look up what you already know about the user from long-term memory.

        Call this at the start of a new conversation, or whenever the user refers
        to how they 'usually' do something, who their usual contacts are, or any
        standing preference you might have saved before. Pass a short query
        describing what you need (e.g. 'preferred contacts for client updates').
        Returns a bullet list of remembered facts, or an empty string if nothing
        relevant is stored. Use the results silently to personalize your response."""
        if not user_id:
            return ""
        return memory_recall(user_id, query, provider=embed_provider, api_key=embed_key)

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

    print(f"sys={formatted_sys_prompt}")
    tools = mcp_tools + [bound_schedule_send_email, bound_schedule_recurring_email, update_email_settings,
                         remember_user_fact, recall_user_context, forget_memory]

    # Catch provider quota/auth failures from the chat model and turn them into a
    # friendly assistant message instead of a hard error. Defined here so it can
    # capture using_shared, which decides whether we say "add your own key".
    @wrap_model_call
    async def handle_model_errors(request, handler):
        try:
            return await handler(request)
        except GraphInterrupt:
            raise
        except Exception as e:
            kind = classify_provider_error(e)
            if kind == "quota":
                print(f"[CHAT] quota/limit error (shared={using_shared}): {e!r}")
                return AIMessage(content=quota_message(using_shared))
            if kind == "auth":
                print(f"[CHAT] auth error: {e!r}")
                return AIMessage(content=auth_message())
            import traceback
            traceback.print_exc()
            return AIMessage(content=generic_message())

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
                    print(f"[APPROVAL] could not persist always-allow for {tool_name}: {e!r}")

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
        middleware=[handle_model_errors, handle_tool_errors]
    )


# Tools that send mail or destroy data. These pause for explicit human approval
# before running. Reads, searches, and drafts stay frictionless.
SENSITIVE_TOOLS = {"send_email", "reply_to_email", "send_draft", "delete_email"}
