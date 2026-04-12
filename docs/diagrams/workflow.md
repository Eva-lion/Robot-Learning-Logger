# Workflow Diagram — Robot Learning Logger

Пошаговое выполнение запроса, включая ветки ошибок.

```mermaid
sequenceDiagram
    participant ROS as ROS 2 / Simulation
    participant RI as ROS Interface
    participant DC as Data Collector
    participant AN as Anonymization Module
    participant QE as Quality Evaluator
    participant KB as Knowledge Base
    participant LLM as LLM API
    participant MH as Memory Hub
    participant Eng as ML Engineer

    ROS->>RI: Publish /odom, /imu, /camera (async)
    RI->>DC: Raw episode data objects

    DC->>DC: CRC / hash validation

    alt CRC fail
        DC->>MH: Log failure, mark episode REJECTED
        DC->>Eng: Alert (log + metric)
    else CRC ok
        DC->>AN: Camera frames only
        AN->>AN: Face detection (OpenCV)
        AN->>DC: Anonymized frames (blurred)

        DC->>QE: Trigger QA — validated episode

        QE->>KB: Get sensor norms (topic, field)
        KB-->>QE: Norm rules (min, max, max_std, max_gap_ms)

        QE->>QE: Heuristic analysis

        alt Heuristic hard fail
            QE->>MH: Save REJECTED report (no LLM call)
        else Heuristic pass or soft warn
            QE->>QE: Sanitize episode context
            QE->>LLM: POST annotation request (sanitized)

            alt LLM success
                LLM-->>QE: {annotation, confidence, anomalies, flags}
                QE->>QE: Validate response schema + confidence
                alt confidence < 0.7
                    QE->>QE: Flag NEEDS_REVIEW
                end
            else LLM timeout / error
                QE->>QE: Fallback — heuristic-only report
                QE->>QE: Flag LLM_UNAVAILABLE
            end

            QE->>MH: Save QA report (heuristic + LLM)
            MH->>Eng: Notify: report ready (link)

            Eng->>MH: approve / reject

            alt Approved
                MH->>MH: Increment version, mark APPROVED
                MH->>DC: Trigger dataset versioning
            else Rejected
                MH->>MH: Mark REJECTED
            end
        end
    end
```

## Состояния эпизода

```
PENDING → (CRC fail)    → REJECTED
PENDING → (heuristic hard fail) → REJECTED
PENDING → (QA complete, human)  → APPROVED
PENDING → (low confidence / LLM unavailable) → NEEDS_REVIEW
NEEDS_REVIEW → (human decision) → APPROVED | REJECTED
```

## Ветки ошибок

| Ветка | Триггер | Результат |
|-------|---------|-----------|
| CRC fail | Hash mismatch при записи | REJECTED, retry × 1, alert |
| ROS disconnect | Heartbeat timeout 5 с | Retry × 3; буфер сохраняется на диск |
| LLM timeout | >30 с без ответа | Fallback: heuristic-only; flag LLM_UNAVAILABLE |
| LLM rate limit | HTTP 429 | Exponential backoff 1→2→4 с |
| Low confidence | `confidence < 0.7` | Flag NEEDS_REVIEW; manual review required |
| Human timeout | Нет ответа за 24 ч | Автоматически → NEEDS_REVIEW |
