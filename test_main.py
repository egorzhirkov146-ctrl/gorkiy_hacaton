import json
import logging
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

    def test_conversational_turns_are_answered_by_gigachat_plan(self):
        row = self.add_event(
            "reminder",
            "позвонить маме",
            (date.today() + timedelta(days=3)).isoformat(),
        )
        for text in ("привет", "ты?", "круто", "я понял", "еще раз", "почему"):
            with self.subTest(text=text):
                with patch(
                    "main.ask_gigachat",
                    return_value=({"actions": [], "reply": f"Ответ GigaChat на: {text}"}, None),
                ) as ask:
                    result = main.handle_chat(text)

                self.assertEqual(result["reply"], f"Ответ GigaChat на: {text}")
                self.assertEqual(result["events"], [])
                self.assertEqual(ask.call_count, 1)
                self.assertEqual(ask.call_args.kwargs.get("phase", "plan"), "plan")

        self.assertEqual([event["id"] for event in self.get_events()], [row["id"]])

    def test_empty_model_plan_gets_a_reply_phase_retry(self):
        with patch(
            "main.ask_gigachat",
            side_effect=[
                ({"invalid": True}, None),
                ({"reply": "Ответ от GigaChat"}, None),
            ],
        ) as ask:
            result = main.handle_chat("Расскажи об этом подробнее")

        self.assertEqual(result["reply"], "Ответ от GigaChat")
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(ask.call_args_list[1].args[2], "reply")

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
            result = main.handle_chat("Расскажи о своих возможностях")

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

    def test_delete_event_alias_selects_and_deletes_only_matching_record(self):
        selected = self.add_event("reminder", "позвонить маме", "2026-10-23")
        kept = self.add_event("task", "купить продукты", "2026-10-24")
        db = main.connect()
        try:
            with patch(
                "main.ask_gigachat",
                return_value=({"event_ids": [selected["id"]]}, None),
            ) as ask:
                result, error = main.action_results(
                    {
                        "actions": [{
                            "type": "delete_event",
                            "date": "2026-10-23",
                        }]
                    },
                    db,
                    {"message": "удали запись на 23 октября"},
                    "session",
                )
            remaining = db.execute("SELECT id FROM events ORDER BY id").fetchall()
        finally:
            db.close()

        self.assertIsNone(error)
        self.assertEqual(result["results"][0]["status"], "completed")
        self.assertEqual([row["id"] for row in result["events"]], [selected["id"]])
        self.assertEqual([row["id"] for row in remaining], [kept["id"]])
        self.assertEqual(ask.call_args.args[2], "select")

    def test_unsupported_model_action_is_rejected_without_mutating_records(self):
        row = self.add_event("reminder", "позвонить маме", "2026-10-23")
        db = main.connect()
        try:
            result, error = main.action_results(
                {"actions": [{"type": "delete_by_date"}]},
                db,
                {"message": "удали запись на 23 октября"},
                "session",
            )
            saved = db.execute("SELECT id FROM events WHERE id = ?", (row["id"],)).fetchone()
        finally:
            db.close()

        self.assertIsNone(result)
        self.assertIn("неподдерживаемое действие", error)
        self.assertIsNotNone(saved)

    def test_why_is_sent_to_gigachat_as_the_latest_user_message(self):
        row = self.add_event("reminder", "позвонить маме", "2026-10-23")
        db = main.connect()
        try:
            db.execute(
                "INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)",
                ("assistant", "Не удалось удалить запись.", datetime.now().isoformat()),
            )
            db.commit()
        finally:
            db.close()

        with patch(
            "main.ask_gigachat",
            return_value=({
                "actions": [],
                "reply": "Ответ GigaChat: удаление не удалось, потому что ответ модели не разобрался.",
            }, None),
        ) as ask:
            result = main.handle_chat("почему")

        self.assertEqual(result["reply"], "Ответ GigaChat: удаление не удалось, потому что ответ модели не разобрался.")
        self.assertEqual(result["events"], [])
        self.assertEqual(ask.call_args.kwargs.get("phase", "plan"), "plan")
        self.assertEqual(ask.call_args.args[0]["history"][0]["content"], "Не удалось удалить запись.")
        self.assertEqual([event["id"] for event in self.get_events()], [row["id"]])

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

    def test_confirming_pending_meeting_cancellation_deletes_the_event(self):
        meeting = self.add_event(
            "meeting",
            "встреча с подрядчиком",
            "2026-10-30",
            "14:00",
        )
        clarification = {
            "actions": [],
            "clarify": "Хотите отменить именно встречу в пятницу в 14:00?",
        }
        with patch("main.ask_gigachat", return_value=(clarification, None)):
            first = main.handle_chat("Удали встречу в пятницу")

        self.assertTrue(first["needs_reply"])
        pending = json.loads(first["context"])["pending_confirmation"]
        self.assertEqual(pending["request"], "Удали встречу в пятницу")
        self.assertEqual(pending["question"], clarification["clarify"])

        plan = {"actions": [{"type": "delete", "event_ids": [meeting["id"]]}]}
        with patch(
            "main.ask_gigachat",
            side_effect=[
                (plan, None),
                ({"reply": "Встреча отменена."}, None),
            ],
        ) as ask:
            confirmed = main.handle_chat("Да", first["context"])

        self.assertEqual(confirmed["reply"], "Встреча отменена.")
        self.assertEqual(confirmed["events"], [meeting])
        self.assertEqual(self.get_events(), [])
        self.assertEqual(
            ask.call_args_list[0].args[0]["pending_confirmation"]["request"],
            "Удали встречу в пятницу",
        )
        self.assertEqual(
            ask.call_args_list[0].args[0]["pending_confirmation"]["question"],
            clarification["clarify"],
        )

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
        with patch("main.logger.error") as log_error:
            with patch("main.ask_gigachat", return_value=(None, "GigaChat недоступен.")):
                result = main.handle_chat("Напомни завтра позвонить Ивану")

        self.assertIn("GigaChat недоступен", result["error"])
        self.assertNotIn("reply", result)
        self.assertEqual(result["events"], [])
        self.assertEqual(self.get_events(), [])
        log_error.assert_called_once()
        db = main.connect()
        try:
            self.assertEqual([row["role"] for row in main.chat_rows(db)], ["user"])
        finally:
            db.close()

    def test_application_errors_are_configured_to_write_to_a_log_file(self):
        file_handlers = [
            handler for handler in main.logger.handlers
            if isinstance(handler, logging.FileHandler)
        ]

        self.assertTrue(file_handlers)
        self.assertIn(main.LOG_FILE.resolve(), {
            Path(handler.baseFilename) for handler in file_handlers
        })

    def test_missing_gigachat_reply_is_reported_not_replaced_with_event_text(self):
        row = self.add_event("reminder", "позвонить маме")
        with patch("main.logger.error") as log_error:
            with patch(
                "main.ask_gigachat",
                side_effect=[
                    ({"actions": [{"type": "search", "event_ids": [row["id"]]}]}, None),
                    (None, "GigaChat недоступен."),
                ],
            ):
                result = main.handle_chat("Что я должен сделать?")

        self.assertEqual(result["error"], "GigaChat недоступен.")
        self.assertNotIn("reply", result)
        log_error.assert_called_once()

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

    def test_gigachat_response_falls_back_to_choices_when_messages_are_empty(self):
        response = (
            '{"messages":[],"choices":[{"message":{"content":"{\\"event_ids\\":[7]}"}}]}'
        ).encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)):
                result, error = main.ask_gigachat({}, [], "select")

        self.assertEqual(result, {"event_ids": [7]})
        self.assertIsNone(error)

    def test_successful_gigachat_exchange_logs_metadata_without_prompt_text(self):
        response = (
            '{"messages":[{"content":[{"text":"{\\"actions\\":[],'
            '\\"reply\\":\\"Ответ модели\\",\\"clarify\\":\\"\\"}"}]}]}'
        ).encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)):
                with patch("main.logger.info") as log_info:
                    result, error = main.ask_gigachat(
                        {"message": "секретный текст запроса"}, [], "plan"
                    )

        self.assertIsNone(error)
        self.assertEqual(result["reply"], "Ответ модели")
        log_lines = "\n".join(str(call) for call in log_info.call_args_list)
        self.assertIn("GigaChat request started", log_lines)
        self.assertIn("GigaChat response received", log_lines)
        self.assertIn("GigaChat response parsed", log_lines)
        self.assertNotIn("секретный текст запроса", log_lines)
        self.assertNotIn("Ответ модели", log_lines)

    def test_gigachat_invalid_http_body_returns_diagnostic_instead_of_generic_parse_error(self):
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(b"")):
                result, error = main.ask_gigachat({"message": "ты?"}, [], "plan")

        self.assertIsNone(result)
        self.assertIn("пустой ответ (HTTP 200)", error)
        self.assertNotIn("Не удалось прочитать ответ GigaChat", error)

    def test_gigachat_json_without_message_text_returns_response_shape(self):
        response = b'{"error":{"message":"temporary failure"},"status":"ok"}'
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)):
                result, error = main.ask_gigachat({"message": "ты?"}, [], "plan")

        self.assertIsNone(result)
        self.assertIn("JSON без текста ответа", error)
        self.assertIn("error, status", error)

    def test_empty_selection_response_returns_no_ids_for_clarification(self):
        response = '{"messages":[{"content":[]}]}'.encode("utf-8")
        with patch("main.gigachat_token", return_value=("test-token", None)):
            with patch("main.urllib.request.urlopen", return_value=BytesIO(response)):
                result, error = main.ask_gigachat({}, [], "select")

        self.assertEqual(result, {"event_ids": []})
        self.assertIsNone(error)

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
        self.assertIn("последнему сообщению пользователя", messages[0]["content"][0]["text"])

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

    def test_update_action_changes_existing_event_without_creating_another(self):
        row = self.add_event("reminder", "позвонить маме", "2026-10-31")
        db = main.connect()
        try:
            result = main.apply_action(
                {
                    "type": "update",
                    "event_ids": [row["id"]],
                    "title": "позвонить маме и уточнить время",
                    "weekday": "понедельник",
                    "date_is_explicit": False,
                    "time": "19:00",
                    "status": "done",
                },
                db,
            )
            saved = db.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            db.close()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(saved["title"], "позвонить маме и уточнить время")
        self.assertEqual(saved["event_date"], main.next_weekday("понедельник").isoformat())
        self.assertEqual(saved["event_time"], "19:00")
        self.assertEqual(saved["status"], "done")
        self.assertEqual(count, 1)

    def test_update_rejects_invalid_meeting_change_without_partial_updates(self):
        row = self.add_event("meeting", "созвон с командой", "2026-10-31", "19:00")
        db = main.connect()
        try:
            result = main.apply_action(
                {
                    "type": "update",
                    "event_ids": [row["id"]],
                    "title": "перенесённый созвон",
                    "time": None,
                },
                db,
            )
            saved = db.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
        finally:
            db.close()

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(saved["title"], "созвон с командой")
        self.assertEqual(saved["event_time"], "19:00")

    def test_delete_action_removes_only_selected_event(self):
        selected = self.add_event("reminder", "позвонить маме")
        kept = self.add_event("task", "купить продукты")
        db = main.connect()
        try:
            result = main.apply_action(
                {"type": "delete", "event_ids": [selected["id"]]},
                db,
            )
            remaining = db.execute("SELECT id FROM events").fetchall()
        finally:
            db.close()

        self.assertEqual(result["status"], "completed")
        self.assertEqual([row["id"] for row in result["events"]], [selected["id"]])
        self.assertEqual([row["id"] for row in remaining], [kept["id"]])

    def test_update_selects_target_event_before_mutating(self):
        row = self.add_event("reminder", "позвонить маме")
        db = main.connect()
        try:
            with patch(
                "main.ask_gigachat",
                return_value=({"event_ids": [row["id"]]}, None),
            ) as ask:
                result, error = main.action_results(
                    {
                        "actions": [{
                            "type": "update",
                            "title": "позвонить маме в понедельник",
                            "weekday": "понедельник",
                            "date_is_explicit": False,
                        }]
                    },
                    db,
                    {"message": "Перенеси звонок маме на понедельник"},
                    "session",
                )
            saved = db.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
        finally:
            db.close()

        self.assertIsNone(error)
        self.assertEqual(result["results"][0]["status"], "completed")
        self.assertEqual(saved["title"], "позвонить маме в понедельник")
        self.assertEqual(saved["event_date"], main.next_weekday("понедельник").isoformat())
        self.assertEqual(ask.call_args.args[2], "select")

    def test_delete_without_unambiguous_selection_does_not_remove_records(self):
        row = self.add_event("reminder", "позвонить маме")
        db = main.connect()
        try:
            with patch("main.ask_gigachat", return_value=({"event_ids": []}, None)):
                result, error = main.action_results(
                    {"actions": [{"type": "delete"}]},
                    db,
                    {"message": "Удали то напоминание"},
                    "session",
                )
            saved = db.execute("SELECT id FROM events WHERE id = ?", (row["id"],)).fetchone()
        finally:
            db.close()

        self.assertIsNone(error)
        self.assertTrue(result["clarify"])
        self.assertIsNotNone(saved)

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
