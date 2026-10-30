from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.schemas.record import (
    RecordList,
    RecordType,
    RecordStatus,
    RecordCreate,
    RecordOut,
    RecordUpdate,
)
from backend.services.task_service import TaskService

router = APIRouter(tags=["events"])


@router.get("/events", response_model=RecordList)
def list_events(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    type: Optional[RecordType] = None,
    user_id: int = Query(1),
    db: Session = Depends(get_db),
) -> RecordList:
    service = TaskService(db)
    return service.list(from_=from_, to=to, record_type=type, user_id=user_id)


@router.get("/events/search", response_model=RecordList)
def search_events(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
    type: Optional[RecordType] = None,
    user_id: int = Query(1),
    db: Session = Depends(get_db),
) -> RecordList:
    service = TaskService(db)
    return service.search(query=q, record_type=type, limit=limit, user_id=user_id)


@router.post("/events", response_model=RecordOut, status_code=status.HTTP_201_CREATED)
def create_event(
    rec: RecordCreate,
    db: Session = Depends(get_db),
) -> RecordOut:
    service = TaskService(db)
    created, _ = service.create(rec)
    return RecordOut.model_validate(created)


@router.get("/events/{event_id}", response_model=RecordOut)
def get_event(
    event_id: int,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> RecordOut:
    service = TaskService(db)
    rec = service.get(event_id)
    if not rec or (user_id is not None and rec.user_id != user_id):
        raise HTTPException(status_code=404, detail="Event not found")
    return RecordOut.model_validate(rec)


@router.patch("/events/{event_id}", response_model=RecordOut)
def update_event(
    event_id: int,
    data: RecordUpdate,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> RecordOut:
    service = TaskService(db)
    rec = service.get(event_id)
    if not rec or (user_id is not None and rec.user_id != user_id):
        raise HTTPException(status_code=404, detail="Event not found")
    updated = service.update(event_id, data)
    return RecordOut.model_validate(updated)


@router.delete("/events/{event_id}")
def delete_event(
    event_id: int,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    service = TaskService(db)
    rec = service.get(event_id)
    if not rec or (user_id is not None and rec.user_id != user_id):
        raise HTTPException(status_code=404, detail="Event not found")
    service.delete(event_id)
    return {"status": "ok", "deleted_id": event_id}


@router.post("/events/seed", response_model=RecordList)
def seed_user_events(
    user_id: int = Query(1),
    db: Session = Depends(get_db),
) -> RecordList:
    """Инициализирует демонстрационные задачи и встречи для конкретного user_id."""
    from backend.models.record import Record
    from datetime import datetime, timedelta

    # Удаляем только записи данного пользователя
    db.query(Record).filter(Record.user_id == user_id).delete()
    db.commit()

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    tomorrow = now + timedelta(days=1)
    thursday = now + timedelta(days=(3 - now.weekday()) % 7 or 7)
    friday = now + timedelta(days=(4 - now.weekday()) % 7 or 7)
    sunday = now + timedelta(days=6 - now.weekday())

    demo_records = [
        Record(
            user_id=user_id,
            type=RecordType.reminder,
            title="Позвонить Ивану",
            raw_text="Напомни мне завтра в 10 утра позвонить Ивану",
            datetime=tomorrow.replace(hour=10, minute=0),
            status=RecordStatus.pending,
        ),
        Record(
            user_id=user_id,
            type=RecordType.task,
            title="Отправить отчет",
            raw_text="В пятницу нужно отправить отчет",
            datetime=friday.replace(hour=18, minute=0),
            status=RecordStatus.pending,
        ),
        Record(
            user_id=user_id,
            type=RecordType.task,
            title="Купить билеты до конца недели",
            raw_text="Поставь задачу купить билеты до конца недели",
            datetime=sunday.replace(hour=23, minute=59, second=59),
            status=RecordStatus.pending,
        ),
        Record(
            user_id=user_id,
            type=RecordType.meeting,
            title="Встреча с командой",
            raw_text="Добавь встречу с командой завтра в 15:00",
            datetime=tomorrow.replace(hour=15, minute=0),
            status=RecordStatus.pending,
        ),
        Record(
            user_id=user_id,
            type=RecordType.meeting,
            title="Встреча с дизайнером",
            raw_text="В четверг в 11 у меня встреча с дизайнером",
            datetime=thursday.replace(hour=11, minute=0),
            status=RecordStatus.pending,
        ),
        Record(
            user_id=user_id,
            type=RecordType.task,
            title="Подготовить презентацию для инвесторов",
            raw_text="Подготовить презентацию по проекту",
            datetime=now - timedelta(days=3),
            status=RecordStatus.done,
        ),
        Record(
            user_id=user_id,
            type=RecordType.task,
            title="Согласовать договор с контрагентом",
            raw_text="Поставить задачу по договору",
            datetime=now - timedelta(days=7),
            status=RecordStatus.done,
        ),
        Record(
            user_id=user_id,
            type=RecordType.meeting,
            title="Встреча с Иваном по партнерству",
            raw_text="Встреча с Иваном в кафе",
            datetime=now - timedelta(days=5),
            status=RecordStatus.done,
        ),
    ]
    for r in demo_records:
        db.add(r)
    db.commit()

    service = TaskService(db)
    return service.list(user_id=user_id)


@router.delete("/events/clear/{user_id}")
def clear_user_events(
    user_id: int,
    db: Session = Depends(get_db),
) -> dict:
    from backend.models.record import Record
    deleted = db.query(Record).filter(Record.user_id == user_id).delete()
    db.commit()
    return {"status": "ok", "deleted_count": deleted, "user_id": user_id}
