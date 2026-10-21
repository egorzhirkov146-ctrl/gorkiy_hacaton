"""Полнотекстовый индекс SQLite FTS5 по полям title и raw_text таблицы records.

Индекс хранит нормализованную копию текста, в которой "ё" заменена на "е",
потому что токенизатор unicode61 считает эти буквы разными. Три триггера
обновляют индекс при INSERT, UPDATE и DELETE, так что любой код, который
пишет в records, держит индекс в актуальном состоянии без участия репозитория.
"""
from __future__ import annotations

import difflib
import weakref
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from backend.storage.text import fold, keywords, stem, synonym_stems

FTS_TABLE = "records_fts"
VOCAB_TABLE = "records_fts_vocab"

# Вес совпадения в заголовке в 10 раз больше веса совпадения в исходной фразе.
TITLE_WEIGHT = 10.0
RAW_TEXT_WEIGHT = 1.0
# Порог похожести слов для опечаток ("презинтация" -> "презентацию").
FUZZY_RATIO = 0.8

# SQLite не умеет переводить кириллицу в нижний регистр в SQL, поэтому триггер
# заменяет только "ё" на "е", а регистр приводит токенизатор unicode61.
_NORM = "replace(replace(coalesce({x}, ''), 'ё', 'е'), 'Ё', 'Е')"
_INSERT_ROW = (
    f"INSERT INTO {FTS_TABLE}(rowid, title, raw_text) "
    f"VALUES (new.id, {_NORM.format(x='new.title')}, {_NORM.format(x='new.raw_text')});"
)

_DDL = {
    FTS_TABLE: f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
            title, raw_text,
            tokenize='unicode61',
            prefix='2 3 4'
        )
    """,
    VOCAB_TABLE: f"CREATE VIRTUAL TABLE IF NOT EXISTS {VOCAB_TABLE} USING fts5vocab({FTS_TABLE}, 'row')",
    "records_fts_ai": f"""
        CREATE TRIGGER IF NOT EXISTS records_fts_ai AFTER INSERT ON records BEGIN
            {_INSERT_ROW}
        END
    """,
    "records_fts_ad": f"""
        CREATE TRIGGER IF NOT EXISTS records_fts_ad AFTER DELETE ON records BEGIN
            DELETE FROM {FTS_TABLE} WHERE rowid = old.id;
        END
    """,
    "records_fts_au": f"""
        CREATE TRIGGER IF NOT EXISTS records_fts_au AFTER UPDATE OF title, raw_text ON records BEGIN
            DELETE FROM {FTS_TABLE} WHERE rowid = old.id;
            {_INSERT_ROW}
        END
    """,
}

# Движки, для которых индекс уже проверен в этом процессе.
_ready_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def _existing_objects(conn: Connection) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"))
    return {r[0] for r in rows}


def ensure_fts(conn: Connection) -> bool:
    """Создает недостающие объекты FTS и перестраивает индекс, если он отстал.

    Возвращает True, если функция что-то изменила в базе. Индекс отстает,
    когда записи попали в records до создания триггеров, например в базу
    из ранней версии проекта.
    """
    existing = _existing_objects(conn)
    if "records" not in existing:
        return False
    changed = False
    for name, ddl in _DDL.items():
        if name not in existing:
            conn.exec_driver_sql(ddl)
            changed = True
    indexed = conn.execute(text(f"SELECT count(*) FROM {FTS_TABLE}")).scalar_one()
    total = conn.execute(text("SELECT count(*) FROM records")).scalar_one()
    if indexed != total:
        rebuild(conn)
        changed = True
    return changed


def rebuild(conn: Connection) -> None:
    """Перестраивает индекс целиком по текущему содержимому records."""
    conn.exec_driver_sql(f"DELETE FROM {FTS_TABLE}")
    conn.exec_driver_sql(
        f"INSERT INTO {FTS_TABLE}(rowid, title, raw_text) SELECT id, "
        f"{_NORM.format(x='title')}, {_NORM.format(x='raw_text')} FROM records"
    )


def integrity_check(conn: Connection) -> None:
    """Проверяет внутреннюю структуру индекса, при повреждении SQLite бросает ошибку."""
    conn.exec_driver_sql(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES ('integrity-check')")


def unsynced_rows(conn: Connection) -> int:
    """Число записей без строки в индексе плюс число строк индекса без записи."""
    missing = conn.execute(
        text(f"SELECT count(*) FROM records r WHERE NOT EXISTS (SELECT 1 FROM {FTS_TABLE} f WHERE f.rowid = r.id)")
    ).scalar_one()
    orphan = conn.execute(
        text(f"SELECT count(*) FROM {FTS_TABLE} f WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.id = f.rowid)")
    ).scalar_one()
    return missing + orphan


def create_fts_listener(target, connection: Connection, **kw) -> None:
    """Обработчик события after_create таблицы records."""
    if connection.dialect.name == "sqlite":
        ensure_fts(connection)


def ensure_ready(session: Session) -> None:
    """Один раз на движок проверяет индекс перед первым поиском."""
    engine = session.get_bind()
    if engine.dialect.name != "sqlite" or engine in _ready_engines:
        return
    if ensure_fts(session.connection()):
        session.commit()
    _ready_engines.add(engine)


def forget_engine(engine: Engine) -> None:
    """Сбрасывает отметку о проверке, нужно после ручной правки схемы."""
    _ready_engines.discard(engine)


@dataclass(frozen=True)
class QueryPlan:
    """Разобранный запрос: по одной группе вариантов на каждое слово."""

    words: tuple[str, ...]
    groups: tuple[tuple[str, ...], ...]

    def match_expression(self) -> str | None:
        terms = sorted({t for g in self.groups for t in g})
        if not terms:
            return None
        # Каждый вариант идет в кавычках со звездочкой, то есть как префикс.
        # Кавычки защищают от синтаксиса FTS5 (OR, NEAR, двоеточие) в запросе.
        return " OR ".join(f'"{t}"*' for t in terms)


def _vocabulary(conn: Connection) -> list[str]:
    return [r[0] for r in conn.execute(text(f"SELECT term FROM {VOCAB_TABLE}"))]


def build_query(conn: Connection, query: str) -> QueryPlan:
    """Превращает фразу пользователя в набор префиксов для MATCH.

    Для каждого значимого слова запрос берет основу, основы синонимов, а также
    слова словаря индекса, которые содержат основу внутри ("билет" и
    "авиабилеты") или похожи на слово запроса с учетом опечатки.
    """
    query_words = keywords(query)
    vocab: list[str] | None = None
    groups = []
    for word in query_words:
        variants = {fold(s) for s in synonym_stems(stem(word))}
        variants.add(fold(stem(word)))
        if vocab is None:
            vocab = _vocabulary(conn)
        folded_word = fold(word)
        for term in vocab:
            if any(len(v) >= 4 and v in term and not term.startswith(v) for v in variants):
                variants.add(term)
            elif len(folded_word) >= 4 and difflib.SequenceMatcher(None, folded_word, term).ratio() >= FUZZY_RATIO:
                variants.add(term)
        groups.append(tuple(sorted(v for v in variants if v)))
    return QueryPlan(words=tuple(query_words), groups=tuple(groups))
