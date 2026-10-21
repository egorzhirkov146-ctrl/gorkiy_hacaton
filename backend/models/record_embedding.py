import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class RecordEmbedding(Base):
    """Вектор записи для семантического поиска (опционально, sentence-transformers).

    Вектор лежит в отдельной таблице, чтобы основная таблица records оставалась
    легкой, а без библиотеки эмбеддингов таблица просто остается пустой.
    """

    __tablename__ = "record_embeddings"

    record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    # sha1 от title и raw_text: по нему видно, что текст изменился и вектор устарел.
    text_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # Нормированный вектор float32 в виде байтов.
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: dt.datetime.now().replace(microsecond=0)
    )
