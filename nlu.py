from datetime import datetime
from typing import Optional

from backend.nlu import (
    NLUModule,
    NLUResult,
    RussianDateParser,
    ParsedDateTime,
    build_system_prompt,
    TOOLS_DEFINITIONS,
    LLMClient,
)
from backend.schemas.chat import MessageIn

_default_nlu = NLUModule()


def parse_user_intent(
    text: str,
    history: Optional[list[MessageIn]] = None,
    now: Optional[datetime] = None,
) -> NLUResult:
    """Удобная функция для быстрого разбора намерения пользователя (для интеграции тимлидом)."""
    return _default_nlu.parse(text=text, history=history, now=now)


__all__ = [
    "parse_user_intent",
    "NLUModule",
    "NLUResult",
    "RussianDateParser",
    "ParsedDateTime",
    "build_system_prompt",
    "TOOLS_DEFINITIONS",
    "LLMClient",
]
