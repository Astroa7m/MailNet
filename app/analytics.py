"""Product analytics: a small append-only event log in MongoDB.

track() is called from request paths (the model middleware, the agent
endpoint, memory), so it must never slow a request down or break one. It
only puts the event on an in-process queue; a single daemon thread writes
the queue to the `events` collection. When the queue is full or a write
fails, the event is dropped and logged at debug level. Losing an analytics
event is always better than losing a user's message.

Events carry ids and labels, never content: no message text, no email
addresses, no subjects. The privacy page says so, and the dashboard does not
need them.

Design notes:
- The database comes in through configure(get_db), a getter that common.py
  passes in. Importing common here would create an import cycle, and a
  getter (not the db object) means the eval harness's fake db is picked up
  when it patches common.db, so eval runs never write events to Atlas.
- summarize() is a pure function over a list of event dicts, so every number
  on the admin dashboard is unit tested without Mongo.
"""
import datetime
import logging
import os
import queue
import statistics
import threading
from collections import Counter, defaultdict
from typing import Callable, Optional

log = logging.getLogger("analytics")

EVENTS_COLLECTION = "events"
EVENTS_TTL_DAYS = int(os.getenv("ANALYTICS_TTL_DAYS", "90"))

_get_db: Optional[Callable] = None
_sink: Optional[Callable[[dict], None]] = None
_queue: "queue.Queue[dict]" = queue.Queue(maxsize=10_000)
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def configure(get_db: Callable) -> None:
    """Tell analytics how to reach the database. Called once by common.py."""
    global _get_db
    _get_db = get_db


def set_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Route events to a callable instead of Mongo (tests). None restores Mongo."""
    global _sink
    _sink = sink


def _enabled() -> bool:
    # Read at call time so tests and the eval harness can switch it per run.
    return os.getenv("ANALYTICS_ENABLED", "1") != "0"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def track(event: str, user_id: Optional[str] = None, **props) -> None:
    """Record one event. Never raises, never waits on the network."""
    try:
        doc = {"event": event, "ts": _now(), "user_id": str(user_id) if user_id else None}
        doc.update(props)
        if _sink is not None:
            _sink(doc)
            return
        if not _enabled() or _get_db is None:
            return
        _ensure_worker()
        _queue.put_nowait(doc)
    except queue.Full:
        log.debug("analytics queue full, dropped %s", event)
    except Exception as e:  # analytics must never break the caller
        log.debug("analytics track(%s) failed: %r", event, e)


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain_forever, name="analytics-writer", daemon=True)
            _worker.start()


def _drain_forever() -> None:
    while True:
        doc = _queue.get()
        try:
            _get_db()[EVENTS_COLLECTION].insert_one(doc)
        except Exception as e:
            log.debug("analytics write failed, dropped %s: %r", doc.get("event"), e)
        finally:
            _queue.task_done()


def flush(timeout: float = 5.0) -> bool:
    """Wait until queued events are written. For tests and graceful shutdown."""
    deadline = _now() + datetime.timedelta(seconds=timeout)
    while _queue.unfinished_tasks and _now() < deadline:
        threading.Event().wait(0.02)
    return _queue.unfinished_tasks == 0


def ensure_indexes(db) -> None:
    """TTL index so events expire on their own, plus the dashboard's query index."""
    coll = db[EVENTS_COLLECTION]
    coll.create_index("ts", expireAfterSeconds=EVENTS_TTL_DAYS * 86400, name="ttl_ts")
    coll.create_index([("event", 1), ("ts", -1)], name="event_ts")


def provider_of(label: Optional[str]) -> Optional[str]:
    """'groq/openai/gpt-oss-120b (shared failover)' gives 'groq'."""
    if not label:
        return None
    return label.split("/", 1)[0].strip() or None


# ----------------------------------------------------------------- dashboard

def _pct(values: list, q: int) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    return round(cuts[q - 1], 1)


def _as_utc(ts):
    # pymongo hands back naive datetimes that are already UTC.
    return ts.replace(tzinfo=datetime.timezone.utc) if ts.tzinfo is None else ts


