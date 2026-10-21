import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base
from backend.models.record import Record
from backend.models.message import Message
from backend.repositories.record_repo import RecordRepository
from backend.repositories.message_repo import MessageRepository
from backend.schemas.record import RecordCreate, RecordUpdate, RecordType, RecordStatus


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_record_repo_create_and_get(db_session):
    repo = RecordRepository(db_session)
    rec = repo.create(
        RecordCreate(
            type=RecordType.task,
            title="Отправить отчет",
            raw_text="В пятницу отправить отчет",
            datetime=datetime(2026, 10, 23, 18, 0),
        )
    )
    assert rec.id is not None
    assert rec.title == "Отправить отчет"
    assert rec.status == RecordStatus.pending

    fetched = repo.get(rec.id)
    assert fetched is not None
    assert fetched.title == "Отправить отчет"


def test_record_repo_list_filters(db_session):
    repo = RecordRepository(db_session)
    now = datetime(2026, 10, 20, 12, 0)
    repo.create(RecordCreate(type=RecordType.task, title="Задача 1", datetime=now))
    repo.create(RecordCreate(type=RecordType.meeting, title="Встреча 1", datetime=now + timedelta(hours=2)))
    repo.create(RecordCreate(type=RecordType.reminder, title="Напоминание 1", datetime=now + timedelta(days=1)))

    tasks = repo.list(record_type=RecordType.task)
    assert len(tasks) == 1
    assert tasks[0].title == "Задача 1"

    meetings = repo.list(record_type=RecordType.meeting)
    assert len(meetings) == 1
    assert meetings[0].title == "Встреча 1"

    period_items = repo.list(from_=now - timedelta(hours=1), to=now + timedelta(hours=3))
    assert len(period_items) == 2


def test_record_repo_update_and_delete(db_session):
    repo = RecordRepository(db_session)
    rec = repo.create(RecordCreate(type=RecordType.task, title="Купить молоко"))
    
    updated = repo.update(rec.id, RecordUpdate(title="Купить хлеб и молоко", status=RecordStatus.done))
    assert updated.title == "Купить хлеб и молоко"
    assert updated.status == RecordStatus.done

    assert repo.delete(rec.id) is True
    assert repo.get(rec.id) is None


def test_record_repo_find_conflicts(db_session):
    repo = RecordRepository(db_session)
    meeting_time = datetime(2026, 10, 21, 15, 0)
    repo.create(RecordCreate(type=RecordType.meeting, title="Встреча с командой", datetime=meeting_time))

    conflicts = repo.find_conflicts(datetime(2026, 10, 21, 15, 15), window_minutes=30)
    assert len(conflicts) == 1
    assert conflicts[0].title == "Встреча с командой"

    # Разница более 30 минут — конфликта нет
    no_conflicts = repo.find_conflicts(datetime(2026, 10, 21, 16, 0), window_minutes=30)
    assert len(no_conflicts) == 0


def test_message_repo(db_session):
    msg_repo = MessageRepository(db_session)
    msg_repo.add("sess_1", "user", "Привет")
    msg_repo.add("sess_1", "assistant", "Здравствуйте! Чем помочь?")
    msg_repo.add("sess_2", "user", "Другая сессия")

    history = msg_repo.get_history("sess_1")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"

    cleared = msg_repo.clear("sess_1")
    assert cleared == 2
    assert len(msg_repo.get_history("sess_1")) == 0


def test_message_repo_limit_chronological(db_session):
    msg_repo = MessageRepository(db_session)
    for i in range(1, 16):
        msg_repo.add("sess_limit", "user", f"msg_{i}")

    # Запрашиваем лимит 5 — должны вернуться последние сообщения 11..15 в хронологическом порядке
    recent = msg_repo.get_history("sess_limit", limit=5)
    assert len(recent) == 5
    contents = [m.content for m in recent]
    assert contents == ["msg_11", "msg_12", "msg_13", "msg_14", "msg_15"]

