from datetime import datetime, time
from typing import Optional
from sqlalchemy.orm import Session

from backend.schemas.chat import ChatRequest, ChatResponse, ActionOut, MessageIn
from backend.schemas.record import RecordCreate, RecordType, RecordStatus, RecordOut
from backend.services.task_service import TaskService
from backend.repositories.message_repo import MessageRepository
from backend.nlu.nlu import NLUModule, NLUResult
from backend.models.record import Record


class DialogService:
    def __init__(self, nlu_module: Optional[NLUModule] = None):
        self.nlu = nlu_module or NLUModule()

    def handle(
        self,
        req: ChatRequest,
        now: Optional[datetime] = None,
        db: Optional[Session] = None,
    ) -> ChatResponse:
        current_dt = now or datetime.now()

        # Защита от пустого ввода
        if not req.text or not req.text.strip():
            reply = "Пожалуйста, скажите или напишите, чем я могу вам помочь."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type="conversation", status="ok"),
                needs_clarification=False,
            )

        # История сообщений: из запроса или из БД (последние N сообщений)
        history = list(req.history) if req.history else []
        if db is not None and not history:
            msg_repo = MessageRepository(db)
            db_msgs = msg_repo.get_history(req.session_id, limit=6)
            for m in db_msgs:
                history.append(MessageIn(role=m.role, content=m.content))

        nlu_res: NLUResult = self.nlu.parse(req.text, history=history, now=current_dt)

        task_service = TaskService(db) if db is not None else None

        # 1. Вежливый диалог / общение
        if nlu_res.intent == "conversation":
            reply = nlu_res.reply_text or nlu_res.clarification_question or "Здравствуйте! Чем я могу вам помочь?"
            self._save_interaction(db, req.session_id, req.text, reply)

            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type="conversation", status="ok"),
                needs_clarification=False,
            )

        # 2. Уточняющий вопрос
        if nlu_res.needs_clarification:
            reply = nlu_res.clarification_question or "Уточните, пожалуйста, детали."
            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="pending"),
                needs_clarification=True,
            )

        # 3. Создание встречи
        if nlu_res.intent == "create_meeting":
            dt_display = nlu_res.datetime.strftime("%d.%m в %H:%M") if nlu_res.datetime else "указанное время"
            created_rec_out: Optional[RecordOut] = None
            conflict_msg: Optional[str] = None

            if task_service:
                rec_create = RecordCreate(
                    user_id=req.user_id,
                    type=RecordType.meeting,
                    title=nlu_res.title or "Встреча",
                    raw_text=req.text,
                    datetime=nlu_res.datetime,
                )
                created_record, conflict_msg = task_service.create(rec_create)
                created_rec_out = RecordOut.model_validate(created_record)

            reply = f"Запланировал: {nlu_res.title} на {dt_display}."
            if conflict_msg:
                reply += f" ({conflict_msg})"

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", record=created_rec_out),
                needs_clarification=False,
            )

        # 4. Создание задачи или напоминания
        if nlu_res.intent == "create_task":
            rec_type = RecordType.reminder if nlu_res.record_type == "reminder" else RecordType.task
            dt_display = None
            if nlu_res.datetime:
                if nlu_res.has_explicit_time:
                    dt_display = nlu_res.datetime.strftime("%d.%m в %H:%M")
                else:
                    dt_display = nlu_res.datetime.strftime("%d.%m")

            created_rec_out = None
            if task_service:
                rec_create = RecordCreate(
                    user_id=req.user_id,
                    type=rec_type,
                    title=nlu_res.title or "Задача",
                    raw_text=req.text,
                    datetime=nlu_res.datetime,
                )
                created_record, _ = task_service.create(rec_create)
                created_rec_out = RecordOut.model_validate(created_record)

            type_ru = "напоминание" if rec_type == RecordType.reminder else "задачу"
            if dt_display:
                reply = f"Записал {type_ru}: {nlu_res.title} (срок: {dt_display})."
            else:
                reply = f"Записал {type_ru}: {nlu_res.title}."

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", record=created_rec_out),
                needs_clarification=False,
            )

        # 5. Получение списка событий на период
        if nlu_res.intent == "list_events":
            clean_text = req.text.lower()
            weekday_ru_map = {
                "понедельник": "понедельник",
                "вторник": "вторник",
                "сред": "среду",
                "четверг": "четверг",
                "пятниц": "пятницу",
                "суббот": "субботу",
                "воскресень": "воскресенье",
            }
            target_w = None
            for k, v in weekday_ru_map.items():
                if k in clean_text:
                    target_w = v
                    break
            default_period_ru = target_w or ("послезавтра" if "послезавтра" in clean_text else "запрошенный период")
            period_ru = {
                "today": "сегодня",
                "tomorrow": "завтра",
                "this_week": "эту неделю",
                "next_week": "следующую неделю",
                "all": "все время",
                "custom": default_period_ru,
            }.get(nlu_res.period or "today", default_period_ru)

            records_out = None
            if task_service:
                rec_type = None
                if nlu_res.record_type in ("task", "meeting", "reminder"):
                    rec_type = RecordType(nlu_res.record_type)

                res_list = task_service.list(
                    from_=nlu_res.period_start,
                    to=nlu_res.period_end,
                    record_type=rec_type,
                    user_id=req.user_id,
                )
                records_out = res_list.items
                if not records_out:
                    if rec_type == RecordType.meeting:
                        reply = f"У вас нет запланированных встреч на {period_ru}."
                    elif rec_type == RecordType.task:
                        reply = f"У вас нет запланированных задач на {period_ru}."
                    else:
                        reply = f"У вас нет запланированных событий на {period_ru}."
                else:
                    count = len(records_out)
                    items_str = ", ".join(
                        f"{r.title} ({r.datetime.strftime('%H:%M') if r.datetime else 'без времени'})"
                        for r in records_out[:4]
                    )
                    more_str = f" и еще {count - 4}" if count > 4 else ""
                    type_label = "Встречи" if rec_type == RecordType.meeting else ("Задачи" if rec_type == RecordType.task else "Планы")
                    reply = f"{type_label} на {period_ru} ({count}): {items_str}{more_str}."
            else:
                reply = f"Проверяю ваши планы на {period_ru}..."

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", records=records_out),
                needs_clarification=False,
            )

        # 6. Поиск событий
        if nlu_res.intent == "search_events":
            records_out = None
            if task_service:
                rec_type = None
                if nlu_res.record_type in ("task", "meeting", "reminder"):
                    rec_type = RecordType(nlu_res.record_type)

                search_res = task_service.search(
                    query=nlu_res.search_query or req.text,
                    record_type=rec_type,
                    user_id=req.user_id,
                )
                records_out = search_res.items
                if not records_out:
                    reply = f"По запросу '{nlu_res.search_query}' ничего не найдено."
                else:
                    def _format_rec(r):
                        if r.datetime:
                            time_str = r.datetime.strftime("%H:%M")
                            if time_str != "00:00" or r.type == RecordType.meeting:
                                dt_s = r.datetime.strftime("%d.%m в %H:%M")
                            else:
                                dt_s = r.datetime.strftime("%d.%m")
                            return f"'{r.title}' ({dt_s})"
                        return f"'{r.title}'"

                    items_str = ", ".join(_format_rec(r) for r in records_out[:3])
                    more_str = f" и еще {len(records_out) - 3}" if len(records_out) > 3 else ""
                    reply = f"Найдено ({len(records_out)}): {items_str}{more_str}."
            else:
                reply = f"Ищу записи по запросу '{nlu_res.search_query}'..."

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", records=records_out),
                needs_clarification=False,
            )

        # 7. Изменение / перенос события
        if nlu_res.intent == "update_event":
            updated_out = None
            conflict_msg: Optional[str] = None
            upd_rec: Optional[Record] = None
            if task_service:
                upd_rec, conflict_msg = task_service.find_and_update(
                    target_query=nlu_res.target_query or "её",
                    new_datetime=nlu_res.datetime,
                    new_title=nlu_res.title,
                    has_explicit_time=nlu_res.has_explicit_time,
                    has_explicit_date=nlu_res.has_explicit_date,
                    user_id=req.user_id,
                )

                if upd_rec:
                    updated_out = RecordOut.model_validate(upd_rec)

            dt_source = upd_rec.datetime if (upd_rec and upd_rec.datetime) else nlu_res.datetime
            if dt_source:
                dt_str = (
                    dt_source.strftime("%d.%m в %H:%M")
                    if (nlu_res.has_explicit_time or (upd_rec and upd_rec.type == RecordType.meeting and dt_source.time() != time(0, 0)))
                    else dt_source.strftime("%d.%m")
                )
            else:
                dt_str = "новую дату"

            if upd_rec:
                reply = f"Событие '{upd_rec.title}' перенесено на {dt_str}."
            else:
                reply = f"Событие перенесено на {dt_str}."

            if conflict_msg:
                reply += f" ({conflict_msg})"

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", record=updated_out),
                needs_clarification=False,
            )

        # 8. Завершение задачи
        if nlu_res.intent == "complete_event":
            updated_out = None
            if task_service:
                comp_rec = task_service.find_and_complete(
                    target_query=nlu_res.target_query or "задача",
                    user_id=req.user_id,
                )
                if comp_rec:
                    updated_out = RecordOut.model_validate(comp_rec)
                    reply = f"Отметил задачу '{comp_rec.title}' как выполненную."
                else:
                    reply = "Отметил задачу как выполненную."
            else:
                reply = "Отметил задачу как выполненную."

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", record=updated_out),
                needs_clarification=False,
            )

        # 9. Удаление события
        if nlu_res.intent == "delete_event":
            deleted_out = None
            if task_service:
                del_rec = task_service.find_and_delete(
                    target_query=nlu_res.target_query or "запись",
                    user_id=req.user_id,
                )
                if del_rec:
                    deleted_out = RecordOut.model_validate(del_rec)
                    reply = f"Запись '{del_rec.title}' удалена."
                else:
                    reply = "Запись удалена."
            else:
                reply = "Запись удалена."

            self._save_interaction(db, req.session_id, req.text, reply)
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok", record=deleted_out),
                needs_clarification=False,
            )

        # 10. Неизвестное намерение
        reply = "Я вас понял, но не уверен, какое действие выполнить. Вы можете сказать: 'Напомни мне...', 'Добавь встречу...' или 'Что у меня сегодня?'."
        self._save_interaction(db, req.session_id, req.text, reply)
        return ChatResponse(
            session_id=req.session_id,
            reply_text=reply,
            action=ActionOut(type="unknown", status="error"),
            needs_clarification=False,
        )

    def _save_interaction(
        self,
        db: Optional[Session],
        session_id: str,
        user_text: str,
        reply_text: str,
    ) -> None:
        if db is not None:
            try:
                repo = MessageRepository(db)
                repo.add(session_id=session_id, role="user", content=user_text)
                repo.add(session_id=session_id, role="assistant", content=reply_text)
            except Exception:
                pass


dialog_service = DialogService()
