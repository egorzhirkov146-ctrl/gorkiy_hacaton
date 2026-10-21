"""Настройка SQLite и создание схемы хранилища."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import Engine, event, inspect, text

# Колонки, которых нет в таблице records ранних версий проекта.
_ADDED_COLUMNS = {
    "recurrence": "VARCHAR(16)",
    "recurrence_until": "DATETIME",
}


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """Включает внешние ключи, журнал WAL и ожидание блокировки для каждого соединения.

    WAL позволяет читать базу во время записи, а synchronous=NORMAL в режиме WAL
    не теряет данные при падении процесса, поэтому записи переживают перезапуск.
    """
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    db_file = cur.execute("PRAGMA database_list").fetchone()[2]
    if db_file:  # у базы в памяти пути нет, и WAL для нее не нужен
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def _ensure_parent_dir(engine: Engine) -> None:
    database = engine.url.database
    if database and database != ":memory:" and not database.startswith("file:"):
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def upgrade_schema(engine: Engine) -> list[str]:
    """Доводит существующую таблицу records до текущей модели.

    create_all не меняет уже созданные таблицы, поэтому функция добавляет
    новые колонки через ALTER TABLE и создает недостающие индексы.
    Возвращает список выполненных изменений.
    """
    from backend.models.record import Record

    changes: list[str] = []
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("records")}
        for name, ddl_type in _ADDED_COLUMNS.items():
            if name not in columns:
                conn.exec_driver_sql(f"ALTER TABLE records ADD COLUMN {name} {ddl_type}")
                changes.append(f"column {name}")
        for index in Record.__table__.indexes:
            exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :n"), {"n": index.name}
            ).first()
            if not exists:
                index.create(conn)
                changes.append(f"index {index.name}")
    return changes


def init_storage(engine: Engine) -> None:
    """Создает таблицы, индексы и FTS5, затем доводит старую схему до текущей.

    Функция идемпотентна: повторный вызов на готовой базе ничего не меняет,
    поэтому ее можно вызывать при каждом старте приложения.
    """
    from backend.db import Base
    from backend.models.record import Record  # noqa: F401  регистрирует таблицы
    from backend.storage import fts

    _ensure_parent_dir(engine)
    Base.metadata.create_all(bind=engine)
    upgrade_schema(engine)
    with engine.begin() as conn:
        fts.ensure_fts(conn)
    fts.forget_engine(engine)
