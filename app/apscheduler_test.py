from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

# the scheduler must always be alive in the server to avoid losing jobs for users
# we can also persist it for better sclaing
# gonna think later about the arch
scheduler = BackgroundScheduler()
scheduler.start()

def sayHey(for_name):
    print(f"Hey {for_name}")

def get_current_data_time():
    return datetime.now().isoformat()

def schedule_one_shot_event(func, datetime_iso_string):
    # e.g. "2026-02-02T20:31:00+04:00"
    date = datetime.fromisoformat(datetime_iso_string).isoformat()
    scheduler.add_job(func, "date", run_date=date, kwargs={"for_name": "Ahmed"})



def schedule_recurring_event(func, day_of_week, hour, minute, second):
    scheduler.add_job(func, "cron", day_of_week=day_of_week, hour=hour, minute=minute, second=second, kwargs={
        "for_name": "Ahmed"})

# todo: fix the cron scheduling

try:
    while True:
        pass
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()

