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
    "пару": 2,
    "пара": 2,
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
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "двадцать": 20,
    "двадцать пять": 25,
    "тридцать": 30,
    "сорок": 40,
    "сорок пять": 45,
    "пятьдесят": 50,
    "полчаса": 30,
    "полтора": 1.5,
}

RU_WEEKDAYS = {
    "понедельник": 0,
    "понедельника": 0,
    "понедельнику": 0,
    "вторник": 1,
    "вторника": 1,
    "вторнику": 1,
    "среду": 2,
    "среда": 2,
    "среды": 2,
    "среде": 2,
    "четверг": 3,
    "четверга": 3,
    "четвергу": 3,
    "пятницу": 4,
    "пятница": 4,
    "пятницы": 4,
    "пятнице": 4,
    "субботу": 5,
    "суббота": 5,
    "субботы": 5,
    "субботе": 5,
    "воскресенье": 6,
    "воскресенья": 6,
    "воскресенью": 6,
}



@dataclass
class ParsedDateTime:
    dt: Optional[datetime] = None
    iso: Optional[str] = None
    has_explicit_time: bool = False
    has_explicit_date: bool = False
    period: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None



class RussianDateParser:
    def __init__(self, default_tz: str = "Europe/Moscow"):
        self.default_tz = default_tz

    def parse_time_component(self, text: str) -> tuple[Optional[time], bool]:
        clean = text.lower().strip()

        # 1. Формат ЧЧ:ММ (15:00, 18.30)
        match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", clean)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
            if 0 <= h < 24 and 0 <= m < 60:
                return time(h, m), True

        # 2. в X часов утра / ночи
        match = re.search(r"\bв\s+(\d{1,2})\s*(?:ч|час|часа|часов)?\s*(?:утра|ночи)\b", clean)
        if match:
            h = int(match.group(1))
            if 0 <= h <= 12:
                return time(h if h < 12 else 0, 0), True

        # 3. в X часов дня / вечера (например: в 3 часа дня, в 8 вечера, в 11 вечера)
        match = re.search(r"\bв\s+(\d{1,2})\s*(?:ч|час|часа|часов)?\s*(?:дня|вечера)\b", clean)
        if match:
            h = int(match.group(1))
            if 1 <= h <= 12:
                actual_h = h + 12 if h < 12 else 12
                return time(actual_h, 0), True

        # 4. в X (часов) (например: в 11, в 15, в 15:00)
        match = re.search(r"\bв\s+(\d{1,2})\s*(?:ч|час|часа|часов)?\b", clean)
        if match:
            h = int(match.group(1))
            if 1 <= h <= 6:
                return time(h + 12, 0), True
            elif 0 <= h < 24:
                return time(h, 0), True

        # 5. Словесные указания времени
        if "утром" in clean:
            return time(9, 0), True
        if "днем" in clean or "днём" in clean:
            return time(14, 0), True
        if "вечером" in clean:
            return time(19, 0), True
        if "в полдень" in clean or "полдень" in clean:
            return time(12, 0), True
        if "в полночь" in clean or "полночь" in clean:
            return time(0, 0), True

        return None, False

    def parse_relative_delta(self, text: str, base_dt: datetime) -> Optional[datetime]:
        clean = text.lower().strip()

        if "через полчаса" in clean:
            return base_dt + timedelta(minutes=30)
        if "через полтора часа" in clean:
            return base_dt + timedelta(minutes=90)
        if "через пару часов" in clean:
            return base_dt + timedelta(hours=2)
        if "через пару дней" in clean:
            return base_dt + timedelta(days=2)
        if "через час" in clean or "через часик" in clean:
            return base_dt + timedelta(hours=1)
        if "через день" in clean:
            return base_dt + timedelta(days=1)
        if "через неделю" in clean:
            return base_dt + timedelta(days=7)

        match = re.search(r"через\s+(\w+|\d+)\s*(час|часа|часов|минут|минуты|минуту|дней|дня|день|недел|недели|недель)", clean)
        if match:
            val_raw = match.group(1)
            unit = match.group(2)

            if val_raw.isdigit():
                val = float(val_raw)
            else:
                val = RU_NUMBER_WORDS.get(val_raw, None)

            if val is not None:
                if "час" in unit:
                    return base_dt + timedelta(hours=int(val))
                elif "минут" in unit:
                    return base_dt + timedelta(minutes=int(val))
                elif "дн" in unit or "ден" in unit:
                    return base_dt + timedelta(days=int(val))
                elif "недел" in unit:
                    return base_dt + timedelta(days=int(val * 7))

        return None

    def parse_period(self, text: str, base_dt: datetime) -> Optional[tuple[str, datetime, datetime]]:
        clean = text.lower().strip()

        if clean in ("after_tomorrow", "day_after_tomorrow", "послезавтра") or "послезавтра" in clean:
            t = base_dt + timedelta(days=2)
            start = t.replace(hour=0, minute=0, second=0, microsecond=0)
            end = t.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "custom", start, end

        if clean in ("today", "сегодня") or re.search(r"\bсегодня\b", clean):
            start = base_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end = base_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "today", start, end

        if clean in ("tomorrow", "завтра") or re.search(r"\bзавтра\b", clean):
            t = base_dt + timedelta(days=1)
            start = t.replace(hour=0, minute=0, second=0, microsecond=0)
            end = t.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "tomorrow", start, end

        if clean == "this_week" or "до конца недели" in clean or "на этой неделе" in clean or "на эту неделю" in clean:
            monday = base_dt - timedelta(days=base_dt.weekday())
            sunday = monday + timedelta(days=6)
            start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "this_week", start, end

        if clean == "next_week" or "на следующей неделе" in clean or "на следующую неделю" in clean:
            next_monday = base_dt + timedelta(days=7 - base_dt.weekday())
            next_sunday = next_monday + timedelta(days=6)
            start = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = next_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "next_week", start, end

        if clean == "weekend" or "на выходных" in clean or "в выходные" in clean or "на эти выходные" in clean:
            saturday_offset = (5 - base_dt.weekday()) % 7
            saturday = base_dt + timedelta(days=saturday_offset)
            sunday = saturday + timedelta(days=1)
            start = saturday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return "this_week", start, end

        for w_name, w_idx in RU_WEEKDAYS.items():
            if re.search(rf"\b(?:в|во|на)?\s*{w_name}\b", clean):
                days_ahead = (w_idx - base_dt.weekday()) % 7
                if days_ahead == 0 and "сегодня" not in clean:
                    days_ahead = 7
                target_d = base_dt + timedelta(days=days_ahead)
                start = target_d.replace(hour=0, minute=0, second=0, microsecond=0)
                end = target_d.replace(hour=23, minute=59, second=59, microsecond=999999)
                return "custom", start, end

        if clean in ("all", "all_time", "все время", "всё время"):
            return "all", None, None

        return None

    def parse(self, text: Optional[str], base_dt: Optional[datetime] = None) -> ParsedDateTime:
        if not text:
            return ParsedDateTime()

        clean = text.lower().strip()
        now = base_dt or datetime.now()

        # 0. ISO дата или дата со временем в формате YYYY-MM-DD
        try:
            iso_dt = datetime.fromisoformat(text.strip())
            has_explicit = (iso_dt.time() != time(0, 0)) or ("T" in text or "t" in text or ":" in text)
            return ParsedDateTime(
                dt=iso_dt,
                iso=iso_dt.isoformat(),
                has_explicit_time=has_explicit,
            )
        except Exception:
            pass

        match_iso = re.search(r"(\d{4}-\d{2}-\d{2})(?:[T\s](\d{1,2}:\d{2}(?::\d{2})?))?", text, re.IGNORECASE)
        if match_iso:
            try:
                date_part = datetime.strptime(match_iso.group(1), "%Y-%m-%d").date()
                if match_iso.group(2):
                    time_part = datetime.strptime(match_iso.group(2)[:5], "%H:%M").time()
                    has_explicit = True
                else:
                    parsed_time, has_explicit = self.parse_time_component(clean)
                    time_part = parsed_time if has_explicit else time(0, 0, 0)
                res_dt = datetime.combine(date_part, time_part)
                return ParsedDateTime(
                    dt=res_dt,
                    iso=res_dt.isoformat(),
                    has_explicit_time=has_explicit,
                    has_explicit_date=True,
                )
            except Exception:
                pass

        # 1. Относительные дельты ("через два часа", "через 15 минут", "через час")
        delta_dt = self.parse_relative_delta(clean, now)
        if delta_dt:
            return ParsedDateTime(
                dt=delta_dt,
                iso=delta_dt.isoformat(),
                has_explicit_time=True,
                has_explicit_date=True,
            )

        parsed_time, has_time = self.parse_time_component(clean)

        period_info = self.parse_period(clean, now)
        period_name, p_start, p_end = (period_info if period_info else (None, None, None))

        target_date = None

        if clean in ("after_tomorrow", "day_after_tomorrow", "послезавтра") or "послезавтра" in clean:
            target_date = (now + timedelta(days=2)).date()
        elif clean in ("tomorrow", "завтра") or re.search(r"\bзавтра\b", clean):
            target_date = (now + timedelta(days=1)).date()
        elif clean in ("today", "сегодня") or re.search(r"\bсегодня\b", clean):
            target_date = now.date()
        elif re.search(r"\bвчера\b", clean):
            target_date = (now - timedelta(days=1)).date()
        elif "до конца недели" in clean:
            days_ahead = 6 - now.weekday()
            target_date = (now + timedelta(days=days_ahead)).date()
            if not has_time:
                parsed_time = time(23, 59, 59)
                has_time = True
        else:
            is_next_week = bool(re.search(r"\bследующ\w*\b", clean)) or ("на следующей неделе" in clean)
            weekday_found = False
            for wname, wday in RU_WEEKDAYS.items():
                if re.search(rf"\b(?:в|во|до|к|на)?\s*{wname}\b", clean):
                    days_ahead = (wday - now.weekday()) % 7
                    if is_next_week:
                        days_ahead += 7
                    elif days_ahead == 0 and has_time and parsed_time and parsed_time <= now.time():
                        days_ahead = 7
                    elif days_ahead == 0 and not has_time:
                        if bool(re.search(rf"\b(до|к)\s*{wname}\b", clean)):
                            days_ahead = 0
                        else:
                            days_ahead = 7
                    target_date = (now + timedelta(days=days_ahead)).date()
                    if bool(re.search(rf"\b(до|к)\s*{wname}\b", clean)) and not has_time:
                        parsed_time = time(23, 59, 59)
                        has_time = True
                    weekday_found = True
                    break

            if not weekday_found and "на следующей неделе" in clean:
                days_ahead = 7 - now.weekday()
                target_date = (now + timedelta(days=days_ahead)).date()


        if target_date is not None:
            final_time = parsed_time if has_time else time(0, 0, 0)
            res_dt = datetime.combine(target_date, final_time)
            return ParsedDateTime(
                dt=res_dt,
                iso=res_dt.isoformat(),
                has_explicit_time=has_time,
                has_explicit_date=True,
                period=period_name,
                period_start=p_start,
                period_end=p_end
            )

        month_match = re.search(
            r"\b(\d{1,2}\s+(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[яеи]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)(?:\s+(?:в\s+)?\d{1,2}[:.]\d{2})?)\b|\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?:\s+(?:в\s+)?\d{1,2}[:.]\d{2})?)\b",
            clean
        )

        fallback_dt = None
        if month_match:
            date_snippet = (month_match.group(1) or month_match.group(2) or clean).strip()
            fallback_dt = dateparser.parse(
                date_snippet,
                languages=["ru"],
                settings={
                    "RELATIVE_BASE": now,
                    "PREFER_DATES_FROM": "future",
                    "RETURN_AS_TIMEZONE_AWARE": False,
                    "DATE_ORDER": "DMY",
                }
            )

        if fallback_dt:
            final_time = parsed_time if has_time else fallback_dt.time()
            res_dt = datetime.combine(fallback_dt.date(), final_time)
            has_explicit = has_time or (final_time != time(0, 0))
            return ParsedDateTime(
                dt=res_dt,
                iso=res_dt.isoformat(),
                has_explicit_time=has_explicit,
                has_explicit_date=True,
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
                has_explicit_time=True,
                has_explicit_date=False
            )

        fallback_dt = dateparser.parse(
            clean,
            languages=["ru"],
            settings={
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "DATE_ORDER": "DMY",
            }
        )

        if fallback_dt:
            has_explicit = has_time or (fallback_dt.time() != time(0, 0))
            return ParsedDateTime(
                dt=fallback_dt,
                iso=fallback_dt.isoformat(),
                has_explicit_time=has_explicit,
                has_explicit_date=True,
                period=period_name,
                period_start=p_start,
                period_end=p_end
            )

        return ParsedDateTime(
            period=period_name,
            period_start=p_start,
            period_end=p_end
        )
