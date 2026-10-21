"""Поиск FTS5: формулировки из задания, падежи, синонимы, опечатки, синхронность индекса."""
import pytest

from backend.schemas.record import RecordCreate, RecordStatus, RecordType, RecordUpdate
from backend.storage.text import keywords, stem


def first_title(search, query, **kw):
    hits = search.search(query, **kw)
    return hits[0].title if hits else None


# Запросы из раздела "Поиск старых задач и событий" задания и близкие по смыслу формулировки.
@pytest.mark.parametrize(
    "query, expected",
    [
        ("Найди задачу про презентацию", "Подготовить презентацию для инвесторов"),
        ("Когда у меня была встреча с Иваном?", "Встреча с Иваном по партнерству"),
        ("Я когда-то ставил задачу по договору, найди ее", "Согласовать договор с подрядчиком"),
        # Падежные формы.
        ("презентации", "Подготовить презентацию для инвесторов"),
        ("договора", "Согласовать договор с подрядчиком"),
        ("с Иваном", "Встреча с Иваном по партнерству"),
        # Синонимы, то есть запросы без общих слов с записью.
        ("слайды для инвесторов", "Подготовить презентацию для инвесторов"),
        ("контракт", "Согласовать договор с подрядчиком"),
        ("соглашение с подрядчиком", "Согласовать договор с подрядчиком"),
        ("доктор", "Записаться к стоматологу"),
        ("поезд", "Купить билеты"),
        # Опечатки.
        ("презинтация", "Подготовить презентацию для инвесторов"),
        ("догавор", "Согласовать договор с подрядчиком"),
        # Буква ё и регистр.
        ("ОТЧЁТ", "Отправить отчет"),
    ],
)
def test_natural_queries(demo_session, search, query, expected):
    assert first_title(search, query) == expected


def test_title_match_ranks_above_raw_text_match(session, repo, search):
    repo.create(RecordCreate(type=RecordType.task, title="Купить продукты", raw_text="молоко и отчет для мамы"))
    repo.create(RecordCreate(type=RecordType.task, title="Отчет по продажам"))
    assert first_title(search, "отчет") == "Отчет по продажам"


def test_exact_word_ranks_above_synonym(session, repo, search):
    repo.create(RecordCreate(type=RecordType.task, title="Подготовить доклад"))
    repo.create(RecordCreate(type=RecordType.task, title="Подготовить презентацию"))
    assert first_title(search, "презентация") == "Подготовить презентацию"


def test_more_query_words_rank_higher(demo_session, search):
    titles = [r.title for r in search.search("встреча с Иваном")]
    assert titles[0] == "Встреча с Иваном по партнерству"
    assert "Позвонить Ивану" in titles


def test_no_results(demo_session, search):
    assert search.search("несуществующий объект") == []
    assert search.search("") == []
    assert search.search("   ") == []


@pytest.mark.parametrize("query", ['"', "*", "OR", "NEAR(", "title:отчет", "a AND NOT b", "'; DROP TABLE records; --"])
def test_fts_syntax_in_query_is_safe(demo_session, search, query):
    # Спецсимволы FTS5 и SQL в запросе не должны ломать поиск.
    search.search(query)
    assert search.search("отчет")


def test_filters_by_user_type_and_status(demo_session, search):
    assert all(r.user_id == 1 for r in search.search("Иван"))
    assert [r.title for r in search.search("Иван", user_id=2)] == ["Встреча с Иваном (чужой календарь)"]
    reminders = search.search("Иван", record_type=RecordType.reminder)
    assert [r.title for r in reminders] == ["Позвонить Ивану"]
    pending = search.search("презентация", status=RecordStatus.pending)
    assert all(r.status == RecordStatus.pending for r in pending)
    assert "Подготовить презентацию для инвесторов" not in [r.title for r in pending]


def test_index_follows_update_and_delete(session, repo, search):
    rec = repo.create(RecordCreate(type=RecordType.task, title="Купить молоко"))
    assert first_title(search, "молоко") == "Купить молоко"

    repo.update(rec.id, RecordUpdate(title="Купить хлеб"))
    assert search.search("молоко") == []
    assert first_title(search, "хлеб") == "Купить хлеб"

    repo.delete(rec.id)
    assert search.search("хлеб") == []


def test_limit(demo_session, search):
    assert len(search.search("встреча", limit=2)) == 2


def test_stemmer_and_keywords():
    assert stem("договору") == "договор"
    assert stem("презентацию") == "презентаци"
    assert stem("Иваном") == "иван"
    # Основа короче трех букв не получается, поэтому короткое слово остается целым.
    assert stem("чай") == "чай"
    assert keywords("Найди задачу про презентацию") == ["презентацию"]
    # Запрос только из служебных слов не превращается в пустой.
    assert keywords("встреча") == ["встреча"]


def test_yo_in_stored_text(session, repo, search):
    # Токенизатор FTS5 различает "ё" и "е", поэтому триггер хранит текст с заменой "ё".
    repo.create(RecordCreate(type=RecordType.task, title="Сдать квартальный отчёт", raw_text="Ёлка в офисе"))
    assert first_title(search, "отчет") == "Сдать квартальный отчёт"
    assert first_title(search, "ёлка") == "Сдать квартальный отчёт"
