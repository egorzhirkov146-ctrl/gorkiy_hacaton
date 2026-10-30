from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


import os
from pathlib import Path


def init_db() -> None:
    from backend.models import Record, Message  # noqa: F401
    db_file = Path(settings.db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Автоматическая миграция новых колонок для SQLite
    try:
        with engine.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(records)")).fetchall()
            existing_cols = {row[1] for row in res}
            if "recurrence" not in existing_cols:
                conn.execute(text("ALTER TABLE records ADD COLUMN recurrence VARCHAR(20)"))
            if "recurrence_until" not in existing_cols:
                conn.execute(text("ALTER TABLE records ADD COLUMN recurrence_until DATETIME"))
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
