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


def test_e2e_user_isolation_and_seed(client):
    # Очищаем перед тестом
    client.delete("/events/clear/99999")
    client.delete("/events/clear/88888")

    # 1. Сидируем изолированного пользователя 99999
    seed_res = client.post("/events/seed", params={"user_id": 99999})
    assert seed_res.status_code == 200
    assert seed_res.json()["count"] == 8

    # 2. Пользователь 88888 изначально имеет 0 записей
    res_88888 = client.get("/events", params={"user_id": 88888})
    assert res_88888.status_code == 200
    assert res_88888.json()["count"] == 0

    # 3. Пользователь 88888 создает задачу через /chat
    chat_res = client.post(
        "/chat",
        json={"user_id": 88888, "session_id": "sess_iso", "text": "Поставь задачу секретный синхрофазотрон"}
    )
    assert chat_res.status_code == 200

    # 4. Пользователь 88888 видит только свою задачу
    res_88888_after = client.get("/events", params={"user_id": 88888})
    assert res_88888_after.json()["count"] == 1
    assert "синхрофазотрон" in res_88888_after.json()["items"][0]["title"]

    # 5. Пользователь 99999 при поиске НЕ видит задачу пользователя 88888 (полная изоляция баз данных)
    search_99999 = client.get("/events/search", params={"q": "синхрофазотрон", "user_id": 99999})
    assert search_99999.status_code == 200
    assert search_99999.json()["count"] == 0

    # 6. Очистка пользователя 99999 не удаляет данные 88888
    clear_res = client.delete("/events/clear/99999")
    assert clear_res.status_code == 200
    assert client.get("/events", params={"user_id": 99999}).json()["count"] == 0
    assert client.get("/events", params={"user_id": 88888}).json()["count"] == 1

    # 7. Защита от IDOR: пользователь 99999 не может прочитать или удалить задачу 88888
    event_88888_id = res_88888_after.json()["items"][0]["id"]
    get_cross = client.get(f"/events/{event_88888_id}", params={"user_id": 99999})
    assert get_cross.status_code == 404
    del_cross = client.delete(f"/events/{event_88888_id}", params={"user_id": 99999})
    assert del_cross.status_code == 404

