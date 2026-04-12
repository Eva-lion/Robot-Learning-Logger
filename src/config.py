"""Загрузка конфигурации из config.yaml и .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _ROOT / "config.yaml"

_cfg: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    global _cfg
    if _cfg:
        return _cfg
    with open(_CONFIG_PATH) as f:
        _cfg = yaml.safe_load(f)
    return _cfg


def get(section: str, key: str | None = None, default: Any = None) -> Any:  # noqa: ANN401
    cfg = _load()
    section_data = cfg.get(section, {})
    if key is None:
        return section_data
    return section_data.get(key, default)


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Required environment variable '{name}' is not set.")
    return value
