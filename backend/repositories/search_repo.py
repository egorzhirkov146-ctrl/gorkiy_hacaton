import difflib
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.schemas.record import RecordType
from backend.storage.text import fold, stem, keywords, synonym_stems, words as split_words


def normalize_word(w: str) -> str:
    return stem(w)


def extract_keywords(text: str) -> list[str]:
    return keywords(text)


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

        clean_query = fold(query.strip())
        query_words = extract_keywords(clean_query)
        if not query_words:
            query_words = split_words(clean_query) or [clean_query]

        query_stems = [stem(w) for w in query_words]

        # Добавим основы синонимов двунаправленно
        expanded_stems = set(query_stems)
        for q_stem in query_stems:
            expanded_stems.update(synonym_stems(q_stem))

        scored_records: list[tuple[float, Record]] = []

        for rec in all_records:
            score = 0.0
            title_folded = fold(rec.title)
            raw_folded = fold(rec.raw_text or "")

            # 1. Точное вхождение всей фразы
            if clean_query in title_folded:
                score += 5.0
            elif clean_query in raw_folded:
                score += 3.0

            # 2. Пословное совпадение и стемминг (title и raw_text)
            title_words = extract_keywords(title_folded)
            raw_words = extract_keywords(raw_folded)
            all_text_words = title_words + raw_words
            all_text_stems = [stem(w) for w in all_text_words]

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

            # 4. Нечеткое совпадение (Levenshtein/SequenceMatcher) для опечаток
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
