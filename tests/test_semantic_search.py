"""Семантический поиск на эмбеддингах (бонус S2).

Первая группа тестов использует детерминированный учебный кодировщик, чтобы
проверить хранение векторов, их обновление и объединение с FTS5 без загрузки
модели. Последний тест запускает настоящую модель, и он включается
переменной RUN_MODEL_TESTS=1.
"""
import os

import pytest
from sqlalchemy import func, select

from backend.models.record_embedding import RecordEmbedding
from backend.repositories.search_repo import SearchRepository
from backend.schemas.record import RecordCreate, RecordType, RecordUpdate
from backend.storage.text import stem, words

# Учебное пространство смыслов: каждое измерение соответствует одной теме.
CONCEPTS = {
    "health": {"стоматолог", "зуб", "врач", "доктор", "болит", "клиник"},
    "money": {"оплат", "счет", "аренд", "деньг", "заплат", "платеж"},
    "travel": {"билет", "поезд", "самолет", "поездк", "командировк"},
    "family": {"мам", "пап", "рождени", "торт", "подарок"},
}


class ConceptEmbedder:
    model_name = "test-concepts"

    def encode(self, texts):
        vectors = []
        for t in texts:
            stems = [stem(w) for w in words(t)]
            vectors.append(
                [float(sum(any(s.startswith(c) for c in group) for s in stems)) for group in CONCEPTS.values()]
                + [0.01]
            )
        return vectors


@pytest.fixture
def semantic(session):
    return SearchRepository(session, embedder=ConceptEmbedder())


def test_semantic_finds_record_without_shared_words(demo_session, semantic):
    # В записи "Записаться к стоматологу" нет слов "зуб" и "болит".
    hits = semantic.search_scored("у меня болит зуб")
    assert hits[0].record.title == "Записаться к стоматологу"
    assert "semantic" in hits[0].sources


def test_hybrid_merges_sources(demo_session, semantic):
    hits = semantic.search_scored("оплатить аренду")
    assert hits[0].record.title == "Оплатить аренду квартиры"
    assert hits[0].sources == {"fts", "semantic"}


def test_embeddings_are_cached_and_refreshed(session, repo, semantic):
    rec = repo.create(RecordCreate(type=RecordType.task, title="Купить билеты на поезд"))
    assert semantic.sync_embeddings() == 1
    assert semantic.sync_embeddings() == 0  # текст не менялся, вектор не пересчитывается

    repo.update(rec.id, RecordUpdate(title="Купить подарок маме"))
    assert semantic.sync_embeddings() == 1
    assert semantic.search_scored("день рождения мамы")[0].record.id == rec.id

    repo.delete(rec.id)
    assert session.scalar(select(func.count()).select_from(RecordEmbedding)) == 0


def test_semantic_respects_user_and_type(demo_session, semantic):
    assert all(h.record.user_id == 1 for h in semantic.search_scored("врач"))
    assert semantic.search_scored("врач", record_type=RecordType.meeting) == []


_cache = {}


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1", reason="включается RUN_MODEL_TESTS=1")
@pytest.mark.parametrize(
    "query, expected",
    [
        ("когда я собирался к зубному", "Записаться к стоматологу"),
        ("заплатить за жилье", "Оплатить аренду квартиры"),
        ("подготовка слайдов", "Подготовить презентацию для инвесторов"),
        ("найм программиста", "Собеседование с бэкенд-разработчиком"),
    ],
)
def test_real_model(demo_session, query, expected):
    pytest.importorskip("sentence_transformers")
    from backend.storage.embeddings import SearchSettings, SentenceTransformerEmbedder

    name = SearchSettings().embedding_model
    if name not in _cache:
        _cache[name] = SentenceTransformerEmbedder(name)
    titles = [r.title for r in SearchRepository(demo_session, embedder=_cache[name]).search(query, limit=3)]
    assert expected in titles, titles
