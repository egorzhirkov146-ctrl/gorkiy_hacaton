import pytest
from io import BytesIO
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import init_db


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def test_e2e_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_e2e_chat_create_task(client):
    body = {
        "session_id": "e2e_sess_1",
        "text": "Поставь задачу купить билеты до конца недели"
    }
    res = client.post("/chat", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["action"]["type"] == "create_task"
    assert data["action"]["status"] == "ok"
    assert data["action"]["record"] is not None
    assert "билеты" in data["action"]["record"]["title"].lower()


def test_e2e_chat_create_meeting_with_conflict(client):
    # Создаем первую встречу
    body1 = {
        "session_id": "e2e_sess_2",
        "text": "Добавь встречу с инвестором завтра в 16:00"
    }
    res1 = client.post("/chat", json=body1)
    assert res1.status_code == 200
    assert res1.json()["action"]["type"] == "create_meeting"

    # Создаем вторую встречу на то же время (проверяем обнаружение конфликта)
    body2 = {
        "session_id": "e2e_sess_2",
        "text": "Добавь встречу с партнерами завтра в 16:10"
    }
    res2 = client.post("/chat", json=body2)
    assert res2.status_code == 200
    data2 = res2.json()
    assert "пересекается" in data2["reply_text"].lower()


def test_e2e_events_crud_and_search(client):
    # Создаем через POST /events
    new_event = {
        "type": "task",
        "title": "Тестовая задача через API",
        "raw_text": "Тестовый текст",
        "datetime": "2026-10-25T14:00:00"
    }
    create_res = client.post("/events", json=new_event)
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    # Поиск через /events/search
    search_res = client.get("/events/search", params={"q": "Тестовая задача"})
    assert search_res.status_code == 200
    assert any(item["id"] == created_id for item in search_res.json()["items"])

    # Получение списка /events
    list_res = client.get("/events")
    assert list_res.status_code == 200
    assert list_res.json()["count"] > 0

    # Обновление PATCH /events/{id}
    patch_res = client.patch(f"/events/{created_id}", json={"status": "done"})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "done"

    # Удаление DELETE /events/{id}
    del_res = client.delete(f"/events/{created_id}")
    assert del_res.status_code == 200

    get_res = client.get(f"/events/{created_id}")
    assert get_res.status_code == 404


def test_e2e_tts_endpoint(client):
    body = {"text": "Тестовая фраза для синтеза речи"}
    res = client.post("/tts", json=body)
    assert res.status_code == 200
    data = res.json()
    assert "audio_url" in data
    assert data["audio_url"].endswith(".mp3")


def test_e2e_stt_endpoint(client):
    fake_audio_bytes = b"RIFF" + b"\x00" * 300
    files = {"audio": ("test.wav", BytesIO(fake_audio_bytes), "audio/wav")}
    res = client.post("/stt", files=files)
    assert res.status_code == 200
    data = res.json()
    assert "text" in data
    assert len(data["text"]) > 0
