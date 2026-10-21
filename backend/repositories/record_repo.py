from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.schemas.record import RecordCreate, RecordUpdate, RecordType, RecordStatus


class RecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, rec: RecordCreate) -> Record:
        db_rec = Record(
            user_id=rec.user_id,
            type=rec.type,
            title=rec.title,
            raw_text=rec.raw_text,
            datetime=rec.datetime,
            status=RecordStatus.pending,
        )
        self.db.add(db_rec)
        self.db.commit()
        self.db.refresh(db_rec)
        return db_rec

    def get(self, record_id: int) -> Optional[Record]:
        return self.db.get(Record, record_id)

    def list(
        self,
        user_id: int = 1,
        from_: Optional[datetime] = None,
        to: Optional[datetime] = None,
        record_type: Optional[RecordType] = None,
        status: Optional[RecordStatus] = None,
        limit: int = 100,
    ) -> list[Record]:
        stmt = select(Record).where(Record.user_id == user_id)

        if record_type:
            stmt = stmt.where(Record.type == record_type)
        if status:
            stmt = stmt.where(Record.status == status)
        if from_:
            stmt = stmt.where(Record.datetime >= from_)
        if to:
            stmt = stmt.where(Record.datetime <= to)

        stmt = stmt.order_by(Record.datetime.asc().nulls_last(), Record.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def update(self, record_id: int, update_data: RecordUpdate) -> Optional[Record]:
        rec = self.get(record_id)
        if not rec:
            return None

        if update_data.title is not None:
            rec.title = update_data.title
        if update_data.datetime is not None:
            rec.datetime = update_data.datetime
        if update_data.status is not None:
            rec.status = update_data.status

        self.db.commit()
        self.db.refresh(rec)
        return rec

    def delete(self, record_id: int) -> bool:
        rec = self.get(record_id)
        if not rec:
            return False
        self.db.delete(rec)
        self.db.commit()
        return True

    def find_conflicts(
        self,
        dt: datetime,
        window_minutes: int = 30,
        user_id: int = 1,
        exclude_id: Optional[int] = None,
    ) -> list[Record]:
        start_w = dt - timedelta(minutes=window_minutes)
        end_w = dt + timedelta(minutes=window_minutes)

        stmt = select(Record).where(
            and_(
                Record.user_id == user_id,
                Record.type == RecordType.meeting,
                Record.status != RecordStatus.cancelled,
                Record.datetime.is_not(None),
                Record.datetime >= start_w,
                Record.datetime <= end_w,
            )
        )
        if exclude_id:
            stmt = stmt.where(Record.id != exclude_id)

        return list(self.db.scalars(stmt).all())
