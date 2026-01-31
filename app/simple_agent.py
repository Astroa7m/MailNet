import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()
path = Path().resolve().parents[0]

client = MultiServerMCPClient(
    {
        "email_mcp": {
            "command": "uv",
            "args": [
                "--directory",
                str(path / "mcp-server"),
                "run",
                "-m",
                "mcp_launcher.server"
            ],
            "env": {
                "AZURE_APPLICATION_CLIENT_ID": os.getenv("AZURE_APPLICATION_CLIENT_ID"),
                "AZURE_CLIENT_SECRET_VALUE": os.getenv("AZURE_SECRET_VALUE"),
                "AZURE_PREFERRED_TOKEN_FILE_PATH": str(path / "azure_token.json"),

                "GOOGLE_CREDENTIALS_FILE_PATH": str(path / "google_credentials.json"),
                "GOOGLE_PREFERRED_TOKEN_FILE_PATH": str(path / "google_token.json")
            },
            "transport": "stdio",
        }
    }
)

llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b")


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
    tools = await client.get_tools()
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
