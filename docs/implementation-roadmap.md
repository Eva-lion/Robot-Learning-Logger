# Implementation Roadmap — Robot Learning Logger (PoC)

Команда: 2 человека × 2 недели (20 рабочих дней).  
Среда: симуляция или готовые ROS bag-файлы, локальная машина.

---

## Phase 0 — Project Skeleton (День 1)

**Цель:** запустить пустой проект, убедиться что среда работает.

- [ ] Создать структуру директорий:
  ```
  src/
    __init__.py
    ros_interface/
    data_collector/
    anonymization/
    knowledge_base/
    quality_evaluator/
      heuristics.py
      llm_caller.py
      sanitizer.py
      report_builder.py
      orchestrator.py
    memory_hub/
    api/
    dashboard/
    main.py
  data/
    episodes/
    norms.json          ← пустой шаблон
    reference_trajectories.json
  tests/
    fixtures/episodes/
  config.yaml
  .env.example
  requirements.txt
  ```
- [ ] Создать `config.yaml` и `.env.example` по spec `serving-config.md`.
- [ ] Настроить виртуальное окружение, установить зависимости (`requirements.txt`).
- [ ] Настроить `pytest`; убедиться что `pytest` проходит на пустом проекте.
- [ ] Добавить `pyproject.toml` или `setup.cfg` с линтером (`ruff` / `flake8`).

**Критерий готовности:** `python -m src.main --help` не падает.

---

## Phase 1 — Data Foundation (Дни 2–3)

**Цель:** заполнить Knowledge Base, подготовить тестовые данные.

### 1.1 Sensor Norms

- [ ] Создать SQLite схему: `sensor_norms`, `episodes`, `reports`, `llm_cache`, `rejected_patterns` (по spec `memory-context.md`).
- [ ] Написать `src/memory_hub/db.py`: инициализация БД, CRUD-функции.
- [ ] Заполнить `data/norms.json` реальными диапазонами:
  - `/imu/angular_velocity` (x, y, z)
  - `/imu/linear_acceleration` (x, y, z)
  - `/odom/twist/linear` (x)
  - `/camera/image_raw` (fps, resolution, gap_ms)
- [ ] Написать `src/knowledge_base/loader.py`: загрузка норм из JSON/SQLite в memory-cache при старте.

### 1.2 Тестовые данные

- [ ] Записать или скачать 3–5 ROS bag-файлов (Gazebo / открытые датасеты RoboNet).
  - 2 «хороших» эпизода (нормальные данные)
  - 2 «плохих» (аномалии: выход за диапазон, пропуски, фриз сенсора)
  - 1 пограничный (soft warning)
- [ ] Создать `tests/fixtures/episodes/`: JSON-резюме для offline-тестов (без ROS).

**Критерий:** `loader.py` загружает нормы; БД инициализируется без ошибок.

---

## Phase 2 — ROS Interface + Data Collector (Дни 4–5)

**Цель:** принимать данные из ROS и сохранять их валидированными.

### 2.1 ROS Interface

- [ ] Реализовать `src/ros_interface/subscriber.py`:
  - Подписка на `/odom`, `/imu/data`, `/camera/image_raw`.
  - Десериализация сообщений в Python dataclass (по контракту из spec `tools-apis.md`).
  - Heartbeat-таймаут 5 с; retry × 3; callback на disconnect.
- [ ] Реализовать heartbeat loop и обновление `session_state["ros_connected"]`.

### 2.2 Data Collector

- [ ] Реализовать `src/data_collector/collector.py`:
  - Буфер `deque(maxlen=1000)`.
  - Сброс буфера на диск при disconnect или конце эпизода.
  - CRC/SHA256 проверка после записи; retry × 1; reject + лог при неудаче.
  - Проверка дисковой квоты: `disk_usage > 90 %` → пауза + алерт.
- [ ] Реализовать `src/data_collector/storage.py`: запись bag-файлов + метаданных в SQLite.

### 2.3 Тесты

- [ ] `test_collector_crc_fail` — повреждённые данные → reject.
- [ ] `test_collector_quota_pause` — превышение квоты → пауза.
- [ ] Мок ROS-топиков для unit-тестов (без реального ROS).

**Критерий:** Data Collector принимает mock-сообщения, сохраняет, валидирует CRC.

---

## Phase 3 — Anonymization Module (День 6)

**Цель:** удалять лица из camera-фреймов до любой дальнейшей обработки.

