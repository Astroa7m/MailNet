"""Resumable model eval harness for MailNet's real agent graph.

Runs the REAL build_agent (system prompt, dynamic tools, HITL middleware,
failover chain) against stub mail tools, one candidate model at a time, and
scores each scenario with deterministic checks.

Provider isolation: each candidate runs with SHARED_CHAT_CHAIN pinned to a
single provider, so the failover chain has zero hops and can never silently
answer for the model under test.

Quota reality (NVIDIA free tier 429s unpredictably): every (model, scenario,
repeat) cell is written to a JSONL ledger the moment it finishes; a 429 marks
the cell quota_blocked instead of fail; --resume RUN_ID skips cells that
already concluded, so a run can be finished across days.

Usage:
  python -m tests.evals.run_evals --models nvidia:openai/gpt-oss-120b,groq:openai/gpt-oss-120b
  python -m tests.evals.run_evals --resume 20260827-1 --models ...
  python -m tests.evals.run_evals --dry          (offline machinery self-test)

Safety: the harness is the human in the HITL loop. It approves an interrupt
only when the scenario says approve AND any recipient in the args is in
scenarios.SAFE_RECIPIENTS. Everything else is declined and recorded.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Deterministic, network-safe defaults land BEFORE app imports (dotenv does
# not override existing vars). Real provider keys are expected in the real
# environment or .env for live runs; --dry needs none.
os.environ.setdefault("MONGO_DB_URL", "mongodb://127.0.0.1:9/?serverSelectionTimeoutMS=100&connectTimeoutMS=100")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:9/0")
if "ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
if os.environ.get("OPENROUTER_API_KEY"):
    sys.exit("OPENROUTER_API_KEY is set; it hijacks mem0/openai clients. Unset it and rerun.")

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import app.common as common
from app.llm_errors import quota_message
from tests.evals import checks as C
from tests.evals.scenarios import SAFE_RECIPIENTS, SCENARIOS
from tests.stubs import stub_mail_tools as stubs
from tests.stubs.stub_llms import ScriptedChatModel


class Meter(AsyncCallbackHandler):
    """Counts model calls and captures time to first token."""

    def __init__(self):
        self.model_calls = 0
        self.t_start = None
        self.ttft = None

    async def on_chat_model_start(self, *a, **k):
        self.model_calls += 1
        if self.t_start is None:
            self.t_start = time.perf_counter()

    async def on_llm_new_token(self, *a, **k):
        if self.ttft is None and self.t_start is not None:
            self.ttft = time.perf_counter() - self.t_start


class _FakeColl:
    def find_one(self, *a, **k): return None
    def update_one(self, *a, **k): return None
    def insert_one(self, *a, **k): return None
    def delete_many(self, *a, **k): return None


class _FakeDB:
    def __getitem__(self, name): return _FakeColl()


def _patch_offline(candidate_provider: str, candidate_model: str, prefs_override, scheduler_calls: list):
    """Point app.common at fakes and the candidate model. Returns undo()."""
    saved = {
        "db": common.db,
        "ckpt": common._checkpointer_inst,
        "sched_once": common.schedule_send_email,
        "sched_cron": common.schedule_recurring_email,
        "prefs": common.DEFAULT_PREFERENCES,
        "model": dict(common.DEFAULT_CHAT_MODELS),
        "chain_env": os.environ.get("SHARED_CHAT_CHAIN"),
    }
    common.db = _FakeDB()
    common._checkpointer_inst = InMemorySaver()

    def _sched_recorder(**kwargs):
        scheduler_calls.append(kwargs)
        return "Scheduled successfully. The email will be sent at the requested time."

    common.schedule_send_email = _sched_recorder
    common.schedule_recurring_email = _sched_recorder
    if prefs_override:
        merged = dict(common.DEFAULT_PREFERENCES)
        merged.update(prefs_override)
        common.DEFAULT_PREFERENCES = merged
    common.DEFAULT_CHAT_MODELS[candidate_provider] = candidate_model
    os.environ["SHARED_CHAT_CHAIN"] = candidate_provider

    def undo():
        common.db = saved["db"]
        common._checkpointer_inst = saved["ckpt"]
        common.schedule_send_email = saved["sched_once"]
        common.schedule_recurring_email = saved["sched_cron"]
        common.DEFAULT_PREFERENCES = saved["prefs"]
        common.DEFAULT_CHAT_MODELS.clear()
        common.DEFAULT_CHAT_MODELS.update(saved["model"])
        if saved["chain_env"] is None:
            os.environ.pop("SHARED_CHAT_CHAIN", None)
        else:
            os.environ["SHARED_CHAT_CHAIN"] = saved["chain_env"]

    return undo


def _dry_primary():
    """Scripted model for --dry: one read_emails call, then a short answer."""
    return ScriptedChatModel(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "read_emails", "args": {"max_results": 5}, "id": "dry1"}]),
        AIMessage(content="Here is your inbox summary. Nothing urgent."),
    ]))


def _recipient_safe(args: dict) -> bool:
    to = args.get("to") or args.get("recipient")
    return to is None or str(to).lower() in SAFE_RECIPIENTS


async def _run_cell(scenario, provider, model, dry: bool):
    """Execute one scenario against one model. Returns the ledger record body."""
    stubs.reset_log()
    scheduler_calls: list = []
    undo = _patch_offline(provider, model, scenario.prefs_override, scheduler_calls)
    meter = Meter()
    t0 = time.perf_counter()
    interrupt_seen = False
    interrupt_tool = ""
    try:
        if dry:
            # Bypass the provider entirely: swap the shared builder.
            saved_builder = common._build_shared_llm
            common._build_shared_llm = lambda _p: _dry_primary()
        agent = await common.build_agent(
            azure_token=None,
            google_token={"token": "stub", "refresh_token": "stub"},
            user_tz="UTC",
            user_id=None,
            disconnected=None,
            recalled_context=scenario.recalled_context,
            prefetched_mcp_tools=list(stubs.STUB_TOOLS),
        )
        cfg = {"configurable": {"thread_id": f"eval-{provider}-{scenario.id}"},
               "callbacks": [meter]}
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=scenario.prompt)]}, cfg
        )
        turns = 0
        while "__interrupt__" in result and turns < scenario.max_turns:
            payload = C.interrupt_payload(result) or {}
            if not interrupt_seen:
                interrupt_seen = True
                interrupt_tool = str(payload.get("tool", ""))
            args = payload.get("args") or {}
            approve = bool(scenario.approve) and _recipient_safe(args)
            result = await agent.ainvoke(Command(resume={"approved": approve}), cfg)
            turns += 1

        texts = []
        for m in result.get("messages", []):
            c = getattr(m, "content", "")
            texts.append(c if isinstance(c, str) else json.dumps(c, default=str))

        final = C.final_text(result)
        if final == quota_message(True):
            return {"status": "quota_blocked", "error_text": "terminal quota message"}

        result["_interrupt_seen"] = interrupt_seen
        result["_interrupt_tool"] = interrupt_tool
        result["_scheduler_calls"] = scheduler_calls
        checks = scenario.check(result, list(stubs.CALL_LOG), texts)
        status = "pass" if all(checks.values()) else "fail"
        return {
            "status": status,
            "checks": checks,
            "latency": {
                "total_s": round(time.perf_counter() - t0, 2),
                "ttft_s": round(meter.ttft, 2) if meter.ttft else None,
                "model_calls": meter.model_calls,
            },
            "interrupt": {"seen": interrupt_seen, "tool": interrupt_tool},
            "call_log": [[n, a] for n, a in stubs.CALL_LOG],
            "final_text": final[:500],
            "paired": C.tool_call_ids_paired(result.get("messages", [])),
        }
    except Exception as e:
        text = str(e)
        status = "quota_blocked" if "[429]" in text or "429" in text[:40] else "error"
        return {"status": status, "error_text": text[:400]}
    finally:
        if dry:
            common._build_shared_llm = saved_builder
        undo()


def _load_done(ledger: Path) -> set:
    done = set()
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") in ("pass", "fail"):
                done.add((r["model_key"], r["scenario"], r["repeat"]))
    return done


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="nvidia:openai/gpt-oss-120b",
                    help="comma list of provider:model, e.g. nvidia:meta/llama-3.3-70b-instruct,groq:openai/gpt-oss-120b")
    ap.add_argument("--scenarios", default="", help="comma list of scenario ids to run (default: all)")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--resume", default="", help="run id to continue")
    ap.add_argument("--max-calls", type=int, default=250, help="hard cap on model calls this process")
    ap.add_argument("--dry", action="store_true", help="offline self-test with a scripted model")
    args = ap.parse_args()

    run_id = args.resume or time.strftime("%Y%m%d-%H%M%S")
    out = _ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "results.jsonl"
    done = _load_done(ledger) if args.resume else set()

    model_keys = [m.strip() for m in args.models.split(",") if m.strip()]
    wanted = {s.strip() for s in args.scenarios.split(",") if s.strip()}
    scenarios = [s for s in SCENARIOS if not wanted or s.id in wanted]

    if not args.dry:
        for mk in model_keys:
            prov = mk.split(":", 1)[0]
            env = common.SHARED_CHAT_KEYS.get(prov)
            if not env or not os.environ.get(env):
                sys.exit(f"{mk}: no key in {env or 'unknown env var'}; set it or use --dry")

    total_calls = 0
    for mk in model_keys:
        provider, model = mk.split(":", 1)
        for sc in scenarios:
            for rep in range(1, args.repeats + 1):
                key = (mk, sc.id, rep)
                if key in done:
                    print(f"skip (done)  {mk}  {sc.id}  #{rep}")
                    continue
                if total_calls >= args.max_calls:
                    print(f"budget reached ({args.max_calls} calls); stopping. Resume with --resume {run_id}")
                    return
                print(f"run          {mk}  {sc.id}  #{rep}", flush=True)
                body = await _run_cell(sc, provider, model, args.dry)
                total_calls += (body.get("latency") or {}).get("model_calls", 1)
                record = {"run_id": run_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "model_key": mk, "scenario": sc.id, "repeat": rep, **body}
                with ledger.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
                print(f"  -> {body['status']}"
                      + (f"  failed: {[k for k, v in body.get('checks', {}).items() if not v]}"
                         if body.get("status") == "fail" else ""))
    print(f"\nledger: {ledger}\nreport: python -m tests.evals.report {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
