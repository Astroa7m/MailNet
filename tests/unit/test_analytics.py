"""Analytics: the events the app emits and the numbers the dashboard shows.

Three layers, each tested on its own:
- track() and its background writer: never raises, never blocks, writes to
  whatever database configure() points at.
- The real emit points: the failover middleware driven through a real
  create_agent graph, and memory saves/recalls with fake mem0 instances.
- summarize(): the pure function behind every dashboard number.
"""
import datetime

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

import app.analytics as analytics
import app.memory_store as ms
from app.common import make_model_error_middleware
from tests.stubs.stub_llms import RaisingChatModel, ScriptedChatModel

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

PRIMARY = "nvidia/nvidia/nemotron-3-super-120b-a12b (shared)"
GROQ = "groq/openai/gpt-oss-120b (shared failover)"
GEMINI = "google_genai/gemini-2.5-flash (shared failover)"


@pytest.fixture
def events():
    """Capture every tracked event in a list for the duration of a test."""
    captured = []
    analytics.set_sink(captured.append)
    yield captured
    analytics.set_sink(None)


def _ok(text="ok"):
    return ScriptedChatModel(messages=iter([AIMessage(content=text)]))


def _err(msg="[429] Too Many Requests"):
    return RaisingChatModel(messages=iter([]), error_message=msg)


async def _run(primary, chain, using_shared=True):
    mw = make_model_error_middleware(chain, using_shared, primary_label=PRIMARY, user_id="u1")
    agent = create_agent(primary, tools=[], middleware=[mw])
    out = await agent.ainvoke({"messages": [HumanMessage(content="hi")]})
    return out["messages"][-1].content


def _model_calls(evs):
    return [e for e in evs if e["event"] == "model_call"]


# --------------------------------------------------------------- track()

def test_track_never_raises_even_when_the_sink_explodes():
    def boom(_doc):
        raise RuntimeError("sink down")

    analytics.set_sink(boom)
    try:
        analytics.track("anything", "u1", x=1)  # must not raise
    finally:
        analytics.set_sink(None)


def test_track_is_a_noop_when_disabled(monkeypatch):
    written = []

    class _Coll:
        def insert_one(self, doc):
            written.append(doc)

    monkeypatch.setattr(analytics, "_get_db", lambda: {"events": _Coll()})
    monkeypatch.setenv("ANALYTICS_ENABLED", "0")
    analytics.track("agent_run", "u1")
    assert analytics.flush(1.0)
    assert written == []


def test_background_writer_lands_events_in_the_configured_db(monkeypatch):
    written = []

    class _Coll:
        def insert_one(self, doc):
            written.append(doc)

    monkeypatch.setattr(analytics, "_get_db", lambda: {"events": _Coll()})
    monkeypatch.setenv("ANALYTICS_ENABLED", "1")
    analytics.track("agent_run", "u1", source="test")
    assert analytics.flush(5.0)
    assert len(written) == 1
    doc = written[0]
    assert doc["event"] == "agent_run" and doc["user_id"] == "u1" and doc["source"] == "test"
    assert doc["ts"].tzinfo is not None


def test_a_failing_write_is_dropped_not_raised(monkeypatch):
    class _Down:
        def insert_one(self, doc):
            raise ConnectionError("atlas unreachable")

    monkeypatch.setattr(analytics, "_get_db", lambda: {"events": _Down()})
    monkeypatch.setenv("ANALYTICS_ENABLED", "1")
    analytics.track("agent_run", "u1")
    assert analytics.flush(5.0), "a failed write must still mark the item done"


def test_provider_of_reads_the_label_prefix():
    assert analytics.provider_of(PRIMARY) == "nvidia"
    assert analytics.provider_of(GROQ) == "groq"
    assert analytics.provider_of(None) is None


# ---------------------------------------------- failover middleware events

async def test_primary_success_is_hop_zero(events):
    await _run(_ok(), [("groq", _err())])
    (call,) = _model_calls(events)
    assert call["outcome"] == "ok" and call["hop"] == 0
    assert call["provider"] == "nvidia" and call["served_by"] == PRIMARY
    assert call["failures"] == [] and call["tier"] == "shared" and call["user_id"] == "u1"
    assert isinstance(call["latency_ms"], int)


