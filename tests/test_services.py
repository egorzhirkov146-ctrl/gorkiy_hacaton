import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base
from backend.services.task_service import TaskService
from backend.services.voice_service import VoiceService
from backend.schemas.record import RecordCreate, RecordType, RecordStatus


@pytest.fixture
def task_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    service = TaskService(session)
    yield service
    session.close()


def test_task_service_meeting_conflict(task_service):
    dt_meeting = datetime(2026, 10, 21, 15, 0)
    rec1, warn1 = task_service.create(
        RecordCreate(type=RecordType.meeting, title="Встреча с командой", datetime=dt_meeting)
    )
    assert warn1 is None

    # Конфликтующая встреча на 15:15 (в пределах 45 минут)
    rec2, warn2 = task_service.create(
        RecordCreate(type=RecordType.meeting, title="Встреча с клиентом", datetime=dt_meeting + timedelta(minutes=15))
    )
    assert warn2 is not None
    assert "пересекается" in warn2.lower()
    assert "Встреча с командой" in warn2


def test_task_service_list_and_search(task_service):
    now = datetime(2026, 10, 20, 10, 0)
    task_service.create(RecordCreate(type=RecordType.task, title="Отправить отчет", datetime=now))
    task_service.create(RecordCreate(type=RecordType.task, title="Купить билеты", datetime=now + timedelta(days=2)))

    res_list = task_service.list(from_=now - timedelta(hours=1), to=now + timedelta(hours=1))
    assert res_list.count == 1

    search_res = task_service.search("отчет")
    assert search_res.count >= 1
    assert "отчет" in search_res.items[0].title.lower()


def test_task_service_complete_and_delete(task_service):
    rec, _ = task_service.create(RecordCreate(type=RecordType.task, title="Подготовить презентацию"))
    assert rec.status == RecordStatus.pending

    completed = task_service.find_and_complete("презентацию")
    assert completed is not None
    assert completed.status == RecordStatus.done

    deleted = task_service.find_and_delete("презентацию")
    assert deleted is not None
    assert task_service.get(rec.id) is None


@pytest.mark.asyncio
async def test_voice_service_mock_transcribe():
    service = VoiceService()
    # Эмуляция аудиофайла байтами
    fake_audio = b"RIFF....WAVEfmt ...." + b"\x00" * 400
    res = await service.transcribe(fake_audio, filename="test.wav")
    assert "text" in res
    assert len(res["text"]) > 0


def test_task_service_reschedule_preserves_time(task_service):
    dt_meeting = datetime(2026, 10, 22, 11, 0)
    rec, _ = task_service.create(
        RecordCreate(type=RecordType.meeting, title="Встреча с дизайнером", datetime=dt_meeting)
    )

    # Перенос на завтра без указания времени должен сохранить 11:00
    tomorrow_midnight = datetime(2026, 10, 21, 0, 0)
    updated, warn = task_service.find_and_update(
        "её",
        new_datetime=tomorrow_midnight,
        has_explicit_time=False,
    )
    assert updated is not None
    assert updated.datetime == datetime(2026, 10, 21, 11, 0)

    # Перенос на 16:00 (указано только время) должен сохранить дату 21.10
    updated2, warn2 = task_service.find_and_update(
        "её",
        new_datetime=datetime(2026, 10, 20, 16, 0),
        has_explicit_time=True,
        has_explicit_date=False,
    )
    assert updated2 is not None
    assert updated2.datetime == datetime(2026, 10, 21, 16, 0)



def test_task_service_reschedule_conflict(task_service):
    dt1 = datetime(2026, 10, 21, 15, 0)
    dt2 = datetime(2026, 10, 22, 11, 0)
    task_service.create(RecordCreate(type=RecordType.meeting, title="Встреча с командой", datetime=dt1))
    rec2, _ = task_service.create(RecordCreate(type=RecordType.meeting, title="Встреча с дизайнером", datetime=dt2))

    # Переносим rec2 на 15:10 21 октября (конфликт с 15:00)
    updated, warn = task_service.find_and_update(
        "дизайнером",
        new_datetime=datetime(2026, 10, 21, 15, 10),
        has_explicit_time=True,
    )
    assert updated is not None
    assert warn is not None
    assert "пересекается" in warn.lower()


def test_task_service_pronoun_resolution_latest_created(task_service):
    # Создаем первую встречу с ранней датой
    rec1, _ = task_service.create(
        RecordCreate(type=RecordType.meeting, title="Старая встреча", datetime=datetime(2026, 10, 21, 10, 0))
    )
    # Создаем вторую встречу с поздней датой
    rec2, _ = task_service.create(
        RecordCreate(type=RecordType.meeting, title="Свежая встреча", datetime=datetime(2026, 10, 25, 12, 0))
    )

    # Резолвинг местоимения "её" должен выбрать последнюю созданную запись rec2
    target = task_service.find_target_record("её", record_type=RecordType.meeting)
    assert target is not None
    assert target.id == rec2.id

