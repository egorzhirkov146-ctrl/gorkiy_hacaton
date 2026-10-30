import json
import logging
import os
import sqlite3
import time
import uuid
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse


ROOT = Path(__file__).resolve().parent
DB = ROOT / "assistant.db"
LOG_FILE = ROOT / "assistant.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not any(
    isinstance(handler, logging.FileHandler)
    and Path(handler.baseFilename) == LOG_FILE.resolve()
    for handler in logger.handlers
):
    log_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    logger.addHandler(log_handler)
MODEL = "GigaChat-2-Max"
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"type": "string"}},
                "required": ["type"],
                "additionalProperties": True,
            },
        },
        "reply": {"type": "string"},
        "clarify": {"type": "string"},
    },
    "required": ["actions", "reply", "clarify"],
    "additionalProperties": True,
}
SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "event_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["event_ids"],
    "additionalProperties": True,
}
WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def load_env():
    file = ROOT / ".env"
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()
GIGACHAT_AUTH_KEY = os.environ.get("Authorization_key", "").strip()
GIGACHAT_SCOPE = os.environ.get("Scope", "GIGACHAT_API_PERS").strip()
GIGACHAT_TOKEN = ""
GIGACHAT_TOKEN_EXPIRES = 0


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT,
            event_time TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    return db


def chat_session_id(db):
    row = db.execute(
        "SELECT value FROM app_settings WHERE key = 'gigachat_session_id'"
    ).fetchone()
    if row:
        return row["value"]
    value = str(uuid.uuid4())
    db.execute(
        "INSERT INTO app_settings (key, value) VALUES ('gigachat_session_id', ?)",
        (value,),
    )
    db.commit()
    return value


def chat_rows(db, limit=None):
    query = "SELECT role, content FROM chat_history ORDER BY id DESC"
    args = ()
    if limit is not None:
        query += " LIMIT ?"
        args = (limit,)
    rows = db.execute(query, args).fetchall()
    return [dict(row) for row in reversed(rows)]


