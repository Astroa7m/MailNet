from datetime import datetime

import requests


# todo: Make sure the timezone is sit well for diff locations
def get_current_datatime():
    """
    You must call this tool before any scheduling to get the correct date and time in iso format
    :return: datetime in iso
    """
    return datetime.now().isoformat()


def schedule_one_shot_event(second: int, minute: int, hour: int, day: int, month: int, year: int, func_name, kwargs):
    """
    This function is used to schedule events for one time only
    You can use it when the user asks for scheduling an action
    :param hour: hour of the time for the schedule
    :param second: seconds of the time for the schedule
    :param minute: minute of the time for the schedule
    :param day: day of the time for the schedule
    :param month: month of the time for the schedule
    :param year: year of the time for the schedule
    :param func: the function to schedule this event from your tools
    :param kwargs: the function arguments
    :return: Status message
    """

    dt = datetime(year=year, month=month, day=day, hour=hour, minute=minute, second=second).isoformat()

    url = f"http://127.0.0.1:8000/schedule_one_shot"

    json_payload = {
        "func_name": func_name,
        "datetime_iso_string": dt,
        "kwargs": kwargs
    }

    response = requests.post(url, json=json_payload)
    if response.status_code == 200:
        return f"Server says: OK"
    else:
        return "Failed to reach server."

if __name__ == "__main__":
    result = schedule_one_shot_event(
        30, 43, 0, 4, 2, 2026, "hello", {"name": "Ahmed"}
    )

    print(result)
