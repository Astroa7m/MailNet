import json
import os
import pickle
import sys
import time
from base64 import b64decode
from pathlib import Path
from typing import cast, Optional

import redis
from itsdangerous import TimestampSigner
from langgraph.graph.state import CompiledStateGraph

from common import encrypt_payload, decrypt_payload, refresh_microsoft_token_if_needed, refresh_google_token_if_needed, \
    build_agent

# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import chainlit as cl
from dotenv import load_dotenv

load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")

redis_client = redis.asyncio.from_url(os.getenv("REDIS_URL"))


@cl.header_auth_callback
async def header_auth(headers: dict) -> Optional[cl.User]:
    # getting the session cookie
    cookie_header = headers.get("cookie", "")
    session_cookie = None
    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("session="):
            # the session cookie contain the session id of the current user
            session_cookie = cookie.split("=", 1)[1]
            break

    if not session_cookie:
        print("FOUND NO SESSION")
        return None

    try:
        # decoding the session id
        signer = TimestampSigner(os.getenv("SESSION_SECRET"))

        unsigned_data = signer.unsign(session_cookie)
        decoded_data = b64decode(unsigned_data)
        decoded_json_session = json.loads(decoded_data)
        # starlette-session uses _cssid key to store session ids
        user_id = decoded_json_session.get("_cssid")

        try:
            raw = await redis_client.get(user_id)
            if raw is None:
                print(f"[AUTH] No session found for user_id: {user_id}")
                return None
            # redis uses pickle to store objects
            session_data = pickle.loads(raw)
        except (pickle.UnpicklingError, EOFError, TypeError) as e:
            print(f"[AUTH] Failed to deserialize session: {e}")
            return None

        user = session_data.get("user")
        raw_google = session_data.get("google_token")
        raw_azure = session_data.get("azure_token")
        google_token = decrypt_payload(raw_google) if raw_google else None
        microsoft_token = decrypt_payload(raw_azure) if raw_azure else None
        if not user:
            return None

        return cl.User(
            identifier=user.get("email"),
            metadata={
                "name": user.get("name", ""),
                "provider": user.get("provider", ""),
                "picture": user.get("picture", ""),
                "email": user["email"],
                "google_token": google_token,
                "azure_token": microsoft_token,
                "redis_user_id": user_id,
                "tz": session_data.get("tz", "UTC"),
            }
        )
    except Exception as e:
        print(f"Error decoding session: {e}")
        return None


@cl.on_chat_start
async def on_chat_start():
    # get the authenticated user
    user = cl.user_session.get("user")
    # message with user info
    await cl.Message(
        content=f"""
    🎉 Welcome to MailNet Chat, **{user.metadata.get('name', 'User')}**!

    📧 Email: {user.identifier}
    🔐 Provider: {user.metadata.get('provider', 'unknown').title()}
    """
    ).send()

    azure_token = user.metadata.get("azure_token")
    google_token = user.metadata.get("google_token")

    # store tokens in mutable session so on_message can refresh them
    cl.user_session.set("azure_token", azure_token)
    cl.user_session.set("google_token", google_token)
    cl.user_session.set("redis_user_id", user.metadata.get("redis_user_id"))

    user_tz = user.metadata.get("tz", "UTC")
    cl.user_session.set("tz", user_tz)

    agent = await build_agent(azure_token, google_token, user_tz)
    config = {"configurable": {"thread_id": cl.user_session.get("id")}}

    cl.user_session.set("agent", agent)
    cl.user_session.set("config", config)


@cl.on_message
async def on_message(message: cl.Message):
    azure_token = cl.user_session.get("azure_token")
    google_token = cl.user_session.get("google_token")
    refreshed = False

    if azure_token:
        fresh = await refresh_microsoft_token_if_needed(azure_token)
        if fresh != azure_token:
            print("[CHAT] Microsoft token refreshed mid-session")
            cl.user_session.set("azure_token", fresh)
            azure_token = fresh
            refreshed = True

    if google_token:
        fresh = await refresh_google_token_if_needed(google_token)
        if fresh != google_token:
            print("[CHAT] Google token refreshed mid-session")
            cl.user_session.set("google_token", fresh)
            google_token = fresh
            refreshed = True

    if refreshed:
        # persist fresh tokens back to Redis so page reload also gets them
        user_id = cl.user_session.get("redis_user_id")
        if user_id:
            try:
                raw = await redis_client.get(user_id)
                session_data = pickle.loads(raw)
                if azure_token:
                    session_data["azure_token"] = encrypt_payload(azure_token)
                if google_token:
                    session_data["google_token"] = encrypt_payload(google_token)
                await redis_client.set(user_id, pickle.dumps(session_data))
            except Exception as e:
                print(f"[CHAT] Failed to update Redis session after token refresh: {e}")

        # rebuild agent with fresh token headers
        agent = await build_agent(azure_token, google_token, cl.user_session.get("tz", "UTC"))
        cl.user_session.set("agent", agent)

    agent = cast(CompiledStateGraph, cl.user_session.get("agent"))
    config = cl.user_session.get("config")

    start = time.time()

    msg = cl.Message(content="")

    stream = agent.astream_events(
        {"messages": [("user", message.content)]},
        config=config,
    )

    thinking_step = None
    tool_step = None
    async for event in stream:
        kind = event["event"]

        # handle thinking & content
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            reasoning_content = chunk.additional_kwargs.get("reasoning_content")

            # stream thinking content
            if reasoning_content:
                if thinking_step is None:
                    thinking_step = cl.Step(name="Thinking")
                async with thinking_step:
                    await thinking_step.stream_token(reasoning_content)

            # stream regular response content
            content = chunk.content
            if content:
                # close thinking step if it exists and we're starting regular content
                if thinking_step is not None:
                    thinking_step.name = f"Thought for {time.time() - start} s"
                    await thinking_step.update()
                    thinking_step = None
                await msg.stream_token(content)

        # showing tool call
        if kind == "on_tool_start":
            async with cl.Step(name=event["name"], type="tool") as tool_step:
                tool_step.input = event["data"].get("input")

        # updating the tool result
        if kind == "on_tool_end" or kind == "on_tool_error":
            if tool_step:
                tool_step.output = event["data"].get("output") or event['data'].get("error")
                await tool_step.update()

        # updating the message with the final message
        if kind == "on_chat_model_end":
            await msg.update()


@cl.on_logout
async def on_logout(request, response):
    print("[CHAINLIT] Reached logout route")
    request.session.clear()


@cl.on_chat_end
async def end():
    user = cl.user_session.get("user")
    if user:
        print(f"Chat ended for user: {user.identifier}")