def summarize(events: list, days: int, now: Optional[datetime.datetime] = None) -> dict:
    """Turn raw events into everything the admin dashboard shows.

    Pure function, no I/O. The window is the last `days` calendar days (UTC)
    ending at `now`, so events outside it are ignored and the caller may
    over-fetch.
    """
    now = _as_utc(now or _now())
    start = (now - datetime.timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_keys = [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    rows = []
    for e in events:
        ts = e.get("ts")
        if ts is None:
            continue
        ts = _as_utc(ts)
        if start <= ts <= now:
            rows.append((ts.strftime("%Y-%m-%d"), e))

    totals = Counter(e["event"] for _, e in rows)
    active = defaultdict(set)
    per_day_event = defaultdict(Counter)
    for d, e in rows:
        per_day_event[d][e["event"]] += 1
        if e.get("user_id"):
            active[d].add(e["user_id"])

    # Model calls: who actually served them, and how often we fell back.
    served_by, by_hop, outcomes, failed_attempts = Counter(), Counter(), Counter(), Counter()
    latency = defaultdict(list)
    per_day = {k: {"calls": 0, "fallback": 0, "failed": 0} for k in day_keys}
    shared_ok = shared_fallback = 0
    calls = [(d, e) for d, e in rows if e["event"] == "model_call"]
    for d, e in calls:
        outcome = e.get("outcome", "ok")
        outcomes[outcome] += 1
        per_day[d]["calls"] += 1
        hop = e.get("hop") or 0
        if outcome == "ok":
            prov = e.get("provider") or "unknown"
            served_by[prov] += 1
            by_hop["primary" if hop == 0 else f"failover {hop}"] += 1
            if hop:
                per_day[d]["fallback"] += 1
            if e.get("tier") == "shared":
                shared_ok += 1
                shared_fallback += 1 if hop else 0
            if e.get("latency_ms") is not None:
                latency[prov].append(float(e["latency_ms"]))
        else:
            per_day[d]["failed"] += 1
        for f in e.get("failures") or []:
            failed_attempts[(f.get("provider") or "unknown", f.get("kind") or "error")] += 1

    saves = Counter(e.get("outcome", "unknown") for _, e in rows if e["event"] == "memory_save")
    recalls = [e for _, e in rows if e["event"] == "memory_recall"]
    tool_calls = [e for _, e in rows if e["event"] == "tool_call" and e.get("tool")]
    hitl = defaultdict(lambda: {"approved": 0, "declined": 0})
    for _, e in rows:
        if e["event"] == "hitl_decision" and e.get("tool"):
            hitl[e["tool"]]["approved" if e.get("approved") else "declined"] += 1

    daily = [
        {
            "day": k,
            "active_users": len(active.get(k, ())),
            **per_day[k],
            "agent_runs": per_day_event[k]["agent_run"],
            "signups": per_day_event[k]["signup"],
            "rate_limited": per_day_event[k]["rate_limited"],
        }
        for k in day_keys
    ]

    return {
        "window": {"days": days, "start": day_keys[0], "end": day_keys[-1]},
        "totals": dict(totals),
        "users": {
            "active": len({e["user_id"] for _, e in rows if e.get("user_id")}),
            "signups": totals.get("signup", 0),
        },
        "models": {
            "calls": len(calls),
            "outcomes": dict(outcomes),
            "served_by": dict(served_by.most_common()),
            "by_hop": dict(by_hop.most_common()),
            "fallback_rate_pct": round(100 * shared_fallback / shared_ok, 1) if shared_ok else None,
            "failed_attempts": [
                {"provider": p, "kind": k, "count": n} for (p, k), n in failed_attempts.most_common()
            ],
            "latency_ms": {
                prov: {"p50": _pct(v, 50), "p95": _pct(v, 95), "n": len(v)}
                for prov, v in sorted(latency.items())
            },
        },
        "memory": {
            "saves": dict(saves),
            "recalls": len(recalls),
            "recall_hit_pct": (
                round(100 * sum(1 for e in recalls if (e.get("hits") or 0) > 0) / len(recalls), 1)
                if recalls else None
            ),
        },
        "tools": {
            "calls": dict(Counter(e["tool"] for e in tool_calls).most_common()),
            "errors": dict(Counter(e["tool"] for e in tool_calls if e.get("outcome") == "error").most_common()),
            "hitl": dict(sorted(hitl.items())),
        },
        "rate_limited": dict(Counter(e.get("limit", "unknown") for _, e in rows if e["event"] == "rate_limited")),
        "daily": daily,
    }
