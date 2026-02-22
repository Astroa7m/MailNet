import json
import os
import sys
import time
from base64 import b64decode
from pathlib import Path
from typing import cast, Optional

from itsdangerous import TimestampSigner
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

# adding project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import chainlit as cl
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.common import encrypt_payload
from app.extra_tools import schedule_send_email

load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")


@cl.header_auth_callback
def header_auth(headers: dict) -> Optional[cl.User]:
    # getting the session cookie
    cookie_header = headers.get("cookie", "")
    session_cookie = None

    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("session="):
            session_cookie = cookie.split("=", 1)[1]
            break

    if not session_cookie:
        print("FOUND NO SESSION")
        return None

    try:
        # decoding the session
        signer = TimestampSigner(os.getenv("SESSION_SECRET"))

        unsigned_data = signer.unsign(session_cookie)

        decoded = b64decode(unsigned_data)

        decoded_json_session = json.loads(decoded)
        user = decoded_json_session.get("user")
        google_token = decoded_json_session.get("google_token")
        if not user:
            return None

        return cl.User(
            identifier=user.get("email"),
            metadata={
                "name": user.get("name", ""),
                "provider": user.get("provider", ""),
                "picture": user.get("picture", ""),
                "email": user["email"],
                "token": google_token
            }
        )
    except Exception as e:
        print(f"Error decoding session: {e}")
        return None


@cl.on_chat_start
async def on_chat_start():
    llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b")

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

    #  todo: change to postgres saver in prod
    # in ram checkpointer
    checkpointer = MemorySaver()

    with open(os.getenv(r"AZURE_PREFERRED_TOKEN_FILE_PATH")) as f:
        azure_token = json.loads(f.read())

    with open(os.getenv(r"GOOGLE_PREFERRED_TOKEN_FILE_PATH")) as f:
        google_token = json.loads(f.read())
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
    tools = mcp_tools + [schedule_send_email]
    agent = create_agent(
        llm,
        tools,
        system_prompt="You are a helpful assistant, do not call a tool unless told.",
        checkpointer=checkpointer
    )

    config = {"configurable": {"thread_id": cl.user_session.get("current_thread")}}

    cl.user_session.set("agent", agent)
    cl.user_session.set("config", config)
    cl.user_session.set("checkpointer", checkpointer)


@cl.on_message
async def on_message(message: cl.Message):
    agent = cast(CompiledStateGraph, cl.user_session.get("agent"))
    config = cl.user_session.get("config")

    start = time.time()

    msg = cl.Message(content="")

    stream = agent.astream_events(
        {"messages": [("user", message.content)]},
        config=config,
    )

    thinking_step = None

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
        if kind == "on_tool_end":
            tool_step.output = event["data"].get("output")
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
