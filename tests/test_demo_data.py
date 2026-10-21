"""Демо-набор: покрытие сценариев задания и повторяемость загрузки."""
from datetime import timedelta

from sqlalchemy import func, select

from backend.models.record import Record
from backend.schemas.record import RecordType
from backend.storage import check_integrity
from backend.storage.demo_data import build_records, load_demo_data


def test_reload_does_not_duplicate(session, now):
    first = load_demo_data(session, now=now)
    second = load_demo_data(session, now=now)
    assert first == second
    assert session.scalar(select(func.count()).select_from(Record)) == first


def test_demo_covers_task_scenarios(demo_session, repo, now):
    today = now.replace(hour=0, minute=0)
    today_items = repo.list_by_period(today, today + timedelta(hours=23, minutes=59))
    assert len(today_items) >= 4, "ответ на 'Что у меня сегодня?' не должен быть пустым"
    assert any(r.type == RecordType.meeting for r in today_items)

    tomorrow = today + timedelta(days=1)
    tomorrow_titles = {r.title for r in repo.list_by_period(tomorrow, tomorrow + timedelta(hours=23, minutes=59))}
    assert {"Позвонить Ивану", "Встреча с командой"} <= tomorrow_titles

    week = repo.list_by_period(today, today + timedelta(days=7))
    assert {"Отправить отчет", "Встреча с дизайнером", "Купить билеты"} <= {r.title for r in week}


def test_demo_dates_are_consistent(now):
    for rec in build_records(now):
        assert rec.created_at <= now
        if rec.datetime is not None:
            assert rec.created_at <= rec.datetime


def test_demo_passes_integrity_check(engine, demo_session):
    assert check_integrity(engine).ok
