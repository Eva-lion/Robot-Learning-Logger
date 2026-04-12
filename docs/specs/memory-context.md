# Spec: Memory / Context

## Назначение

Описывает управление состоянием сессии, хранение метаданных, политику контекста LLM-вызовов и жизненный цикл данных внутри системы.

---

## 1. Слои памяти

| Слой | Тип | Хранилище | Содержимое | TTL |
|-----|-----|----------|-----------|-----|
| **Session state** | In-memory | Python `dict` | Статус ROS, активная сессия, буфер сообщений | До конца сессии |
| **Episode metadata** | Persistent | SQLite `episodes` | `episode_id`, статус, `quality_score`, версия, timestamp | Постоянно |
| **QA-отчёты** | Persistent | SQLite `reports` + `.json` | Аномалии, аннотация LLM, confidence, вердикт | Постоянно |
| **LLM context** | Ephemeral | Временный объект | System prompt + данные эпизода + few-shot | 1 LLM-вызов |
| **LLM cache** | Persistent | SQLite `llm_cache` | `SHA256(input) → response` | 24 ч |
| **Sensor norms** | Static | SQLite `sensor_norms` / JSON | Допустимые диапазоны по топикам | Статично; меняется вручную |
| **Reference traces** | Static | JSON-файл | Reference-траектории по сценариям | Статично; меняется вручную |
| **Rejected patterns** | Accumulative | SQLite `rejected_patterns` | Паттерны + комментарии при ручном reject | Постоянно |

---

## 2. Session State

```python
# Структура in-memory state (per session)
session_state = {
    "session_id": str,          # UUID
    "started_at": str,          # ISO 8601
    "ros_connected": bool,
    "ros_reconnects": int,
    "active_episode_id": str | None,
    "message_buffer": deque,    # скользящий буфер последних N сообщений
    "disk_usage_bytes": int,    # обновляется периодически
    "llm_requests_this_minute": int,
    "status": "running" | "paused" | "error"
}
```

**Политика буфера:** `maxlen=1000` сообщений; при переполнении старые вытесняются. Буфер сбрасывается на диск при disconnect / завершении.

---

## 3. Схема SQLite

### Таблица `episodes`

```sql
CREATE TABLE episodes (
    episode_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    started_at   TEXT NOT NULL,          -- ISO 8601
    ended_at     TEXT,
    topics       TEXT,                   -- JSON-массив топиков
    frame_count  INTEGER DEFAULT 0,
    quality_score REAL,                  -- 0.0–1.0; NULL пока не посчитан
    status       TEXT DEFAULT 'PENDING', -- PENDING | OK | SOFT_WARN | REJECT | NEEDS_REVIEW | HEURISTIC_ONLY
    version      INTEGER DEFAULT 1,
    notes        TEXT
);
```

### Таблица `reports`

```sql
CREATE TABLE reports (
    report_id    TEXT PRIMARY KEY,
    episode_id   TEXT NOT NULL REFERENCES episodes(episode_id),
    created_at   TEXT NOT NULL,
    anomalies    TEXT,                   -- JSON-массив строк
    annotation   TEXT,                  -- текст от LLM или эвристик
    confidence   REAL,                  -- 0.0–1.0; NULL для HEURISTIC_ONLY
    verdict      TEXT,                  -- OK | SOFT_WARN | REJECT
    source       TEXT DEFAULT 'FULL'    -- FULL | HEURISTIC_ONLY
);
```

### Таблица `llm_cache`

```sql
CREATE TABLE llm_cache (
    cache_key    TEXT PRIMARY KEY,       -- SHA256(input_json)
    response     TEXT NOT NULL,          -- JSON-ответ LLM
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL           -- created_at + 24h
);
```

---

## 4. LLM Context Budget

**Лимит:** ≤ 4 000 токенов на один вызов.

| Блок | Токены | Содержимое |
|-----|-------|-----------|
| System prompt | ~500 | Роль агента, формат ответа, запреты |
| Episode summary | ~2 500–3 000 | Статистика по топикам, аномалии эвристик, временны́е метки |
| Few-shot пример | ~400–500 | 1 пример хорошего и 1 пример плохого отчёта |
| Response budget | 512 | Зарезервировано под ответ LLM |

**Усечение:** если данные эпизода превышают 3 000 токенов, они усекаются по приоритету:
1. Оставить аномальные сегменты полностью.
2. Усечь нормальные сегменты до агрегатов (min/max/std).
3. Добавить пометку `[data truncated]` в промпт.

---

## 5. Memory Policy

| Правило | Детали |
|---------|-------|
| Нет PII в памяти | Camera-фреймы не хранятся; хранятся только метаданные (fps, resolution, gaps) |
| Анонимизация до сохранения | Лица удаляются до записи в Data Collector |
| Хэширование идентификаторов | `session_id` и `user_id` (если есть) в логах — SHA256 |
| LLM не видит raw bytes | Агенту передаётся только JSON-резюме эпизода |
| Квота хранения | 1 ГБ (bag-файлы + БД + отчёты); при превышении — пауза и алерт |
| Очистка кэша | LLM-кэш: TTL 24 ч; очистка при старте сессии по `expires_at` |
| Версионирование датасета | Поле `version` в `episodes`; инкремент при ручном approve + изменении |

---

## 6. Ограничения

- Нет распределённого состояния в PoC: один процесс, один SQLite.
- При краше сессии — буфер сообщений теряется (только то, что не успело записаться на диск).
- Нет автоматической ротации старых эпизодов; ручная архивация при приближении к квоте 1 ГБ.
- Нет поддержки multi-robot (несколько параллельных сессий) в PoC; `session_id` один на процесс.
