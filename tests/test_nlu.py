from datetime import datetime
import uuid
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
        ("через час", 20, (14, 0)),
        ("через пару часов", 20, (15, 0)),
        ("через день", 21, (13, 0)),
        ("через неделю", 27, (13, 0)),
        ("в 3 часа дня", 20, (15, 0)),
        ("в 8 вечера", 20, (20, 0)),
        ("в полдень", 21, (12, 0)),
        ("в полночь", 21, (0, 0)),
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


def test_root_nlu_module_import():
    import nlu
    res = nlu.parse_user_intent("В пятницу отправить отчет")
    assert res.intent == "create_task"
    assert "отчет" in res.title.lower()


def test_tools_definitions_format():
    from backend.nlu.tools import TOOLS_DEFINITIONS
    tool_names = {t["function"]["name"] for t in TOOLS_DEFINITIONS}
    assert "create_task" in tool_names
    assert "create_meeting" in tool_names
    assert "list_events" in tool_names
    assert "search_events" in tool_names
    assert "ask_clarification" in tool_names
    assert "update_event" in tool_names
    assert "complete_event" in tool_names
    assert "delete_event" in tool_names



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


def test_nlu_empty_and_whitespace_input(nlu, fixed_now):
    res1 = nlu.parse("", now=fixed_now)
    assert res1.intent == "conversation"
    assert res1.reply_text is not None
    assert len(res1.reply_text) > 0

    res2 = nlu.parse("   ", now=fixed_now)
    assert res2.intent == "conversation"
    assert res2.reply_text is not None


def test_nlu_conversational_queries(nlu, fixed_now):
    for phrase in ["Привет", "Здравствуйте", "Спасибо огромное", "Помощь", "Что ты умеешь?"]:
        res = nlu.parse(phrase, now=fixed_now)
        assert res.intent == "conversation"
        assert res.reply_text is not None
        assert res.tool_called is None


def test_nlu_weekday_prepositions_and_inflections(parser, fixed_now):
    # fixed_now = Tuesday 2026-10-20 13:00
    res_fri = parser.parse("до пятницы", base_dt=fixed_now)
    assert res_fri.dt is not None
    assert res_fri.dt.day == 23

    res_wed = parser.parse("к среде", base_dt=fixed_now)
    assert res_wed.dt is not None
    assert res_wed.dt.day == 21

    res_tue = parser.parse("во вторник в 14:30", base_dt=fixed_now)
    assert res_tue.dt is not None
    assert res_tue.dt.day == 20
    assert (res_tue.dt.hour, res_tue.dt.minute) == (14, 30)

    res_next_wed = parser.parse("на следующей неделе в среду", base_dt=fixed_now)
    assert res_next_wed.dt is not None
    # Следующая среда после 20.10: 28.10
    assert res_next_wed.dt.day == 28


def test_nlu_number_words_delta(parser, fixed_now):
    res_20m = parser.parse("через двадцать минут", base_dt=fixed_now)
    assert res_20m.dt is not None
    assert (res_20m.dt.hour, res_20m.dt.minute) == (13, 20)

    res_30m = parser.parse("через тридцать минут", base_dt=fixed_now)
    assert res_30m.dt is not None
    assert (res_30m.dt.hour, res_30m.dt.minute) == (13, 30)


def test_clarification_with_day_after_tomorrow(nlu, fixed_now):
    # Turn 1: встреча без времени на послезавтра
    res1 = nlu.parse("Встреча с партнерами послезавтра", now=fixed_now)
    assert res1.needs_clarification is True
    assert res1.intent == "ask_clarification"
    assert res1.datetime.day == 22


    # Turn 2: пользователь уточняет "в 14:00"
    history = [
        MessageIn(role="user", content="Встреча с партнерами послезавтра"),
        MessageIn(role="assistant", content="Уточните, пожалуйста, время встречи?")
    ]
    res2 = nlu.parse("в 14:00", history=history, now=fixed_now)
    assert res2.needs_clarification is False
    assert res2.intent == "create_meeting"
    assert res2.datetime == datetime(2026, 10, 22, 14, 0)
    assert "партнер" in res2.title.lower()


