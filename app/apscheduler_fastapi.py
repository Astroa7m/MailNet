import os
from datetime import datetime

import requests
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request

api = FastAPI()
load_dotenv()

send_email_tool_url = os.getenv("SEND_EMAIL_URL")

scheduler = BackgroundScheduler()
scheduler.start()


def send_email_route(
        to: str,
        subject: str,
        body: str,
):
    endpoint = f"{send_email_tool_url}/send_email"

    response = None

    json_payload = {
        "to": to,
        "subject": subject,
        "body": body,
    }

    try:
        response = requests.post(endpoint, json=json_payload)
        response.raise_for_status()
        return f"Send email request has been successfully requested"
    except Exception as e:
        extras = "\nCode: {response.status_code}, Error: {response.text}" if response else ""
        return f"Requesting send email failed, error while connecting to the server: {e}." + extras


# todo: fix the cron scheduling
@api.post("/schedule_one_shot")
async def schedule_one_shot_event(
        req: Request
):
    # e.g. "2026-02-02T20:31:00+04:00"

    data = await req.json()
    dt = data['dt']
    del data['dt']

    date = datetime.fromisoformat(dt).isoformat()
    scheduler.add_job(send_email_route, "date", run_date=date, kwargs=data)


@api.post("/schedule_recurring")
def schedule_recurring_event(func, day_of_week, hour, minute, second, kwargs):
    scheduler.add_job(func, "cron", day_of_week=day_of_week, hour=hour, minute=minute, second=second, kwargs=kwargs)


if __name__ == "__main__":
    # Runs the server on localhost port 8000
    uvicorn.run(api, host="127.0.0.1", port=8000)
