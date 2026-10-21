from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.repositories.record_repo import RecordRepository
from backend.repositories.search_repo import SearchRepository
from backend.storage import init_storage
from backend.storage.demo_data import load_demo_data

# Среда, 21 октября 2026 года, полдень: от этого момента считаются демо-данные.
NOW = datetime(2026, 10, 21, 12, 0)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    init_storage(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with sessionmaker(bind=engine, autoflush=False)() as s:
        yield s


@pytest.fixture
def repo(session) -> RecordRepository:
    return RecordRepository(session)


@pytest.fixture
def search(session) -> SearchRepository:
    # Эмбеддинги выключены явно, чтобы тесты не зависели от .env и сети.
    return SearchRepository(session, embedder=None)


@pytest.fixture
def demo_session(session, now):
    load_demo_data(session, now=now)
    return session
