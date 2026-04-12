# Spec: Tools / APIs

## Назначение

Описывает все внешние и внутренние интеграции системы: контракты, параметры безопасности, обработку ошибок и побочные эффекты.

---

## 1. ROS Interface

| Параметр | Значение |
|---------|---------|
| Библиотека | `rclpy` (ROS 2) / `roslibpy` (WebSocket bridge) |
| Режим доступа | Read-only подписка |
| Топики | `/odom`, `/imu/data`, `/camera/image_raw` |
| Timeout | 5 с на heartbeat |
| Retry | × 3 с интервалом 1 с, затем буфер на диск |

### Контракт сообщения

```python
# /imu/data → sensor_msgs/Imu
{
  "header": {"stamp": {"sec": int, "nanosec": int}, "frame_id": str},
  "angular_velocity": {"x": float, "y": float, "z": float},
  "linear_acceleration": {"x": float, "y": float, "z": float}
}

# /odom → nav_msgs/Odometry
{
  "header": {"stamp": {...}, "frame_id": str},
  "child_frame_id": str,
  "pose": {"pose": {"position": {"x": float, "y": float, "z": float}}},
  "twist": {"twist": {"linear": {"x": float}, "angular": {"z": float}}}
}

# /camera/image_raw → sensor_msgs/Image
{
  "header": {...},
  "height": int,
  "width": int,
  "encoding": str,   # e.g. "bgr8"
  "data": bytes
}
```

### Побочные эффекты

- Нет; только чтение.
- При потере соединения — `ros_disconnected` event в in-memory state, метрика `ros_reconnects_total++`.

### Защита

- LLM-агент не имеет доступа к ROS-клиенту; только Data Collector.
- Нет write-подписок или service calls.

---

## 2. LLM API

| Параметр | Значение |
|---------|---------|
| Провайдеры | OpenAI (`gpt-4o-mini`) / Anthropic (`claude-3-haiku`) — выбор через `config.yaml` |
| Назначение | Генерация текстовой аннотации QA-отчёта |
| Rate limit | 10 req/min (self-imposed); провайдерский — не превышать |
| Timeout | 30 с на запрос |
| Retry | Exponential backoff: 1 → 2 → 4 с; максимум 3 попытки |
| Бюджет | ≤ $100 за PoC |
| Context budget | ≤ 4 000 токенов: ~500 system + ~3 000 data + ~500 few-shot |

### Контракт вызова

```python
# Вход (после Sanitizer)
{
  "model": str,                  # из config
  "messages": [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user",   "content": episode_summary_json}
  ],
  "max_tokens": 512,
  "temperature": 0.2
}

# Ожидаемый выход
{
  "annotation": str,             # текстовая аннотация
  "anomalies": [str],            # список обнаруженных проблем
  "confidence": float,           # 0.0–1.0
  "verdict": "OK" | "SOFT_WARN" | "REJECT"
}
```

### Sanitizer (обязательный слой перед вызовом)

- Блок-лист ключевых слов: `exec`, `eval`, `import`, `os.`, `sys.`, `subprocess`, `open(`, `__`.
- Ограничение длины user-контента: ≤ 3 500 токенов.
- Запрещены инструкции переключения роли ("ignore previous instructions", "you are now...").
- При срабатывании → отклонить вызов, залогировать событие `sanitizer_block`.

### Ошибки и fallback

| Ошибка | Поведение |
|-------|----------|
| HTTP 429 (rate limit) | Exponential backoff, затем `LLM_UNAVAILABLE` |
| HTTP 5xx | Retry × 3, затем fallback |
| Timeout | Fallback: только эвристический отчёт |
| `confidence < 0.7` | Флаг `NEEDS_REVIEW`; не блокирует пайплайн |
| Unparseable response | Fallback: только эвристический отчёт; предупреждение в лог |

**Fallback:** при любой ошибке LLM отчёт формируется только на основе эвристик; эпизод получает статус `HEURISTIC_ONLY`.

### Кэш

- Ключ: `SHA256(episode_summary_json)`.
- Хранилище: SQLite `llm_cache` (ttl 24 ч).
- Назначение: не повторять идентичный запрос при retry; экономить бюджет.

### Побочные эффекты

- Внешний сетевой запрос; данные передаются после анонимизации.
- Стоимость токенов списывается с API-ключа из `.env`.

---

## 3. Local Filesystem (Data Collector)

| Параметр | Значение |
|---------|---------|
| Библиотека | `pathlib`, `shutil`, `hashlib` |
| Назначение | Сохранение bag-файлов и QA-отчётов |
| Квота | 1 ГБ (PoC); мониторинг через `disk_usage_bytes` |
| Формат | `.bag` (ROS 2) + `.json` (отчёт) |

### Контракт записи

```python
def save_episode(episode_id: str, data: bytes, metadata: dict) -> bool:
    # 1. Вычислить CRC / SHA256
    # 2. Записать файл
    # 3. Записать метаданные в SQLite
    # 4. Вернуть True при успехе, False при ошибке
```

### Защита

- CRC-валидация после каждой записи.
- При `disk_usage > 90 %` — пауза Data Collector + алерт.
- Нет прямого доступа LLM к FS; только технический модуль.

---

## 4. SQLite (Memory Hub)

| Параметр | Значение |
|---------|---------|
| Библиотека | `sqlite3` (stdlib) |
| Файл | `data/rll.db` |
| Таблицы | `episodes`, `reports`, `sensor_norms`, `llm_cache`, `rejected_patterns` |
| Backup | Ручной; при росте > 500 MB — рекомендован вывод в MinIO |

### Ограничения

- Нет конкурентных записей из нескольких процессов (WAL mode включён).
- Не используется для хранения бинарных данных (bag-файлы — только на FS).

---

## 5. MinIO (опционально)

| Параметр | Значение |
|---------|---------|
| Библиотека | `boto3` |
| Назначение | S3-совместимое хранилище bag-файлов при превышении локальной квоты |
| Аутентификация | `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` из `.env` |
| Защита | HTTPS; нет публичного bucket; IAM-политики |
| Активация | `STORAGE_BACKEND=minio` в `config.yaml` |

---

## 6. Prometheus + Grafana / Plotly Dash

| Параметр | Значение |
|---------|---------|
| Библиотека | `prometheus_client`, `plotly-dash` |
| Назначение | Экспорт метрик, локальный дашборд |
| Endpoint | `http://localhost:8001/metrics` (Prometheus) |
| Dash | `http://localhost:8050` (только loopback) |
| Направление | Push-only из системы; нет входящего API |

---

## 7. Monitoring API (FastAPI)

| Параметр | Значение |
|---------|---------|
| Библиотека | `fastapi`, `uvicorn` |
| Назначение | REST read-only интерфейс для ML Engineer |
| Порт | `8000` (localhost) |
| Аутентификация | API-ключ в header `X-API-Key` (из `.env`) |
| Методы | Только GET; нет мутирующих эндпоинтов |

### Эндпоинты

| Метод | Путь | Описание |
|------|-----|--------|
| GET | `/episodes` | Список эпизодов с качеством |
| GET | `/episodes/{id}` | Полный QA-отчёт по эпизоду |
| GET | `/metrics/summary` | Агрегированная статистика качества |
| GET | `/health` | Статус системы |

### Защита

- Rate limit: 60 req/min (middleware).
- Только read-only; нет эндпоинтов изменения данных.
- Запросы логируются; чувствительные поля не возвращаются.
