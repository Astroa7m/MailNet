"""The failover chain, driven through a real create_agent graph offline.

These tests pin the semantics the plan specifies for
make_model_error_middleware: hop order, quota and shared-auth walking, BYOK
never walking, stale-tool re-raise, GraphInterrupt survival across a hop, and
the terminal-message rule (last error's class decides the message).
"""
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

from app.common import make_model_error_middleware
from app.llm_errors import auth_message, generic_message, quota_message
from tests.stubs.stub_llms import (
    RaisingChatModel,
    RecordingChatModel,
    ScriptedChatModel,
)


def _scripted(*contents):
    return ScriptedChatModel(messages=iter([AIMessage(content=c) for c in contents]))


def _raising(msg="[429] Too Many Requests"):
    return RaisingChatModel(messages=iter([]), error_message=msg)


async def _run(primary, chain, using_shared=True, prompt="hello"):
    mw = make_model_error_middleware(chain, using_shared)
    agent = create_agent(primary, tools=[], middleware=[mw])
    result = await agent.ainvoke({"messages": [HumanMessage(content=prompt)]})
    return result["messages"][-1].content


async def test_healthy_primary_never_walks():
    hop = _scripted("hop-should-not-run")
    out = await _run(_scripted("primary-ok"), [("hop", hop)])
    assert out == "primary-ok"


async def test_quota_fails_over_to_first_hop():
    out = await _run(_raising(), [("groq-hop", _scripted("hop1-ok"))])
    assert out == "hop1-ok"


async def test_two_quota_hops_reach_third_provider():
    chain = [("groq-hop", _raising()), ("gemini-hop", _scripted("hop2-ok"))]
    out = await _run(_raising(), chain)
    assert out == "hop2-ok"


async def test_all_quota_ends_with_shared_quota_message():
    chain = [("h1", _raising()), ("h2", _raising())]
    out = await _run(_raising(), chain)
    assert out == quota_message(True)


async def test_shared_auth_error_walks_the_chain():
    out = await _run(
        _raising("[401] Unauthorized: invalid key"),
        [("groq-hop", _scripted("hop-ok"))],
    )
    assert out == "hop-ok"


async def test_shared_auth_exhausted_gives_generic_not_auth_message():
    chain = [("h1", _raising("[401] Unauthorized"))]
    out = await _run(_raising("[403] Forbidden"), chain)
    assert out == generic_message()
    assert out != auth_message()


async def test_byok_quota_never_walks_even_with_chain_present():
    trap = _scripted("must-not-appear")
    out = await _run(_raising(), [("trap", trap)], using_shared=False)
    assert out == quota_message(False)


async def test_byok_auth_shows_auth_message():
    out = await _run(_raising("[401] Unauthorized"), [], using_shared=False)
    assert out == auth_message()


async def test_non_quota_hop_error_stops_walk_with_generic_message():
    chain = [
        ("h1", _raising("boom: internal server exploded")),
        ("h2", _scripted("must-not-appear")),
    ]
    out = await _run(_raising(), chain)
    assert out == generic_message()


async def test_stale_tool_error_reraises_from_primary():
    with pytest.raises(Exception, match="not in request.tools"):
        await _run(
            _raising("tool call validation failed: x not in request.tools"),
            [("hop", _scripted("nope"))],
        )


async def test_stale_tool_error_reraises_from_a_hop():
    chain = [("h1", _raising("tool call validation failed: y not in request.tools"))]
    with pytest.raises(Exception, match="not in request.tools"):
        await _run(_raising(), chain)


async def test_unclassified_primary_error_gives_generic_message():
    out = await _run(_raising("weird nonsense failure"), [("hop", _scripted("no"))])
    assert out == generic_message()


async def test_interrupt_survives_failover_and_resume_completes():
    """Primary 429s, the hop calls a HITL-gated tool, the interrupt must
    surface (not be swallowed as a quota message), and resuming must run the
    tool and finish on the hop model."""

    @tool
    def guarded(x: str) -> str:
        """A tool gated by human approval."""
        decision = interrupt({"tool": "guarded", "args": {"x": x}})
        return f"ran:{decision}"

    hop = ScriptedChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "guarded", "args": {"x": "1"}, "id": "c1"}]),
        AIMessage(content="all-done"),
    ]))
    mw = make_model_error_middleware([("hop", hop)], True)
    agent = create_agent(
        _raising(), tools=[guarded], middleware=[mw], checkpointer=InMemorySaver()
    )
    cfg = {"configurable": {"thread_id": "t-interrupt"}}
    first = await agent.ainvoke({"messages": [HumanMessage(content="go")]}, cfg)
    assert "__interrupt__" in first, "interrupt was swallowed by the failover walk"
    second = await agent.ainvoke(Command(resume="approved"), cfg)
    contents = [getattr(m, "content", "") for m in second["messages"]]
    assert any("ran:approved" in str(c) for c in contents)
    assert second["messages"][-1].content == "all-done"


async def test_override_rebinds_tools_on_the_hop_model():
    """request.override(model=...) must hand the hop the same tool set the
    active model had; the factory re-binds per call."""

    @tool
    def probe(x: str) -> str:
        """Probe tool."""
        return "probed"

    hop = RecordingChatModel(messages=iter([AIMessage(content="done")]))
    mw = make_model_error_middleware([("hop", hop)], True)
    agent = create_agent(_raising(), tools=[probe], middleware=[mw])
    await agent.ainvoke({"messages": [HumanMessage(content="go")]})
    assert hop.bound_tools_log, "hop model was never bound with tools"
    flat = [t for bound in hop.bound_tools_log for t in bound]
    assert any(getattr(t, "name", getattr(t, "__name__", "")) == "probe" or "probe" in str(t) for t in flat)
