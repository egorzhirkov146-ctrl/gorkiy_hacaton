from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.nlu.nlu import NLUModule
from backend.nlu.date_parser import RussianDateParser
from backend.schemas.chat import MessageIn, ChatRequest


@pytest.fixture
def nlu():
    return NLUModule()


@pytest.fixture
def parser():
    return RussianDateParser()


@pytest.fixture
def fixed_now():
    return datetime(2026, 10, 20, 13, 0)


@pytest.fixture
def client():
    return TestClient(app)


def test_create_task_remind_tomorrow_10am(nlu, fixed_now):
    res = nlu.parse("Напомни мне завтра в 10 утра позвонить Ивану", now=fixed_now)
    assert res.intent == "create_task"
    assert "позвонить" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 21, 10, 0)
    assert res.has_explicit_time is True
    assert res.needs_clarification is False


def test_create_task_friday_report(nlu, fixed_now):
    res = nlu.parse("В пятницу нужно отправить отчет", now=fixed_now)
    assert res.intent == "create_task"
    assert "отчет" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 23, 0, 0)
    assert res.needs_clarification is False


def test_create_task_tickets_end_of_week(nlu, fixed_now):
    res = nlu.parse("Поставь задачу купить билеты до конца недели", now=fixed_now)
    assert res.intent == "create_task"
    assert "билеты" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 25, 23, 59, 59)
    assert res.needs_clarification is False


def test_create_task_remind_half_hour(nlu, fixed_now):
    res = nlu.parse("Напомни через полчаса позвонить маме", now=fixed_now)
    assert res.intent == "create_task"
    assert "позвонить" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 20, 13, 30)
    assert res.has_explicit_time is True


def test_create_task_in_two_hours(nlu, fixed_now):
    res = nlu.parse("Поставь задачу проверить сервер через два часа", now=fixed_now)
    assert res.intent == "create_task"
    assert "проверить сервер" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 20, 15, 0)
    assert res.has_explicit_time is True


def test_create_meeting_team_tomorrow_15(nlu, fixed_now):
    res = nlu.parse("Добавь встречу с командой завтра в 15:00", now=fixed_now)
    assert res.intent == "create_meeting"
    assert "командой" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 21, 15, 0)
    assert res.has_explicit_time is True
    assert res.needs_clarification is False


def test_create_meeting_designer_thursday_11(nlu, fixed_now):
    res = nlu.parse("В четверг в 11 у меня встреча с дизайнером", now=fixed_now)
    assert res.intent == "create_meeting"
    assert "дизайнером" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 22, 11, 0)
    assert res.has_explicit_time is True
    assert res.needs_clarification is False


def test_create_meeting_friday_evening(nlu, fixed_now):
    res = nlu.parse("Запланируй встречу с инвесторами в пятницу в 18:30", now=fixed_now)
    assert res.intent == "create_meeting"
    assert "инвесторами" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 23, 18, 30)
    assert res.has_explicit_time is True


def test_meeting_without_time_triggers_clarification(nlu, fixed_now):
    res = nlu.parse("Поставь встречу с Иваном завтра", now=fixed_now)
    assert res.intent == "ask_clarification"
    assert res.needs_clarification is True
    assert res.missing_field == "time"
    assert "время" in res.clarification_question.lower()


def test_meeting_partners_friday_without_time(nlu, fixed_now):
    res = nlu.parse("Встреча с партнерами в пятницу", now=fixed_now)
    assert res.intent == "ask_clarification"
    assert res.needs_clarification is True
    assert res.missing_field == "time"


def test_meeting_client_after_tomorrow_without_time(nlu, fixed_now):
    res = nlu.parse("Добавь встречу с клиентом послезавтра", now=fixed_now)
    assert res.intent == "ask_clarification"
    assert res.needs_clarification is True
    assert res.missing_field == "time"


def test_clarification_response_resolves_meeting(nlu, fixed_now):
    history = [
        MessageIn(role="user", content="Поставь встречу с Иваном завтра"),
        MessageIn(role="assistant", content="На какое время поставить встречу?")
    ]
    res = nlu.parse("В 15:00", history=history, now=fixed_now)
    assert res.intent == "create_meeting"
    assert "иван" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 21, 15, 0)
    assert res.has_explicit_time is True
    assert res.needs_clarification is False


def test_clarification_response_11_am(nlu, fixed_now):
    history = [
        MessageIn(role="user", content="Добавь встречу с дизайнером в четверг"),
        MessageIn(role="assistant", content="На какое время поставить встречу?")
    ]
    res = nlu.parse("В 11 утра", history=history, now=fixed_now)
    assert res.intent == "create_meeting"
    assert "дизайнер" in res.title.lower()
    assert res.datetime == datetime(2026, 10, 22, 11, 0)
    assert res.has_explicit_time is True


