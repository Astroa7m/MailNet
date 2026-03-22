import calendar
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

schedule_protocol = os.getenv("SCHEDULE_PROTOCOL")
schedule_host = os.getenv("SCHEDULE_HOST")
schedule_port = os.getenv("SCHEDULE_PORT")


def get_iso_based_on_args(
        seconds: Optional[int] = None,
        minutes: Optional[int] = None,
        hours: Optional[int] = None,
        day_of_month: Optional[int] = None,
        month: Optional[int] = None,
        year: Optional[int] = None,
        days_count_from_today: Optional[int] = None,
        day_string: Optional[str] = None,
) -> datetime:
    now = datetime.now()

    # case 1, provided days from today e.g. schedule it after 4 days
    if days_count_from_today:
        dt = now + timedelta(days=days_count_from_today)
        return dt

    # case 2, provided a day string e.g. schedule it Monday (then we get next monday)
    if day_string:
        day_string = day_string.capitalize()
        if day_string not in calendar.day_name:
            raise ValueError(f"Invalid day string: {day_string}")
        target_weekday = list(calendar.day_name).index(day_string)
        days_ahead = (target_weekday - now.weekday() + 7) % 7
        if days_ahead == 0:  # if today, schedule next week
            days_ahead = 7
        return (now + timedelta(days=days_ahead)).replace(
            hour=hours or now.hour, minute=minutes or now.minute, second=seconds or now.second, microsecond=0
        )

    # case 3, exact date
    if year and month and day_of_month:
        return datetime(
            year, month, day_of_month,
            hours or 0, minutes or 0, seconds or 0
        )

    # last case, only time, then next time
    if hours is not None or minutes is not None or seconds is not None:
        target = now + timedelta(hours=hours or 0, minutes=minutes or 0, seconds=seconds or 0)
        if target <= now:  # if time already passed today
            target += timedelta(days=1)
        return target

    raise ValueError("At least one scheduling parameter required")


def schedule_send_email(
        to: str,
        subject: str,
        body: str,
        seconds: Optional[int] = None,
        minutes: Optional[int] = None,
        hours: Optional[int] = None,
        day_of_month: Optional[int] = None,
        month: Optional[int] = None,
        year: Optional[int] = None,
        days_count_from_today: Optional[int] = None,
        day_string: Optional[str] = None,
        user_id: str = "tester-user-001"
):
    """
    schedules email to send, if succeeded, you should return the scheduled datetime to the user in human-readable way
    :param user_id: current user id interacting with the application
    :param to: recipient of the email
    :param subject: subject of the email
    :param body: body of the email
    :param seconds: seconds of the time to schedule
    :param minutes: minutes of the time to schedule
    :param hours: hours of the time to schedule
    :param day_of_month: day of the month of the time to schedule
    :param month: month of the time to schedule
    :param year: year of the time to schedule
    :param days_count_from_today: how many days from today to schedule
    :param day_string: day in form of a string to schedule
    :return: success or failure message
    """
    response = None
    dt = get_iso_based_on_args(seconds, minutes, hours, day_of_month, month, year, days_count_from_today, day_string)

    endpoint = f"{schedule_protocol}://{schedule_host}:{schedule_port}/schedule_one_shot"

    json_payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "dt": dt.isoformat(),
        "user_id": user_id
    }

    try:
        response = requests.post(endpoint, json=json_payload)
        response.raise_for_status()
        return f"Schedule successfully, message will be sent on {dt.isoformat()}"
    except Exception as e:
        extras = f"\nCode: {response.status_code}, Error: {response.text}" if response else ""
        return f"Scheduled failed, error while connecting to the server: {e}." + extras
