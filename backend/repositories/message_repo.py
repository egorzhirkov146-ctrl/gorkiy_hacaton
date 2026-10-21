from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from backend.models.message import Message


class MessageRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, session_id: str, role: str, content: str) -> Message:
        msg = Message(session_id=session_id, role=role, content=content)
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_history(self, session_id: str, limit: int = 10) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        msgs = list(self.db.scalars(stmt).all())
        msgs.reverse()
        return msgs

    def clear(self, session_id: str) -> int:
        stmt = delete(Message).where(Message.session_id == session_id)
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount or 0
