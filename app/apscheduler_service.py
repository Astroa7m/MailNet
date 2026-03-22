import os
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastmcp import Client
from pymongo import MongoClient

load_dotenv()

schedule_host = os.getenv("SCHEDULE_HOST")
schedule_port = os.getenv("SCHEDULE_PORT")
mailnet_server_url = os.getenv("MAILNET_SERVER_URL")
mongo_connection_string = os.getenv("MONGO_DB_URL")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # this runs when FastAPI starts
    scheduler.start()
    yield
    # this runs when FastAPI stops
    scheduler.shutdown()


api = FastAPI(lifespan=lifespan)
mcp_client = Client(mailnet_server_url)

mongo_job_store = MongoDBJobStore(
    client=MongoClient(host=mongo_connection_string),
    database="MailNet",
    collection="schedules"
)

jobstores = {
    'default': mongo_job_store
}

scheduler = AsyncIOScheduler(jobstores=jobstores)


async def send_email_route(
        to: str,
        subject: str,
        body: str,
        user_id: str
):
    response = None

    payload = {
        "to": to,
        "subject": subject,
        "body": body,
        # "user_id": user_id
    }

    try:
        async with mcp_client:
            response = await mcp_client.call_tool("send_email", payload)
            print("we called it", response)
            return f"Send email request has been successfully requested: {response}"
    except Exception as e:
        extras = "\nCode: {response.status_code}, Error: {response.text}" if response else ""
        return f"Requesting send email failed, error while connecting to the server: {e}." + extras


# todo: fix the cron scheduling
@api.post("/schedule_one_shot")
async def schedule_one_shot_event(
        req: Request,
):
    # e.g. "2026-02-02T20:31:00+04:00"

    data = await req.json()
    dt = data.pop('dt')

    date = datetime.fromisoformat(dt).isoformat()
    job = scheduler.add_job(
        func=send_email_route,
        trigger="date",
        run_date=date,
        kwargs=data,
        name="Sending email scheduled",
        id=f"job()_for_({data['user_id']})_run_at_{dt}"
    )
    return {"status": "scheduled", "job_id": job.id, "run_date": date}


@api.post("/schedule_recurring")
def schedule_recurring_event(func, day_of_week, hour, minute, second, kwargs):
    scheduler.add_job(func, "cron", day_of_week=day_of_week, hour=hour, minute=minute, second=second, kwargs=kwargs)


if __name__ == "__main__":
    uvicorn.run(api, host=schedule_host, port=int(schedule_port))
    # res = asyncio.run(send_email_route("ahmed123.as27@gmail.com", "test subject", "test body", ""))
    # print(res)
