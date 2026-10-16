import calendar
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

# The scheduler service authenticates callers with a shared secret; it used to
# accept whatever user_id a request claimed.
SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "")


def _scheduler_headers() -> dict:
    return {"x-scheduler-secret": SCHEDULER_SECRET} if SCHEDULER_SECRET else {}


schedule_protocol = os.getenv("SCHEDULE_PROTOCOL")
schedule_host = os.getenv("SCHEDULE_HOST")
schedule_port = os.getenv("SCHEDULE_PORT")

# A recurring email must pin a field coarser than minute/second, and must not
# fire more often than hourly. Without this an under-specified cron fires every
# second, flooding the user's own account (security review F3).
MIN_RECURRING_INTERVAL_S = 3600
MAX_RECURRING_JOBS_PER_USER = 20
_RECURRING_COARSE_FIELDS = ("hour", "day_of_week", "day", "month")


def validate_recurring_cron(cron_fields: dict, timezone: str = "UTC"):
    """Return (ok, reason). Rejects a cron schedule that would fire too often:
    one that pins nothing coarser than minute/second, or whose first two fire
    times are less than MIN_RECURRING_INTERVAL_S apart."""
    if not any(cron_fields.get(f) is not None for f in _RECURRING_COARSE_FIELDS):
        return False, (
            "A recurring email needs at least a time of day (an hour), and usually "
            "a weekday or day too. Without one it would fire every minute. Tell me "
            "when it should go out, for example 'every Monday at 9am'."
        )
    try:
        trigger = CronTrigger(timezone=timezone, **cron_fields)
        now = datetime.now(trigger.timezone)
        first = trigger.get_next_fire_time(None, now)
        if first is None:
            return True, ""  # never fires again, harmless
        nxt = trigger.get_next_fire_time(first, first + timedelta(seconds=1))
        if nxt is not None and (nxt - first).total_seconds() < MIN_RECURRING_INTERVAL_S:
            return False, (
                "That schedule would send more than once an hour. Please space it out "
                "to at most hourly."
            )
    except Exception as e:
        return False, f"I could not understand that schedule ({e}). Please restate it."
    return True, ""


