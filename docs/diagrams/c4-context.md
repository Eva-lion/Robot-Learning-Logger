# C4 Context — Robot Learning Logger

Показывает систему в целом: пользователи, внешние сервисы и границы.

```mermaid
C4Context
    title C4 Context — Robot Learning Logger

    Person(ml_eng, "ML Engineer", "Запускает сбор данных.<br/>Просматривает QA-отчёты.<br/>Подтверждает изменения датасета.")

    System(rll, "Robot Learning Logger", "Автоматизирует сбор и оценку качества обучающих данных робота. Агент анализирует данные и формирует QA-отчёты.")

    System_Ext(ros, "ROS 2 / Simulation", "Gazebo / Webots / ROS bag. Публикует топики /odom, /imu, /camera.")
    System_Ext(llm, "LLM API", "OpenAI / Anthropic / Llama.cpp local. Генерирует аннотации и QA-отчёты.")
    System_Ext(storage, "Object Storage", "MinIO / Local FS. Долгосрочное хранение bag-файлов и QA-отчётов.")
    System_Ext(grafana, "Grafana / Plotly Dash", "Визуализация метрик качества данных.")

    Rel(ml_eng, rll, "Конфигурирует, просматривает отчёты, подтверждает изменения")
    Rel(rll, ros, "Подписывается (read-only)", "/odom /imu /camera")
    Rel(rll, llm, "Отправляет санитизированные запросы на аннотацию")
    Rel(rll, storage, "Сохраняет bag-файлы и QA-отчёты")
    Rel(rll, grafana, "Экспортирует Prometheus-метрики")
```

## Границы

| Граница | Описание |
|---------|---------|
| Система | Robot Learning Logger — всё, что запускается локально |
| Пользователь | Один ML Engineer на PoC; роль: оператор и ревьюер |
| Внешние сервисы | ROS (симулятор), LLM API, хранилище, дашборд |
| Не входит в PoC | Реальный робот, облачное хранение, внешний CI/CD |
