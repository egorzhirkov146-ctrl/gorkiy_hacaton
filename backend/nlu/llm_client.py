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

        # 1. Вежливый диалог, приветствия, помощь, подтверждения и отмена
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

        if re.search(r"^(?:хорошо|ок|окей|ладно|понятно|ясно|договорились|принято|понял|всё понятно|все понятно)\b", clean):
            return "conversation", {
                "reply": "Договорились! Обращайтесь, если потребуется что-то запланировать.",
                "sub_type": "ack"
            }, None

        if re.search(r"^(?:отмена|отбой|не надо|стоп|передумал|забудь|отставить)\b", clean):
            return "conversation", {
                "reply": "Хорошо, действие отменено.",
                "sub_type": "cancel"
            }, None

        if re.search(r"\b(?:как\s+дела|как\s+жизнь|как\s+ты|как\s+поживаешь)\b", clean):
            return "conversation", {
                "reply": "Всё отлично, готов помочь с вашими задачами и расписанием!",
                "sub_type": "smalltalk"
            }, None

        if re.search(r"\b(?:кто\s+ты|ты\s+кто|как\s+тебя\s+зовут|что\s+ты\s+такое)\b", clean):
            return "conversation", {
                "reply": "Я ваш голосовой ассистент для управления личными задачами, встречами и расписанием.",
                "sub_type": "identity"
            }, None

        # 2. Уточняющий диалог
        if len(messages) >= 2:
            unresolved_time_question = False
            unresolved_title_question = False
            last_meeting_user_msg = ""
            last_time_user_msg = ""
            for m in reversed(messages[:-1]):
                role = m.get("role")
                content = m.get("content", "").lower()
                if role == "assistant":
                    if "запланировал:" in content or ("событие" in content and "перенесено" in content) or "записал" in content:
                        break
                    if "?" in content and ("какую задачу" in content or "какую встречу" in content or "какое событие" in content or "что поставить" in content):
                        unresolved_title_question = True
                    elif "?" in content and ("время" in content or "во сколько" in content or "на какое время" in content):
                        unresolved_time_question = True
                elif role == "user":
                    if unresolved_time_question and not last_meeting_user_msg:
                        if any(w in content for w in ("встреч", "созвон", "митинг")):
                            last_meeting_user_msg = m.get("content", "")
                    elif unresolved_title_question and not last_time_user_msg:
                        last_time_user_msg = m.get("content", "")

            has_new_intent = bool(
                re.search(
                    r"^(?:напомни|поставь задачу|создай задачу|добавь задачу|нужно|надо|купи|отправь|позвони|сделай|найди|поищи|что у меня|какие планы|какие задачи|список)\b",
                    clean,
                )
            )
            has_own_meeting_subject = bool(
                re.search(r"(?:встреч\w*|созвон\w*|митинг\w*)\s+(?:с\s+|со\s+|по\s+|для\s+)?([^,.?!]+)", clean)
            )

            if unresolved_title_question and last_time_user_msg:
                from datetime import timedelta, time as dt_time
                prev_t, has_prev_t = self.date_parser.parse_time_component(last_time_user_msg)
                prev_parsed = self.date_parser.parse(last_time_user_msg, base_dt=now)
                time_val = prev_t or (prev_parsed.dt.time() if prev_parsed.dt else dt_time(12, 0))
                
                curr_parsed = self.date_parser.parse(clean, base_dt=now)
                if curr_parsed.has_explicit_date and curr_parsed.dt:
                    date_val = curr_parsed.dt.date()
                elif prev_parsed.has_explicit_date and prev_parsed.dt:
                    date_val = prev_parsed.dt.date()
                else:
                    date_val = (now + timedelta(days=1)).date() if now.time() > time_val else now.date()

                combined_dt = datetime.combine(date_val, time_val).isoformat()

                if any(w in clean for w in ("встреч", "созвон", "митинг")):
                    m_kind = "Созвон" if "созвон" in clean else ("Митинг" if "митинг" in clean else "Встреча")
                    match_m = re.search(r"(?:встреч\w*|созвон\w*|митинг\w*)\s+([^,.?!]+)", clean, re.IGNORECASE)
                    if match_m:
                        sub = match_m.group(1).strip()
                        sub = re.sub(r"^(?:с|со|по|для|о|об)\s+", "", sub).strip()
                        m_title = f"{m_kind} с {sub}" if sub else m_kind
                    else:
                        m_title = m_kind
                    return "create_meeting", {
                        "title": m_title,
                        "datetime_str": combined_dt,
                        "raw_text": f"{m_title} {combined_dt}"
                    }, None
                else:
                    task_clean = re.sub(r"^(?:поставь\s+задачу|добавь\s+задачу|создай\s+задачу|задача|напомни)\s*", "", clean).strip()
                    t_title = task_clean or clean
                    rec_k = "reminder" if "напомни" in clean else "task"
                    return "create_task", {
                        "title": t_title,
                        "datetime_str": combined_dt,
                        "record_type": rec_k,
                        "raw_text": f"{t_title} {combined_dt}"
                    }, None

            if unresolved_time_question and not has_new_intent and not has_own_meeting_subject:
                parsed_t, has_t = self.date_parser.parse_time_component(clean)
                parsed_self = self.date_parser.parse(clean, base_dt=now)

                if has_t or parsed_self.has_explicit_time:
                    meeting_title = "Встреча"
                    prev_date: Optional[datetime] = None

                    u_prev = last_meeting_user_msg
                    if not u_prev:
                        for m in reversed(messages[:-1]):
                            if m.get("role") == "user" and any(w in m.get("content", "").lower() for w in ("встреч", "созвон", "митинг")):
                                u_prev = m.get("content", "")
                                break

                    if u_prev:
                        m_kind = "Созвон" if "созвон" in u_prev.lower() else ("Митинг" if "митинг" in u_prev.lower() else "Встреча")
                        match_m = re.search(r"(?:встреч\w*|созвон\w*|митинг\w*)\s+([^,.?!]+)", u_prev, re.IGNORECASE)
                        if match_m:
                            raw_sub = match_m.group(1).strip()
                            cleaned_sub = re.sub(
                                r"\bчерез\s+(?:полчаса|полтора\s+часа|пару\s+часов|пару\s+дней|час|часик|день|неделю|\w+\s*(?:час\w*|минут\w*|дн\w*|ден\w*|недел\w*))\b|"
                                r"\b(завтра|сегодня|послезавтра|вчера|до конца недели|на следующей неделе)\b|"
                                r"\b(?:в|к|на)\s+\d{1,2}(?::\d{2})?\b|\b\d{1,2}:\d{2}\b|"
                                r"\b(?:в|во|до|к|на)?\s*(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+)\b|"
                                r"\b\d{1,2}\s*(?:ч|час|часа|часов)?\s*(?:утра|ночи|дня|вечера)?\b|"
                                r"\b(?:утра|ночи|дня|вечера)\b",
                                "", raw_sub, flags=re.IGNORECASE
                            ).strip()
                            cleaned_sub = re.sub(r"[\s:]+$", "", cleaned_sub).strip()
                            if cleaned_sub.startswith(("с ", "со ", "по ", "для ", "о ", "об ")):
                                meeting_title = f"{m_kind} {cleaned_sub}"
                            elif cleaned_sub:
                                meeting_title = f"{m_kind} с {cleaned_sub}"
                            else:
                                meeting_title = m_kind

                        parsed_prev = self.date_parser.parse(u_prev, base_dt=now)
                        if parsed_prev.dt:
                            prev_date = parsed_prev.dt

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
            new_date = clean
            m_resched = re.search(r"\b(?:перенеси|сдвинь|отложи)\s+(.*?)\s+(?:на|к|до)\s+(.+)", clean)
            if m_resched:
                target_raw = m_resched.group(1).strip()
                new_date = m_resched.group(2).strip()
                cleaned_target = re.sub(r"^(?:встреч[уаеы]|задач[уаеы]|созвон\w*|митинг\w*|дело)\s*", "", target_raw).strip()
                target = cleaned_target if cleaned_target else target_raw
            else:
                if "встреч" in clean:
                    target = "встреча"
                elif "задач" in clean:
                    target = "задача"
                elif "ее" in clean or "её" in clean:
                    target = "её"
                for prefix in ["перенеси", "сдвинь", "отложи", "её", "ее", "встречу", "задачу", "на"]:
                    new_date = re.sub(rf"\b{prefix}\b", "", new_date).strip()

            return "update_event", {
                "target_query": target,
                "new_datetime_str": new_date or "завтра"
            }, None

        # 4. Отметка выполненным (complete_event)
        if re.search(r"(?:отметь\b.*\bвыполнен|выполнен|сделал\b|выполнил\b|заверши\b)", clean):
            target = "задача"
            match = re.search(r"(?:отметь\s+)?(?:выполнен\w*\s+)?(?:задач[уаеы]|дело|встреч[уаеы])\s+([^,.?!]+?)(?:\s+выполнен|\s+завершен|\s+как\s+сделанн|$)", clean)
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
            elif any(w in clean for w in ("понедельник", "вторник", "сред", "четверг", "пятниц", "суббот", "воскресень")):
                period = "custom"

            rec_type = "all"
            if "встреч" in clean:
                rec_type = "meeting"
            elif "задач" in clean or "напоминан" in clean:
                rec_type = "task"

            return "list_events", {"period": period, "record_type": rec_type}, None

        # 7. Поиск старых записей (search_events)
        search_prefix_regex = re.compile(
            r"^(?:"
            r"когда\s+(?:у\s+нас\s+|у\s+меня\s+)?(?:был[аои]?\s+|будет\s+|запланирован[аоы]?\s+)?(?:встреч\w*|созвон\w*|митинг\w*)?\s*(?:с\s+|со\s+|по\s+)?|"
            r"я\s+(?:когда-то\s+)?(?:ставил|создавал|заводил|писал)\s*(?:задач\w*|напоминан\w*|встреч\w*|дело)?\s*(?:по\s+|про\s+|о\s+|об\s+|обо\s+|на\s+)?|"
            r"(?:найди|поищи|поиск|вспомни|где|покажи)\s+(?:мне\s+)?(?:пожалуйста,\s*)?(?:информацию\s+)?(?:про\s+|по\s+|о\s+|об\s+|обо\s+)?(?:задач\w*|встреч\w*|созвон\w*|митинг\w*|дело|заметк\w*|напоминан\w*)?\s*(?:про\s+|по\s+|о\s+|об\s+|обо\s+|с\s+|со\s+|для\s+)?|"
            r"что\s+там\s+(?:с\s+|со\s+|по\s+)"
            r")",
            re.IGNORECASE
        )

        is_search_match = search_prefix_regex.match(clean) or re.search(
            r"\b(найди|поищи|поиск|вспомни|где|я когда-то ставил|что там с|что там по)\b", clean
        ) or (
            clean.startswith("когда") and any(w in clean for w in ("встреч", "созвон", "митинг", "задач", "был", "будет"))
        ) or (
            clean.startswith("покажи") and not re.search(r"\b(мои|все|планы|расписание|сегодня|завтра|недел)\b", clean)
        )

        if is_search_match:
            q = search_prefix_regex.sub("", clean).strip(" ,.?!") if search_prefix_regex.match(clean) else clean
            for prefix in [
                "найди мне задачу про", "найди мне задачу по", "найди мне задачу о", "найди мне задачу", "найди мне",
                "найди задачу про", "найди задачу по", "найди задачу о", "найди задачу",
                "найди встречу про", "найди встречу с", "найди встречу", "найди",
                "когда у меня была встреча с", "когда у меня была встреча", "когда у меня была",
                "когда была встреча с", "когда была встреча", "когда был созвон с", "когда был созвон",
                "когда встреча с", "когда встреча", "когда созвон с", "когда созвон",
                "я когда-то ставил задачу по", "я когда-то ставил задачу про", "я когда-то ставил задачу",
                "я когда-то ставил", "поищи", "поиск", "вспомни про", "вспомни о", "вспомни",
                "где моя", "где мой", "где", "что там с", "что там по", "покажи задачу про",
                "покажи задачу по", "покажи задачу о", "покажи задачу", "покажи", "найди ее", "найди её"
            ]:
                if q.startswith(prefix):
                    q = q[len(prefix):].strip()
                    break

            q = re.sub(r"[,.?!]", "", q).strip()
            q = re.sub(r"\b(найди|ее|её|задачу|встречу|созвон)\b", "", q).strip()
            rec_type = "meeting" if any(w in clean for w in ("встреч", "созвон", "митинг")) else ("task" if "задач" in clean else "all")
            return "search_events", {"query": q or text, "record_type": rec_type}, None

        # 8. Создание встречи (create_meeting или ask_clarification)
        if "встреч" in clean or "созвон" in clean or "митинг" in clean:
            parsed_time, has_time = self.date_parser.parse_time_component(clean)
            has_explicit_date_or_time = self.date_parser.parse(clean, base_dt=now).has_explicit_time

            kind = "Созвон" if "созвон" in clean else ("Митинг" if "митинг" in clean else "Встреча")
            title = kind

            match = re.search(r"(?:добавь|создай|поставь|запланируй|у меня)?\s*(?:встреч\w*|созвон\w*|митинг\w*)\s+([^,.?!]+)", clean)
            if not match:
                match = re.search(r"(?:встреч\w*|созвон\w*|митинг\w*)\s+([^,.?!]+)", clean)

            if match:
                raw_sub = match.group(1).strip()
                cleaned_sub = re.sub(
                    r"\b\d{1,2}\s+(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[яеи]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\b|"
                    r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b|"
                    r"\bчерез\s+(?:полчаса|полтора\s+часа|пару\s+часов|пару\s+дней|час|часик|день|неделю|\w+\s*(?:час\w*|минут\w*|дн\w*|ден\w*|недел\w*))\b|"
                    r"\b(завтра|сегодня|послезавтра|вчера|до конца недели|на следующей неделе)\b|"
                    r"\b(?:в|к|на)\s+\d{1,2}(?::\d{2})?\b|\b\d{1,2}:\d{2}\b|"
                    r"\b(?:в|во|до|к|на)?\s*(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w+|суббот\w+|воскресень\w+)\b|"
                    r"\b\d{1,2}\s*(?:ч|час|часа|часов)?\s*(?:утра|ночи|дня|вечера)?\b|"
                    r"\b(?:утра|ночи|дня|вечера)\b",
                    "", raw_sub, flags=re.IGNORECASE
                ).strip()
                cleaned_sub = re.sub(r"[\s:]+$", "", cleaned_sub).strip()
                if cleaned_sub.startswith(("с ", "со ", "по ", "для ", "о ", "об ")):
                    title = f"{kind} {cleaned_sub}"
                elif cleaned_sub:
                    title = f"{kind} с {cleaned_sub}"
                else:
                    title = kind

            if not has_time and not has_explicit_date_or_time:
                return "ask_clarification", {
                    "question": "На какое время поставить встречу?",
                    "missing_field": "time",
                    "pending_action": "create_meeting",
                    "partial_data": {"title": title, "raw_text": text}
                }, None

            parsed_meeting_dt = self.date_parser.parse(clean, base_dt=now)
            dt_str_val = parsed_meeting_dt.iso or clean

            return "create_meeting", {
                "title": title or "Встреча",
                "datetime_str": dt_str_val,
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
            if dt_extracted:
                return "ask_clarification", {
                    "question": "Уточните, пожалуйста, какую задачу или встречу поставить на это время?",
                    "missing_field": "title",
                    "pending_action": "create_event",
                    "partial_data": {"datetime_str": dt_extracted}
                }, None
            title = text.strip()

        rec_type = "reminder" if re.search(r"\bнапомни\b", clean) else "task"
        return "create_task", {
            "title": title,
            "datetime_str": dt_extracted,
            "record_type": rec_type,
            "raw_text": text
        }, None
