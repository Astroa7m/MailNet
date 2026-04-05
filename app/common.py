import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from app.extra_tools import schedule_send_email

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")


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


async def build_agent(azure_token, google_token, user_tz="UTC"):
    checkpointer = MongoDBSaver(MongoClient(os.getenv("MONGO_DB_URL")), db_name="MailNet")
    llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b")
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
    mcp_tools = await mcp_client.get_tools()

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

    tools = mcp_tools + [bound_schedule_send_email]
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