- [ ] Реализовать `src/anonymization/face_blur.py`:
  - OpenCV `CascadeClassifier` (Haar) или DNN face detector.
  - Gaussian blur на обнаруженных регионах.
  - Хэш-проверка: если hash фрейма уже обработан — пропустить.
  - Возвращает anonymized bytes; никогда не пишет raw-фреймы.
- [ ] Интегрировать в Data Collector: анонимизация до сохранения.
- [ ] Тест `test_face_blur_applied` — фрейм с лицом → blur применён.
- [ ] Тест `test_no_face_passthrough` — фрейм без лиц → без изменений.

**Критерий:** ни один raw-фрейм с лицом не попадает в хранилище.

---

## Phase 4 — Quality Evaluator: Heuristics (Дни 7–8)

**Цель:** реализовать быстрый первый фильтр без LLM.

- [ ] Реализовать `src/quality_evaluator/heuristics.py`:
  - `analyze(episode_stats, norms_cache) → HeuristicResult`
  - Проверки по каждому топику/полю: `min_val`, `max_val`, `max_std_dev`, `max_gap_ms`.
  - `severity='hard'` → `REJECT` (немедленно, без LLM).
  - `severity='soft'` → добавить в список аномалий, продолжить.
  - Если норма отсутствует → флаг `MISSING_NORM`, статус `NEEDS_REVIEW`.
- [ ] Реализовать агрегацию статистики из буфера: `build_episode_stats(messages) → EpisodeStats`.
- [ ] Unit-тесты (обязательно):
  - `test_hard_fail_out_of_range`
  - `test_soft_warn_gap`
  - `test_ok_normal_episode`
  - `test_missing_norm_flag`

**Критерий:** все 4 unit-теста зелёные; no LLM calls в этой фазе.

---

## Phase 5 — Quality Evaluator: LLM Caller + Sanitizer (Дни 9–10)

**Цель:** LLM-аннотация с защитой от prompt injection.

### 5.1 Sanitizer

- [ ] Реализовать `src/quality_evaluator/sanitizer.py`:
  - Блок-лист: `exec`, `eval`, `import`, `os.`, `sys.`, `subprocess`, `open(`, `__`, "ignore previous", "you are now".
  - Лимит длины: ≤ 3 500 токенов (оценка по `len(text) // 4`).
  - При срабатывании → raise `SanitizerBlockError`; лог события `sanitizer_block`.
- [ ] Тест `test_sanitizer_blocks_injection`.
- [ ] Тест `test_sanitizer_passes_clean_input`.

### 5.2 LLM Caller

- [ ] Реализовать `src/quality_evaluator/llm_caller.py`:
  - `call(episode_summary: dict) → LLMResponse | None`
  - Проверка LLM-кэша по `SHA256(json(summary))` → если hit, вернуть из кэша.
  - Прогон через Sanitizer.
  - Вызов OpenAI или Anthropic (по `config.yaml`).
  - Exponential backoff: 1 → 2 → 4 с; максимум 3 попытки.
  - При всех ошибках → вернуть `None` (fallback).
  - Сохранить успешный ответ в `llm_cache`.
- [ ] `build_episode_summary(stats, anomalies, reference) → dict` — формирует JSON ≤ 3 000 токенов с усечением.
- [ ] Тест с mock LLM API — проверить retry, fallback, cache hit.

### 5.3 Report Builder

- [ ] Реализовать `src/quality_evaluator/report_builder.py`:
  - `build(heuristic_result, llm_response) → QAReport`
  - Определение итогового вердикта по матрице из spec `agent-orchestrator.md`.
  - `confidence < 0.7` → флаг `NEEDS_REVIEW`.
  - `llm_response is None` → `source = HEURISTIC_ONLY`.

**Критерий:** полный анализ на offline-фикстуре < 15 с; no реальных LLM-запросов в CI.

---

## Phase 6 — Orchestrator + Memory Hub (День 11)

**Цель:** связать все компоненты в единый пайплайн.

- [ ] Реализовать `src/quality_evaluator/orchestrator.py`:
  - `analyze_episode(episode_input: EpisodeInput) → QAReport`
  - Последовательность шагов по spec `agent-orchestrator.md` (шаги 1–11).
  - Обработка stop conditions: диск > 90 %, LLM бюджет исчерпан, sanitizer × 5.
- [ ] Реализовать `src/memory_hub/writer.py`:
  - `save_episode(episode)`, `save_report(report)`, `update_episode_status(id, status)`.
