import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.common import encrypt_payload
from app.extra_tools import schedule_send_email

load_dotenv()

llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b")


path = Path().resolve().parents[0]

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
                "microsoft_token": encrypt_payload(azure_token),
                "google_token": encrypt_payload(google_token),
                "redirect_uri": "http://localhost/"
            }
        }
    }
)


def print_messenger(turn):
    if isinstance(turn, AIMessage):
        # red
        color = "\033[31mAI:\033[0m"
    elif isinstance(turn, HumanMessage):
        # green
        color = "\033[32mHuman:\033[0m"
    else:
        # blue
        color = "\033[34mTool:\033[0m"

    print(color)


async def run_agent():
    mcp_tools = await mcp_client.get_tools()
    tools = mcp_tools + [schedule_send_email]
    agent = create_agent(
        llm,
        tools,
        system_prompt="You are a helpful assistant, do not call a tool unless told."
    )

    messages = []

    while True:
        inn = input("\033[32mHuman:\033[0m ")

        if inn == "exit":
            break

        human_message = HumanMessage(content=inn)
        messages.append(human_message)

        result = await agent.ainvoke({"messages": messages})

        new_messages = result["messages"][len(messages):]
        # extending the list with the new messages only not the full
        messages.extend(new_messages)
        # iterating only through the new messages so we do not duplicate the output
        for turn in new_messages:
            print_messenger(turn)
            if "reasoning_content" in turn.additional_kwargs:
                print(f"Thinking: {turn.additional_kwargs['reasoning_content']}")
            if "tool_calls" in turn.additional_kwargs:
                tool_call = turn.additional_kwargs['tool_calls'][0]
                print(f"Calling function: {tool_call}")
            print(f"Content: {turn.content}")


asyncio.run(run_agent())
