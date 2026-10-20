import sys
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.nlu import NLUModule
from backend.services.dialog_service import DialogService
from backend.schemas.chat import ChatRequest, MessageIn


def run_demo():
    dialog = DialogService()
    now = datetime(2026, 10, 20, 13, 0)

    print("=" * 60)
    print("ДЕМО ГОЛОСОВОГО АССИСТЕНТА: NLU И ДИАЛОГОВЫЕ СЦЕНАРИИ")
    print(f"Текущая точка времени: Вторник, {now.strftime('%d.%m.%Y %H:%M')} (Europe/Moscow)")
    print("=" * 60)

    scenarios = [
        {
            "category": "СЦЕНАРИЙ 1: Создание задач и напоминаний",
            "steps": [
                {"input": "Напомни мне завтра в 10 утра позвонить Ивану", "history": []},
                {"input": "В пятницу нужно отправить отчет", "history": []},
                {"input": "Поставь задачу купить билеты до конца недели", "history": []},
            ]
        },
        {
            "category": "СЦЕНАРИЙ 2: Создание встреч (с явным временем)",
            "steps": [
                {"input": "Добавь встречу с командой завтра в 15:00", "history": []},
                {"input": "В четверг в 11 у меня встреча с дизайнером", "history": []},
            ]
        },
        {
            "category": "СЦЕНАРИЙ 3: Уточняющий диалог (встреча без времени)",
            "steps": [
                {"input": "Поставь встречу с Иваном завтра", "history": []},
                {
                    "input": "В 15:00",
                    "history": [
                        MessageIn(role="user", content="Поставь встречу с Иваном завтра"),
                        MessageIn(role="assistant", content="На какое время поставить встречу?")
                    ]
                }
            ]
        },
        {
            "category": "СЦЕНАРИЙ 4: Получение расписания и планов",
            "steps": [
                {"input": "Что у меня сегодня?", "history": []},
                {"input": "Есть ли у меня встречи сегодня?", "history": []},
                {"input": "Какие задачи у меня на завтра?", "history": []},
                {"input": "Что запланировано на эту неделю?", "history": []},
            ]
        },
        {
            "category": "СЦЕНАРИЙ 5: Поиск старых записей",
            "steps": [
                {"input": "Найди задачу про презентацию", "history": []},
                {"input": "Когда у меня была встреча с Иваном?", "history": []},
                {"input": "Я когда-то ставил задачу по договору, найди ее", "history": []},
            ]
        },
        {
            "category": "СЦЕНАРИЙ 6: Контекстное управление (перенос и отметка)",
            "steps": [
                {
                    "input": "Перенеси её на завтра",
                    "history": [
                        MessageIn(role="user", content="В четверг в 11 у меня встреча с дизайнером"),
                        MessageIn(role="assistant", content="Запланировал: Встреча с дизайнером на 22.10 в 11:00.")
                    ]
                },
                {"input": "Отметь задачу по отчету выполненной", "history": []},
                {"input": "Удали задачу про презентацию", "history": []}
            ]
        }
    ]

    for sc in scenarios:
        print(f"\n>>> {sc['category']}")
        print("-" * 60)
        for step in sc["steps"]:
            req = ChatRequest(
                session_id="demo-session",
                text=step["input"],
                history=step["history"]
            )
            resp = dialog.handle(req, now=now)

            if step["history"]:
                ctx_summary = " -> ".join([f"{m.role}: '{m.content}'" for m in step["history"]])
                print(f"[Контекст]: {ctx_summary}")

            print(f"[Пользователь]: \"{step['input']}\"")
            print(f"[Ассистент]:   \"{resp.reply_text}\"")
            print(f"[Action]:       type={resp.action.type}, status={resp.action.status}, needs_clarification={resp.needs_clarification}")
            print()

    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
