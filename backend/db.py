from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Таблицы records, record_embeddings, индексы и FTS5 создает слой хранения.
    from backend.storage import init_storage

    init_storage(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
