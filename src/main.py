"""Entry point: python -m src.main [--mode=live|offline] [--input=<path>]"""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from src import __version__
from src.observability.logger import get_logger

logger = get_logger(__name__)

_shutdown_event = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("Shutdown signal received", extra={"event": "shutdown_requested", "signal": signum})
    _shutdown_event.set()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description=f"Robot Learning Logger v{__version__}",
    )
    parser.add_argument(
        "--mode",
        choices=["live", "offline"],
        default="live",
        help="live = подключение к ROS; offline = анализ готового файла",
    )
    parser.add_argument(
        "--input",
        metavar="PATH",
        help="Путь к JSON-файлу эпизода (только для --mode=offline)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


def _run_offline(input_path: str) -> None:
    import json
    from pathlib import Path

    from src.memory_hub.db import init_db
    from src.knowledge_base.loader import NormsCache
    from src.quality_evaluator.orchestrator import Orchestrator
    from src.models import EpisodeInput, TopicStats

    init_db()
    norms = NormsCache()
    norms.load()
    orchestrator = Orchestrator(norms)

    raw = json.loads(Path(input_path).read_text())
    stats = [TopicStats(**s) for s in raw.get("stats", [])]
    episode = EpisodeInput(
        episode_id=raw["episode_id"],
        session_id=raw.get("session_id", "offline"),
        started_at=raw["started_at"],
        ended_at=raw["ended_at"],
        topics=raw.get("topics", []),
        stats=stats,
        frame_count=raw.get("frame_count", 0),
        scenario=raw.get("scenario"),
    )
    report = orchestrator.analyze_episode(episode)
    logger.info(
        "Offline analysis complete",
        extra={
            "event": "offline_complete",
            "episode_id": episode.episode_id,
            "verdict": report.verdict,
            "status": report.status,
        },
    )
    print(f"\nVERDICT: {report.verdict}  |  STATUS: {report.status}")
    print(f"Annotation: {report.annotation}")
    if report.anomalies:
        print("Anomalies:")
        for a in report.anomalies:
            print(f"  - {a}")


def _run_live() -> None:
    import threading

    from src.memory_hub.db import init_db
    from src.knowledge_base.loader import NormsCache
    from src.quality_evaluator.orchestrator import Orchestrator
    from src.data_collector.collector import DataCollector
    from src.ros_interface.subscriber import ROSSubscriber
    from src.api.app import create_app
    import uvicorn

    init_db()
    norms = NormsCache()
    norms.load()
    orchestrator = Orchestrator(norms)
    collector = DataCollector(orchestrator)

    app = create_app()
    from src import config
    api_cfg = config.get("api")
    api_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": app,
            "host": api_cfg.get("host", "127.0.0.1"),
            "port": api_cfg.get("port", 8000),
            "log_level": "warning",
        },
        daemon=True,
    )
    api_thread.start()
    logger.info("Monitoring API started", extra={"event": "api_started"})

    ros = ROSSubscriber(collector)
    ros.connect()
    logger.info("ROS subscriber connected", extra={"event": "ros_connected"})

    _shutdown_event.wait()

    logger.info("Graceful shutdown started", extra={"event": "shutdown_start"})
    ros.disconnect()
    collector.flush()
    logger.info("Shutdown complete", extra={"event": "shutdown_complete"})


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = _parse_args()

    if args.mode == "offline":
        if not args.input:
            print("Error: --input is required for offline mode", file=sys.stderr)
            sys.exit(1)
        _run_offline(args.input)
    else:
        _run_live()


if __name__ == "__main__":
    main()
