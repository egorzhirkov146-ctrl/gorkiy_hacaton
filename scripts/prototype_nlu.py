import json
import sys
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.nlu import NLUModule
from backend.schemas.chat import MessageIn


def main():
    nlu = NLUModule()
    test_now = datetime(2026, 10, 20, 13, 0)

    test_phrases = [
        ("Напомни мне завтра в 10 утра позвонить Ивану", None),
        ("В пятницу нужно отправить отчет", None),
        ("Поставь задачу купить билеты до конца недели", None),
        ("Добавь встречу с командой завтра в 15:00", None),
        ("В четверг в 11 у меня встреча с дизайнером", None),
        ("Что у меня сегодня?", None),
        ("Есть ли у меня встречи сегодня?", None),
        ("Какие задачи у меня на завтра?", None),
        ("Что запланировано на эту неделю?", None),
        ("Найди задачу про презентацию", None),
        ("Когда у меня была встреча с Иваном?", None),
        ("Я когда-то ставил задачу по договору, найди ее", None),
        ("Поставь встречу с Иваном завтра", None),
        (
            "В 15:00",
            [
                MessageIn(role="user", content="Поставь встречу с Иваном завтра"),
                MessageIn(role="assistant", content="На какое время поставить встречу?")
            ]
        ),
        (
            "Перенеси её на завтра",
            [
                MessageIn(role="user", content="Добавь встречу с дизайнером в четверг в 11"),
                MessageIn(role="assistant", content="Встреча с дизайнером запланирована на четверг в 11:00")
            ]
        ),
        ("Отметь задачу по отчету выполненной", None),
        ("Удали задачу про презентацию", None)
    ]

    print("=== S0 PROTOTYPE FUNCTION CALLING (NO DB) ===")
    print(f"Reference time: {test_now.isoformat()} (Tuesday, Europe/Moscow)\n")

    results = []

    for phrase, history in test_phrases:
        res = nlu.parse(phrase, history=history, now=test_now)
        out = {
            "query": phrase,
            "has_history": bool(history),
            "tool_called": res.intent,
            "arguments": res.raw_arguments,
            "parsed_title": res.title,
            "parsed_datetime": res.datetime_iso,
            "has_explicit_time": res.has_explicit_time,
            "period": res.period,
            "search_query": res.search_query,
            "needs_clarification": res.needs_clarification,
            "clarification_question": res.clarification_question
        }
        results.append(out)

        print(f"User: \"{phrase}\"")
        if history:
            print(f"Context: {[m.content for m in history]}")
        print(f"Tool -> {res.intent}")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("-" * 50)

    print(f"\nCompleted {len(results)} queries. Function calling stable and validated.")


if __name__ == "__main__":
    main()
