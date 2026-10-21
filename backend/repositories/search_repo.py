import re
import difflib
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.schemas.record import RecordType, RecordStatus


SYNONYM_GROUPS = [
    {"договор", "контракт", "соглашение", "документ", "бумаги"},
    {"презентация", "презентаци", "слайды", "питч", "демо", "выступление", "доклад"},
    {"встреча", "созвон", "митинг", "переговоры", "синк", "звонок"},
    {"отчет", "отчёт", "доклад", "сводка"},

    {"команда", "коллектив", "тим", "отдел", "разработка"},
    {"билеты", "билет", "авиабилеты", "поездка", "перелет", "самолет", "поезд"},
    {"позвонить", "звонок", "набрать", "созвониться"},
    {"дизайнер", "дизайн", "макеты", "фигма"},
]

STOP_WORDS = {
    "найди", "поищи", "поиск", "задачу", "встречу", "запись", "напоминание", "про", "о", "об",
    "по", "с", "со", "когда", "у", "меня", "была", "я", "когда-то", "ставил", "ее",
    "её", "в", "на", "для", "и", "или", "что", "где", "как", "там"
}


def normalize_word(w: str) -> str:
    word = re.sub(r"[^\w]", "", w.lower().strip())
    # Базовый стемминг русских окончаний
    endings = [
        "ами", "ями", "ов", "ев", "ей", "иями", "иям", "иях",
        "ую", "юю", "ой", "ей", "ою", "ею", "ом", "ем", "ах", "ях",
        "ам", "ям", "ый", "ий", "ая", "яя", "ое", "ее", "ые", "ие",
        "а", "е", "и", "й", "о", "у", "ы", "ь", "я"
    ]
    for end in endings:
        if len(word) > len(end) + 3 and word.endswith(end):
            return word[:-len(end)]
    return word


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r"\b\w+\b", text.lower())
    clean = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    return clean


# Построение двунаправленного графа синонимов
SYNONYMS_GRAPH: dict[str, set[str]] = {}
for group in SYNONYM_GROUPS:
    stems = {normalize_word(w) for w in group}
    for stem in stems:
        if stem not in SYNONYMS_GRAPH:
            SYNONYMS_GRAPH[stem] = set()
        SYNONYMS_GRAPH[stem].update(stems - {stem})


class SearchRepository:
    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        query: str,
        user_id: int = 1,
        record_type: Optional[RecordType] = None,
        limit: int = 10,
    ) -> list[Record]:
        stmt = select(Record).where(Record.user_id == user_id)
        if record_type:
            stmt = stmt.where(Record.type == record_type)

        all_records = list(self.db.scalars(stmt).all())
        if not all_records:
            return []

        clean_query = query.lower().strip()
        query_words = extract_keywords(clean_query)
        if not query_words:
            query_words = [clean_query]

        query_stems = [normalize_word(w) for w in query_words]

        # Добавим синонимы двунаправленно
        expanded_stems = set(query_stems)
        for q_stem in query_stems:
            for base_stem, syn_stems in SYNONYMS_GRAPH.items():
                if q_stem.startswith(base_stem[:4]) or base_stem.startswith(q_stem[:4]):
                    expanded_stems.update(syn_stems)

        scored_records: list[tuple[float, Record]] = []

        for rec in all_records:
            score = 0.0
            title_lower = rec.title.lower()
            raw_lower = (rec.raw_text or "").lower()

            # 1. Точное вхождение всей фразы
            if clean_query in title_lower:
                score += 5.0
            elif clean_query in raw_lower:
                score += 3.0

            # 2. Пословное совпадение и стемминг (title и raw_text)
            title_words = extract_keywords(title_lower)
            raw_words = extract_keywords(raw_lower)
            all_text_words = title_words + raw_words
            all_text_stems = [normalize_word(w) for w in all_text_words]

            for q_stem in query_stems:
                if any(q_stem in t_stem or t_stem in q_stem for t_stem in all_text_stems):
                    score += 2.0
                elif any(q_stem in w for w in all_text_words):
                    score += 1.5

            # 3. Совпадение по расширенным синонимам
            for exp_stem in expanded_stems:
                if exp_stem not in query_stems:
                    if any(exp_stem in t_stem or t_stem in exp_stem for t_stem in all_text_stems):
                        score += 1.2

            # 4. Нечеткое совпадение (Levenshtein/SequenceMatcher)
            for qw in query_words:
                best_ratio = 0.0
                for tw in all_text_words:
                    ratio = difflib.SequenceMatcher(None, qw, tw).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                if best_ratio >= 0.75:
                    score += best_ratio * 1.5

            if score > 0.5:
                scored_records.append((score, rec))

        scored_records.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored_records[:limit]]
