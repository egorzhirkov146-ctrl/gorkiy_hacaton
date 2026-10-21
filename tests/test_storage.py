"""Схема хранилища: таблицы, индексы, FTS5, миграция старой базы, перезапуск, целостность."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.repositories.record_repo import RecordRepository
from backend.repositories.search_repo import SearchRepository
from backend.schemas.record import RecordCreate, RecordStatus, RecordType
from backend.storage import check_integrity, init_storage
from backend.storage.demo_data import load_demo_data


def objects(engine, kind):
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = :t"), {"t": kind})}


def test_schema_objects_created(engine):
    assert {"records", "record_embeddings", "records_fts", "records_fts_vocab"} <= objects(engine, "table")
    assert {"records_fts_ai", "records_fts_au", "records_fts_ad"} <= objects(engine, "trigger")
    assert {
        "ix_records_user_datetime",
        "ix_records_user_type_datetime",
        "ix_records_user_status",
        "ix_records_user_created",
        "ix_records_recurring",
    } <= objects(engine, "index")
    columns = {c["name"] for c in inspect(engine).get_columns("records")}
    assert {"id", "type", "title", "raw_text", "datetime", "created_at", "status", "user_id"} <= columns


def test_init_storage_is_idempotent(engine):
    before = objects(engine, "index") | objects(engine, "trigger")
    init_storage(engine)
    init_storage(engine)
    assert objects(engine, "index") | objects(engine, "trigger") == before


def test_data_persists_across_restart(tmp_path):
    """Запись, сохраненная до "перезапуска", читается и ищется после него.

    Перезапуск моделируется закрытием всех соединений и созданием нового
    движка на тот же файл, как это происходит при рестарте контейнера.
    """
    db_file = tmp_path / "data" / "sqlite.db"
    url = f"sqlite:///{db_file}"

    engine = create_engine(url)
    init_storage(engine)
    with sessionmaker(bind=engine)() as s:
        rec_id = RecordRepository(s).create(
            RecordCreate(type=RecordType.meeting, title="Встреча с дизайнером", datetime=datetime(2026, 10, 22, 11))
        ).id
    engine.dispose()

    restarted = create_engine(url)
    init_storage(restarted)
    with sessionmaker(bind=restarted)() as s:
        rec = RecordRepository(s).get(rec_id)
        assert rec.title == "Встреча с дизайнером"
        assert rec.datetime == datetime(2026, 10, 22, 11)
        assert [r.id for r in SearchRepository(s, embedder=None).search("дизайнер")] == [rec_id]
    with restarted.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    restarted.dispose()


LEGACY_SCHEMA = """
CREATE TABLE records (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER,
    type VARCHAR(8) NOT NULL,
    title VARCHAR(500) NOT NULL,
    raw_text VARCHAR(1000),
    datetime DATETIME,
    created_at DATETIME NOT NULL,
    status VARCHAR(9) NOT NULL
)
"""


def test_upgrade_legacy_database(tmp_path):
    """База, созданная ранней моделью без FTS и повторов, доводится до текущей схемы."""
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(LEGACY_SCHEMA)
        conn.exec_driver_sql(
            "INSERT INTO records (user_id, type, title, raw_text, datetime, created_at, status) "
            "VALUES (1, 'task', 'Согласовать договор', NULL, '2026-10-10 12:00:00', '2026-10-01 10:00:00', 'done')"
        )
    init_storage(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("records")}
    assert {"recurrence", "recurrence_until"} <= columns
    with sessionmaker(bind=engine)() as s:
        hits = SearchRepository(s, embedder=None).search("договор")
        assert [h.title for h in hits] == ["Согласовать договор"]
        assert hits[0].status == RecordStatus.done
    assert check_integrity(engine).ok
    engine.dispose()


def test_fts_rebuilds_when_rows_bypass_triggers(engine, session):
    # Имитация строк, которые попали в records до создания триггеров.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER records_fts_ai")
        conn.exec_driver_sql(
            "INSERT INTO records (user_id, type, title, created_at, status) "
            "VALUES (1, 'task', 'Продлить страховку', '2026-10-01 10:00:00', 'pending')"
        )
    init_storage(engine)
    assert [r.title for r in SearchRepository(session, embedder=None).search("страховка")] == ["Продлить страховку"]


def test_integrity_report(engine, demo_session):
    report = check_integrity(engine)
    assert report.ok, str(report)
    assert report.records > 20

    with engine.begin() as conn:
        # Встреча без даты считается ошибкой данных.
        conn.exec_driver_sql(
            "INSERT INTO records (user_id, type, title, created_at, status) "
            "VALUES (1, 'meeting', 'Встреча без времени', '2026-10-01 10:00:00', 'pending')"
        )
    report = check_integrity(engine)
    assert not report.ok
    assert report.problems["встреча без даты"] == 1


def test_cascade_deletes_embeddings(engine, session, repo):
    rec = repo.create(RecordCreate(type=RecordType.task, title="Задача с вектором"))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO record_embeddings (record_id, model, text_hash, dim, vector, updated_at) "
            "VALUES (?, 'fake', 'x', 1, x'00000000', '2026-10-01 10:00:00')",
            (rec.id,),
        )
    repo.delete(rec.id)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM record_embeddings").scalar_one() == 0


# Запросы, которые выполняет репозиторий, и индекс, который SQLite должен для них выбрать.
QUERY_PLANS = [
    (
        "SELECT * FROM records WHERE user_id = 1 AND datetime >= '2026-10-21' AND datetime <= '2026-10-22'",
        "ix_records_user_datetime",
    ),
    (
        "SELECT * FROM records WHERE user_id = 1 AND type = 'meeting' "
        "AND datetime >= '2026-10-21 14:15' AND datetime <= '2026-10-21 15:45'",
        "ix_records_user_type_datetime",
    ),
    ("SELECT * FROM records WHERE user_id = 1 ORDER BY created_at DESC LIMIT 1", "ix_records_user_created"),
    (
        "SELECT * FROM records WHERE user_id = 1 AND recurrence IS NOT NULL AND datetime <= '2026-10-22'",
        "ix_records_recurring",
    ),
]


@pytest.mark.parametrize("sql, index", QUERY_PLANS)
def test_queries_use_indexes(engine, demo_session, sql, index):
    with engine.connect() as conn:
        conn.exec_driver_sql("ANALYZE")
        plan = " ".join(str(r[-1]) for r in conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {sql}"))
    assert index in plan, plan


def test_period_query_is_fast_on_large_table(engine, session, repo):
    """Выборка за день среди 20 000 записей занимает меньше 50 мс."""
    import time

    start = datetime(2026, 1, 1, 9, 0)
    rows = [
        RecordCreate(type=RecordType.task, title=f"Задача {i}", datetime=start + timedelta(hours=3 * i))
        for i in range(20_000)
    ]
    repo.create_many(rows)
    day = datetime(2027, 6, 1)
    t0 = time.perf_counter()
    result = repo.list_by_period(day, day + timedelta(hours=23, minutes=59))
    elapsed = time.perf_counter() - t0
    assert len(result) == 8
    assert elapsed < 0.05, elapsed
