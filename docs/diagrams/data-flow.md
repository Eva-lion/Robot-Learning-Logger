# Data Flow Diagram — Robot Learning Logger

Показывает, как данные проходят через систему: что хранится, что логируется, что никогда не покидает sandbox.

```mermaid
flowchart TD
    ROS["ROS 2 / Simulation\n/odom · /imu · /camera"]

    subgraph Ingestion ["Ingestion Layer"]
        RI["ROS Interface\n(async subscriber)"]
        BUFF["In-memory Buffer\n(Data Collector)"]
        ANON["Anonymization Module\n(OpenCV · camera only)"]
    end

    subgraph Analysis ["Analysis Layer"]
        QE["Quality Evaluator\n(Orchestrator)"]
        KB["Knowledge Base\n(sensor norms · reference trajectories)"]
        LLM["LLM API\n(sanitized prompt → annotation)"]
    end

    subgraph Storage ["Storage Layer"]
        STORE["Local FS / MinIO\nbag files · raw data"]
        MH["Memory Hub\n(SQLite)\nepisodes · reports · metadata"]
    end

    subgraph Observability ["Observability Layer"]
        PROM["Prometheus Client\n(metrics)"]
        GRAF["Grafana / Plotly Dash\n(dashboard)"]
        LOG["Structured Logs\n(local · hashed IDs)"]
    end

    ENG["ML Engineer\n(approve / reject)"]
    API["Monitoring API\n(FastAPI · read-only)"]

    %% Ingestion flow
    ROS -->|raw ROS messages| RI
    RI -->|Python objects| BUFF
    BUFF -->|camera frames only| ANON
    ANON -->|anonymized frames| BUFF
    BUFF -->|CRC-validated episode| QE
    BUFF -->|bag files + CRC hash| STORE

    %% Analysis flow
    KB -->|norm rules| QE
    QE <-->|sanitized prompt / annotation| LLM
    QE -->|QA report + metadata| MH

    %% Human loop
    MH -->|report notification| ENG
    ENG -->|approve / reject| MH
    MH -->|versioned dataset metadata| STORE

    %% Observability
    MH -->|episode counters| PROM
    QE -->|latency · LLM metrics| PROM
    BUFF -->|buffer size · CRC failures| PROM
    PROM -->|metrics export| GRAF
    QE -->|structured events| LOG
    BUFF -->|CRC events| LOG

    %% API
    MH -->|reports · metadata| API
    API -->|REST responses| ENG

    %% Styling
    style ANON fill:#ffe4b5,stroke:#d4a800
    style LLM fill:#fff3cd,stroke:#c9a800
    style MH fill:#d4edda,stroke:#28a745
    style STORE fill:#f8d7da,stroke:#dc3545
    style QE fill:#cce5ff,stroke:#004085
    style ENG fill:#e2e3e5,stroke:#383d41
```

## Что хранится и где

| Данные | Хранилище | Формат | Содержит PII? |
|--------|-----------|--------|---------------|
| Bag-файлы эпизодов | Local FS / MinIO | Binary / ROS bag | Нет (после анонимизации) |
| CRC-хэши файлов | SQLite `episodes` | TEXT | Нет |
| QA-отчёты | SQLite `reports` + JSON | JSON | Нет |
| Метаданные эпизодов | SQLite `episodes` | Табличные | Нет |
| Нормы сенсоров | SQLite / JSON | JSON | Нет |
| Prometheus-метрики | In-memory / endpoint | Text (OpenMetrics) | Нет |
| Структурированные логи | Local FS | JSON lines | ID хэшированы |

## Что никогда не покидает sandbox

- Сырые camera-кадры до анонимизации — не передаются в LLM, не логируются.
- Идентификаторы пользователей — хэшируются SHA-256 перед сохранением.
- API-ключи — только в `.env`; не логируются, не попадают в отчёты.
- Данные эпизодов — не уходят в публичное облако в PoC.

## Что логируется

| Событие | Уровень | Содержимое |
|---------|---------|-----------|
| Старт/стоп сессии | INFO | session_id (хэш), timestamp |
| Получение эпизода | INFO | episode_id, topics, duration |
| CRC fail | WARNING | episode_id, retry count |
| Результат QA | INFO | episode_id, status, quality_score |
| LLM fallback | WARNING | episode_id, reason |
| Prompt injection detected | ERROR | sanitizer rule matched (без payload) |
| Disk quota warning | WARNING | current_usage_gb |
