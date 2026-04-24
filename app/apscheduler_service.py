import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import uvicorn
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
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


async def send_email_route(
        to: str,
        subject: str,
        body: str,
        user_id: str,
        google_token: Optional[str] = None,
        azure_token: Optional[str] = None,
        default_provider: str = "google",
):
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
    raise RuntimeError(f"Failed to send scheduled email to {to} after {MAX_RETRIES} attempts: {last_error}")


@api.post("/schedule_one_shot")
async def schedule_one_shot_event(req: Request):
    data = await req.json()
    dt = data.pop("dt")
    run_date = datetime.fromisoformat(dt).isoformat()

    job = scheduler.add_job(
        func=send_email_route,
        trigger="date",
        run_date=run_date,
        kwargs=data,
        name="scheduled_one_shot_email",
        id=f"one_shot_for_{data.get('user_id')}_at_{dt}",
        replace_existing=True,
        misfire_grace_time=300,
    )
    return {"status": "scheduled", "job_id": job.id, "run_date": run_date}


@api.post("/schedule_recurring")
async def schedule_recurring_event(req: Request):
    data = await req.json()

    job_kwargs = {
        "to": data["to"],
        "subject": data["subject"],
        "body": data["body"],
        "user_id": data.get("user_id", ""),
        "google_token": data.get("google_token"),
        "azure_token": data.get("azure_token"),
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
        misfire_grace_time=60,
        timezone=timezone,
        **cron_fields,
    )
    return {"status": "scheduled", "job_id": job.id, "trigger": str(job.trigger)}


if __name__ == "__main__":
    uvicorn.run(api, host=schedule_host, port=int(schedule_port))