- [ ] Реализовать Human Gateway (PoC): вывод уведомления в stdout + callback hook.
- [ ] Интеграционный тест: offline-фикстура → orchestrator → report сохранён в SQLite.

**Критерий:** E2E пайплайн (без ROS, без реального LLM) проходит.

---

## Phase 7 — Monitoring API (День 12)

**Цель:** REST-интерфейс для ML Engineer.

- [ ] Реализовать `src/api/app.py` (FastAPI):
  - `GET /episodes` — список с фильтрами по статусу.
  - `GET /episodes/{id}` — полный QA-отчёт.
  - `GET /metrics/summary` — агрегированная статистика.
  - `GET /health` — статус системы.
  - `POST /episodes/{id}/approve` — approve от ML Engineer → `APPROVED`.
  - `POST /episodes/{id}/reject` — reject → `REJECTED_MANUAL` + паттерн в `rejected_patterns`.
- [ ] Middleware: API-ключ из `.env`; rate limit 60 req/min.
- [ ] Тест каждого эндпоинта (pytest + `TestClient`).

**Критерий:** все эндпоинты отвечают; неавторизованный запрос → 401.

---

## Phase 8 — Observability (День 13)

**Цель:** метрики, логи, дашборд.

- [ ] Реализовать `src/observability/metrics.py`:
  - Все счётчики и gauges из spec `observability-evals.md`.
  - Prometheus HTTP endpoint на порту 8001.
- [ ] Настроить структурированное JSON-логирование: `src/observability/logger.py`.
  - Ротация: 50 MB, 3 файла.
  - Обязательные поля: `timestamp`, `level`, `module`, `session_id`, `episode_id`, `event`.
- [ ] Реализовать `src/dashboard/app.py` (Plotly Dash):
  - 6 панелей по spec `observability-evals.md`.
  - Автообновление каждые 10 с.
- [ ] Пронизать метриками все модули: каждое событие инкрементирует нужный счётчик.

**Критерий:** `/metrics` отдаёт данные; дашборд открывается на `localhost:8050`.

---

## Phase 9 — Integration & E2E Test (День 14)

**Цель:** проверить полную систему на симуляции.

- [ ] Запустить Gazebo / воспроизвести ROS bag через `ros2 bag play`.
- [ ] Запустить `python -m src.main`; убедиться что:
  - Данные поступают из ROS и сохраняются.
  - Анонимизация отрабатывает на camera-топике.
  - Quality Evaluator формирует отчёты.
  - LLM-вызовы уходят и возвращаются (или fallback при ошибке).
  - Отчёты видны в `/episodes` API и дашборде.
- [ ] Проверить SLO: p95 latency ≤ 15 с на тестовых эпизодах.
- [ ] Провести spot-check: вручную проверить ≥ 10 % отчётов; посчитать precision/recall.
- [ ] Запустить все regression-тесты: `pytest tests/ -v`.

**Критерий:** SLO выдержаны; precision@REJECT ≥ 0.90; все тесты зелёные.

---

## Phase 10 — Hardening & Documentation (День 15)

**Цель:** привести проект в финальный PoC-вид.

- [ ] Проверить все failure modes из system-design.md: симулировать каждый и убедиться в корректном fallback.
- [ ] Проверить SLO-алерты: симулировать disk > 90 %, LLM timeout.
- [ ] Пройтись по OWASP: prompt injection, нет хардкода секретов, нет утечки PII в логах.
- [ ] Написать `README.md`: требования, установка, запуск, структура проекта.
- [ ] Зафиксировать версии зависимостей: `pip freeze > requirements.lock`.
- [ ] Финальный `git tag v0.1.0-poc`.

---

## Карта зависимостей между фазами

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4
                                              ↓
                                         Phase 5
                                              ↓
                              Phase 6 ←───────┘
                                 ↓
                    Phase 7 ─── Phase 8
                                 ↓
                             Phase 9 → Phase 10
```

---

## Что остаётся за рамками PoC (post-PoC backlog)

| Фича | Причина отложить |
|-----|----------------|
| Docker / контейнеризация | Усложняет ROS-интеграцию; не нужна для локального PoC |
| OpenTelemetry distributed tracing | Избыточно для 1-процессной системы |
| Горизонтальное масштабирование | Нет multi-robot требований в PoC |
| Persistent task queue (Celery/Redis) | Нет параллельного анализа в PoC |
| Автоматическая ротация норм | Требует ML-pipeline; post-PoC |
| Webhook Human Gateway | stdout достаточен для PoC |
| MLflow / W&B интеграция | Post-PoC ML-pipeline |