async def test_failover_records_who_served_it_and_why_the_primary_failed(events):
    await _run(_err(), [(GROQ, _ok("from groq"))])
    (call,) = _model_calls(events)
    assert call["outcome"] == "ok" and call["hop"] == 1 and call["provider"] == "groq"
    assert call["failures"] == [{"label": PRIMARY, "provider": "nvidia", "kind": "quota"}]


async def test_reaching_gemini_is_hop_two_with_both_failures(events):
    await _run(_err(), [(GROQ, _err("[401] Unauthorized")), (GEMINI, _ok("from gemini"))])
    (call,) = _model_calls(events)
    assert call["hop"] == 2 and call["provider"] == "google_genai"
    assert [f["kind"] for f in call["failures"]] == ["quota", "auth"]


async def test_whole_chain_down_records_a_failed_call(events):
    await _run(_err(), [(GROQ, _err()), (GEMINI, _err())])
    (call,) = _model_calls(events)
    assert call["outcome"] == "quota" and call["served_by"] is None and call["hop"] is None
    assert [f["provider"] for f in call["failures"]] == ["nvidia", "groq", "google_genai"]


async def test_byok_failure_never_walks_and_is_tagged_byok(events):
    await _run(_err("[401] Unauthorized"), [(GROQ, _ok())], using_shared=False)
    (call,) = _model_calls(events)
    assert call["tier"] == "byok" and call["outcome"] == "auth" and len(call["failures"]) == 1


async def test_unclassified_error_is_recorded_as_error(events):
    await _run(_err("something odd"), [(GROQ, _ok())])
    (call,) = _model_calls(events)
    assert call["outcome"] == "error" and call["failures"][0]["kind"] == "error"


# ---------------------------------------------------------- memory events

def test_memory_save_outcomes(events, monkeypatch):
    class _Mem:
        def __init__(self, results):
            self.results = results

        def add(self, text, user_id=None):
            return {"results": self.results}

    monkeypatch.setattr(ms, "_memory_save_capped", lambda uid: False)
    monkeypatch.setattr(ms, "_get_memory", lambda p=None, k=None: _Mem([{"memory": "x"}]))
    ms.remember("u1", "fact")
    monkeypatch.setattr(ms, "_get_memory", lambda p=None, k=None: _Mem([]))
    ms.remember("u1", "small talk")
    monkeypatch.setattr(ms, "_memory_save_capped", lambda uid: True)
    ms.remember("u1", "over the cap")
    monkeypatch.setattr(ms, "_get_memory", lambda p=None, k=None: None)
    ms.remember("u1", "nothing configured")

    saves = [e["outcome"] for e in events if e["event"] == "memory_save"]
    assert saves == ["saved", "nothing_to_save", "capped", "unavailable"]


def test_memory_recall_counts_hits(events, monkeypatch):
    class _Mem:
        def search(self, q, filters=None, top_k=5):
            return {"results": [{"memory": "a"}, {"memory": "b"}]}

    monkeypatch.setattr(ms, "_get_memory", lambda p=None, k=None: _Mem())
    ms.recall("u1", "who is my manager")
    (rec,) = [e for e in events if e["event"] == "memory_recall"]
    assert rec["hits"] == 2 and rec["tier"] == "shared"


def test_no_event_ever_carries_message_text(events, monkeypatch):
    """Privacy page promise: ids and labels, never content."""
    class _Mem:
        def add(self, text, user_id=None):
            return {"results": [{"memory": text}]}

        def search(self, q, filters=None, top_k=5):
            return {"results": [{"memory": "secret fact"}]}

    monkeypatch.setattr(ms, "_memory_save_capped", lambda uid: False)
    monkeypatch.setattr(ms, "_get_memory", lambda p=None, k=None: _Mem())
    ms.remember("u1", "my bank pin is 4417")
    ms.recall("u1", "what is my bank pin")
    blob = repr(events)
    assert "4417" not in blob and "bank" not in blob and "secret fact" not in blob


# -------------------------------------------------------------- summarize()

def _ev(event, hours_ago=1, user="u1", **props):
    return {"event": event, "user_id": user, "ts": NOW - datetime.timedelta(hours=hours_ago), **props}


