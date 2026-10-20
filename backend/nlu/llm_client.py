import json
import re
from datetime import datetime
from typing import Optional, Any
from openai import OpenAI

from backend.config import settings
from backend.nlu.tools import TOOLS_DEFINITIONS
from backend.nlu.prompts import build_system_prompt
from backend.nlu.date_parser import RussianDateParser


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.client = OpenAI(api_key=self.api_key) if self.api_key and not self.api_key.startswith("sk-...") else None
        self.date_parser = RussianDateParser(default_tz=settings.tz)

    def is_live(self) -> bool:
        return self.client is not None

    def call_tools(
        self,
        messages: list[dict[str, str]],
        now: Optional[datetime] = None
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        current_dt = now or datetime.now()

        if self.is_live():
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.0,
                    timeout=settings.llm_timeout_sec
                )
                choice = response.choices[0]
                message = choice.message

                if message.tool_calls:
                    tool_call = message.tool_calls[0]
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    return name, args, message.content
            except Exception:
                pass

        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break

        return self._offline_extract(user_content, messages, current_dt)

    def _offline_extract(
        self,
        text: str,
        messages: list[dict[str, str]],
        now: datetime
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        clean = text.lower().strip()

        if len(messages) >= 2:
            last_assistant = ""
            for m in reversed(messages[:-1]):
                if m.get("role") == "assistant":
                    last_assistant = m.get("content", "").lower()
                    break

            if "на какое время" in last_assistant or "какое время" in last_assistant:
                parsed_t, has_t = self.date_parser.parse_time_component(clean)
                if has_t or self.date_parser.parse(clean, base_dt=now).has_explicit_time:
                    meeting_title = "Встреча"
                    prev_date_str = "завтра"
                    for m in reversed(messages[:-1]):
                        if m.get("role") == "user":
                            u_prev = m.get("content", "")
                            if "встреч" in u_prev.lower():
                                match_m = re.search(r"встреч[уаеы]?\s+(?:с\s+)?([^,.?!]+)", u_prev, re.IGNORECASE)
                                if match_m:
                                    raw_sub = match_m.group(1).strip()
                                    cleaned_sub = re.sub(r"\b(завтра|сегодня|послезавтра|в\s+\w+)\b", "", raw_sub, flags=re.IGNORECASE).strip()
                                    meeting_title = f"Встреча с {cleaned_sub}" if cleaned_sub else "Встреча"
                                if "завтра" in u_prev.lower():
                                    prev_date_str = "завтра"
                                elif "сегодня" in u_prev.lower():
                                    prev_date_str = "сегодня"
                                elif "четверг" in u_prev.lower():
                                    prev_date_str = "в четверг"
                                elif "пятниц" in u_prev.lower():
                                    prev_date_str = "в пятницу"
                                break

                    full_datetime = f"{prev_date_str} {text}"
                    return "create_meeting", {
                        "title": meeting_title,
                        "datetime_str": full_datetime,
                        "raw_text": f"{meeting_title} {full_datetime}"
                    }, None

        if re.search(r"\b(перенеси|сдвинь|отложи)\b", clean):
            target = "её"
            if "встреч" in clean:
                target = "встреча"
            elif "задач" in clean:
                target = "задача"
            elif "ее" in clean or "её" in clean:
                target = "её"

            new_date = clean
            for prefix in ["перенеси", "сдвинь", "отложи", "её", "ее", "встречу", "задачу", "на"]:
                new_date = re.sub(rf"\b{prefix}\b", "", new_date).strip()

            return "update_event", {
                "target_query": target,
                "new_datetime_str": new_date or "завтра"
            }, None

        if re.search(r"(?:отметь\b.*\bвыполнен|выполнен|сделал\b|выполнил\b|заверши\b)", clean):
            target = "задача"
            match = re.search(r"(?:отметь\s+)?(?:задач[уаеы]|дело|встреч[уаеы])\s+([^,.?!]+?)(?:\s+выполнен|\s+завершен|$)", clean)
            if match:
                target = match.group(1).strip()
            return "complete_event", {"target_query": target}, None

        if re.search(r"\b(удали|отмени|стереть)\b", clean):
            target = "запись"
            match = re.search(r"(?:удали|отмени|стереть)\s+([^,.?!]+)", clean)
            if match:
                target = match.group(1).strip()
            return "delete_event", {"target_query": target}, None

        if re.search(r"\b(найди|когда у меня была|я когда-то ставил|вспомни|поищи)\b", clean):
            q = clean
            for prefix in [
                "найди задачу про", "найди задачу о", "найди задачу", "найди встречу про", "найди встречу", "найди",
                "когда у меня была встреча с", "когда у меня была встреча", "когда у меня была",
                "я когда-то ставил задачу по", "я когда-то ставил задачу про", "я когда-то ставил задачу",
                "я когда-то ставил", "поищи", "найди ее", "найди её"
            ]:
                if q.startswith(prefix):
                    q = q[len(prefix):].strip()
                    break

            q = re.sub(r"[,.?!]", "", q).strip()
            q = re.sub(r"\b(найди|ее|её)\b", "", q).strip()
            rec_type = "meeting" if "встреч" in clean else ("task" if "задач" in clean else "all")
            return "search_events", {"query": q or text, "record_type": rec_type}, None

        if re.search(r"\b(что у меня|какие планы|покажи мои встречи|есть ли у меня|какие задачи|что запланировано|покажи расписание|планы на)\b", clean):
            period = "all"
            if "сегодня" in clean:
                period = "today"
            elif "завтра" in clean:
                period = "tomorrow"
            elif "на эту неделю" in clean or "на этой неделе" in clean:
                period = "this_week"
            elif "на следующей неделе" in clean or "на следующую неделю" in clean:
                period = "next_week"

            rec_type = "all"
            if "встреч" in clean:
                rec_type = "meeting"
            elif "задач" in clean:
                rec_type = "task"

            return "list_events", {"period": period, "record_type": rec_type}, None

        if "встреч" in clean:
            parsed_time, has_time = self.date_parser.parse_time_component(clean)
            has_explicit_date_or_time = self.date_parser.parse(clean, base_dt=now).has_explicit_time

            title = text
            match = re.search(r"(?:добавь|создай|поставь|запланируй)?\s*встреч[уаеы]?\s*(?:с\s+)?([^,.?!]+)", clean)
            if match:
                raw_sub = match.group(1).strip()
                cleaned_sub = re.sub(r"\b(завтра|сегодня|послезавтра)\b|\bв\s+\d{1,2}:\d{2}\b|\b\d{1,2}:\d{2}\b|\bв\s+\d{1,2}\b|\bв\s+\w+\b", "", raw_sub).strip()
                cleaned_sub = re.sub(r"[\s:]+$", "", cleaned_sub).strip()
                title = f"Встреча с {cleaned_sub}" if cleaned_sub else "Встреча"
            else:
                title = "Встреча"

            if not has_time and not has_explicit_date_or_time:
                return "ask_clarification", {
                    "question": "На какое время поставить встречу?",
                    "missing_field": "time",
                    "pending_action": "create_meeting",
                    "partial_data": {"title": title, "raw_text": text}
                }, None

            dt_extracted = clean
            for trigger in ["добавь", "создай", "поставь", "у меня", "встреча", "встречу", "с командой", "с дизайнером"]:
                dt_extracted = re.sub(rf"\b{trigger}\b", "", dt_extracted).strip()

            return "create_meeting", {
                "title": title or "Встреча",
                "datetime_str": dt_extracted or clean,
                "raw_text": text
            }, None

        clean_task = text
        for trigger in [
            "напомни мне", "напомни", "нужно", "поставь задачу", "создай задачу", "добавь задачу",
            "поставить задачу", "напоминание"
        ]:
            if clean_task.lower().startswith(trigger):
                clean_task = clean_task[len(trigger):].strip()
                break

        title = clean_task
        dt_extracted = None

        match_delta = re.search(r"\b(через\s+(?:полчаса|[\w\d]+\s*(?:час\w*|минут\w*|дн\w*|ден\w*)))\b", clean_task, re.IGNORECASE)
        if match_delta:
            dt_extracted = match_delta.group(1).strip()
            title = re.sub(rf"(?i)\b{re.escape(dt_extracted)}\b", "", title).strip()
        else:
            date_triggers = [
                "завтра в 10 утра", "завтра в 15:00", "до конца недели", "на следующей неделе",
                "в пятницу", "в четверг", "сегодня", "завтра", "послезавтра"
            ]
            for dt_pattern in date_triggers:
                if dt_pattern in clean.lower():
                    dt_extracted = dt_pattern
                    title = re.sub(rf"(?i)\b{dt_pattern}\b", "", title).strip()
                    break

        title = re.sub(r"^(?:что|чтобы|надо|нужно|сделать|о)\s+", "", title, flags=re.IGNORECASE).strip()

        rec_type = "reminder" if "напомни" in clean else "task"
        return "create_task", {
            "title": title or text,
            "datetime_str": dt_extracted,
            "record_type": rec_type,
            "raw_text": text
        }, None