def test_chat_api_conversational_and_empty(client):
    res_empty = client.post("/chat", json={"session_id": "test-chat-conv", "text": "   "})
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    assert data_empty["action"]["type"] == "conversation"

    res_greet = client.post("/chat", json={"session_id": "test-chat-conv", "text": "Привет!"})
    assert res_greet.status_code == 200
    data_greet = res_greet.json()
    assert data_greet["action"]["type"] == "conversation"
    assert "помочь" in data_greet["reply_text"].lower() or "привет" in data_greet["reply_text"].lower() or "здравствуйте" in data_greet["reply_text"].lower()


def test_conflict_warning_in_history_does_not_hijack_subsequent_meeting(nlu, fixed_now):
    history = [
        MessageIn(role="user", content="Добавь встречу с командой завтра в 15:00"),
        MessageIn(role="assistant", content="Запланировал: Встреча с командой на 21.10 в 15:00. (Внимание: время пересекается с событием 'Созвон' в 15:00.)")
    ]
    res = nlu.parse("В четверг в 11 у меня встреча с дизайнером", history=history, now=fixed_now)
    assert res.intent == "create_meeting"
    assert "дизайнер" in res.title.lower()
    assert res.datetime.hour == 11
    assert res.datetime.day == 22
    assert ":00" not in res.title


def test_list_events_bounds_populated(nlu, fixed_now):
    res_today = nlu.parse("Что у меня сегодня?", now=fixed_now)
    assert res_today.period_start == datetime(2026, 10, 20, 0, 0)
    assert res_today.period_end.hour == 23

    res_tomorrow = nlu.parse("Какие планы на завтра?", now=fixed_now)
    assert res_tomorrow.period_start == datetime(2026, 10, 21, 0, 0)
    assert res_tomorrow.period_end.hour == 23

    res_week = nlu.parse("Что запланировано на эту неделю?", now=fixed_now)
    assert res_week.period_start is not None
    assert res_week.period_end is not None


def test_meeting_preposition_preservation(nlu, fixed_now):
    res1 = nlu.parse("Встреча по проекту завтра в 10:00", now=fixed_now)
    assert res1.intent == "create_meeting"
    assert res1.title == "Встреча по проекту"

    res2 = nlu.parse("Встреча для инвесторов в пятницу в 12:00", now=fixed_now)
    assert res2.intent == "create_meeting"
    assert res2.title == "Встреча для инвесторов"

    res3 = nlu.parse("Созвон с техлидом в 16:00", now=fixed_now)
    assert res3.intent == "create_meeting"
    assert res3.title == "Созвон с техлидом"


def test_meeting_relative_delta_stripped(nlu, fixed_now):
    res = nlu.parse("Встреча через полчаса с клиентом", now=fixed_now)
    assert res.intent == "create_meeting"
    assert res.title == "Встреча с клиентом"
    assert res.datetime == datetime(2026, 10, 20, 13, 30)


def test_search_inquiry_variations(nlu, fixed_now):
    cases = [
        "Когда была встреча с Иваном?",
        "Когда созвон с техлидом?",
        "Когда у нас встреча с дизайнером?",
        "Покажи контракт",
        "Покажи задачу про договор",
        "Я когда-то создавал задачу про отчет"
    ]
    for c in cases:
        res = nlu.parse(c, now=fixed_now)
        assert res.intent == "search_events", f"Failed for query: {c}"


