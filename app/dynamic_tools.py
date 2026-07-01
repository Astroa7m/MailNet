"""Deferred / dynamic tool loading, to cut per-request token cost.

Binding all ~17 tool schemas on every model call is what blew Groq's free-tier
8k tokens-per-minute limit after ~2 messages: the schemas alone are ~2k tokens,
re-sent every turn even for "hi". This module keeps the model lean by binding
only a tiny core on each call:

  - search_tools(query): BM25 search over the catalog, returns names+descriptions
  - load_tools(names):   activate tools (persisted in agent state) so their full
                         schemas are sent on the next model call
  - unload_tools(names): drop tools once done, to keep the context small

A wrap_model_call middleware reads the active set from graph state and overrides
the per-call tool list to `core + active`. Crucially, the ToolNode is still
built with EVERY tool, so anything can execute; the middleware only controls
which schemas the MODEL sees, which is where the savings come from.

The model is told up front which tools exist (names + one-line descriptions, a
few hundred tokens) so it can load directly without always searching first.
"""
import math
import re
from collections import Counter
from typing import Annotated, Callable

from langchain.agents import AgentState
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, BaseTool, tool as _tool
from langchain.agents.middleware import wrap_model_call
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.logging_config import get_logger

log = get_logger("tools")


def coerce_tool(t):
    """Coerce a plain callable into a BaseTool (no-op if already one).

    The local tool functions (web_search, resolve_location, the scheduling
    closures, etc.) are plain functions; only the MCP tools arrive as BaseTool.
    We need a stable `.name` before create_agent would normally coerce them, so
    we coerce up front. Idempotent."""
    return t if isinstance(t, BaseTool) else _tool(t)


# --- state ----------------------------------------------------------------

def _take_last(_old: list, new: list) -> list:
    """Reducer for active_tools: keep the latest full list.

    load_tools/unload_tools each read the current list and return the full new
    one, so overwrite is the right merge. Without a reducer this is a LastValue
    channel that RAISES InvalidUpdateError if the model emits two plumbing tool
    calls in a single turn; a reducer folds multiple writes instead of crashing
    (the last one wins, and the model can re-load if needed)."""
    return new


class DynamicToolState(AgentState):
    # Names of catalog tools whose full schema is currently exposed to the model.
    # load/unload read the current list (via InjectedState) and return the full
    # new list; the reducer above keeps the latest and tolerates >1 write/step.
    active_tools: Annotated[list[str], _take_last]


# --- tiny BM25 (no extra dependency) --------------------------------------

def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


class _BM25:
    def __init__(self, docs: list[tuple[str, str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.ids = [d[0] for d in docs]
        self.corpus = [_tok(d[1]) for d in docs]
        self.tfs = [Counter(doc) for doc in self.corpus]
        self.N = len(self.corpus)
        self.avgdl = (sum(len(d) for d in self.corpus) / self.N) if self.N else 0.0
        df: dict[str, int] = {}
        for doc in self.corpus:
            for w in set(doc):
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for w, n in df.items()}

    def search(self, query: str, k: int = 8) -> list[str]:
        q = _tok(query)
        scored: list[tuple[float, str]] = []
        for i, tf in enumerate(self.tfs):
            dl = len(self.corpus[i])
            score = 0.0
            for w in q:
                idf = self.idf.get(w)
                if not idf:
                    continue
                f = tf.get(w, 0)
                if not f:
                    continue
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                scored.append((score, self.ids[i]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [tid for _, tid in scored[:k]]


# --- catalog + core tools --------------------------------------------------

def _short(tool) -> str:
    """First line of a tool's description, for compact listings."""
    desc = (getattr(tool, "description", "") or "").strip()
    return desc.split("\n", 1)[0][:140] if desc else ""


def build_dynamic_toolset(catalog_tools: list, always_on: list | None = None):
    """Wire up deferred tool loading for one agent build.

    catalog_tools: the heavy tools to defer (email, scheduling, search, etc.).
    always_on: tools small/common enough to bind every call (besides the core).

    Returns (all_tools, core_tools, middleware, catalog_listing) where:
      - all_tools is what create_agent gets (ToolNode can run everything),
      - core_tools + always_on are always exposed to the model,
      - middleware overrides per-call tool schemas from state["active_tools"],
      - catalog_listing is prompt text naming every loadable tool.
    """
    always_on = [coerce_tool(t) for t in (always_on or [])]
    catalog_tools = [coerce_tool(t) for t in catalog_tools]
    catalog = {t.name: t for t in catalog_tools}
    bm25 = _BM25([(name, f"{name} {_short(t)}") for name, t in catalog.items()])

    def search_tools(query: str) -> str:
        """Search available actions by keyword and return the best matches.

        Use this to discover which tool can do something (e.g. 'send email',
        'schedule', 'look up business hours', 'remember a fact'). Returns tool
        names with one-line descriptions. After finding the right one, call
        load_tools to activate it, then call it."""
        names = bm25.search(query, k=8)
        if not names:
            return f"No tools matched '{query}'. Try different keywords."
        return "\n".join(f"- {n}: {_short(catalog[n])}" for n in names)

    def load_tools(
        names: list[str],
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[dict, InjectedState],
    ) -> Command:
        """Activate one or more tools by name so you can call them next.

        Pass the exact tool names (from search_tools or the catalog you were
        given). Their full schemas become available on your next step. Load only
        what you need for the current task."""
        current = list(state.get("active_tools") or [])
        valid, unknown = [], []
        for n in names:
            (valid if n in catalog else unknown).append(n)
        for n in valid:
            if n not in current:
                current.append(n)
        msg = f"Loaded: {', '.join(valid) or 'none'}. You can call them now."
        if unknown:
            msg += f" Unknown (ignored): {', '.join(unknown)}."
        log.info("load_tools -> active=%s", current)
        return Command(update={
            "active_tools": current,
            "messages": [ToolMessage(msg, tool_call_id=tool_call_id)],
        })

    def unload_tools(
        names: list[str],
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[dict, InjectedState],
    ) -> Command:
        """Deactivate tools you are done with, to keep your context small.

        Call this once a sub-task is finished and you no longer need a tool."""
        drop = set(names)
        current = [n for n in (state.get("active_tools") or []) if n not in drop]
        log.info("unload_tools -> active=%s", current)
        return Command(update={
            "active_tools": current,
            "messages": [ToolMessage(f"Unloaded: {', '.join(names)}.", tool_call_id=tool_call_id)],
        })

    core_tools = [coerce_tool(search_tools), coerce_tool(load_tools), coerce_tool(unload_tools)]
    exposed_always = core_tools + always_on

    @wrap_model_call
    async def bind_active_tools(request, handler):
        active = request.state.get("active_tools") or []
        extra = [catalog[n] for n in active if n in catalog]
        return await handler(request.override(tools=exposed_always + extra))

    listing = "\n".join(f"    - {name}: {_short(t)}" for name, t in catalog.items())
    all_tools = exposed_always + list(catalog_tools)
    return all_tools, core_tools, bind_active_tools, listing
