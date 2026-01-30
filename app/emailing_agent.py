import asyncio
import os
from pathlib import Path
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.constants import END, START
from langgraph.graph import MessagesState, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

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


class State(MessagesState):
    email_input: dict
    classification_decision: Literal["ignore", "respond", "notify"]


class RouterSchema(BaseModel):
    """Analyzes the unread messages and route the llm to act accordingly"""

    reasoning: str = Field(
        description="Step by step reasoning behind the classification"
    )
    classification: Literal["ignore", "respond", "notify"] = Field(
        description="The classification of an email, 'ignore' for irrelevant emails', 'notify' for important information that doesn't need a response, and 'respond' for emails that needs a response"
    )


class StateInput(TypedDict):
    # This is the input to the state
    email_input: dict


sample_email = """
Dear Bruh,

I hope this message finds you well. I wanted to follow up on our recent conversation regarding the [project/topic discussed], and share a few additional thoughts that might help us move forward.

Based on our discussion, I’ve outlined a preliminary approach that aligns with your goals and timeline. I’ve attached a brief summary for your review. Please let me know if you’d like to schedule a quick call to refine the details or explore alternatives.

Looking forward to your feedback.

Warm regards,
Ahmed Samir
Founder & Lead Developer
Kalima Tech
"""

sys_prompt = """
Classify the following email based on the following rules
1. ignore - Emails that are not worth responding to or tracking
2. notify - Important information that worth notification but doesn't require a response
3. respond - Emails that need a direct response
"""


user_prompt = """
Please determine how to handle the below email thread:

From: {author}
Subject: {subject}
{email_thread}"""

llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="openai/gpt-oss-120b")

llm_router = llm.with_structured_output(RouterSchema, method="json_schema")


async def router(state: State) -> Command[Literal["response_agent", END]]:
    """Analyze email content to decide if we should respond, notify, or ignore.

     The triage step prevents the assistant from wasting time on:
     - Marketing emails and spam
     - Company-wide announcements
     - Messages meant for other teams
     """

    print("Got state in router", state)

    email_input = state['email_input']

    res = await llm_router.ainvoke(
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt.format(author=email_input['email'], subject=email_input['subject'], email_thread=email_input['body'])}
        ]
    )
    # print(res)
    if res.classification == "respond":
        print("This emai requires a response")
        goto = "response_agent"
        update = {
            "messages": [
                {
                    "role": "user",
                    "content": f"respond to email {sample_email}"
                }
            ],
            "classification_decision": res.classification
        }

    elif res.classification == "ignore":
        print("Ignoring email")
        goto = END
        update = {
            "classification_decision": res.classification
        }
    elif res.classification == "notify":
        print("This email contians important information")
        goto = END
        update = {
            "classification_decision": res.classification
        }
    else:
        raise ValueError(f"Invalid classification {res.classification}")
    return Command(goto=goto, update=update)


@tool
class Done(BaseModel):
    """E-mail has been sent."""
    done: bool


tools = asyncio.run(client.get_tools())

llm_ith_tools = llm.bind_tools(tools + [Done])


def call_llm(state: State):
    another_one = state['messages'][-1]
    """Calls LLM"""
    return {
        "messages": [
            llm_ith_tools.invoke(
                [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant, if you are done, call Done tool"
                    },
                ] + state['messages']
            )
        ]
    }


async def tool_handler(state: dict):
    "Performs tool call"

    # list tool for tool message
    result = []

    # iterate through tool calls

    for tool_call in state['messages'][-1].tool_calls:
        # get the tool
        tool = list(filter(lambda x: x.name.lower() == tool_call["name"].lower(), tools))[0]
        # run the tool
        tool_res = await tool.ainvoke(tool_call['args'])
        # create a tool message
        result.append(
            {
                "role": "tool",
                "content": tool_res,
                "tool_call_id": tool_call['id']
            }
        )
    return {"messages": result}


def should_continue(state: State) -> Literal["tool_handler", END]:
    """Route to tool handler"""
    # get last message
    last_message = state['messages'][-1]

    # if the last message is a tool call
    if last_message.tool_calls:
        print(f"We got a call here {last_message.tool_calls}")
        for tool_call in last_message.tool_calls:
            print(f"current tool {tool_call}")
            if tool_call["name"] == "Done":
                return END
            else:
                return "tool_handler"
    return END


# building the graph

agent_builder = StateGraph(State)

# add nodes
agent_builder.add_node("call_llm", call_llm)
agent_builder.add_node("tool_handler", tool_handler)

# add edge
agent_builder.add_edge(START, "call_llm")
agent_builder.add_conditional_edges("call_llm",
                                    should_continue)

agent_builder.add_edge("tool_handler", "call_llm")

agent = agent_builder.compile()

overall_workflow = (
    StateGraph(State, input_schema=StateInput)
    .add_node(router)
    .add_node("response_agent", agent)
    .add_edge(START, "router")
)

email_assistant = overall_workflow.compile()


async def main():
    res = await email_assistant.ainvoke(
        {
            "email_input": {
                "subject": "IMMEDIATE REQUEST!!!",
                "body": "I was having probelm with the API could you help explain some?",
                "email": "ahah@mfa.com"
            }
        }
    )

    for message in res['messages']:
        message.pretty_print()


asyncio.run(main())
