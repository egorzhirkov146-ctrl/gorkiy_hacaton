# Интеграция frontend с backend команды

Изменены только файлы в `frontend/`.

## Исправления

- `/chat`: `text`, `session_id`, `user_id`, `history` вместо поля `message`; чтение `reply_text`, `action.record`, `action.records`, `needs_clarification`.
- `/events`: чтение `items`, `count` вместо `events`; разбор `datetime`, `status`, `type` согласно `RecordOut`.
- `/stt`: multipart с полем `audio` вместо `file`, ответ `text`.
- `/tts`: JSON `{audio_url}`, запрос файла по `/static/...`, проксирование этого пути в Vite.
- Добавлены сообщения об ответах-заглушках и тесты контракта.

## Что ещё не готово в backend архива

`backend/api/chat.py`, `events.py`, `voice.py` содержат TODO/stub, поэтому реальные операции и озвучивание до реализации коллег не заработают. Frontend эти файлы не изменяет. `backend/main.py` пока не монтирует `/static/tts`. При подключении рабочего backend проверьте форматы аудио MediaRecorder (webm/mp4/ogg), маршруты и CORS на продакшене.

## Запуск

`frontend/.env`: `VITE_DEMO_MODE=false`, `VITE_BACKEND_URL=http://localhost:8000`, `VITE_API_BASE_URL=/api`. Перезапустить Vite после изменения `.env`.
