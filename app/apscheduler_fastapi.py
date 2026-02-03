from datetime import datetime
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Body

# the scheduler must always be alive in the server to avoid losing jobs for users
# we can also persist it for better sclaing
# gonna think later about the arch
# todo: fix the cron scheduling

api = FastAPI()

scheduler = BackgroundScheduler()
scheduler.start()


def hello(name):
    print(f"Hello {name}")


tools_dict = {
    "hello": hello
}


@api.post("/schedule_one_shot")
def schedule_one_shot_event(
        func_name: str = Body(...),
        datetime_iso_string: str = Body(...),
        kwargs: dict = Body(...)
):
    # e.g. "2026-02-02T20:31:00+04:00"
    func = tools_dict[func_name]
    date = datetime.fromisoformat(datetime_iso_string).isoformat()
    scheduler.add_job(func, "date", run_date=date, kwargs=kwargs)


@api.post("/schedule_recurring")
def schedule_recurring_event(func, day_of_week, hour, minute, second, kwargs):
    scheduler.add_job(func, "cron", day_of_week=day_of_week, hour=hour, minute=minute, second=second, kwargs=kwargs)


if __name__ == "__main__":
    # Runs the server on localhost port 8000
    uvicorn.run(api, host="127.0.0.1", port=8000)
