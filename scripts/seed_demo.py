"""Заполняет базу демонстрационными записями и проверяет целостность данных.

Запуск из корня проекта:
    python scripts/seed_demo.py              # пересоздать демо-набор в DB_PATH
    python scripts/seed_demo.py --keep       # добавить набор, не удаляя записи
    python scripts/seed_demo.py --check      # только проверить целостность
    python scripts/seed_demo.py --db ./data/demo.db
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.storage import check_integrity, init_storage  # noqa: E402
from backend.storage.demo_data import load_demo_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Демо-данные голосового ассистента")
    parser.add_argument("--db", default=settings.db_path, help="путь к файлу SQLite")
    parser.add_argument("--keep", action="store_true", help="не удалять существующие записи")
    parser.add_argument("--check", action="store_true", help="только проверить целостность")
    args = parser.parse_args()

    engine = create_engine(f"sqlite:///{args.db}")
    init_storage(engine)
    if not args.check:
        with sessionmaker(bind=engine)() as session:
            count = load_demo_data(session, reset=not args.keep)
        print(f"Создано демо-записей: {count} в {args.db}")

    report = check_integrity(engine)
    print(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
