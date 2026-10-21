import json
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


def gigachat_token():
    global GIGACHAT_TOKEN, GIGACHAT_TOKEN_EXPIRES
    if not GIGACHAT_AUTH_KEY:
        return None, "Добавьте Authorization_key в .env."
    if GIGACHAT_TOKEN and time.time() < GIGACHAT_TOKEN_EXPIRES:
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
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            return None, "GigaChat не принял Authorization_key из .env."
        if error.code == 429:
            return None, "GigaChat временно ограничил запросы авторизации."
        return None, f"GigaChat вернул ошибку авторизации HTTP {error.code}."
    except urllib.error.URLError:
        return None, "Не удалось подключиться к сервису авторизации GigaChat."
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None, "Не удалось прочитать ответ авторизации GigaChat."
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
            "Каждое действие в actions — объект с полем type. Доступны create, list, search. "
            "create: kind (task/reminder/meeting), title, date (YYYY-MM-DD или null), time (HH:MM или null), "
            "weekday (название дня недели по-русски, например воскресенье; null если даты нет). "
            "Если человек назвал только день недели, укажи weekday и date_is_explicit=false; приложение выберет ближайший такой день. "
            "Если пользователь назвал конкретную календарную дату, укажи date_is_explicit=true и соответствующий weekday, если он назван. "
            "list: kind (task/reminder/meeting/all), date_from, date_to (YYYY-MM-DD или null), event_ids. "
            "search: event_ids — числовые id подходящих записей из списка. "
            "Если вопрос касается сохранённых задач или встреч, обязательно верни действие search или list; "
            "не отвечай на такой вопрос напрямую, даже если видишь подходящую запись. "
            "Для запроса о человеке или теме без периода верни search и выбери подходящие id. "
            "Для запроса о планах за период верни list, при необходимости ограничь event_ids. "
            "Когда вернул действие, оставь reply пустым: итоговый ответ будет составлен после выполнения действия. "
            "Для приветствий и обычной беседы без действий ответь в reply. "
            "Если встрече не хватает даты или времени, верни пустой actions и вопрос в clarify. "
            "Можно вернуть несколько действий, например сначала create, затем search. "
            "Не выдумывай записи и их id; сопоставляй по смыслу и разным формам имён. "
            "Относительные даты считай от переданных текущих даты и времени. Учитывай весь контекст беседы. "
            "Пример: на вопрос «че там с Иваном?» при записи с id 2 верни "
            "{\"actions\":[{\"type\":\"search\",\"event_ids\":[2]}],\"reply\":\"\"}. "
            "Пример создания: верни create с названием дела, датой YYYY-MM-DD и временем HH:MM. "
            "Пример приветствия: {\"actions\":[],\"reply\":\"Привет! Чем помочь?\"}."
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
            "Не говори, что действие выполнено, если в результатах указано, что оно не выполнялось. "
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
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
        if "messages" in data:
            content = data["messages"][0]["content"]
            if isinstance(content, list):
                content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        else:
            content = data["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3].strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            if phase == "plan":
                return {"invalid": True}, None
            result = {"reply": content}
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            global GIGACHAT_TOKEN, GIGACHAT_TOKEN_EXPIRES
            GIGACHAT_TOKEN = ""
            GIGACHAT_TOKEN_EXPIRES = 0
            return None, "GigaChat не принял токен доступа."
        if error.code == 429:
            return None, "GigaChat временно ограничил запросы или закончился доступный лимит."
        if error.code == 404:
            return None, "GigaChat не нашёл выбранную модель. Проверьте GIGACHAT_MODEL в .env."
        return None, f"GigaChat вернул ошибку HTTP {error.code}."
    except urllib.error.URLError:
        return None, "Не удалось подключиться к GigaChat."
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None, "Не удалось прочитать ответ GigaChat."
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
        if action.get("type") == "search" and not isinstance(action.get("event_ids"), list):
            selected, error = ask_gigachat(
                conversation, event_rows(db), "select", session_id=session_id
            )
            if error:
                return None, error
            if not isinstance(selected, dict) or not isinstance(selected.get("event_ids"), list):
                return None, "GigaChat не смог выбрать подходящие записи."
            action = {**action, "event_ids": selected.get("event_ids", [])}
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
                "message": "Для создания встречи не хватает даты или времени.",
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

        def finish(result):
            db.execute(
                "INSERT INTO chat_history (role, content, created_at) VALUES (?, ?, ?)",
                ("assistant", result["reply"], datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            return result

        plan, error = ask_gigachat(conversation, event_rows(db), session_id=session_id)
        if error:
            return finish({"reply": f"Не удалось обработать запрос: {error}", "events": []})
        if not isinstance(plan, dict):
            return finish({"reply": "GigaChat вернул ответ в неверном формате.", "events": []})
        if plan.get("invalid"):
            answer, error = ask_gigachat(
                conversation,
                event_rows(db),
                "reply",
                [{"status": "not_executed", "message": "План не разобран, действия не выполнялись."}],
                session_id,
            )
            reply = get_reply(answer)
            if error or not reply:
                return finish({"reply": "Не удалось обработать ответ GigaChat. Попробуйте ещё раз.", "events": []})
            return finish({"reply": reply, "events": []})

        actions = plan.get("actions", [])
        if not actions:
            clarify = plan.get("clarify")
            if isinstance(clarify, str) and clarify.strip():
                return finish({"reply": clarify.strip(), "needs_reply": True, "context": json.dumps(conversation, ensure_ascii=False)})
            reply = plan.get("reply")
            if isinstance(reply, str) and reply.strip():
                return finish({"reply": reply.strip(), "events": []})
            return finish({"reply": "GigaChat не сформулировал ответ.", "events": []})

        completed, error = action_results(plan, db, conversation, session_id)
        if error:
            return finish({"reply": f"Не удалось выполнить действие: {error}", "events": []})
        if completed.get("clarify"):
            answer, error = ask_gigachat(
                conversation, event_rows(db), "reply", completed["results"], session_id
            )
            reply = get_reply(answer)
            if not reply:
                reply = "Уточните дату и время встречи."
            return finish({
                "reply": reply,
                "needs_reply": True,
                "context": json.dumps(conversation, ensure_ascii=False),
            })

        answer, error = ask_gigachat(
            conversation, event_rows(db), "reply", completed["results"], session_id
        )
        reply = answer.get("reply") if isinstance(answer, dict) else None
        if not isinstance(reply, str) or not reply.strip():
            lines = []
            for item in completed["results"]:
                if item["events"]:
                    lines.extend(item["events"])
                elif item.get("message"):
                    lines.append(item["message"])
                elif item["status"] == "no_results":
                    lines.append("Подходящих записей не найдено.")
            reply = "\n".join(lines) or "Действия выполнены."
        if error:
            reply += f"\n\nНе удалось получить ответ от GigaChat: {error}"
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
        if urlparse(self.path).path != "/api/chat":
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
            self.send_json(handle_chat(text, context))
        except (json.JSONDecodeError, AttributeError, TypeError):
            self.send_json({"error": "Не удалось прочитать запрос."}, 400)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Сервер запущен: http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
