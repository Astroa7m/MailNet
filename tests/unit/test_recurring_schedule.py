"""Recurring-email schedule validation (security review F3).

An under-specified cron (no field coarser than minute/second) fires every
second forever. validate_recurring_cron refuses those before they reach the
scheduler, and allows normal daily/weekly/monthly schedules.
"""
from app.extra_tools import validate_recurring_cron as v


def test_empty_schedule_refused():
    ok, reason = v({}, "UTC")
    assert not ok
    assert "every minute" in reason.lower()


def test_minute_only_refused():
    # minute=30 with no hour means "every hour at :30": no coarse field set.
    ok, _ = v({"minute": 30}, "UTC")
    assert not ok


def test_second_only_refused():
    ok, _ = v({"second": 5}, "UTC")
    assert not ok


def test_daily_allowed():
    ok, reason = v({"hour": 9}, "UTC")
    assert ok and reason == ""


def test_daily_with_minute_allowed():
    ok, _ = v({"hour": 9, "minute": 30}, "UTC")
    assert ok


def test_weekly_allowed_in_user_timezone():
    ok, _ = v({"day_of_week": "mon", "hour": 9}, "Asia/Muscat")
    assert ok


def test_monthly_allowed():
    ok, _ = v({"day": 1, "hour": 8}, "UTC")
    assert ok


def test_garbage_timezone_is_rejected_not_crashed():
    ok, reason = v({"hour": 9}, "Not/AZone")
    assert not ok and "schedule" in reason.lower()
