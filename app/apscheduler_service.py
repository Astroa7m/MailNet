import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import uuid4

import uvicorn
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from langchain_mcp_adapters.client import MultiServerMCPClient
from pymongo import MongoClient

load_dotenv()

schedule_host = os.getenv("SCHEDULE_HOST")
schedule_port = os.getenv("SCHEDULE_PORT")
mailnet_server_url = os.getenv("MAILNET_SERVER_URL")
mongo_connection_string = os.getenv("MONGO_DB_URL")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


api = FastAPI(lifespan=lifespan)

mongo_job_store = MongoDBJobStore(
    client=MongoClient(host=mongo_connection_string),
    database="MailNet",
    collection="schedules"
)

scheduler = AsyncIOScheduler(jobstores={"default": mongo_job_store})

MAX_RETRIES = 3
RETRY_DELAYS = [10, 30, 60]

# This service publishes no ports, but it took user_id as plain request data, so
# anything able to reach it could schedule, list, or cancel mail for any user.
# Every route now requires a shared secret.
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "")
if not SCHEDULER_SECRET:
    print("[SCHEDULER] WARNING: SCHEDULER_SECRET is not set; routes will refuse requests")


def _require_secret(req: Request) -> None:
    presented = req.headers.get("x-scheduler-secret", "")
    if not SCHEDULER_SECRET or not secrets.compare_digest(presented, SCHEDULER_SECRET):
        raise HTTPException(status_code=404, detail="Not found")


async def _fresh_tokens(user_id: str):
    """Mint fresh access tokens from the user's CURRENT stored refresh tokens.

    Jobs used to carry an encrypted token snapshot taken at scheduling time.
    That snapshot went stale within the hour, persisted in Mongo forever, and
    survived logout. Resolving at fire time means a recurring job keeps working
    and self-heals after the user signs in again. Rotated refresh tokens are
    written back, which Microsoft requires."""
    from bson import ObjectId
    from common import (
        db, decrypt_payload, encrypt_payload,
        refresh_google_token_if_needed, refresh_microsoft_token_if_needed,
    )

    doc = db["users"].find_one(
        {"_id": ObjectId(user_id)},
        {"google_refresh_token": 1, "microsoft_refresh_token": 1},
    ) or {}

    google_token = azure_token = None

    if doc.get("google_refresh_token"):
        try:
            stored = decrypt_payload(doc["google_refresh_token"])["token"]
            minimal = {
                "token": "", "refresh_token": stored,
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "scopes": ["https://mail.google.com/"],
                "expiry": "2000-01-01T00:00:00Z",
            }
            fresh = await refresh_google_token_if_needed(minimal)
            google_token = encrypt_payload(fresh)
            new_refresh = fresh.get("refresh_token")
            if new_refresh and new_refresh != stored:
                db["users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"google_refresh_token": encrypt_payload({"token": new_refresh})}},
                )
        except Exception as e:
            print("[SCHEDULER] google token refresh failed for", user_id, repr(e))

    if doc.get("microsoft_refresh_token"):
        try:
            stored = decrypt_payload(doc["microsoft_refresh_token"])["token"]
            fresh = await refresh_microsoft_token_if_needed({"refresh_token": stored, "expires_at": 0})
            azure_token = encrypt_payload(fresh)
            new_refresh = fresh.get("refresh_token")
            if new_refresh and new_refresh != stored:
                db["users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"microsoft_refresh_token": encrypt_payload({"token": new_refresh})}},
                )
        except Exception as e:
            print("[SCHEDULER] microsoft token refresh failed for", user_id, repr(e))

    return google_token, azure_token


def _record_failure(user_id: str, to: str, subject: str, reason) -> None:
    """Persist a permanent failure so the user can be told, instead of the send
    vanishing into the log."""
    try:
        from common import db
        db["scheduled_failures"].insert_one({
            "user_id": user_id, "to": to, "subject": subject,
            "reason": str(reason)[:500],
            "failed_at": datetime.utcnow(), "seen": False,
        })
    except Exception as e:
        print("[SCHEDULER] could not record failure:", repr(e))


