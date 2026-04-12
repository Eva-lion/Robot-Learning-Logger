# Robot Learning Logger

### Что за задача

Robot Learning Logger — это агентная система, автоматизирующая сбор и верификацию данных, используемых для обучения робототехнических моделей (reinforcement learning, imitation learning).  
Основная цель — повысить качество датасетов и снизить долю ручных проверок данных с сенсоров.

### Для кого и какая боль сейчас

- **Лаборатории робототехники**, которые тренируют модели управления, регулярно сталкиваются с проблемой «грязных» данных: сбои сенсоров, разрывы синхронизации, видео с неполными фреймами.
- **Индустрия** (R&D-отделы, стартапы): подготовка и аннотация логов занимает до 30–60 % времени цикла разработки.
- **Боль:** контроль качества данных осуществляется вручную или скриптами, не способными адаптироваться к новым сценариям.

### Что сделает PoC (на демо)

На демо система:

1. Подключается к ROS‑симуляции (Gazebo/Webots/TurtleBot).
2. Автоматически собирает сенсорные логи (IMU, Odom, Camera).
3. Агент‑анализатор оценивает собранные данные:
   - выявляет ошибки (разрывы последовательностей, шум, пропуски);
   - делает краткую текстовую аннотацию.
4. Формируется отчёт о качестве данных и версия датасета.

### Что НЕ делает PoC (out‑of‑scope)

Обучение нейронных сетей на собранных данных.  
Управление физическим роботом.  
Глубокая визуальная обработка (OpenCV segmentation, SLAM).  
Многоагентные сценарии — только одиночный робот и симуляция.

---

## Быстрый старт

### Требования

- Python 3.11+
- (опционально) ROS 2 + `roslibpy` или `rclpy`

### Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Запуск тестов

```bash
pytest tests/ -v
```

### Offline-анализ готового эпизода

```bash
python -m src.main --mode=offline --input=tests/fixtures/episodes/bad_episode.json
```

### Live-режим (с ROS)

```bash
# Запустить rosbridge (ROS 2):
ros2 launch rosbridge_server rosbridge_websocket_launch.xml

# Запустить систему:
python -m src.main --mode=live
```

Monitoring API: `http://localhost:8000/docs`  
Prometheus: `http://localhost:8001/metrics`  
Dashboard: `python -m src.dashboard.app` → `http://localhost:8050`

---

## Структура проекта

```
src/
  main.py                  — точка входа
  config.py                — загрузка config.yaml и .env
  models.py                — общие типы данных
  ros_interface/           — подписка на ROS-топики
  data_collector/          — буферизация, CRC, запись эпизодов
  anonymization/           — замыливание лиц в camera-фреймах
  knowledge_base/          — загрузка норм сенсоров в memory cache
  quality_evaluator/
    heuristics.py          — быстрый первый фильтр без LLM
    sanitizer.py           — защита от prompt injection
    llm_caller.py          — вызов LLM API с retry/fallback/cache
    report_builder.py      — формирование QA-отчёта
    orchestrator.py        — центральный пайплайн
  memory_hub/
    db.py                  — SQLite CRUD
    writer.py              — сохранение эпизодов и отчётов
  api/app.py               — FastAPI Monitoring API
  dashboard/app.py         — Plotly Dash дашборд
  observability/
    metrics.py             — Prometheus метрики
    logger.py              — JSON-логирование с ротацией
data/
  norms.json               — нормы сенсоров
  reference_trajectories.json
tests/                     — 32 unit/integration/API теста
docs/                      — архитектурные документы, диаграммы, спеки
```

---