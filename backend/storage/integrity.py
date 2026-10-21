"""Проверка целостности данных перед демо (спринт S4)."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.storage import fts

# Каждая проверка это SQL, который возвращает число нарушений.
_CHECKS = {
    "пустой заголовок": "SELECT count(*) FROM records WHERE title IS NULL OR length(trim(title)) = 0",
    "неизвестный тип": "SELECT count(*) FROM records WHERE type NOT IN ('task', 'meeting', 'reminder')",
    "неизвестный статус": "SELECT count(*) FROM records WHERE status NOT IN ('pending', 'done', 'cancelled')",
    "встреча без даты": "SELECT count(*) FROM records WHERE type = 'meeting' AND datetime IS NULL",
    "повтор без даты": "SELECT count(*) FROM records WHERE recurrence IS NOT NULL AND datetime IS NULL",
    "граница повтора раньше начала": (
        "SELECT count(*) FROM records WHERE recurrence_until IS NOT NULL AND recurrence_until < datetime"
    ),
    "дата создания в будущем": (
        "SELECT count(*) FROM records WHERE created_at > datetime('now', 'localtime', '+1 day')"
    ),
    "вектор без записи": (
        "SELECT count(*) FROM record_embeddings e LEFT JOIN records r ON r.id = e.record_id WHERE r.id IS NULL"
    ),
}


@dataclass
class IntegrityReport:
    records: int = 0
    problems: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not any(self.problems.values())

    def __str__(self) -> str:
        lines = [f"Записей: {self.records}. Итог: {'OK' if self.ok else 'ЕСТЬ ПРОБЛЕМЫ'}"]
        lines += [f"  {name}: {count}" for name, count in self.problems.items() if count]
        lines += [f"  ошибка: {e}" for e in self.errors]
        return "\n".join(lines)


def check_integrity(engine: Engine) -> IntegrityReport:
    """Проверяет файл SQLite, ограничения данных и синхронность индекса FTS5.

    "Встреча без даты" считается проблемой, потому что NLU-модуль задает
    уточняющий вопрос о времени и не должен сохранять такую встречу.
    """
    report = IntegrityReport()
    with engine.connect() as conn:
        status = conn.exec_driver_sql("PRAGMA integrity_check").scalar_one()
        if status != "ok":
            report.errors.append(f"PRAGMA integrity_check: {status}")
        for row in conn.exec_driver_sql("PRAGMA foreign_key_check"):
            report.errors.append(f"нарушен внешний ключ: {tuple(row)}")
        report.records = conn.execute(text("SELECT count(*) FROM records")).scalar_one()
        for name, sql in _CHECKS.items():
            report.problems[name] = conn.execute(text(sql)).scalar_one()
        report.problems["запись не синхронна с индексом FTS5"] = fts.unsynced_rows(conn)
        try:
            fts.integrity_check(conn)
        except Exception as exc:
            report.errors.append(f"индекс FTS5 поврежден: {exc}")
        conn.rollback()
    return report
