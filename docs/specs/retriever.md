# Spec: Knowledge Base / Retriever

## Назначение

Предоставляет Quality Evaluator эталонные нормы сенсоров и reference-траектории для детекции аномалий без LLM-вызова. Работает как детерминированный first-pass фильтр.

---

## Источники данных

| Источник | Формат | Обновление |
|---------|--------|-----------|
| Нормы сенсоров (IMU, odom, camera) | SQLite `sensor_norms` / `data/norms.json` | Ручное; при смене платформы или сценария |
| Reference-траектории | `data/reference_trajectories.json` (RoboNet / IsaacGym snippets) | Ручное; при добавлении сценариев |
| Отклонённые паттерны (feedback) | SQLite `rejected_patterns` | Автоматически при reject с комментарием |

---

## Структура индекса

### Таблица `sensor_norms`

```sql
CREATE TABLE sensor_norms (
    id           INTEGER PRIMARY KEY,
    topic        TEXT NOT NULL,        -- e.g. '/imu/angular_velocity'
    field        TEXT NOT NULL,        -- e.g. 'z'
    min_val      REAL,                 -- допустимый минимум
    max_val      REAL,                 -- допустимый максимум
    max_std_dev  REAL,                 -- максимальное стандартное отклонение
    max_gap_ms   INTEGER,              -- допустимый разрыв между сообщениями (мс)
    severity     TEXT DEFAULT 'hard',  -- 'hard' | 'soft'
    updated_at   TEXT                  -- ISO 8601
);
```

**Пример данных:**

| topic | field | min_val | max_val | max_std_dev | max_gap_ms | severity |
|-------|-------|---------|---------|-------------|-----------|---------|
| `/imu/angular_velocity` | `z` | -10.0 | 10.0 | 2.0 | 100 | hard |
| `/imu/linear_acceleration` | `x` | -20.0 | 20.0 | 5.0 | 100 | hard |
| `/odom/twist/linear` | `x` | -3.0 | 3.0 | 1.0 | 200 | soft |
| `/camera/image_raw` | `fps` | 10.0 | 60.0 | — | 150 | soft |

---

## Метод поиска (Lookup)

- Точечный lookup: `SELECT * FROM sensor_norms WHERE topic = ? AND field = ?`
- Нет vector search в PoC; все правила детерминированы.
- При запросе несуществующей нормы → флаг `MISSING_NORM`; эпизод помечается `NEEDS_REVIEW`.
- Все нормы кэшируются в memory при старте (`dict[topic][field] → rule`).

---

## Reference-траектории

- Загружаются из `data/reference_trajectories.json` при старте сессии.
- Структура: `[{scenario, topic, expected_pattern, description}]`.
- Используются как контекст в LLM-промпте: «эталонная траектория показывает X, текущая — Y».
- Не индексируются; выбираются по `scenario` (match по типу задачи в метаданных эпизода).
- Максимальный размер reference JSON: **50 KB**; при превышении — усечение до первых N записей.

---

## Reranking

Не применяется — результат lookup единственен по `(topic, field)`.

**Расширение (post-PoC):** при росте базы сценариев — BM25 или embedding-поиск по `description` поля reference-траекторий.

---

## Ограничения

- Нормы задаются вручную; неверно настроенные диапазоны → ложные позитивы/негативы.
- Нет автоматического обновления норм из production-данных в PoC.
- Нет поддержки multi-modal норм (зависимости между топиками) в PoC.
- База норм не версионируется автоматически; версия фиксируется в `config.yaml`.
