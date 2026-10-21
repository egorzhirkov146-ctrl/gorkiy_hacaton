"""Репозиторий записей: создание, чтение, выборка за период, изменение, удаление."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.record import Record
from backend.schemas.record import RecordCreate, RecordOut, RecordStatus, RecordType, RecordUpdate


def make(repo, title, when=None, type_=RecordType.task, user_id=1, raw_text=None):
    return repo.create(RecordCreate(type=type_, title=title, datetime=when, user_id=user_id, raw_text=raw_text))


def test_create_fills_defaults(repo):
    rec = make(repo, "  Отправить отчет  ", datetime(2026, 10, 23, 18, 0), raw_text="В пятницу нужно отправить отчет")
    assert rec.id is not None
    assert rec.title == "Отправить отчет"
    assert rec.status == RecordStatus.pending
    assert rec.user_id == 1
    assert rec.created_at is not None
    assert rec.recurrence is None


def test_create_output_matches_api_schema(repo):
    rec = make(repo, "Позвонить Ивану", datetime(2026, 10, 22, 10, 0), RecordType.reminder)
    out = RecordOut.model_validate(rec)
    assert out.type == RecordType.reminder
    assert out.datetime == datetime(2026, 10, 22, 10, 0)


def test_get_by_id_and_user_isolation(repo):
    rec = make(repo, "Задача пользователя 2", user_id=2)
    assert repo.get_by_id(rec.id).title == "Задача пользователя 2"
    assert repo.get_by_id(rec.id, user_id=2) is not None
    assert repo.get_by_id(rec.id, user_id=1) is None
    assert repo.get_by_id(999_999) is None


def test_list_by_period_includes_both_bounds(repo):
    day = datetime(2026, 10, 22)
    make(repo, "Ровно в начале", day)
    make(repo, "Внутри", day + timedelta(hours=15))
    make(repo, "Ровно в конце", day + timedelta(hours=23, minutes=59))
    make(repo, "Следующий день", day + timedelta(days=1))
    make(repo, "Без даты")
    titles = [r.title for r in repo.list_by_period(day, day + timedelta(hours=23, minutes=59))]
    assert titles == ["Ровно в начале", "Внутри", "Ровно в конце"]


def test_list_by_period_filters_type_status_and_user(repo):
    day = datetime(2026, 10, 22, 9, 0)
    make(repo, "Встреча", day, RecordType.meeting)
    done = make(repo, "Задача", day + timedelta(hours=1))
    repo.update_status(done.id, RecordStatus.done)
    make(repo, "Чужая встреча", day, RecordType.meeting, user_id=2)
    period = (day - timedelta(hours=1), day + timedelta(hours=5))

    meetings = repo.list_by_period(*period, record_type=RecordType.meeting)
    assert [r.title for r in meetings] == ["Встреча"]
    assert [r.title for r in repo.list_by_period(*period, status=RecordStatus.done)] == ["Задача"]
    assert [r.title for r in repo.list_by_period(*period, user_id=2)] == ["Чужая встреча"]


def test_list_by_period_rejects_reversed_period(repo):
    with pytest.raises(ValueError):
        repo.list_by_period(datetime(2026, 10, 23), datetime(2026, 10, 22))


def test_list_without_period_keeps_undated_last(repo):
    make(repo, "Без даты")
    make(repo, "С датой", datetime(2026, 10, 22, 9, 0))
    assert [r.title for r in repo.list()] == ["С датой", "Без даты"]
    assert [r.title for r in repo.list_undated()] == ["Без даты"]


def test_list_respects_limit(repo):
    for i in range(5):
        make(repo, f"Задача {i}", datetime(2026, 10, 22, 9 + i))
    assert len(repo.list(limit=3)) == 3
    assert len(repo.list_by_period(datetime(2026, 10, 22), datetime(2026, 10, 23), limit=2)) == 2


def test_update_changes_only_given_fields(repo):
    rec = make(repo, "Встреча с командой", datetime(2026, 10, 22, 15, 0), RecordType.meeting)
    updated = repo.update(rec.id, RecordUpdate(datetime=datetime(2026, 10, 23, 15, 0)))
    assert updated.title == "Встреча с командой"
    assert updated.datetime == datetime(2026, 10, 23, 15, 0)
    assert repo.update(999_999, RecordUpdate(title="нет")) is None


def test_update_status(repo):
    rec = make(repo, "Купить билеты")
    assert repo.update_status(rec.id, RecordStatus.done).status == RecordStatus.done
    assert repo.update_status(rec.id, RecordStatus.cancelled).status == RecordStatus.cancelled
    assert repo.update_status(999_999, RecordStatus.done) is None


def test_delete(repo):
    rec = make(repo, "Временная задача")
    assert repo.delete(rec.id) is True
    assert repo.get(rec.id) is None
    assert repo.delete(rec.id) is False


def test_latest_returns_last_created(repo):
    make(repo, "Первая встреча", datetime(2026, 10, 22, 9, 0), RecordType.meeting)
    last_meeting = make(repo, "Вторая встреча", datetime(2026, 10, 20, 9, 0), RecordType.meeting)
    make(repo, "Задача")
    assert repo.latest(record_type=RecordType.meeting).id == last_meeting.id
    assert repo.latest().title == "Задача"


def test_find_conflicts_ignores_cancelled_and_other_types(repo):
    at = datetime(2026, 10, 22, 15, 0)
    meeting = make(repo, "Встреча с командой", at, RecordType.meeting)
    make(repo, "Задача в то же время", at, RecordType.task)
    cancelled = make(repo, "Отмененная встреча", at, RecordType.meeting)
    repo.update_status(cancelled.id, RecordStatus.cancelled)

    conflicts = repo.find_conflicts(at + timedelta(minutes=15), window_minutes=30)
    assert [r.id for r in conflicts] == [meeting.id]
    assert repo.find_conflicts(at + timedelta(minutes=31), window_minutes=30) == []
    assert repo.find_conflicts(at, window_minutes=30, exclude_id=meeting.id) == []


def test_database_rejects_invalid_values(session):
    # Ограничения CHECK работают даже для кода, который пишет в базу мимо репозитория.
    session.add(Record(type=RecordType.task, title="   "))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(Record(type=RecordType.task, title="Повтор без даты", recurrence="daily"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_create_many_is_one_transaction(repo):
    items = [RecordCreate(type=RecordType.task, title=f"Импорт {i}") for i in range(50)]
    rows = repo.create_many(items)
    assert len(rows) == 50 and all(r.id for r in rows)
