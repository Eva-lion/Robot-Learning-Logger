# C4 Component — Quality Evaluator

Показывает внутреннее устройство ядра системы: компоненты оркестратора и их взаимодействие.

```mermaid
C4Component
    title C4 Component — Quality Evaluator (Orchestrator)

    System_Ext(kb, "Knowledge Base", "Нормы сенсоров")
    System_Ext(llm_api, "LLM API", "OpenAI / Anthropic / local")
    System_Ext(memory, "Memory Hub", "SQLite")
    System_Ext(ml_eng, "ML Engineer", "Человек-ревьюер")

    Container_Boundary(evaluator, "Quality Evaluator") {
        Component(orch, "Orchestrator Loop", "Python", "Управляет последовательностью шагов, retry-логикой и stop condition.")
        Component(heuristic, "Heuristic Analyzer", "Python", "Проверяет диапазоны сенсоров, временные разрывы, выбросы по std_dev.")
        Component(sanitizer, "Input Sanitizer", "Python", "Фильтрует FS/exec-команды и prompt injection перед LLM-вызовом.")
        Component(llm_caller, "LLM Caller", "Python / openai", "Формирует промпт, вызывает LLM API, парсит и валидирует ответ.")
        Component(report, "Report Builder", "Python", "Агрегирует результаты эвристик и LLM в структурированный QA-отчёт.")
        Component(gateway, "Human Gateway", "Python", "Уведомляет ML Engineer, ожидает approve/reject, обновляет статус.")
    }

    Rel(orch, heuristic, "1. Run heuristic checks")
    Rel(heuristic, kb, "Lookup sensor norms by topic/field")
    Rel(orch, sanitizer, "2. Pass episode context (if heuristic pass/warn)")
    Rel(sanitizer, llm_caller, "Sanitized prompt")
    Rel(llm_caller, llm_api, "POST /chat/completions")
    Rel(llm_api, llm_caller, "Annotation + confidence JSON")
    Rel(llm_caller, orch, "Parsed annotation result")
    Rel(orch, report, "3. Aggregate heuristic + LLM results")
    Rel(report, memory, "4. Save QA report")
    Rel(report, gateway, "5. Trigger human review")
    Rel(gateway, ml_eng, "Notification + report link")
    Rel(ml_eng, gateway, "approve / reject")
    Rel(gateway, memory, "6. Update episode status")
```

## Ответственность компонентов

| Компонент | Что делает | Чего не делает |
|-----------|-----------|----------------|
| Orchestrator Loop | Управляет шагами, retry, timeout | Не пишет данные напрямую |
| Heuristic Analyzer | Threshold-проверки, outlier detection | Не вызывает LLM |
| Input Sanitizer | Блок-лист команд, escape | Не изменяет смысл данных |
| LLM Caller | Формирует промпт, парсит ответ | Не выполняет function calling |
| Report Builder | Структурирует отчёт | Не принимает решения, только агрегирует |
| Human Gateway | Уведомление, ожидание approval | Не auto-approve |

## Стратегия fallback

```
Heuristic OK → LLM Caller
                ├── success → Report с LLM annotation
                └── error / timeout → Report с heuristic-only
                                      (флаг: LLM_UNAVAILABLE)
```