def get_iso_based_on_args(
        minutes_from_now: Optional[int] = None,
        hours_from_now: Optional[int] = None,
        days_from_now: Optional[int] = None,
        day_string: Optional[str] = None,
        at_year: Optional[int] = None,
        at_month: Optional[int] = None,
        at_day: Optional[int] = None,
        at_hour: Optional[int] = None,
        at_minute: Optional[int] = None,
        at_second: Optional[int] = None,
        timezone: str = "UTC",
) -> datetime:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    # relative: X minutes/hours/days from now
    if minutes_from_now is not None or hours_from_now is not None:
        delta = timedelta(
            hours=hours_from_now or 0,
            minutes=minutes_from_now or 0,
        )
        return now + delta

    if days_from_now is not None:
        return now + timedelta(days=days_from_now)

    # next named weekday, optionally at a specific time
    if day_string:
        day_string = day_string.capitalize()
        if day_string not in calendar.day_name:
            raise ValueError(f"Invalid day: {day_string}. Use full English name e.g. 'Monday'.")
        target_weekday = list(calendar.day_name).index(day_string)
        days_ahead = (target_weekday - now.weekday() + 7) % 7
        if days_ahead == 0:
            days_ahead = 7
        base = now + timedelta(days=days_ahead)
        return base.replace(
            hour=at_hour if at_hour is not None else 9,
            minute=at_minute if at_minute is not None else 0,
            second=at_second if at_second is not None else 0,
            microsecond=0,
        )

    # specific date + time
    if at_year and at_month and at_day:
        return datetime(
            at_year, at_month, at_day,
            at_hour or 0, at_minute or 0, at_second or 0,
            tzinfo=tz,
        )

    # specific time today (or tomorrow if already passed)
    if at_hour is not None:
        target = now.replace(
            hour=at_hour,
            minute=at_minute if at_minute is not None else 0,
            second=at_second if at_second is not None else 0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        return target

    raise ValueError(
        "Provide one of: minutes_from_now, hours_from_now, days_from_now, "
        "day_string, at_hour (specific time today/tomorrow), "
        "or at_year+at_month+at_day for an exact date."
    )


def schedule_send_email(
        to: str,
        subject: str,
        body: str,
        minutes_from_now: Optional[int] = None,
        hours_from_now: Optional[int] = None,
        days_from_now: Optional[int] = None,
        day_string: Optional[str] = None,
        at_year: Optional[int] = None,
        at_month: Optional[int] = None,
        at_day: Optional[int] = None,
        at_hour: Optional[int] = None,
        at_minute: Optional[int] = None,
        at_second: Optional[int] = None,
        user_id: str = "",
        timezone: str = "UTC",
        google_token: Optional[str] = None,
        azure_token: Optional[str] = None,
        default_provider: str = "google",
):
    """
    Schedules a one-time email send.
    - Relative: minutes_from_now, hours_from_now, days_from_now
    - Named day: day_string (e.g. 'Monday') + optional at_hour/at_minute
    - Specific time today/tomorrow: at_hour + at_minute (if time already passed today, schedules tomorrow)
    - Exact date: at_year + at_month + at_day + optional at_hour/at_minute
    """
    response = None
    dt = get_iso_based_on_args(
        minutes_from_now=minutes_from_now,
        hours_from_now=hours_from_now,
        days_from_now=days_from_now,
        day_string=day_string,
        at_year=at_year, at_month=at_month, at_day=at_day,
        at_hour=at_hour, at_minute=at_minute, at_second=at_second,
        timezone=timezone,
    )

    endpoint = f"{schedule_protocol}://{schedule_host}:{schedule_port}/schedule_one_shot"

    json_payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "dt": dt.isoformat(),
        "user_id": user_id,
        "default_provider": default_provider,
    }

    try:
        response = requests.post(endpoint, json=json_payload, headers=_scheduler_headers(), timeout=15)
        response.raise_for_status()
        return f"Scheduled successfully. The email will be sent at {dt.strftime('%Y-%m-%d %H:%M %Z')}"
    except Exception as e:
        extras = f"\nCode: {response.status_code}, Error: {response.text}" if response else ""
        return f"Scheduling failed: {e}" + extras


def schedule_recurring_email(
        to: str,
        subject: str,
        body: str,
        user_id: str = "",
        timezone: str = "UTC",
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        second: Optional[int] = None,
        day_of_week: Optional[str] = None,
        day: Optional[int] = None,
        month: Optional[int] = None,
        google_token: Optional[str] = None,
        azure_token: Optional[str] = None,
        default_provider: str = "google",
):
    """
    Schedules a recurring email using cron syntax.
    day_of_week accepts: 'mon', 'tue', 'mon-fri', '1,3,5' (0=Monday).
    hour/minute are the time of day in the user's local timezone.
    Returns a success or failure message.
    """
    # Refuse an under-specified schedule before it reaches the scheduler, so the
    # model gets a clear reason instead of silently creating a once-a-second job
    # (security review F3).
    cron_fields = {}
    for _k, _v in (("hour", hour), ("minute", minute), ("second", second),
                   ("day", day), ("month", month)):
        if _v is not None:
            cron_fields[_k] = _v
    if day_of_week:
        cron_fields["day_of_week"] = day_of_week
    ok, reason = validate_recurring_cron(cron_fields, timezone)
    if not ok:
        return reason

    endpoint = f"{schedule_protocol}://{schedule_host}:{schedule_port}/schedule_recurring"

    payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "user_id": user_id,
        "timezone": timezone,
        "default_provider": default_provider,
    }
    if hour is not None:
        payload["hour"] = hour
    if minute is not None:
        payload["minute"] = minute
    if second is not None:
        payload["second"] = second
    if day_of_week:
        payload["day_of_week"] = day_of_week
    if day is not None:
        payload["day"] = day
    if month is not None:
        payload["month"] = month

    response = None
    try:
        response = requests.post(endpoint, json=payload, headers=_scheduler_headers(), timeout=15)
        response.raise_for_status()
        return f"Recurring email scheduled successfully. Job ID: {response.json().get('job_id')}"
    except Exception as e:
        extras = f"\nCode: {response.status_code}, Error: {response.text}" if response else ""
        return f"Failed to schedule recurring email: {e}" + extras
