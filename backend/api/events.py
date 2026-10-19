from datetime import datetime
from typing import Optional

from fastapi import APIRouter

from backend.schemas.record import RecordList, RecordType

router = APIRouter(tags=["events"])


@router.get("/events", response_model=RecordList)
def list_events(
    from_: Optional[datetime] = None,
    to: Optional[datetime] = None,
    type: Optional[RecordType] = None,
) -> RecordList:
    # TODO(A + E): list_events через task_service
    return RecordList(items=[], count=0)


@router.get("/events/search", response_model=RecordList)
def search_events(q: str, limit: int = 10) -> RecordList:
    # TODO(A + E): search_events через task_service
    return RecordList(items=[], count=0)