def event_rows(db):
    rows = db.execute(
        "SELECT id, kind, title, event_date, event_time, status FROM events ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    return [dict(row) for row in rows]


def gigachat_error(message, stage):
    logger.error("GigaChat %s error: %s", stage, message)
    return None, message


def gigachat_token():
    global GIGACHAT_TOKEN, GIGACHAT_TOKEN_EXPIRES
    if not GIGACHAT_AUTH_KEY:
        return gigachat_error("Добавьте Authorization_key в .env.", "authorization")
    if GIGACHAT_TOKEN and time.time() < GIGACHAT_TOKEN_EXPIRES:
        logger.info("Using cached GigaChat authorization token.")
        return GIGACHAT_TOKEN, None

    auth = GIGACHAT_AUTH_KEY
    if not auth.lower().startswith("basic "):
        auth = f"Basic {auth}"
    request = urllib.request.Request(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=urlencode({"scope": GIGACHAT_SCOPE}).encode("ascii"),
        headers={
            "Authorization": auth,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read())
        GIGACHAT_TOKEN = data["access_token"]
        GIGACHAT_TOKEN_EXPIRES = data["expires_at"] / 1000 - 60
        logger.info("GigaChat authorization succeeded.")
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            return gigachat_error("GigaChat не принял Authorization_key из .env.", "authorization")
        if error.code == 429:
            return gigachat_error("GigaChat временно ограничил запросы авторизации.", "authorization")
        return gigachat_error(
            f"GigaChat вернул ошибку авторизации HTTP {error.code}.",
            "authorization",
        )
    except urllib.error.URLError:
        return gigachat_error("Не удалось подключиться к сервису авторизации GigaChat.", "authorization")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return gigachat_error("Не удалось прочитать ответ авторизации GigaChat.", "authorization")
    return GIGACHAT_TOKEN, None


def ask_gigachat(conversation, events, phase="plan", results=None, session_id=None):
    token, error = gigachat_token()
    if not token:
        return None, error

    history = conversation.get("history", []) if isinstance(conversation, dict) else []
    dialog = {
        key: value
        for key, value in conversation.items()
        if key != "history"
    } if isinstance(conversation, dict) else conversation

    if phase == "plan":
        system = (
            "Ты — личный ассистент и сам решаешь, что делать по сообщению. "
            "Верни только JSON: {\"actions\":[...],\"reply\":\"...\",\"clarify\":\"...\"}. "
            "Каждое действие в actions — объект с полем type. Допустимы только create, list, search, update, delete. "
            "create: kind (task/reminder/meeting), title, date (YYYY-MM-DD или null), time (HH:MM или null), "
            "weekday (название дня недели по-русски, например воскресенье; null если даты нет). "
            "Если человек назвал только день недели, укажи weekday и date_is_explicit=false; приложение выберет ближайший такой день. "
            "Если пользователь назвал конкретную календарную дату, укажи date_is_explicit=true и соответствующий weekday, если он назван. "
            "list: kind (task/reminder/meeting/all), date_from, date_to (YYYY-MM-DD или null), event_ids. "
            "search: event_ids — числовые id подходящих записей из списка. "
            "update: event_ids — id изменяемых записей; укажи только меняемые поля из title, kind, date, time, weekday, date_is_explicit, status. "
            "Для изменения существующей записи сначала выбери её по смыслу из переданных events. "
            "delete: event_ids — id удаляемых записей. Удаляй только если пользователь явно попросил удалить. "
            "Если пользователь указал дату, выбирай только записи с этой датой; если подходящих записей несколько и неясно, какие удалить, попроси уточнить. "
            "При update и delete не угадывай запись: если подходящих записей несколько и нельзя понять нужную, верни пустые event_ids и попроси уточнить. "
            "Если пользователь исправляет дату или день недели, обнови ту же запись; не создавай новую. "
            "Если вопрос касается сохранённых задач или встреч, обязательно верни действие search или list; "
            "не отвечай на такой вопрос напрямую, даже если видишь подходящую запись. "
            "Для запроса о человеке или теме без периода верни search и выбери подходящие id. "
            "Для запроса о планах за период верни list, при необходимости ограничь event_ids. "
            "Когда вернул действие, оставь reply пустым: итоговый ответ будет составлен после выполнения действия. "
            "Для приветствий и обычной беседы без действий ответь в reply. "
            "Определи намерение по последнему сообщению пользователя (conversation.message). "
            "Предыдущая история нужна только для контекста и не является новым запросом. "
            "Не повторяй предыдущий ответ и не выполняй действие снова, если последнее сообщение этого прямо не просит. "
            "На приветствие, благодарность, согласие, короткую реакцию, вопрос «почему» или «ещё раз» отвечай как в обычном разговоре, без действий. "
            "«Ещё раз» означает повторить предыдущий ответ, а не повторно выполнять действие с записью. "
            "На «почему» объясни предыдущий ответ по истории беседы; не запускай действие с записью. "
            "Если conversation.pending_confirmation присутствует, последнее сообщение — ответ на указанное уточнение. "
            "Используй исходный запрос, вопрос и предыдущий план вместе с текущими events. "
            "При утвердительном подтверждении продолжи исходное действие и верни его в actions с точными event_ids; "
            "при отказе не выполняй действие. Не утверждай, что действие выполнено, если его нет в actions. "
            "Если встрече не хватает даты или времени, верни пустой actions и вопрос в clarify. "
            "Можно вернуть несколько действий, например сначала create, затем search. "
            "Не выдумывай записи и их id; сопоставляй по смыслу и разным формам имён. "
            "Относительные даты считай от переданных текущих даты и времени. Учитывай весь контекст беседы. "
            "Пример: на вопрос «че там с Иваном?» при записи с id 2 верни "
            "{\"actions\":[{\"type\":\"search\",\"event_ids\":[2]}],\"reply\":\"\"}. "
            "Пример создания: верни create с названием дела, датой YYYY-MM-DD и временем HH:MM."
        )
        user_content = {
            "now": datetime.now().isoformat(timespec="minutes"),
            "calendar": [
                {
                    "date": (date.today() + timedelta(days=offset)).isoformat(),
                    "weekday": WEEKDAYS[(date.today() + timedelta(days=offset)).weekday()],
                    "weekday_index": (date.today() + timedelta(days=offset)).weekday(),
                }
                for offset in range(14)
            ],
            "conversation": dialog,
            "events": events,
        }
    elif phase == "select":
        system = (
            "Выбери из списка записи, подходящие запросу пользователя. "
            "Сопоставляй по смыслу, учитывай имена и разные формы слов. "
            "Если запрос ограничен датой или периодом, сравни его с текущей датой и датами записей; "
            "не выбирай запись, которая не попадает в указанный период. "
            "Не выдумывай id. Верни только JSON вида {\"event_ids\":[числовые id]}."
        )
        user_content = {
            "now": datetime.now().isoformat(timespec="minutes"),
            "conversation": dialog,
            "events": events,
        }
    else:
        system = (
            "Сформулируй короткий естественный ответ на русском языке по запросу и результатам действий. "
            "Не выдумывай факты. Если действие не удалось, честно сообщи об этом. "
            "Если пользователь спрашивает «почему», объясни только известную из истории или результатов причину; "
            "если причина неизвестна, так и скажи и не придумывай её. "
            "Не говори, что действие выполнено, если в результатах указано, что оно не выполнялось. "
            "Для обновления назови, какие данные записи изменены. "
            "Если пользователь исправил дату/день недели, подтверди только фактическую сохранённую дату из результата. "
            "Верни только текст ответа, не JSON и не блок кода."
        )
        user_content = {"conversation": dialog, "results": results}

    messages = [{"role": "system", "content": [{"text": system}]}]
    if isinstance(history, list):
        messages.extend(
            {"role": item["role"], "content": [{"text": item["content"]}]}
            for item in history
            if isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
        )
    messages.append({
        "role": "user",
        "content": [{"text": json.dumps(user_content, ensure_ascii=False)}],
    })
    body = {
        "model": os.environ.get("GIGACHAT_MODEL", MODEL),
        "messages": messages,
        "temperature": 0,
        "max_tokens": 600,
    }
    if phase != "reply":
        body["model_options"] = {
            "response_format": {
                "type": "json_schema",
                "schema": PLAN_SCHEMA if phase == "plan" else SELECT_SCHEMA,
                "strict": True,
            }
        }
    model = body["model"]
    body = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        "https://api.giga.chat/v2/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Session-ID": session_id or "default",
        },
        method="POST",
    )
    logger.info(
        "GigaChat request started: phase=%s model=%s",
        phase,
        model,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw_response = response.read()
            status = getattr(response, "status", 200)
            headers = getattr(response, "headers", None)
            content_type = (
                headers.get_content_type()
                if headers and hasattr(headers, "get_content_type")
                else "unknown"
            )
        logger.info(
            "GigaChat response received: phase=%s http_status=%s content_type=%s bytes=%s",
            phase,
            status,
            content_type,
            len(raw_response),
        )
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            global GIGACHAT_TOKEN, GIGACHAT_TOKEN_EXPIRES
            GIGACHAT_TOKEN = ""
            GIGACHAT_TOKEN_EXPIRES = 0
            return gigachat_error("GigaChat не принял токен доступа.", f"request phase={phase}")
        if error.code == 429:
            return gigachat_error(
                "GigaChat временно ограничил запросы или закончился доступный лимит.",
                f"request phase={phase}",
            )
        if error.code == 404:
            return gigachat_error(
                "GigaChat не нашёл выбранную модель. Проверьте GIGACHAT_MODEL в .env.",
                f"request phase={phase}",
            )
        return gigachat_error(
            f"GigaChat вернул ошибку HTTP {error.code}.",
            f"request phase={phase}",
        )
    except urllib.error.URLError:
        return gigachat_error("Не удалось подключиться к GigaChat.", f"request phase={phase}")

    if not raw_response:
        return gigachat_error(
            f"GigaChat вернул пустой ответ (HTTP {status}).",
            f"response phase={phase}",
        )
    try:
        data = json.loads(raw_response)
    except UnicodeDecodeError:
        return gigachat_error(
            f"Ответ GigaChat не удалось декодировать как UTF-8 (HTTP {status}).",
            f"response phase={phase}",
        )
    except json.JSONDecodeError:
        return gigachat_error(
            f"GigaChat вернул не JSON (HTTP {status}, Content-Type: {content_type}).",
            f"response phase={phase}",
        )

    content = None
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            content = messages[0].get("content")
        if content is None:
            choices = data.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    elif isinstance(content, dict):
        content = content.get("text")
    if isinstance(content, str) and not content.strip():
        if phase == "plan":
            logger.error("GigaChat returned an empty plan response.")
            return {"invalid": True}, None
        if phase == "select":
            return {"event_ids": []}, None
    if not isinstance(content, str) or not content.strip():
        keys = ", ".join(sorted(data)) if isinstance(data, dict) else type(data).__name__
        return gigachat_error(
            f"GigaChat вернул JSON без текста ответа (HTTP {status}; поля: {keys}).",
            f"response phase={phase}",
        )

    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3].strip()
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        if phase == "plan":
            logger.error("GigaChat returned invalid plan JSON.")
            return {"invalid": True}, None
        if phase == "select":
            return {"event_ids": []}, None
        result = {"reply": content}
    if phase != "reply" and not isinstance(result, dict):
        if phase == "plan":
            logger.error("GigaChat returned a plan with unexpected JSON type %s.", type(result).__name__)
            return {"invalid": True}, None
        return {"event_ids": []}, None
    logger.info("GigaChat response parsed: phase=%s result_type=%s", phase, type(result).__name__)
    return result, None


def valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def valid_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def next_weekday(weekday):
    if isinstance(weekday, str) and weekday in WEEKDAYS:
        weekday = WEEKDAYS.index(weekday)
    if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday < 7:
        return None
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def format_event(row):
    kind = {"task": "Задача", "meeting": "Встреча", "reminder": "Напоминание"}.get(row["kind"], "Событие")
    when = ""
    if row["event_date"]:
        day = date.fromisoformat(row["event_date"])
        when = f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d.%m.%Y')}"
        if row["event_time"]:
            when += " в " + row["event_time"]
    elif row["event_time"]:
        when = "в " + row["event_time"]
    status = " · выполнено" if row["status"] == "done" else ""
    return f"{kind}: {row['title']}" + (f" — {when}" if when else "") + status


def get_reply(answer):
    if not isinstance(answer, dict):
        return None
    reply = answer.get("reply")
    if not isinstance(reply, str):
        return None
    try:
        nested = json.loads(reply)
    except json.JSONDecodeError:
        return reply.strip() or None
    if isinstance(nested, dict) and isinstance(nested.get("reply"), str):
        return nested["reply"].strip() or None
    return reply.strip() or None


def normalize_action_type(action):
    action_type = action.get("type")
    if not isinstance(action_type, str):
        return action
    aliases = {
        "delete_event": "delete",
        "delete_record": "delete",
        "remove": "delete",
        "remove_event": "delete",
        "remove_record": "delete",
        "edit": "update",
        "edit_event": "update",
        "modify": "update",
        "update_event": "update",
    }
    normalized = action_type.strip().lower()
    return {**action, "type": aliases.get(normalized, normalized)}


