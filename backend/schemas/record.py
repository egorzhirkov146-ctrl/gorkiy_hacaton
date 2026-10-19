from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    task = "task"
    meeting = "meeting"
    reminder = "reminder"


class RecordStatus(str, Enum):
    pending = "pending"
    done = "done"
    cancelled = "cancelled"


class RecordCreate(BaseModel):
    user_id: int = 1
    type: RecordType
    title: str = Field(..., min_length=1, max_length=500)
    raw_text: Optional[str] = None
    datetime: Optional[datetime] = None


class RecordUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    datetime: Optional[datetime] = None
    status: Optional[RecordStatus] = None


class RecordOut(BaseModel):
    id: int
    user_id: int
    type: RecordType
    title: str
    raw_text: Optional[str] = None
    datetime: Optional[datetime] = None
    created_at: datetime
    status: RecordStatus

    model_config = {"from_attributes": True}


class RecordList(BaseModel):
    items: list[RecordOut]
    count: int
