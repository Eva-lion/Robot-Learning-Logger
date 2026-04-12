# Spec: Serving / Config

## Назначение

Описывает запуск системы, конфигурацию, управление секретами и версионирование зависимостей.

---

## 1. Режимы запуска

| Режим | Команда | Описание |
|------|--------|---------|
| Полный стек | `python -m src.main` | ROS Interface + Data Collector + Quality Evaluator + Monitoring API |
| Только анализ (без ROS) | `python -m src.main --mode=offline --input=data/episode.json` | Режим тестирования на готовых данных |
| API только | `uvicorn src.api.app:app --port 8000` | Запуск Monitoring API отдельно |
| Дашборд | `python -m src.dashboard` | Plotly Dash на порту 8050 |

---

## 2. Структура конфигурации

Конфигурация хранится в `config.yaml` (версионируется в git) и `.env` (не версионируется).

### `config.yaml`

```yaml
ros:
  mode: rclpy          # rclpy | roslibpy
  topics:
    - /odom
    - /imu/data
    - /camera/image_raw
  heartbeat_timeout_s: 5
  reconnect_retries: 3

data_collector:
  storage_backend: local    # local | minio
  local_path: data/episodes/
  quota_gb: 1.0
  crc_algorithm: sha256

quality_evaluator:
  heuristics_only_fallback: true
  llm_confidence_threshold: 0.7
  llm_max_tokens_input: 4000
  llm_response_tokens: 512
  llm_temperature: 0.2
  llm_timeout_s: 30
  llm_retry_count: 3
  llm_rate_limit_rpm: 10

llm:
  provider: openai          # openai | anthropic
  model: gpt-4o-mini        # gpt-4o-mini | claude-3-haiku

memory:
  db_path: data/rll.db
  llm_cache_ttl_hours: 24
  reference_traces_path: data/reference_trajectories.json
  sensor_norms_path: data/norms.json

api:
  port: 8000
  host: 127.0.0.1
  rate_limit_rpm: 60

observability:
  prometheus_port: 8001
  log_level: INFO           # DEBUG | INFO | WARNING | ERROR
  log_format: json          # json | text

dataset:
  norms_version: "1.0.0"    # фиксируется при изменении sensor_norms
```

### `.env` (секреты — никогда не в git)

```dotenv
# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Monitoring API
API_KEY=your-secret-api-key

# MinIO (опционально)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rll-episodes
```

---

## 3. Порядок запуска и инициализация

```
1. Загрузить .env (python-dotenv)
2. Загрузить config.yaml (PyYAML)
3. Проверить наличие обязательных переменных окружения
4. Инициализировать SQLite (создать таблицы если нет)
5. Загрузить sensor_norms в memory cache
6. Загрузить reference_trajectories в memory
7. Очистить просроченные LLM-кэши (expires_at < now)
8. Инициализировать ROS Interface (subscribe on topics)
9. Запустить Monitoring API (FastAPI) в отдельном потоке
10. Запустить main event loop (Data Collector → Quality Evaluator)
```

**Проверки при старте (fail-fast):**

| Проверка | При ошибке |
|---------|-----------|
| `OPENAI_API_KEY` или `ANTHROPIC_API_KEY` присутствует | Старт только в HEURISTIC_ONLY режиме; предупреждение |
| SQLite доступен на запись | Критическая ошибка; выход |
| `disk_usage < 90 %` | Предупреждение; продолжить |
| `data/norms.json` / DB `sensor_norms` не пуст | Предупреждение; `MISSING_NORM` будет для всех |

---

## 4. Зависимости и версии

| Пакет | Версия | Назначение |
|------|-------|-----------|
| `rclpy` | ROS 2 Humble+ | ROS 2 интеграция |
| `roslibpy` | ≥ 1.3 | ROS bridge (альтернатива) |
| `openai` | ≥ 1.0 | LLM API |
| `anthropic` | ≥ 0.25 | LLM API (альтернатива) |
| `fastapi` | ≥ 0.110 | Monitoring API |
| `uvicorn` | ≥ 0.29 | ASGI сервер |
| `opencv-python` | ≥ 4.9 | Анонимизация (face detection) |
| `prometheus_client` | ≥ 0.20 | Метрики |
| `plotly-dash` | ≥ 2.16 | Дашборд |
| `boto3` | ≥ 1.34 | MinIO / S3 (опц.) |
| `python-dotenv` | ≥ 1.0 | Загрузка `.env` |
| `PyYAML` | ≥ 6.0 | Конфигурация |
| `pydantic` | ≥ 2.0 | Валидация данных |

Python: **3.11+**

---

## 5. Управление секретами

- Все ключи хранятся в `.env`; файл в `.gitignore`.
- В коде нет хардкода ключей; только `os.environ.get(...)` с fail-fast проверкой.
- В логах и отчётах ключи не появляются.
- Ротация ключей: ручная через замену `.env` + рестарт процесса.

---

## 6. Версионирование моделей и норм

| Артефакт | Версионирование | Хранение |
|---------|----------------|---------|
| Модель LLM | `config.yaml` → `llm.model` | Не хранится локально |
| Нормы сенсоров | `config.yaml` → `dataset.norms_version` | `data/norms.json` + SQLite |
| Reference-траектории | Ручной changelog в файле | `data/reference_trajectories.json` |
| Датасет (эпизоды) | Поле `version` в `episodes` таблице | SQLite + FS |

---

## 7. Остановка и graceful shutdown

- Получение `SIGTERM` / `SIGINT` → флаг `shutdown_requested = True`.
- Data Collector завершает текущий эпизод (или сбрасывает буфер на диск).
- Quality Evaluator завершает текущий анализ (или сохраняет промежуточный результат).
- Monitoring API отвечает `503` на новые запросы, завершает текущие.
- ROS Interface отписывается от топиков.
- SQLite connection закрывается.
- Graceful shutdown timeout: **15 с**, после — force exit.

---

## 8. Ограничения

- Нет автоматического рестарта при краше (systemd / supervisor — post-PoC).
- Нет hot-reload конфига; изменение `config.yaml` требует рестарта.
- Один процесс, нет горизонтального масштабирования в PoC.
- Нет контейнеризации (Docker) в PoC; только виртуальное окружение Python.
