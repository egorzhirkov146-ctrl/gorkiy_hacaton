"""Слой хранения: настройка SQLite, FTS5, повторы, эмбеддинги и проверки данных.

Публичные функции пакета подключаются к приложению одной строкой в init_db:
init_storage(engine).
"""
from backend.storage.integrity import IntegrityReport, check_integrity
from backend.storage.sqlite import init_storage, upgrade_schema

__all__ = ["init_storage", "upgrade_schema", "check_integrity", "IntegrityReport"]