def apply_action(action, db):
    action_type = action.get("type")
    kind = action.get("kind")
    ids = action.get("event_ids")
    if isinstance(ids, list):
        ids = [value for value in ids if isinstance(value, int) and not isinstance(value, bool)]
    else:
        ids = None

    if action_type == "create":
        title = action.get("title")
        if kind not in {"task", "reminder", "meeting"} or not isinstance(title, str) or not title.strip():
            return {"status": "failed", "message": "Модель вернула некорректные данные записи.", "events": []}
        event_date = valid_date(action.get("date"))
        clock = valid_time(action.get("time"))
        weekday = action.get("weekday")
        if weekday is not None:
            expected_date = next_weekday(weekday)
            if expected_date is None:
                return {"status": "failed", "message": "Модель вернула некорректный день недели.", "events": []}
            if action.get("date_is_explicit") is True:
                if not event_date or date.fromisoformat(event_date).weekday() != expected_date.weekday():
                    return {"status": "failed", "message": "Дата не совпадает с указанным днём недели.", "events": []}
            else:
                event_date = expected_date.isoformat()
        if action.get("date") and not event_date:
            return {"status": "failed", "message": "Модель вернула некорректную дату.", "events": []}
        if action.get("time") and not clock:
            return {"status": "failed", "message": "Модель вернула некорректное время.", "events": []}
        if kind == "meeting" and (not event_date or not clock):
            return {"status": "needs_clarification", "events": []}
        db.execute(
            "INSERT INTO events (kind, title, event_date, event_time, created_at) VALUES (?, ?, ?, ?, ?)",
            (kind, title.strip(), event_date, clock, datetime.now().isoformat(timespec="seconds")),
        )
        row = db.execute("SELECT * FROM events WHERE id = last_insert_rowid()").fetchone()
        db.commit()
        return {"status": "completed", "events": [dict(row)]}

    if action_type in {"update", "delete"}:
        if ids is None:
            return {
                "status": "failed",
                "message": "Для изменения записи не удалось определить её id.",
                "events": [],
            }
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {"status": "no_results", "events": []}

        rows = db.execute(
            "SELECT * FROM events WHERE id IN (" + ",".join("?" for _ in ids) + ") ORDER BY id",
            ids,
        ).fetchall()
        if not rows:
            return {"status": "no_results", "events": []}

        if action_type == "delete":
            db.execute(
                "DELETE FROM events WHERE id IN (" + ",".join("?" for _ in ids) + ")",
                ids,
            )
            db.commit()
            return {"status": "completed", "events": [dict(row) for row in rows]}

        updates = {}
        if "title" in action:
            title = action["title"]
            if not isinstance(title, str) or not title.strip():
                return {"status": "failed", "message": "Модель вернула некорректное название записи.", "events": []}
            updates["title"] = title.strip()
        if "kind" in action:
            if action["kind"] not in {"task", "reminder", "meeting"}:
                return {"status": "failed", "message": "Модель вернула некорректный тип записи.", "events": []}
            updates["kind"] = action["kind"]
        if "date" in action:
            event_date = action["date"]
            if event_date is not None:
                event_date = valid_date(event_date)
                if not event_date:
                    return {"status": "failed", "message": "Модель вернула некорректную дату.", "events": []}
            updates["event_date"] = event_date
        if "weekday" in action and action["weekday"] is not None:
            expected_date = next_weekday(action["weekday"])
            if expected_date is None:
                return {"status": "failed", "message": "Модель вернула некорректный день недели.", "events": []}
            if action.get("date_is_explicit") is True:
                event_date = valid_date(action.get("date"))
                expected_weekday = WEEKDAYS.index(action["weekday"]) if isinstance(action["weekday"], str) and action["weekday"] in WEEKDAYS else action["weekday"]
                if (
                    not event_date
                    or not isinstance(expected_weekday, int)
                    or date.fromisoformat(event_date).weekday() != expected_weekday
                ):
                    return {"status": "failed", "message": "Дата не совпадает с указанным днём недели.", "events": []}
                updates["event_date"] = event_date
            else:
                updates["event_date"] = expected_date.isoformat()
        if "time" in action:
            clock = action["time"]
            if clock is not None:
                clock = valid_time(clock)
                if not clock:
                    return {"status": "failed", "message": "Модель вернула некорректное время.", "events": []}
            updates["event_time"] = clock
        if "status" in action:
            if action["status"] not in {"open", "done"}:
                return {"status": "failed", "message": "Модель вернула некорректный статус записи.", "events": []}
            updates["status"] = action["status"]
        if not updates:
            return {"status": "failed", "message": "Модель не указала, что именно изменить.", "events": []}

        for row in rows:
            merged = dict(row)
            merged.update(updates)
            if merged["kind"] == "meeting" and (not merged["event_date"] or not merged["event_time"]):
                return {
                    "status": "needs_clarification",
                    "message": "Для встречи нужны дата и время.",
                    "events": [],
                }

        updated_rows = []
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values())
        for row in rows:
            db.execute(
                f"UPDATE events SET {assignments} WHERE id = ?",
                [*values, row["id"]],
            )
            updated = db.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
            updated_rows.append(dict(updated))
        db.commit()
        return {"status": "completed", "events": updated_rows}

    if action_type in {"search", "list"}:
        if action_type == "search" and ids is None:
            return {"status": "needs_event_selection", "events": []}
        sql = "SELECT * FROM events WHERE 1 = 1"
        args = []
        date_from = action.get("date_from")
        date_to = action.get("date_to")
        if action_type == "list" and date_from:
            date_from = valid_date(date_from)
            if not date_from:
                return {"status": "failed", "message": "Модель вернула некорректную начальную дату.", "events": []}
            sql += " AND event_date >= ?"
            args.append(date_from)
        if action_type == "list" and date_to:
            date_to = valid_date(date_to)
            if not date_to:
                return {"status": "failed", "message": "Модель вернула некорректную конечную дату.", "events": []}
            sql += " AND event_date <= ?"
            args.append(date_to)
        if kind in {"task", "reminder", "meeting"}:
            sql += " AND kind = ?"
            args.append(kind)
        if ids is not None:
            if not ids:
                return {"status": "no_results", "events": []}
            sql += " AND id IN (" + ",".join("?" for _ in ids) + ")"
            args.extend(ids)
        sql += " ORDER BY event_date, event_time, id LIMIT 100"
        rows = [dict(row) for row in db.execute(sql, args).fetchall()]
        return {"status": "completed" if rows else "no_results", "events": rows}

    return {"status": "failed", "message": "Модель предложила неизвестное действие.", "events": []}


