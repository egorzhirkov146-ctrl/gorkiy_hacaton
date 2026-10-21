"""Демонстрационные записи для тестов, сидов и показа прототипа.

Даты считаются от переданного момента now, поэтому демо всегда показывает
"сегодня", "завтра" и "на этой неделе" относительно дня показа. Набор покрывает
сценарии из задания: создание задач и встреч, выборку за период и поиск
старых записей по смыслу.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.schemas.record import RecordStatus, RecordType

DEMO_USER_ID = 1
OTHER_USER_ID = 2


@dataclass(frozen=True)
class DemoRecord:
    type: RecordType
    title: str
    raw_text: Optional[str]
    # Смещение в днях от сегодняшней даты и время "ЧЧ:ММ"; None значит "без срока".
    day_offset: Optional[int]
    time: Optional[str] = None
    status: RecordStatus = RecordStatus.pending
    recurrence: Optional[str] = None
    user_id: int = DEMO_USER_ID
    # На сколько дней раньше даты события запись создана.
    created_days_before: int = 2


def _weekday_offset(now: datetime, weekday: int) -> int:
    """Число дней до ближайшего дня недели weekday (0 это понедельник), не считая сегодня."""
    return (weekday - now.weekday()) % 7 or 7


def demo_records(now: datetime) -> list[DemoRecord]:
    friday = _weekday_offset(now, 4)
    thursday = _weekday_offset(now, 3)
    sunday = 6 - now.weekday() if now.weekday() < 6 else 0
    return [
        # Сценарий 1: задачи и напоминания из текста задания.
        DemoRecord(RecordType.reminder, "Позвонить Ивану", "Напомни мне завтра в 10 утра позвонить Ивану", 1, "10:00"),
        DemoRecord(RecordType.task, "Отправить отчет", "В пятницу нужно отправить отчет", friday, "18:00"),
        DemoRecord(RecordType.task, "Купить билеты", "Поставь задачу купить билеты до конца недели", sunday, "23:59"),
        # Сценарий 2: встречи.
        DemoRecord(RecordType.meeting, "Встреча с командой", "Добавь встречу с командой завтра в 15:00", 1, "15:00"),
        DemoRecord(RecordType.meeting, "Встреча с дизайнером", "В четверг в 11 у меня встреча с дизайнером", thursday, "11:00"),
        # Сценарий 3: записи на сегодня, чтобы ответ на "Что у меня сегодня?" не был пустым.
        DemoRecord(RecordType.meeting, "Созвон с заказчиком по срокам", "Сегодня в 12 созвон с заказчиком", 0, "12:00"),
        DemoRecord(RecordType.task, "Проверить почту и ответить на письма", None, 0, "09:30", RecordStatus.done),
        DemoRecord(RecordType.reminder, "Забрать посылку на почте", "Напомни сегодня вечером забрать посылку", 0, "19:00"),
        DemoRecord(RecordType.meeting, "Обед с Ольгой", None, 0, "13:30", RecordStatus.cancelled),
        # Сценарий 4: старые записи для поиска по смыслу.
        DemoRecord(RecordType.task, "Подготовить презентацию для инвесторов", "Сделать слайды по итогам квартала", -3, "17:00", RecordStatus.done),
        DemoRecord(RecordType.task, "Согласовать договор с подрядчиком", "Я ставил задачу по договору, юристы должны проверить", -7, "12:00", RecordStatus.done),
        DemoRecord(RecordType.meeting, "Встреча с Иваном по партнерству", "Встреча с Иваном в кафе на Тверской", -5, "16:00", RecordStatus.done),
        DemoRecord(RecordType.meeting, "Собеседование с бэкенд-разработчиком", None, -10, "14:00", RecordStatus.done),
        DemoRecord(RecordType.task, "Оплатить счет за интернет", "Оплатить интернет до конца месяца", -12, "10:00", RecordStatus.done),
        DemoRecord(RecordType.reminder, "Записаться к стоматологу", "Напомни записаться к зубному врачу", -20, "09:00", RecordStatus.done),
        DemoRecord(RecordType.task, "Заказать торт на день рождения мамы", None, -30, "18:00", RecordStatus.done),
        # Ближайшие недели: выборка "на следующей неделе".
        DemoRecord(RecordType.meeting, "Планирование спринта", "Планирование спринта с командой разработки", 7, "10:00"),
        DemoRecord(RecordType.task, "Продлить страховку автомобиля", None, 9, "12:00"),
        DemoRecord(RecordType.meeting, "Демо прототипа голосового ассистента", "Показать прототип жюри хакатона", 10, "16:00"),
        # Задача без срока.
        DemoRecord(RecordType.task, "Прочитать книгу про архитектуру", "Когда-нибудь прочитать книгу про архитектуру", None),
        # Повторяющиеся записи (бонус S3).
        DemoRecord(RecordType.meeting, "Ежедневный стендап", "Стендап команды по будням в 10:00", 0, "10:00", recurrence="weekdays", created_days_before=14),
        DemoRecord(RecordType.reminder, "Оплатить аренду квартиры", "Каждый месяц оплачивать аренду", -15, "11:00", recurrence="monthly", created_days_before=0),
        # Запись другого пользователя: проверка, что выборки не смешивают пользователей.
        DemoRecord(RecordType.meeting, "Встреча с Иваном (чужой календарь)", None, 1, "15:00", user_id=OTHER_USER_ID),
    ]


def build_records(now: Optional[datetime] = None) -> list[Record]:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    today = now.replace(hour=0, minute=0)
    rows = []
    for item in demo_records(now):
        when = None
        created = now - timedelta(days=item.created_days_before)
        if item.day_offset is not None:
            hours, minutes = map(int, item.time.split(":"))
            when = today + timedelta(days=item.day_offset, hours=hours, minutes=minutes)
            created = min(now, when - timedelta(days=item.created_days_before))
        rows.append(
            Record(
                user_id=item.user_id,
                type=item.type,
                title=item.title,
                raw_text=item.raw_text,
                datetime=when,
                created_at=created,
                status=item.status,
                recurrence=item.recurrence,
            )
        )
    return rows


def load_demo_data(session: Session, now: Optional[datetime] = None, reset: bool = True) -> int:
    """Загружает демо-набор и возвращает число созданных записей.

    При reset=True функция сначала удаляет все записи, поэтому повторный
    запуск дает тот же набор, а не его копию.
    """
    if reset:
        session.execute(delete(Record))
    rows = build_records(now)
    session.add_all(rows)
    session.commit()
    return len(rows)
