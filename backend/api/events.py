from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.schemas.record import (
    RecordList,
    RecordType,
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
    db: Session = Depends(get_db),
) -> RecordOut:
    service = TaskService(db)
    rec = service.get(event_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Event not found")
    return RecordOut.model_validate(rec)


@router.patch("/events/{event_id}", response_model=RecordOut)
def update_event(
    event_id: int,
    data: RecordUpdate,
    db: Session = Depends(get_db),
) -> RecordOut:
    service = TaskService(db)
    rec = service.update(event_id, data)
    if not rec:
        raise HTTPException(status_code=404, detail="Event not found")
    return RecordOut.model_validate(rec)


@router.delete("/events/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
) -> dict:
    service = TaskService(db)
    if not service.delete(event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "ok", "deleted_id": event_id}