def action_results(plan, db, conversation, session_id):
    actions = plan.get("actions", [])
    if not isinstance(actions, list):
        return None, "GigaChat вернул неверный список действий."
    if len(actions) > 10:
        return None, "GigaChat предложил слишком много действий за один запрос."

    done = []
    found = []
    for action in actions:
        if isinstance(action, str):
            action = {"type": action}
        if not isinstance(action, dict):
            return None, "GigaChat вернул действие в неверном формате."
        action = normalize_action_type(action)
        if action.get("type") not in {"create", "list", "search", "update", "delete"}:
            return None, (
                f"GigaChat предложил неподдерживаемое действие "
                f"«{action.get('type', '')}». Записи не изменены."
            )
        if action.get("type") in {"search", "update", "delete"} and not isinstance(action.get("event_ids"), list):
            selected, error = ask_gigachat(
                conversation, event_rows(db), "select", session_id=session_id
            )
            if error:
                return None, error
            if not isinstance(selected, dict) or not isinstance(selected.get("event_ids"), list):
                return None, "GigaChat не смог выбрать подходящие записи."
            action = {**action, "event_ids": selected.get("event_ids", [])}
        if action.get("type") in {"update", "delete"} and not action.get("event_ids"):
            return {
                "clarify": True,
                "results": [{
                    "action": action["type"],
                    "status": "needs_clarification",
                    "message": "Не удалось однозначно определить запись. Уточните её название или дату.",
                    "events": [],
                }],
            }, None
        result = apply_action(action, db)
        if action.get("type") == "list" and result["status"] == "no_results":
            selected, error = ask_gigachat(
                conversation, event_rows(db), "select", session_id=session_id
            )
            if error:
                return None, error
            if not isinstance(selected, dict) or not isinstance(selected.get("event_ids"), list):
                return None, "GigaChat не смог проверить записи за этот период."
            result = apply_action(
                {
                    "type": "search",
                    "kind": action.get("kind"),
                    "event_ids": selected["event_ids"],
                },
                db,
            )
        if result["status"] == "needs_clarification":
            return {"clarify": True, "results": [{
                "action": action.get("type"),
                "status": "needs_clarification",
                "message": result.get("message", "Нужно уточнить данные записи."),
                "events": [],
            }]}, None
        found.extend(result["events"])
        done.append({
            "action": action.get("type"),
            "status": result["status"],
            "message": result.get("message"),
            "events": [format_event(row) for row in result["events"]],
        })
    return {"results": done, "events": found}, None


