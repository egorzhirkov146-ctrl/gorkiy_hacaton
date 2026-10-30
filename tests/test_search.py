import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base
from backend.repositories.record_repo import RecordRepository
from backend.repositories.search_repo import SearchRepository
from backend.schemas.record import RecordCreate, RecordType


@pytest.fixture
def search_repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    rec_repo = RecordRepository(session)
    rec_repo.create(RecordCreate(type=RecordType.task, title="Подготовить презентацию для руководства", raw_text="сделать слайды"))
    rec_repo.create(RecordCreate(type=RecordType.meeting, title="Встреча с Иваном по партнерству", raw_text="обсудить сотрудничество"))
    rec_repo.create(RecordCreate(type=RecordType.task, title="Согласовать договор с контрагентом", raw_text="проверить юристов"))
    rec_repo.create(RecordCreate(type=RecordType.meeting, title="Встреча с дизайнером", raw_text="макеты интерфейса"))
    rec_repo.create(RecordCreate(type=RecordType.task, title="Купить авиабилеты в Москву"))

    repo = SearchRepository(session)
    yield repo
    session.close()


def test_search_presentation(search_repo):
    results = search_repo.search("презентация")
    assert len(results) > 0
    assert "презентацию" in results[0].title.lower()


def test_search_presentation_synonym_slides(search_repo):
    results = search_repo.search("слайды")
    assert len(results) > 0
    assert "презентацию" in results[0].title.lower() or "слайды" in (results[0].raw_text or "").lower()


def test_search_ivan_meeting(search_repo):
    results = search_repo.search("Иван")
    assert len(results) > 0
    assert "иваном" in results[0].title.lower()


def test_search_contract_variations(search_repo):
    # Тест падежной формы "по договору"
    results = search_repo.search("по договору")
    assert len(results) > 0
    assert "договор" in results[0].title.lower()

    # Тест синонима "контракт"
    syn_results = search_repo.search("контракт")
    assert len(syn_results) > 0
    assert "договор" in syn_results[0].title.lower()


def test_search_tickets_fuzzy(search_repo):
    results = search_repo.search("билеты")
    assert len(results) > 0
    assert "авиабилеты" in results[0].title.lower()


def test_search_no_results(search_repo):
    results = search_repo.search("несуществующий объект")
    assert len(results) == 0


def test_search_reverse_and_bidirectional_synonyms(search_repo):
    # Поиск по синониму "макет" находит встречу с дизайнером
    res_design = search_repo.search("макеты")
    assert len(res_design) > 0
    assert "дизайнер" in res_design[0].title.lower()

    # Поиск по синониму "соглашение" находит задачу по договору
    res_agree = search_repo.search("соглашение")
    assert len(res_agree) > 0
    assert "договор" in res_agree[0].title.lower()

    # Поиск по синониму "поезд" находит билеты
    res_train = search_repo.search("поезд")
    assert len(res_train) > 0
    assert "билет" in res_train[0].title.lower()

    # Поиск по синониму "доклад" находит презентацию
    res_talk = search_repo.search("доклад")
    assert len(res_talk) > 0
    assert "презентаци" in res_talk[0].title.lower()


def test_search_yo_folding_and_expanded_synonyms(search_repo):
    # Тест на букву "ё" и "е": "отчёт" vs "отчет"
    # Добавим запись с буквой ё
    from backend.schemas.record import RecordCreate, RecordType
    search_repo.rec_repo = RecordRepository(search_repo.db)
    search_repo.rec_repo.create(RecordCreate(type=RecordType.task, title="Подготовить годовой отчёт"))
    search_repo.rec_repo.create(RecordCreate(type=RecordType.meeting, title="Приём у врача кардиолога"))

    # Поиск без ё должен найти запись с буквой ё
    res_report = search_repo.search("отчет")
    assert len(res_report) > 0
    assert "отчёт" in res_report[0].title.lower()

    # Поиск синонима доктора "поликлиника" должен найти встречу с врачом
    res_doctor = search_repo.search("поликлиника")
    assert len(res_doctor) > 0
    assert "врача" in res_doctor[0].title.lower()


