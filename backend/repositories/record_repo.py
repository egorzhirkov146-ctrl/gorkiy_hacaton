from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.models.record import RECURRENCE_RULES, Record
from backend.schemas.record import RecordCreate, RecordStatus, RecordType, RecordUpdate
from backend.storage import recurrence as rec_rules


def make_occurrence(rec: Record, when: datetime) -> Record:
    """Создает несохраняемую копию повторяющейся записи с датой конкретного повтора.

    Копия имеет тот же id, что и серия, поэтому изменение или удаление по id
    затрагивает всю серию. Копию нельзя добавлять в сессию.
    """
    copy = Record(
        id=rec.id,
        user_id=rec.user_id,
        type=rec.type,
        title=rec.title,
        raw_text=rec.raw_text,
        datetime=when,
        created_at=rec.created_at,
        status=rec.status,
        recurrence=rec.recurrence,
        recurrence_until=rec.recurrence_until,
    )
    copy.is_occurrence = True
    copy.series_start = rec.datetime
    return copy


def _sort_key(rec: Record):
    # Записи без даты идут в конце, как NULLS LAST в SQL.
    return (rec.datetime is None, rec.datetime or datetime.min, -(rec.id or 0))


class RecordRepository:
    """CRUD для таблицы records.

    Каждый метод, который меняет данные, сам делает commit, поэтому сервисный
    слой получает уже сохраненную запись с id.
    """

    def __init__(self, db: Session):
        self.db = db

    # ---- создание ---------------------------------------------------------

    def create(
        self,
        rec: RecordCreate,
        recurrence: Optional[str] = None,
        recurrence_until: Optional[datetime] = None,
    ) -> Record:
        # Схема RecordCreate пока не знает о повторении, поэтому поле читается мягко.
        recurrence = recurrence or getattr(rec, "recurrence", None)
        recurrence_until = recurrence_until or getattr(rec, "recurrence_until", None)
        self._validate_recurrence(recurrence, rec.datetime, recurrence_until)
        db_rec = Record(
            user_id=rec.user_id,
            type=rec.type,
            title=rec.title.strip(),
            raw_text=rec.raw_text,
            datetime=rec.datetime,
            status=RecordStatus.pending,
            recurrence=recurrence,
            recurrence_until=recurrence_until,
        )
        self.db.add(db_rec)
        self.db.commit()
        self.db.refresh(db_rec)
        return db_rec

    def create_many(self, items: list[RecordCreate]) -> list[Record]:
        """Создает записи одной транзакцией, это быстрее для сидов и импорта."""
        rows = [
            Record(
                user_id=i.user_id,
                type=i.type,
                title=i.title.strip(),
                raw_text=i.raw_text,
                datetime=i.datetime,
                status=RecordStatus.pending,
            )
            for i in items
        ]
        self.db.add_all(rows)
        self.db.commit()
        return rows

    @staticmethod
    def _validate_recurrence(
        rule: Optional[str], start: Optional[datetime], until: Optional[datetime]
    ) -> None:
        if rule is None:
            return
        if rule not in RECURRENCE_RULES:
            raise ValueError(f"recurrence должен быть одним из {RECURRENCE_RULES}, получено {rule!r}")
        if start is None:
            raise ValueError("Повторяющейся записи нужна дата первого повтора")
        if until is not None and until < start:
            raise ValueError("recurrence_until раньше даты первого повтора")

    # ---- чтение -----------------------------------------------------------

    def get(self, record_id: int, user_id: Optional[int] = None) -> Optional[Record]:
        rec = self.db.get(Record, record_id)
        if rec is not None and user_id is not None and rec.user_id != user_id:
            return None
        return rec

    def get_by_id(self, record_id: int, user_id: Optional[int] = None) -> Optional[Record]:
        return self.get(record_id, user_id=user_id)

    def list(
        self,
        user_id: int = 1,
        from_: Optional[datetime] = None,
        to: Optional[datetime] = None,
        record_type: Optional[RecordType] = None,
        status: Optional[RecordStatus] = None,
        limit: int = 100,
        expand_recurring: bool = True,
    ) -> list[Record]:
        """Возвращает записи пользователя, отсортированные по дате.

        Если задан период, повторяющиеся записи разворачиваются в повторы,
        которые попадают в период. Если задана только нижняя граница
        ("предстоящие"), серия дает один ближайший повтор.
        """
        filters = [Record.user_id == user_id]
        if record_type:
            filters.append(Record.type == record_type)
        if status:
            filters.append(Record.status == status)

        expand = expand_recurring and from_ is not None
        stmt = select(Record).where(*filters)
        if expand:
            stmt = stmt.where(Record.recurrence.is_(None))
        if from_:
            stmt = stmt.where(Record.datetime >= from_)
        if to:
            stmt = stmt.where(Record.datetime <= to)
        stmt = stmt.order_by(Record.datetime.asc().nulls_last(), Record.created_at.desc()).limit(limit)
        result = list(self.db.scalars(stmt).all())

        if expand:
            result.extend(self._expand_series(filters, from_, to))
            result.sort(key=_sort_key)
            result = result[:limit]
        return result

    def list_by_period(
        self,
        start: datetime,
        end: datetime,
        user_id: int = 1,
        record_type: Optional[RecordType] = None,
        status: Optional[RecordStatus] = None,
        limit: int = 100,
    ) -> list[Record]:
        """Записи с датой в отрезке [start, end] включительно, вместе с повторами."""
        if end < start:
            raise ValueError("Конец периода раньше начала")
        return self.list(
            user_id=user_id, from_=start, to=end, record_type=record_type, status=status, limit=limit
        )

    def list_undated(self, user_id: int = 1, status: Optional[RecordStatus] = None) -> list[Record]:
        """Задачи без срока, которые не попадают ни в один период."""
        stmt = select(Record).where(Record.user_id == user_id, Record.datetime.is_(None))
        if status:
            stmt = stmt.where(Record.status == status)
        return list(self.db.scalars(stmt.order_by(Record.created_at.desc())).all())

    def latest(self, user_id: int = 1, record_type: Optional[RecordType] = None) -> Optional[Record]:
        """Последняя созданная запись, на нее ссылаются фразы "перенеси ее"."""
        stmt = select(Record).where(Record.user_id == user_id)
        if record_type:
            stmt = stmt.where(Record.type == record_type)
        stmt = stmt.order_by(Record.created_at.desc(), Record.id.desc()).limit(1)
        return self.db.scalars(stmt).first()

    def _expand_series(
        self, filters: list, from_: datetime, to: Optional[datetime]
    ) -> list[Record]:
        stmt = select(Record).where(*filters, Record.recurrence.is_not(None))
        if to:
            stmt = stmt.where(Record.datetime <= to)
        stmt = stmt.where(or_(Record.recurrence_until.is_(None), Record.recurrence_until >= from_))
        expanded: list[Record] = []
        for series in self.db.scalars(stmt):
            if to is None:
                when = rec_rules.next_occurrence(
                    series.datetime, series.recurrence, from_, series.recurrence_until
                )
                dates = [when] if when else []
            else:
                dates = rec_rules.occurrences(
                    series.datetime, series.recurrence, from_, to, series.recurrence_until
                )
            expanded.extend(make_occurrence(series, d) for d in dates)
        return expanded

    # ---- изменение --------------------------------------------------------

    def update(self, record_id: int, update_data: RecordUpdate) -> Optional[Record]:
        rec = self.get(record_id)
        if not rec:
            return None

        if update_data.title is not None:
            rec.title = update_data.title.strip()
        if update_data.datetime is not None:
            rec.datetime = update_data.datetime
        if update_data.status is not None:
            rec.status = update_data.status

        self.db.commit()
        self.db.refresh(rec)
        return rec

    def update_status(self, record_id: int, status: RecordStatus) -> Optional[Record]:
        return self.update(record_id, RecordUpdate(status=status))

    def set_recurrence(
        self, record_id: int, rule: Optional[str], until: Optional[datetime] = None
    ) -> Optional[Record]:
        """Включает или выключает (rule=None) повторение записи."""
        rec = self.get(record_id)
        if not rec:
            return None
        self._validate_recurrence(rule, rec.datetime, until)
        rec.recurrence = rule
        rec.recurrence_until = until if rule else None
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

    # ---- конфликты --------------------------------------------------------

    def find_conflicts(
        self,
        dt: datetime,
        window_minutes: int = 30,
        user_id: int = 1,
        exclude_id: Optional[int] = None,
    ) -> list[Record]:
        """Встречи, кроме отмененных, которые идут ближе window_minutes к dt."""
        start_w = dt - timedelta(minutes=window_minutes)
        end_w = dt + timedelta(minutes=window_minutes)
        filters = [
            Record.user_id == user_id,
            Record.type == RecordType.meeting,
            Record.status != RecordStatus.cancelled,
        ]
        if exclude_id:
            filters.append(Record.id != exclude_id)

        stmt = select(Record).where(
            and_(*filters, Record.datetime >= start_w, Record.datetime <= end_w)
        )
        conflicts = [r for r in self.db.scalars(stmt) if not r.recurrence]
        conflicts.extend(self._expand_series(filters, start_w, end_w))
        conflicts.sort(key=lambda r: abs((r.datetime - dt).total_seconds()))
        return conflicts
