import datetime as dt
from typing import Optional
from sqlalchemy import Integer, String, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base
from backend.schemas.record import RecordType, RecordStatus


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    type: Mapped[RecordType] = mapped_column(SQLEnum(RecordType), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    datetime: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        SQLEnum(RecordStatus), default=RecordStatus.pending, nullable=False, index=True
    )
