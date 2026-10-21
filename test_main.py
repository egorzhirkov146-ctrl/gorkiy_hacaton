import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import main


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        main.DB = Path(self.tmp.name) / "test.db"
        self.old_key = main.GIGACHAT_AUTH_KEY
        self.old_token = main.GIGACHAT_TOKEN
        self.old_expires = main.GIGACHAT_TOKEN_EXPIRES
        main.GIGACHAT_AUTH_KEY = ""
        main.GIGACHAT_TOKEN = ""
        main.GIGACHAT_TOKEN_EXPIRES = 0

    def tearDown(self):
        main.GIGACHAT_AUTH_KEY = self.old_key
        main.GIGACHAT_TOKEN = self.old_token
        main.GIGACHAT_TOKEN_EXPIRES = self.old_expires
        self.tmp.cleanup()

    def add_event(self, kind, title, day=None, clock=None):
        db = main.connect()
        db.execute(
            "INSERT INTO events (kind, title, event_date, event_time, created_at) VALUES (?, ?, ?, ?, ?)",
            (kind, title, day, clock, datetime.now().isoformat()),
        )
        db.commit()
        row = db.execute("SELECT * FROM events WHERE id = last_insert_rowid()").fetchone()
        db.close()
        return dict(row)

    def get_events(self):
        db = main.connect()
        rows = main.event_rows(db)
        db.close()
        return rows

    def test_model_creates_record_and_writes_final_reply(self):
        day = (datetime.now().date() + timedelta(days=1)).isoformat()
        plan = {
            "actions": [{
                "type": "create",
                "kind": "reminder",
                "title": "позвонить Ивану",
                "date": day,
                "time": "10:00",
                "weekday": (datetime.now().date() + timedelta(days=1)).weekday(),
            }],
            "reply": "",
        }
        final = {"reply": "Записал звонок Ивану на завтра в 10:00."}
        with patch("main.ask_gigachat", side_effect=[(plan, None), (final, None)]) as ask:
            result = main.handle_chat("Напомни завтра в 10:00 позвонить Ивану")

        self.assertEqual(result["reply"], final["reply"])
        self.assertEqual(result["events"][0]["title"], "позвонить Ивану")
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(ask.call_args.args[2], "reply")

    def test_model_can_reply_without_database_actions(self):
        with patch(
            "main.ask_gigachat",
            return_value=({"actions": [], "reply": "Привет! Чем помочь?"}, None),
        ) as ask:
            result = main.handle_chat("привет")

        self.assertEqual(result["reply"], "Привет! Чем помочь?")
        self.assertEqual(result["events"], [])
        self.assertEqual(ask.call_count, 1)

    def test_chat_history_is_saved_and_sent_with_the_next_message(self):
        with patch(
            "main.ask_gigachat",
            return_value=({"actions": [], "reply": "Привет! Чем помочь?"}, None),
        ):
            main.handle_chat("Привет")

        with patch(
            "main.ask_gigachat",
            return_value=({"actions": [], "reply": "Понял, продолжим."}, None),
        ) as ask:
            main.handle_chat("Расскажи подробнее")

        history = ask.call_args.args[0]["history"]
        self.assertEqual(
            history,
            [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Привет! Чем помочь?"},
            ],
        )
        db = main.connect()
        try:
            self.assertEqual(
                main.chat_rows(db),
                history + [
                    {"role": "user", "content": "Расскажи подробнее"},
                    {"role": "assistant", "content": "Понял, продолжим."},
                ],
            )
        finally:
            db.close()

    def test_gigachat_session_id_is_stable_in_database(self):
        db = main.connect()
        try:
            first = main.chat_session_id(db)
            db.close()
            db = main.connect()
            second = main.chat_session_id(db)
        finally:
            db.close()

        self.assertEqual(first, second)

    def test_invalid_plan_is_rephrased_without_showing_raw_json(self):
        with patch(
            "main.ask_gigachat",
            side_effect=[
                ({"invalid": True}, None),
                ({"reply": "Привет! Чем могу помочь?"}, None),
            ],
        ) as ask:
            result = main.handle_chat("привет")

        self.assertEqual(result["reply"], "Привет! Чем могу помочь?")
        self.assertEqual(result["events"], [])
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(ask.call_args_list[1].args[2], "reply")
        self.assertEqual(ask.call_args_list[1].args[3][0]["status"], "not_executed")

    def test_model_search_uses_selected_database_ids(self):
        row = self.add_event(
            "reminder",
            "позвонить Ивану",
            (datetime.now().date() + timedelta(days=1)).isoformat(),
            "10:00",
        )
        plan = {"actions": [{"type": "search", "event_ids": [row["id"]]}]}
        with patch(
            "main.ask_gigachat",
            side_effect=[(plan, None), ({"reply": "Завтра позвонить Ивану в 10:00."}, None)],
        ):
            result = main.handle_chat("че там с Иваном у меня")

        self.assertEqual([item["id"] for item in result["events"]], [row["id"]])
        self.assertIn("позвонить Ивану", result["reply"])

    def test_model_selects_ids_for_search_as_a_separate_llm_step(self):
        row = self.add_event("meeting", "обсудить договор с Иваном")
        plan = {"actions": [{"type": "search", "query": "встреча с Иваном"}]}
        selected = {"event_ids": [row["id"]]}
        final = {"reply": "Нашёл встречу по договору с Иваном."}
        with patch(
            "main.ask_gigachat",
            side_effect=[(plan, None), (selected, None), (final, None)],
        ) as ask:
            result = main.handle_chat("Когда у меня была встреча с Иваном?")

        self.assertEqual(result["events"][0]["id"], row["id"])
        self.assertEqual(ask.call_count, 3)
        self.assertEqual(ask.call_args_list[1].args[2], "select")
        self.assertEqual(ask.call_args_list[2].args[2], "reply")

    def test_model_lists_events_using_its_date_range(self):
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        row = self.add_event("reminder", "позвонить Саньку", tomorrow, "10:00")
        self.add_event("task", "купить билеты", tomorrow)
        plan = {
            "actions": [{
                "type": "list",
                "kind": "reminder",
                "date_from": tomorrow,
                "date_to": tomorrow,
            }]
        }
        with patch(
            "main.ask_gigachat",
            side_effect=[(plan, None), ({"reply": "Завтра нужно позвонить Саньку."}, None)],
        ):
            result = main.handle_chat("Что у меня с Саньком завтра?")

        self.assertEqual([item["id"] for item in result["events"]], [row["id"]])
        self.assertIn("позвонить Саньку", result["reply"])

    def test_empty_period_result_is_checked_against_saved_event_dates(self):
        row = self.add_event("meeting", "созвон с мамой", "2026-10-25", "13:00")
        plan = {
            "actions": [{
                "type": "list",
                "kind": "all",
                "date_from": "2026-10-24",
                "date_to": "2026-10-24",
            }]
        }
        selected = {"event_ids": [row["id"]]}
        final = {"reply": "В воскресенье у тебя созвон с мамой в 13:00."}
        with patch(
            "main.ask_gigachat",
            side_effect=[(plan, None), (selected, None), (final, None)],
        ) as ask:
            result = main.handle_chat("а на послепослепосле завтра")

        self.assertEqual([item["id"] for item in result["events"]], [row["id"]])
        self.assertIn("созвон с мамой", result["reply"])
        self.assertEqual(ask.call_args_list[1].args[2], "select")
        self.assertEqual(
            ask.call_args_list[1].args[1][0]["event_date"],
            "2026-10-25",
        )

    def test_model_can_ask_for_missing_meeting_details(self):
        plan = {"actions": [], "clarify": "На какую дату и время поставить встречу?"}
        with patch("main.ask_gigachat", return_value=(plan, None)):
            result = main.handle_chat("Добавь встречу с дизайнером")

        self.assertTrue(result["needs_reply"])
        self.assertIn("дату и время", result["reply"])
        self.assertEqual(self.get_events(), [])

    def test_rejects_invalid_model_action_without_creating_data(self):
        plan = {
            "actions": [{
                "type": "create",
                "kind": "task",
                "title": "позвонить Ивану",
                "date": "завтра",
                "time": "10:00",
            }]
        }
        with patch(
            "main.ask_gigachat",
            side_effect=[
                (plan, None),
                ({"reply": "Не получилось сохранить дату."}, None),
            ],
        ):
            result = main.handle_chat("Напомни завтра позвонить Ивану")

        self.assertEqual(result["events"], [])
        self.assertEqual(self.get_events(), [])
        self.assertIn("Не получилось", result["reply"])

    def test_reports_gigachat_error_without_local_keyword_fallback(self):
        with patch("main.ask_gigachat", return_value=(None, "GigaChat недоступен.")):
            result = main.handle_chat("Напомни завтра позвонить Ивану")

        self.assertIn("GigaChat недоступен", result["reply"])
        self.assertEqual(result["events"], [])
        self.assertEqual(self.get_events(), [])

    def test_gigachat_token_uses_authorization_and_caches_token(self):
        main.GIGACHAT_AUTH_KEY = "test-auth"
        data = b'{"access_token":"test-token","expires_at":4102444800000}'
        with patch("main.urllib.request.urlopen", return_value=BytesIO(data)) as open_url:
            token, error = main.gigachat_token()
            cached, cached_error = main.gigachat_token()

        self.assertEqual(token, "test-token")
        self.assertIsNone(error)
        self.assertEqual(cached, token)
        self.assertIsNone(cached_error)
        self.assertEqual(open_url.call_count, 1)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
        self.assertEqual(request.get_header("Authorization"), "Basic test-auth")
        self.assertIn(b"GIGACHAT_API_PERS", request.data)

    def test_gigachat_request_uses_model_and_rejects_non_json_plan(self):
        response = '{"messages":[{"role":"assistant","content":[{"text":"Привет! Чем помочь?"}]}]}'.encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)) as open_url:
                result, error = main.ask_gigachat({"message": "привет"}, [], "plan")

        self.assertEqual(result, {"invalid": True})
        self.assertIsNone(error)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.giga.chat/v2/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertIn(main.os.environ.get("GIGACHAT_MODEL", main.MODEL).encode(), request.data)
        body = json.loads(request.data)
        self.assertEqual(body["model_options"]["response_format"]["type"], "json_schema")
        self.assertEqual(body["model_options"]["response_format"]["schema"], main.PLAN_SCHEMA)

    def test_invalid_plan_json_is_not_returned_as_a_user_reply(self):
        response = '{"messages":[{"role":"assistant","content":[{"text":"{\\"actions\\": [], \\"reply\\": \\"Привет! Чем помочь?}"}]}]}'.encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)):
                result, error = main.ask_gigachat({"message": "привет"}, [], "plan")

        self.assertEqual(result, {"invalid": True})
        self.assertIsNone(error)

    def test_reply_request_returns_plain_text_without_json_mode(self):
        response = '{"messages":[{"role":"assistant","content":[{"text":"Встреча в воскресенье."}]}]}'.encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)) as open_url:
                result, error = main.ask_gigachat({}, [], "reply", [])

        body = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(result, {"reply": "Встреча в воскресенье."})
        self.assertIsNone(error)
        self.assertNotIn("model_options", body)

    def test_gigachat_request_sends_session_id_header(self):
        response = '{"messages":[{"role":"assistant","content":[{"text":"{}"}]}]}'.encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)) as open_url:
                main.ask_gigachat({}, [], session_id="stable-session-id")

        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("X-session-id"), "stable-session-id")

    def test_gigachat_request_sends_history_as_role_messages(self):
        response = '{"messages":[{"role":"assistant","content":[{"text":"{}"}]}]}'.encode("utf-8")
        conversation = {
            "history": [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Привет! Чем помочь?"},
            ],
            "context": "",
            "message": "Есть планы на завтра?",
        }
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)) as open_url:
                main.ask_gigachat(conversation, [], "plan")

        body = json.loads(open_url.call_args.args[0].data)
        messages = body["messages"]
        self.assertEqual(
            [
                {
                    "role": item["role"],
                    "content": "".join(part["text"] for part in item["content"]),
                }
                for item in messages[1:3]
            ],
            conversation["history"],
        )
        self.assertEqual(messages[3]["role"], "user")
        current = json.loads(messages[3]["content"][0]["text"])
        self.assertEqual(current["conversation"]["message"], "Есть планы на завтра?")
        self.assertNotIn("history", current["conversation"])

    def test_uses_nearest_date_for_weekday_chosen_by_model(self):
        plan = {
            "actions": [{
                "type": "create",
                "kind": "meeting",
                "title": "встреча с командой",
                "date": "2026-10-22",
                "time": "13:30",
                "weekday": "воскресенье",
                "date_is_explicit": False,
            }]
        }
        with patch("main.ask_gigachat", side_effect=[
            (plan, None),
            ({"reply": "Встреча запланирована на ближайшее воскресенье."}, None),
        ]):
            result = main.handle_chat("Добавь встречу с командой через в воскресенье в 13:30")

        self.assertEqual(result["events"][0]["event_date"], main.next_weekday("воскресенье").isoformat())
        self.assertEqual(date.fromisoformat(result["events"][0]["event_date"]).weekday(), 6)

    def test_rejects_explicit_date_that_conflicts_with_model_weekday(self):
        db = main.connect()
        result = main.apply_action(
            {
                "type": "create",
                "kind": "meeting",
                "title": "встреча с командой",
                "date": "2026-10-22",
                "time": "13:30",
                "weekday": "воскресенье",
                "date_is_explicit": True,
            },
            db,
        )
        db.close()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.get_events(), [])

    def test_event_format_includes_weekday_from_saved_date(self):
        row = self.add_event("meeting", "встреча с командой", "2026-10-25", "13:30")
        self.assertIn("воскресенье, 25.10.2026", main.format_event(row))

    def test_extracts_user_reply_from_nested_json(self):
        self.assertEqual(
            main.get_reply({"reply": '{"reply":"Встреча в воскресенье."}'}),
            "Встреча в воскресенье.",
        )

    def test_formats_valid_dates_and_times_from_model(self):
        self.assertEqual(main.valid_date("2026-10-22"), "2026-10-22")
        self.assertIsNone(main.valid_date("завтра"))
        self.assertEqual(main.valid_time("10:00"), "10:00")
        self.assertIsNone(main.valid_time("25:00"))


if __name__ == "__main__":
    unittest.main()
