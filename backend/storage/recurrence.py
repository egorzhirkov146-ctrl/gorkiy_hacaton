"""Развертка повторяющихся записей в отдельные даты внутри периода.

В базе повторяющаяся запись хранится одной строкой: дата первого повтора
в datetime, правило в recurrence и необязательная граница recurrence_until.
Повторы не записываются в базу, а вычисляются при чтении периода.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Iterator, Optional

# Защита от бесконечной развертки, если период задан на годы вперед.
MAX_OCCURRENCES = 1000


def _add_months(start: datetime, months: int) -> datetime:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    # 31 января плюс месяц дает последний день февраля, а не ошибку.
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def nth_occurrence(start: datetime, rule: str, n: int) -> datetime:
    """Возвращает n-й повтор, считая первый повтор (start) нулевым."""
    if rule == "daily":
        return start + timedelta(days=n)
    if rule == "weekly":
        return start + timedelta(weeks=n)
    if rule == "monthly":
        return _add_months(start, n)
    if rule == "yearly":
        return _add_months(start, 12 * n)
    raise ValueError(f"Неизвестное правило повторения: {rule}")


def occurrences(
    start: datetime,
    rule: str,
    window_from: datetime,
    window_to: datetime,
    until: Optional[datetime] = None,
    limit: int = MAX_OCCURRENCES,
) -> Iterator[datetime]:
    """Перечисляет повторы, которые попадают в отрезок [window_from, window_to]."""
    end = min(window_to, until) if until else window_to
    if start > end:
        return
    count = 0
    if rule == "weekdays":
        current = start
        if current < window_from:
            # Перескакиваем к началу окна целыми днями и сохраняем время суток.
            current = start + timedelta(days=(window_from - start).days)
            if current < window_from:
                current += timedelta(days=1)
        while current <= end and count < limit:
            if current.weekday() < 5:
                yield current
                count += 1
            current += timedelta(days=1)
        return

    n = 0
    if window_from > start and rule in ("daily", "weekly"):
        step = timedelta(days=1 if rule == "daily" else 7)
        n = (window_from - start) // step
    while count < limit:
        current = nth_occurrence(start, rule, n)
        if current > end:
            return
        if current >= window_from:
            yield current
            count += 1
        n += 1


def next_occurrence(
    start: datetime, rule: str, after: datetime, until: Optional[datetime] = None
) -> Optional[datetime]:
    """Возвращает первый повтор не раньше момента after или None."""
    horizon = after + timedelta(days=366 * 2)
    return next(occurrences(start, rule, after, horizon, until, limit=1), None)
