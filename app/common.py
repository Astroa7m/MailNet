import datetime
import json
import os
import sys
import time
from pathlib import Path
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
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.extra_tools import schedule_send_email

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
}


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
        new_user = {
            "google_email": email if provider == "google" else None,
            "outlook_email": email if provider == "microsoft" else None,
            "name": name,
            "picture": picture,
            "providers": [provider],
            "preferences": DEFAULT_PREFERENCES.copy(),
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


async def build_agent(azure_token, google_token, user_tz="UTC", user_id=None):
    checkpointer = MongoDBSaver(mongo_client, db_name="MailNet")
    # checkpointer = InMemorySaver()
    llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b", streaming=True)
    mcp_client = MultiServerMCPClient(
        {
            "email_mcp": {
                "transport": "streamable_http",
                "url": "http://localhost:9111/mcp",
                "headers": {
                    "azure_token": encrypt_payload(azure_token),
                    "google_token": encrypt_payload(google_token),
                    "redirect_uri": "http://localhost/"
                }
            }
        }
    )
    mcp_tools = [
        t for t in await mcp_client.get_tools()
        if t.name not in ("load_email_settings", "update_email_settings")
    ]

    def bound_schedule_send_email(
            to: str, subject: str, body: str,
            seconds: Optional[int] = None, minutes: Optional[int] = None,
            hours: Optional[int] = None, day_of_month: Optional[int] = None,
            month: Optional[int] = None, year: Optional[int] = None,
            days_count_from_today: Optional[int] = None, day_string: Optional[str] = None,
            user_id: str = "tester-user-001",
    ):
        """schedules email to send, if succeeded, you should return the scheduled datetime to the user in human-readable way"""
        return schedule_send_email(
            to=to, subject=subject, body=body, seconds=seconds, minutes=minutes,
            hours=hours, day_of_month=day_of_month, month=month, year=year,
            days_count_from_today=days_count_from_today, day_string=day_string,
            user_id=user_id, timezone=user_tz,
        )

    def load_email_settings() -> dict:
        """Load the user's email preferences (language, tone, signature, etc.)."""
        if not user_id:
            return DEFAULT_PREFERENCES.copy()
        user_doc = db["users"].find_one({"_id": ObjectId(user_id)}, {"preferences": 1})
        if not user_doc or "preferences" not in user_doc:
            return DEFAULT_PREFERENCES.copy()
        return user_doc["preferences"]

    def update_email_settings(updates_json: str) -> str:
        """Update the user's email preferences. Pass a JSON string with the fields to change.
        Available fields: language, tone, writing_style, sender_name, organization_name,
        include_signature, signature, preferred_greeting, auto_adjust_tone,
        include_thread_context, character_limit, default_provider."""
        if not user_id:
            return "Cannot update settings: no user context."
        try:
            updates = json.loads(updates_json)
            set_fields = {f"preferences.{k}": v for k, v in updates.items()}
            db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": set_fields})
            return "Settings updated successfully."
        except Exception as e:
            return f"Failed to update settings: {e}"

    tools = mcp_tools + [bound_schedule_send_email, load_email_settings, update_email_settings]
    return create_agent(
        llm,
        tools,
        system_prompt="You are a helpful assistant, do not call a tool unless told.",
        checkpointer=checkpointer,
        middleware=[handle_tool_errors]
    )


@wrap_tool_call
async def handle_tool_errors(request, handler):
    try:
        return await handler(request)
    except Exception as e:
        return ToolMessage(
            content=f"Tool error: Please check your input and try again. ({str(e)})",
            tool_call_id=request.tool_call["id"],
            is_error=True
        )
