import asyncio
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from dotenv import load_dotenv
import os

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


async def run_agent():
    tools = await client.get_tools()
    agent = create_agent(
        llm,
        tools
    )

    messages = []

    while True:
        inn = input("Prompt: ")

        if inn == "exit":
            break

        human_message = HumanMessage(content=inn)
        messages.append(human_message)

        result = await agent.ainvoke({"messages": messages})

        ai_message = result["messages"][-1]
        messages.append(ai_message)

        print(f"Agent: {ai_message.content}")


asyncio.run(run_agent())
