import asyncio
from pathlib import Path

from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
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

llm = ChatGroq(api_key = os.getenv("GROQ_API_KEY"), model = "openai/gpt-oss-120b")

async def run_agent():
    tools = await client.get_tools()
    agent = create_react_agent(
        llm,
        tools
    )

    query = input("prompt: ")
    while query.lower() != "exit":
        resposne = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]}
        )

        print("reasoning:", resposne['messages'][-1].additional_kwargs['reasoning_content'])
        print("response:", resposne['messages'][-1].content)
        query = input("prompt: ")



asyncio.run(run_agent())