def handle_chat(text, context=""):
    logger.info("Chat request received: characters=%s", len(text))
    db = connect()
    try:
        session_id = chat_session_id(db)
        history = chat_rows(db, 20)
        db.execute(
            "INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)",
            ("user", text, datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()
        conversation = {"history": history, "context": context, "message": text}
        pending_confirmation = None
        if context:
            try:
                context_state = json.loads(context)
            except json.JSONDecodeError:
                context_state = None
            if isinstance(context_state, dict):
                candidate = context_state.get("pending_confirmation")
                if isinstance(candidate, dict):
                    pending_confirmation = candidate
                    conversation["pending_confirmation"] = candidate

        original_request = (
            pending_confirmation.get("request")
            if isinstance(pending_confirmation, dict)
            and isinstance(pending_confirmation.get("request"), str)
            else text
        )

        def confirmation_context(question, plan):
            return json.dumps(
                {
                    "pending_confirmation": {
                        "request": original_request,
                        "question": question,
                        "plan": plan,
                    }
                },
                ensure_ascii=False,
            )

        def finish(result):
            db.execute(
                "INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)",
                ("assistant", result["reply"], datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            logger.info("Chat request completed.")
            return result

        def fail(message):
            logger.error("Chat request failed: %s", message)
            return {"error": message, "events": []}

        plan, error = ask_gigachat(conversation, event_rows(db), session_id=session_id)
        if error:
            return fail(error)
        if not isinstance(plan, dict):
            return fail("GigaChat вернул ответ в неверном формате.")
        if plan.get("invalid"):
            answer, error = ask_gigachat(
                conversation,
                event_rows(db),
                "reply",
                [{"status": "not_executed", "message": "План не разобран, действия не выполнялись."}],
                session_id,
            )
            reply = get_reply(answer)
            if error:
                return fail(error)
            if not reply:
                return fail("GigaChat не вернул текстовый ответ после некорректного плана.")
            return finish({"reply": reply, "events": []})

        actions = plan.get("actions", [])
        if not actions:
            clarify = plan.get("clarify")
            if isinstance(clarify, str) and clarify.strip():
                return finish({
                    "reply": clarify.strip(),
                    "needs_reply": True,
                    "context": confirmation_context(clarify.strip(), plan),
                })
            reply = plan.get("reply")
            if isinstance(reply, str) and reply.strip() and not pending_confirmation:
                return finish({"reply": reply.strip(), "events": []})
            if pending_confirmation:
                results = [{
                    "status": "not_executed",
                    "message": "Действие ещё не выполнено. Для изменения данных нужна соответствующая команда в actions.",
                }]
            else:
                results = [{"status": "not_executed", "message": "Действия не выполнялись."}]
            answer, error = ask_gigachat(
                conversation,
                event_rows(db),
                "reply",
                results,
                session_id,
            )
            reply = get_reply(answer)
            if error:
                return fail(error)
            if not reply:
                return fail("GigaChat не вернул текстовый ответ.")
            return finish({"reply": reply, "events": []})

        completed, error = action_results(plan, db, conversation, session_id)
        if error:
            return fail(error)
        if completed.get("clarify"):
            answer, error = ask_gigachat(
                conversation, event_rows(db), "reply", completed["results"], session_id
            )
            reply = get_reply(answer)
            if error:
                return fail(error)
            if not reply:
                return fail("GigaChat не вернул текст для уточнения.")
            return finish({
                "reply": reply,
                "needs_reply": True,
                "context": confirmation_context(reply, plan),
            })

        answer, error = ask_gigachat(
            conversation, event_rows(db), "reply", completed["results"], session_id
        )
        if error:
            return fail(error)
        reply = get_reply(answer)
        if not isinstance(reply, str) or not reply.strip():
            return fail("GigaChat не вернул текстовый ответ после выполнения действия.")
        unique = {row["id"]: row for row in completed["events"]}
        return finish({"reply": reply, "events": list(unique.values())})
    finally:
        db.close()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/history":
            db = connect()
            try:
                self.send_json(chat_rows(db))
            finally:
                db.close()
            return
        if path == "/api/events":
            db = connect()
            try:
                rows = db.execute("SELECT * FROM events ORDER BY event_date, event_time, id").fetchall()
                self.send_json([dict(row) for row in rows])
            finally:
                db.close()
            return
        file = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        if file.parent != ROOT or not file.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8" if file.suffix == ".html" else "application/octet-stream"
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/events/") and path.endswith("/status"):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "events"] or not parts[2].isdigit():
                self.send_json({"error": "Некорректный id записи."}, 400)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > 10000:
                    self.send_json({"error": "Запрос слишком большой."}, 413)
                    return
                data = json.loads(self.rfile.read(size))
            except (json.JSONDecodeError, TypeError):
                self.send_json({"error": "Не удалось прочитать запрос."}, 400)
                return
            status = data.get("status") if isinstance(data, dict) else None
            if status not in {"open", "done"}:
                self.send_json({"error": "Некорректный статус записи."}, 400)
                return
            db = connect()
            try:
                db.execute("UPDATE events SET status = ? WHERE id = ?", (status, int(parts[2])))
                row = db.execute("SELECT * FROM events WHERE id = ?", (int(parts[2]),)).fetchone()
                if not row:
                    self.send_json({"error": "Запись не найдена."}, 404)
                    return
                db.commit()
                self.send_json(dict(row))
            finally:
                db.close()
            return
        if path != "/api/chat":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 10000:
                self.send_json({"error": "Сообщение слишком длинное."}, 413)
                return
            data = json.loads(self.rfile.read(size))
            text = data.get("text", "").strip()
            context = data.get("context", "").strip()
            if not text:
                self.send_json({"error": "Введите сообщение."}, 400)
                return
            result = handle_chat(text, context)
            if "error" in result:
                self.send_json({"error": result["error"]}, 502)
                return
            self.send_json(result)
        except (json.JSONDecodeError, AttributeError, TypeError):
            logger.error("Rejected malformed /api/chat request.")
            self.send_json({"error": "Не удалось прочитать запрос."}, 400)

    def do_DELETE(self):
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "events"] or not parts[2].isdigit():
            self.send_error(404)
            return
        db = connect()
        try:
            row = db.execute("SELECT * FROM events WHERE id = ?", (int(parts[2]),)).fetchone()
            if not row:
                self.send_json({"error": "Запись не найдена."}, 404)
                return
            db.execute("DELETE FROM events WHERE id = ?", (int(parts[2]),))
            db.commit()
            self.send_json({"deleted": dict(row)})
        finally:
            db.close()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Сервер запущен: http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
