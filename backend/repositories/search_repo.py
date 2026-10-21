from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models.record import Record
from backend.models.record_embedding import RecordEmbedding
from backend.schemas.record import RecordStatus, RecordType
from backend.storage import embeddings as emb
from backend.storage import fts
from backend.storage.text import fold, stem, words

# Константа метода Reciprocal Rank Fusion: запись на месте k получает 1 / (RRF_K + k).
RRF_K = 60
# Сколько кандидатов брать из каждого источника на одно место в выдаче.
CANDIDATES_PER_SLOT = 5

_DEFAULT = object()


@dataclass
class SearchHit:
    record: Record
    score: float
    # Источники, которые нашли запись: "fts" и (или) "semantic".
    sources: set[str] = field(default_factory=set)


class SearchRepository:
    """Поиск записей по фразе пользователя.

    Основной источник это FTS5 по title и raw_text с учетом окончаний,
    синонимов и опечаток. Если подключены эмбеддинги, второй источник ищет
    близкие по смыслу записи, и два списка объединяются методом Reciprocal
    Rank Fusion, который складывает величины 1 / (60 + место в списке).
    """

    def __init__(self, db: Session, embedder=_DEFAULT):
        self.db = db
        self.embedder = emb.get_default_embedder() if embedder is _DEFAULT else embedder

    def search(
        self,
        query: str,
        user_id: int = 1,
        record_type: Optional[RecordType] = None,
        limit: int = 10,
        status: Optional[RecordStatus] = None,
    ) -> list[Record]:
        return [h.record for h in self.search_scored(query, user_id, record_type, limit, status)]

    def search_scored(
        self,
        query: str,
        user_id: int = 1,
        record_type: Optional[RecordType] = None,
        limit: int = 10,
        status: Optional[RecordStatus] = None,
    ) -> list[SearchHit]:
        if not query or not query.strip() or limit <= 0:
            return []
        fts.ensure_ready(self.db)
        pool = limit * CANDIDATES_PER_SLOT

        lexical = self._fts_search(query, user_id, record_type, status, pool)
        semantic = (
            self._semantic_search(query, user_id, record_type, status, pool) if self.embedder else []
        )
        if not semantic:
            return lexical[:limit]
        return self._fuse(lexical, semantic)[:limit]

    # ---- полнотекстовый поиск ---------------------------------------------

    def _fts_search(
        self,
        query: str,
        user_id: int,
        record_type: Optional[RecordType],
        status: Optional[RecordStatus],
        pool: int,
    ) -> list[SearchHit]:
        plan = fts.build_query(self.db.connection(), query)
        match = plan.match_expression()
        if match is None:
            return []
        sql = f"""
            SELECT r.id, bm25({fts.FTS_TABLE}, :tw, :rw) AS rank
            FROM {fts.FTS_TABLE}
            JOIN records r ON r.id = {fts.FTS_TABLE}.rowid
            WHERE {fts.FTS_TABLE} MATCH :match AND r.user_id = :user_id
        """
        params = {"match": match, "user_id": user_id, "tw": fts.TITLE_WEIGHT, "rw": fts.RAW_TEXT_WEIGHT}
        if record_type:
            sql += " AND r.type = :type"
            params["type"] = record_type.value
        if status:
            sql += " AND r.status = :status"
            params["status"] = status.value
        sql += " ORDER BY rank LIMIT :pool"
        params["pool"] = pool
        rows = self.db.execute(text(sql), params).all()
        if not rows:
            return []

        records = self._load([r.id for r in rows])
        exact_stems = [fold(stem(w)) for w in plan.words]
        hits = []
        for row in rows:
            rec = records[row.id]
            tokens = [fold(t) for t in words(f"{rec.title} {rec.raw_text or ''}")]
            title_tokens = {fold(t) for t in words(rec.title)}
            exact = sum(any(t.startswith(s) for t in tokens) for s in exact_stems)
            loose = sum(any(t.startswith(v) for t in tokens for v in g) for g in plan.groups)
            in_title = sum(any(t.startswith(v) for t in title_tokens for v in g) for g in plan.groups)
            # Главный вклад дают слова запроса, найденные без синонимов,
            # затем число покрытых слов, затем совпадения в заголовке и bm25.
            score = 3.0 * exact + 2.0 * loose + 1.0 * in_title + min(-row.rank, 10.0) / 10.0
            hits.append(SearchHit(rec, score, {"fts"}))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    def _load(self, ids: list[int]) -> dict[int, Record]:
        rows = self.db.scalars(select(Record).where(Record.id.in_(ids)))
        return {r.id: r for r in rows}

    # ---- семантический поиск ----------------------------------------------

    def _semantic_search(
        self,
        query: str,
        user_id: int,
        record_type: Optional[RecordType],
        status: Optional[RecordStatus],
        pool: int,
    ) -> list[SearchHit]:
        self.sync_embeddings(user_id)
        stmt = (
            select(Record, RecordEmbedding.vector)
            .join(RecordEmbedding, RecordEmbedding.record_id == Record.id)
            .where(Record.user_id == user_id, RecordEmbedding.model == self.embedder.model_name)
        )
        if record_type:
            stmt = stmt.where(Record.type == record_type)
        if status:
            stmt = stmt.where(Record.status == status)
        query_vec = emb.normalize(self.embedder.encode([query])[0])
        min_score = emb.SearchSettings().embedding_min_score
        hits = []
        for rec, blob in self.db.execute(stmt):
            score = emb.cosine(query_vec, emb.from_bytes(blob))
            if score >= min_score:
                hits.append(SearchHit(rec, score, {"semantic"}))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:pool]

    def sync_embeddings(self, user_id: Optional[int] = None) -> int:
        """Считает векторы для новых и измененных записей, возвращает их число.

        Векторы считаются лениво перед поиском, поэтому создание записи не ждет
        модель, а записи, которые попали в базу через сиды, тоже получают векторы.
        """
        if not self.embedder:
            return 0
        stmt = select(Record, RecordEmbedding).outerjoin(
            RecordEmbedding, RecordEmbedding.record_id == Record.id
        )
        if user_id is not None:
            stmt = stmt.where(Record.user_id == user_id)
        stale = []
        for rec, vec in self.db.execute(stmt):
            body = emb.record_text(rec.title, rec.raw_text)
            digest = emb.text_hash(body)
            if vec is None or vec.text_hash != digest or vec.model != self.embedder.model_name:
                stale.append((rec, vec, body, digest))
        if not stale:
            return 0
        vectors = self.embedder.encode([s[2] for s in stale])
        for (rec, vec, _body, digest), vector in zip(stale, vectors):
            blob = emb.to_bytes(vector)
            if vec is None:
                vec = RecordEmbedding(record_id=rec.id)
                self.db.add(vec)
            vec.model = self.embedder.model_name
            vec.text_hash = digest
            vec.dim = len(blob) // 4
            vec.vector = blob
        self.db.commit()
        return len(stale)

    # ---- объединение ------------------------------------------------------

    @staticmethod
    def _fuse(*ranked_lists: list[SearchHit]) -> list[SearchHit]:
        fused: dict[int, SearchHit] = {}
        for hits in ranked_lists:
            for place, hit in enumerate(hits, start=1):
                item = fused.setdefault(hit.record.id, SearchHit(hit.record, 0.0, set()))
                item.score += 1.0 / (RRF_K + place)
                item.sources |= hit.sources
        return sorted(fused.values(), key=lambda h: h.score, reverse=True)
