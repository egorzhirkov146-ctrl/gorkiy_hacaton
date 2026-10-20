from typing import Optional, Literal
from pydantic import BaseModel, Field


TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Создать новую задачу или напоминание без строго фиксированного времени встречи",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Суть задачи или напоминания без временных меток и слов 'напомни', 'поставь задачу'"
                    },
                    "datetime_str": {
                        "type": "string",
                        "description": "Срок выполнения, дата или относительное время (например 'завтра в 10 утра', 'в пятницу', 'до конца недели')"
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["task", "reminder"],
                        "description": "Тип записи: task (задача) или reminder (напоминание)"
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "Оригинальная фраза пользователя"
                    }
                },
                "required": ["title", "raw_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_meeting",
            "description": "Создать встречу. ВНИМАНИЕ: для встречи ОБЯЗАТЕЛЬНО должны быть известны И дата, И точное время. Если время не указано, вызывай ask_clarification",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название или участники встречи (например 'встреча с командой', 'встреча с дизайнером')"
                    },
                    "datetime_str": {
                        "type": "string",
                        "description": "Дата и точное время встречи (например 'завтра в 15:00', 'в четверг в 11:00')"
                    },
                    "raw_text": {
                        "type": "string",
                        "description": "Оригинальная фраза пользователя"
                    }
                },
                "required": ["title", "datetime_str", "raw_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "Получить список событий, встреч или задач за указанный период",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "this_week", "next_week", "all", "custom"],
                        "description": "Период выборки событий"
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["all", "task", "meeting", "reminder"],
                        "description": "Фильтр по типу: all (все), task (только задачи), meeting (только встречи)"
                    },
                    "from_datetime": {
                        "type": "string",
                        "description": "Начало интервала в формате ISO (если применимо)"
                    },
                    "to_datetime": {
                        "type": "string",
                        "description": "Конец интервала в формате ISO (если применимо)"
                    }
                },
                "required": ["period"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "Поиск ранее созданных задач и встреч по ключевым словам или смыслу",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос (например 'презентация', 'Иван', 'договор')"
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["all", "task", "meeting", "reminder"],
                        "description": "Фильтр по типу записи"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "Задать пользователю уточняющий вопрос, если для выполнения действия не хватает обязательных данных (например у встречи нет точного времени)",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Вежливый вопрос пользователю (например 'На какое время поставить встречу?')"
                    },
                    "missing_field": {
                        "type": "string",
                        "enum": ["time", "date", "title", "confirmation"],
                        "description": "Какое поле отсутствует"
                    },
                    "pending_action": {
                        "type": "string",
                        "description": "Какое действие планировалось (например 'create_meeting')"
                    },
                    "partial_data": {
                        "type": "object",
                        "description": "Уже извлеченные параметры (например title, date)",
                        "additionalProperties": True
                    }
                },
                "required": ["question", "missing_field"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Изменить или перенести ранее созданную задачу или встречу (в том числе по контексту 'перенеси её на завтра')",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_query": {
                        "type": "string",
                        "description": "Название или ссылка на событие из контекста (например 'её', 'встреча с дизайнером', 'презентация')"
                    },
                    "new_datetime_str": {
                        "type": "string",
                        "description": "Новая дата или время (например 'завтра', 'в 16:00')"
                    },
                    "new_title": {
                        "type": "string",
                        "description": "Новое название если требуется изменить"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done", "cancelled"],
                        "description": "Новый статус записи"
                    }
                },
                "required": ["target_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_event",
            "description": "Отметить задачу или встречу как выполненную",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_query": {
                        "type": "string",
                        "description": "Название или ссылка на событие ('задача по отчету', 'её')"
                    }
                },
                "required": ["target_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Удалить задачу или встречу",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_query": {
                        "type": "string",
                        "description": "Название или ссылка на удаляемое событие"
                    }
                },
                "required": ["target_query"]
            }
        }
    }
]


class CreateTaskArgs(BaseModel):
    title: str = Field(..., min_length=1)
    datetime_str: Optional[str] = None
    record_type: Literal["task", "reminder"] = "task"
    raw_text: str


class CreateMeetingArgs(BaseModel):
    title: str = Field(..., min_length=1)
    datetime_str: str = Field(..., min_length=1)
    raw_text: str


class ListEventsArgs(BaseModel):
    period: Literal["today", "tomorrow", "this_week", "next_week", "all", "custom"]
    record_type: Literal["all", "task", "meeting", "reminder"] = "all"
    from_datetime: Optional[str] = None
    to_datetime: Optional[str] = None


class SearchEventsArgs(BaseModel):
    query: str = Field(..., min_length=1)
    record_type: Literal["all", "task", "meeting", "reminder"] = "all"


class AskClarificationArgs(BaseModel):
    question: str = Field(..., min_length=1)
    missing_field: Literal["time", "date", "title", "confirmation"]
    pending_action: Optional[str] = None
    partial_data: Optional[dict] = None


class UpdateEventArgs(BaseModel):
    target_query: str = Field(..., min_length=1)
    new_datetime_str: Optional[str] = None
    new_title: Optional[str] = None
    status: Optional[Literal["pending", "done", "cancelled"]] = None


class CompleteEventArgs(BaseModel):
    target_query: str = Field(..., min_length=1)


class DeleteEventArgs(BaseModel):
    target_query: str = Field(..., min_length=1)