def test_multi_turn_clarification_with_intermediate_search(client):
    sess = f"test-multi-turn-search-interrupt-{uuid.uuid4().hex}"
    # Turn 1: create meeting without time triggers clarification
    r1 = client.post("/chat", json={"session_id": sess, "text": "Поставь встречу с Иваном завтра"})
    assert r1.status_code == 200
    assert r1.json()["needs_clarification"] is True

    # Turn 2: intermediate search does not break the clarification flow
    r2 = client.post("/chat", json={"session_id": sess, "text": "Найди презентацию"})
    assert r2.status_code == 200
    assert r2.json()["action"]["type"] == "search_events"

    # Turn 3: user answers with time, resolving the meeting with Ivan
    r3 = client.post("/chat", json={"session_id": sess, "text": "в 15:00"})
    assert r3.status_code == 200
    data3 = r3.json()
    assert data3["action"]["type"] == "create_meeting"
    assert "иван" in data3["action"]["record"]["title"].lower()
    assert "15:00" in data3["reply_text"]


def test_bare_time_without_context_prompts_clarification(client):
    sess = f"fresh-session-bare-time-{uuid.uuid4().hex}"
    r = client.post("/chat", json={"session_id": sess, "text": "в 15:00"})
    assert r.status_code == 200
    data = r.json()
    assert data["needs_clarification"] is True
    assert "какую задачу" in data["reply_text"].lower() or "уточните" in data["reply_text"].lower()


def test_bare_time_followup_meeting(client):
    sess = f"test-bare-time-followup-m-{uuid.uuid4().hex}"
    r1 = client.post("/chat", json={"session_id": sess, "text": "в 15:00"})
    assert r1.status_code == 200
    assert r1.json()["needs_clarification"] is True

    r2 = client.post("/chat", json={"session_id": sess, "text": "встреча с дизайнером"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["action"]["type"] == "create_meeting"
    assert "дизайнер" in d2["action"]["record"]["title"].lower()
    assert "15:00" in d2["action"]["record"]["datetime"]


def test_bare_time_followup_task(client):
    sess = f"test-bare-time-followup-t-{uuid.uuid4().hex}"
    r1 = client.post("/chat", json={"session_id": sess, "text": "завтра в 10 утра"})
    assert r1.status_code == 200
    assert r1.json()["needs_clarification"] is True

    r2 = client.post("/chat", json={"session_id": sess, "text": "позвонить маме"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["action"]["type"] == "create_task"
    assert "позвонить маме" in d2["action"]["record"]["title"].lower()
    assert "10:00" in d2["action"]["record"]["datetime"]


def test_reschedule_named_meeting(client):
    sess = f"test-resched-named-{uuid.uuid4().hex}"
    client.post("/chat", json={"session_id": sess, "text": "Добавь встречу с дизайнером в четверг в 11:00"})
    r_upd = client.post("/chat", json={"session_id": sess, "text": "Перенеси встречу с дизайнером на пятницу"})
    assert r_upd.status_code == 200
    data = r_upd.json()
    assert data["action"]["type"] == "update_event"
    assert "дизайнер" in data["reply_text"].lower()
    assert "11:00" in data["reply_text"]


def test_explicit_month_date_parsing(nlu, fixed_now):
    res = nlu.parse("Встреча 15 ноября в 14:00 с партнерами", now=fixed_now)
    assert res.intent == "create_meeting"
    assert res.datetime == datetime(2026, 11, 15, 14, 0)
    assert res.title == "Встреча с партнерами"


def test_list_events_weekday_filtering(client, fixed_now):
    sess = f"test-weekday-filter-{uuid.uuid4().hex}"
    # Seed specific events for Friday
    r = client.post("/chat", json={"session_id": sess, "text": "Что у меня в пятницу?"})
    assert r.status_code == 200
    data = r.json()
    assert data["action"]["type"] == "list_events"
    assert "пятниц" in data["reply_text"].lower()


def test_conversational_words_do_not_create_tasks(client):
    for word in ["хорошо", "ок", "отмена", "не надо", "как дела?", "кто ты?"]:
        sess = f"test-conv-{uuid.uuid4().hex}"
        r = client.post("/chat", json={"session_id": sess, "text": word})
        assert r.status_code == 200
        data = r.json()
        assert data["action"]["type"] == "conversation"
        assert data["action"]["record"] is None




