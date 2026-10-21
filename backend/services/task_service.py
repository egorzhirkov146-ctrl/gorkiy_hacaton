from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.schemas.record import (
    RecordCreate,
    RecordUpdate,
    RecordType,
    RecordStatus,
    RecordOut,
    RecordList,
)
from backend.repositories.record_repo import RecordRepository
from backend.repositories.search_repo import SearchRepository


class TaskService:
    def __init__(self, db: Session):
        self.db = db
        self.record_repo = RecordRepository(db)
        self.search_repo = SearchRepository(db)

    def create(self, rec: RecordCreate) -> tuple[Record, Optional[str]]:
        warning: Optional[str] = None
        if rec.type == RecordType.meeting and rec.datetime:
            conflicts = self.record_repo.find_conflicts(rec.datetime, window_minutes=45, user_id=rec.user_id)
            if conflicts:
                first = conflicts[0]
                conf_time = first.datetime.strftime("%H:%M") if first.datetime else "указанное время"
                warning = f"Внимание: время пересекается с событием '{first.title}' в {conf_time}."

        created = self.record_repo.create(rec)
        return created, warning

    def get(self, record_id: int) -> Optional[Record]:
        return self.record_repo.get(record_id)

    def list(
        self,
        from_: Optional[datetime] = None,
        to: Optional[datetime] = None,
        record_type: Optional[RecordType] = None,
        status: Optional[RecordStatus] = None,
        limit: int = 100,
        user_id: int = 1,
    ) -> RecordList:
        records = self.record_repo.list(
            user_id=user_id,
            from_=from_,
            to=to,
            record_type=record_type,
            status=status,
            limit=limit,
        )
        items = [RecordOut.model_validate(r) for r in records]
        return RecordList(items=items, count=len(items))

    def search(
        self,
        query: str,
        user_id: int = 1,
        record_type: Optional[RecordType] = None,
        limit: int = 10,
    ) -> RecordList:
        records = self.search_repo.search(
            query=query,
            user_id=user_id,
            record_type=record_type,
            limit=limit,
        )
        items = [RecordOut.model_validate(r) for r in records]
        return RecordList(items=items, count=len(items))

    def update(self, record_id: int, update_data: RecordUpdate) -> Optional[Record]:
        return self.record_repo.update(record_id, update_data)

    def delete(self, record_id: int) -> bool:
        return self.record_repo.delete(record_id)

    def find_target_record(
        self,
        target_query: str,
        record_type: Optional[RecordType] = None,
        user_id: int = 1,
    ) -> Optional[Record]:
        clean_target = target_query.lower().strip()
        if clean_target in ("её", "ее", "это", "эту", "последнюю", "встреча", "встречу", "задача", "задачу", "запись"):
            from sqlalchemy import select
            stmt = select(Record).where(Record.user_id == user_id)
            if record_type:
                stmt = stmt.where(Record.type == record_type)
            elif "встреч" in clean_target:
                stmt = stmt.where(Record.type == RecordType.meeting)
            elif "задач" in clean_target:
                stmt = stmt.where(Record.type == RecordType.task)
            stmt = stmt.order_by(Record.created_at.desc(), Record.id.desc()).limit(1)
            return self.db.scalars(stmt).first()

        results = self.search_repo.search(target_query, user_id=user_id, record_type=record_type, limit=1)
        return results[0] if results else None

    def find_and_update(
        self,
        target_query: str,
        new_datetime: Optional[datetime] = None,
        new_title: Optional[str] = None,
        new_status: Optional[RecordStatus] = None,
        has_explicit_time: bool = False,
        has_explicit_date: bool = True,
        user_id: int = 1,
    ) -> tuple[Optional[Record], Optional[str]]:
        rec = self.find_target_record(target_query, user_id=user_id)
        if not rec:
            return None, None

        final_dt = new_datetime
        if new_datetime and rec.datetime:
            if not has_explicit_time:
                # Пользователь указал только новую дату ("перенеси на пятницу") - сохраняем время исходного события
                final_dt = datetime.combine(new_datetime.date(), rec.datetime.time())
            elif not has_explicit_date:
                # Пользователь указал только новое время ("перенеси на 16:00") - сохраняем дату исходного события
                final_dt = datetime.combine(rec.datetime.date(), new_datetime.time())


        warning: Optional[str] = None
        if final_dt and rec.type == RecordType.meeting:
            conflicts = self.record_repo.find_conflicts(
                final_dt, window_minutes=45, user_id=user_id, exclude_id=rec.id
            )
            if conflicts:
                first = conflicts[0]
                conf_time = first.datetime.strftime("%H:%M") if first.datetime else "указанное время"
                warning = f"Внимание: время пересекается с событием '{first.title}' в {conf_time}."

        upd = RecordUpdate(
            title=new_title,
            datetime=final_dt,
            status=new_status,
        )
        updated = self.record_repo.update(rec.id, upd)
        return updated, warning

    def find_and_complete(self, target_query: str, user_id: int = 1) -> Optional[Record]:
        rec, _ = self.find_and_update(target_query, new_status=RecordStatus.done, user_id=user_id)
        return rec

    def find_and_delete(self, target_query: str, user_id: int = 1) -> Optional[Record]:
        rec = self.find_target_record(target_query, user_id=user_id)
        if not rec:
            return None
        self.record_repo.delete(rec.id)
        return rec
