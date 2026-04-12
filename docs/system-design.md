# System Design — Robot Learning Logger (PoC)

## 1. Ключевые архитектурные решения

| Решение | Обоснование |
|---------|-------------|
| LLM-агент не пишет данные напрямую | Sandbox: LLM анализирует, технический модуль записывает |
| Human approval на изменение статуса датасета | Обязательная точка контроля; LLM может галлюцинировать |
| Всё хранение локально в PoC | Бюджет и конфиденциальность; MinIO как опциональное расширение |
| Async-подписка на ROS-топики | Данные поступают потоком; pull/sync невозможен |
| Heuristic Analyzer как первый фильтр перед LLM | Снижает стоимость LLM-вызовов; быстрый reject явных аномалий |
| Анонимизация до любого анализа | Приватность: лица не попадают ни в LLM, ни в логи |
| Все LLM-вызовы через sanitizer | OWASP: предотвращение prompt injection и FS/exec команд |
| SQLite как Memory Hub | Нет внешних зависимостей; легко развернуть в PoC |

---

## 2. Модули и их роли

| Модуль | Роль | Технологии |
|--------|------|------------|
| **ROS Interface** | Подписка на `/odom`, `/imu`, `/camera`; преобразование в Python-объекты | `rclpy` / `roslibpy` |
| **Data Collector** | Буферизация, CRC-валидация, персистентное хранение | `pathlib`, `hashlib`, `boto3` (MinIO опц.) |
| **Anonymization Module** | Детекция лиц, замыливание/обрезка; только для camera-топика | `opencv-python` |
| **Knowledge Base** | Эталонные диапазоны сенсоров, reference-траектории | SQLite / JSON |
| **Quality Evaluator** | Оркестратор: эвристики → LLM → QA-отчёт | Python, `openai` / `anthropic` |
| **Memory Hub** | Сессионное состояние, метаданные датасетов, статусы эпизодов | SQLite |
| **Monitoring API** | REST-эндпоинты для отдачи метрик и отчётов (read-only) | FastAPI |
| **Observability** | Prometheus-метрики, Plotly Dash / Grafana-дашборд | `prometheus_client`, `plotly-dash` |

---

## 3. Основной workflow

```
ROS-топики (/odom, /imu, /camera)
        │   [ROS Interface]
        │
   [Data Collector]
        ├── CRC fail? → retry × 1 → reject episode → alert
        └── CRC ok
              │
        [Anonymization Module]  ← только camera frames
              │
        Validated & anonymized data
              │
        [Quality Evaluator]
              ├── [Heuristic Analyzer] ◄── Knowledge Base (sensor norms)
              │         ├── hard fail → reject episode (без LLM)
              │         └── pass / soft warn
              │
              ├── [LLM Caller] → Sanitizer → LLM API
              │         ├── timeout / error → fallback: only heuristics
              │         └── response → parse → confidence check
              │
              └── [Report Builder] → QA-отчёт
                        │
                  [Memory Hub] ← сохранить отчёт
                        │
                  [Human Gateway] ← notify ML Engineer
                        │
                  (approve) → [Dataset Versioning] → хранилище
                  (reject)  → эпизод помечен REJECTED
```

---

## 4. State / Memory / Context

| Слой | Хранилище | Содержимое | TTL |
|------|-----------|-----------|-----|
| Session state | In-memory dict | Текущая сессия, статус ROS, буфер сообщений | Время сессии |
| Dataset metadata | SQLite `episodes` | episode_id, timestamp, версия, quality_score, статус | Постоянно |
| QA-отчёты | SQLite `reports` + JSON | Полный отчёт: аномалии, аннотация LLM, confidence | Постоянно |
| LLM context | Временный (один вызов) | System prompt + данные эпизода + few-shot пример | 1 вызов |
| Reference norms | SQLite `sensor_norms` / JSON | Диапазоны `(min, max, max_std)` по топикам | Статично |

**Context budget:** ≤ 4 000 токенов на LLM-вызов: системный промпт (~500) + данные эпизода (~3 000) + пример отчёта (~500).

---

## 5. Retrieval-контур

- **Источник:** `sensor_norms` — SQLite/JSON с допустимыми диапазонами по каждому топику.
- **Содержимое норм:** `(topic, field, min, max, max_std_dev, max_gap_ms)` для `/imu`, `/odom`, `/camera` (fps, resolution).
- **Метод поиска:** точечный lookup `topic → field → rule`; vector search не нужен в PoC.
- **Reference-траектории:** JSON (RoboNet / IsaacGym); загружаются в память при старте; используются для контекстуализации аномалий в LLM-промпте.
- **Reranking:** не применяется — нормы детерминированы.
- **Расширение:** при росте базы — BM25 или embedding-поиск по reference-сценариям.

---

## 6. Tool / API-интеграции

| Интеграция | Библиотека | Назначение | Защита |
|-----------|------------|-----------|--------|
| ROS 2 | `rclpy` / `roslibpy` | Подписка на топики | Read-only; timeout 5 с; retry × 3 |
| LLM API | `openai` / `anthropic` | Аннотация, QA-отчёт | Sanitizer; rate limit 10 req/min; timeout 30 с |
| Local FS | `pathlib`, `shutil` | Сохранение bag-файлов | CRC-валидация; квота 1 ГБ |
| MinIO (опц.) | `boto3` | S3-совместимое хранилище | IAM из `.env`; HTTPS |
| Prometheus | `prometheus_client` | Экспорт метрик | Push-only; нет входящего трафика |
| Grafana / Dash | `plotly-dash` | Визуализация качества | Локальный дашборд; нет публичного доступа |

---

## 7. Failure modes, fallback и guardrails

| Сценарий | Детект | Fallback | Guardrail |
|----------|--------|----------|-----------|
| Потеря соединения с ROS | Heartbeat timeout 5 с | Retry × 3, затем буфер на диск | Лог + метрика `ros_reconnects_total` |
| Повреждение данных (CRC fail) | `hashlib` проверка | Retry записи × 1, затем reject | Счётчик `data_crc_failures_total` |
| LLM галлюцинация / низкая уверенность | `confidence < 0.7` в ответе | Флаг `NEEDS_REVIEW`; только эвристический отчёт | Spot-check 10 % ML Engineer |
| Rate limit / timeout LLM API | HTTP 429 / timeout | Exponential backoff (1→2→4 с); кэш hash→ответ | Бюджет ≤ $100 |
| Нехватка места | `disk_usage > 90 %` | Пауза Data Collector, алерт | Квота 1 ГБ |
| Prompt injection | Sanitizer блок-лист | Отклонить вызов, залогировать | Запрет FS/exec/system команд |
| Лицо в кадре | OpenCV face detection | Замыливание до передачи агенту | Данные до анонимизации не уходят в LLM |

---

## 8. Технические и операционные ограничения

| Параметр | Значение |
|---------|---------|
| p95 latency QA-проверки | ≤ 15 с / эпизод |
| Target latency | ≤ 10 с / эпизод |
| Точность детекта «плохих» данных | ≥ 90 % (ручная валидация) |
| Доля авто-верифицированных логов | ≥ 80 % |
| Допустимая потеря данных | < 0,1 % |
| Хранение (PoC) | 1 ГБ |
| Бюджет LLM API | ≤ $100 |
| LLM context window | ≤ 4 000 токенов / вызов |
| Команда | 2 чел. × 2 недели |
| Среда | Симуляция (Gazebo / Webots / ROS bag) |
| Облачные данные | Не используются в PoC |
