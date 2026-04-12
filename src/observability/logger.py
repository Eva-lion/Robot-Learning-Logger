"""Структурированное JSON-логирование с ротацией."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

from src import config

_LOG_LEVEL = config.get("observability", "log_level", "INFO")
_LOG_FORMAT = config.get("observability", "log_format", "json")
_LOG_FILE = config.get("observability", "log_file", "logs/rll.log")
_LOG_MAX_BYTES = config.get("observability", "log_max_bytes", 52_428_800)
_LOG_BACKUP_COUNT = config.get("observability", "log_backup_count", 3)

_configured = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                base[key] = value
        return json.dumps(base, ensure_ascii=False, default=str)


def _configure() -> None:
    global _configured
    if _configured:
        return

    level = getattr(logging, _LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger("src")
    root.setLevel(level)
    root.propagate = False

    if _LOG_FORMAT == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = Path(_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_path),
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)
