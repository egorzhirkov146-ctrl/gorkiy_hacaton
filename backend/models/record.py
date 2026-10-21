import datetime as dt
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.schemas.record import RecordStatus, RecordType
from backend.storage import fts
from backend.storage import sqlite as _sqlite  # noqa: F401  регистрирует PRAGMA для SQLite

RECURRENCE_RULES = ("daily", "weekdays", "weekly", "monthly", "yearly")


def _enum(enum_cls) -> SQLEnum:
    # В базе хранится значение ("task"), а CHECK не дает записать чужую строку.
    return SQLEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        name=f"ck_{enum_cls.__name__.lower()}",
    )


def _now() -> dt.datetime:
    # Даты событий хранятся в локальном времени без зоны, поэтому created_at тоже.
    return dt.datetime.now().replace(microsecond=0)


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    type: Mapped[RecordType] = mapped_column(_enum(RecordType), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    datetime: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, default=_now)
    status: Mapped[RecordStatus] = mapped_column(
        _enum(RecordStatus), nullable=False, default=RecordStatus.pending
    )
    # Повторение: None для разовой записи, иначе одно из RECURRENCE_RULES.
    recurrence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    recurrence_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_records_title_not_empty"),
        CheckConstraint(
            "recurrence IS NULL OR recurrence IN ('daily', 'weekdays', 'weekly', 'monthly', 'yearly')",
            name="ck_records_recurrence_rule",
        ),
        CheckConstraint(
            "recurrence IS NULL OR datetime IS NOT NULL",
            name="ck_records_recurrence_needs_datetime",
        ),
        # Выборка за период и поиск конфликтов: WHERE user_id = ? AND datetime BETWEEN ? AND ?
        Index("ix_records_user_datetime", "user_id", "datetime"),
        # Фильтр по типу ("встречи на сегодня") и конфликты встреч.
        Index("ix_records_user_type_datetime", "user_id", "type", "datetime"),
        Index("ix_records_user_status", "user_id", "status"),
        # "Последняя созданная запись" для команд вида "перенеси ее".
        Index("ix_records_user_created", "user_id", "created_at"),
        # Частичный индекс по повторяющимся записям, он маленький и быстрый.
        Index(
            "ix_records_recurring",
            "user_id",
            "datetime",
            sqlite_where=text("recurrence IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Record id={self.id} type={self.type} title={self.title!r} datetime={self.datetime}>"


# FTS5-таблица и триггеры создаются вместе с таблицей records при create_all.
event.listen(Record.__table__, "after_create", fts.create_fts_listener)

# Таблица векторов регистрируется в метаданных вместе с records.
from backend.models import record_embedding as _record_embedding  # noqa: E402,F401
