# Голосовой ассистент для задач и встреч

## Слой данных

Слой данных хранит задачи, встречи и напоминания в SQLite, и он находит старые записи по фразе пользователя через полнотекстовый индекс FTS5 и, если это включено, через эмбеддинги sentence-transformers. Подробное описание схемы, поиска, индексов, замеров скорости и порядка слияния с другими ветками находится в файле docs/DATA_LAYER.md.

### Схема базы данных

Таблица records хранит одну запись пользователя, а остальные объекты базы обслуживают поиск. Функция init_storage из пакета backend/storage создаёт всю схему при старте приложения, и повторный вызов этой функции ничего не меняет.

| Объект | Тип | Содержимое |
|---|---|---|
| records | таблица | id, user_id, type, title, raw_text, datetime, created_at, status, recurrence, recurrence_until |
| record_embeddings | таблица | record_id со ссылкой на records.id и каскадным удалением, model, text_hash, dim, vector |
| records_fts | виртуальная таблица FTS5 | копия title и raw_text, в которой буква "ё" заменена на "е" |
| records_fts_vocab | виртуальная таблица fts5vocab | словарь индекса для поиска по опечаткам |
| records_fts_ai, records_fts_au, records_fts_ad | триггеры | обновление индекса при вставке, изменении и удалении записи |

Колонка type принимает значения task, meeting и reminder, колонка status принимает значения pending, done и cancelled, а ограничения CHECK не дают записать другие значения. Колонка datetime пуста у задачи без срока, а колонки recurrence и recurrence_until заполнены только у повторяющейся записи.

    records
      id               INTEGER PRIMARY KEY
      user_id          INTEGER NOT NULL DEFAULT 1
      type             VARCHAR(20) NOT NULL       CHECK IN (task, meeting, reminder)
      title            VARCHAR(500) NOT NULL      CHECK length(trim(title)) > 0
      raw_text         TEXT
      datetime         DATETIME                   локальное время без зоны
      created_at       DATETIME NOT NULL
      status           VARCHAR(20) NOT NULL       CHECK IN (pending, done, cancelled)
      recurrence       VARCHAR(16)                daily, weekdays, weekly, monthly, yearly
      recurrence_until DATETIME

      INDEX ix_records_user_datetime      (user_id, datetime)
      INDEX ix_records_user_type_datetime (user_id, type, datetime)
      INDEX ix_records_user_status        (user_id, status)
      INDEX ix_records_user_created       (user_id, created_at)
      INDEX ix_records_recurring          (user_id, datetime) WHERE recurrence IS NOT NULL

    record_embeddings
      record_id  INTEGER PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE
      model      VARCHAR(200) NOT NULL
      text_hash  VARCHAR(40) NOT NULL
      dim        INTEGER NOT NULL
      vector     BLOB NOT NULL
      updated_at DATETIME NOT NULL

Если README из ветки feat/nlu-module конфликтует с этим файлом при слиянии, раздел "Слой данных" нужно перенести в README ветки NLU целиком, потому что остальные разделы описывают другие модули.

### Запуск сидов и тестов

Команды ниже запускаются из корня проекта, и первая из них заполняет базу из переменной DB_PATH демонстрационным набором из 23 записей, даты которых считаются от момента запуска.

    python scripts/seed_demo.py
    python scripts/seed_demo.py --check
    pytest -q

Семантический поиск включается переменной SEARCH_EMBEDDINGS=1 в файле .env, а его зависимости устанавливаются отдельно, потому что библиотека torch весит сотни мегабайт.

    pip install -r requirements-search.txt
