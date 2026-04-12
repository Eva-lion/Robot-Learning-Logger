# Spec: Agent / Orchestrator (Quality Evaluator)

## Назначение

Quality Evaluator — центральный оркестратор, управляющий пайплайном анализа эпизода: от получения валидированных данных до формирования QA-отчёта и уведомления Human Gateway. Не выполняет запись данных напрямую.

---

## 1. Роль и границы

| Что делает | Что НЕ делает |
|-----------|--------------|
| Запускает эвристический анализ | Пишет bag-файлы на диск |
| Вызывает LLM через Sanitizer | Выполняет системные команды |
| Формирует и сохраняет QA-отчёт | Принимает решения об одобрении датасета |
| Уведомляет Human Gateway | Обращается к ROS напрямую |
| Управляет retry и fallback | Изменяет sensor norms |

---

## 2. Шаги выполнения (Happy Path)

```
1. receive_episode(episode_id, validated_data)
       │
2. load_sensor_norms()          ← из cache (dict в памяти)
       │
3. heuristic_analysis()
       ├── for each topic/field: compare against norms
       ├── hard_fail? → REJECT (шаг 9, без LLM)
       └── soft_warn / ok → собрать список аномалий
       │
4. build_episode_summary()      ← JSON-резюме для LLM (≤ 3 000 tokens)
       │
5. check_llm_cache(SHA256(summary))
       ├── cache hit  → взять из кэша (шаг 7)
       └── cache miss → шаг 6
       │
6. sanitize_and_call_llm()
       ├── sanitizer_block? → fallback (шаг 8)
       ├── timeout / error  → retry × 3 → fallback (шаг 8)
       └── success → parse_llm_response()
       │
7. validate_llm_response()
       ├── confidence < 0.7 → флаг NEEDS_REVIEW
       └── confidence ≥ 0.7 → всё ок
       │
8. build_report(heuristics, llm_result)
       │
9. save_report_to_memory_hub()
       │
10. notify_human_gateway()      ← async уведомление
       │
11. return report_id
```

---

## 3. Правила переходов статусов

| Условие | Статус эпизода |
|--------|---------------|
| Все нормы ок, LLM confidence ≥ 0.7, verdict OK | `OK` |
| Есть soft warnings, LLM verdict SOFT_WARN | `SOFT_WARN` |
| Hard fail в эвристиках (до LLM) | `REJECT` |
| LLM verdict REJECT | `REJECT` |
| LLM confidence < 0.7 | `NEEDS_REVIEW` |
| LLM недоступен (любая ошибка) | `HEURISTIC_ONLY` |
| Отсутствует норма для топика/поля | `NEEDS_REVIEW` (флаг `MISSING_NORM`) |
| Ручное одобрение ML Engineer | `APPROVED` |
| Ручной отказ ML Engineer | `REJECTED_MANUAL` |

---

## 4. Retry и Fallback

### LLM Retry

```
Попытка 1 → fail → ждать 1 с
Попытка 2 → fail → ждать 2 с
Попытка 3 → fail → ждать 4 с
После 3 неудач → FALLBACK
```

### Fallback (HEURISTIC_ONLY)

- Отчёт строится только на эвристиках.
- `confidence = None`; `source = "HEURISTIC_ONLY"`.
- Эпизод не блокируется; ML Engineer сам решает.
- Событие `llm_fallback_total` инкрементируется.

### CRC fail при получении данных

- Retry записи × 1.
- При повторной неудаче → `REJECT`; уведомление; пайплайн продолжается для следующего эпизода.

---

## 5. Stop Conditions

| Условие | Действие |
|--------|---------|
| `disk_usage > 90 %` | Пауза приёма новых эпизодов; алерт |
| ROS disconnect × 3 подряд | Пауза; ждать reconnect или команду оператора |
| LLM бюджет исчерпан (`llm_cost >= $100`) | Принудительный HEURISTIC_ONLY режим; алерт |
| Sanitizer блок > 5 раз подряд | Стоп; алерт security |

---

## 6. Human Gateway

- Оркестратор **не принимает** решений об одобрении датасета.
- После формирования отчёта → асинхронная нотификация (callback / webhook / stdout в PoC).
- Ожидаемые действия ML Engineer:
  - `approve(episode_id)` → статус `APPROVED`; Dataset Versioning
  - `reject(episode_id, reason)` → статус `REJECTED_MANUAL`; паттерн добавляется в `rejected_patterns`
  - `request_review(episode_id)` → статус `NEEDS_REVIEW`; без изменений
- Таймаут ожидания решения: не ограничен (PoC); эпизод висит в `SOFT_WARN` / `NEEDS_REVIEW` без авто-перехода.

---

## 7. Контракт входа и выхода

### Вход

```python
@dataclass
class EpisodeInput:
    episode_id: str
    session_id: str
    started_at: str          # ISO 8601
    ended_at: str
    topics: list[str]
    imu_stats: dict          # {field: {min, max, mean, std, gap_ms_max}}
    odom_stats: dict
    camera_stats: dict       # {fps_actual, resolution, gap_ms_max}
    frame_count: int
    scenario: str | None     # для подбора reference-траектории
```

### Выход

```python
@dataclass
class QAReport:
    report_id: str
    episode_id: str
    created_at: str
    anomalies: list[str]
    annotation: str
    confidence: float | None
    verdict: Literal["OK", "SOFT_WARN", "REJECT"]
    source: Literal["FULL", "HEURISTIC_ONLY"]
    status: str              # итоговый статус эпизода
```

---

## 8. Ограничения

- Один оркестратор на процесс; нет параллельного анализа нескольких эпизодов в PoC.
- Нет персистентной очереди задач; при краше — потеря текущего эпизода.
- Human Gateway реализован как callback/stdout в PoC; webhook — post-PoC.
- Нет автоматического повтора после `NEEDS_REVIEW` по расписанию.
