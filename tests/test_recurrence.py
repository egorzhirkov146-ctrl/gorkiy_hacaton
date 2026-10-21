"""Повторяющиеся задачи и встречи (бонус S3)."""
from datetime import datetime, timedelta

import pytest

from backend.schemas.record import RecordCreate, RecordStatus, RecordType
from backend.storage.recurrence import next_occurrence, occurrences

WED = datetime(2026, 10, 21, 10, 0)  # среда


def dates(rule, start, frm, to, until=None):
    return list(occurrences(start, rule, frm, to, until))


def test_daily_and_weekly():
    assert dates("daily", WED, WED, WED + timedelta(days=2)) == [WED + timedelta(days=i) for i in range(3)]
    assert dates("weekly", WED, WED + timedelta(days=1), WED + timedelta(days=21)) == [
        WED + timedelta(weeks=1),
        WED + timedelta(weeks=2),
        WED + timedelta(weeks=3),
    ]


def test_weekdays_skip_weekend():
    result = dates("weekdays", WED, WED, WED + timedelta(days=6, hours=23))
    assert [d.strftime("%a") for d in result] == ["Wed", "Thu", "Fri", "Mon", "Tue"]


def test_monthly_clamps_to_month_end():
    start = datetime(2026, 1, 31, 9, 0)
    result = dates("monthly", start, start, datetime(2026, 4, 30, 23, 0))
    assert [d.date().isoformat() for d in result] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


def test_until_and_window_before_start():
    assert dates("daily", WED, WED, WED + timedelta(days=10), until=WED + timedelta(days=1)) == [
        WED,
        WED + timedelta(days=1),
    ]
    assert dates("daily", WED, WED - timedelta(days=5), WED - timedelta(days=1)) == []


def test_next_occurrence():
    assert next_occurrence(WED, "weekly", WED + timedelta(minutes=1)) == WED + timedelta(weeks=1)
    assert next_occurrence(WED, "daily", WED + timedelta(days=3), until=WED + timedelta(days=2)) is None


def test_repository_expands_series_in_period(repo):
    repo.create(RecordCreate(type=RecordType.meeting, title="Стендап", datetime=WED), recurrence="weekdays")
    repo.create(RecordCreate(type=RecordType.task, title="Разовая задача", datetime=WED + timedelta(days=1, hours=2)))

    week = repo.list_by_period(WED.replace(hour=0), WED.replace(hour=0) + timedelta(days=7))
    standups = [r for r in week if r.title == "Стендап"]
    assert len(standups) == 5
    assert all(getattr(r, "is_occurrence", False) for r in standups)
    assert len({r.id for r in standups}) == 1  # все повторы ссылаются на одну серию
    assert [r.datetime for r in week] == sorted(r.datetime for r in week)


def test_upcoming_gives_one_next_occurrence(repo):
    repo.create(RecordCreate(type=RecordType.reminder, title="Аренда", datetime=WED), recurrence="monthly")
    upcoming = repo.list(from_=WED + timedelta(days=1))
    assert [(r.title, r.datetime) for r in upcoming] == [("Аренда", datetime(2026, 11, 21, 10, 0))]


def test_recurring_meeting_conflicts(repo):
    repo.create(RecordCreate(type=RecordType.meeting, title="Планерка", datetime=WED), recurrence="weekly")
    conflicts = repo.find_conflicts(WED + timedelta(weeks=3, minutes=20), window_minutes=30)
    assert [r.title for r in conflicts] == ["Планерка"]
    assert conflicts[0].datetime == WED + timedelta(weeks=3)


def test_series_status_and_stop(repo):
    rec = repo.create(RecordCreate(type=RecordType.meeting, title="Йога", datetime=WED), recurrence="daily")
    repo.update_status(rec.id, RecordStatus.cancelled)
    period = (WED, WED + timedelta(days=3))
    assert repo.list_by_period(*period, status=RecordStatus.pending) == []

    repo.set_recurrence(rec.id, None)
    assert [r.datetime for r in repo.list_by_period(*period)] == [WED]


@pytest.mark.parametrize(
    "rule, start, until",
    [("hourly", WED, None), ("daily", None, None), ("daily", WED, WED - timedelta(days=1))],
)
def test_invalid_recurrence(repo, rule, start, until):
    with pytest.raises(ValueError):
        repo.create(
            RecordCreate(type=RecordType.task, title="Ошибка", datetime=start),
            recurrence=rule,
            recurrence_until=until,
        )
