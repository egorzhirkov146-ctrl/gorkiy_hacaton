import json
import re
import ssl
import time
import uuid
import urllib.request
import urllib.error
from urllib.parse import urlencode
from datetime import datetime
from typing import Optional, Any
from openai import OpenAI

from backend.config import settings
from backend.nlu.tools import TOOLS_DEFINITIONS
from backend.nlu.prompts import build_system_prompt
from backend.nlu.date_parser import RussianDateParser, RU_WEEKDAYS

_GIGACHAT_TOKEN = ""
_GIGACHAT_TOKEN_EXPIRES = 0


def get_gigachat_token(auth_key: str, scope: str = "GIGACHAT_API_PERS") -> Optional[str]:
    global _GIGACHAT_TOKEN, _GIGACHAT_TOKEN_EXPIRES
    if not auth_key:
        return None
    if _GIGACHAT_TOKEN and time.time() < _GIGACHAT_TOKEN_EXPIRES:
        return _GIGACHAT_TOKEN

    auth = auth_key.strip()
    if not auth.lower().startswith("basic "):
        auth = f"Basic {auth}"

    req = urllib.request.Request(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=urlencode({"scope": scope}).encode("ascii"),
        headers={
            "Authorization": auth,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
        },
        method="POST"
    )
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _GIGACHAT_TOKEN = data.get("access_token", "")
            _GIGACHAT_TOKEN_EXPIRES = data.get("expires_at", 0) / 1000 - 60
            return _GIGACHAT_TOKEN
    except Exception:
        return None


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.base_url = base_url or settings.llm_base_url

        if self.base_url or (self.api_key and self.api_key not in ("", "sk-...", "your-key-here")):
            self.client = OpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.base_url,
            )
        else:
            self.client = None

        self.date_parser = RussianDateParser(default_tz=settings.tz)

    def is_live(self) -> bool:
        return self.client is not None

    def _call_gigachat(
        self,
        messages: list[dict[str, str]],
        now: datetime
    ) -> Optional[tuple[str, dict[str, Any], Optional[str]]]:
        auth_key = settings.get_gigachat_key()
        token = get_gigachat_token(auth_key, settings.gigachat_scope)
        if not token:
            return None

        formatted_messages = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                formatted_messages.append({"role": m.get("role", "user"), "content": content})

        body = {
            "model": settings.gigachat_model,
            "messages": formatted_messages,
            "temperature": 0.0,
            "max_tokens": 1000,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST"
        )
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=settings.llm_timeout_sec, context=ctx) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                choice = resp_data["choices"][0]["message"]
                content = choice.get("content", "").strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rstrip("`").strip()
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        if "function" in parsed:
                            return parsed["function"], parsed.get("arguments", {}), content
                        if "type" in parsed:
                            action_type = parsed["type"]
                            if action_type == "create":
                                tool = "create_meeting" if parsed.get("kind") == "meeting" else "create_task"
                                return tool, parsed, content
                            elif action_type == "list":
                                return "list_events", parsed, content
                            elif action_type == "search":
                                return "search_events", parsed, content
                        if "reply" in parsed and parsed["reply"]:
                            return "conversation", {"reply": parsed["reply"]}, parsed["reply"]
                except Exception:
                    pass
                if content:
                    return "conversation", {"reply": content}, content
        except Exception:
            return None
        return None

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
                elif message.content:
                    return "conversation", {"reply": message.content.strip()}, message.content
            except Exception:
                pass

        if settings.get_gigachat_key():
            g_res = self._call_gigachat(messages, current_dt)
            if g_res:
                return g_res

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
        clean = (text or "").lower().strip()
        if not clean:
            return "unknown", {}, None

        # 1. Вежливый диалог, приветствия, помощь и благодарности
        if re.search(r"^(?:привет|здравствуй|здравствуйте|добрый день|доброе утро|добрый вечер|салют|хай)\b", clean):
            return "conversation", {
                "reply": "Здравствуйте! Я ваш голосовой ассистент. Могу записать задачу, назначить встречу, найти старые записи или показать расписание.",
                "sub_type": "greeting"
            }, None

        if re.search(r"^(?:спасибо|благодарю|отлично|супер|спасибо большое)\b", clean):
            return "conversation", {
                "reply": "Пожалуйста! Обращайтесь, если потребуется что-то запланировать.",
                "sub_type": "thanks"
            }, None

        if re.search(r"^(?:пока|до свидания|всего доброго|до встречи|прощай)\b", clean):
            return "conversation", {
                "reply": "До свидания! Хорошего вам дня!",
                "sub_type": "bye"
            }, None

        if re.search(r"^(?:помощь|справка|что ты умеешь|как пользоваться|команды|help)\b", clean):
            return "conversation", {
                "reply": "Я умею создавать задачи и напоминания ('Напомни завтра в 10 утра позвонить Ивану'), планировать встречи ('Добавь встречу с дизайнером в четверг в 11'), показывать планы ('Что у меня сегодня?') и искать старые дела ('Найди задачу про договор').",
                "sub_type": "help"
            }, None

        # 2. Уточняющий диалог (ответ пользователя на вопрос ассистента о времени)
        if len(messages) >= 2:
            last_assistant = ""
            for m in reversed(messages[:-1]):
                if m.get("role") == "assistant":
                    last_assistant = m.get("content", "").lower()
                    break

            if "время" in last_assistant or "во сколько" in last_assistant:
                parsed_t, has_t = self.date_parser.parse_time_component(clean)
                parsed_self = self.date_parser.parse(clean, base_dt=now)


                # Должно быть указано именно время! Если пользователь повторил запрос без времени, не считаем это ответом на время.
                if has_t or parsed_self.has_explicit_time:
                    meeting_title = "Встреча"
                    prev_date: Optional[datetime] = None

                    for m in reversed(messages[:-1]):
                        if m.get("role") == "user":
                            u_prev = m.get("content", "")
                            if "встреч" in u_prev.lower():
                                match_m = re.search(r"встреч[уаеы]?\s+(?:с\s+)?([^,.?!]+)", u_prev, re.IGNORECASE)
                                if match_m:
                                    raw_sub = match_m.group(1).strip()
                                    cleaned_sub = re.sub(
                                        r"\b(завтра|сегодня|послезавтра|вчера|до конца недели|на следующей неделе|в\s+\w+)\b",
                                        "", raw_sub, flags=re.IGNORECASE
                                    ).strip()
                                    meeting_title = f"Встреча с {cleaned_sub}" if cleaned_sub else "Встреча"

                                parsed_prev = self.date_parser.parse(u_prev, base_dt=now)
                                if parsed_prev.dt:
                                    prev_date = parsed_prev.dt
                                break

                    has_explicit_date_word = bool(re.search(
                        r"\b(?:сегодня|завтра|послезавтра|до\s+конца\s+недели|на\s+следующей\s+неделе|на\s+этой\s+неделе|на\s+выходных|"
                        r"(?:в|во|до|к|на)?\s*(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+))\b",
                        clean
                    ))

                    if has_explicit_date_word and parsed_self.dt and parsed_self.has_explicit_time:
                        full_datetime = parsed_self.dt.isoformat()
                    else:
                        from datetime import timedelta, time as dt_time
                        base_d = prev_date.date() if prev_date else (now + timedelta(days=1)).date()
                        time_val = parsed_t or (parsed_self.dt.time() if parsed_self.dt else dt_time(12, 0))
                        full_datetime = datetime.combine(base_d, time_val).isoformat()

                    return "create_meeting", {
                        "title": meeting_title,
                        "datetime_str": full_datetime,
                        "raw_text": f"{meeting_title} {full_datetime}"
                    }, None

        # 3. Перенос / изменение событий (update_event)
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

        # 4. Отметка выполненным (complete_event)
        if re.search(r"(?:отметь\b.*\bвыполнен|выполнен|сделал\b|выполнил\b|заверши\b)", clean):
            target = "задача"
            match = re.search(r"(?:отметь\s+)?(?:задач[уаеы]|дело|встреч[уаеы])\s+([^,.?!]+?)(?:\s+выполнен|\s+завершен|$)", clean)
            if match:
                target = match.group(1).strip()
            return "complete_event", {"target_query": target}, None

        # 5. Удаление события (delete_event)
        if re.search(r"\b(удали|отмени|стереть)\b", clean):
            target = "запись"
            match = re.search(r"(?:удали|отмени|стереть)\s+([^,.?!]+)", clean)
            if match:
                target = match.group(1).strip()
            return "delete_event", {"target_query": target}, None

        # 6. Получение планов и расписания (list_events)
        list_pattern = (
            r"\b(что у меня|что у нас|какие у меня|какие у нас|какие планы|какие задачи|какие встречи|"
            r"список задач|список встреч|покажи мои|покажи задачи|покажи встречи|покажи все|покажи планы|"
            r"покажи расписание|есть ли у меня|есть ли задачи|есть ли встречи|что запланировано|планы на|"
            r"что в планах|расписание на|мои планы|мои встречи|мои задачи)\b"
        )
        if re.search(list_pattern, clean):
            period = "all"
            if re.search(r"\bсегодня\b", clean):
                period = "today"
            elif re.search(r"\bзавтра\b", clean) and "послезавтра" not in clean:
                period = "tomorrow"
            elif "послезавтра" in clean:
                period = "custom"
            elif "на эту неделю" in clean or "на этой неделе" in clean or "до конца недели" in clean:
                period = "this_week"
            elif "на следующей неделе" in clean or "на следующую неделю" in clean:
                period = "next_week"

            rec_type = "all"
            if "встреч" in clean:
                rec_type = "meeting"
            elif "задач" in clean or "напоминан" in clean:
                rec_type = "task"

            return "list_events", {"period": period, "record_type": rec_type}, None

        # 7. Поиск старых записей (search_events)
        search_pattern = r"\b(найди|поищи|поиск|вспомни|где|когда у меня была|я когда-то ставил|что там с|что там по)\b"
        if re.search(search_pattern, clean):
            q = clean
            for prefix in [
                "найди мне задачу про", "найди мне задачу по", "найди мне задачу о", "найди мне задачу", "найди мне",
                "найди задачу про", "найди задачу по", "найди задачу о", "найди задачу",
                "найди встречу про", "найди встречу с", "найди встречу", "найди",
                "когда у меня была встреча с", "когда у меня была встреча", "когда у меня была",
                "я когда-то ставил задачу по", "я когда-то ставил задачу про", "я когда-то ставил задачу",
                "я когда-то ставил", "поищи", "поиск", "вспомни про", "вспомни о", "вспомни",
                "где моя", "где мой", "где", "что там с", "что там по", "найди ее", "найди её"
            ]:
                if q.startswith(prefix):
                    q = q[len(prefix):].strip()
                    break

            q = re.sub(r"[,.?!]", "", q).strip()
            q = re.sub(r"\b(найди|ее|её|задачу|встречу)\b", "", q).strip()
            rec_type = "meeting" if "встреч" in clean else ("task" if "задач" in clean else "all")
            return "search_events", {"query": q or text, "record_type": rec_type}, None

        # 8. Создание встречи (create_meeting или ask_clarification)
        if "встреч" in clean or "созвон" in clean or "митинг" in clean:
            parsed_time, has_time = self.date_parser.parse_time_component(clean)
            has_explicit_date_or_time = self.date_parser.parse(clean, base_dt=now).has_explicit_time

            title = text
            match = re.search(r"(?:добавь|создай|поставь|запланируй)?\s*встреч[уаеы]?\s*(?:с\s+)?([^,.?!]+)", clean)
            if match:
                raw_sub = match.group(1).strip()
                cleaned_sub = re.sub(
                    r"\b(завтра|сегодня|послезавтра|вчера)\b|\bв\s+\d{1,2}[:.-]\d{2}\b|\b\d{1,2}[:.-]\d{2}\b|\bв\s+\d{1,2}\b|"
                    r"\b(?:в|во|до|к|на)?\s*(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+)\b|"
                    r"\b\d{1,2}\s*(?:ч|час|часа|часов)?\s*(?:утра|ночи|дня|вечера)\b|"
                    r"\b(?:утра|ночи|дня|вечера)\b",
                    "", raw_sub
                ).strip()
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
            for trigger in ["добавь", "создай", "поставь", "у меня", "встреча", "встречу", "созвон"]:
                dt_extracted = re.sub(rf"\b{trigger}\b", "", dt_extracted).strip()

            return "create_meeting", {
                "title": title or "Встреча",
                "datetime_str": dt_extracted or clean,
                "raw_text": text
            }, None

        # 9. Создание задачи или напоминания (create_task)
        clean_task = text
        for trigger in [
            r"^(?:пожалуйста,\s*)?напомни(?:ть)?(?:\s+мне)?\b",
            r"^(?:поставь|создай|добавь|заведи)\s+(?:мне\s+)?(?:задачу|напоминание|заметку|дело)\b",
            r"^(?:нужно|надо|необходимо|следует|хочу|планирую)\s+(?:сделать|поставить)?\b",
            r"^(?:поставить|создать|добавить)\s+(?:задачу|напоминание)\b",
        ]:
            clean_task = re.sub(trigger, "", clean_task, flags=re.IGNORECASE).strip()

        dt_regex = re.compile(
            r"\b(?:сегодня|завтра|послезавтра|до\s+конца\s+недели|на\s+следующей\s+неделе|на\s+этой\s+неделе|на\s+выходных|в\s+выходные|"
            r"(?:в|во|до|к|на)?\s*(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+)|"
            r"через\s+(?:полчаса|полтора\s+часа|пару\s+часов|пару\s+дней|час|часик|день|неделю|\w+\s*(?:час\w*|минут\w*|дн\w*|ден\w*|недел\w*))|"
            r"(?:в|к|на)?\s*\d{1,2}[:.-]\d{2}|"
            r"(?:в|к|на)?\s*\d{1,2}\s*(?:ч|час|часа|часов)?\s*(?:утра|ночи|дня|вечера)|"
            r"(?:в|к|на)\s+\d{1,2}\s*(?:ч|час|часа|часов)?\b|"
            r"утром|днем|днём|вечером|в\s+полдень|в\s+полночь)\b",
            re.IGNORECASE
        )

        found_matches = list(dt_regex.finditer(clean_task))
        dt_extracted = None
        title = clean_task

        if found_matches:
            dt_parts = [m.group(0).strip() for m in found_matches]
            dt_extracted = " ".join(dt_parts)
            for m in reversed(found_matches):
                title = title[:m.start()] + " " + title[m.end():]

        title = re.sub(r"^(?:что|чтобы|надо|нужно|сделать|о|про|быть)\s+", "", title.strip(), flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" ,.?!")

        if not title:
            title = text.strip()

        rec_type = "reminder" if re.search(r"\bнапомни\b", clean) else "task"
        return "create_task", {
            "title": title,
            "datetime_str": dt_extracted,
            "record_type": rec_type,
            "raw_text": text
        }, None