def _call(hop, provider, outcome="ok", failures=None, latency=1000, tier="shared", **kw):
    return _ev("model_call", hop=hop, provider=provider, outcome=outcome,
               failures=failures or [], latency_ms=latency, tier=tier, **kw)


def test_fallback_rate_counts_only_successful_shared_calls():
    evs = [
        _call(0, "nvidia"), _call(0, "nvidia"), _call(0, "nvidia"),
        _call(1, "groq", failures=[{"provider": "nvidia", "kind": "quota"}]),
        _call(None, None, outcome="quota", failures=[{"provider": "nvidia", "kind": "quota"}] * 3),
        _call(0, "openai", tier="byok"),  # BYOK never counts toward the shared rate
    ]
    m = analytics.summarize(evs, 7, NOW)["models"]
    assert m["calls"] == 6
    assert m["fallback_rate_pct"] == 25.0  # 1 of the 4 successful shared calls
    assert m["served_by"] == {"nvidia": 3, "groq": 1, "openai": 1}
    assert m["by_hop"] == {"primary": 4, "failover 1": 1}
    assert m["outcomes"] == {"ok": 5, "quota": 1}
    top = m["failed_attempts"][0]
    assert (top["provider"], top["kind"], top["count"]) == ("nvidia", "quota", 4)


def test_latency_percentiles_per_provider():
    evs = [_call(0, "nvidia", latency=ms_) for ms_ in (1000, 2000, 3000, 4000, 100000)]
    lat = analytics.summarize(evs, 7, NOW)["models"]["latency_ms"]["nvidia"]
    assert lat["n"] == 5 and lat["p50"] == 3000.0 and lat["p95"] > 4000


def test_window_drops_old_events_and_accepts_naive_mongo_datetimes():
    naive = {"event": "agent_run", "user_id": "u2",
             "ts": (NOW - datetime.timedelta(hours=2)).replace(tzinfo=None)}
    old = _ev("agent_run", hours_ago=24 * 30)
    out = analytics.summarize([naive, old], 7, NOW)
    assert out["totals"] == {"agent_run": 1}
    assert out["users"]["active"] == 1


def test_daily_rows_cover_every_day_including_empty_ones():
    evs = [_ev("agent_run", hours_ago=1), _ev("agent_run", hours_ago=1, user="u2"),
           _ev("signup", hours_ago=49, user="u3"), _call(1, "groq")]
    daily = analytics.summarize(evs, 3, NOW)["daily"]
    assert [d["day"] for d in daily] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    today = daily[-1]
    assert today["active_users"] == 2 and today["agent_runs"] == 2
    assert today["calls"] == 1 and today["fallback"] == 1
    assert daily[0]["signups"] == 1 and daily[1]["agent_runs"] == 0


def test_memory_tools_hitl_and_limits_roll_up():
    evs = [
        _ev("memory_save", outcome="saved"), _ev("memory_save", outcome="capped"),
        _ev("memory_recall", hits=2), _ev("memory_recall", hits=0),
        _ev("tool_call", tool="read_emails", outcome="ok"),
        _ev("tool_call", tool="read_emails", outcome="error"),
        _ev("tool_call", tool="send_email", outcome="ok"),
        _ev("hitl_decision", tool="send_email", approved=True),
        _ev("hitl_decision", tool="send_email", approved=False),
        _ev("rate_limited", limit="daily_shared"),
    ]
    out = analytics.summarize(evs, 7, NOW)
    assert out["memory"] == {"saves": {"saved": 1, "capped": 1}, "recalls": 2, "recall_hit_pct": 50.0}
    assert out["tools"]["calls"] == {"read_emails": 2, "send_email": 1}
    assert out["tools"]["errors"] == {"read_emails": 1}
    assert out["tools"]["hitl"] == {"send_email": {"approved": 1, "declined": 1}}
    assert out["rate_limited"] == {"daily_shared": 1}


def test_empty_window_is_well_formed():
    out = analytics.summarize([], 14, NOW)
    assert out["models"]["fallback_rate_pct"] is None
    assert out["memory"]["recall_hit_pct"] is None
    assert len(out["daily"]) == 14 and out["totals"] == {}