def test_list_events_today(nlu, fixed_now):
    res = nlu.parse("Что у меня сегодня?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "today"


def test_list_events_plans_today(nlu, fixed_now):
    res = nlu.parse("Какие планы на сегодня?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "today"


def test_list_events_meetings_today(nlu, fixed_now):
    res = nlu.parse("Покажи мои встречи на сегодня", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "today"
    assert res.record_type == "meeting"


def test_list_events_have_meetings_today(nlu, fixed_now):
    res = nlu.parse("Есть ли у меня встречи сегодня?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "today"
    assert res.record_type == "meeting"


def test_list_events_tasks_tomorrow(nlu, fixed_now):
    res = nlu.parse("Какие задачи у меня на завтра?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "tomorrow"
    assert res.record_type == "task"


def test_list_events_this_week(nlu, fixed_now):
    res = nlu.parse("Что запланировано на эту неделю?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "this_week"


def test_list_events_plans_next_week(nlu, fixed_now):
    res = nlu.parse("Какие планы на следующей неделе?", now=fixed_now)
    assert res.intent == "list_events"
    assert res.period == "next_week"


def test_search_presentation(nlu, fixed_now):
    res = nlu.parse("Найди задачу про презентацию", now=fixed_now)
    assert res.intent == "search_events"
    assert "презентаци" in res.search_query.lower()


def test_search_when_was_meeting_ivan(nlu, fixed_now):
    res = nlu.parse("Когда у меня была встреча с Иваном?", now=fixed_now)
    assert res.intent == "search_events"
    assert "иван" in res.search_query.lower()


def test_search_contract_task(nlu, fixed_now):
    res = nlu.parse("Я когда-то ставил задачу по договору, найди ее", now=fixed_now)
    assert res.intent == "search_events"
    assert "договор" in res.search_query.lower()


def test_search_project_tasks(nlu, fixed_now):
    res = nlu.parse("Поищи задачи по проекту", now=fixed_now)
    assert res.intent == "search_events"
    assert "проект" in res.search_query.lower()


def test_bonus_move_event_by_context(nlu, fixed_now):
    history = [
        MessageIn(role="user", content="Добавь встречу с дизайнером в четверг в 11"),
        MessageIn(role="assistant", content="Встреча с дизайнером запланирована на четверг в 11:00")
    ]
    res = nlu.parse("Перенеси её на завтра", history=history, now=fixed_now)
    assert res.intent == "update_event"
    assert res.target_query in ("её", "ее", "встреча")
    assert res.datetime == datetime(2026, 10, 21, 0, 0)


def test_bonus_postpone_to_16(nlu, fixed_now):
    history = [
        MessageIn(role="user", content="Добавь встречу с командой в 15:00"),
        MessageIn(role="assistant", content="Встреча запланирована")
    ]
    res = nlu.parse("Сдвинь её на 16:00", history=history, now=fixed_now)
    assert res.intent == "update_event"
    assert res.datetime == datetime(2026, 10, 20, 16, 0)


def test_bonus_complete_task(nlu, fixed_now):
    res = nlu.parse("Отметь задачу по отчету выполненной", now=fixed_now)
    assert res.intent == "complete_event"
    assert "отчет" in res.target_query.lower()


def test_bonus_i_did_it(nlu, fixed_now):
    res = nlu.parse("Я сделал презентацию", now=fixed_now)
    assert res.intent == "complete_event"


def test_bonus_delete_event(nlu, fixed_now):
    res = nlu.parse("Удали задачу про презентацию", now=fixed_now)
    assert res.intent == "delete_event"
    assert "презентаци" in res.target_query.lower()


def test_bonus_cancel_meeting(nlu, fixed_now):
    res = nlu.parse("Отмени встречу с дизайнером", now=fixed_now)
    assert res.intent == "delete_event"
    assert "дизайнер" in res.target_query.lower()


@pytest.mark.parametrize(
    "phrase,expected_day,expected_time",
    [
        ("сегодня", 20, (0, 0)),
        ("завтра", 21, (0, 0)),
        ("послезавтра", 22, (0, 0)),
        ("в пятницу", 23, (0, 0)),
        ("через два часа", 20, (15, 0)),
        ("до конца недели", 25, (23, 59, 59)),
        ("на следующей неделе", 26, (0, 0)),
        ("завтра в 10 утра", 21, (10, 0)),
        ("завтра в 15:00", 21, (15, 0)),
        ("в четверг в 11", 22, (11, 0)),
        ("через 15 минут", 20, (13, 15)),
        ("через полчаса", 20, (13, 30)),
        ("сегодня в 18:00", 20, (18, 0)),
        ("послезавтра в 12:00", 22, (12, 0)),
    ]
)
def test_date_parser_variations(parser, fixed_now, phrase, expected_day, expected_time):
    p = parser.parse(phrase, base_dt=fixed_now)
    assert p.dt is not None
    assert p.dt.day == expected_day
    if len(expected_time) == 2:
        assert (p.dt.hour, p.dt.minute) == expected_time
    else:
        assert (p.dt.hour, p.dt.minute, p.dt.second) == expected_time


def test_chat_api_endpoint_flow(client):
    req_body = {
        "session_id": "test-session-123",
        "text": "Добавь встречу с командой завтра в 15:00"
    }
    response = client.post("/chat", json=req_body)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-123"
    assert data["action"]["type"] == "create_meeting"
    assert data["action"]["status"] == "ok"
    assert data["needs_clarification"] is False
    assert "Встреча с командой" in data["reply_text"]


def test_chat_api_endpoint_clarification(client):
    req_body = {
        "session_id": "test-session-456",
        "text": "Поставь встречу с Иваном завтра"
    }
    response = client.post("/chat", json=req_body)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-456"
    assert data["needs_clarification"] is True
    assert "время" in data["reply_text"].lower()


def test_chat_api_endpoint_search(client):
    req_body = {
        "session_id": "test-session-789",
        "text": "Найди задачу про презентацию"
    }
    response = client.post("/chat", json=req_body)
    assert response.status_code == 200
    data = response.json()
    assert data["action"]["type"] == "search_events"
    assert data["needs_clarification"] is False