async def send_email_route(
        to: str,
        subject: str,
        body: str,
        user_id: str,
        google_token: Optional[str] = None,
        azure_token: Optional[str] = None,
        default_provider: str = "google",
):
    # google_token / azure_token stay in the signature so jobs written by an
    # older build still load, but they are ignored: credentials are resolved
    # fresh from the user record at fire time.
    google_token, azure_token = await _fresh_tokens(user_id)
    if not google_token and not azure_token:
        reason = "no usable mail credentials; the user needs to reconnect their account"
        print("[SCHEDULER]", reason, "user=", user_id)
        _record_failure(user_id, to, subject, reason)
        raise RuntimeError(reason)

    headers = {
        "redirect_uri": "http://localhost/",
        "default_provider": default_provider,
    }
    if google_token:
        headers["google_token"] = google_token
    if azure_token:
        headers["azure_token"] = azure_token

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            mcp = MultiServerMCPClient({
                "email_mcp": {
                    "transport": "streamable_http",
                    "url": mailnet_server_url,
                    "headers": headers,
                }
            })
            tools = await mcp.get_tools()
            send_tool = next((t for t in tools if t.name == "send_email"), None)
            if not send_tool:
                raise RuntimeError("send_email tool not found on MCP server")
            result = await send_tool.ainvoke({"to": to, "subject": subject, "body": body})
            print(f"[SCHEDULER] Email sent to {to} (attempt {attempt + 1}): {result}")
            return f"Email sent successfully: {result}"
        except Exception as e:
            last_error = e
            print(f"[SCHEDULER] Attempt {attempt + 1}/{MAX_RETRIES} failed for {to}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

    print(f"[SCHEDULER] All {MAX_RETRIES} attempts failed for {to}: {last_error}")
    _record_failure(user_id, to, subject, last_error)
    raise RuntimeError(f"Failed to send scheduled email to {to} after {MAX_RETRIES} attempts: {last_error}")


@api.post("/schedule_one_shot")
async def schedule_one_shot_event(req: Request):
    _require_secret(req)
    data = await req.json()
    dt = data.pop("dt")
    run_date = datetime.fromisoformat(dt).isoformat()

    # Whitelist the executor kwargs. The entire request body used to be splatted
    # in, so any extra key became a call argument.
    job_kwargs = {
        "to": data["to"],
        "subject": data["subject"],
        "body": data["body"],
        "user_id": data.get("user_id", ""),
        "default_provider": data.get("default_provider", "google"),
    }

    job = scheduler.add_job(
        func=send_email_route,
        trigger="date",
        run_date=run_date,
        kwargs=job_kwargs,
        name="scheduled_one_shot_email",
        # Ids were derived from user + minute with replace_existing, so two sends
        # scheduled for the same minute silently destroyed each other.
        id="one_shot_" + str(job_kwargs["user_id"]) + "_" + uuid4().hex,
        # A short grace meant any job due during a deploy or outage was dropped
        # for good. A day of slack means it still goes out once we are back.
        misfire_grace_time=86400,
    )
    return {"status": "scheduled", "job_id": job.id, "run_date": run_date}


@api.post("/schedule_recurring")
async def schedule_recurring_event(req: Request):
    _require_secret(req)
    data = await req.json()

    # No token material is persisted with the job; it is resolved at fire time.
    job_kwargs = {
        "to": data["to"],
        "subject": data["subject"],
        "body": data["body"],
        "user_id": data.get("user_id", ""),
        "default_provider": data.get("default_provider", "google"),
    }

    cron_fields = {
        k: data[k] for k in ("hour", "minute", "second", "day_of_week", "day", "month")
        if k in data and data[k] is not None
    }
    timezone = data.get("timezone", "UTC")

    safe_to = data["to"].replace("@", "_").replace(".", "_")
    job_id = f"cron_{data.get('user_id', 'unknown')}_{safe_to}_{'_'.join(f'{k}{v}' for k, v in cron_fields.items())}"

    job = scheduler.add_job(
        func=send_email_route,
        trigger="cron",
        kwargs=job_kwargs,
        id=job_id,
        replace_existing=True,
        # 60s of grace silently dropped any occurrence due during a deploy or a
        # restart. coalesce collapses a backlog into one send rather than N.
        misfire_grace_time=86400,
        coalesce=True,
        timezone=timezone,
        **cron_fields,
    )
    return {"status": "scheduled", "job_id": job.id, "trigger": str(job.trigger)}


def _job_summary(job) -> dict:
    """Public view of a job. kwargs carry encrypted OAuth tokens, so only
    whitelisted fields ever leave this service."""
    kw = job.kwargs or {}
    is_cron = type(job.trigger).__name__ == "CronTrigger"
    next_run = getattr(job, "next_run_time", None)
    return {
        "job_id": job.id,
        "to": kw.get("to", ""),
        "subject": kw.get("subject", ""),
        "type": "recurring" if is_cron else "one_time",
        "trigger": str(job.trigger),
        "next_run_time": next_run.isoformat() if next_run else None,
    }


@api.get("/jobs")
async def list_jobs(req: Request, user_id: str):
    _require_secret(req)
    jobs = [j for j in scheduler.get_jobs() if (j.kwargs or {}).get("user_id") == user_id]
    return {"jobs": [_job_summary(j) for j in jobs]}


@api.delete("/jobs/{job_id}")
async def delete_job(req: Request, job_id: str, user_id: str):
    _require_secret(req)
    job = scheduler.get_job(job_id)
    if not job or (job.kwargs or {}).get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="No such scheduled email for this user")
    summary = _job_summary(job)
    scheduler.remove_job(job_id)
    print(f"[SCHEDULER] Cancelled job {job_id} for user {user_id}")
    return {"status": "cancelled", **summary}


if __name__ == "__main__":
    uvicorn.run(api, host=schedule_host, port=int(schedule_port))
