from datetime import datetime
from typing import Optional

from backend.schemas.chat import ChatRequest, ChatResponse, ActionOut
from backend.nlu.nlu import NLUModule, NLUResult


class DialogService:
    def __init__(self, nlu_module: Optional[NLUModule] = None):
        self.nlu = nlu_module or NLUModule()

    def handle(self, req: ChatRequest, now: Optional[datetime] = None) -> ChatResponse:
        current_dt = now or datetime.now()
        nlu_res: NLUResult = self.nlu.parse(req.text, history=req.history, now=current_dt)

        if nlu_res.needs_clarification:
            return ChatResponse(
                session_id=req.session_id,
                reply_text=nlu_res.clarification_question or "Уточните, пожалуйста, детали.",
                action=ActionOut(type=nlu_res.intent, status="pending"),
                needs_clarification=True,
            )

        if nlu_res.intent == "create_meeting":
            dt_display = nlu_res.datetime.strftime("%d.%m в %H:%M") if nlu_res.datetime else "указанное время"
            reply = f"Запланировал: {nlu_res.title} на {dt_display}."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "create_task":
            if nlu_res.datetime:
                if nlu_res.has_explicit_time:
                    dt_display = nlu_res.datetime.strftime("%d.%m в %H:%M")
                else:
                    dt_display = nlu_res.datetime.strftime("%d.%m")
                reply = f"Записал задачу: {nlu_res.title} (срок: {dt_display})."
            else:
                reply = f"Записал задачу: {nlu_res.title}."

            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "list_events":
            period_ru = {
                "today": "сегодня",
                "tomorrow": "завтра",
                "this_week": "эту неделю",
                "next_week": "следующую неделю",
                "all": "все время",
                "custom": "выбранный период"
            }.get(nlu_res.period or "today", "запрошенный период")

            reply = f"Проверяю ваши планы на {period_ru}..."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "search_events":
            reply = f"Ищу записи по запросу '{nlu_res.search_query}'..."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "update_event":
            dt_str = nlu_res.datetime.strftime("%d.%m в %H:%M") if (nlu_res.datetime and nlu_res.has_explicit_time) else (nlu_res.datetime.strftime("%d.%m") if nlu_res.datetime else "новую дату")
            reply = f"Событие перенесено на {dt_str}."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "complete_event":
            reply = "Отметил задачу как выполненную."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        if nlu_res.intent == "delete_event":
            reply = "Запись удалена."
            return ChatResponse(
                session_id=req.session_id,
                reply_text=reply,
                action=ActionOut(type=nlu_res.intent, status="ok"),
                needs_clarification=False,
            )

        return ChatResponse(
            session_id=req.session_id,
            reply_text="Я вас понял, но не уверен, какое действие выполнить.",
            action=ActionOut(type="unknown", status="error"),
            needs_clarification=False,
        )


dialog_service = DialogService()
