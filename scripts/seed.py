import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.db import init_db, SessionLocal
from backend.models.record import Record
from backend.schemas.record import RecordType, RecordStatus


def seed_database():
    print("Инициализация базы данных...")
    init_db()

    db = SessionLocal()
    try:
        count = db.query(Record).count()
        if count > 0:
            print(f"В базе данных уже есть {count} записей. Очищаем для свежего сида...")
            db.query(Record).delete()
            db.commit()

        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        tomorrow = now + timedelta(days=1)
        thursday = now + timedelta(days=(3 - now.weekday()) % 7 or 7)
        friday = now + timedelta(days=(4 - now.weekday()) % 7 or 7)
        sunday = now + timedelta(days=6 - now.weekday())

        sample_records = [
            Record(
                user_id=1,
                type=RecordType.reminder,
                title="Позвонить Ивану",
                raw_text="Напомни мне завтра в 10 утра позвонить Ивану",
                datetime=tomorrow.replace(hour=10, minute=0),
                status=RecordStatus.pending,
            ),
            Record(
                user_id=1,
                type=RecordType.task,
                title="Отправить отчет",
                raw_text="В пятницу нужно отправить отчет",
                datetime=friday.replace(hour=18, minute=0),
                status=RecordStatus.pending,
            ),
            Record(
                user_id=1,
                type=RecordType.task,
                title="Купить билеты до конца недели",
                raw_text="Поставь задачу купить билеты до конца недели",
                datetime=sunday.replace(hour=23, minute=59, second=59),
                status=RecordStatus.pending,
            ),
            Record(
                user_id=1,
                type=RecordType.meeting,
                title="Встреча с командой",
                raw_text="Добавь встречу с командой завтра в 15:00",
                datetime=tomorrow.replace(hour=15, minute=0),
                status=RecordStatus.pending,
            ),
            Record(
                user_id=1,
                type=RecordType.meeting,
                title="Встреча с дизайнером",
                raw_text="В четверг в 11 у меня встреча с дизайнером",
                datetime=thursday.replace(hour=11, minute=0),
                status=RecordStatus.pending,
            ),
            Record(
                user_id=1,
                type=RecordType.task,
                title="Подготовить презентацию для инвесторов",
                raw_text="Подготовить презентацию по проекту",
                datetime=now - timedelta(days=3),
                status=RecordStatus.done,
            ),
            Record(
                user_id=1,
                type=RecordType.task,
                title="Согласовать договор с контрагентом",
                raw_text="Поставить задачу по договору",
                datetime=now - timedelta(days=7),
                status=RecordStatus.done,
            ),
            Record(
                user_id=1,
                type=RecordType.meeting,
                title="Встреча с Иваном по партнерству",
                raw_text="Встреча с Иваном в кафе",
                datetime=now - timedelta(days=5),
                status=RecordStatus.done,
            ),
        ]

        db.add_all(sample_records)
        db.commit()
        print(f"Успешно создано {len(sample_records)} начальных записей в БД.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
