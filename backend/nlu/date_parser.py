import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional
import dateparser


RU_NUMBER_WORDS = {
    "ноль": 0,
    "один": 1,
    "одна": 1,
    "одну": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "полчаса": 30,
    "полтора": 1.5,
}

RU_WEEKDAYS = {
    "понедельник": 0,
    "вторник": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
}


@dataclass
class ParsedDateTime:
    dt: Optional[datetime] = None
    iso: Optional[str] = None
    has_explicit_time: bool = False
    period: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class RussianDateParser:
    def __init__(self, default_tz: str = "Europe/Moscow"):
        self.default_tz = default_tz

    def parse_time_component(self, text: str) -> tuple[Optional[time], bool]:
        clean = text.lower().strip()

        match = re.search(r"\b(\d{1,2})[:.-](\d{2})\b", clean)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            if 0 <= h < 24 and 0 <= m < 60:
                return time(h, m), True

        match = re.search(r"\bв\s+(\d{1,2})\s*(?:утра|ночи)\b", clean)
        if match:
            h = int(match.group(1))
            if 0 <= h <= 12:
                return time(h if h < 12 else 0, 0), True

        match = re.search(r"\bв\s+(\d{1,2})\s*(?:дня|вечера)\b", clean)
        if match:
            h = int(match.group(1))
            if 1 <= h <= 12:
                actual_h = h + 12 if h < 12 else 12
                return time(actual_h, 0), True

        match = re.search(r"\bв\s+(\d{1,2})\s*(?:ч|час|часа|часов)?\b", clean)
        if match:
            h = int(match.group(1))
            if 0 <= h < 24:
                return time(h, 0), True

        if "утром" in clean:
            return time(9, 0), True
        if "днем" in clean or "днём" in clean:
            return time(14, 0), True
        if "вечером" in clean:
            return time(19, 0), True
        if "в полдень" in clean:
            return time(12, 0), True
        if "в полночь" in clean:
            return time(0, 0), True

        return None, False

    def parse_relative_delta(self, text: str, base_dt: datetime) -> Optional[datetime]:
        clean = text.lower().strip()

        if "через полчаса" in clean:
            return base_dt + timedelta(minutes=30)

        match = re.search(r"через\s+(\w+|\d+)\s*(час|часа|часов|минут|минуты|минуту|дней|дня|день)", clean)
        if match:
            val_raw = match.group(1)
            unit = match.group(2)

            if val_raw.isdigit():
                val = int(val_raw)
            else:
                val = RU_NUMBER_WORDS.get(val_raw, None)

            if val is not None:
                if "час" in unit:
                    return base_dt + timedelta(hours=int(val))
                elif "минут" in unit:
                    return base_dt + timedelta(minutes=int(val))
                elif "дн" in unit or "ден" in unit:
                    return base_dt + timedelta(days=int(val))

        return None

    def parse_period(self, text: str, base_dt: datetime) -> Optional[tuple[str, datetime, datetime]]:
        clean = text.lower().strip()

        if "сегодня" in clean:
            start = base_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end = base_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "today", start, end

        if "завтра" in clean:
            t = base_dt + timedelta(days=1)
            start = t.replace(hour=0, minute=0, second=0, microsecond=0)
            end = t.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "tomorrow", start, end

        if "до конца недели" in clean:
            days_ahead = 6 - base_dt.weekday()
            sunday = base_dt + timedelta(days=days_ahead)
            end = sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "this_week", base_dt, end

        if "на этой неделе" in clean or "на эту неделю" in clean:
            monday = base_dt - timedelta(days=base_dt.weekday())
            sunday = monday + timedelta(days=6)
            start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "this_week", start, end

        if "на следующей неделе" in clean or "на следующую неделю" in clean:
            next_monday = base_dt + timedelta(days=7 - base_dt.weekday())
            next_sunday = next_monday + timedelta(days=6)
            start = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = next_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "next_week", start, end

        return None

    def parse(self, text: Optional[str], base_dt: Optional[datetime] = None) -> ParsedDateTime:
        if not text:
            return ParsedDateTime()

        clean = text.lower().strip()
        now = base_dt or datetime.now()

        delta_dt = self.parse_relative_delta(clean, now)
        if delta_dt:
            return ParsedDateTime(dt=delta_dt, iso=delta_dt.isoformat(), has_explicit_time=True)

        parsed_time, has_time = self.parse_time_component(clean)

        period_info = self.parse_period(clean, now)
        period_name, p_start, p_end = (period_info if period_info else (None, None, None))

        target_date = None

        if "послезавтра" in clean:
            target_date = (now + timedelta(days=2)).date()
        elif "завтра" in clean:
            target_date = (now + timedelta(days=1)).date()
        elif "сегодня" in clean:
            target_date = now.date()
        elif "вчера" in clean:
            target_date = (now - timedelta(days=1)).date()
        elif "до конца недели" in clean:
            days_ahead = 6 - now.weekday()
            target_date = (now + timedelta(days=days_ahead)).date()
            if not has_time:
                parsed_time = time(23, 59, 59)
                has_time = True
        elif "на следующей неделе" in clean:
            days_ahead = 7 - now.weekday()
            target_date = (now + timedelta(days=days_ahead)).date()
        else:
            for wname, wday in RU_WEEKDAYS.items():
                if re.search(rf"\b(в|во)?\s*{wname}\b", clean):
                    days_ahead = (wday - now.weekday()) % 7
                    if days_ahead == 0 and has_time and parsed_time and parsed_time <= now.time():
                        days_ahead = 7
                    elif days_ahead == 0 and not has_time:
                        days_ahead = 7
                    target_date = (now + timedelta(days=days_ahead)).date()
                    break

        if target_date is not None:
            final_time = parsed_time if has_time else time(0, 0, 0)
            res_dt = datetime.combine(target_date, final_time)
            return ParsedDateTime(
                dt=res_dt,
                iso=res_dt.isoformat(),
                has_explicit_time=has_time,
                period=period_name,
                period_start=p_start,
                period_end=p_end
            )

        if has_time and parsed_time is not None:
            today_dt = datetime.combine(now.date(), parsed_time)
            if today_dt < now:
                res_dt = today_dt + timedelta(days=1)
            else:
                res_dt = today_dt
            return ParsedDateTime(
                dt=res_dt,
                iso=res_dt.isoformat(),
                has_explicit_time=True
            )

        fallback_dt = dateparser.parse(
            clean,
            languages=["ru"],
            settings={
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False
            }
        )

        if fallback_dt:
            has_explicit = has_time or (fallback_dt.time() != time(0, 0))
            return ParsedDateTime(
                dt=fallback_dt,
                iso=fallback_dt.isoformat(),
                has_explicit_time=has_explicit,
                period=period_name,
                period_start=p_start,
                period_end=p_end
            )

        return ParsedDateTime(
            period=period_name,
            period_start=p_start,
            period_end=p_end
        )
