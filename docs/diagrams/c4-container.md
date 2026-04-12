# C4 Container — Robot Learning Logger

Показывает контейнеры внутри системы: процессы, хранилища, их ответственность и взаимодействие.

```mermaid
C4Container
    title C4 Container — Robot Learning Logger

    Person(ml_eng, "ML Engineer")

    System_Ext(ros, "ROS 2 / Simulation")
    System_Ext(llm, "LLM API")
    System_Ext(storage, "Object Storage (FS / MinIO)")
    System_Ext(grafana, "Grafana / Plotly Dash")

    System_Boundary(rll, "Robot Learning Logger") {
        Container(ros_if, "ROS Interface", "Python / rclpy", "Подписка на ROS-топики. Преобразует ROS-сообщения в Python-объекты.")
        Container(collector, "Data Collector", "Python", "Буферизация входящих данных. CRC-валидация. Сохранение эпизодов на диск.")
        Container(anon, "Anonymization Module", "Python / OpenCV", "Детекция лиц в camera-кадрах. Замыливание или обрезка перед анализом.")
        Container(evaluator, "Quality Evaluator", "Python", "Оркестратор QA-цикла: эвристики → LLM → QA-отчёт.")
        Container(kb, "Knowledge Base", "SQLite / JSON", "Эталонные нормы сенсоров. Reference-траектории (RoboNet / IsaacGym).")
        Container(memory, "Memory Hub", "SQLite", "Сессионное состояние. Метаданные эпизодов. QA-отчёты.")
        Container(api, "Monitoring API", "FastAPI", "REST read-only: метрики, отчёты, health check.")
        Container(prom, "Prometheus Client", "Python lib", "Сбор и экспорт внутренних метрик системы.")
    }

    Rel(ros, ros_if, "ROS messages (async)", "/odom /imu /camera")
    Rel(ros_if, collector, "Raw data objects")
    Rel(collector, anon, "Camera frames only")
    Rel(anon, collector, "Anonymized frames")
    Rel(collector, evaluator, "Validated episode trigger")
    Rel(collector, storage, "Persist bag files")
    Rel(evaluator, kb, "Lookup sensor norms")
    Rel(evaluator, llm, "Sanitized annotation request")
    Rel(evaluator, memory, "Save QA report + metadata")
    Rel(memory, api, "Query reports & episode metadata")
    Rel(api, ml_eng, "REST responses (reports, metrics)")
    Rel(ml_eng, api, "HTTP GET")
    Rel(ml_eng, memory, "approve / reject episode")
    Rel(prom, grafana, "Metrics scrape / export")
    Rel(prom, memory, "Scrape episode counters")
    Rel(prom, evaluator, "Scrape latency, LLM metrics")
    Rel(prom, collector, "Scrape buffer, CRC metrics")
```

## Ответственность контейнеров

| Контейнер | Читает | Пишет |
|-----------|--------|-------|
| ROS Interface | ROS topics | In-memory buffer |
| Data Collector | ROS Interface buffer | Local FS / MinIO, Memory Hub (metadata) |
| Anonymization Module | Camera frames | Anonymized frames (in-memory) |
| Quality Evaluator | Knowledge Base, LLM API | Memory Hub (reports) |
| Knowledge Base | JSON / SQLite (static) | — |
| Memory Hub | — | SQLite (episodes, reports) |
| Monitoring API | Memory Hub | — |
| Prometheus Client | Internal counters | Metrics endpoint |
