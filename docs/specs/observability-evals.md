# Spec: Observability / Evals

## Назначение

Описывает метрики, логи, трейсы и автоматические проверки качества, необходимые для контроля системы в PoC.

---

## 1. Метрики (Prometheus)

Экспортируются на `http://localhost:8001/metrics`.

### Системные метрики

| Метрика | Тип | Описание |
|--------|-----|---------|
| `rll_ros_connected` | Gauge | 1 = подключён, 0 = нет |
| `rll_ros_reconnects_total` | Counter | Число переподключений к ROS |
| `rll_disk_usage_bytes` | Gauge | Текущий размер хранилища |
| `rll_episodes_total` | Counter | Всего обработанных эпизодов |
| `rll_episodes_by_status` | Counter (labels: `status`) | Разбивка по статусу (OK, REJECT, NEEDS_REVIEW, …) |

### Метрики качества

| Метрика | Тип | Описание |
|--------|-----|---------|
| `rll_data_crc_failures_total` | Counter | Ошибки CRC при записи |
| `rll_anomalies_detected_total` | Counter (labels: `topic`, `severity`) | Число аномалий по топику |
| `rll_quality_score` | Histogram (buckets: 0.1 шаг) | Распределение quality_score |
| `rll_auto_verified_ratio` | Gauge | Доля эпизодов со статусом OK / SOFT_WARN без ручного вмешательства |

### Метрики LLM

| Метрика | Тип | Описание |
|--------|-----|---------|
| `rll_llm_requests_total` | Counter (labels: `provider`, `status`) | Все LLM-вызовы: success/error/timeout |
| `rll_llm_latency_seconds` | Histogram | Время одного LLM-вызова |
| `rll_llm_tokens_used_total` | Counter | Суммарный расход токенов |
| `rll_llm_cost_usd` | Gauge | Оценочная стоимость ($) нарастающим итогом |
| `rll_llm_cache_hits_total` | Counter | Количество cache hit |
| `rll_llm_fallback_total` | Counter | Количество переходов в HEURISTIC_ONLY |
| `rll_llm_confidence` | Histogram | Распределение confidence LLM-ответов |
| `rll_sanitizer_blocks_total` | Counter | Число срабатываний sanitizer |

### Метрики API

| Метрика | Тип | Описание |
|--------|-----|---------|
| `rll_api_requests_total` | Counter (labels: `endpoint`, `status_code`) | HTTP-запросы к Monitoring API |
| `rll_api_latency_seconds` | Histogram (labels: `endpoint`) | Латентность API |

---

## 2. Логирование

**Формат:** JSON (структурированный); переключается на text в `config.yaml` (dev-режим).

**Уровни:**

| Уровень | Что попадает |
|--------|-------------|
| `ERROR` | Crash, CRC fail, критические ошибки |
| `WARNING` | LLM fallback, sanitizer block, disk > 90%, confidence < 0.7 |
| `INFO` | Старт/стоп, начало/конец эпизода, вердикт отчёта |
| `DEBUG` | Каждое ROS-сообщение, шаги эвристик (только в dev) |

**Обязательные поля каждой записи:**

```json
{
  "timestamp": "ISO 8601",
  "level": "INFO",
  "module": "quality_evaluator",
  "session_id": "sha256-хэш",
  "episode_id": "uuid или null",
  "event": "episode_analyzed",
  "verdict": "OK",
  "details": {}
}
```

**Что никогда не логируется:**

- Raw image bytes / bag-файлы.
- API-ключи, токены, переменные окружения.
- Несанированный пользовательский ввод (только после sanitizer).
- Лица / изображения до анонимизации.

**Хранение логов:** локальный файл `logs/rll.log`; ротация при `size > 50 MB` (3 файла max).

---

## 3. Трейсинг (PoC-уровень)

Полноценный distributed tracing (OpenTelemetry) — post-PoC. В PoC используется упрощённый трейсинг:

- Каждый эпизод получает `trace_id = episode_id`.
- В лог пишутся временны́е метки ключевых шагов:
  - `ros_received_at`
  - `crc_checked_at`
  - `anonymized_at`
  - `heuristics_done_at`
  - `llm_called_at`
  - `llm_responded_at`
  - `report_saved_at`
  - `human_notified_at`
- На основе этих меток вычисляются latency-метрики для каждого шага.

---

## 4. Дашборд (Plotly Dash)

`http://localhost:8050` — только loopback.

**Панели:**

| Панель | Содержимое |
|-------|-----------|
| Overview | Всего эпизодов, % OK / SOFT_WARN / REJECT, текущий статус ROS |
| Quality Trend | График quality_score по времени |
| Anomaly Breakdown | Топ-аномалий по топику и severity |
| LLM Stats | Запросы, latency, cost, cache hit rate |
| Disk Usage | Текущее использование vs квота |
| Recent Episodes | Таблица последних 20 эпизодов с вердиктами |

---

## 5. Автоматические проверки качества (Evals)

### 5.1. Spot-check (ручной, обязательный)

- ML Engineer проверяет вручную ≥ 10 % отчётов.
- Сравнивает вердикт системы с собственной оценкой.
- Метрика: **precision@REJECT** и **recall@REJECT** по выборке.
- Цель (PoC): precision ≥ 0.90, recall ≥ 0.85.

### 5.2. Unit-тесты эвристик (автоматические)

Запускаются при каждом коммите (`pytest`).

| Тест | Проверяет |
|-----|---------|
| `test_hard_fail_out_of_range` | IMU вне нормы → статус REJECT |
| `test_soft_warn_gap` | Пропуск сообщений → SOFT_WARN |
| `test_ok_normal_episode` | Нормальные данные → OK |
| `test_missing_norm_flag` | Отсутствующая норма → NEEDS_REVIEW |
| `test_crc_fail` | Повреждённые данные → retry + reject |

### 5.3. Regression-тесты LLM (автоматические, offline)

- Фиксированный набор из 10 эпизодов с известными вердиктами.
- Запускаются еженедельно или при смене модели.
- Допустимое отклонение: ≤ 1 эпизод из 10.
- Хранятся в `tests/fixtures/episodes/`.

### 5.4. SLO-алерты

| SLO | Цель | Алерт при |
|----|-----|----------|
| p95 latency анализа | ≤ 15 с | > 15 с в течение 5 мин |
| % автоверифицированных | ≥ 80 % | < 70 % за последние 100 эпизодов |
| Потеря данных (CRC fail) | < 0.1 % | > 0.5 % за последние 1000 |
| LLM cost | ≤ $100 | > $80 (предупреждение), > $95 (стоп) |
| Disk usage | < 100 % квоты | > 90 % |

---

## 6. Ограничения

- Нет distributed tracing в PoC (OpenTelemetry — post-PoC).
- Prometheus-метрики не персистентны при рестарте процесса (нет remote write).
- Алерты реализованы как stdout-предупреждения в PoC; PagerDuty / Slack — post-PoC.
- LLM regression-тесты не запускаются в CI автоматически (стоимость API); только локально по требованию.
