from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.schemas.record import RecordOut


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    user_id: int = 1
    session_id: str
    text: str = Field(..., min_length=1, max_length=2000)
    history: Optional[list[MessageIn]] = None


class ActionOut(BaseModel):
    type: str
    status: Literal["ok", "pending", "error"] = "ok"
    record: Optional[RecordOut] = None
    records: Optional[list[RecordOut]] = None


class ChatResponse(BaseModel):
    session_id: str
    reply_text: str
    action: ActionOut
    needs_clarification: bool = False
