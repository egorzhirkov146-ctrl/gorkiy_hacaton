"""Необязательный семантический поиск через sentence-transformers.

Модуль включается переменной окружения SEARCH_EMBEDDINGS=1 и требует пакетов
из requirements-search.txt. Без них поиск работает только на FTS5, а функция
get_default_embedder возвращает None.
"""
from __future__ import annotations

import hashlib
import logging
import math
from array import array
from functools import lru_cache
from typing import Optional, Protocol, Sequence

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class SearchSettings(BaseSettings):
    """Настройки поиска читаются из того же файла .env, что и backend.config."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    search_embeddings: bool = False
    # rubert-tiny2 весит около 120 МБ и обучена на русском языке.
    embedding_model: str = "cointegrated/rubert-tiny2"
    # Минимальное косинусное сходство, ниже которого запись не считается похожей.
    embedding_min_score: float = 0.45


class Embedder(Protocol):
    """Любой объект, который превращает тексты в нормированные векторы."""

    model_name: str

    def encode(self, texts: Sequence[str]) -> "list[list[float]]": ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]):
        return self._model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)


@lru_cache(maxsize=1)
def get_default_embedder() -> Optional[Embedder]:
    settings = SearchSettings()
    if not settings.search_embeddings:
        return None
    try:
        return SentenceTransformerEmbedder(settings.embedding_model)
    except Exception as exc:  # нет пакета, нет сети для загрузки модели и т. п.
        log.warning("Семантический поиск выключен: %s", exc)
        return None


def record_text(title: str, raw_text: Optional[str]) -> str:
    """Текст, по которому строится вектор записи."""
    if raw_text and raw_text.strip() and raw_text.strip().lower() != title.strip().lower():
        return f"{title}. {raw_text}"
    return title


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize(vector: Sequence[float]) -> list[float]:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values]


def to_bytes(vector: Sequence[float]) -> bytes:
    """Упаковывает нормированный вектор в float32 без зависимости от numpy."""
    return array("f", normalize(vector)).tobytes()


def from_bytes(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Косинусное сходство нормированных векторов равно их скалярному произведению."""
    return float(sum(x * y for x, y in zip(a, b)))
